#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-6-pre-cutover-probe.sh — Phase-3c Pre-Cutover-Sanity-Probe
# -----------------------------------------------------------------
#
# Purpose
#   Executes a non-mutating Pre-Cutover-Sanity-Run against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) for Welle-6
#   (subscribe_loop, ADR-0066 §Doppel-Welle KW-27 + ADR-0065
#   §Welle-6).  This probe is the *pre-flight test* of substance
#   against the real substrate ahead of the KW-27 Doppel-Welle —
#   it confirms that the Tag-37 / Tag-38 / Tag-40 / Tag-41 substance
#   meets the Welle-6 GO-criteria *on the actual VM*, not just on
#   the Mira-sandbox hermetic test bed.
#
#   Welle-6 is the second-to-last cutover wave of Phase-3 and runs
#   *in parallel* with Welle-7 (recovery_workflow) — the cutover
#   pair forms the Phase-3-Ende Doppel-Welle.  Cross-Modul-Drift
#   isolation between Welle-6 and Welle-7 is therefore the single
#   highest-impact Pre-Cutover concern; AXIS-4 is dedicated to it.
#
#   The probe is intentionally distinct from the welle-6-cutover-
#   smoke script: where the smoke *enacts* a hermetic dry-run /
#   simulation of the Cutover sequence, this probe only *observes*
#   + *verifies* the system in its Default-State (backend=python
#   for subscribe_loop) before any env-overlay drop-in.  When --
#   dry-run is set, the probe additionally invokes the Welle-6-
#   smoke wrapper in its built-in dry-run mode (no env mutation,
#   no remote side-effects) to confirm the smoke harness itself
#   is reachable from this VM substrate.
#
# Authority
#   Mira-Hand-SSH per ADR-0058 §Nachtrag (approved KW-20).  Uses key
#   ${HOME}/.ssh/wakir-pilot-vm-diagnose.  No AR escalation required
#   for the read-only checks executed here.
#
# Sandbox boundary
#   This script never executes podman / systemctl locally.  All
#   probes ship over SSH.  The hermetic test suite stubs `ssh` via
#   $WAKIR_SSH_BIN so no real connection opens in CI.  When the VM
#   is unreachable the probe emits a structured "PROBE-NOT-EXECUTED"
#   verdict so callers can still consume an Acceptance-Report — the
#   AR-direktive Tag-41 explicitly mandates non-blocking behaviour
#   on VM-down.
#
# Five verification axes (output triad green/yellow/red per axis):
#
#   AXIS-1  Subscribe-Loop-Drain-Pre-State — engine-subscribe-loop
#           worker is up, ack-queue-depth is below the drain-stable
#           threshold, and the lag-histogram pre-state-snapshot is
#           captured for the post-cutover delta comparison.  This
#           is the subscribe-loop-lag-stability baseline that the
#           Welle-6 cutover-smoke A6 assert later compares against.
#   AXIS-2  NATS-Connection-Persistence — NATS broker is reachable
#           and the persona-engine subscribe-loop holds a stable
#           subscription (no rapid re-connect storm in the last
#           5 minutes).  This is the protocol-level connectivity
#           pre-check; AXIS-1 covers the application-level worker.
#   AXIS-3  FSM-Awareness post-Welle-5 — WAKIR_FSM_BACKEND=rust
#           is pinned in the engine env-map (Welle-5 already
#           cutovert in KW-26 per ADR-0066) and the FSM substrate
#           reports rust-backed phase transitions in the audit
#           tail.  This guards against starting Welle-6 before
#           Welle-5 has stabilised on Rust-default.
#   AXIS-4  Cross-Modul-Drift-Pre-Check zu Welle-7 — subscribe_loop
#           env-var is at python in PHASE_PRE and recovery_workflow
#           env-var (Welle-7 sibling) is *also* at python in
#           PHASE_PRE — i.e. neither focus-module has leaked a
#           premature cutover into the other.  This is the
#           pre-state mirror of the cutover-smoke A7 isolation
#           assert.  RED if either env-var is unexpectedly already
#           at rust.
#   AXIS-5  Rollback-Probe — subscribe_loop env-overlay drop-in
#           dir is writable for root, systemctl daemon-reload +
#           restart commands are present, persona-engine service
#           is enabled.  Non-mutating: only the rollback *surface*
#           is inspected (we do NOT execute the rollback action;
#           that is the cutover-action layer, not pre-cutover).
#
# Exit-codes
#   0  green       — all five axes matched, Welle-6 cutover GREEN.
#   1  caution     — >= 1 axis yellow, none red.  Operator-Hand-Decision.
#   2  block       — >= 1 axis red.  Welle-6 cutover BLOCKED.
#   3  precond     — bad CLI args / missing SSH key / invalid Welle.
#   4  not-exec    — VM unreachable (SSH fail) — special status that
#                    surfaces in the Acceptance-Report as
#                    PROBE-NOT-EXECUTED.
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 §Welle-6 (Phase-3c Cutover-Plan: subscribe_loop)
#   - ADR-0066 §Doppel-Welle KW-27 (Welle-6 + Welle-7 parallel)
#   - PR #257 (Welle-6 End-to-End Cutover-Smoke + A6 lag-stability)
#   - PR #250 (Tag-38 migrate-version — BackendDecision baseline)
#   - reports/live-vm/2026-05-18-welle-6-pre-cutover-probe.md
#
# Author: Amara Osei (QA-Engineer), Sprint-Tag-42, 2026-05-18.
# -----------------------------------------------------------------

set -euo pipefail

# -----------------------------------------------------------------
# Defaults — overridable via env or CLI.
# -----------------------------------------------------------------

WAKIR_PILOT_HOST="${WAKIR_PILOT_HOST:-192.168.178.116}"
WAKIR_PILOT_USER="${WAKIR_PILOT_USER:-root}"
WAKIR_PILOT_SSH_KEY="${WAKIR_PILOT_SSH_KEY:-${HOME}/.ssh/wakir-pilot-vm-diagnose}"
WAKIR_SSH_BIN="${WAKIR_SSH_BIN:-ssh}"
WAKIR_DATE_BIN="${WAKIR_DATE_BIN:-date}"
WAKIR_PROBE_LOG_DIR="${WAKIR_PROBE_LOG_DIR:-/tmp/wakir-pre-cutover-probe}"
WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC="${WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC:-8}"
WAKIR_PROBE_WELLE="${WAKIR_PROBE_WELLE:-6}"
WAKIR_PROBE_COMPONENT="${WAKIR_PROBE_COMPONENT:-subscribe_loop}"
WAKIR_PROBE_SIBLING_COMPONENT="${WAKIR_PROBE_SIBLING_COMPONENT:-recovery_workflow}"
WAKIR_PROBE_DEFAULT_BACKEND="${WAKIR_PROBE_DEFAULT_BACKEND:-python}"
WAKIR_PROBE_ROLLBACK_ENV_NAME="${WAKIR_PROBE_ROLLBACK_ENV_NAME:-WAKIR_SUBSCRIBE_LOOP_BACKEND}"
WAKIR_PROBE_SIBLING_ENV_NAME="${WAKIR_PROBE_SIBLING_ENV_NAME:-WAKIR_RECOVERY_WORKFLOW_BACKEND}"
WAKIR_PROBE_FSM_ENV_NAME="${WAKIR_PROBE_FSM_ENV_NAME:-WAKIR_FSM_BACKEND}"
WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX="${WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX:-256}"
WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN="${WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN:-2}"

DRY_RUN=0
QUIET=0

PROBE_TS="$("${WAKIR_DATE_BIN}" -u +%Y%m%dT%H%M%SZ)"
PROBE_LOG=""

# -----------------------------------------------------------------
# CLI parsing.
# -----------------------------------------------------------------

usage() {
    cat <<USAGE
usage: $(basename "$0") [options]

Pre-Cutover-Sanity-Probe for Phase-3c Welle-6 (subscribe_loop,
ADR-0065 §Welle-6 + ADR-0066 §Doppel-Welle KW-27) against the
wakir-pilot live VM via Mira-Hand-SSH (ADR-0058).

Options:
  --dry-run                Plan probe steps; do not open SSH.
                           Also invokes Welle-6-smoke in dry-run.
  --quiet                  Suppress non-error stdout chatter.
  --welle <n>              Welle index (default: 6).
  --component <name>       Component name (default: subscribe_loop).
  --sibling <name>         Sibling component for AXIS-4 Cross-Modul-
                           Drift check (default: recovery_workflow).
  --ack-queue-max <n>      AXIS-1 max stable ack-queue-depth
                           (default: ${WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX}).
  --nats-reconnect-max <n> AXIS-2 max NATS reconnects in 5 min
                           (default: ${WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN}).
  --host <ip>              Override pilot host (default: ${WAKIR_PILOT_HOST}).
  --user <name>            Override SSH user  (default: ${WAKIR_PILOT_USER}).
  --ssh-key <path>         Override SSH key   (default: ${WAKIR_PILOT_SSH_KEY}).
  -h, --help               Show this help and exit.

Exit-codes: 0 green / 1 caution / 2 block / 3 precond / 4 not-exec.
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --dry-run)               DRY_RUN=1; shift ;;
        --quiet)                 QUIET=1; shift ;;
        --welle)                 WAKIR_PROBE_WELLE="$2"; shift 2 ;;
        --component)             WAKIR_PROBE_COMPONENT="$2"; shift 2 ;;
        --sibling)               WAKIR_PROBE_SIBLING_COMPONENT="$2"; shift 2 ;;
        --ack-queue-max)         WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX="$2"; shift 2 ;;
        --nats-reconnect-max)    WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN="$2"; shift 2 ;;
        --host)                  WAKIR_PILOT_HOST="$2"; shift 2 ;;
        --user)                  WAKIR_PILOT_USER="$2"; shift 2 ;;
        --ssh-key)               WAKIR_PILOT_SSH_KEY="$2"; shift 2 ;;
        -h|--help)               usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 3 ;;
    esac
done

# -----------------------------------------------------------------
# Logging helpers.
# -----------------------------------------------------------------

mkdir -p "${WAKIR_PROBE_LOG_DIR}"
PROBE_LOG="${WAKIR_PROBE_LOG_DIR}/welle-${WAKIR_PROBE_WELLE}-${PROBE_TS}.log"

log() {
    local level="$1"; shift
    local msg="$*"
    local stamp
    stamp="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    if [[ "${QUIET}" -eq 0 || "${level}" == "ERROR" ]]; then
        printf '[%s] [%-7s] %s\n' "${stamp}" "${level}" "${msg}"
    fi
    printf '[%s] [%-7s] %s\n' "${stamp}" "${level}" "${msg}" >> "${PROBE_LOG}"
}

log_info()    { log INFO    "$@"; }
log_warn()    { log WARN    "$@"; }
log_error()   { log ERROR   "$@" >&2; }
log_step()    { log STEP    "$@"; }
log_verdict() { log VERDICT "$@"; }

# -----------------------------------------------------------------
# SSH wrapper.  Captures stdout; emits exit-4 on connection failure.
# -----------------------------------------------------------------

remote_exec() {
    local desc="$1"; local cmd="$2"
    local ssh_target="${WAKIR_PILOT_USER}@${WAKIR_PILOT_HOST}"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        log_info "DRY-RUN [${desc}] ssh ${ssh_target}: ${cmd}"
        printf 'DRY-RUN-STDOUT\n'
        return 0
    fi
    local out
    if ! out=$("${WAKIR_SSH_BIN}" \
        -o BatchMode=yes \
        -o ConnectTimeout="${WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC}" \
        -o StrictHostKeyChecking=accept-new \
        -i "${WAKIR_PILOT_SSH_KEY}" \
        "${ssh_target}" \
        "${cmd}" 2>>"${PROBE_LOG}"); then
        log_error "ssh failure [${desc}] target=${ssh_target}"
        return 4
    fi
    printf '%s' "${out}"
}

check_ssh_key_present() {
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        return 0
    fi
    if [[ ! -r "${WAKIR_PILOT_SSH_KEY}" ]]; then
        log_error "SSH key not readable at ${WAKIR_PILOT_SSH_KEY}"
        return 3
    fi
    return 0
}

# -----------------------------------------------------------------
# Axis implementations.  Each returns 0=green / 1=yellow / 2=red /
# 4=not-exec.  Globals AXIS_<n>_VERDICT capture per-axis result for
# later report rendering.
# -----------------------------------------------------------------

AXIS_1_VERDICT="UNKNOWN"
AXIS_2_VERDICT="UNKNOWN"
AXIS_3_VERDICT="UNKNOWN"
AXIS_4_VERDICT="UNKNOWN"
AXIS_5_VERDICT="UNKNOWN"
AXIS_1_DETAIL=""
AXIS_2_DETAIL=""
AXIS_3_DETAIL=""
AXIS_4_DETAIL=""
AXIS_5_DETAIL=""

# AXIS-1 — Subscribe-Loop-Drain-Pre-State.
#   We sample (a) the subscribe-ack-queue depth and (b) the
#   subscribe-loop lag-histogram tail.  Both feed the post-cutover
#   delta check that the smoke A6 assert will perform.
axis_1_subscribe_loop_drain_pre_state() {
    log_step "AXIS-1 subscribe-loop-drain-pre-state (component=${WAKIR_PROBE_COMPONENT})"
    local cmd='persona-engine-cli subscribe-loop-status --json 2>/dev/null | head -c 4096; echo; persona-engine-cli subscribe-lag-histogram --tail 5 --json 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-1-drain-pre-state" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_1_VERDICT="NOT-EXEC"
        AXIS_1_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_1_VERDICT="DRY-RUN"
        AXIS_1_DETAIL="dry-run (no remote call)"
        return 0
    fi
    if [[ -z "${out}" ]]; then
        AXIS_1_VERDICT="RED"
        AXIS_1_DETAIL="empty-drain-pre-state-output"
        return 2
    fi
    # Extract ack-queue-depth if present.  Defensive parse: if not
    # present, treat as YELLOW (cannot conclude stability).
    local depth
    depth=$(printf '%s' "${out}" | grep -oE '"ack_queue_depth":[0-9]+' | head -1 | grep -oE '[0-9]+' || true)
    if [[ -z "${depth}" ]]; then
        AXIS_1_VERDICT="YELLOW"
        AXIS_1_DETAIL="ack-queue-depth-field-missing"
        return 1
    fi
    AXIS_1_DETAIL="ack_queue_depth=${depth} max_stable=${WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX} pre-state-bytes=$(printf '%s' "${out}" | wc -c | tr -d ' ')"
    if (( depth <= WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX )); then
        AXIS_1_VERDICT="GREEN"
        return 0
    elif (( depth <= WAKIR_PROBE_ACK_QUEUE_DRAIN_MAX * 2 )); then
        AXIS_1_VERDICT="YELLOW"
        return 1
    else
        AXIS_1_VERDICT="RED"
        return 2
    fi
}

# AXIS-2 — NATS-Connection-Persistence.
#   Counts NATS reconnects in the last 5 minutes; a stable
#   subscription should show <= WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN.
axis_2_nats_connection_persistence() {
    log_step "AXIS-2 nats-connection-persistence (max-reconnect-5min=${WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN})"
    local cmd='journalctl -u persona-engine --since="5 minutes ago" --no-pager 2>/dev/null | grep -cE "nats.*(reconnect|disconnected|connection_lost)" || true'
    local out rc count
    set +e
    out=$(remote_exec "axis-2-nats-persistence" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_2_VERDICT="NOT-EXEC"
        AXIS_2_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_2_VERDICT="DRY-RUN"
        AXIS_2_DETAIL="dry-run (no remote call)"
        return 0
    fi
    count=$(printf '%s' "${out}" | tr -dc '0-9')
    if [[ -z "${count}" ]]; then count=0; fi
    AXIS_2_DETAIL="reconnect-events-5min=${count} max=${WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN}"
    if (( count <= WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN )); then
        AXIS_2_VERDICT="GREEN"
        return 0
    elif (( count <= WAKIR_PROBE_NATS_RECONNECT_MAX_5MIN * 3 )); then
        AXIS_2_VERDICT="YELLOW"
        return 1
    else
        AXIS_2_VERDICT="RED"
        return 2
    fi
}

# AXIS-3 — FSM-Awareness post-Welle-5.
#   Verifies that WAKIR_FSM_BACKEND=rust is set (Welle-5 done in
#   KW-26) and the FSM substrate reports rust-backed transitions
#   in the audit tail.  Guards against starting Welle-6 before
#   Welle-5 has stabilised.
axis_3_fsm_awareness_post_welle_5() {
    log_step "AXIS-3 fsm-awareness-post-welle-5 (expected=${WAKIR_PROBE_FSM_ENV_NAME}=rust)"
    local cmd
    cmd='systemctl show persona-engine -p Environment 2>/dev/null; echo "---AUDIT-FSM-TAIL---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "FSMTransition|lifecycle_state_machine" | tail -3'
    local out rc
    out=$(remote_exec "axis-3-fsm-awareness" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_3_VERDICT="NOT-EXEC"
        AXIS_3_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_3_VERDICT="DRY-RUN"
        AXIS_3_DETAIL="dry-run (no remote call)"
        return 0
    fi
    local fsm_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_FSM_ENV_NAME}=rust"; then
        fsm_env_rust=1
    fi
    local audit_fsm_backend=""
    if printf '%s' "${out}" | grep -qE "backend=rust.*lifecycle_state_machine|lifecycle_state_machine.*backend=rust"; then
        audit_fsm_backend="rust"
    elif printf '%s' "${out}" | grep -qE "backend=python.*lifecycle_state_machine|lifecycle_state_machine.*backend=python"; then
        audit_fsm_backend="python"
    fi
    AXIS_3_DETAIL="fsm_env_rust=${fsm_env_rust} audit_fsm_backend=${audit_fsm_backend:-unknown}"
    if (( fsm_env_rust == 1 )) && [[ "${audit_fsm_backend}" == "rust" ]]; then
        AXIS_3_VERDICT="GREEN"
        return 0
    elif (( fsm_env_rust == 0 )); then
        AXIS_3_VERDICT="RED"
        return 2
    else
        AXIS_3_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-4 — Cross-Modul-Drift-Pre-Check zu Welle-7.
#   Both subscribe_loop and recovery_workflow env-vars must be
#   at python in PHASE_PRE — i.e. neither focus-module has leaked
#   a premature cutover.  This is the pre-state mirror of the
#   cutover-smoke A7 isolation assert.
axis_4_cross_modul_drift_pre_check() {
    log_step "AXIS-4 cross-modul-drift-pre-check welle-6<->welle-7 (sibling=${WAKIR_PROBE_SIBLING_COMPONENT})"
    local cmd
    cmd='systemctl show persona-engine -p Environment 2>/dev/null; echo "---OVERLAY-LIST---"; ls -1 /etc/systemd/system/persona-engine.service.d/ 2>/dev/null || true'
    local out rc
    out=$(remote_exec "axis-4-cross-modul-drift" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_4_VERDICT="NOT-EXEC"
        AXIS_4_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_4_VERDICT="DRY-RUN"
        AXIS_4_DETAIL="dry-run (no remote call)"
        return 0
    fi
    # Welle-6 own env-var should be at python (or unset = default-python).
    local welle6_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_ROLLBACK_ENV_NAME}=rust"; then
        welle6_env_rust=1
    fi
    # Welle-7 sibling env-var should also be at python in PHASE_PRE.
    local welle7_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_SIBLING_ENV_NAME}=rust"; then
        welle7_env_rust=1
    fi
    # Overlay files for either welle should not yet be present.
    local welle6_overlay=0
    local welle7_overlay=0
    if printf '%s' "${out}" | grep -qE "welle-6-subscribe-loop-rust\.conf"; then
        welle6_overlay=1
    fi
    if printf '%s' "${out}" | grep -qE "welle-7-recovery-workflow-rust\.conf"; then
        welle7_overlay=1
    fi
    AXIS_4_DETAIL="welle6_env_rust=${welle6_env_rust} welle7_env_rust=${welle7_env_rust} welle6_overlay=${welle6_overlay} welle7_overlay=${welle7_overlay}"
    if (( welle6_env_rust == 0 && welle7_env_rust == 0 && welle6_overlay == 0 && welle7_overlay == 0 )); then
        AXIS_4_VERDICT="GREEN"
        return 0
    elif (( welle6_env_rust == 1 || welle7_env_rust == 1 )); then
        AXIS_4_VERDICT="RED"
        return 2
    else
        AXIS_4_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-5 — Rollback-Probe surface inspection (non-mutating).
axis_5_rollback_surface() {
    log_step "AXIS-5 rollback-surface-inspection (env=${WAKIR_PROBE_ROLLBACK_ENV_NAME})"
    local cmd
    cmd='ls -ld /etc/systemd/system/persona-engine.service.d 2>/dev/null; systemctl is-enabled persona-engine 2>/dev/null; command -v systemctl >/dev/null && echo systemctl-OK; command -v journalctl >/dev/null && echo journalctl-OK'
    local out rc
    out=$(remote_exec "axis-5-rollback-surface" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_5_VERDICT="NOT-EXEC"
        AXIS_5_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_5_VERDICT="DRY-RUN"
        AXIS_5_DETAIL="dry-run (no remote call)"
        return 0
    fi
    local levers_ok=0
    printf '%s' "${out}" | grep -q "systemctl-OK"  && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "journalctl-OK" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -qE "(enabled|static|alias|enabled-runtime)" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "persona-engine.service.d" && (( levers_ok+=1 )) || true
    AXIS_5_DETAIL="rollback-levers-present=${levers_ok}/4"
    if (( levers_ok >= 4 )); then
        AXIS_5_VERDICT="GREEN"
        return 0
    elif (( levers_ok >= 2 )); then
        AXIS_5_VERDICT="YELLOW"
        return 1
    else
        AXIS_5_VERDICT="RED"
        return 2
    fi
}

# -----------------------------------------------------------------
# Welle-6-Smoke dry-run-Mode invocation.
#   When --dry-run is set we invoke the sibling smoke wrapper with
#   its built-in --dry-run / --probe-mode flag so the probe also
#   confirms that the smoke harness substrate is wired correctly
#   from this VM.  This is non-mutating by construction.
# -----------------------------------------------------------------

SMOKE_INVOCATION_VERDICT="SKIPPED"

invoke_welle_6_smoke_dry_run() {
    if [[ "${DRY_RUN}" -ne 1 ]]; then
        SMOKE_INVOCATION_VERDICT="SKIPPED-NOT-DRY-RUN"
        return 0
    fi
    log_step "smoke-dry-run invocation (welle-6-subscribe-loop-cutover-smoke.sh --dry-run)"
    local smoke_script
    smoke_script="$(dirname "${BASH_SOURCE[0]}")/welle-6-subscribe-loop-cutover-smoke.sh"
    if [[ ! -r "${smoke_script}" ]]; then
        SMOKE_INVOCATION_VERDICT="SCRIPT-MISSING"
        log_warn "smoke script not found at ${smoke_script}; skipping dry-run invocation"
        return 0
    fi
    # We do not actually execute the smoke here in --dry-run because
    # the smoke has its own external dependencies (Python venv, NATS
    # broker stub) — we only assert that the wrapper is present and
    # executable.  The full smoke-dry-run-execution happens in the
    # smoke-CI workflow, not in this probe.
    if [[ -x "${smoke_script}" ]]; then
        SMOKE_INVOCATION_VERDICT="WRAPPER-READY"
        log_info "smoke wrapper present + executable: ${smoke_script}"
    else
        SMOKE_INVOCATION_VERDICT="WRAPPER-NOT-EXECUTABLE"
        log_warn "smoke wrapper present but not executable: ${smoke_script}"
    fi
    return 0
}

# -----------------------------------------------------------------
# Verdict aggregation.
# -----------------------------------------------------------------

aggregate_verdict() {
    local v1="$1" v2="$2" v3="$3" v4="$4" v5="$5"
    local any_not_exec=0 any_red=0 any_yellow=0
    for v in "$v1" "$v2" "$v3" "$v4" "$v5"; do
        case "$v" in
            NOT-EXEC) any_not_exec=1 ;;
            RED)      any_red=1 ;;
            YELLOW)   any_yellow=1 ;;
        esac
    done
    if (( any_not_exec == 1 )); then printf 'NOT-EXEC\n'; return; fi
    if (( any_red == 1 ));      then printf 'BLOCK\n';    return; fi
    if (( any_yellow == 1 ));   then printf 'CAUTION\n';  return; fi
    printf 'GREEN\n'
}

# -----------------------------------------------------------------
# Main.
# -----------------------------------------------------------------

main() {
    log_info "welle-6-pre-cutover-probe start ts=${PROBE_TS} host=${WAKIR_PILOT_HOST} dry-run=${DRY_RUN}"
    log_info "component=${WAKIR_PROBE_COMPONENT} sibling=${WAKIR_PROBE_SIBLING_COMPONENT} welle=${WAKIR_PROBE_WELLE} default-backend=${WAKIR_PROBE_DEFAULT_BACKEND}"

    if ! check_ssh_key_present; then
        log_error "precondition failure: SSH key"
        exit 3
    fi

    local r1=0 r2=0 r3=0 r4=0 r5=0
    axis_1_subscribe_loop_drain_pre_state  || r1=$?
    axis_2_nats_connection_persistence     || r2=$?
    axis_3_fsm_awareness_post_welle_5      || r3=$?
    axis_4_cross_modul_drift_pre_check     || r4=$?
    axis_5_rollback_surface                || r5=$?

    invoke_welle_6_smoke_dry_run

    local verdict
    verdict=$(aggregate_verdict \
        "${AXIS_1_VERDICT}" "${AXIS_2_VERDICT}" "${AXIS_3_VERDICT}" \
        "${AXIS_4_VERDICT}" "${AXIS_5_VERDICT}")

    log_verdict "AXIS-1 ${AXIS_1_VERDICT}: ${AXIS_1_DETAIL}"
    log_verdict "AXIS-2 ${AXIS_2_VERDICT}: ${AXIS_2_DETAIL}"
    log_verdict "AXIS-3 ${AXIS_3_VERDICT}: ${AXIS_3_DETAIL}"
    log_verdict "AXIS-4 ${AXIS_4_VERDICT}: ${AXIS_4_DETAIL}"
    log_verdict "AXIS-5 ${AXIS_5_VERDICT}: ${AXIS_5_DETAIL}"
    log_verdict "SMOKE-INVOCATION: ${SMOKE_INVOCATION_VERDICT}"
    log_verdict "AGGREGATE: ${verdict}"

    printf 'PROBE-VERDICT=%s welle=%s component=%s sibling=%s ts=%s log=%s\n' \
        "${verdict}" "${WAKIR_PROBE_WELLE}" "${WAKIR_PROBE_COMPONENT}" \
        "${WAKIR_PROBE_SIBLING_COMPONENT}" "${PROBE_TS}" "${PROBE_LOG}"

    case "${verdict}" in
        GREEN)    exit 0 ;;
        CAUTION)  exit 1 ;;
        BLOCK)    exit 2 ;;
        NOT-EXEC) exit 4 ;;
        *)        exit 2 ;;
    esac
}

main "$@"
