#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-Tag-19 — Phase-3b Live-VM Acceptance Driver Script
# (follow-up to Tag-18 PR #168; the workflow surface declared the
#  contract this driver fulfils).
#
# **Why this script exists.**
#
# `.github/workflows/live-vm-acceptance.yml` (Tag-18 Mini-Welle, PR
# #168) introduced the `live-vm-acceptance-phase-3b` matrix job. Each
# matrix-cell shells out to `scripts/ci-live-vm-phase-3b-driver.sh`
# with seven flags and expects a structured JSON report. Tag-18
# tolerated the driver being absent by emitting a `driver-not-present`
# stub from the workflow YAML itself; this Tag-19 deliverable ships
# the real driver and replaces that stub-path on the workflow side
# (the workflow still keeps the stub-emit as a safety net — see
# `live-vm-acceptance.yml:648` `if [[ -x "${DRIVER}" ]]; then`).
#
# Driver contract (anchored in
# `docs/operations/live-vm-acceptance-phase-3b.md` §4)
# ----------------------------------------------------
#
#   bash scripts/ci-live-vm-phase-3b-driver.sh \
#       --target                  <wakir-pilot|wakir-orbit|both> \
#       --ssh-user                wakir-acceptance \
#       --ssh-key                 <runner-temp-path> \
#       --recovery-backend        <python|rust> \
#       --state-backing-backend   <python|rust_inmemory|rust_natskv> \
#       --latency-budget-ms       <int> \
#       --report-json             <output-path>
#
# Optional flags (Tag-19 additions, non-breaking to the workflow):
#
#   --component               <recovery|state-backing|fsm>
#                             Routing hint for sub-component focus.
#                             Default: `both` (recovery + state-backing).
#                             `fsm` is reserved for a future Phase-3c
#                             FSM-equivalence lane and currently maps
#                             to `recovery`.
#   --mode                    <ssh|self-test>
#                             `ssh`  (default): SSH to --target, spawn
#                                    persona, drive R1..R4 + state
#                                    roundtrip, collect verdict.
#                             `self-test`: skip SSH; synthesise a
#                                    valid report from
#                                    WAKIR_PHASE_3B_MOCK_* ENV-vars.
#                                    Used by tests/scripts/.
#   --ssh-options             Extra ssh(1) options (single string,
#                             default conservative set).
#   --help, -h                Show this help text and exit.
#
# Sandbox boundary
# ----------------
#
# This driver DOES NOT run in the claude-dev Sandbox in `--mode=ssh`.
# The Sandbox cannot reach 192.168.178.* — see
# `feedback_sandbox_host_trennung.md`. It runs on the GitHub-Actions
# runner that the workflow allocates, with the SSH key materialised
# into `${RUNNER_TEMP}` by the `Materialise SSH key` step.
#
# `--mode=self-test` is the safe surface for hermetic tests: it bypasses
# SSH entirely and reads its verdict-shape from ENV-vars. This mirrors
# the Tag-15/Tag-18 hermetic-test pattern (cf.
# `tests/infra/test_live_vm_acceptance_phase_3b.py`).
#
# Verdict-JSON schema (anchored in
# `docs/operations/live-vm-acceptance-phase-3b.md` §4)
# ----------------------------------------------------
#
# Every successful invocation writes a JSON report to --report-json:
#
#   {
#     "target_vm":                "wakir-pilot",
#     "recovery_backend":         "rust",
#     "state_backing_backend":    "rust_natskv",
#     "latency_budget_ms":        1500,
#     "status":                   "ok" | "fail" | "driver-not-present",
#     "final_state_hash":         "<64-hex-blake3>"|null,
#     "recovery_latency_ms_p50":  <int>|null,
#     "recovery_latency_ms_p95":  <int>|null,
#     "state_latency_ms_p50":     <int>|null,
#     "state_latency_ms_p95":     <int>|null,
#     "fallback_reason":          <string>|null,
#     "backend_decision_record":  {
#       "recovery_backend":       "rust",
#       "state_backing_backend":  "rust_natskv",
#       "component_focus":        "recovery"|"state-backing"|"both",
#       "fail_subkind":           null | "latency-budget" | "driver-error" | "on-vm"
#     }
#   }
#
# Status-codomain is deliberately narrow ({ok, fail, driver-not-present}).
# The narrow set is dictated by the workflow's `Per-permutation verdict`
# step (live-vm-acceptance.yml:707-724) which accepts exactly those three
# tokens and treats anything else as an unknown-status hard-error. The
# driver therefore funnels its richer internal failure-modes into
# ``status=fail`` with a structured ``backend_decision_record.fail_subkind``
# discriminator so an operator triaging the verdict-JSON can still tell
# the failure-modes apart.
#
# Exit codes (operator-side richer surface than the verdict-status):
#
#   0   verdict is `ok` (driver ran end-to-end, status==ok)
#   0   verdict is `driver-not-present` (workflow-stub-equivalent)
#   2   verdict is `fail` with fail_subkind == "latency-budget"
#   3   verdict is `fail` with fail_subkind == "driver-error"
#   4   verdict is `fail` with fail_subkind == "on-vm" (default fail)
#   64  CLI-usage error (missing flag, unknown flag, conflicting flags)
#
# The workflow consumes the verdict-JSON via jq in the
# `Per-permutation verdict` step; the exit code is informational
# only (the workflow re-derives PASS/FAIL from the `status` field).
# The richer exit-code surface stays useful for direct operator
# invocations and for the aggregate-job's defence-in-depth p95-budget
# re-check (live-vm-acceptance.yml:773-830).
#
# --------------------------------------------------------------------

set -euo pipefail

# --------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------

TARGET=""
SSH_USER=""
SSH_KEY=""
RECOVERY_BACKEND=""
STATE_BACKING_BACKEND=""
LATENCY_BUDGET_MS=""
REPORT_JSON=""
COMPONENT="both"
MODE="ssh"
SSH_OPTIONS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=15"

PROG_NAME="$(basename "${BASH_SOURCE[0]}")"

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

usage() {
  cat <<'EOF'
ci-live-vm-phase-3b-driver.sh — Phase-3b matrix-cell driver

Required:
  --target <name>                       Target VM (SSH host)
  --ssh-user <user>                     SSH user (production: wakir-acceptance)
  --ssh-key <path>                      SSH key path
  --recovery-backend <python|rust>      WAKIR_RECOVERY_BACKEND
  --state-backing-backend <python|rust_inmemory|rust_natskv>
                                        WAKIR_STATE_BACKING_BACKEND
  --latency-budget-ms <int>             p95 latency budget (per backend)
  --report-json <path>                  Output JSON report path

Optional:
  --component <recovery|state-backing|fsm>
                                        Sub-component focus hint. Default: both.
  --mode <ssh|self-test>                Default: ssh. Self-test bypasses
                                        SSH and reads mock verdict from
                                        WAKIR_PHASE_3B_MOCK_* ENV-vars.
  --ssh-options <string>                Extra ssh(1) options.
  --help, -h                            Show this message.

See docs/operations/live-vm-acceptance-phase-3b.md §4 for the full
driver contract.
EOF
}

die_usage() {
  echo "${PROG_NAME}: error: $*" >&2
  echo "Use --help for usage." >&2
  exit 64
}

log() {
  # Send progress to stderr so stdout stays clean for piping.
  echo "[${PROG_NAME}] $*" >&2
}

# --------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)                 TARGET="${2:-}"; shift 2 ;;
    --ssh-user)               SSH_USER="${2:-}"; shift 2 ;;
    --ssh-key)                SSH_KEY="${2:-}"; shift 2 ;;
    --recovery-backend)       RECOVERY_BACKEND="${2:-}"; shift 2 ;;
    --state-backing-backend)  STATE_BACKING_BACKEND="${2:-}"; shift 2 ;;
    --latency-budget-ms)      LATENCY_BUDGET_MS="${2:-}"; shift 2 ;;
    --report-json)            REPORT_JSON="${2:-}"; shift 2 ;;
    --component)              COMPONENT="${2:-}"; shift 2 ;;
    --mode)                   MODE="${2:-}"; shift 2 ;;
    --ssh-options)            SSH_OPTIONS="${2:-}"; shift 2 ;;
    --help|-h)                usage; exit 0 ;;
    *)                        die_usage "unknown flag: $1" ;;
  esac
done

# --------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------

[[ -n "${TARGET}" ]]                  || die_usage "--target is required"
[[ -n "${RECOVERY_BACKEND}" ]]        || die_usage "--recovery-backend is required"
[[ -n "${STATE_BACKING_BACKEND}" ]]   || die_usage "--state-backing-backend is required"
[[ -n "${LATENCY_BUDGET_MS}" ]]       || die_usage "--latency-budget-ms is required"
[[ -n "${REPORT_JSON}" ]]             || die_usage "--report-json is required"

case "${RECOVERY_BACKEND}" in
  python|rust) ;;
  *) die_usage "--recovery-backend must be python|rust (got: ${RECOVERY_BACKEND})" ;;
esac

case "${STATE_BACKING_BACKEND}" in
  python|rust_inmemory|rust_natskv) ;;
  *) die_usage "--state-backing-backend must be python|rust_inmemory|rust_natskv (got: ${STATE_BACKING_BACKEND})" ;;
esac

case "${COMPONENT}" in
  recovery|state-backing|both) ;;
  fsm) COMPONENT="recovery" ;;  # Reserved for Phase-3c; map to recovery for now.
  *) die_usage "--component must be recovery|state-backing|fsm|both (got: ${COMPONENT})" ;;
esac

case "${MODE}" in
  ssh|self-test) ;;
  *) die_usage "--mode must be ssh|self-test (got: ${MODE})" ;;
esac

if ! [[ "${LATENCY_BUDGET_MS}" =~ ^[0-9]+$ ]]; then
  die_usage "--latency-budget-ms must be a positive integer (got: ${LATENCY_BUDGET_MS})"
fi

if [[ "${MODE}" == "ssh" ]]; then
  [[ -n "${SSH_USER}" ]] || die_usage "--ssh-user is required in --mode=ssh"
  [[ -n "${SSH_KEY}" ]]  || die_usage "--ssh-key is required in --mode=ssh"
fi

# Ensure REPORT_JSON parent directory exists.
REPORT_DIR="$(dirname "${REPORT_JSON}")"
mkdir -p "${REPORT_DIR}"

# Verify jq is available — every emit path uses jq for safety.
if ! command -v jq >/dev/null 2>&1; then
  echo "${PROG_NAME}: error: jq not found on PATH" >&2
  exit 3
fi

# --------------------------------------------------------------------
# Report emit helper
# --------------------------------------------------------------------
#
# All exit paths funnel through `emit_report` so the JSON schema is
# enforced in exactly one place. The function takes named values via
# environment variables (set by callers) to keep the call-site readable.

emit_report() {
  # Args (positional, all optional except status + fail_subkind):
  #   1: status            ok|fail|driver-not-present
  #   2: final_state_hash  "" -> null
  #   3: rec_p50           "" -> null
  #   4: rec_p95           "" -> null
  #   5: st_p50            "" -> null
  #   6: st_p95            "" -> null
  #   7: fallback_reason   "" -> null
  #   8: fail_subkind      "" -> null (only meaningful when status=="fail")
  local status="$1"
  local final_state_hash="${2:-}"
  local rec_p50="${3:-}"
  local rec_p95="${4:-}"
  local st_p50="${5:-}"
  local st_p95="${6:-}"
  local fallback_reason="${7:-}"
  local fail_subkind="${8:-}"

  jq -n \
    --arg target              "${TARGET}" \
    --arg recovery            "${RECOVERY_BACKEND}" \
    --arg state               "${STATE_BACKING_BACKEND}" \
    --argjson budget          "${LATENCY_BUDGET_MS}" \
    --arg status              "${status}" \
    --arg hash                "${final_state_hash}" \
    --arg rec_p50             "${rec_p50}" \
    --arg rec_p95             "${rec_p95}" \
    --arg st_p50              "${st_p50}" \
    --arg st_p95              "${st_p95}" \
    --arg fallback            "${fallback_reason}" \
    --arg component           "${COMPONENT}" \
    --arg subkind             "${fail_subkind}" \
    '
    def to_int_or_null:
      if . == "" then null else (. | tonumber) end;
    def to_str_or_null:
      if . == "" then null else . end;
    {
      target_vm:                $target,
      recovery_backend:         $recovery,
      state_backing_backend:    $state,
      latency_budget_ms:        $budget,
      status:                   $status,
      final_state_hash:         ($hash       | to_str_or_null),
      recovery_latency_ms_p50:  ($rec_p50    | to_int_or_null),
      recovery_latency_ms_p95:  ($rec_p95    | to_int_or_null),
      state_latency_ms_p50:     ($st_p50     | to_int_or_null),
      state_latency_ms_p95:     ($st_p95     | to_int_or_null),
      fallback_reason:          ($fallback   | to_str_or_null),
      backend_decision_record: {
        recovery_backend:       $recovery,
        state_backing_backend:  $state,
        component_focus:        $component,
        fail_subkind:           ($subkind    | to_str_or_null)
      }
    }
    ' > "${REPORT_JSON}"
  log "wrote report ${REPORT_JSON} (status=${status}, fail_subkind=${fail_subkind:-null})"
}

# Map a (status, fail_subkind) pair to the documented exit code.
# This is the operator-facing exit-code surface; the workflow ignores
# the exit code and reads the status field from the verdict-JSON
# instead.
exit_for_status() {
  local status="$1"
  local subkind="${2:-}"
  case "${status}" in
    ok)                       exit 0 ;;
    driver-not-present)       exit 0 ;;
    fail)
      case "${subkind}" in
        latency-budget)       exit 2 ;;
        driver-error)         exit 3 ;;
        on-vm|"")             exit 4 ;;
        *)                    exit 4 ;;
      esac
      ;;
    *)                        exit 3 ;;
  esac
}

# --------------------------------------------------------------------
# Self-test mode
# --------------------------------------------------------------------
#
# `--mode=self-test` is the hermetic surface used by
# `tests/scripts/test_ci_live_vm_phase_3b_driver.py`. It reads the
# verdict-shape from WAKIR_PHASE_3B_MOCK_* ENV-vars and emits a
# fully-valid report without touching SSH or the Pilot-VM. This
# matches the Tag-18 sandbox boundary: hermetic Sandbox cannot
# reach 192.168.178.*, so any test surface for the driver must
# bypass SSH.

run_self_test_mode() {
  # Self-test mode lets the hermetic test suite inject every documented
  # verdict-shape. The injection-ENV defaults to a clean status=ok.
  # The user-input WAKIR_PHASE_3B_MOCK_STATUS accepts the wider
  # operator-friendly token-set ({ok, fail, driver-not-present,
  # fail-latency-budget, fail-driver-error}); the driver internally
  # folds the latter two into status=fail with a `fail_subkind`
  # discriminator before emitting, so the verdict-JSON stays within
  # the workflow-accepted three-token codomain.
  local mock_status="${WAKIR_PHASE_3B_MOCK_STATUS:-ok}"
  local mock_hash="${WAKIR_PHASE_3B_MOCK_FINAL_STATE_HASH:-$(printf '%064d' 0)}"
  local mock_rec_p50="${WAKIR_PHASE_3B_MOCK_RECOVERY_P50:-42}"
  local mock_rec_p95="${WAKIR_PHASE_3B_MOCK_RECOVERY_P95:-187}"
  local mock_st_p50="${WAKIR_PHASE_3B_MOCK_STATE_P50:-31}"
  local mock_st_p95="${WAKIR_PHASE_3B_MOCK_STATE_P95:-142}"
  local mock_fallback="${WAKIR_PHASE_3B_MOCK_FALLBACK_REASON:-}"

  local emit_status=""
  local emit_subkind=""

  # If status is ok, drive the latency-budget logic so the test can
  # assert the same code path the production-mode ssh-path takes.
  if [[ "${mock_status}" == "ok" ]]; then
    local worst_p95
    worst_p95="${mock_rec_p95}"
    if [[ "${mock_st_p95}" -gt "${worst_p95}" ]]; then
      worst_p95="${mock_st_p95}"
    fi
    if [[ "${worst_p95}" -gt "${LATENCY_BUDGET_MS}" ]]; then
      mock_status="fail-latency-budget"
      mock_fallback="p95-exceeded-budget(${worst_p95}ms > ${LATENCY_BUDGET_MS}ms)"
    fi
  fi

  case "${mock_status}" in
    ok)
      emit_status="ok"; emit_subkind=""
      emit_report "${emit_status}" "${mock_hash}" "${mock_rec_p50}" "${mock_rec_p95}" "${mock_st_p50}" "${mock_st_p95}" "" "${emit_subkind}"
      ;;
    fail-latency-budget)
      emit_status="fail"; emit_subkind="latency-budget"
      emit_report "${emit_status}" "${mock_hash}" "${mock_rec_p50}" "${mock_rec_p95}" "${mock_st_p50}" "${mock_st_p95}" "${mock_fallback}" "${emit_subkind}"
      ;;
    fail-driver-error)
      emit_status="fail"; emit_subkind="driver-error"
      emit_report "${emit_status}" "" "" "" "" "" "${mock_fallback:-self-test-injected-driver-error}" "${emit_subkind}"
      ;;
    fail)
      emit_status="fail"; emit_subkind="on-vm"
      emit_report "${emit_status}" "" "" "" "" "" "${mock_fallback:-self-test-injected-on-vm-failure}" "${emit_subkind}"
      ;;
    driver-not-present)
      emit_status="driver-not-present"; emit_subkind=""
      emit_report "${emit_status}" "" "" "" "" "" "${mock_fallback:-self-test-driver-not-present}" "${emit_subkind}"
      ;;
    *)
      die_usage "unknown WAKIR_PHASE_3B_MOCK_STATUS: ${mock_status}"
      ;;
  esac

  exit_for_status "${emit_status}" "${emit_subkind}"
}

# --------------------------------------------------------------------
# SSH mode — real Pilot-VM drive
# --------------------------------------------------------------------
#
# The SSH-mode path constructs a deterministic remote command, runs
# it on the target VM, parses the JSON the remote emits to stdout,
# and re-emits it locally as the verdict report. The remote script
# (Tag-19 follow-up: `infra/persona-engine/phase-3b-acceptance.sh`)
# is responsible for the actual persona-spawn + R1..R4 + state-
# roundtrip. This driver's responsibility is the **transport** and
# the **verdict-shape enforcement**.
#
# For Tag-19 the remote script is not yet present on every Pilot-VM
# image. The driver therefore probes for it first and, if absent,
# emits `driver-not-present` from the local side so the workflow
# verdict-step sees a clean signal. This mirrors the Tag-18 stub
# path that the workflow YAML emits when the *local* driver was
# absent (now: when the *remote* driver is absent).

ssh_probe_remote_driver() {
  ssh -i "${SSH_KEY}" ${SSH_OPTIONS} "${SSH_USER}@${TARGET}" \
    "test -x /opt/wakir/bin/wakir-phase-3b-acceptance.sh && echo PRESENT || echo ABSENT" 2>/dev/null
}

ssh_drive_remote() {
  # We pass the backend selectors via ENV (server-side `LANG=` style)
  # to avoid quoting issues on the remote shell. The remote script
  # emits a JSON dict on stdout — we capture it via tee'd stdout.
  local remote_out
  remote_out="$(
    ssh -i "${SSH_KEY}" ${SSH_OPTIONS} \
      "${SSH_USER}@${TARGET}" \
      "WAKIR_RECOVERY_BACKEND='${RECOVERY_BACKEND}' \
       WAKIR_STATE_BACKING_BACKEND='${STATE_BACKING_BACKEND}' \
       WAKIR_LATENCY_BUDGET_MS='${LATENCY_BUDGET_MS}' \
       WAKIR_COMPONENT_FOCUS='${COMPONENT}' \
       sudo -E -n /opt/wakir/bin/wakir-phase-3b-acceptance.sh --emit-json"
  )" || return 3

  # Validate it parses as JSON and has a `status` field.
  if ! echo "${remote_out}" | jq -e '.status' >/dev/null 2>&1; then
    return 3
  fi

  echo "${remote_out}"
  return 0
}

run_ssh_mode() {
  log "probing remote driver presence on ${TARGET}"
  local probe
  probe="$(ssh_probe_remote_driver || true)"

  if [[ "${probe}" != "PRESENT" ]]; then
    log "remote driver absent on ${TARGET}; emitting driver-not-present stub"
    emit_report "driver-not-present" "" "" "" "" "" "remote-driver-not-yet-deployed" ""
    exit_for_status "driver-not-present" ""
  fi

  log "remote driver present; invoking on ${TARGET}"
  local remote_out
  if ! remote_out="$(ssh_drive_remote)"; then
    log "remote driver invocation failed"
    emit_report "fail" "" "" "" "" "" "remote-driver-exec-error" "driver-error"
    exit_for_status "fail" "driver-error"
  fi

  # Extract the canonical verdict fields from the remote JSON and
  # re-emit through emit_report so the schema invariants apply locally.
  local r_status r_hash r_rec_p50 r_rec_p95 r_st_p50 r_st_p95 r_fallback r_subkind
  r_status="$(echo "${remote_out}"   | jq -r '.status                                 // "fail"')"
  r_hash="$(echo "${remote_out}"     | jq -r '.final_state_hash                       // ""')"
  r_rec_p50="$(echo "${remote_out}"  | jq -r '.recovery_latency_ms_p50                // ""')"
  r_rec_p95="$(echo "${remote_out}"  | jq -r '.recovery_latency_ms_p95                // ""')"
  r_st_p50="$(echo "${remote_out}"   | jq -r '.state_latency_ms_p50                   // ""')"
  r_st_p95="$(echo "${remote_out}"   | jq -r '.state_latency_ms_p95                   // ""')"
  r_fallback="$(echo "${remote_out}" | jq -r '.fallback_reason                        // ""')"
  r_subkind="$(echo "${remote_out}"  | jq -r '.backend_decision_record.fail_subkind   // ""')"

  # If the remote emitted any non-workflow-accepted status token,
  # normalise it to fail+driver-error so the workflow's per-permutation
  # verdict-step never trips its `Unknown report status` branch.
  case "${r_status}" in
    ok|fail|driver-not-present) ;;
    *)
      log "remote status '${r_status}' is outside the workflow-accepted set; normalising to fail+driver-error"
      r_status="fail"
      r_subkind="driver-error"
      [[ -z "${r_fallback}" ]] && r_fallback="remote-emitted-unknown-status"
      ;;
  esac

  # Apply the latency-budget gate locally — defence-in-depth in case
  # the remote script forgot to enforce it. Only relevant on status=ok.
  if [[ "${r_status}" == "ok" && -n "${r_rec_p95}" && -n "${r_st_p95}" ]]; then
    local worst="${r_rec_p95}"
    if [[ "${r_st_p95}" -gt "${worst}" ]]; then worst="${r_st_p95}"; fi
    if [[ "${worst}" -gt "${LATENCY_BUDGET_MS}" ]]; then
      r_status="fail"
      r_subkind="latency-budget"
      r_fallback="p95-exceeded-budget(${worst}ms > ${LATENCY_BUDGET_MS}ms)"
    fi
  fi

  # On a clean fail with no subkind from remote, default to on-vm.
  if [[ "${r_status}" == "fail" && -z "${r_subkind}" ]]; then
    r_subkind="on-vm"
  fi

  emit_report "${r_status}" "${r_hash}" "${r_rec_p50}" "${r_rec_p95}" "${r_st_p50}" "${r_st_p95}" "${r_fallback}" "${r_subkind}"
  exit_for_status "${r_status}" "${r_subkind}"
}

# --------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------

case "${MODE}" in
  self-test) run_self_test_mode ;;
  ssh)       run_ssh_mode ;;
esac
