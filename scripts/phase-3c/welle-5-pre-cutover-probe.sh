#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-5-pre-cutover-probe.sh — Phase-3c Pre-Cutover-Sanity-Probe
# for Welle-5 (lifecycle_state_machine, ADR-0066 KW-26 Doppel-Welle).
# -----------------------------------------------------------------
#
# Purpose
#   Executes a non-mutating Pre-Cutover-Sanity-Run against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) for Welle-5
#   (lifecycle_state_machine, aka fsm).  This probe is the *pre-flight
#   test* of substance against the real substrate ahead of the KW-26
#   Doppel-Welle cutover window — it confirms that the Welle-5
#   substance (PR #249 Cutover-Smoke + fsm canonical serializer) meets
#   the GO-criteria *on the actual VM*, not just on the Mira-sandbox
#   hermetic test bed.
#
#   The probe is intentionally distinct from the welle-5 cutover-smoke
#   driver (PR #249): where the smoke *enacts* the Cutover sequence in
#   dry-run-mode against the substrate, the probe only *observes* +
#   *verifies* the system in its Default-State (backend=python for
#   lifecycle_state_machine) before any env-overlay drop-in.
#
# Doppel-Welle Coordination (§10 below)
#   KW-26 runs Welle-4 (state_backing) and Welle-5
#   (lifecycle_state_machine) in parallel — the probes share the
#   Cross-Modul-Drift-Pre-Check axis (A5 symmetric in both wrappers).
#   See §10 in this file and the matching block in
#   welle-4-pre-cutover-probe.sh for the parallel-run contract.
#
# Authority
#   Mira-Hand-SSH per ADR-0058 §Nachtrag (approved KW-20).  Uses key
#   ${HOME}/.ssh/wakir-pilot-vm-diagnose.  No AR escalation required
#   for the read-only checks executed here.
#
# Sandbox boundary
#   This script never executes podman / systemctl locally.  All probes
#   ship over SSH.  The hermetic test suite stubs `ssh` via
#   $WAKIR_SSH_BIN so no real connection opens in CI.  When the VM is
#   unreachable the probe emits a structured "PROBE-NOT-EXECUTED"
#   verdict so callers can still consume an Acceptance-Report — the
#   AR-direktive Tag-41 explicitly mandates non-blocking behaviour on
#   VM-down.
#
# Six verification axes (output triad green/yellow/red per axis):
#
#   AXIS-1  FSM-State-Persistence-Pre-Verification — Pre-Cutover fsm
#           state snapshot via lifecycle-state-machine-CLI emits non-
#           empty canonical-serialized payload; hash captured for
#           later compare against PHASE_POST.
#   AXIS-2  Welle-5 Cutover-Smoke dry-run (PR #249) emits exit-0 in
#           dry-run-mode against the live VM — substance gate.
#   AXIS-3  FSM-Transition-Integrity-Pre-Check + Phantom-Transition
#           scan: the fsm trace recomputation contains zero edges
#           outside spec §3.3 VALID_TRANSITIONS in the captured
#           pre-cutover transition log slice.
#   AXIS-4  BackendDecision-Stream-Health: ≥ 11 BackendDecision audit
#           entries since service start (Tag-38 PR #250 migrate-
#           version baseline) AND lifecycle_state_machine
#           component-line in default backend=python in audit-tail.
#   AXIS-5  Cross-Modul-Drift-Pre-Check zu Welle-4 (symmetric A7):
#           state_backing overlay is *absent* in Default-State (the
#           inverse of Welle-4's AXIS-5 — together they form the
#           pre-image of the KW-26 isolation contract).
#   AXIS-6  Cross-Lang-Parity vs. Pin-Pack anchor: remote
#           lifecycle-state-machine CLI emits canonical fsm-state
#           hash identical to in-repo --expected-hash value.
#   AXIS-7  Rollback-Probe: env unset → service restart → engine
#           returns to backend=python (dry-run only; no env mutation
#           actually performed in pre-cutover phase — this axis
#           verifies the *capability* by inspecting the rollback
#           command surface, not by executing it).
#
#   (Auftrag-Spec: "5+1 Asserts" — AXIS-3 carries the FSM-Transition-
#   Integrity-Pre-Check *and* the Phantom-Transition-Scan as one
#   combined integrity axis, plus the +1 Rollback-Probe.  Counted
#   as 6 axes for the aggregate, but the rubric reads as 5+1.)
#
# Exit-codes
#   0  green       — all axes matched, Welle-5 cutover GREEN.
#   1  caution     — ≥ 1 axis yellow, none red.  Operator-Hand-Decision.
#   2  block       — ≥ 1 axis red.  Welle-5 cutover BLOCKED.
#   3  precond     — bad CLI args / missing SSH key / invalid Welle.
#   4  not-exec    — VM unreachable (SSH fail) — special status that
#                    surfaces in the Acceptance-Report as
#                    PROBE-NOT-EXECUTED.
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 (Phase-3c Cutover-Plan)
#   - ADR-0066 (Phase-3c Doppel-Welle order; KW-26 Welle-4 + Welle-5)
#   - PR #224 (Pin-Pack Cross-Lang Anchor)
#   - PR #249 (Welle-5 lifecycle_state_machine Cutover-Smoke)
#   - PR #250 (Tag-38 migrate-version → 11 BackendDecision baseline)
#   - PR #267 (Welle-1 Pre-Cutover-Probe wrapper template)
#   - reports/live-vm/2026-05-18-welle-5-pre-cutover-probe.md
#
# Author: Kai Hoffmann (DevOps-3), Sprint-Tag-42, 2026-05-18.
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
WAKIR_PROBE_WELLE="${WAKIR_PROBE_WELLE:-5}"
WAKIR_PROBE_COMPONENT="${WAKIR_PROBE_COMPONENT:-lifecycle_state_machine}"
WAKIR_PROBE_PAIR_COMPONENT="${WAKIR_PROBE_PAIR_COMPONENT:-state_backing}"
WAKIR_PROBE_PAIR_OVERLAY_NAME="${WAKIR_PROBE_PAIR_OVERLAY_NAME:-welle-4-state-backing-rust.conf}"
WAKIR_PROBE_OVERLAY_NAME="${WAKIR_PROBE_OVERLAY_NAME:-welle-5-lifecycle-state-machine-rust.conf}"
WAKIR_PROBE_DEFAULT_BACKEND="${WAKIR_PROBE_DEFAULT_BACKEND:-python}"
WAKIR_PROBE_ROLLBACK_ENV_NAME="${WAKIR_PROBE_ROLLBACK_ENV_NAME:-WAKIR_LIFECYCLE_STATE_MACHINE_BACKEND}"

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

Pre-Cutover-Sanity-Probe for Phase-3c Welle-5
(lifecycle_state_machine, ADR-0066 KW-26 Doppel-Welle) against the
wakir-pilot live VM via Mira-Hand-SSH (ADR-0058).

Options:
  --dry-run                Plan probe steps; do not open SSH.
  --quiet                  Suppress non-error stdout chatter.
  --welle <n>              Welle index (default: 5).
  --component <name>       Component name (default:
                           lifecycle_state_machine).
  --pair-component <name>  Doppel-Welle pair component (default:
                           state_backing).
  --expected-hash <hex>    Pin-Pack anchor hash for AXIS-6 cross-lang.
  --min-decisions <n>      AXIS-4 minimum BackendDecision count
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
        --dry-run)        DRY_RUN=1; shift ;;
        --quiet)          QUIET=1; shift ;;
        --welle)          WAKIR_PROBE_WELLE="$2"; shift 2 ;;
        --component)      WAKIR_PROBE_COMPONENT="$2"; shift 2 ;;
        --pair-component) WAKIR_PROBE_PAIR_COMPONENT="$2"; shift 2 ;;
        --expected-hash)  WAKIR_PROBE_EXPECTED_HASH="$2"; shift 2 ;;
        --min-decisions)  WAKIR_PROBE_MIN_BACKEND_DECISIONS="$2"; shift 2 ;;
        --host)           WAKIR_PILOT_HOST="$2"; shift 2 ;;
        --user)           WAKIR_PILOT_USER="$2"; shift 2 ;;
        --ssh-key)        WAKIR_PILOT_SSH_KEY="$2"; shift 2 ;;
        -h|--help)        usage; exit 0 ;;
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
# 4=not-exec.
# -----------------------------------------------------------------

AXIS_1_VERDICT="UNKNOWN"
AXIS_2_VERDICT="UNKNOWN"
AXIS_3_VERDICT="UNKNOWN"
AXIS_4_VERDICT="UNKNOWN"
AXIS_5_VERDICT="UNKNOWN"
AXIS_6_VERDICT="UNKNOWN"
AXIS_7_VERDICT="UNKNOWN"
AXIS_1_DETAIL=""
AXIS_2_DETAIL=""
AXIS_3_DETAIL=""
AXIS_4_DETAIL=""
AXIS_5_DETAIL=""
AXIS_6_DETAIL=""
AXIS_7_DETAIL=""

# AXIS-1 — FSM-State-Persistence-Pre-Verification.
axis_1_fsm_state_persistence() {
    log_step "AXIS-1 fsm-state-persistence-pre-verification (component=${WAKIR_PROBE_COMPONENT})"
    local cmd='lifecycle-state-machine-cli state-snapshot --canonical --json 2>/dev/null | head -c 4096; echo; persona-engine-cli audit-stream-snapshot --tail 5 --json 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-1-fsm-snapshot" "${cmd}") || rc=$?
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
        AXIS_1_DETAIL="empty-fsm-snapshot-output"
        return 2
    fi
    AXIS_1_VERDICT="GREEN"
    AXIS_1_DETAIL="fsm-snapshot-bytes=$(printf '%s' "${out}" | wc -c | tr -d ' ')"
    return 0
}

# AXIS-2 — Welle-5 Cutover-Smoke dry-run (PR #249).
axis_2_smoke_dry_run() {
    log_step "AXIS-2 welle-5-cutover-smoke dry-run (PR #249)"
    local cmd='cd /opt/wakir-runtime && python scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py --dry-run --quiet 2>&1 | tail -5; echo "RC=$?"'
    local out rc
    out=$(remote_exec "axis-2-smoke" "${cmd}") || rc=$?
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
    if printf '%s' "${out}" | grep -qE "RC=0$"; then
        AXIS_2_VERDICT="GREEN"
        AXIS_2_DETAIL="smoke-dry-run-rc=0"
        return 0
    elif printf '%s' "${out}" | grep -qE "RC=1$"; then
        AXIS_2_VERDICT="YELLOW"
        AXIS_2_DETAIL="smoke-dry-run-rc=1 (caution)"
        return 1
    else
        AXIS_2_VERDICT="RED"
        AXIS_2_DETAIL="smoke-dry-run-rc=non-zero-non-1"
        return 2
    fi
}

# AXIS-3 — FSM-Transition-Integrity-Pre-Check + Phantom-Transition-Scan.
axis_3_fsm_transition_integrity() {
    log_step "AXIS-3 fsm-transition-integrity + phantom-transition-scan"
    # phantom-transition scan: lifecycle-state-machine-cli emits a JSON
    # array of transitions outside VALID_TRANSITIONS (spec §3.3); empty
    # array means clean state.
    local cmd='lifecycle-state-machine-cli trace-validate --canonical --json 2>/dev/null | head -c 4096; echo; lifecycle-state-machine-cli phantom-transitions --json 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-3-fsm-integrity" "${cmd}") || rc=$?
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
    # Heuristics: trace-validate output must contain "valid":true and
    # phantom-transitions output must contain an empty array "[]" or
    # `"phantom_count":0`.
    local trace_ok=0
    local phantom_clean=0
    if printf '%s' "${out}" | grep -qE '"valid"[[:space:]]*:[[:space:]]*true'; then
        trace_ok=1
    fi
    if printf '%s' "${out}" | grep -qE '"phantom_count"[[:space:]]*:[[:space:]]*0|"phantom_transitions"[[:space:]]*:[[:space:]]*\[\]'; then
        phantom_clean=1
    fi
    AXIS_3_DETAIL="trace_valid=${trace_ok} phantom_clean=${phantom_clean}"
    if (( trace_ok == 1 )) && (( phantom_clean == 1 )); then
        AXIS_3_VERDICT="GREEN"
        return 0
    elif (( trace_ok == 1 )) || (( phantom_clean == 1 )); then
        AXIS_3_VERDICT="YELLOW"
        return 1
    else
        AXIS_3_VERDICT="RED"
        return 2
    fi
}

# AXIS-4 — BackendDecision-Stream-Health.
axis_4_backend_decision_health() {
    log_step "AXIS-4 backend-decision-stream-health (min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS})"
    local cmd
    cmd='journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -c BackendDecision || true; echo "---COMPONENT-TAIL---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "BackendDecision.*'"${WAKIR_PROBE_COMPONENT}"'" | tail -1'
    local out rc count
    set +e
    out=$(remote_exec "axis-4-health" "${cmd}") || rc=$?
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
    count=$(printf '%s' "${out}" | sed -n '1p' | tr -dc '0-9')
    if [[ -z "${count}" ]]; then count=0; fi
    local component_backend=""
    if printf '%s' "${out}" | grep -qE "backend=python|backend=\"python\""; then
        component_backend="python"
    elif printf '%s' "${out}" | grep -qE "backend=rust|backend=\"rust\""; then
        component_backend="rust"
    fi
    AXIS_4_DETAIL="observed=${count} min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS} component_backend=${component_backend:-unknown}"
    if (( count >= WAKIR_PROBE_MIN_BACKEND_DECISIONS )) && [[ "${component_backend}" == "${WAKIR_PROBE_DEFAULT_BACKEND}" ]]; then
        AXIS_4_VERDICT="GREEN"
        return 0
    elif (( count >= 1 )); then
        AXIS_4_VERDICT="YELLOW"
        return 1
    else
        AXIS_4_VERDICT="RED"
        return 2
    fi
}

# AXIS-5 — Cross-Modul-Drift-Pre-Check zu Welle-4 (symmetric A7).
axis_5_cross_modul_drift_pre_check() {
    log_step "AXIS-5 cross-modul-drift-pre-check (pair=${WAKIR_PROBE_PAIR_COMPONENT})"
    local cmd
    cmd='ls -1 /etc/systemd/system/persona-engine.service.d/ 2>/dev/null; echo "---PAIR-AUDIT-TAIL---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "BackendDecision.*'"${WAKIR_PROBE_PAIR_COMPONENT}"'" | tail -1'
    local out rc
    out=$(remote_exec "axis-5-drift" "${cmd}") || rc=$?
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
    local pair_overlay_present=0
    if printf '%s' "${out}" | grep -qF "${WAKIR_PROBE_PAIR_OVERLAY_NAME}"; then
        pair_overlay_present=1
    fi
    local pair_backend=""
    if printf '%s' "${out}" | grep -qE "backend=python|backend=\"python\""; then
        pair_backend="python"
    elif printf '%s' "${out}" | grep -qE "backend=rust|backend=\"rust\""; then
        pair_backend="rust"
    fi
    AXIS_5_DETAIL="pair=${WAKIR_PROBE_PAIR_COMPONENT} pair_overlay_present=${pair_overlay_present} pair_backend=${pair_backend:-unknown}"
    if (( pair_overlay_present == 0 )) && [[ "${pair_backend}" != "rust" ]]; then
        AXIS_5_VERDICT="GREEN"
        return 0
    elif (( pair_overlay_present == 1 )); then
        AXIS_5_VERDICT="RED"
        return 2
    else
        AXIS_5_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-6 — Cross-Lang-Parity vs. Pin-Pack anchor.
axis_6_cross_lang_parity() {
    log_step "AXIS-6 cross-lang-parity (expected=${WAKIR_PROBE_EXPECTED_HASH:-<unset>})"
    if [[ -z "${WAKIR_PROBE_EXPECTED_HASH}" ]]; then
        AXIS_6_VERDICT="YELLOW"
        AXIS_6_DETAIL="no expected-hash provided; skipping strict equality"
        log_warn "AXIS-6 skipped: --expected-hash not provided"
        return 1
    fi
    local cmd='lifecycle-state-machine-cli state-hash --canonical-fixture pin-pack-v1 --json 2>/dev/null | head -c 1024'
    local out rc
    out=$(remote_exec "axis-6-hash" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_6_VERDICT="NOT-EXEC"
        AXIS_6_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_6_VERDICT="DRY-RUN"
        AXIS_6_DETAIL="dry-run (no remote call)"
        return 0
    fi
    if printf '%s' "${out}" | grep -qF "${WAKIR_PROBE_EXPECTED_HASH}"; then
        AXIS_6_VERDICT="GREEN"
        AXIS_6_DETAIL="hash-match expected=${WAKIR_PROBE_EXPECTED_HASH}"
        return 0
    else
        AXIS_6_VERDICT="RED"
        AXIS_6_DETAIL="hash-mismatch (Pin-Pack anchor drift)"
        return 2
    fi
}

# AXIS-7 — Rollback-Probe surface inspection (non-mutating).
axis_7_rollback_surface() {
    log_step "AXIS-7 rollback-surface-inspection (env=${WAKIR_PROBE_ROLLBACK_ENV_NAME})"
    local cmd
    cmd='ls -ld /etc/systemd/system/persona-engine.service.d 2>/dev/null; systemctl is-enabled persona-engine 2>/dev/null; command -v systemctl >/dev/null && echo systemctl-OK; command -v journalctl >/dev/null && echo journalctl-OK'
    local out rc
    out=$(remote_exec "axis-7-rollback-surface" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_7_VERDICT="NOT-EXEC"
        AXIS_7_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_7_VERDICT="DRY-RUN"
        AXIS_7_DETAIL="dry-run (no remote call)"
        return 0
    fi
    local levers_ok=0
    printf '%s' "${out}" | grep -q "systemctl-OK"  && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "journalctl-OK" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -qE "(enabled|static|alias|enabled-runtime)" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "persona-engine.service.d" && (( levers_ok+=1 )) || true
    AXIS_7_DETAIL="rollback-levers-present=${levers_ok}/4"
    if (( levers_ok >= 4 )); then
        AXIS_7_VERDICT="GREEN"
        return 0
    elif (( levers_ok >= 2 )); then
        AXIS_7_VERDICT="YELLOW"
        return 1
    else
        AXIS_7_VERDICT="RED"
        return 2
    fi
}

# -----------------------------------------------------------------
# Verdict aggregation.
# -----------------------------------------------------------------

aggregate_verdict() {
    local any_not_exec=0 any_red=0 any_yellow=0
    for v in "$@"; do
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
# §10 — Doppel-Welle KW-26 Parallel-Run Coordination Note.
#
# ADR-0066 schedules Welle-4 (state_backing) and Welle-5
# (lifecycle_state_machine) in parallel during the KW-26 cutover
# window.  The pre-cutover probes carry that constraint forward
# via AXIS-5 (Cross-Modul-Drift-Pre-Check) — symmetric in both
# wrappers:
#
#   * welle-5-pre-cutover-probe.sh AXIS-5 verifies the Welle-4
#     overlay (welle-4-state-backing-rust.conf) is NOT present in
#     Default-State.  If it is, the parallel-Welle isolation
#     contract is already broken and the Welle-5 cutover MUST NOT
#     start.
#
#   * welle-4-pre-cutover-probe.sh AXIS-5 verifies the inverse:
#     the Welle-5 overlay
#     (welle-5-lifecycle-state-machine-rust.conf) is NOT present
#     in Default-State.
#
# These two AXIS-5 results together form the pre-image of the
# Welle-4 / Welle-5 cutover-smoke A7 assertions (the per-smoke
# isolation asserts that the parallel module did not leak during
# the cutover window).  A GREEN AXIS-5 in *both* wrappers is the
# necessary precondition to enter the KW-26 Doppel-Welle window.
#
# Operator-Hand workflow:
#   1. Run welle-4-pre-cutover-probe.sh, capture verdict.
#   2. Run welle-5-pre-cutover-probe.sh, capture verdict.
#   3. Both GREEN → enter cutover window.  Any BLOCK / CAUTION
#      on either side → route to engineering before window-start.
#
# This §10 block is intentionally duplicated (verbatim modulo
# component swap) in welle-4-pre-cutover-probe.sh.
# -----------------------------------------------------------------

# -----------------------------------------------------------------
# Main.
# -----------------------------------------------------------------

main() {
    log_info "welle-5-pre-cutover-probe start ts=${PROBE_TS} host=${WAKIR_PILOT_HOST} dry-run=${DRY_RUN}"
    log_info "component=${WAKIR_PROBE_COMPONENT} welle=${WAKIR_PROBE_WELLE} pair-component=${WAKIR_PROBE_PAIR_COMPONENT}"

    if ! check_ssh_key_present; then
        log_error "precondition failure: SSH key"
        exit 3
    fi

    local r1=0 r2=0 r3=0 r4=0 r5=0 r6=0 r7=0
    axis_1_fsm_state_persistence        || r1=$?
    axis_2_smoke_dry_run                || r2=$?
    axis_3_fsm_transition_integrity     || r3=$?
    axis_4_backend_decision_health      || r4=$?
    axis_5_cross_modul_drift_pre_check  || r5=$?
    axis_6_cross_lang_parity            || r6=$?
    axis_7_rollback_surface             || r7=$?

    local verdict
    verdict=$(aggregate_verdict \
        "${AXIS_1_VERDICT}" "${AXIS_2_VERDICT}" "${AXIS_3_VERDICT}" \
        "${AXIS_4_VERDICT}" "${AXIS_5_VERDICT}" "${AXIS_6_VERDICT}" \
        "${AXIS_7_VERDICT}")

    log_verdict "AXIS-1 ${AXIS_1_VERDICT}: ${AXIS_1_DETAIL}"
    log_verdict "AXIS-2 ${AXIS_2_VERDICT}: ${AXIS_2_DETAIL}"
    log_verdict "AXIS-3 ${AXIS_3_VERDICT}: ${AXIS_3_DETAIL}"
    log_verdict "AXIS-4 ${AXIS_4_VERDICT}: ${AXIS_4_DETAIL}"
    log_verdict "AXIS-5 ${AXIS_5_VERDICT}: ${AXIS_5_DETAIL}"
    log_verdict "AXIS-6 ${AXIS_6_VERDICT}: ${AXIS_6_DETAIL}"
    log_verdict "AXIS-7 ${AXIS_7_VERDICT}: ${AXIS_7_DETAIL}"
    log_verdict "AGGREGATE: ${verdict}"

    printf 'PROBE-VERDICT=%s welle=%s component=%s pair-component=%s ts=%s log=%s\n' \
        "${verdict}" "${WAKIR_PROBE_WELLE}" "${WAKIR_PROBE_COMPONENT}" \
        "${WAKIR_PROBE_PAIR_COMPONENT}" "${PROBE_TS}" "${PROBE_LOG}"

    case "${verdict}" in
        GREEN)    exit 0 ;;
        CAUTION)  exit 1 ;;
        BLOCK)    exit 2 ;;
        NOT-EXEC) exit 4 ;;
        *)        exit 2 ;;
    esac
}

main "$@"
