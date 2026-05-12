#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT TV-3 backfill-behaviour persistent live-run driver.
#
# This driver exercises the backfill daemon's behavioural contract
# (see ``wat/anchor/backfill.py:process_pending_queue`` and the gated
# pytest ``tests/wat/test_tv3_backfill_leg.py``) against a synthetic
# pending-receipt archive whose mtimes are deterministically aged
# past the seven-day soft window from WAT-Phase-1a-Spec §3.4.
#
# Unlike TV-1 (single-hour stamp + day-+1 collect) and TV-2 (multi-
# hour chained stamps + day-+1 collect), TV-3 is **not** a calendar-
# politeness-heavy run: it spends zero submits on the production
# OpenTimestamps calendars by default. The behavioural surface under
# test is the daemon's age-vs-finalisation logic, exercised against
# a stub upgrader that returns a deterministic pending result.
#
# Submit cadence pacing
# ---------------------
#
# When ``WAT_TV3_LIVE_STAMP=1`` is set, the driver additionally
# submits the synthetic Merkle root through the four default public
# OTS calendars exactly once per archive run. Submit cadence pacing
# is enforced via a daily budget file
# (``.runtime/wat-tv3-archive/.daily-budget.json``): no more than
# ``WAT_TV3_DAILY_SUBMIT_BUDGET`` (default 4) submits per UTC day.
# A run that would breach the budget refuses to stamp, completes
# the rest of the behavioural probe, and exits 6 (budget breach).
# Multi-day live-run sequences are therefore staged across several
# UTC days by re-invoking the driver — the budget file is the
# resume substrate.
#
# Resume path
# -----------
#
# A run interrupted between archive layout and behavioural probe
# can be resumed via ``WAT_TV3_RESUME_FROM=<archive-root>``. The
# driver detects the per-receipt state file in
# ``<archive-root>/.state.json`` and skips already-completed steps
# (synthetic-aging, backfill-probe). The state file is the single
# source of truth for resume — losing it forces a full re-run.
#
# Day-+1 harvest
# --------------
#
# The behavioural probe reports immediately and does not wait for a
# Bitcoin batch. There is no day-+1 harvest leg analogous to TV-1's
# ``wat-block-heights-collect.sh`` — the contract under test is the
# alarm-flagging behaviour against the local clock, not the Bitcoin
# finalisation latency.
#
# Usage
# -----
#
#   bash scripts/wat-tv3-run-persistent.sh [archive-root]
#
#   WAT_TV3_HOUR_BASE=2026-05-26T17 — synthetic hour slot, must
#                                      match the gated test fixture
#                                      shape (``YYYY-MM-DDTHH``).
#   WAT_TV3_AGE_HOURS=192          — age in hours to apply to the
#                                      synthetic .ots receipt mtime
#                                      (default 192 = 8.0 days,
#                                      crosses the 7-day soft window).
#   WAT_TV3_LIVE_STAMP=0           — when set to 1, additionally
#                                      submits one stamp through the
#                                      4 default calendars (subject
#                                      to the daily budget).
#   WAT_TV3_DAILY_SUBMIT_BUDGET=4  — max submits per UTC day.
#   WAT_TV3_RESUME_FROM=           — when set, resume from existing
#                                      archive-root rather than
#                                      starting a fresh run.
#
# Defaults
# --------
#
#   archive-root  ./.runtime/wat-tv3-archive/<run-utc>/
#                 The archive root .runtime/ is in .gitignore (local
#                 only, never pushed to the public repo).
#
# Layout per run
# --------------
#
#   <archive-root>/
#       run.log                   — tee'd output of this script
#       summary.txt               — single-line outbox-friendly
#                                    summary
#       .state.json               — resume substrate
#       <hour-slot>/
#           tv3.jsonl             — 1-event spool (deterministic)
#           manifest.json         — aggregator output (prev=null)
#           root.bin              — Merkle root binary
#           root.bin.ots          — synthetic .ots receipt
#                                    (mtime aged past soft window)
#           backfill-probe.json   — behavioural-probe result capture
#
# Exit codes
# ----------
#
#   0  hard-alarm correctly flagged for the aged receipt
#   1  spool generation drift (event count mismatch)
#   2  aggregator/manifest build failure
#   3  ots binary not on PATH
#   4  hard-alarm NOT flagged (bug in the backfill code path)
#   5  resume-state corruption (state.json malformed)
#   6  daily submit budget breach (live-stamp refused)
#   7  live-stamp receipt persistence broken (file too small or
#      synthetic marker still present after stamp)

set -euo pipefail

log() { printf '[wat-tv3-run] %s\n' "$*"; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_UTC="$(date -u '+%Y%m%dT%H%M%SZ')"
DEFAULT_ARCHIVE_ROOT="${REPO_ROOT}/.runtime/wat-tv3-archive/${RUN_UTC}"

# Resume vs. fresh-run selection.
if [[ -n "${WAT_TV3_RESUME_FROM:-}" ]]; then
    ARCHIVE_ROOT="${WAT_TV3_RESUME_FROM}"
    if [[ ! -d "${ARCHIVE_ROOT}" ]]; then
        printf '[wat-tv3-run] ERROR: resume-from %s does not exist\n' \
            "${ARCHIVE_ROOT}" >&2
        exit 5
    fi
else
    ARCHIVE_ROOT="${1:-${DEFAULT_ARCHIVE_ROOT}}"
fi

RUN_LOG="${ARCHIVE_ROOT}/run.log"
SUMMARY_FILE="${ARCHIVE_ROOT}/summary.txt"
STATE_FILE="${ARCHIVE_ROOT}/.state.json"

HOUR_SLOT="${WAT_TV3_HOUR_BASE:-2026-05-26T17}"
AGE_HOURS="${WAT_TV3_AGE_HOURS:-192}"
LIVE_STAMP="${WAT_TV3_LIVE_STAMP:-0}"
DAILY_BUDGET="${WAT_TV3_DAILY_SUBMIT_BUDGET:-4}"
BUDGET_FILE="${WAT_TV3_BUDGET_FILE:-${REPO_ROOT}/.runtime/wat-tv3-archive/.daily-budget.json}"

# Validate HOUR_SLOT shape (YYYY-MM-DDTHH) — same regex as TV-1/TV-2.
if [[ ! "${HOUR_SLOT}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}$ ]]; then
    printf '[wat-tv3-run] ERROR: WAT_TV3_HOUR_BASE=%s not in YYYY-MM-DDTHH form\n' \
        "${HOUR_SLOT}" >&2
    exit 1
fi

# Validate AGE_HOURS as a non-negative integer.
if [[ ! "${AGE_HOURS}" =~ ^[0-9]+$ ]]; then
    printf '[wat-tv3-run] ERROR: WAT_TV3_AGE_HOURS=%s not a non-negative integer\n' \
        "${AGE_HOURS}" >&2
    exit 1
fi

mkdir -p "${ARCHIVE_ROOT}"
exec > >(tee -a "${RUN_LOG}") 2>&1

log "repo_root=${REPO_ROOT}"
log "archive_root=${ARCHIVE_ROOT}"
log "hour_slot=${HOUR_SLOT} age_hours=${AGE_HOURS} live_stamp=${LIVE_STAMP}"
log "started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Validate state file shape up-front so a malformed resume substrate
# fails fast with a dedicated exit code rather than at first read.
if [[ -f "${STATE_FILE}" ]]; then
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
            "${STATE_FILE}" >/dev/null 2>&1; then
        log "ERROR: state file ${STATE_FILE} is malformed"
        exit 5
    fi
fi

if ! command -v ots >/dev/null 2>&1; then
    log "ERROR: ots CLI not on PATH; run scripts/setup.sh"
    exit 3
fi

# ---------------------------------------------------------------------------
# State machine. Steps are recorded in .state.json so a partial run
# can be resumed without re-doing completed steps. Step ordering:
#
#   1. spool        — synthetic spool generated
#   2. manifest     — aggregator manifest built + Merkle root captured
#   3. receipt      — synthetic .ots receipt placed
#   4. aged         — mtime aged by AGE_HOURS
#   5. probe        — backfill behavioural-probe captured
#   6. (optional) stamp — live calendar stamp performed
# ---------------------------------------------------------------------------

read_state() {
    if [[ -f "${STATE_FILE}" ]]; then
        if ! python3 -c "import json,sys;json.load(open(sys.argv[1]))" \
                "${STATE_FILE}" >/dev/null 2>&1; then
            log "ERROR: state file ${STATE_FILE} is malformed"
            exit 5
        fi
        cat "${STATE_FILE}"
    else
        printf '{"steps_done":[]}'
    fi
}

mark_done() {
    local step="$1"
    python3 - "${STATE_FILE}" "${step}" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
step = sys.argv[2]
if state_path.exists():
    state = json.loads(state_path.read_text())
else:
    state = {"steps_done": []}
if step not in state["steps_done"]:
    state["steps_done"].append(step)
state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
PY
}

is_done() {
    local step="$1"
    python3 - "${STATE_FILE}" "${step}" <<'PY'
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
step = sys.argv[2]
if not state_path.exists():
    sys.exit(1)
state = json.loads(state_path.read_text())
sys.exit(0 if step in state.get("steps_done", []) else 1)
PY
}

HOUR_DIR="${ARCHIVE_ROOT}/${HOUR_SLOT}"
SPOOL_FILE="${HOUR_DIR}/tv3.jsonl"
MANIFEST_FILE="${HOUR_DIR}/manifest.json"
ROOT_FILE="${HOUR_DIR}/root.bin"
RECEIPT_FILE="${HOUR_DIR}/root.bin.ots"
PROBE_FILE="${HOUR_DIR}/backfill-probe.json"

mkdir -p "${HOUR_DIR}"

# ---------------------------------------------------------------------------
# 1. Synthetic spool generation. Single deterministic event whose
#    payload bytes match the gated pytest fixture.
# ---------------------------------------------------------------------------

if is_done spool; then
    log "step 1/6: spool already done — skipping (resume)"
else
    log "step 1/6: generating synthetic 1-event spool"
    python3 - "${SPOOL_FILE}" "${HOUR_SLOT}" <<'PY'
import hashlib
import json
import sys

SPOOL_FILE = sys.argv[1]
HOUR_SLOT = sys.argv[2]


def hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


event = {
    "event_id": "evt-tv3-00-0000",
    "time": f"{HOUR_SLOT}:00:00.000Z",
    "payload_hash": hex_sha256("tv3-h0-payload-0"),
    "capability_token_hash": hex_sha256("tv3-cap-0"),
    "agent_did": "did:wakir:tv3-h0-agent",
}

with open(SPOOL_FILE, "w", encoding="utf-8") as fh:
    fh.write(json.dumps(event) + "\n")

print(f"[gen] tv3 hour {HOUR_SLOT}: wrote 1 event")
PY

    SPOOLED="$(wc -l < "${SPOOL_FILE}" | tr -d ' ')"
    if [[ "${SPOOLED}" != "1" ]]; then
        log "ERROR: tv3 expected 1 event, got ${SPOOLED}"
        exit 1
    fi
    mark_done spool
fi

# ---------------------------------------------------------------------------
# 2. Manifest build via the production aggregator (no Bitcoin work).
# ---------------------------------------------------------------------------

if is_done manifest; then
    log "step 2/6: manifest already built — skipping (resume)"
    ROOT_HEX="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['merkle_root'])" "${MANIFEST_FILE}")"
else
    log "step 2/6: building manifest hour=${HOUR_SLOT} (prev=null, cold-start)"
    python3 -m wat.cmd.aggregator_cli build \
        --hour "${HOUR_SLOT}" \
        --input-events "${SPOOL_FILE}" \
        --output-manifest "${MANIFEST_FILE}"

    ROOT_HEX="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['merkle_root'])" "${MANIFEST_FILE}")"
    log "  hour=${HOUR_SLOT} merkle_root=${ROOT_HEX}"
    mark_done manifest
fi

# ---------------------------------------------------------------------------
# 3. Synthetic .ots receipt. We do NOT submit to public calendars
#    by default — TV-3's behavioural surface is the daemon's age
#    handling, not calendar latency. The receipt content is a
#    placeholder byte string; the daemon's stub upgrader (in the
#    gated pytest) does not parse it.
# ---------------------------------------------------------------------------

if is_done receipt; then
    log "step 3/6: receipt already placed — skipping (resume)"
else
    log "step 3/6: writing synthetic .ots receipt"
    # Write the Merkle root as root.bin so verify-CLI cross-checks
    # have something to chew on, even though we don't exercise that
    # leg in the default behavioural run.
    python3 - "${ROOT_FILE}" "${ROOT_HEX}" <<'PY'
import sys
from pathlib import Path

out = Path(sys.argv[1])
root_hex = sys.argv[2]
out.write_bytes(bytes.fromhex(root_hex))
PY
    printf 'SYNTHETIC_TV3_OTS_RECEIPT' > "${RECEIPT_FILE}"
    mark_done receipt
fi

# ---------------------------------------------------------------------------
# 4. Synthetic aging — set mtime to (now - AGE_HOURS).
# ---------------------------------------------------------------------------

if is_done aged; then
    log "step 4/6: receipt already aged — skipping (resume)"
else
    log "step 4/6: aging receipt mtime by ${AGE_HOURS}h (crosses 7-day window if >=168)"
    python3 - "${RECEIPT_FILE}" "${AGE_HOURS}" <<'PY'
import datetime as dt
import os
import sys
from pathlib import Path

receipt = Path(sys.argv[1])
age_hours = float(sys.argv[2])
now = dt.datetime.now(tz=dt.timezone.utc)
target = now - dt.timedelta(hours=age_hours)
ts = target.timestamp()
os.utime(receipt, (ts, ts))
print(f"[age] {receipt.name}: mtime set to {target.isoformat()}")
PY
    mark_done aged
fi

# ---------------------------------------------------------------------------
# 5. Backfill behavioural probe. Calls process_pending_queue with a
#    monkey-patched stub upgrader so no public calendar is touched.
#    Captures the resulting UpgradeResult to backfill-probe.json.
# ---------------------------------------------------------------------------

log "step 5/6: invoking backfill behavioural probe"
set +e
python3 - "${ARCHIVE_ROOT}" "${PROBE_FILE}" <<'PY'
"""Behavioural probe stand-in.

Calls ``process_pending_queue`` against the synthetic archive root
with a stub upgrader that always returns a non-finalised result.
Captures the per-receipt UpgradeResult fields to JSON for the
driver's exit-code decision and for the outbox memo.
"""

import dataclasses
import json
import sys
from pathlib import Path

from wat.anchor import backfill as backfill_mod
from wat.anchor.ots_anchor import UpgradedReceipt


def _stub_upgrader(receipt_path):
    return UpgradedReceipt(
        merkle_root=b"\x00" * 32,
        receipt_path=Path(receipt_path),
        bitcoin_block_height=None,
        bitcoin_tx_id=None,
        upgraded_at="2026-05-26T17:00:00Z",
    )


def main():
    archive_root = Path(sys.argv[1])
    probe_out = Path(sys.argv[2])

    backfill_mod.upgrade_pending = _stub_upgrader
    results = backfill_mod.process_pending_queue(archive_root)

    payload = {
        "results": [
            {
                "receipt_path": str(r.receipt_path),
                "finalised": r.finalised,
                "bitcoin_block_height": r.bitcoin_block_height,
                "age_days": r.age_days,
                "soft_window_breached": r.soft_window_breached,
                "error": r.error,
            }
            for r in results
        ]
    }
    probe_out.write_text(json.dumps(payload, indent=2, sort_keys=True))

    breached = [r for r in results if r.soft_window_breached]
    print(f"[probe] receipts={len(results)} breached={len(breached)}")
    # Exit 0 = at least one breach detected (expected for aged receipt).
    # Exit 4 = no breach detected (bug or AGE_HOURS too low).
    sys.exit(0 if breached else 4)


if __name__ == "__main__":
    main()
PY
PROBE_RC=$?
set -e
log "probe_rc=${PROBE_RC} (0=alarm-flagged, 4=no-alarm/bug)"

if [[ "${PROBE_RC}" == "0" ]]; then
    mark_done probe
elif [[ "${PROBE_RC}" == "4" ]]; then
    log "ERROR: backfill probe did not flag soft-window breach"
    exit 4
else
    log "ERROR: backfill probe failed with rc=${PROBE_RC}"
    exit 2
fi

# ---------------------------------------------------------------------------
# 6. Optional live calendar stamp (off by default). Subject to the
#    UTC-day submit budget. This is only useful when the operator
#    wants a real receipt for cross-tool verify probes; the
#    behavioural contract under test does not require it.
# ---------------------------------------------------------------------------

STAMP_RC=""
if [[ "${LIVE_STAMP}" == "1" ]]; then
    if is_done stamp; then
        log "step 6/6: live stamp already done — skipping (resume)"
        STAMP_RC=0
    else
        TODAY="$(date -u '+%Y-%m-%d')"
        log "step 6/6: checking daily submit budget for ${TODAY}"
        mkdir -p "$(dirname "${BUDGET_FILE}")"
        python3 - "${BUDGET_FILE}" "${TODAY}" "${DAILY_BUDGET}" <<'PY'
import json
import sys
from pathlib import Path

budget_path = Path(sys.argv[1])
today = sys.argv[2]
limit = int(sys.argv[3])

if budget_path.exists():
    state = json.loads(budget_path.read_text())
else:
    state = {}

used = state.get(today, 0)
if used >= limit:
    print(f"[budget] {today}: used={used} limit={limit} — REFUSE", file=sys.stderr)
    sys.exit(6)
state[today] = used + 1
budget_path.write_text(json.dumps(state, indent=2, sort_keys=True))
print(f"[budget] {today}: used={used + 1}/{limit} — OK")
PY
        BUDGET_RC=$?
        if [[ "${BUDGET_RC}" == "6" ]]; then
            log "ERROR: daily submit budget exhausted; live stamp refused"
            exit 6
        fi

        # Defect-fix Tag-25 (2026-05-07): the synthetic marker from
        # step 3 lives at the same path that ``ots stamp`` would write
        # the real receipt to. Empirically (Tag-22 + Tag-24 audit-trail
        # checks) ``ots stamp`` does NOT overwrite an existing
        # ``root.bin.ots`` — the real receipt is silently dropped and
        # the audit-trail file remains the 25-byte synthetic marker.
        # We unlink the placeholder before stamping so the real OTS
        # receipt persists. ``root.bin`` (the binary Merkle root) is
        # left untouched: ``ots stamp`` re-reads it as input.
        log "step 6/6: removing synthetic marker before live stamp"
        rm -f "${RECEIPT_FILE}"

        log "step 6/6: stamping merkle_root via 4 default calendars"
        python3 -m wat.cmd.anchor_cli stamp "${ROOT_HEX}" \
            --out "${HOUR_DIR}" \
            --min-calendars 2

        # Sanity check: a real OTS pending receipt is at least ~700
        # bytes (TV-1/TV-2 production receipts measured 800-900 bytes
        # for 4-calendar submits; the floor is conservative). A file
        # smaller than that — or a still-present 25-byte synthetic
        # marker — means the receipt did not persist correctly.
        if [[ ! -f "${RECEIPT_FILE}" ]]; then
            log "ERROR: live stamp completed but no receipt at ${RECEIPT_FILE}"
            exit 7
        fi
        RECEIPT_SIZE="$(wc -c < "${RECEIPT_FILE}" | tr -d ' ')"
        if [[ "${RECEIPT_SIZE}" -lt 700 ]]; then
            log "ERROR: receipt at ${RECEIPT_FILE} is ${RECEIPT_SIZE} bytes (<700); persistence broken"
            exit 7
        fi
        log "step 6/6: receipt persisted (${RECEIPT_SIZE} bytes)"
        STAMP_RC=0
        mark_done stamp
    fi
fi

# ---------------------------------------------------------------------------
# 7. Single-line summary for the outbox memo.
# ---------------------------------------------------------------------------

SUMMARY="hour=${HOUR_SLOT} age_hours=${AGE_HOURS} probe_rc=${PROBE_RC} stamp_rc=${STAMP_RC:-skipped} archive=${ARCHIVE_ROOT} root=${ROOT_HEX}"
log "summary: ${SUMMARY}"
printf '%s\n' "${SUMMARY}" > "${SUMMARY_FILE}"

log "completed=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit 0
