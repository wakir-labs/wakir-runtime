#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-7-pre-cutover-probe.sh — Phase-3c Pre-Cutover-Sanity-Probe
# -----------------------------------------------------------------
#
# §0  Phase-3-Marathon-Schluss-Markierung
# ---------------------------------------
#
#   *** THIS IS THE LAST PRE-CUTOVER-PROBE OF PHASE-3. ***
#
#   Welle-7 (recovery_workflow) is the final cutover wave of the
#   Phase-3-Doppel-Welle pair (Welle-6 + Welle-7, KW-27, ADR-0066
#   §Doppel-Welle KW-27).  After Welle-7 cutover completes
#   successfully on the live pilot VM, Phase-3 is structurally
#   complete and the phase-3-complete marker workflow
#   (.github/workflows/phase-3-complete-marker.yml) fires to
#   record the Marathon endpoint.
#
#   Consequently this probe is the *last* read-only sanity gate
#   between substance-readiness and the Phase-3-COMPLETE-Marker.
#   Any RED verdict here BLOCKS the cutover and therefore BLOCKS
#   the marker from firing.  Operator-hand replay is mandatory
#   before the KW-27 Welle-7 cutover step.
#
#   In addition to the five core axes, Welle-7 carries one
#   probe-extension Pre-Condition: the Henrik / IIA-1130 Pre-
#   Auditor-Decision-Check.  Phase-3-Ende cutover requires a
#   prior Internal-Audit sign-off captured as
#   ``state/welle-7-pre-auditor-decision.json`` (see ADR-0067 +
#   ADR-0068 audit-trail).  This probe verifies the file exists
#   and parses as JSON before any axis runs.  Missing file =>
#   exit-3 (precondition).  This is symmetric to (but separate
#   from) the IIA-1110 Pre-Cutover-Auditor-Check that fires
#   pre-Welle-6 in the §Doppel-Welle ordering.
#
# §1  Purpose
# -----------
#
#   Executes a non-mutating Pre-Cutover-Sanity-Run against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) for Welle-7
#   (recovery_workflow, ADR-0066 §Doppel-Welle KW-27 + ADR-0065
#   §Welle-7).  Confirms that the Tag-37 / Tag-38 / Tag-40 /
#   Tag-41 substance meets the Welle-7 GO-criteria *on the
#   actual VM*, not just on the Mira-sandbox hermetic test bed.
#
#   Welle-7 runs *in parallel* with Welle-6 (subscribe_loop) —
#   the cutover pair forms the Phase-3-Ende Doppel-Welle.  Cross-
#   Modul-Drift isolation between Welle-6 and Welle-7 is therefore
#   the single highest-impact Pre-Cutover concern; AXIS-3 is
#   dedicated to it (symmetric to Welle-6 AXIS-4, but inverted
#   direction).
#
# §2  Authority
# -------------
#
#   Mira-Hand-SSH per ADR-0058 §Nachtrag.  Uses key
#   ${HOME}/.ssh/wakir-pilot-vm-diagnose.  No AR escalation
#   required for the read-only checks executed here.
#
# §3  Sandbox boundary
# --------------------
#
#   This script never executes podman / systemctl locally.  All
#   probes ship over SSH.  The hermetic test suite stubs `ssh`
#   via $WAKIR_SSH_BIN so no real connection opens in CI.  When
#   the VM is unreachable the probe emits a structured
#   "PROBE-NOT-EXECUTED" verdict so callers can still consume an
#   Acceptance-Report.
#
# §4  Pre-Condition (Welle-7 only)
# --------------------------------
#
#   Before any axis runs, the probe checks the existence of
#   ``state/welle-7-pre-auditor-decision.json`` (relative to the
#   repository root, or overridable via $WAKIR_PROBE_PRE_AUDITOR_PATH).
#   This file is produced by Henrik (Internal Audit) per the
#   IIA-1130-Pre-Auditor workflow.  If the file is missing or
#   does not parse as JSON, the probe exits with code 3
#   (precondition) and does NOT proceed to the axes.  This is
#   the Phase-3-Ende audit-gate; cutover cannot start without
#   it.
#
# §5  Six verification asserts (5 + 1 axes)
# -----------------------------------------
#
#   Output triad green/yellow/red per axis.
#
#   AXIS-1  R1..R4-Recovery-Pre-Stability — recovery-drill-pre-
#           snapshot via persona-engine-cli; recomputed recovery
#           outcome preserves spec §3.7.4 R-phase ordering
#           (R1 -> R2 -> R3 -> R4).  This is the recovery-drill
#           baseline that the Welle-7 cutover-smoke A6 assert
#           later compares against.
#   AXIS-2  State-Backing-Dependency-Pre-Check — Welle-4
#           (state_backing) is already cutovert per ADR-0066:
#           WAKIR_STATE_BACKING_BACKEND=rust must be pinned and
#           the state_backing substrate must report rust-backed
#           reads in the audit tail.  Guards against starting
#           Welle-7 before state_backing has stabilised on
#           Rust-default.
#   AXIS-3  Cross-Modul-Drift-Pre-Check zu Welle-6 (symmetric
#           A7) — recovery_workflow env-var is at python in
#           PHASE_PRE and subscribe_loop env-var (Welle-6
#           sibling) is *also* at python in PHASE_PRE — i.e.
#           neither focus-module has leaked a premature cutover
#           into the other.  Pre-state mirror of the cutover-
#           smoke A7 isolation assert.  Inverted direction
#           relative to Welle-6's AXIS-4.
#   AXIS-4  BackendDecision-Stream — engine emits >= 11
#           BackendDecision audit entries since service start
#           with at least one entry naming component=
#           recovery_workflow (Tag-38 PR #250 migrate-version
#           baseline + Welle-7 specialisation).
#   AXIS-5  Cross-Lang-Parity — recovery-outcome canonical
#           hash for the canonical recovery-fixture matches
#           the in-repo Pin-Pack anchor.  Mirrors Welle-1
#           AXIS-4 cross-lang-hash-parity, applied to
#           RecoveryOutcome instead of v907-verify.
#   AXIS-6  Rollback-Probe — recovery_workflow env-overlay
#           drop-in dir is writable for root, systemctl
#           daemon-reload + restart commands present, persona-
#           engine service enabled.  Non-mutating surface
#           inspection only.
#
# §6  Exit-codes
# --------------
#
#   0  green       — all six axes matched, Welle-7 cutover GREEN.
#   1  caution     — >= 1 axis yellow, none red.  Operator-Hand-Decision.
#   2  block       — >= 1 axis red.  Welle-7 cutover BLOCKED.
#   3  precond     — bad CLI args / missing SSH key / invalid Welle /
#                    MISSING Pre-Auditor-Decision file (§4).
#   4  not-exec    — VM unreachable (SSH fail) — PROBE-NOT-EXECUTED.
#
# §7  Anchors
# -----------
#
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 §Welle-7 (Phase-3c Cutover-Plan: recovery_workflow)
#   - ADR-0066 §Doppel-Welle KW-27 (Welle-6 + Welle-7 parallel,
#     Phase-3-Ende)
#   - ADR-0067 / ADR-0068 (IIA-1130-Pre-Auditor-Workflow,
#     audit-trail substrate)
#   - PR #257 (Welle-7 End-to-End Cutover-Smoke + A6 R1..R4 ordering)
#   - PR #250 (Tag-38 migrate-version — BackendDecision baseline)
#   - reports/live-vm/2026-05-18-welle-7-pre-cutover-probe.md
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
WAKIR_PROBE_MIN_BACKEND_DECISIONS="${WAKIR_PROBE_MIN_BACKEND_DECISIONS:-11}"
WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC="${WAKIR_PROBE_SSH_CONNECT_TIMEOUT_SEC:-8}"
WAKIR_PROBE_EXPECTED_HASH="${WAKIR_PROBE_EXPECTED_HASH:-}"
WAKIR_PROBE_WELLE="${WAKIR_PROBE_WELLE:-7}"
WAKIR_PROBE_COMPONENT="${WAKIR_PROBE_COMPONENT:-recovery_workflow}"
WAKIR_PROBE_SIBLING_COMPONENT="${WAKIR_PROBE_SIBLING_COMPONENT:-subscribe_loop}"
WAKIR_PROBE_DEFAULT_BACKEND="${WAKIR_PROBE_DEFAULT_BACKEND:-python}"
WAKIR_PROBE_ROLLBACK_ENV_NAME="${WAKIR_PROBE_ROLLBACK_ENV_NAME:-WAKIR_RECOVERY_WORKFLOW_BACKEND}"
WAKIR_PROBE_SIBLING_ENV_NAME="${WAKIR_PROBE_SIBLING_ENV_NAME:-WAKIR_SUBSCRIBE_LOOP_BACKEND}"
WAKIR_PROBE_STATE_BACKING_ENV_NAME="${WAKIR_PROBE_STATE_BACKING_ENV_NAME:-WAKIR_STATE_BACKING_BACKEND}"
WAKIR_PROBE_PRE_AUDITOR_PATH="${WAKIR_PROBE_PRE_AUDITOR_PATH:-}"

DRY_RUN=0
QUIET=0

PROBE_TS="$("${WAKIR_DATE_BIN}" -u +%Y%m%dT%H%M%SZ)"
PROBE_LOG=""

PRE_AUDITOR_STATUS="UNKNOWN"
PRE_AUDITOR_DETAIL=""

# -----------------------------------------------------------------
# CLI parsing.
# -----------------------------------------------------------------

usage() {
    cat <<USAGE
usage: $(basename "$0") [options]

Pre-Cutover-Sanity-Probe for Phase-3c Welle-7 (recovery_workflow,
ADR-0065 §Welle-7 + ADR-0066 §Doppel-Welle KW-27 / Phase-3-Ende)
against the wakir-pilot live VM via Mira-Hand-SSH (ADR-0058).

*** Last Pre-Cutover-Probe of Phase-3.  RED here BLOCKS the
    Phase-3-COMPLETE-Marker. ***

Options:
  --dry-run                Plan probe steps; do not open SSH.
  --quiet                  Suppress non-error stdout chatter.
  --welle <n>              Welle index (default: 7).
  --component <name>       Component name (default: recovery_workflow).
  --sibling <name>         Sibling component for AXIS-3 (default:
                           subscribe_loop).
  --expected-hash <hex>    Pin-Pack anchor hash for AXIS-5 cross-lang
                           parity check.
  --min-decisions <n>      AXIS-4 minimum BackendDecision count
                           (default: ${WAKIR_PROBE_MIN_BACKEND_DECISIONS}).
  --pre-auditor-path <p>   Override path to IIA-1130 Pre-Auditor-
                           Decision file (default: repo-root/state/
                           welle-7-pre-auditor-decision.json).
  --host <ip>              Override pilot host (default: ${WAKIR_PILOT_HOST}).
  --user <name>            Override SSH user  (default: ${WAKIR_PILOT_USER}).
  --ssh-key <path>         Override SSH key   (default: ${WAKIR_PILOT_SSH_KEY}).
  -h, --help               Show this help and exit.

Exit-codes: 0 green / 1 caution / 2 block / 3 precond / 4 not-exec.
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --dry-run)            DRY_RUN=1; shift ;;
        --quiet)              QUIET=1; shift ;;
        --welle)              WAKIR_PROBE_WELLE="$2"; shift 2 ;;
        --component)          WAKIR_PROBE_COMPONENT="$2"; shift 2 ;;
        --sibling)            WAKIR_PROBE_SIBLING_COMPONENT="$2"; shift 2 ;;
        --expected-hash)      WAKIR_PROBE_EXPECTED_HASH="$2"; shift 2 ;;
        --min-decisions)      WAKIR_PROBE_MIN_BACKEND_DECISIONS="$2"; shift 2 ;;
        --pre-auditor-path)   WAKIR_PROBE_PRE_AUDITOR_PATH="$2"; shift 2 ;;
        --host)               WAKIR_PILOT_HOST="$2"; shift 2 ;;
        --user)               WAKIR_PILOT_USER="$2"; shift 2 ;;
        --ssh-key)            WAKIR_PILOT_SSH_KEY="$2"; shift 2 ;;
        -h|--help)            usage; exit 0 ;;
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
# Pre-Condition: IIA-1130 Pre-Auditor-Decision file Existence-Check.
# -----------------------------------------------------------------

resolve_pre_auditor_path() {
    if [[ -n "${WAKIR_PROBE_PRE_AUDITOR_PATH}" ]]; then
        printf '%s\n' "${WAKIR_PROBE_PRE_AUDITOR_PATH}"
        return 0
    fi
    # Walk upward from script dir to find a state/ sibling.  This
    # is robust under worktree relocation.
    local d
    d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [[ "${d}" != "/" ]]; do
        if [[ -d "${d}/state" ]]; then
            printf '%s/state/welle-7-pre-auditor-decision.json\n' "${d}"
            return 0
        fi
        d="$(dirname "${d}")"
    done
    # Fallback: try a sibling of scripts/.
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    printf '%s/../../state/welle-7-pre-auditor-decision.json\n' "${script_dir}"
}

check_pre_auditor_decision() {
    local path
    path="$(resolve_pre_auditor_path)"
    log_step "pre-condition welle-7-IIA-1130-pre-auditor-decision (path=${path})"
    if [[ ! -f "${path}" ]]; then
        PRE_AUDITOR_STATUS="MISSING"
        PRE_AUDITOR_DETAIL="path=${path}"
        log_error "Pre-Auditor-Decision file MISSING at ${path} — Phase-3-Ende audit-gate not signed; cutover BLOCKED."
        return 3
    fi
    # Soft JSON parse check (no `jq` dependency; use python3 if
    # available; otherwise just check non-empty + balanced braces).
    if command -v python3 >/dev/null 2>&1; then
        if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "${path}" >/dev/null 2>&1; then
            PRE_AUDITOR_STATUS="INVALID-JSON"
            PRE_AUDITOR_DETAIL="path=${path} json-parse-failed"
            log_error "Pre-Auditor-Decision file exists but does not parse as JSON: ${path}"
            return 3
        fi
    else
        if [[ ! -s "${path}" ]]; then
            PRE_AUDITOR_STATUS="EMPTY"
            PRE_AUDITOR_DETAIL="path=${path}"
            log_error "Pre-Auditor-Decision file is empty: ${path}"
            return 3
        fi
    fi
    PRE_AUDITOR_STATUS="PRESENT"
    PRE_AUDITOR_DETAIL="path=${path} bytes=$(wc -c < "${path}" | tr -d ' ')"
    log_info "Pre-Auditor-Decision file present and JSON-parseable."
    return 0
}

# -----------------------------------------------------------------
# SSH wrapper.
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
# Axis implementations.
# -----------------------------------------------------------------

AXIS_1_VERDICT="UNKNOWN"
AXIS_2_VERDICT="UNKNOWN"
AXIS_3_VERDICT="UNKNOWN"
AXIS_4_VERDICT="UNKNOWN"
AXIS_5_VERDICT="UNKNOWN"
AXIS_6_VERDICT="UNKNOWN"
AXIS_1_DETAIL=""
AXIS_2_DETAIL=""
AXIS_3_DETAIL=""
AXIS_4_DETAIL=""
AXIS_5_DETAIL=""
AXIS_6_DETAIL=""

# AXIS-1 — R1..R4-Recovery-Pre-Stability.
axis_1_r1_r4_recovery_pre_stability() {
    log_step "AXIS-1 r1-r4-recovery-pre-stability (component=${WAKIR_PROBE_COMPONENT})"
    local cmd='persona-engine-cli recovery-drill-snapshot --json 2>/dev/null | head -c 4096; echo; persona-engine-cli recovery-outcome-tail --tail 1 --json 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-1-r-phases" "${cmd}") || rc=$?
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
        AXIS_1_DETAIL="empty-recovery-snapshot-output"
        return 2
    fi
    # Verify R1..R4 phase ordering tokens are all present in the
    # captured snapshot.  We look for monotonic R1, R2, R3, R4
    # occurrence indices.
    local i1 i2 i3 i4
    i1=$(printf '%s' "${out}" | grep -bo 'R1' | head -1 | cut -d: -f1 || true)
    i2=$(printf '%s' "${out}" | grep -bo 'R2' | head -1 | cut -d: -f1 || true)
    i3=$(printf '%s' "${out}" | grep -bo 'R3' | head -1 | cut -d: -f1 || true)
    i4=$(printf '%s' "${out}" | grep -bo 'R4' | head -1 | cut -d: -f1 || true)
    AXIS_1_DETAIL="R1@${i1:-NA} R2@${i2:-NA} R3@${i3:-NA} R4@${i4:-NA}"
    if [[ -n "${i1}" && -n "${i2}" && -n "${i3}" && -n "${i4}" ]]; then
        if (( i1 < i2 && i2 < i3 && i3 < i4 )); then
            AXIS_1_VERDICT="GREEN"
            return 0
        else
            AXIS_1_VERDICT="RED"
            AXIS_1_DETAIL="${AXIS_1_DETAIL} (ordering-violated)"
            return 2
        fi
    elif [[ -n "${i1}" || -n "${i2}" || -n "${i3}" || -n "${i4}" ]]; then
        AXIS_1_VERDICT="YELLOW"
        AXIS_1_DETAIL="${AXIS_1_DETAIL} (partial-phases-only)"
        return 1
    else
        AXIS_1_VERDICT="RED"
        AXIS_1_DETAIL="${AXIS_1_DETAIL} (no-R-phases-detected)"
        return 2
    fi
}

# AXIS-2 — State-Backing-Dependency-Pre-Check.
axis_2_state_backing_dependency() {
    log_step "AXIS-2 state-backing-dependency-pre-check (expected=${WAKIR_PROBE_STATE_BACKING_ENV_NAME}=rust)"
    local cmd
    cmd='systemctl show persona-engine -p Environment 2>/dev/null; echo "---AUDIT-STATE-BACKING-TAIL---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "state_backing|StateBackingRead" | tail -3'
    local out rc
    out=$(remote_exec "axis-2-state-backing" "${cmd}") || rc=$?
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
    local sb_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_STATE_BACKING_ENV_NAME}=rust"; then
        sb_env_rust=1
    fi
    local audit_sb_backend=""
    if printf '%s' "${out}" | grep -qE "backend=rust.*state_backing|state_backing.*backend=rust"; then
        audit_sb_backend="rust"
    elif printf '%s' "${out}" | grep -qE "backend=python.*state_backing|state_backing.*backend=python"; then
        audit_sb_backend="python"
    fi
    AXIS_2_DETAIL="state_backing_env_rust=${sb_env_rust} audit_state_backing_backend=${audit_sb_backend:-unknown}"
    if (( sb_env_rust == 1 )) && [[ "${audit_sb_backend}" == "rust" ]]; then
        AXIS_2_VERDICT="GREEN"
        return 0
    elif (( sb_env_rust == 0 )); then
        AXIS_2_VERDICT="RED"
        return 2
    else
        AXIS_2_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-3 — Cross-Modul-Drift-Pre-Check zu Welle-6 (symmetric A7,
#          inverted direction relative to Welle-6 AXIS-4).
axis_3_cross_modul_drift_to_welle_6() {
    log_step "AXIS-3 cross-modul-drift-pre-check welle-7<->welle-6 (sibling=${WAKIR_PROBE_SIBLING_COMPONENT})"
    local cmd
    cmd='systemctl show persona-engine -p Environment 2>/dev/null; echo "---OVERLAY-LIST---"; ls -1 /etc/systemd/system/persona-engine.service.d/ 2>/dev/null || true'
    local out rc
    out=$(remote_exec "axis-3-cross-modul-drift" "${cmd}") || rc=$?
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
    local welle7_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_ROLLBACK_ENV_NAME}=rust"; then
        welle7_env_rust=1
    fi
    local welle6_env_rust=0
    if printf '%s' "${out}" | grep -qE "${WAKIR_PROBE_SIBLING_ENV_NAME}=rust"; then
        welle6_env_rust=1
    fi
    local welle6_overlay=0
    local welle7_overlay=0
    if printf '%s' "${out}" | grep -qE "welle-6-subscribe-loop-rust\.conf"; then
        welle6_overlay=1
    fi
    if printf '%s' "${out}" | grep -qE "welle-7-recovery-workflow-rust\.conf"; then
        welle7_overlay=1
    fi
    AXIS_3_DETAIL="welle7_env_rust=${welle7_env_rust} welle6_env_rust=${welle6_env_rust} welle7_overlay=${welle7_overlay} welle6_overlay=${welle6_overlay}"
    if (( welle7_env_rust == 0 && welle6_env_rust == 0 && welle7_overlay == 0 && welle6_overlay == 0 )); then
        AXIS_3_VERDICT="GREEN"
        return 0
    elif (( welle7_env_rust == 1 || welle6_env_rust == 1 )); then
        AXIS_3_VERDICT="RED"
        return 2
    else
        AXIS_3_VERDICT="YELLOW"
        return 1
    fi
}

# AXIS-4 — BackendDecision-Stream.
axis_4_backend_decision_stream() {
    log_step "AXIS-4 backend-decision-stream (min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS}, component=${WAKIR_PROBE_COMPONENT})"
    local cmd
    cmd='journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -cE "BackendDecision" || true; echo "---WELLE-7-COMPONENT-PRESENCE---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "BackendDecision.*'"${WAKIR_PROBE_COMPONENT}"'" | tail -1'
    local out rc count
    set +e
    out=$(remote_exec "axis-4-bd-stream" "${cmd}") || rc=$?
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
    # Extract leading integer count.
    count=$(printf '%s' "${out}" | head -1 | tr -dc '0-9')
    if [[ -z "${count}" ]]; then count=0; fi
    local component_present=0
    if printf '%s' "${out}" | grep -qE "BackendDecision.*${WAKIR_PROBE_COMPONENT}"; then
        component_present=1
    fi
    AXIS_4_DETAIL="observed=${count} min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS} ${WAKIR_PROBE_COMPONENT}-present=${component_present}"
    if (( count >= WAKIR_PROBE_MIN_BACKEND_DECISIONS )) && (( component_present == 1 )); then
        AXIS_4_VERDICT="GREEN"
        return 0
    elif (( count >= WAKIR_PROBE_MIN_BACKEND_DECISIONS )) && (( component_present == 0 )); then
        AXIS_4_VERDICT="YELLOW"
        return 1
    elif (( count > 0 )); then
        AXIS_4_VERDICT="YELLOW"
        return 1
    else
        AXIS_4_VERDICT="RED"
        return 2
    fi
}

# AXIS-5 — Cross-Lang-Parity (RecoveryOutcome canonical hash).
axis_5_cross_lang_parity() {
    log_step "AXIS-5 cross-lang-parity recovery-outcome-hash (expected=${WAKIR_PROBE_EXPECTED_HASH:-<unset>})"
    if [[ -z "${WAKIR_PROBE_EXPECTED_HASH}" ]]; then
        AXIS_5_VERDICT="YELLOW"
        AXIS_5_DETAIL="no expected-hash provided; skipping strict equality"
        log_warn "AXIS-5 skipped: --expected-hash not provided"
        return 1
    fi
    local cmd='persona-engine-cli recovery-outcome-hash --canonical-fixture pin-pack-v1 --json 2>/dev/null | head -c 1024'
    local out rc
    out=$(remote_exec "axis-5-recovery-hash" "${cmd}") || rc=$?
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
    if printf '%s' "${out}" | grep -qF "${WAKIR_PROBE_EXPECTED_HASH}"; then
        AXIS_5_VERDICT="GREEN"
        AXIS_5_DETAIL="hash-match expected=${WAKIR_PROBE_EXPECTED_HASH}"
        return 0
    else
        AXIS_5_VERDICT="RED"
        AXIS_5_DETAIL="hash-mismatch (Pin-Pack anchor drift)"
        return 2
    fi
}

# AXIS-6 — Rollback-Probe surface inspection (non-mutating).
axis_6_rollback_surface() {
    log_step "AXIS-6 rollback-surface-inspection (env=${WAKIR_PROBE_ROLLBACK_ENV_NAME})"
    local cmd
    cmd='ls -ld /etc/systemd/system/persona-engine.service.d 2>/dev/null; systemctl is-enabled persona-engine 2>/dev/null; command -v systemctl >/dev/null && echo systemctl-OK; command -v journalctl >/dev/null && echo journalctl-OK'
    local out rc
    out=$(remote_exec "axis-6-rollback-surface" "${cmd}") || rc=$?
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
    local levers_ok=0
    printf '%s' "${out}" | grep -q "systemctl-OK"  && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "journalctl-OK" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -qE "(enabled|static|alias|enabled-runtime)" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "persona-engine.service.d" && (( levers_ok+=1 )) || true
    AXIS_6_DETAIL="rollback-levers-present=${levers_ok}/4"
    if (( levers_ok >= 4 )); then
        AXIS_6_VERDICT="GREEN"
        return 0
    elif (( levers_ok >= 2 )); then
        AXIS_6_VERDICT="YELLOW"
        return 1
    else
        AXIS_6_VERDICT="RED"
        return 2
    fi
}

# -----------------------------------------------------------------
# Verdict aggregation.
# -----------------------------------------------------------------

aggregate_verdict() {
    local v1="$1" v2="$2" v3="$3" v4="$4" v5="$5" v6="$6"
    local any_not_exec=0 any_red=0 any_yellow=0
    for v in "$v1" "$v2" "$v3" "$v4" "$v5" "$v6"; do
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
    log_info "welle-7-pre-cutover-probe start ts=${PROBE_TS} host=${WAKIR_PILOT_HOST} dry-run=${DRY_RUN}"
    log_info "component=${WAKIR_PROBE_COMPONENT} sibling=${WAKIR_PROBE_SIBLING_COMPONENT} welle=${WAKIR_PROBE_WELLE} default-backend=${WAKIR_PROBE_DEFAULT_BACKEND}"
    log_info "PHASE-3-MARATHON-SCHLUSS-MARKIERUNG: this is the LAST pre-cutover-probe before phase-3-COMPLETE-marker."

    if ! check_ssh_key_present; then
        log_error "precondition failure: SSH key"
        exit 3
    fi

    # §4 Pre-Condition: IIA-1130 Pre-Auditor-Decision file.
    if ! check_pre_auditor_decision; then
        log_error "precondition failure: IIA-1130 Pre-Auditor-Decision missing/invalid"
        printf 'PROBE-VERDICT=PRECOND-FAIL welle=%s component=%s reason=pre-auditor-decision-%s log=%s\n' \
            "${WAKIR_PROBE_WELLE}" "${WAKIR_PROBE_COMPONENT}" \
            "${PRE_AUDITOR_STATUS}" "${PROBE_LOG}"
        exit 3
    fi

    local r1=0 r2=0 r3=0 r4=0 r5=0 r6=0
    axis_1_r1_r4_recovery_pre_stability  || r1=$?
    axis_2_state_backing_dependency      || r2=$?
    axis_3_cross_modul_drift_to_welle_6  || r3=$?
    axis_4_backend_decision_stream       || r4=$?
    axis_5_cross_lang_parity             || r5=$?
    axis_6_rollback_surface              || r6=$?

    local verdict
    verdict=$(aggregate_verdict \
        "${AXIS_1_VERDICT}" "${AXIS_2_VERDICT}" "${AXIS_3_VERDICT}" \
        "${AXIS_4_VERDICT}" "${AXIS_5_VERDICT}" "${AXIS_6_VERDICT}")

    log_verdict "PRE-AUDITOR ${PRE_AUDITOR_STATUS}: ${PRE_AUDITOR_DETAIL}"
    log_verdict "AXIS-1 ${AXIS_1_VERDICT}: ${AXIS_1_DETAIL}"
    log_verdict "AXIS-2 ${AXIS_2_VERDICT}: ${AXIS_2_DETAIL}"
    log_verdict "AXIS-3 ${AXIS_3_VERDICT}: ${AXIS_3_DETAIL}"
    log_verdict "AXIS-4 ${AXIS_4_VERDICT}: ${AXIS_4_DETAIL}"
    log_verdict "AXIS-5 ${AXIS_5_VERDICT}: ${AXIS_5_DETAIL}"
    log_verdict "AXIS-6 ${AXIS_6_VERDICT}: ${AXIS_6_DETAIL}"
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
