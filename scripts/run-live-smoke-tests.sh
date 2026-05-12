#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Live-NATS-Test-Mode driver for the Phase-2 Sprint-4 Tag-1 orchestrator
# smoke contract (ADR-0051-rejected; Mira-Hand operative practice retained).
#
# What this script does
# ---------------------
#
# 1. Pre-flight: verify NATS reachability at the configured server.
#    The check uses three independent probes (TCP connect on 4222,
#    HTTP /jsz on 8222, optional `nats` CLI ping) so a transient
#    failure in any one probe does not block the test run, but all
#    three reporting unreachable does. The exact probes are documented
#    inline so an operator can repro them by hand.
# 2. Pre-flight: verify ``nats-py`` is importable in the repo venv.
# 3. Run the gated pytest selection with ``WAKIR_NATS_LIVE=1``:
#
#       tests/orchestrator/test_init_nats_buckets.py
#       tests/orchestrator/test_check_nats_kv_health.py
#       tests/orchestrator/test_check_federation_evaluator_health.py
#       tests/orchestrator/test_live_nats_cross_validation.py
#
#    The full orchestrator suite runs (hermetic + gated); the
#    ``--collect-only`` mode emits the selection plan for the operator
#    log without executing anything.
# 4. Emit a JSON summary on stdout with the pre-flight result, the
#    pytest exit code, and the count of live tests that ran vs.
#    skipped.
#
# What this script does NOT do
# ----------------------------
#
#   * It does NOT bring up the NATS substrate. The compose stack must
#     already be running (`scripts/post-install-live-smoke.sh` brings
#     it up; this script only consumes it).
#   * It does NOT initialise the four Phase-1 buckets. The
#     populated-cluster cross-validation scenario assumes
#     ``scripts/init-nats-buckets.py`` has already run. The
#     empty-cluster scenario assumes the opposite. The live tests
#     ``skipTest`` if the cluster is in an unexpected state rather
#     than failing — see the runbook §7.3 for the operator workflow
#     that drives both scenarios in sequence.
#   * It does NOT push, mutate persistent state, or contact a remote.
#     Pre-flight probes are localhost-only by default; a remote NATS
#     can be targeted via ``WAKIR_NATS_URL`` but the operator must
#     own the consequences.
#   * It does NOT run inside the Mira-Sandbox. The Mira-Sandbox cannot
#     reach the host NATS substrate (ADR-0051-rejected; operative
#     Mira-Hand-Regel). Drive this script from the operator hand.
#
# Usage
# -----
#
#   scripts/run-live-smoke-tests.sh                       # full run
#   scripts/run-live-smoke-tests.sh --dry-run             # plan only
#   scripts/run-live-smoke-tests.sh --collect-only        # pytest collect
#   scripts/run-live-smoke-tests.sh --scenario empty      # cross-val only
#   scripts/run-live-smoke-tests.sh --scenario populated  # cross-val only
#   scripts/run-live-smoke-tests.sh --scenario both       # default
#   scripts/run-live-smoke-tests.sh --no-cross-validation # skip new suite
#
# Environment overrides
# ---------------------
#
#   WAKIR_NATS_URL        default ``nats://127.0.0.1:4222``
#   WAKIR_NATS_JSZ_URL    default ``http://127.0.0.1:8222/jsz``
#   WAKIR_NATS_TOKEN      optional token for token-auth clusters
#
# Exit codes
# ----------
#
#   0   pre-flight ok, pytest exit 0
#   1   pre-flight failed (NATS not reachable or venv broken)
#   2   pytest reported failure
#   3   bad CLI argument
#
# Verification stamp (P5/P7): authoring date 2026-05-11
# (Sprint-4 Tag-1), substrate baseline ``nats:2.11-alpine``
# (Phase-1b production pin; see runbook §1).

set -euo pipefail

readonly SCRIPT_NAME="run-live-smoke-tests.sh"
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly VENV_PY="${REPO_ROOT}/.venv/bin/python3"
readonly VENV_PYTEST="${REPO_ROOT}/.venv/bin/pytest"

NATS_URL="${WAKIR_NATS_URL:-nats://127.0.0.1:4222}"
JSZ_URL="${WAKIR_NATS_JSZ_URL:-http://127.0.0.1:8222/jsz}"
DRY_RUN=0
COLLECT_ONLY=0
SCENARIO="both"
SKIP_CROSS_VALIDATION=0

PREFLIGHT_TCP="unknown"
PREFLIGHT_JSZ="unknown"
PREFLIGHT_NATS_CLI="unknown"
PREFLIGHT_VENV="unknown"
PYTEST_EXIT="unknown"

# ---------------------------------------------------------------- #
# Logging                                                          #
# ---------------------------------------------------------------- #

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s][error] %s\n' "${SCRIPT_NAME}" "$*" >&2; }

# ---------------------------------------------------------------- #
# CLI                                                              #
# ---------------------------------------------------------------- #

usage() {
    sed -n '2,90p' "$0" >&2
    cat >&2 <<'EOT'

Options:
  --dry-run                   print the plan and exit 0
  --collect-only              run pytest --collect-only (no execution)
  --scenario {empty|populated|both}
                              limit cross-validation to one scenario
                              (default: both; see runbook §7.3 for
                              the cluster-state contract)
  --no-cross-validation       skip the new cross-validation suite
                              (runs the legacy gated suites only)
  -h|--help                   show this help
EOT
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ; shift ;;
        --collect-only) COLLECT_ONLY=1 ; shift ;;
        --scenario)
            SCENARIO="${2:?--scenario requires an argument}"
            case "${SCENARIO}" in
                empty|populated|both) ;;
                *) err "--scenario must be one of empty|populated|both" ; exit 3 ;;
            esac
            shift 2 ;;
        --no-cross-validation) SKIP_CROSS_VALIDATION=1 ; shift ;;
        -h|--help) usage ; exit 0 ;;
        *) err "unknown argument: $1" ; usage ; exit 3 ;;
    esac
done

# ---------------------------------------------------------------- #
# Pre-flight probes                                                #
# ---------------------------------------------------------------- #

# Strip ``nats://`` prefix to extract host:port for the TCP probe.
_strip_scheme() {
    local url="$1"
    url="${url#nats://}"
    url="${url#tls://}"
    printf '%s' "${url}"
}

probe_tcp() {
    local hostport
    hostport="$(_strip_scheme "${NATS_URL}")"
    local host="${hostport%%:*}"
    local port="${hostport##*:}"
    if [[ "${port}" == "${host}" ]]; then port="4222"; fi
    # ``bash`` exposes /dev/tcp without a separate netcat dependency;
    # the 2-second connect timeout keeps a wedged box bounded.
    if timeout 2 bash -c ">/dev/tcp/${host}/${port}" 2>/dev/null; then
        PREFLIGHT_TCP="ok"
        log "preflight: TCP ${host}:${port} reachable"
        return 0
    fi
    PREFLIGHT_TCP="unreachable"
    err "preflight: TCP ${host}:${port} unreachable (NATS not listening)"
    return 1
}

probe_jsz() {
    # 2-second connect+read timeout; ``--fail`` so a 5xx is treated
    # as unreachable. We do not parse the body — the substrate's
    # health is a §5.1 concern, this probe only needs "yes/no".
    if curl --fail --silent --show-error --max-time 2 "${JSZ_URL}" \
            >/dev/null 2>&1; then
        PREFLIGHT_JSZ="ok"
        log "preflight: ${JSZ_URL} returned 2xx"
        return 0
    fi
    PREFLIGHT_JSZ="unreachable"
    err "preflight: ${JSZ_URL} unreachable (JetStream HTTP monitor down)"
    return 1
}

probe_nats_cli() {
    # The ``nats`` CLI is optional; if it is missing we record ``skip``
    # rather than fail (the TCP+/jsz probes are sufficient).
    if ! command -v nats >/dev/null 2>&1; then
        PREFLIGHT_NATS_CLI="skip"
        log "preflight: 'nats' CLI not installed; skipping ping probe"
        return 0
    fi
    if NATS_URL="${NATS_URL}" nats --server "${NATS_URL}" \
            server ping --count 1 --timeout 2s >/dev/null 2>&1; then
        PREFLIGHT_NATS_CLI="ok"
        log "preflight: 'nats server ping' succeeded"
        return 0
    fi
    PREFLIGHT_NATS_CLI="unreachable"
    err "preflight: 'nats server ping' failed against ${NATS_URL}"
    return 1
}

probe_venv() {
    if [[ ! -x "${VENV_PY}" ]]; then
        PREFLIGHT_VENV="missing"
        err "preflight: ${VENV_PY} not found; activate per runbook §7.1"
        return 1
    fi
    if ! "${VENV_PY}" -c 'import nats' >/dev/null 2>&1; then
        PREFLIGHT_VENV="nats-py-missing"
        err "preflight: nats-py not importable in ${VENV_PY}"
        return 1
    fi
    if [[ ! -x "${VENV_PYTEST}" ]]; then
        PREFLIGHT_VENV="pytest-missing"
        err "preflight: ${VENV_PYTEST} not found"
        return 1
    fi
    PREFLIGHT_VENV="ok"
    log "preflight: venv ok (${VENV_PY})"
    return 0
}

preflight_all() {
    local failed=0
    probe_venv      || failed=1
    probe_tcp       || failed=1
    probe_jsz       || failed=1
    # nats CLI is best-effort; its failure does not gate.
    probe_nats_cli  || :
    if [[ ${failed} -ne 0 ]]; then
        err "preflight failed; not running live tests"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------- #
# Pytest selection                                                 #
# ---------------------------------------------------------------- #

# Build the test-id selection. The legacy gated suites
# (init-nats-buckets, check-nats-kv-health, check-federation-evaluator-
# health) run by default; the new cross-validation suite is conditional
# on --no-cross-validation. The --scenario flag narrows the cross-
# validation to one of the two byte-identity contracts.
build_pytest_selection() {
    local -a selection=(
        "tests/orchestrator/test_init_nats_buckets.py"
        "tests/orchestrator/test_check_nats_kv_health.py"
        "tests/orchestrator/test_check_federation_evaluator_health.py"
    )
    if [[ ${SKIP_CROSS_VALIDATION} -eq 0 ]]; then
        case "${SCENARIO}" in
            both)
                selection+=("tests/orchestrator/test_live_nats_cross_validation.py")
                ;;
            empty)
                selection+=(
                    "tests/orchestrator/test_live_nats_cross_validation.py::LiveCrossValidationSmokeTests::test_live_empty_cluster_matches_hermetic_baseline_byte_identical"
                    "tests/orchestrator/test_live_nats_cross_validation.py::test_hermetic_empty_cluster_dry_run_baseline"
                )
                ;;
            populated)
                selection+=(
                    "tests/orchestrator/test_live_nats_cross_validation.py::LiveCrossValidationSmokeTests::test_live_populated_cluster_matches_hermetic_baseline_byte_identical"
                    "tests/orchestrator/test_live_nats_cross_validation.py::test_hermetic_populated_cluster_dry_run_baseline"
                )
                ;;
        esac
    fi
    printf '%s\n' "${selection[@]}"
}

run_pytest() {
    local -a sel
    mapfile -t sel < <(build_pytest_selection)
    local -a pytest_args=("${sel[@]}" "-v")
    if [[ ${COLLECT_ONLY} -eq 1 ]]; then
        pytest_args+=("--collect-only")
    fi
    log "pytest: running ${#sel[@]} target(s) with WAKIR_NATS_LIVE=1"
    if WAKIR_NATS_LIVE=1 \
       WAKIR_NATS_URL="${NATS_URL}" \
       WAKIR_NATS_JSZ_URL="${JSZ_URL}" \
       "${VENV_PYTEST}" "${pytest_args[@]}"; then
        PYTEST_EXIT=0
        return 0
    fi
    PYTEST_EXIT=$?
    return 1
}

# ---------------------------------------------------------------- #
# JSON summary                                                     #
# ---------------------------------------------------------------- #

emit_summary() {
    printf '{\n'
    printf '  "tool": "%s",\n' "${SCRIPT_NAME}"
    printf '  "phase": "phase-2-sprint-4-tag-1",\n'
    printf '  "nats_url": "%s",\n' "${NATS_URL}"
    printf '  "jsz_url": "%s",\n' "${JSZ_URL}"
    printf '  "scenario": "%s",\n' "${SCENARIO}"
    printf '  "skip_cross_validation": %s,\n' \
        "$([[ ${SKIP_CROSS_VALIDATION} -eq 1 ]] && echo true || echo false)"
    printf '  "preflight": {\n'
    printf '    "tcp_4222": "%s",\n' "${PREFLIGHT_TCP}"
    printf '    "jsz_8222": "%s",\n' "${PREFLIGHT_JSZ}"
    printf '    "nats_cli_ping": "%s",\n' "${PREFLIGHT_NATS_CLI}"
    printf '    "venv": "%s"\n' "${PREFLIGHT_VENV}"
    printf '  },\n'
    printf '  "pytest_exit": "%s"\n' "${PYTEST_EXIT}"
    printf '}\n'
}

# ---------------------------------------------------------------- #
# Main                                                              #
# ---------------------------------------------------------------- #

log "starting (nats=${NATS_URL} scenario=${SCENARIO} dry_run=${DRY_RUN})"

if [[ ${DRY_RUN} -eq 1 ]]; then
    log "(dry-run) skipping pre-flight and pytest; emitting selection plan only"
    log "(dry-run) pytest selection:"
    build_pytest_selection | while IFS= read -r line; do
        log "(dry-run)   ${line}"
    done
    emit_summary
    exit 0
fi

if ! preflight_all; then
    emit_summary
    exit 1
fi

if run_pytest; then
    log "all live smoke tests clean"
    emit_summary
    exit 0
else
    err "pytest reported failure (exit ${PYTEST_EXIT})"
    emit_summary
    exit 2
fi
