#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT hourly driver: aggregate the previous hour's events, build a
# Merkle tree, anchor the root via OpenTimestamps, archive both
# manifest and receipt under the per-hour directory.
#
# Triggered by the systemd timer ``wakir-wat-hourly.timer`` five
# minutes past every UTC hour boundary (WAT-Phase-1a-Spec §3.2:
# the five-minute slack lets late events from the closing hour
# settle into the spool before aggregation).
#
# Environment
# -----------
#
#   WAKIR_EVENT_SPOOL    directory where one ``<hour>.jsonl`` file
#                        per UTC hour accumulates events. The hour
#                        label is ``YYYY-MM-DDTHH``.
#   WAKIR_RECEIPT_ARCHIVE
#                        archive root. The driver writes
#                        ``<archive>/<hour>/manifest.json``,
#                        ``root.bin`` and ``root.bin.ots``.
#   WAKIR_MIN_CALENDARS  optional override for the OTS calendar
#                        threshold (default 2, per §3.3).
#   WAKIR_HOUR_OVERRIDE  optional ``YYYY-MM-DDTHH`` for backfill or
#                        replay; defaults to the previous UTC hour.
#
# Exit codes
# ----------
#
#   0   anchor completed (or hour was empty and nothing to anchor)
#   1   calendar threshold under-met — systemd's Restart=on-failure
#       picks the run up on the backfill timer
#   2   spool or archive misconfigured (operator error, no retry)

set -euo pipefail

log() {
    # systemd-journald collects stdout; tag every line so log greps
    # are unambiguous when this driver shares a journal with other
    # Wakir services.
    printf '[wat-hourly] %s\n' "$*"
}

fail() {
    printf '[wat-hourly] ERROR: %s\n' "$*" >&2
    exit "${2:-2}"
}

# --- 1. Environment.
EVENT_SPOOL="${WAKIR_EVENT_SPOOL:-}"
RECEIPT_ARCHIVE="${WAKIR_RECEIPT_ARCHIVE:-}"
MIN_CALENDARS="${WAKIR_MIN_CALENDARS:-2}"

[[ -n "${EVENT_SPOOL}" ]] || fail "WAKIR_EVENT_SPOOL is unset"
[[ -n "${RECEIPT_ARCHIVE}" ]] || fail "WAKIR_RECEIPT_ARCHIVE is unset"
[[ -d "${EVENT_SPOOL}" ]] || fail "WAKIR_EVENT_SPOOL ${EVENT_SPOOL} is not a directory"

mkdir -p "${RECEIPT_ARCHIVE}"

# --- 2. Resolve target hour.
if [[ -n "${WAKIR_HOUR_OVERRIDE:-}" ]]; then
    HOUR_SLOT="${WAKIR_HOUR_OVERRIDE}"
else
    # Previous UTC hour. ``date -u -d '1 hour ago'`` is the boring
    # GNU-coreutils-and-busybox-portable way to do this.
    HOUR_SLOT="$(date -u -d '1 hour ago' '+%Y-%m-%dT%H')"
fi
log "hour_slot=${HOUR_SLOT}"

SPOOL_FILE="${EVENT_SPOOL}/${HOUR_SLOT}.jsonl"
HOUR_ARCHIVE="${RECEIPT_ARCHIVE}/${HOUR_SLOT}"
mkdir -p "${HOUR_ARCHIVE}"

# --- 3. Empty-hour short-circuit.
if [[ ! -s "${SPOOL_FILE}" ]]; then
    log "spool ${SPOOL_FILE} is empty or missing; nothing to anchor"
    log "status=skipped event_count=0 hour_slot=${HOUR_SLOT}"
    exit 0
fi

EVENT_COUNT="$(wc -l < "${SPOOL_FILE}" | tr -d ' ')"
log "event_count=${EVENT_COUNT} spool=${SPOOL_FILE}"

# --- 4. Build the hour manifest via wakir-merkle.
#
# The aggregator CLI lands in full form on Phase-1a-Tag-5; today the
# driver invokes it with the contract that day-5 will satisfy. If
# the binary still raises NotImplementedError the run fails loudly
# rather than anchoring an empty root.
MANIFEST_FILE="${HOUR_ARCHIVE}/manifest.json"
if ! wakir-merkle \
        --input-file "${SPOOL_FILE}" \
        --output-receipt "${MANIFEST_FILE}" \
        --hour "${HOUR_SLOT}"; then
    fail "wakir-merkle failed for hour ${HOUR_SLOT}" 1
fi

# Pull the root out of the manifest. ``python -c`` is acceptable
# here because the venv is always available next to the driver.
ROOT_HEX="$(python -c "import json,sys; print(json.load(open('${MANIFEST_FILE}'))['merkle_root'])")"
if [[ -z "${ROOT_HEX}" ]]; then
    fail "manifest at ${MANIFEST_FILE} has empty merkle_root" 1
fi
log "merkle_root=${ROOT_HEX}"

# --- 5. Anchor the root via OpenTimestamps.
if ! wakir-anchor stamp "${ROOT_HEX}" \
        --out "${HOUR_ARCHIVE}" \
        --min-calendars "${MIN_CALENDARS}"; then
    log "anchor_status=failed hour_slot=${HOUR_SLOT}"
    fail "wakir-anchor stamp failed for hour ${HOUR_SLOT} (calendar threshold)" 1
fi

log "anchor_status=ok hour_slot=${HOUR_SLOT} event_count=${EVENT_COUNT}"
log "archive=${HOUR_ARCHIVE}"
exit 0
