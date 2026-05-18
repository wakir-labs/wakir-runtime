#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# live-vm-cutover-drill.sh — Phase-3c SSH-Hand Cutover-Drill (Tag-40)
# -------------------------------------------------------------------
#
# Purpose
#   Executes the SSH-based Mira-Hand cutover sequence against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) per Welle.  This script
#   is the operator-day-of marathon driver that wires together the
#   per-Welle §3.3..§3.5 + §6 steps documented in
#   docs/phase-3c/welle-{1..7}-*-runbook.md into one machine-parseable
#   sequence.
#
#   The drill is parametrised by Welle-Index + Action so each step
#   (pre / cutover / post / rollback) can be replayed independently
#   for incident-response, and a `--full-marathon` mode walks all
#   seven Wellen in the ADR-0066 Doppel-Welle order respecting the
#   sequence gates (Welle-1 → Welle-2 → Welle-3 → Welle-4+5 parallel
#   → Welle-6+7 parallel).
#
# Authority
#   Mira-Hand-SSH per ADR-0058 §Nachtrag (approved KW-20).  All
#   operations executed here fall under the autark Operator-Hand
#   surface (systemctl restart, env-overlay drop-ins, journal reads,
#   service-status checks).  No AR escalation required during the
#   cutover-window; AR sign-off is post-hoc per each Welle-runbook §7.
#
# Sandbox boundary
#   The drill itself never executes podman / systemctl locally — it
#   shells into ${WAKIR_PILOT_HOST} over SSH.  The Mira-sandbox vs.
#   live-VM separation is preserved: --dry-run prints every command
#   without dispatching it.  The hermetic test suite stubs `ssh` via
#   $WAKIR_SSH_BIN so no real SSH connection is opened in CI.
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0065 (Phase-3c Cutover-Plan)
#   - ADR-0066 (Phase-3c Beschleunigung Option-A+; Doppel-Welle order)
#   - docs/phase-3c/welle-{1..7}-*-runbook.md (per-Welle §3.4 + §3.5)
#   - docs/phase-3c/live-vm-cutover-drill.md (operator-doku)
#
# Exit-codes
#   0  green       — drill step completed; verify matched expectation.
#   1  yellow      — non-fatal anomaly (e.g. fewer than required
#                    BackendDecision hits within wait-loop but >= 1).
#                    Operator-Hand-Decision required.
#   2  red         — fatal: SSH unreachable, verify failed, or sequence
#                    gate violated.  Stop the marathon.
#   3  precond     — pre-condition not met (e.g. unknown Welle index,
#                    invalid action, missing SSH-key, prior Welle not
#                    signed-off in --full-marathon mode).
#
# Author: Kai Hoffmann (DevOps), Sprint-Tag-40, 2026-05-18.
# ----------------------------------------------------------------------

set -euo pipefail

# ----------------------------------------------------------------------
# Defaults — overridable via env or CLI.
# ----------------------------------------------------------------------

WAKIR_PILOT_HOST="${WAKIR_PILOT_HOST:-192.168.178.116}"
WAKIR_PILOT_USER="${WAKIR_PILOT_USER:-root}"
WAKIR_PILOT_SSH_KEY="${WAKIR_PILOT_SSH_KEY:-${HOME}/.ssh/wakir-pilot-vm-diagnose}"
WAKIR_SSH_BIN="${WAKIR_SSH_BIN:-ssh}"
WAKIR_SCP_BIN="${WAKIR_SCP_BIN:-scp}"
WAKIR_DATE_BIN="${WAKIR_DATE_BIN:-date}"
WAKIR_DRILL_LOG_DIR="${WAKIR_DRILL_LOG_DIR:-/tmp/wakir-cutover-drill}"
WAKIR_DRILL_SNAPSHOT_DIR="${WAKIR_DRILL_SNAPSHOT_DIR:-/var/lib/wakir/cutover-drill}"
WAKIR_BOOT_AUDIT_TIMEOUT_SEC="${WAKIR_BOOT_AUDIT_TIMEOUT_SEC:-30}"
WAKIR_BOOT_AUDIT_MIN_HITS="${WAKIR_BOOT_AUDIT_MIN_HITS:-5}"
WAKIR_SIGNOFF_DIR_HOST="${WAKIR_SIGNOFF_DIR_HOST:-/var/home/fred/AI-Corp/agents-workspaces/henrik/audit}"

# ----------------------------------------------------------------------
# Welle-Matrix.  Source of truth for per-Welle metadata.
#
# Format per row (TAB-separated):
#   welle | component | env_vars (comma-sep) | env_value | overlay_basename
# ----------------------------------------------------------------------

# shellcheck disable=SC2034 # parsed below via select_welle()
WELLE_MATRIX=$(cat <<'WELLE_EOF'
1	v907_verify	WAKIR_V907_VERIFY_BACKEND	rust	welle-1-v907-verify-rust.conf
2	svid_workload_identity	WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND	rust	welle-2-svid-workload-identity-rust.conf
3	bridge_audit_writer	WAKIR_BRIDGE_AUDIT_WRITER_BACKEND,WAKIR_ANCHOR_EMITTER_BACKEND	rust	welle-3-bridge-audit-writer-rust.conf
4	state_backing	WAKIR_STATE_BACKING_BACKEND	rust_inmemory	welle-4-state-backing-rust.conf
5	lifecycle_state_machine	WAKIR_FSM_BACKEND	rust	welle-5-lifecycle-state-machine-rust.conf
6	subscribe_loop	WAKIR_SUBSCRIBE_LOOP_BACKEND	rust	welle-6-subscribe-loop-rust.conf
7	recovery_workflow	WAKIR_RECOVERY_BACKEND	rust	welle-7-recovery-workflow-rust.conf
WELLE_EOF
)

# Sequence gates: Welle X requires sign-off file for the listed parents.
# 1: (root)
# 2: 1
# 3: 1, 2
# 4: 1, 2, 3
# 5: 1, 2, 3       (parallel to 4)
# 6: 1, 2, 3, 4, 5
# 7: 1, 2, 3, 4, 5 (parallel to 6)
welle_gate_parents() {
    case "$1" in
        1) echo "" ;;
        2) echo "1" ;;
        3) echo "1 2" ;;
        4) echo "1 2 3" ;;
        5) echo "1 2 3" ;;
        6) echo "1 2 3 4 5" ;;
        7) echo "1 2 3 4 5" ;;
        *) echo "" ;;
    esac
}

# Sequence of execution in --full-marathon (ADR-0066 Doppel-Welle order).
# Welle 4+5 parallel; Welle 6+7 parallel.  In drill mode we serialise
# them (run 4 then 5 then 6 then 7) — true parallelism is a live-window
# operator-decision, not a drill-script decision.
MARATHON_ORDER=(1 2 3 4 5 6 7)

# ----------------------------------------------------------------------
# Logging helpers.
# ----------------------------------------------------------------------

DRILL_TS="$("${WAKIR_DATE_BIN}" -u +%Y%m%dT%H%M%SZ)"
DRILL_LOG=""

log() {
    local level="$1"
    shift
    local msg="$*"
    local stamp
    stamp="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '[%s] [%-6s] %s\n' "${stamp}" "${level}" "${msg}"
    if [[ -n "${DRILL_LOG}" ]]; then
        printf '[%s] [%-6s] %s\n' "${stamp}" "${level}" "${msg}" >> "${DRILL_LOG}"
    fi
}

log_info()  { log INFO  "$@"; }
log_warn()  { log WARN  "$@"; }
log_error() { log ERROR "$@" >&2; }
log_step()  { log STEP  "$@"; }

# ----------------------------------------------------------------------
# Welle matrix accessors.  Public for unit tests.
# ----------------------------------------------------------------------

select_welle() {
    # Echoes the matrix row for the requested Welle index.  Exits 3 if
    # the Welle is unknown.
    local idx="$1"
    local row
    row=$(printf '%s\n' "${WELLE_MATRIX}" | awk -F'\t' -v w="${idx}" '$1==w {print; exit}')
    if [[ -z "${row}" ]]; then
        log_error "select_welle: unknown welle index '${idx}'"
        return 3
    fi
    printf '%s\n' "${row}"
}

welle_field() {
    # welle_field <idx> <column>   where column ∈ {1..5}.
    local idx="$1"
    local col="$2"
    local row
    row=$(select_welle "${idx}") || return 3
    printf '%s\n' "${row}" | awk -F'\t' -v c="${col}" '{print $c}'
}

welle_component()        { welle_field "$1" 2; }
welle_env_vars()         { welle_field "$1" 3; }
welle_env_value()        { welle_field "$1" 4; }
welle_overlay_basename() { welle_field "$1" 5; }

# ----------------------------------------------------------------------
# SSH-Bind: every remote operation goes through here.  Tests stub
# $WAKIR_SSH_BIN to a fake.
# ----------------------------------------------------------------------

remote_exec() {
    # remote_exec "<cmd>"
    local cmd="$1"
    local ssh_target="${WAKIR_PILOT_USER}@${WAKIR_PILOT_HOST}"
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        log_info "DRY-RUN ssh ${ssh_target}: ${cmd}"
        return 0
    fi
    "${WAKIR_SSH_BIN}" \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=accept-new \
        -i "${WAKIR_PILOT_SSH_KEY}" \
        "${ssh_target}" \
        "${cmd}"
}

check_ssh_key_present() {
    # SSH-key existence pre-check.  Skipped in dry-run.
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        return 0
    fi
    if [[ ! -r "${WAKIR_PILOT_SSH_KEY}" ]]; then
        log_error "SSH key not readable at ${WAKIR_PILOT_SSH_KEY}"
        return 3
    fi
    return 0
}

# ----------------------------------------------------------------------
# Sequence-gate enforcement: requires all parents to have a sign-off
# marker file in $WAKIR_DRILL_LOG_DIR/signoff/welle-<idx>.signoff before
# the requested Welle action may proceed in marathon mode.  Solo runs
# can opt out via --skip-gate (operator-hand replay).
# ----------------------------------------------------------------------

ensure_signoff_dir() {
    mkdir -p "${WAKIR_DRILL_LOG_DIR}/signoff"
}

mark_welle_signoff() {
    local idx="$1"
    local verdict="$2"
    ensure_signoff_dir
    local marker="${WAKIR_DRILL_LOG_DIR}/signoff/welle-${idx}.signoff"
    {
        printf 'welle=%s\n' "${idx}"
        printf 'verdict=%s\n' "${verdict}"
        printf 'timestamp=%s\n' "$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "${marker}"
    log_info "wrote sign-off marker ${marker}"
}

check_sequence_gate() {
    local idx="$1"
    if [[ "${SKIP_GATE:-0}" == "1" ]]; then
        log_warn "sequence-gate skipped via --skip-gate for welle=${idx}"
        return 0
    fi
    local parents
    parents=$(welle_gate_parents "${idx}")
    if [[ -z "${parents}" ]]; then
        return 0
    fi
    ensure_signoff_dir
    local missing=()
    for p in ${parents}; do
        local marker="${WAKIR_DRILL_LOG_DIR}/signoff/welle-${p}.signoff"
        if [[ ! -r "${marker}" ]]; then
            missing+=("${p}")
            continue
        fi
        local verdict
        verdict=$(awk -F= '$1=="verdict" {print $2}' "${marker}")
        if [[ "${verdict}" != "green" && "${verdict}" != "green-with-yellow-notes" ]]; then
            log_error "welle=${p} sign-off verdict=${verdict} (need green)"
            return 3
        fi
    done
    if (( ${#missing[@]} > 0 )); then
        log_error "missing sign-off for parent welle(s): ${missing[*]}"
        return 3
    fi
    return 0
}

# ----------------------------------------------------------------------
# Pre-Cutover-Snapshot (§3.2 + Tag-40 state-snapshot for rollback
# substrate).  Captures service-status, journal-tail, env overlay
# listing into $WAKIR_DRILL_SNAPSHOT_DIR/welle-<idx>-<ts>.tar.
# ----------------------------------------------------------------------

action_pre() {
    local idx="$1"
    local ts="${2:-${DRILL_TS}}"
    local component
    component=$(welle_component "${idx}")
    log_step "pre: welle=${idx} component=${component} ts=${ts}"

    check_sequence_gate "${idx}" || return 3

    local snapshot_path="${WAKIR_DRILL_SNAPSHOT_DIR}/welle-${idx}-${ts}"
    remote_exec "install -d -m 0750 '${snapshot_path}'" || return 2
    remote_exec "systemctl status wakir-persona-engine.service --no-pager > '${snapshot_path}/service-status.txt' 2>&1; true" || return 2
    remote_exec "journalctl -u wakir-persona-engine.service --since '-30 min' --no-pager > '${snapshot_path}/journal-pre.txt' 2>&1; true" || return 2
    remote_exec "ls -la /etc/systemd/system/wakir-persona-engine.service.d/ > '${snapshot_path}/overlay-listing.txt' 2>&1; true" || return 2
    remote_exec "echo welle=${idx} component=${component} ts=${ts} > '${snapshot_path}/manifest.txt'" || return 2

    log_info "pre-snapshot captured at ${snapshot_path}"
    return 0
}

# ----------------------------------------------------------------------
# Cutover-Step (§3.3 + §3.4 + §3.5 of per-Welle runbook).  Writes the
# overlay drop-in, daemon-reload, restart service, wait-loop for
# BackendDecision records with backend=<env_value>.
# ----------------------------------------------------------------------

action_cutover() {
    local idx="$1"
    local ts="${2:-${DRILL_TS}}"
    local component env_vars env_value overlay
    component=$(welle_component "${idx}")
    env_vars=$(welle_env_vars "${idx}")
    env_value=$(welle_env_value "${idx}")
    overlay=$(welle_overlay_basename "${idx}")
    log_step "cutover: welle=${idx} component=${component} env_vars=${env_vars} value=${env_value}"

    check_sequence_gate "${idx}" || return 3

    # Build the Environment="..." lines for every env var of this Welle.
    # Each line is appended with a literal newline so the overlay file
    # rendered on the pilot VM matches the Welle-runbook §3.3 template.
    local env_lines=""
    local IFS_BACKUP="${IFS}"
    IFS=','
    for var in ${env_vars}; do
        env_lines+=$(printf 'Environment="%s=%s"\n' "${var}" "${env_value}")
        env_lines+=$'\n'
    done
    IFS="${IFS_BACKUP}"

    local overlay_dir='/etc/systemd/system/wakir-persona-engine.service.d'
    remote_exec "install -d -m 0755 '${overlay_dir}'" || return 2

    # Write the overlay file atomically.  printf %q is used so the body
    # round-trips safely through the SSH shell layer.
    local overlay_path="${overlay_dir}/${overlay}"
    local overlay_body
    overlay_body=$(printf '# Phase-3c Welle-%s Cutover-Overlay\n# Generated: %s\n# ADR-0065 §Welle-%s\n[Service]\n%s' "${idx}" "${ts}" "${idx}" "${env_lines}")
    remote_exec "umask 0022 && printf '%s' $(printf '%q' "${overlay_body}") > '${overlay_path}'" || return 2
    remote_exec "systemctl daemon-reload" || return 2

    local ts_restart
    ts_restart="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    remote_exec "systemctl restart wakir-persona-engine.service" || return 2
    log_info "restart issued at ${ts_restart}"

    # Boot-audit wait-loop: scan journal for ≥ N BackendDecision records
    # carrying this component and backend=${env_value}.
    if wait_for_backend_decisions "${idx}" "${component}" "${env_value}" "${ts_restart}"; then
        log_info "cutover boot-audit passed for welle=${idx}"
        return 0
    fi

    log_error "cutover boot-audit FAILED for welle=${idx}; consider --action rollback"
    return 2
}

# ----------------------------------------------------------------------
# Post-Cutover-Verify (§4 condensed): parse BackendDecision stream and
# confirm correct backend for the welle.  This is the lightweight verify
# bundled with the drill; full §4 Soak-Window verify lives in the
# Welle-runbook §4.1..§4.4.
# ----------------------------------------------------------------------

action_post() {
    local idx="$1"
    local ts="${2:-${DRILL_TS}}"
    local component env_value
    component=$(welle_component "${idx}")
    env_value=$(welle_env_value "${idx}")
    log_step "post: welle=${idx} component=${component} expecting backend=${env_value}"

    # Allow a synthetic "since" timestamp from the cutover phase; default
    # to last 5 min as a smoke window.
    local since_ts="${POST_SINCE:--5 min}"
    if wait_for_backend_decisions "${idx}" "${component}" "${env_value}" "${since_ts}"; then
        log_info "post-verify green for welle=${idx}"
        return 0
    fi

    log_error "post-verify failed for welle=${idx}; backend!=${env_value} or stream empty"
    return 2
}

# ----------------------------------------------------------------------
# Rollback-Path (§6): remove overlay, daemon-reload, restart, verify
# backend=python.
# ----------------------------------------------------------------------

action_rollback() {
    local idx="$1"
    local ts="${2:-${DRILL_TS}}"
    local component overlay
    component=$(welle_component "${idx}")
    overlay=$(welle_overlay_basename "${idx}")
    log_step "rollback: welle=${idx} component=${component} overlay=${overlay}"

    local overlay_dir='/etc/systemd/system/wakir-persona-engine.service.d'
    remote_exec "rm -f '${overlay_dir}/${overlay}'" || return 2
    remote_exec "systemctl daemon-reload" || return 2

    local ts_restart
    ts_restart="$("${WAKIR_DATE_BIN}" -u +%Y-%m-%dT%H:%M:%SZ)"
    remote_exec "systemctl restart wakir-persona-engine.service" || return 2
    log_info "rollback restart issued at ${ts_restart}"

    if wait_for_backend_decisions "${idx}" "${component}" "python" "${ts_restart}"; then
        log_info "rollback verified: backend=python for welle=${idx}"
        return 0
    fi

    log_error "rollback verification FAILED for welle=${idx}; backend did not return to python"
    return 2
}

# ----------------------------------------------------------------------
# Wait-Loop: spawn a remote journalctl tail and grep for the expected
# BackendDecision records.  Returns:
#   0  >= WAKIR_BOOT_AUDIT_MIN_HITS within timeout
#   1  1..MIN_HITS-1 hits within timeout (yellow)
#   2  0 hits within timeout (red)
# ----------------------------------------------------------------------

wait_for_backend_decisions() {
    local idx="$1"
    local component="$2"
    local backend="$3"
    local since_ts="$4"
    local timeout_sec="${WAKIR_BOOT_AUDIT_TIMEOUT_SEC}"
    local min_hits="${WAKIR_BOOT_AUDIT_MIN_HITS}"

    log_info "wait_for_backend_decisions welle=${idx} component=${component} backend=${backend} timeout=${timeout_sec}s min_hits=${min_hits}"

    # The remote command emits any number of journal records; we count
    # via grep -c.  Using `timeout` on the remote side keeps the SSH
    # connection bounded even if journalctl tails indefinitely.
    local remote_cmd
    remote_cmd=$(cat <<REMOTE_EOF
timeout ${timeout_sec} journalctl -u wakir-persona-engine.service --since '${since_ts}' --no-pager --output=cat 2>/dev/null \
  | grep -c -E 'BackendDecision.*${component}.*backend=${backend}' \
  || true
REMOTE_EOF
)
    local hits
    if [[ "${DRY_RUN:-0}" == "1" ]]; then
        log_info "DRY-RUN wait_for_backend_decisions ssh: ${remote_cmd}"
        hits="${WAKIR_FAKE_BOOT_HITS:-${min_hits}}"
    else
        hits=$(remote_exec "${remote_cmd}" | tail -n 1 | tr -d '[:space:]')
    fi

    if [[ -z "${hits}" ]] || ! [[ "${hits}" =~ ^[0-9]+$ ]]; then
        log_error "wait-loop hit-count not parseable: '${hits}'"
        return 2
    fi

    log_info "wait-loop hits=${hits} (min required=${min_hits})"
    if (( hits >= min_hits )); then
        return 0
    fi
    if (( hits >= 1 )); then
        return 1
    fi
    return 2
}

# ----------------------------------------------------------------------
# Full-Marathon orchestrator.  Walks ${MARATHON_ORDER}, executes
# pre→cutover→post for each Welle, marks sign-off, then continues.
# Stops on first non-zero verdict.  Rollback is NOT automatic in
# marathon mode (operator-hand-decision per ADR-0058 §Nachtrag).
# ----------------------------------------------------------------------

action_full_marathon() {
    local ts="${1:-${DRILL_TS}}"
    log_step "full-marathon ts=${ts} order=${MARATHON_ORDER[*]}"

    for idx in "${MARATHON_ORDER[@]}"; do
        log_info "=== full-marathon: welle=${idx} ==="
        action_pre "${idx}" "${ts}" || {
            log_error "marathon halted at pre-snapshot welle=${idx}"
            return 2
        }
        action_cutover "${idx}" "${ts}" || {
            log_error "marathon halted at cutover welle=${idx}"
            return 2
        }
        action_post "${idx}" "${ts}" || {
            log_error "marathon halted at post-verify welle=${idx}"
            return 2
        }
        mark_welle_signoff "${idx}" "green"
        log_info "marathon: welle=${idx} green; advancing"
    done
    log_info "full-marathon completed for all wellen 1..7"
    return 0
}

# ----------------------------------------------------------------------
# Argument parsing.
# ----------------------------------------------------------------------

usage() {
    cat <<'USAGE_EOF'
live-vm-cutover-drill.sh — Phase-3c SSH-Hand Cutover-Drill

Usage:
  live-vm-cutover-drill.sh --welle N --action ACTION [options]
  live-vm-cutover-drill.sh --full-marathon [options]

Required (mode A):
  --welle N           1..7 — target Welle index.
  --action ACTION     pre | cutover | post | rollback

Required (mode B):
  --full-marathon     run wellen 1..7 in ADR-0066 order

Options:
  --dry-run           do not invoke ssh; log every step.
  --skip-gate         skip sequence-gate enforcement (replay mode).
  --log-dir DIR       override drill-log directory.
  --pilot-host HOST   override pilot VM host (env: WAKIR_PILOT_HOST).
  --ssh-key PATH      override SSH key path (env: WAKIR_PILOT_SSH_KEY).
  --min-hits N        override BackendDecision min hits (default 5).
  --timeout-sec N     override wait-loop timeout (default 30).
  -h, --help          show this help.

Exit codes:
  0 green | 1 yellow | 2 red | 3 precondition violated.
USAGE_EOF
}

parse_args() {
    WELLE=""
    ACTION=""
    DRY_RUN=0
    SKIP_GATE=0
    FULL_MARATHON=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --welle)
                WELLE="${2:-}"; shift 2 ;;
            --action)
                ACTION="${2:-}"; shift 2 ;;
            --full-marathon)
                FULL_MARATHON=1; shift ;;
            --dry-run)
                DRY_RUN=1; shift ;;
            --skip-gate)
                SKIP_GATE=1; shift ;;
            --log-dir)
                WAKIR_DRILL_LOG_DIR="${2:-${WAKIR_DRILL_LOG_DIR}}"; shift 2 ;;
            --pilot-host)
                WAKIR_PILOT_HOST="${2:-${WAKIR_PILOT_HOST}}"; shift 2 ;;
            --ssh-key)
                WAKIR_PILOT_SSH_KEY="${2:-${WAKIR_PILOT_SSH_KEY}}"; shift 2 ;;
            --min-hits)
                WAKIR_BOOT_AUDIT_MIN_HITS="${2:-${WAKIR_BOOT_AUDIT_MIN_HITS}}"; shift 2 ;;
            --timeout-sec)
                WAKIR_BOOT_AUDIT_TIMEOUT_SEC="${2:-${WAKIR_BOOT_AUDIT_TIMEOUT_SEC}}"; shift 2 ;;
            -h|--help)
                usage; exit 0 ;;
            *)
                log_error "unknown argument: $1"
                usage >&2
                exit 3 ;;
        esac
    done

    if (( FULL_MARATHON == 1 )); then
        if [[ -n "${WELLE}" || -n "${ACTION}" ]]; then
            log_error "--full-marathon excludes --welle / --action"
            return 3
        fi
    else
        if [[ -z "${WELLE}" || -z "${ACTION}" ]]; then
            log_error "either --full-marathon or (--welle + --action) required"
            usage >&2
            return 3
        fi
        if ! [[ "${WELLE}" =~ ^[1-7]$ ]]; then
            log_error "--welle must be in 1..7 (got '${WELLE}')"
            return 3
        fi
        case "${ACTION}" in
            pre|cutover|post|rollback) ;;
            *)
                log_error "--action must be pre|cutover|post|rollback (got '${ACTION}')"
                return 3 ;;
        esac
    fi
    return 0
}

# ----------------------------------------------------------------------
# Main entrypoint.
# ----------------------------------------------------------------------

main() {
    parse_args "$@" || exit 3

    mkdir -p "${WAKIR_DRILL_LOG_DIR}"
    if (( FULL_MARATHON == 1 )); then
        DRILL_LOG="${WAKIR_DRILL_LOG_DIR}/marathon-${DRILL_TS}.log"
    else
        DRILL_LOG="${WAKIR_DRILL_LOG_DIR}/welle-${WELLE}-${ACTION}-${DRILL_TS}.log"
    fi
    : > "${DRILL_LOG}"
    log_info "drill-log: ${DRILL_LOG}"
    log_info "config: host=${WAKIR_PILOT_HOST} key=${WAKIR_PILOT_SSH_KEY} dry_run=${DRY_RUN} skip_gate=${SKIP_GATE}"

    check_ssh_key_present || exit 3

    if (( FULL_MARATHON == 1 )); then
        action_full_marathon "${DRILL_TS}"
        exit $?
    fi

    case "${ACTION}" in
        pre)      action_pre      "${WELLE}" "${DRILL_TS}" ;;
        cutover)  action_cutover  "${WELLE}" "${DRILL_TS}" ;;
        post)     action_post     "${WELLE}" "${DRILL_TS}" ;;
        rollback) action_rollback "${WELLE}" "${DRILL_TS}" ;;
    esac
    exit $?
}

# Allow sourcing for tests: only run main() when invoked directly.
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" && "${WAKIR_DRILL_TEST_MODE:-0}" != "1" ]]; then
    main "$@"
fi
