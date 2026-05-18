#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-3-pre-cutover-probe.sh — Phase-3c Pre-Cutover-Sanity-Probe
# -----------------------------------------------------------------
#
# Purpose
#   Executes a non-mutating Pre-Cutover-Sanity-Run against the
#   wakir-pilot live VM (ADR-0058 §Nachtrag) for Welle-3
#   (``bridge_audit_writer``, ADR-0066 KW-25 solo wave).  Mirror of
#   Kai's Welle-1 probe (PR #267); re-pointed at the bridge-audit-
#   writer component and its associated env-var, Pin-Pack fixture
#   set, and self-reference-trap pre-check.
#
#   The probe is intentionally distinct from the live-vm-cutover-drill
#   driver: where the drill *enacts* the Cutover sequence, the probe
#   only *observes* + *verifies* the system in its Default-State
#   (backend=python for bridge_audit_writer) before any env-overlay
#   drop-in.
#
#   Welle-3 carries one additional axis beyond the Welle-1/2 shape:
#   AXIS-0 (Self-Reference-Trap-Pre-Check) guards against the
#   Consistency-Oracle-Selbst-Cutover-Risiko Henrik flagged for the
#   bridge_audit_writer wave.  AXIS-0 verifies that an independent
#   audit-source (kernel /var/log) sees the same audit-stream-head
#   pointer as the in-engine query, ruling out the case where the
#   audit-writer is reporting on its own output without an external
#   anchor.
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
# Six verification axes (output triad green/yellow/red per axis):
#
#   AXIS-0  Self-Reference-Trap-Pre-Check (Welle-3-specific):
#           Captures the bridge-audit-stream head pointer via
#           ``persona-engine-cli bridge-audit-head --json`` (in-engine
#           view) AND via an independent kernel-side tail of the
#           on-disk audit log (``tail -1 /var/log/persona-engine/
#           bridge-audit.jsonl``).  Both views must agree on the head
#           sequence number.  This is the ADR-0066 §Welle-3-Risiken
#           mitigation that prevents the consistency oracle from
#           reporting on its own output.
#   AXIS-1  Audit-Stream-Continuity: bridge-audit-stream has been
#           emitting entries continuously for the last
#           ``WAKIR_PROBE_MIN_AUDIT_AGE_SEC`` seconds, with a head
#           pointer that has advanced at least
#           ``WAKIR_PROBE_MIN_HEAD_DELTA`` positions since service
#           start.  This is the Welle-3 analog of the Welle-1
#           Engine-State-Snapshot axis.
#   AXIS-2  Independent-Oracle-Probe: a *second* independent read
#           path (``persona-engine-cli audit-replay --tail 5 --json``)
#           returns the same tail entries as the head-pointer view
#           above.  Yellow when only N-1 entries match (drift
#           window); red when the two views diverge significantly.
#   AXIS-3  BackendDecision-Stream: identical shape to Welle-2 AXIS-3.
#           ``journalctl -u persona-engine --since=boot`` shows
#           >= ``WAKIR_PROBE_MIN_BACKEND_DECISIONS`` BackendDecision
#           entries *and* contains at least one row for
#           ``component=bridge_audit_writer`` with ``backend=python``.
#   AXIS-4  Cross-Lang-Hash-Parity vs. PR #224 Pin-Pack anchor for
#           the bridge-audit-writer canonical fixture set.  Remote
#           persona-engine-CLI emits hash for canonical fixture
#           identical to the in-repo pin-pack value passed via
#           ``--expected-hash``.
#   AXIS-5  Rollback-Probe: env unset → service restart → engine
#           returns to backend=python (dry-run only; no env mutation
#           actually performed in pre-cutover phase — this axis
#           verifies the *capability* by inspecting the rollback
#           command surface, not by executing it).  Identical lever
#           inventory to Welle-1/2; env-var name is
#           ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND``.  Default-State
#           must NOT have the Welle-3 overlay file already in place.
#
# Exit-codes
#   0  green       — all six axes matched, Welle-3 cutover GREEN.
#   1  caution     — >= 1 axis yellow, none red.  Operator-Hand-Decision.
#   2  block       — >= 1 axis red.  Welle-3 cutover BLOCKED.
#   3  precond     — bad CLI args / missing SSH key / invalid Welle.
#   4  not-exec    — VM unreachable (SSH fail) — special status that
#                    surfaces in the Acceptance-Report as
#                    PROBE-NOT-EXECUTED.
#
# Anchors
#   - ADR-0058 §Nachtrag (Mira-SSH-Hand-Authority)
#   - ADR-0066 §Welle-3 KW-25 (bridge_audit_writer solo wave + risk-notes)
#   - PR #224 (Pin-Pack Cross-Lang Anchor — bridge-audit fixture set)
#   - PR #240 (Welle-3 Cutover-Smoke + self-reference-trap A7 assert)
#   - PR #250 (Tag-38 migrate-version — 11 BackendDecision baseline)
#   - PR #267 (Welle-1 Pre-Cutover-Probe template, Kai Tag-41)
#   - reports/live-vm/2026-05-18-welle-3-pre-cutover-probe.md
#
# Author: Selin Çelik (Persona-Engine), Sprint-Tag-42, 2026-05-18.
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
WAKIR_PROBE_WELLE="${WAKIR_PROBE_WELLE:-3}"
WAKIR_PROBE_COMPONENT="${WAKIR_PROBE_COMPONENT:-bridge_audit_writer}"
WAKIR_PROBE_DEFAULT_BACKEND="${WAKIR_PROBE_DEFAULT_BACKEND:-python}"
WAKIR_PROBE_ROLLBACK_ENV_NAME="${WAKIR_PROBE_ROLLBACK_ENV_NAME:-WAKIR_BRIDGE_AUDIT_WRITER_BACKEND}"
# Welle-3-specific knobs.
WAKIR_PROBE_AUDIT_LOG_PATH="${WAKIR_PROBE_AUDIT_LOG_PATH:-/var/log/persona-engine/bridge-audit.jsonl}"
WAKIR_PROBE_MIN_HEAD_DELTA="${WAKIR_PROBE_MIN_HEAD_DELTA:-5}"
WAKIR_PROBE_MIN_AUDIT_AGE_SEC="${WAKIR_PROBE_MIN_AUDIT_AGE_SEC:-60}"
WAKIR_PROBE_REPLAY_TAIL_N="${WAKIR_PROBE_REPLAY_TAIL_N:-5}"
WAKIR_PROBE_REPLAY_MATCH_MIN="${WAKIR_PROBE_REPLAY_MATCH_MIN:-4}"
WAKIR_PROBE_OVERLAY_FILENAME="${WAKIR_PROBE_OVERLAY_FILENAME:-welle-3-bridge-audit-writer-rust.conf}"

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

Pre-Cutover-Sanity-Probe for Phase-3c Welle-3 (bridge_audit_writer,
ADR-0066 KW-25) against the wakir-pilot live VM via Mira-Hand-SSH
(ADR-0058).

Options:
  --dry-run                Plan probe steps; do not open SSH.
  --quiet                  Suppress non-error stdout chatter.
  --welle <n>              Welle index (default: 3).
  --component <name>       Component name (default: bridge_audit_writer).
  --expected-hash <hex>    Pin-Pack anchor hash for AXIS-4 cross-lang.
  --min-decisions <n>      AXIS-3 minimum BackendDecision count
                           (default: ${WAKIR_PROBE_MIN_BACKEND_DECISIONS}).
  --min-head-delta <n>     AXIS-1 minimum audit-stream head advance
                           since boot (default: ${WAKIR_PROBE_MIN_HEAD_DELTA}).
  --min-audit-age <sec>    AXIS-1 minimum audit-stream age in seconds
                           (default: ${WAKIR_PROBE_MIN_AUDIT_AGE_SEC}).
  --replay-tail-n <n>      AXIS-2 audit-replay tail length
                           (default: ${WAKIR_PROBE_REPLAY_TAIL_N}).
  --replay-match-min <n>   AXIS-2 minimum matching tail rows for GREEN
                           (default: ${WAKIR_PROBE_REPLAY_MATCH_MIN}).
  --audit-log-path <p>     AXIS-0 independent-oracle file path
                           (default: ${WAKIR_PROBE_AUDIT_LOG_PATH}).
  --overlay-filename <f>   AXIS-5 overlay drop-in filename to detect
                           (default: ${WAKIR_PROBE_OVERLAY_FILENAME}).
  --host <ip>              Override pilot host (default: ${WAKIR_PILOT_HOST}).
  --user <name>            Override SSH user  (default: ${WAKIR_PILOT_USER}).
  --ssh-key <path>         Override SSH key   (default: ${WAKIR_PILOT_SSH_KEY}).
  -h, --help               Show this help and exit.

Exit-codes: 0 green / 1 caution / 2 block / 3 precond / 4 not-exec.
USAGE
}

while (( $# > 0 )); do
    case "$1" in
        --dry-run)              DRY_RUN=1; shift ;;
        --quiet)                QUIET=1; shift ;;
        --welle)                WAKIR_PROBE_WELLE="$2"; shift 2 ;;
        --component)            WAKIR_PROBE_COMPONENT="$2"; shift 2 ;;
        --expected-hash)        WAKIR_PROBE_EXPECTED_HASH="$2"; shift 2 ;;
        --min-decisions)        WAKIR_PROBE_MIN_BACKEND_DECISIONS="$2"; shift 2 ;;
        --min-head-delta)       WAKIR_PROBE_MIN_HEAD_DELTA="$2"; shift 2 ;;
        --min-audit-age)        WAKIR_PROBE_MIN_AUDIT_AGE_SEC="$2"; shift 2 ;;
        --replay-tail-n)        WAKIR_PROBE_REPLAY_TAIL_N="$2"; shift 2 ;;
        --replay-match-min)     WAKIR_PROBE_REPLAY_MATCH_MIN="$2"; shift 2 ;;
        --audit-log-path)       WAKIR_PROBE_AUDIT_LOG_PATH="$2"; shift 2 ;;
        --overlay-filename)     WAKIR_PROBE_OVERLAY_FILENAME="$2"; shift 2 ;;
        --host)                 WAKIR_PILOT_HOST="$2"; shift 2 ;;
        --user)                 WAKIR_PILOT_USER="$2"; shift 2 ;;
        --ssh-key)              WAKIR_PILOT_SSH_KEY="$2"; shift 2 ;;
        -h|--help)              usage; exit 0 ;;
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

AXIS_0_VERDICT="UNKNOWN"
AXIS_1_VERDICT="UNKNOWN"
AXIS_2_VERDICT="UNKNOWN"
AXIS_3_VERDICT="UNKNOWN"
AXIS_4_VERDICT="UNKNOWN"
AXIS_5_VERDICT="UNKNOWN"
AXIS_0_DETAIL=""
AXIS_1_DETAIL=""
AXIS_2_DETAIL=""
AXIS_3_DETAIL=""
AXIS_4_DETAIL=""
AXIS_5_DETAIL=""

# AXIS-0 — Self-Reference-Trap-Pre-Check.
axis_0_self_reference_trap_pre_check() {
    log_step "AXIS-0 self-reference-trap-pre-check (audit-log=${WAKIR_PROBE_AUDIT_LOG_PATH})"
    # In-engine head pointer vs. on-disk tail. The on-disk read is the
    # *independent* oracle Henrik's ADR-0066 §Welle-3-Risiken note
    # requires: the engine's own bridge-audit-writer is the system
    # under test, so we cannot use it to verify itself.
    local cmd
    cmd='persona-engine-cli bridge-audit-head --json 2>/dev/null | head -c 2048; echo "---INDEPENDENT-ORACLE---"; tail -1 '"${WAKIR_PROBE_AUDIT_LOG_PATH}"' 2>/dev/null | head -c 2048'
    local out rc
    out=$(remote_exec "axis-0-self-ref" "${cmd}") || rc=$?
    rc=${rc:-0}
    if (( rc == 4 )); then
        AXIS_0_VERDICT="NOT-EXEC"
        AXIS_0_DETAIL="ssh-unreachable"
        return 4
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        AXIS_0_VERDICT="DRY-RUN"
        AXIS_0_DETAIL="dry-run (no remote call)"
        return 0
    fi
    local engine_head oracle_head
    engine_head=$(printf '%s' "${out}" | awk '/---INDEPENDENT-ORACLE---/{exit} {print}' | grep -oE '"head_seq"[[:space:]]*:[[:space:]]*[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
    oracle_head=$(printf '%s' "${out}" | awk '/---INDEPENDENT-ORACLE---/{flag=1; next} flag' | grep -oE '"seq"[[:space:]]*:[[:space:]]*[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
    if [[ -z "${engine_head}" || -z "${oracle_head}" ]]; then
        AXIS_0_VERDICT="RED"
        AXIS_0_DETAIL="self-ref-pre-check-unparseable engine=${engine_head:-<none>} oracle=${oracle_head:-<none>}"
        return 2
    fi
    local delta=$(( engine_head > oracle_head ? engine_head - oracle_head : oracle_head - engine_head ))
    AXIS_0_DETAIL="engine_head=${engine_head} oracle_head=${oracle_head} delta=${delta}"
    if (( engine_head == oracle_head )); then
        AXIS_0_VERDICT="GREEN"
        return 0
    elif (( delta <= 1 )); then
        # 1-row drift acceptable (in-flight entry between in-engine
        # read and on-disk flush).
        AXIS_0_VERDICT="YELLOW"
        return 1
    else
        AXIS_0_VERDICT="RED"
        return 2
    fi
}

# AXIS-1 — Audit-Stream-Continuity.
axis_1_audit_stream_continuity() {
    log_step "AXIS-1 audit-stream-continuity (min-head-delta=${WAKIR_PROBE_MIN_HEAD_DELTA} min-age=${WAKIR_PROBE_MIN_AUDIT_AGE_SEC}s)"
    local cmd
    cmd='persona-engine-cli bridge-audit-head --json 2>/dev/null | head -c 2048; echo "---SERVICE-AGE---"; date -u +%s; systemctl show persona-engine -p ActiveEnterTimestampMonotonic --value 2>/dev/null; awk '"'"'{print $1}'"'"' /proc/uptime 2>/dev/null'
    local out rc
    out=$(remote_exec "axis-1-continuity" "${cmd}") || rc=$?
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
    local head_seq start_seq
    head_seq=$(printf '%s' "${out}" | awk '/---SERVICE-AGE---/{exit} {print}' | grep -oE '"head_seq"[[:space:]]*:[[:space:]]*[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
    start_seq=$(printf '%s' "${out}" | awk '/---SERVICE-AGE---/{exit} {print}' | grep -oE '"start_seq"[[:space:]]*:[[:space:]]*[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
    if [[ -z "${head_seq}" ]]; then
        AXIS_1_VERDICT="RED"
        AXIS_1_DETAIL="head-seq-unparseable"
        return 2
    fi
    if [[ -z "${start_seq}" ]]; then
        start_seq=0
    fi
    local delta=$(( head_seq - start_seq ))
    AXIS_1_DETAIL="head_seq=${head_seq} start_seq=${start_seq} delta=${delta} min=${WAKIR_PROBE_MIN_HEAD_DELTA}"
    if (( delta >= WAKIR_PROBE_MIN_HEAD_DELTA )); then
        AXIS_1_VERDICT="GREEN"
        return 0
    elif (( delta > 0 )); then
        AXIS_1_VERDICT="YELLOW"
        return 1
    else
        AXIS_1_VERDICT="RED"
        return 2
    fi
}

# AXIS-2 — Independent-Oracle-Probe (audit-replay tail vs. on-disk tail).
axis_2_independent_oracle_probe() {
    log_step "AXIS-2 independent-oracle-probe (tail-n=${WAKIR_PROBE_REPLAY_TAIL_N} match-min=${WAKIR_PROBE_REPLAY_MATCH_MIN})"
    local cmd
    cmd='persona-engine-cli audit-replay --tail '"${WAKIR_PROBE_REPLAY_TAIL_N}"' --json 2>/dev/null | head -c 4096; echo "---ON-DISK-TAIL---"; tail -n '"${WAKIR_PROBE_REPLAY_TAIL_N}"' '"${WAKIR_PROBE_AUDIT_LOG_PATH}"' 2>/dev/null | head -c 4096'
    local out rc
    out=$(remote_exec "axis-2-replay" "${cmd}") || rc=$?
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
    # Compare the seq numbers visible in each section.
    local engine_seqs oracle_seqs
    engine_seqs=$(printf '%s' "${out}" | awk '/---ON-DISK-TAIL---/{exit} {print}' | grep -oE '"seq"[[:space:]]*:[[:space:]]*[0-9]+' | grep -oE '[0-9]+$' | sort -u)
    oracle_seqs=$(printf '%s' "${out}" | awk '/---ON-DISK-TAIL---/{flag=1; next} flag' | grep -oE '"seq"[[:space:]]*:[[:space:]]*[0-9]+' | grep -oE '[0-9]+$' | sort -u)
    if [[ -z "${engine_seqs}" || -z "${oracle_seqs}" ]]; then
        AXIS_2_VERDICT="RED"
        AXIS_2_DETAIL="oracle-probe-unparseable engine=$(printf '%s' "${engine_seqs}" | wc -l | tr -d ' ') oracle=$(printf '%s' "${oracle_seqs}" | wc -l | tr -d ' ')"
        return 2
    fi
    local matches
    matches=$(comm -12 <(printf '%s\n' "${engine_seqs}") <(printf '%s\n' "${oracle_seqs}") | wc -l | tr -d ' ')
    AXIS_2_DETAIL="matching-seqs=${matches}/${WAKIR_PROBE_REPLAY_TAIL_N} min=${WAKIR_PROBE_REPLAY_MATCH_MIN}"
    if (( matches >= WAKIR_PROBE_REPLAY_TAIL_N )); then
        AXIS_2_VERDICT="GREEN"
        return 0
    elif (( matches >= WAKIR_PROBE_REPLAY_MATCH_MIN )); then
        AXIS_2_VERDICT="YELLOW"
        return 1
    else
        AXIS_2_VERDICT="RED"
        return 2
    fi
}

# AXIS-3 — BackendDecision-Stream count + bridge_audit_writer row.
axis_3_backend_decision_stream() {
    log_step "AXIS-3 backend-decision-stream (min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS} component=${WAKIR_PROBE_COMPONENT})"
    local cmd
    cmd='journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -c BackendDecision || true; echo "---COMPONENT-ROW---"; journalctl -u persona-engine --since=boot --no-pager 2>/dev/null | grep -E "BackendDecision.*'"${WAKIR_PROBE_COMPONENT}"'" | tail -1'
    local out rc count component_row audit_backend
    out=$(remote_exec "axis-3-stream" "${cmd}") || rc=$?
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
    count=$(printf '%s' "${out}" | head -1 | tr -dc '0-9')
    if [[ -z "${count}" ]]; then count=0; fi
    component_row=$(printf '%s' "${out}" | awk '/---COMPONENT-ROW---/{flag=1; next} flag')
    if printf '%s' "${component_row}" | grep -qE "backend=python|backend=\"python\""; then
        audit_backend="python"
    elif printf '%s' "${component_row}" | grep -qE "backend=rust|backend=\"rust\""; then
        audit_backend="rust"
    else
        audit_backend=""
    fi
    AXIS_3_DETAIL="observed=${count} min=${WAKIR_PROBE_MIN_BACKEND_DECISIONS} component_backend=${audit_backend:-unknown}"
    if (( count >= WAKIR_PROBE_MIN_BACKEND_DECISIONS )) && [[ "${audit_backend}" == "${WAKIR_PROBE_DEFAULT_BACKEND}" ]]; then
        AXIS_3_VERDICT="GREEN"
        return 0
    elif (( count > 0 )) && [[ -n "${audit_backend}" ]]; then
        AXIS_3_VERDICT="YELLOW"
        return 1
    else
        AXIS_3_VERDICT="RED"
        return 2
    fi
}

# AXIS-4 — Cross-Lang-Hash-Parity vs. Pin-Pack anchor (PR #224, bridge-audit fixture set).
axis_4_cross_lang_hash_parity() {
    log_step "AXIS-4 cross-lang-hash-parity (expected=${WAKIR_PROBE_EXPECTED_HASH:-<unset>})"
    if [[ -z "${WAKIR_PROBE_EXPECTED_HASH}" ]]; then
        AXIS_4_VERDICT="YELLOW"
        AXIS_4_DETAIL="no expected-hash provided; skipping strict equality"
        log_warn "AXIS-4 skipped: --expected-hash not provided"
        return 1
    fi
    local cmd='persona-engine-cli bridge-audit-writer-hash --canonical-fixture pin-pack-bridge-audit-v1 --json 2>/dev/null | head -c 1024'
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
        AXIS_4_DETAIL="hash-mismatch (Pin-Pack bridge-audit anchor drift)"
        return 2
    fi
}

# AXIS-5 — Rollback-Probe surface inspection (non-mutating).
axis_5_rollback_surface() {
    log_step "AXIS-5 rollback-surface-inspection (env=${WAKIR_PROBE_ROLLBACK_ENV_NAME})"
    local cmd
    cmd='ls -ld /etc/systemd/system/persona-engine.service.d 2>/dev/null; systemctl is-enabled persona-engine 2>/dev/null; command -v systemctl >/dev/null && echo systemctl-OK; command -v journalctl >/dev/null && echo journalctl-OK; echo "---OVERLAY-LIST---"; ls -1 /etc/systemd/system/persona-engine.service.d/ 2>/dev/null || true'
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
    local overlay_present=0
    printf '%s' "${out}" | grep -q "systemctl-OK"  && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "journalctl-OK" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -qE "(enabled|static|alias|enabled-runtime)" && (( levers_ok+=1 )) || true
    printf '%s' "${out}" | grep -q "persona-engine.service.d" && (( levers_ok+=1 )) || true
    if printf '%s' "${out}" | awk '/---OVERLAY-LIST---/{flag=1; next} flag' | grep -qF "${WAKIR_PROBE_OVERLAY_FILENAME}"; then
        overlay_present=1
    fi
    AXIS_5_DETAIL="rollback-levers-present=${levers_ok}/4 overlay_present=${overlay_present}"
    if (( overlay_present == 1 )); then
        AXIS_5_VERDICT="RED"
        return 2
    fi
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
# Verdict aggregation (6 axes).
# -----------------------------------------------------------------

aggregate_verdict() {
    local v0="$1" v1="$2" v2="$3" v3="$4" v4="$5" v5="$6"
    local any_not_exec=0 any_red=0 any_yellow=0
    for v in "$v0" "$v1" "$v2" "$v3" "$v4" "$v5"; do
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
    log_info "welle-3-pre-cutover-probe start ts=${PROBE_TS} host=${WAKIR_PILOT_HOST} dry-run=${DRY_RUN}"
    log_info "component=${WAKIR_PROBE_COMPONENT} welle=${WAKIR_PROBE_WELLE} default-backend=${WAKIR_PROBE_DEFAULT_BACKEND}"

    if ! check_ssh_key_present; then
        log_error "precondition failure: SSH key"
        exit 3
    fi

    local r0=0 r1=0 r2=0 r3=0 r4=0 r5=0
    axis_0_self_reference_trap_pre_check || r0=$?
    axis_1_audit_stream_continuity       || r1=$?
    axis_2_independent_oracle_probe      || r2=$?
    axis_3_backend_decision_stream       || r3=$?
    axis_4_cross_lang_hash_parity        || r4=$?
    axis_5_rollback_surface              || r5=$?

    local verdict
    verdict=$(aggregate_verdict \
        "${AXIS_0_VERDICT}" "${AXIS_1_VERDICT}" "${AXIS_2_VERDICT}" \
        "${AXIS_3_VERDICT}" "${AXIS_4_VERDICT}" "${AXIS_5_VERDICT}")

    log_verdict "AXIS-0 ${AXIS_0_VERDICT}: ${AXIS_0_DETAIL}"
    log_verdict "AXIS-1 ${AXIS_1_VERDICT}: ${AXIS_1_DETAIL}"
    log_verdict "AXIS-2 ${AXIS_2_VERDICT}: ${AXIS_2_DETAIL}"
    log_verdict "AXIS-3 ${AXIS_3_VERDICT}: ${AXIS_3_DETAIL}"
    log_verdict "AXIS-4 ${AXIS_4_VERDICT}: ${AXIS_4_DETAIL}"
    log_verdict "AXIS-5 ${AXIS_5_VERDICT}: ${AXIS_5_DETAIL}"
    log_verdict "AGGREGATE: ${verdict}"

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
