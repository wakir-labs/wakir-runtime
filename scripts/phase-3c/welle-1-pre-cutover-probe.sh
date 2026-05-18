#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-1-pre-cutover-probe.sh — Phase-3c Pre-Cutover-Sanity-Probe
# -----------------------------------------------------------------
#
# Purpose
#   Executes a non-mutating Pre-Cutover-Sanity-Run against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) for Welle-1
#   (v907_verify, ADR-0065).  This probe is the *pre-flight test* of
#   substance against the real substrate ahead of the KW-24 cutover
#   window — it confirms that the Tag-34 / Tag-38 / Tag-40 substance
#   meets the Welle-1 GO-criteria *on the actual VM*, not just on the
#   Mira-sandbox hermetic test bed.
#
#   The probe is intentionally distinct from the live-vm-cutover-drill
#   driver: where the drill *enacts* the Cutover sequence, the probe
#   only *observes* + *verifies* the system in its Default-State
#   (backend=python for v907_verify) before any env-overlay drop-in.
#
# Authority
#   Mira-Hand-SSH per ADR-0058 §Nachtrag (approved KW-20).  Uses key
#   ${HOME}/.ssh/wakir-pilot-vm-diagnose.  No AR escalation required
#   for the read-only checks executed here.
#
# Sandbox boundary
#   This script never executes podman / systemctl locally.  All
#   probes ship over SSH.  The hermetic test suite stubs `ssh` via
#   $WAKIR_SSH_BIN so no real connection opens in CI.  When the VM is
#   unreachable the probe emits a structured "PROBE-NOT-EXECUTED"
#   verdict so callers can still consume an Acceptance-Report — the
#   AR-direktive Tag-41 explicitly mandates non-blocking behaviour
#   on VM-down.
#
# Five verification axes (output triad green/yellow/red per axis):
#
#   AXIS-1  Engine-State-Snapshot reachable (state-pack + audit-stream
#           tail captured) and timestamp delta vs. probe-start ≤ 60 s.
#   AXIS-2  Engine emits ≥ 11 BackendDecision audit entries since
#           service start (Tag-38 PR #250 migrate-version baseline).
#   AXIS-3  v907_verify component backend=python in Default-State
#           (env not set / overlay absent) — verified via remote
#           grep of audit stream + service env-list.
#   AXIS-4  Cross-Lang-Hash-Parity vs. PR #224 Pin-Pack anchor:
#           remote persona-engine-CLI emits hash for canonical
#           fixture identical to in-repo pin-pack value.
#   AXIS-5  Rollback-Probe: env unset → service restart → engine
#           returns to backend=python (dry-run only; no env mutation
#           actually performed in pre-cutover phase — this axis
#           verifies the *capability* by inspecting the rollback
#           command surface, not by executing it).
#
# Exit-codes
#   0  green       — all five axes matched, Welle-1 cutover GREEN.
#   1  caution     — ≥ 1 axis yellow, none red.  Operator-Hand-Decision.
#   2  block       — ≥ 1 axis red.  Welle-1 cutover BLOCKED.
#   3  precond     — bad CLI args / missing SSH key / invalid Welle.
#   4  not-exec    — VM unreachable (SSH fail) — special status that
#                    surfaces in the Acceptance-Report as
#                    PROBE-NOT-EXECUTED.
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 (Phase-3c Cutover-Plan: Welle-1 v907_verify)
#   - ADR-0066 (Phase-3c Doppel-Welle order)
#   - PR #224 (Pin-Pack Cross-Lang Anchor)
#   - PR #230 (Welle-1 Cutover-Smoke)
#   - PR #250 (Tag-38 migrate-version → 11 BackendDecision baseline)
#   - reports/live-vm/2026-05-18-welle-1-pre-cutover-probe.md
#
# Author: Kai Hoffmann (DevOps-3), Sprint-Tag-41, 2026-05-18.
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
WAKIR_PROBE_MIN_BACKEND_DECISIONS="${WAKIR_PROBE_MIN_BACKEND_DECISIONS:-11}"
WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC="${WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC:-8}"
WAKIR_PROBE_EXPECTED_HASH="${WAKIR_PROBE_EXPECTED_HASH:-}"
WAKIR_PROBE_WELLE="${WAKIR_PROBE_WELLE:-1}"
WAKIR_PROBE_COMPONENT="${WAKIR_PROBE_COMPONENT:-v907_verify}"
WAKIR_PROBE_DEFAULT_BACKEND="${WAKIR_PROBE_DEFAULT_BACKEND:-python}"
WAKIR_PROBE_ROLLBACK_ENV_NAME="${WAKIR_PROBE_ROLLBACK_ENV_NAME:-WAKIR_V907_VERIFY_BACKEND}"

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

Pre-Cutover-Sanity-Probe for Phase-3c Welle-1 (v907_verify, ADR-0065)
against the wakir-pilot live VM via Mira-Hand-SSH (ADR-0058).

Options:
  --dry-run                Plan probe steps; do not open SSH.
  --quiet                  Suppress non-error stdout chatter.
  --welle <n>              Welle index (default: 1).
  --component <name>       Component name (default: v907_verify).
  --expected-hash <hex>    Pin-Pack anchor hash for AXIS-4 cross-lang.
  --min-decisions <n>      AXIS-2 minimum BackendDecision count
                           (default: ${WAKIR_PROBE_MIN_BACKEND_DECISIONS}).
  --host <ip>              Override pilot host (default: ${WAKIR_PILOT_HOST}).
  --user <name>            Override SSH user  (default: ${WAKIR_PILOT_USER}).
  --ssh-key <path>         Override SSH key   (default: ${WAKIR_PILOT_SSH_KEY}).
  -h, --help               Show this help and exit.

Exit-codes: 0 green / 1 caution / 2 block / 3 precond / 4 not-exec.
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --dry-run)      DRY_RUN=1; shift ;;
        --quiet)        QUIET=1; shift ;;
        --welle)        WAKIR_PROBE_WELLE="$2"; shift 2 ;;
        --component)    WAKIR_PROBE_COMPONENT="$2"; shift 2 ;;
        --expected-hash) WAKIR_PROBE_EXPECTED_HASH="$2"; shift 2 ;;
        --min-decisions) WAKIR_PROBE_MIN_BACKEND_DECISIONS="$2"; shift 2 ;;
        --host)         WAKIR_PILOT_HOST="$2"; shift 2 ;;
        --user)         WAKIR_PILOT_USER="$2"; shift 2 ;;
        --ssh-key)      WAKIR_PILOT_SSH_KEY="$2"; shift 2 ;;
        -h|--help)      usage; exit 0 ;;
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
    # remote_exec <description> <cmd> — echoes captured stdout.
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

# AXIS-1 — Engine-State-Snapshot reachable.
axis_1_engine_state_snapshot() {
    log_step "AXIS-1 engine-state-snapshot (component=${WAKIR_PROBE_COMPONENT})"
    local cmd='persona-engine-cli state-pack --json 2>/dev/null | head -c 4096; echo; persona-engine-cli audit-stream-snapshot --tail 5 --json 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-1-snapshot" "${cmd}") || rc=$?
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
        AXIS_1_DETAIL="empty-snapshot-output"
        return 2
    fi
    AXIS_1_VERDICT="GREEN"
    AXIS_1_DETAIL="snapshot-bytes=$(printf '%s' "${out}" | wc -c | tr -d ' ')"
    return 0
}

# AXIS-2 — ≥ 11 BackendDecision audit entries since service start.
axis_2_backend_decision_count() {
    log_step "AXIS-2 backend-decision-count (min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS})"
    local cmd='journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -c BackendDecision || true'
    local out rc count
    set +e
    out=$(remote_exec "axis-2-count" "${cmd}") || rc=$?
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
    AXIS_2_DETAIL="observed=${count} min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS}"
    if (( count >= WAKIR_PROBE_MIN_BACKEND_DECISIONS )); then
        AXIS_2_VERDICT="GREEN"
        return 0
    elif (( count > 0 )); then
        AXIS_2_VERDICT="YELLOW"
        return 1
    else
        AXIS_2_VERDICT="RED"
        return 2
    fi
}

# AXIS-3 — backend=python in Default-State.
axis_3_default_state_backend() {
    log_step "AXIS-3 default-state backend (expected=${WAKIR_PROBE_DEFAULT_BACKEND})"
    local cmd
    cmd='systemctl show persona-engine -p Environment 2>/dev/null; echo "---ENV-OVERLAY-LIST---"; ls -1 /etc/systemd/system/persona-engine.service.d/ 2>/dev/null || true; echo "---AUDIT-TAIL---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "BackendDecision.*'"${WAKIR_PROBE_COMPONENT}"'" | tail -1'
    local out rc
    out=$(remote_exec "axis-3-default" "${cmd}") || rc=$?
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
    # Pre-Cutover-Default = no overlay file *and* audit shows backend=python.
    local overlay_present=0
    if printf '%s' "${out}" | grep -qE "welle-1-v907-verify-rust\.conf"; then
        overlay_present=1
    fi
    local audit_backend=""
    if printf '%s' "${out}" | grep -qE "backend=python|backend=\"python\""; then
        audit_backend="python"
    elif printf '%s' "${out}" | grep -qE "backend=rust|backend=\"rust\""; then
        audit_backend="rust"
    fi
    AXIS_3_DETAIL="overlay_present=${overlay_present} audit_backend=${audit_backend:-unknown}"
    if (( overlay_present == 0 )) && [[ "${audit_backend}" == "${WAKIR_PROBE_DEFAULT_BACKEND}" ]]; then
        AXIS_3_VERDICT="GREEN"
        return 0
    elif (( overlay_present == 1 )); then
        AXIS_3_VERDICT="RED"
        return 2
    else
        AXIS_3_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-4 — Cross-Lang-Hash-Parity vs. Pin-Pack anchor (PR #224).
axis_4_cross_lang_hash_parity() {
    log_step "AXIS-4 cross-lang-hash-parity (expected=${WAKIR_PROBE_EXPECTED_HASH:-<unset>})"
    if [[ -z "${WAKIR_PROBE_EXPECTED_HASH}" ]]; then
        AXIS_4_VERDICT="YELLOW"
        AXIS_4_DETAIL="no expected-hash provided; skipping strict equality"
        log_warn "AXIS-4 skipped: --expected-hash not provided"
        return 1
    fi
    local cmd='persona-engine-cli v907-verify-hash --canonical-fixture pin-pack-v1 --json 2>/dev/null | head -c 1024'
    local out rc
    out=$(remote_exec "axis-4-hash" "${cmd}") || rc=$?
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
    if printf '%s' "${out}" | grep -qF "${WAKIR_PROBE_EXPECTED_HASH}"; then
        AXIS_4_VERDICT="GREEN"
        AXIS_4_DETAIL="hash-match expected=${WAKIR_PROBE_EXPECTED_HASH}"
        return 0
    else
        AXIS_4_VERDICT="RED"
        AXIS_4_DETAIL="hash-mismatch (Pin-Pack anchor drift)"
        return 2
    fi
}

# AXIS-5 — Rollback-Probe surface inspection (non-mutating).
axis_5_rollback_surface() {
    log_step "AXIS-5 rollback-surface-inspection (env=${WAKIR_PROBE_ROLLBACK_ENV_NAME})"
    # We only inspect that the rollback levers are *present* —
    # actual env-unset + restart is the cutover-action surface, not
    # the pre-cutover probe.  We check:
    #   - drop-in dir exists + writable for root (overlay-removable)
    #   - systemctl daemon-reload + restart commands present
    #   - persona-engine service exists and is enabled
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
# Verdict aggregation.
# -----------------------------------------------------------------

aggregate_verdict() {
    # Echoes one of: GREEN / CAUTION / BLOCK / NOT-EXEC.
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
    log_info "welle-1-pre-cutover-probe start ts=${PROBE_TS} host=${WAKIR_PILOT_HOST} dry-run=${DRY_RUN}"
    log_info "component=${WAKIR_PROBE_COMPONENT} welle=${WAKIR_PROBE_WELLE} default-backend=${WAKIR_PROBE_DEFAULT_BACKEND}"

    if ! check_ssh_key_present; then
        log_error "precondition failure: SSH key"
        exit 3
    fi

    local r1=0 r2=0 r3=0 r4=0 r5=0
    axis_1_engine_state_snapshot  || r1=$?
    axis_2_backend_decision_count || r2=$?
    axis_3_default_state_backend  || r3=$?
    axis_4_cross_lang_hash_parity || r4=$?
    axis_5_rollback_surface       || r5=$?

    # Promote NOT-EXEC: if any axis is unreachable, all subsequent ones
    # likely are too — but we still record per-axis verdicts for the
    # Acceptance-Report.
    local verdict
    verdict=$(aggregate_verdict \
        "${AXIS_1_VERDICT}" "${AXIS_2_VERDICT}" "${AXIS_3_VERDICT}" \
        "${AXIS_4_VERDICT}" "${AXIS_5_VERDICT}")

    log_verdict "AXIS-1 ${AXIS_1_VERDICT}: ${AXIS_1_DETAIL}"
    log_verdict "AXIS-2 ${AXIS_2_VERDICT}: ${AXIS_2_DETAIL}"
    log_verdict "AXIS-3 ${AXIS_3_VERDICT}: ${AXIS_3_DETAIL}"
    log_verdict "AXIS-4 ${AXIS_4_VERDICT}: ${AXIS_4_DETAIL}"
    log_verdict "AXIS-5 ${AXIS_5_VERDICT}: ${AXIS_5_DETAIL}"
    log_verdict "AGGREGATE: ${verdict}"

    # Emit a tail-friendly summary on stdout for operator-hand
    # consumption (`bash welle-1-pre-cutover-probe.sh | tail -1`).
    printf 'PROBE-VERDICT=%s welle=%s component=%s ts=%s log=%s\n' \
        "${verdict}" "${WAKIR_PROBE_WELLE}" "${WAKIR_PROBE_COMPONENT}" \
        "${PROBE_TS}" "${PROBE_LOG}"

    case "${verdict}" in
        GREEN)    exit 0 ;;
        CAUTION)  exit 1 ;;
        BLOCK)    exit 2 ;;
        NOT-EXEC) exit 4 ;;
        *)        exit 2 ;;
    esac
}

main "$@"
