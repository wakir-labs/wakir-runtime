#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT one-command smoke driver for external auditors and CI pipelines.
#
# Generates a small synthetic event spool, walks the production
# pipeline (build -> stamp -> verify-pending), optionally waits for
# the upgrade-to-Bitcoin window, and exits with the same code shape
# as ``wakir-verify``:
#
#   0  finalised on Bitcoin (verified end to end)
#   1  failed (proof or receipt mismatch, missing manifest, ...)
#   3  pending (proof OK, OTS receipt not yet on Bitcoin)
#   4  chain-mismatch (--chain-check only; not exercised here)
#
# Usage
# -----
#
#   bash scripts/wat-smoke-test.sh           # full run, ~5 min sleep
#   bash scripts/wat-smoke-test.sh --quick   # skip the upgrade wait
#
# Talks to the public OTS calendars via the production code path.
# Be polite — one full smoke run = 1 calendar submission. Do not
# run this in a tight loop.

set -euo pipefail

QUICK=0
case "${1:-}" in
    --quick)  QUICK=1 ;;
    "" )      ;;
    -h|--help)
        sed -n '1,30p' "$0"
        exit 0
        ;;
    *)
        printf '[wat-smoke] unknown argument: %s\n' "$1" >&2
        exit 64
        ;;
esac

log() { printf '[wat-smoke] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR="$(mktemp -d -t wat-smoke-XXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

HOUR_SLOT="$(date -u '+%Y-%m-%dT%H')"
SPOOL_FILE="${WORK_DIR}/${HOUR_SLOT}.jsonl"
ARCHIVE_DIR="${WORK_DIR}/archive"
HOUR_DIR="${ARCHIVE_DIR}/${HOUR_SLOT}"
mkdir -p "${HOUR_DIR}"

log "work_dir=${WORK_DIR} hour_slot=${HOUR_SLOT} quick=${QUICK}"

# 1. Synthetic events (8 events, valid B1-consensus shape).
python - <<PY > "${SPOOL_FILE}"
import json, secrets
hour = "${HOUR_SLOT}"
for i in range(8):
    print(json.dumps({
        "event_id": f"smoke-{i:04d}",
        "time": f"{hour}:{i:02d}:00Z",
        "payload_hash": secrets.token_hex(32),
        "capability_token_hash": secrets.token_hex(32),
    }))
PY
log "spooled $(wc -l < "${SPOOL_FILE}") events"

# 2. Build the manifest. wakir-merkle must be on PATH (.venv).
log "build manifest"
python -m wat.cmd.aggregator_cli build \
    --hour "${HOUR_SLOT}" \
    --input-events "${SPOOL_FILE}" \
    --output-manifest "${HOUR_DIR}/manifest.json"

ROOT_HEX="$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['merkle_root'])" "${HOUR_DIR}/manifest.json")"
log "merkle_root=${ROOT_HEX}"

# 3. Stamp via OTS public calendars (-m 2 default, two-of-N).
log "stamp via OTS"
python -m wat.cmd.anchor_cli stamp "${ROOT_HEX}" --out "${HOUR_DIR}" --min-calendars 2

# 4. Verify-pending. Exit code 3 = pending (expected on a fresh stamp).
log "verify (pending tolerated)"
set +e
python -m wat.verify.cli "smoke-0003" --archive-dir "${ARCHIVE_DIR}" --quiet
RC=$?
set -e
log "verify_rc=${RC}"

if [[ "${QUICK}" == "1" ]]; then
    log "quick mode: skipping upgrade wait, exit ${RC}"
    exit "${RC}"
fi

# 5. Optional upgrade leg. Calendar batches typically take 10 min - 6 h
#    to land in Bitcoin; we only wait 5 min as a smoke step.
log "sleep 300s before upgrade"
sleep 300

log "ots upgrade"
ots upgrade "${HOUR_DIR}/root.bin.ots" || log "upgrade still pending (expected)"

set +e
python -m wat.verify.cli "smoke-0003" --archive-dir "${ARCHIVE_DIR}" --quiet
RC=$?
set -e
log "verify_rc=${RC} (0=finalised, 3=still pending)"
exit "${RC}"
