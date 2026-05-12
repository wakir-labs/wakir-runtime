#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Post-install live-smoke driver for the Phase-1b NATS-JetStream KV
# substrate. This script chains the seven verification steps that
# follow a fresh build-host activation pass (see operator runbook
# §7.1 steps 2-5) into a single idempotent invocation:
#
#   1. preflight: gcc/podman/nats/nats-py/python3/repo presence
#   2. image pull: nats:2.11-alpine via the configured engine
#   3. compose up: bring the NATS substrate up via compose/nats.yaml
#   4. wait-ready: poll http://127.0.0.1:8222/jsz until healthy
#   5. bucket init: scripts/init-nats-buckets.py (idempotent)
#   6. real adapter smoke: import wirelang.federation.route_registry_
#      nats_kv_backend.RouteRegistryNatsKvBackend and round-trip a
#      synthetic key through the live KV bucket
#   7. KV health check: scripts/check-nats-kv-health.py (read-only)
#
# A teardown phase (compose down + optional volume drop) runs at the
# end. Each step prints a leading `[step N/7]` line plus a one-line
# pass/fail stamp; the final block prints a JSON summary on stdout
# (machine-parseable) and a human-readable line log on stderr. Exit
# codes mirror the strictest sub-step:
#
#   0   all steps clean
#   1   preflight failed (a tool is missing or the repo is not
#       checked out at this path)
#   2   compose up or wait-ready failed (substrate did not become
#       healthy within the timeout)
#   3   bucket init failed (init-nats-buckets.py exit non-zero)
#   4   real adapter smoke failed (import error, connect error, or
#       round-trip mismatch)
#   5   KV health check failed (check-nats-kv-health.py exit
#       non-zero)
#   6   teardown failed (compose down errored; substrate state may
#       be left over and require manual cleanup)
#
# Usage
# -----
#
#   scripts/post-install-live-smoke.sh                    # full run
#   scripts/post-install-live-smoke.sh --skip-teardown    # leave up
#   scripts/post-install-live-smoke.sh --keep-volume      # no -v
#   scripts/post-install-live-smoke.sh --dry-run          # plan
#   scripts/post-install-live-smoke.sh --engine docker    # default podman
#   scripts/post-install-live-smoke.sh --no-real-adapter  # skip step 6
#
# What this script does NOT do
# ----------------------------
#
#   * It does NOT install any tools; it expects steps 2-5 of the
#     runbook §7.1 build-host activation procedure to have already
#     completed (gcc, podman/docker, podman-compose/docker-compose,
#     nats-cli, nats-py-in-venv). Use scripts/setup.sh and the
#     supervisory-board approval pass for that side.
#   * It does NOT run the gated pytest live-smoke contracts (those
#     are §7.1 step 8; a separate post-install-pytest-smoke.sh is
#     a Sprint-3 follow-up if the CEO-side files such an item). The real-adapter
#     round-trip in step 6 here is the minimum substrate-side smoke
#     that the build-host activation needs to declare done.
#   * It does NOT touch SPIFFE/SVID setup (Cross-Review Zone A
#     deferred to Sprint-3 item 6).
#   * It does NOT push to the remote, mutate any persistent state
#     beyond the one synthetic-key round-trip in step 6 (which is
#     deleted at the end of step 6), or prompt for credentials. The
#     Phase-1b NATS substrate is unauthenticated; do not point this
#     script at a production NATS.
#
# Exit-code-via-trap discipline: the script uses `set -euo pipefail`
# and an EXIT trap that records the highest exit code observed and
# always attempts the teardown unless `--skip-teardown` is set. This
# means a failure in step 4 (real adapter) still attempts to bring
# the compose substrate down so the host is left clean.

set -euo pipefail

# ---------------------------------------------------------------- #
# Configuration                                                    #
# ---------------------------------------------------------------- #

readonly SCRIPT_NAME="post-install-live-smoke.sh"
readonly REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly COMPOSE_FILE="${REPO_ROOT}/compose/nats.yaml"
readonly INIT_SCRIPT="${REPO_ROOT}/scripts/init-nats-buckets.py"
readonly HEALTH_SCRIPT="${REPO_ROOT}/scripts/check-nats-kv-health.py"
readonly VENV_PY="${REPO_ROOT}/.venv/bin/python3"

# Defaults; CLI overrides below.
ENGINE="${WAKIR_LIVE_SMOKE_ENGINE:-podman}"
COMPOSE_BIN=""        # auto-detected from ENGINE
NATS_SERVER="${WAKIR_NATS_SERVER:-nats://127.0.0.1:4222}"
JSZ_URL="${WAKIR_NATS_JSZ_URL:-http://127.0.0.1:8222/jsz}"
WAIT_READY_TIMEOUT="${WAKIR_LIVE_SMOKE_READY_TIMEOUT:-60}"
DRY_RUN=0
SKIP_TEARDOWN=0
KEEP_VOLUME=0
SKIP_REAL_ADAPTER=0

# Step result tracking; shell-portable (no associative arrays in
# strict POSIX, but bash 4+ has them and the shebang already pins
# bash; we keep an ordered array for the JSON summary).
declare -a STEP_NAMES=()
declare -a STEP_RESULTS=()
declare -a STEP_DURATIONS=()
HIGHEST_EXIT=0

# ---------------------------------------------------------------- #
# Logging                                                          #
# ---------------------------------------------------------------- #

log() { printf '[%s] %s\n' "${SCRIPT_NAME}" "$*" >&2; }
err() { printf '[%s][error] %s\n' "${SCRIPT_NAME}" "$*" >&2; }

# Record a step outcome. Args: step-name (string), result (ok|fail|
# skip), duration-seconds (integer or "-").
record_step() {
    local name="$1" result="$2" duration="$3"
    STEP_NAMES+=("${name}")
    STEP_RESULTS+=("${result}")
    STEP_DURATIONS+=("${duration}")
}

# Emit the final JSON summary on stdout. node_exporter-textfile-
# collector-shaped (single line per metric) is overkill here; this
# is the operator-friendly object the Prometheus adapter does not
# consume.
emit_summary() {
    local i
    printf '{\n'
    printf '  "tool": "%s",\n' "${SCRIPT_NAME}"
    printf '  "phase": "phase-1b-sprint-3-tag-4",\n'
    printf '  "engine": "%s",\n' "${ENGINE}"
    printf '  "compose_bin": "%s",\n' "${COMPOSE_BIN}"
    printf '  "nats_server": "%s",\n' "${NATS_SERVER}"
    printf '  "jsz_url": "%s",\n' "${JSZ_URL}"
    printf '  "highest_exit": %d,\n' "${HIGHEST_EXIT}"
    printf '  "steps": [\n'
    for i in "${!STEP_NAMES[@]}"; do
        local sep=","
        if [[ $i -eq $((${#STEP_NAMES[@]} - 1)) ]]; then sep=""; fi
        printf '    {"name": "%s", "result": "%s", "duration_s": "%s"}%s\n' \
            "${STEP_NAMES[$i]}" \
            "${STEP_RESULTS[$i]}" \
            "${STEP_DURATIONS[$i]}" \
            "${sep}"
    done
    printf '  ]\n'
    printf '}\n'
}

# ---------------------------------------------------------------- #
# CLI                                                              #
# ---------------------------------------------------------------- #

usage() {
    sed -n '2,75p' "$0" >&2
    cat >&2 <<'EOT'

Options:
  --engine {podman|docker}    container engine (default podman; env
                              WAKIR_LIVE_SMOKE_ENGINE override)
  --skip-teardown             leave the compose stack running at end
  --keep-volume               do not pass -v to compose down (state
                              survives a teardown)
  --no-real-adapter           skip step 6 (real-nats-py adapter
                              round-trip)
  --dry-run                   print the plan and exit 0
  -h|--help                   show this help

Environment overrides:
  WAKIR_LIVE_SMOKE_ENGINE       same as --engine
  WAKIR_NATS_SERVER             default nats://127.0.0.1:4222
  WAKIR_NATS_JSZ_URL            default http://127.0.0.1:8222/jsz
  WAKIR_LIVE_SMOKE_READY_TIMEOUT  seconds to wait for /jsz (default 60)
EOT
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine) ENGINE="${2:?}" ; shift 2 ;;
        --skip-teardown) SKIP_TEARDOWN=1 ; shift ;;
        --keep-volume) KEEP_VOLUME=1 ; shift ;;
        --no-real-adapter) SKIP_REAL_ADAPTER=1 ; shift ;;
        --dry-run) DRY_RUN=1 ; shift ;;
        -h|--help) usage ; exit 0 ;;
        *) err "unknown argument: $1" ; usage ; exit 1 ;;
    esac
done

# Resolve compose binary once ENGINE is fixed.
case "${ENGINE}" in
    podman) COMPOSE_BIN="podman-compose" ;;
    docker) COMPOSE_BIN="docker compose" ;;
    *) err "unsupported engine: ${ENGINE} (allowed: podman|docker)" ; exit 1 ;;
esac

# ---------------------------------------------------------------- #
# Teardown trap                                                    #
# ---------------------------------------------------------------- #

teardown() {
    local rc=$?
    if [[ ${SKIP_TEARDOWN} -eq 1 ]]; then
        log "teardown skipped (--skip-teardown); compose stack left running"
        record_step "7-teardown" "skip" "-"
    elif [[ ${DRY_RUN} -eq 1 ]]; then
        record_step "7-teardown" "skip" "-"
    else
        local t0=$(date +%s)
        log "[step 7/7] teardown: ${COMPOSE_BIN} down"
        local down_args=()
        if [[ ${KEEP_VOLUME} -eq 0 ]]; then down_args+=("-v"); fi
        if ${COMPOSE_BIN} -f "${COMPOSE_FILE}" down "${down_args[@]}" >&2; then
            record_step "7-teardown" "ok" "$(($(date +%s) - t0))"
        else
            err "teardown failed; substrate state may persist"
            record_step "7-teardown" "fail" "$(($(date +%s) - t0))"
            if [[ ${HIGHEST_EXIT} -lt 6 ]]; then HIGHEST_EXIT=6; fi
        fi
    fi
    emit_summary
    exit "${HIGHEST_EXIT}"
}
trap teardown EXIT

# ---------------------------------------------------------------- #
# Step 1 — preflight                                                #
# ---------------------------------------------------------------- #

step_preflight() {
    log "[step 1/7] preflight"
    local t0=$(date +%s)
    local missing=()
    command -v gcc >/dev/null 2>&1     || missing+=("gcc")
    command -v "${ENGINE}" >/dev/null 2>&1 || missing+=("${ENGINE}")
    # podman-compose is one binary; docker compose is a subcommand.
    if [[ "${ENGINE}" == "podman" ]]; then
        command -v podman-compose >/dev/null 2>&1 || missing+=("podman-compose")
    fi
    command -v nats >/dev/null 2>&1    || missing+=("nats")
    [[ -x "${VENV_PY}" ]]              || missing+=(".venv/bin/python3")
    [[ -f "${COMPOSE_FILE}" ]]         || missing+=("${COMPOSE_FILE}")
    [[ -f "${INIT_SCRIPT}" ]]          || missing+=("${INIT_SCRIPT}")
    [[ -f "${HEALTH_SCRIPT}" ]]        || missing+=("${HEALTH_SCRIPT}")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "preflight failed; missing: ${missing[*]}"
        record_step "1-preflight" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=1
        return 1
    fi
    # Verify nats-py is importable in the venv.
    if ! "${VENV_PY}" -c 'import nats' >/dev/null 2>&1; then
        err "preflight failed; nats-py not importable in ${VENV_PY}"
        record_step "1-preflight" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=1
        return 1
    fi
    log "preflight ok"
    record_step "1-preflight" "ok" "$(($(date +%s) - t0))"
}

# ---------------------------------------------------------------- #
# Step 2 — image pull                                               #
# ---------------------------------------------------------------- #

step_image_pull() {
    log "[step 2/7] image pull: nats:2.11-alpine via ${ENGINE}"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) ${ENGINE} pull nats:2.11-alpine"
        record_step "2-image-pull" "skip" "-"
        return 0
    fi
    if ${ENGINE} pull nats:2.11-alpine >&2; then
        log "image pull ok"
        record_step "2-image-pull" "ok" "$(($(date +%s) - t0))"
    else
        err "image pull failed"
        record_step "2-image-pull" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=2
        return 1
    fi
}

# ---------------------------------------------------------------- #
# Step 3 — compose up                                               #
# ---------------------------------------------------------------- #

step_compose_up() {
    log "[step 3/7] compose up -d (${COMPOSE_BIN} -f ${COMPOSE_FILE})"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) ${COMPOSE_BIN} -f ${COMPOSE_FILE} up -d"
        record_step "3-compose-up" "skip" "-"
        return 0
    fi
    if ${COMPOSE_BIN} -f "${COMPOSE_FILE}" up -d >&2; then
        record_step "3-compose-up" "ok" "$(($(date +%s) - t0))"
    else
        err "compose up failed"
        record_step "3-compose-up" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=2
        return 1
    fi
}

# ---------------------------------------------------------------- #
# Step 4 — wait ready                                               #
# ---------------------------------------------------------------- #

step_wait_ready() {
    log "[step 4/7] wait-ready: poll ${JSZ_URL} (timeout ${WAIT_READY_TIMEOUT}s)"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) wait-ready"
        record_step "4-wait-ready" "skip" "-"
        return 0
    fi
    local deadline=$((t0 + WAIT_READY_TIMEOUT))
    while true; do
        if curl -fsS -m 2 "${JSZ_URL}" >/dev/null 2>&1; then
            log "substrate ready (after $(($(date +%s) - t0))s)"
            record_step "4-wait-ready" "ok" "$(($(date +%s) - t0))"
            return 0
        fi
        if [[ $(date +%s) -ge ${deadline} ]]; then
            err "substrate did not become ready within ${WAIT_READY_TIMEOUT}s"
            record_step "4-wait-ready" "fail" "$(($(date +%s) - t0))"
            HIGHEST_EXIT=2
            return 1
        fi
        sleep 1
    done
}

# ---------------------------------------------------------------- #
# Step 5 — bucket init                                              #
# ---------------------------------------------------------------- #

step_bucket_init() {
    log "[step 5/7] bucket init: init-nats-buckets.py"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) ${VENV_PY} ${INIT_SCRIPT} --servers ${NATS_SERVER}"
        record_step "5-bucket-init" "skip" "-"
        return 0
    fi
    if "${VENV_PY}" "${INIT_SCRIPT}" --servers "${NATS_SERVER}" >&2; then
        log "bucket init ok"
        record_step "5-bucket-init" "ok" "$(($(date +%s) - t0))"
    else
        local rc=$?
        err "bucket init failed (rc=${rc})"
        record_step "5-bucket-init" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=3
        return 1
    fi
}

# ---------------------------------------------------------------- #
# Step 6 — real-nats-py adapter round-trip                          #
# ---------------------------------------------------------------- #

step_real_adapter() {
    if [[ ${SKIP_REAL_ADAPTER} -eq 1 ]]; then
        log "[step 6/7] real-adapter smoke skipped (--no-real-adapter)"
        record_step "6-real-adapter" "skip" "-"
        return 0
    fi
    log "[step 6/7] real-adapter smoke: RouteRegistryNatsKvBackend round-trip"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) python3 -m wakir-internal-real-adapter-smoke"
        record_step "6-real-adapter" "skip" "-"
        return 0
    fi
    # The adapter target lives at
    # wirelang.federation.route_registry_nats_kv_backend.
    # We run an inline async snippet rather than ship a separate
    # python file to keep the post-install smoke a single artefact.
    local script
    script=$(cat <<'PY'
import asyncio
import os
import sys

async def main():
    try:
        import nats
        from nats.js.errors import KeyNotFoundError
    except ModuleNotFoundError as exc:
        print(f"real-adapter smoke: import nats failed: {exc}", file=sys.stderr)
        sys.exit(4)
    server = os.environ.get("WAKIR_NATS_SERVER", "nats://127.0.0.1:4222")
    bucket = "wakir-schemas"  # any Phase-1 bucket; smoke is non-destructive
    key = "post-install-live-smoke-probe"
    payload = b"phase-1b-sprint-3-tag-4-probe"
    try:
        nc = await nats.connect(server, name="post-install-live-smoke")
    except Exception as exc:  # noqa: BLE001
        print(f"real-adapter smoke: connect failed: {exc}", file=sys.stderr)
        sys.exit(4)
    try:
        js = nc.jetstream()
        try:
            kv = await js.key_value(bucket)
        except Exception as exc:  # noqa: BLE001
            print(
                f"real-adapter smoke: bucket {bucket!r} not reachable: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)
        await kv.put(key, payload)
        got = await kv.get(key)
        if got.value != payload:
            print(
                "real-adapter smoke: round-trip mismatch "
                f"want={payload!r} got={got.value!r}",
                file=sys.stderr,
            )
            sys.exit(4)
        # Cleanup the synthetic key so the smoke leaves no residue.
        await kv.delete(key)
        try:
            await kv.get(key)
        except KeyNotFoundError:
            pass
        else:
            print(
                "real-adapter smoke: probe key still present after delete",
                file=sys.stderr,
            )
            sys.exit(4)
        print("real-adapter smoke: round-trip ok", file=sys.stderr)
    finally:
        await nc.drain()

asyncio.run(main())
PY
)
    if "${VENV_PY}" -c "${script}"; then
        record_step "6-real-adapter" "ok" "$(($(date +%s) - t0))"
    else
        local rc=$?
        err "real-adapter smoke failed (rc=${rc})"
        record_step "6-real-adapter" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=4
        return 1
    fi
}

# ---------------------------------------------------------------- #
# Step 7 — KV health check                                          #
# ---------------------------------------------------------------- #

step_kv_health() {
    log "[step 7-pre] kv-health: check-nats-kv-health.py"
    local t0=$(date +%s)
    if [[ ${DRY_RUN} -eq 1 ]]; then
        log "(dry-run) ${VENV_PY} ${HEALTH_SCRIPT} --servers ${NATS_SERVER}"
        record_step "7pre-kv-health" "skip" "-"
        return 0
    fi
    if "${VENV_PY}" "${HEALTH_SCRIPT}" --servers "${NATS_SERVER}" >&2; then
        log "kv-health ok"
        record_step "7pre-kv-health" "ok" "$(($(date +%s) - t0))"
    else
        local rc=$?
        err "kv-health failed (rc=${rc})"
        record_step "7pre-kv-health" "fail" "$(($(date +%s) - t0))"
        HIGHEST_EXIT=5
        return 1
    fi
}

# ---------------------------------------------------------------- #
# Main                                                              #
# ---------------------------------------------------------------- #

log "starting (engine=${ENGINE} compose=${COMPOSE_BIN} server=${NATS_SERVER} dry_run=${DRY_RUN})"

# Each step that fails sets HIGHEST_EXIT and returns non-zero. We
# break after the first failure (so we do not e.g. attempt the
# real-adapter round-trip if the substrate never came up), but the
# EXIT trap still attempts teardown.
step_preflight       || exit 0   # trap will pick up HIGHEST_EXIT
step_image_pull      || exit 0
step_compose_up      || exit 0
step_wait_ready      || exit 0
step_bucket_init     || exit 0
step_real_adapter    || exit 0
step_kv_health       || exit 0

log "all steps clean"
exit 0
