#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT TV-2 persistent multi-hour chain-check live-run driver.
#
# Builds a deterministic ``H``-hour event chain (default ``H=4``,
# overridable via ``WAT_TV2_HOURS``), aggregates each hour with the
# production aggregator carrying the previous hour's Merkle root in
# the manifest's ``prev_hour_root`` slot, anchors each hour through
# the four production OpenTimestamps calendars, and persists the
# manifests + pending receipts to a dedicated archive directory
# outside of the public repo so that
# ``scripts/wat-block-heights-collect.sh`` can be re-run on day +1
# to harvest the resulting Bitcoin block heights.
#
# This script is the integration mirror of TV-2's gated pytest
# (``tests/wat/test_tv2_chain_check_real.py``): same hour spool
# layout, same fixed anchor slot, same prev-hour-root wiring. Where
# the gated pytest exits inside a tmp_path and prefers Python-native
# orchestration, this driver persists the receipts so the long-tail
# Bitcoin batch cadence can be observed across days the same way as
# TV-1's ``scripts/wat-tv1-run-persistent.sh``.
#
# Politeness
# ----------
#
# Talks to each of the four default public OTS calendars exactly
# once per hour-slot, ``H`` hour-slots in series. Default load is
# ``H × 4 = 16`` calendar submits per run. A 2-second sleep between
# hour-stamps spreads the submits enough to avoid bursty rate
# limits on any single calendar. Re-running the script in the same
# fixed-anchor hour-set is deterministic — the Merkle roots are
# byte-for-byte stable — but should not be done in tight loops; the
# production calendars are a courtesy resource.
#
# Usage
# -----
#
#   bash scripts/wat-tv2-run-persistent.sh [archive-root]
#
#   WAT_TV2_HOURS=4 (default, valid range 4-6) — number of contiguous
#                   hours in the chain
#   WAT_TV2_HOUR_BASE=2026-05-27T00 — hour-0 slot (default matches the
#                                     gated pytest fixture)
#   WAT_TV2_INTER_HOUR_SLEEP=2 — seconds between hour-stamps
#
# Defaults
# --------
#
#   archive-root  ./.runtime/wat-tv2-archive/<run-utc>/
#                 The archive root .runtime/ is in .gitignore (local
#                 only, never pushed to the public repo).
#
# Layout per run
# --------------
#
#   <archive-root>/
#       run.log                      — tee'd output of this script
#       summary.txt                  — single-line outbox-friendly
#                                      summary
#       <hour-0-slot>/
#           tv2.jsonl                — 5-event spool for hour 0
#           manifest.json            — aggregator output (prev=null)
#           root.bin                 — Merkle root binary
#           root.bin.ots             — OTS receipt (4 calendars)
#       <hour-1-slot>/
#           tv2.jsonl
#           manifest.json            — prev_hour_root = hour-0 root
#           root.bin
#           root.bin.ots
#       ...
#
# Exit codes
# ----------
#
#   0  all H hours stamped + manifests written
#   1  spool generation drift (event count mismatch)
#   2  aggregator/anchor failure on any hour
#   3  ots binary not on PATH
#   4  prev_hour_root wiring mismatch (manifest h+1 prev field !=
#      manifest h merkle_root)

set -euo pipefail

log() { printf '[wat-tv2-run] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_UTC="$(date -u '+%Y%m%dT%H%M%SZ')"
DEFAULT_ARCHIVE_ROOT="${REPO_ROOT}/.runtime/wat-tv2-archive/${RUN_UTC}"
ARCHIVE_ROOT="${1:-${DEFAULT_ARCHIVE_ROOT}}"
RUN_LOG="${ARCHIVE_ROOT}/run.log"
SUMMARY_FILE="${ARCHIVE_ROOT}/summary.txt"

H="${WAT_TV2_HOURS:-4}"
HOUR_BASE="${WAT_TV2_HOUR_BASE:-2026-05-27T00}"
INTER_HOUR_SLEEP="${WAT_TV2_INTER_HOUR_SLEEP:-2}"

# Validate H ∈ {4, 5, 6}. Wider ranges are not budget-safe against
# the public calendars in a single run (see TV-2 plan §2).
case "${H}" in
    4|5|6) ;;
    *)
        printf '[wat-tv2-run] ERROR: WAT_TV2_HOURS=%s not in {4,5,6}\n' \
            "${H}" >&2
        exit 1
        ;;
esac

mkdir -p "${ARCHIVE_ROOT}"
exec > >(tee -a "${RUN_LOG}") 2>&1

log "repo_root=${REPO_ROOT}"
log "archive_root=${ARCHIVE_ROOT}"
log "hours=${H} hour_base=${HOUR_BASE} inter_hour_sleep=${INTER_HOUR_SLEEP}s"
log "started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if ! command -v ots >/dev/null 2>&1; then
    log "ERROR: ots CLI not on PATH; run scripts/setup.sh"
    exit 3
fi

# ---------------------------------------------------------------------------
# Hour-slot expansion. Splits HOUR_BASE = "YYYY-MM-DDTHH" into a date
# part and an integer hour, then walks H-1 +1h steps. This stays
# pure-bash so the script does not need ``date -d`` (which differs
# between GNU coreutils and BusyBox).
# ---------------------------------------------------------------------------

DATE_PART="${HOUR_BASE%T*}"
HOUR_PART="${HOUR_BASE#*T}"
# Strip a leading zero so ${BASH_REMATCH} arithmetic does not parse
# "08", "09" etc. as octal.
HOUR_INT=$((10#${HOUR_PART}))

declare -a HOUR_SLOTS=()
for ((i = 0; i < H; i++)); do
    h=$((HOUR_INT + i))
    if (( h > 23 )); then
        # TV-2 plan §1 fixes the anchor at 2026-05-27T00 with H ≤ 6,
        # so this never trips in the default config. We refuse to roll
        # the date silently — operators wanting cross-midnight chains
        # need to opt in by re-baselining HOUR_BASE.
        log "ERROR: hour ${h} exceeds 23 (cross-midnight not supported)"
        exit 1
    fi
    HOUR_SLOTS+=("$(printf '%sT%02d' "${DATE_PART}" "${h}")")
done

log "hour_slots: ${HOUR_SLOTS[*]}"

# ---------------------------------------------------------------------------
# 1. Generate one 5-event spool per hour, deterministic.
#
# The Python heredoc mirrors tests/wat/test_tv2_chain_check_real.py's
# event generator byte-for-byte (same constants, same iteration). Drift
# between this driver and the test would surface as a different
# Merkle root, caught downstream by the verify-CLI cross-check.
# ---------------------------------------------------------------------------

EVENTS_PER_HOUR=5

log "step 1/${H}+: generating ${H} hour spools (${EVENTS_PER_HOUR} events each)"

for ((i = 0; i < H; i++)); do
    SLOT="${HOUR_SLOTS[i]}"
    HOUR_DIR="${ARCHIVE_ROOT}/${SLOT}"
    SPOOL_FILE="${HOUR_DIR}/tv2.jsonl"
    mkdir -p "${HOUR_DIR}"
    python3 - "${SPOOL_FILE}" "${SLOT}" "${i}" "${EVENTS_PER_HOUR}" <<'PY'
import hashlib
import json
import sys

SPOOL_FILE = sys.argv[1]
HOUR_SLOT = sys.argv[2]
HOUR_INDEX = int(sys.argv[3])
EVENT_COUNT = int(sys.argv[4])

CAP_TOKENS = ("tv2-cap-0", "tv2-cap-1", "tv2-cap-2")


def hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


events = []
for i in range(EVENT_COUNT):
    minute = i * 10  # 10-minute spacing per TV-2 plan §1
    second = 0
    millis = 0
    cap_seed = CAP_TOKENS[i % len(CAP_TOKENS)]
    events.append(
        {
            "event_id": f"evt-tv2-{HOUR_INDEX:02d}-{i:04d}",
            "time": f"{HOUR_SLOT}:{minute:02d}:{second:02d}.{millis:03d}Z",
            "payload_hash": hex_sha256(f"tv2-h{HOUR_INDEX}-payload-{i}"),
            "capability_token_hash": hex_sha256(cap_seed),
            "agent_did": f"did:wakir:tv2-h{HOUR_INDEX}-agent",
        }
    )

with open(SPOOL_FILE, "w", encoding="utf-8") as fh:
    for ev in events:
        fh.write(json.dumps(ev) + "\n")

print(f"[gen] hour {HOUR_INDEX} ({HOUR_SLOT}): wrote {len(events)} events")
PY

    SPOOLED="$(wc -l < "${SPOOL_FILE}" | tr -d ' ')"
    if [[ "${SPOOLED}" != "${EVENTS_PER_HOUR}" ]]; then
        log "ERROR: hour ${i} expected ${EVENTS_PER_HOUR} events, got ${SPOOLED}"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# 2. Build manifest + stamp per hour, threading prev_hour_root.
# ---------------------------------------------------------------------------

PREV_ROOT=""
declare -a ROOTS=()
declare -a BUILD_ELAPSED=()
declare -a STAMP_ELAPSED=()

for ((i = 0; i < H; i++)); do
    SLOT="${HOUR_SLOTS[i]}"
    HOUR_DIR="${ARCHIVE_ROOT}/${SLOT}"
    SPOOL_FILE="${HOUR_DIR}/tv2.jsonl"
    MANIFEST_FILE="${HOUR_DIR}/manifest.json"

    log "step 2.${i}/${H}: building manifest hour=${SLOT} prev=${PREV_ROOT:-<null>}"

    BUILD_T0=$(date -u '+%s')
    if [[ -z "${PREV_ROOT}" ]]; then
        # Hour 0: cold-start, prev_hour_root absent (defaults null).
        python3 -m wat.cmd.aggregator_cli build \
            --hour "${SLOT}" \
            --input-events "${SPOOL_FILE}" \
            --output-manifest "${MANIFEST_FILE}"
    else
        python3 -m wat.cmd.aggregator_cli build \
            --hour "${SLOT}" \
            --input-events "${SPOOL_FILE}" \
            --output-manifest "${MANIFEST_FILE}" \
            --prev-hour-root "${PREV_ROOT}"
    fi
    BUILD_T1=$(date -u '+%s')
    BUILD_ELAPSED+=($((BUILD_T1 - BUILD_T0)))

    ROOT_HEX="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['merkle_root'])" "${MANIFEST_FILE}")"
    ROOTS+=("${ROOT_HEX}")
    log "  hour=${SLOT} merkle_root=${ROOT_HEX}"

    # Sanity: prev_hour_root in manifest matches what we threaded in.
    MANIFEST_PREV="$(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(m.get('prev_hour_root') or '')" "${MANIFEST_FILE}")"
    if [[ "${MANIFEST_PREV}" != "${PREV_ROOT}" ]]; then
        log "ERROR: hour ${i} manifest prev_hour_root=${MANIFEST_PREV} != threaded ${PREV_ROOT}"
        exit 4
    fi

    log "step 3.${i}/${H}: stamping merkle_root via 4 default calendars"
    STAMP_T0=$(date -u '+%s')
    python3 -m wat.cmd.anchor_cli stamp "${ROOT_HEX}" \
        --out "${HOUR_DIR}" \
        --min-calendars 2
    STAMP_T1=$(date -u '+%s')
    STAMP_ELAPSED+=($((STAMP_T1 - STAMP_T0)))

    if [[ ! -f "${HOUR_DIR}/root.bin.ots" ]]; then
        log "ERROR: hour ${i} stamp produced no root.bin.ots"
        exit 2
    fi
    RECEIPT_BYTES="$(wc -c < "${HOUR_DIR}/root.bin.ots" | tr -d ' ')"
    log "  hour=${SLOT} stamp_elapsed_s=$((STAMP_T1 - STAMP_T0)) receipt_bytes=${RECEIPT_BYTES}"

    PREV_ROOT="${ROOT_HEX}"

    if (( i + 1 < H )); then
        log "  inter-hour sleep ${INTER_HOUR_SLEEP}s (calendar politeness)"
        sleep "${INTER_HOUR_SLEEP}"
    fi
done

# ---------------------------------------------------------------------------
# 3. Verify-CLI sample run on the last hour with --chain-check. Pending
#    (exit 3) is expected today; chain-verified (exit 0) is expected
#    once Bitcoin batch cadence catches up. Either is OK for this
#    driver — block-heights-collect.sh on day +1 finalises the picture.
# ---------------------------------------------------------------------------

LAST_HOUR_INDEX=$((H - 1))
LAST_SLOT="${HOUR_SLOTS[${LAST_HOUR_INDEX}]}"
SAMPLE_EVENT="evt-tv2-$(printf '%02d' "${LAST_HOUR_INDEX}")-0000"

log "step 4/${H}: verify sample event (--chain-check, pending tolerated)"
set +e
python3 -m wat.verify.cli "${SAMPLE_EVENT}" \
    --archive-dir "${ARCHIVE_ROOT}" \
    --chain-check \
    --quiet
VERIFY_RC=$?
set -e
log "verify_rc=${VERIFY_RC} (0=verified+chain-verified, 3=pending — both expected today)"

# ---------------------------------------------------------------------------
# 4. Single-line summary for the outbox memo.
# ---------------------------------------------------------------------------

JOINED_ROOTS="$(IFS=,; echo "${ROOTS[*]}")"
SUMMARY="hours=${H} hour_base=${HOUR_BASE} archive=${ARCHIVE_ROOT} verify_rc=${VERIFY_RC} roots=${JOINED_ROOTS}"
log "summary: ${SUMMARY}"
printf '%s\n' "${SUMMARY}" > "${SUMMARY_FILE}"

log "next: in ~3-24h re-run scripts/wat-block-heights-collect.sh ${ARCHIVE_ROOT} to harvest Bitcoin block heights"
log "completed=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit 0
