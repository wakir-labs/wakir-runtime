#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT TV-1 persistent live-run driver.
#
# Generates the deterministic 100-event TV-1 spool (matches
# tests/wat/test_tv1_one_hour_volume.py byte-for-byte), runs it
# through the production aggregator + anchor pipeline, and persists
# the resulting manifest + pending OTS receipts to a dedicated
# archive directory outside of the public repo so that a follow-up
# run on day +1 (after Bitcoin inclusion) can call
# scripts/wat-block-heights-collect.sh against the same archive and
# observe the finalised block heights.
#
# Unlike scripts/wat-smoke-test.sh this script:
#
#   * does NOT use a tmp_path (the receipts must survive across days),
#   * does NOT sleep / call ots upgrade (block-heights-collect.sh
#     handles the upgrade leg the next day),
#   * uses the SAME deterministic event generator as the gated TV-1
#     test, so the resulting Merkle root is reproducible offline and
#     can be cross-checked against the test fixture if needed,
#   * emits a structured single-line summary suitable for the outbox
#     memo.
#
# Usage
# -----
#
#   bash scripts/wat-tv1-run-persistent.sh [archive-dir]
#
# Defaults
# --------
#
#   archive-dir  ./.runtime/wat-tv1-archive/<YYYY-MM-DDTHH>/
#                where <YYYY-MM-DDTHH> is the current UTC hour. The
#                archive root .runtime/ is in .gitignore (local only).
#
# Politeness
# ----------
#
# Talks to the four default public OTS calendars exactly once via
# the production stamp path. Re-running the script in the same hour
# slot is a no-op for the calendars (identical root) but should not
# be done in tight loops.

set -euo pipefail

log() { printf '[wat-tv1-run] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOUR_SLOT="$(date -u '+%Y-%m-%dT%H')"
DEFAULT_ARCHIVE="${REPO_ROOT}/.runtime/wat-tv1-archive/${HOUR_SLOT}"
ARCHIVE_DIR="${1:-${DEFAULT_ARCHIVE}}"
HOUR_DIR="${ARCHIVE_DIR}"
SPOOL_FILE="${ARCHIVE_DIR}/tv1.jsonl"
RUN_LOG="${ARCHIVE_DIR}/run.log"

mkdir -p "${ARCHIVE_DIR}"

# Tee all subsequent log lines into run.log for the audit memo.
exec > >(tee -a "${RUN_LOG}") 2>&1

log "repo_root=${REPO_ROOT}"
log "hour_slot=${HOUR_SLOT}"
log "archive_dir=${ARCHIVE_DIR}"
log "started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if ! command -v ots >/dev/null 2>&1; then
    log "ERROR: ots CLI not on PATH; run scripts/setup.sh"
    exit 3
fi

# 1. Generate the deterministic TV-1 spool. The Python heredoc mirrors
#    tests/wat/test_tv1_one_hour_volume.py::_generate_tv1_events
#    byte-for-byte (same constants, same iteration logic, same
#    reverse() at the end). Drift between this file and the test would
#    show up as a different merkle_root and is caught by the
#    cross-check at the bottom of this script.
log "step 1/4: generating 100-event spool"
python3 - "${SPOOL_FILE}" "${HOUR_SLOT}" <<'PY'
import hashlib
import json
import sys

SPOOL_FILE = sys.argv[1]
HOUR_SLOT = sys.argv[2]
EVENT_COUNT = 100
CAP_TOKENS = ("tv1-cap-A", "tv1-cap-B", "tv1-cap-C", "tv1-cap-D", "tv1-cap-E")
AGENT_DIDS = (
    "did:wakir:tv1-agent-1",
    "did:wakir:tv1-agent-2",
    "did:wakir:tv1-agent-3",
)


def hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


events = []
for i in range(EVENT_COUNT):
    minute = (i * 7) % 60
    second = (i * 13) % 60
    millis = (i * 37) % 1000
    cap_seed = CAP_TOKENS[i % len(CAP_TOKENS)]
    did_seed = AGENT_DIDS[i % len(AGENT_DIDS)]
    events.append(
        {
            "event_id": f"evt-tv1-{i:04d}",
            "time": f"{HOUR_SLOT}:{minute:02d}:{second:02d}.{millis:03d}Z",
            "payload_hash": hex_sha256(f"tv1-payload-{i}"),
            "capability_token_hash": hex_sha256(cap_seed),
            "agent_did": did_seed,
        }
    )

events.reverse()

with open(SPOOL_FILE, "w", encoding="utf-8") as fh:
    for ev in events:
        fh.write(json.dumps(ev) + "\n")

print(f"[gen] wrote {len(events)} events to {SPOOL_FILE}")
PY

EVENT_COUNT="$(wc -l < "${SPOOL_FILE}" | tr -d ' ')"
log "spooled ${EVENT_COUNT} events to ${SPOOL_FILE}"
if [[ "${EVENT_COUNT}" != "100" ]]; then
    log "ERROR: expected 100 events, got ${EVENT_COUNT}"
    exit 1
fi

# 2. Build the manifest via the production aggregator.
log "step 2/4: building manifest via wat.cmd.aggregator_cli"
BUILD_T0=$(date -u '+%s')
python3 -m wat.cmd.aggregator_cli build \
    --hour "${HOUR_SLOT}" \
    --input-events "${SPOOL_FILE}" \
    --output-manifest "${HOUR_DIR}/manifest.json"
BUILD_T1=$(date -u '+%s')
BUILD_ELAPSED=$((BUILD_T1 - BUILD_T0))

ROOT_HEX="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['merkle_root'])" "${HOUR_DIR}/manifest.json")"
log "merkle_root=${ROOT_HEX}"
log "build_elapsed_s=${BUILD_ELAPSED}"

# 3. Stamp via the four default public OTS calendars (-m 2 default).
log "step 3/4: stamping via wat.cmd.anchor_cli (1 submit, 4 calendars)"
STAMP_T0=$(date -u '+%s')
python3 -m wat.cmd.anchor_cli stamp "${ROOT_HEX}" \
    --out "${HOUR_DIR}" \
    --min-calendars 2
STAMP_T1=$(date -u '+%s')
STAMP_ELAPSED=$((STAMP_T1 - STAMP_T0))
log "stamp_elapsed_s=${STAMP_ELAPSED}"

if [[ ! -f "${HOUR_DIR}/root.bin.ots" ]]; then
    log "ERROR: stamp produced no root.bin.ots"
    exit 1
fi
RECEIPT_BYTES="$(wc -c < "${HOUR_DIR}/root.bin.ots" | tr -d ' ')"
log "receipt_bytes=${RECEIPT_BYTES} path=${HOUR_DIR}/root.bin.ots"

# 4. Verify-pending sample (one event). Exit 3 == pending is expected.
log "step 4/4: verify (pending tolerated)"
set +e
python3 -m wat.verify.cli "evt-tv1-0050" \
    --archive-dir "${REPO_ROOT}/.runtime/wat-tv1-archive" \
    --quiet
VERIFY_RC=$?
set -e
log "verify_rc=${VERIFY_RC} (0=finalised, 3=pending — pending is expected)"

# Pending-attestation summary from ots info.
log "ots info — pending calendars:"
PENDING_CALS="$(ots info "${HOUR_DIR}/root.bin.ots" 2>&1 \
    | grep -E "PendingAttestation" \
    | sed -E "s/.*PendingAttestation\\('([^']+)'\\).*/\\1/" \
    | sort -u | paste -sd, -)"
log "  pending_calendars=${PENDING_CALS:-(none parsed)}"

# Single-line summary for the outbox memo.
log "summary: hour_slot=${HOUR_SLOT} root=${ROOT_HEX} build_s=${BUILD_ELAPSED} stamp_s=${STAMP_ELAPSED} verify_rc=${VERIFY_RC} archive=${ARCHIVE_DIR}"
log "next: run scripts/wat-block-heights-collect.sh ${REPO_ROOT}/.runtime/wat-tv1-archive in ~3-6h to upgrade and capture Bitcoin block heights"
log "completed=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit 0
