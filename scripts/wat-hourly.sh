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

# --- 3. Sealed-rename (Phase-1a-Tag-7 bridge contract).
#
# Per ``docs/wat-spool-spec.md`` §5 the bridge must seal the open
# hour-spool file before the aggregator reads it. Sealing is an
# atomic ``rename(2)`` from ``<hour>.jsonl`` to ``<hour>.jsonl.sealed``.
# This driver runs at H_end + 5min (the systemd timer schedule), so
# the late-frame window has elapsed by the time we reach this step.
SEALED_FILE="${SPOOL_FILE}.sealed"
log "[wat-bridge] checking spool=${SPOOL_FILE} sealed=${SEALED_FILE}"
if [[ -f "${SPOOL_FILE}" && ! -f "${SEALED_FILE}" ]]; then
    # Drive the seal via the in-tree helper. ``--enforce-window`` is
    # the default; the cron schedule already places us past H_end+5min,
    # so the helper accepts the seal cleanly.
    if ! python -m wat.ingestion.cli seal \
            --spool-dir "${EVENT_SPOOL}" \
            --hour "${HOUR_SLOT}"; then
        fail "[wat-bridge] sealed-rename failed for hour ${HOUR_SLOT}" 1
    fi
    log "[wat-bridge] sealed open spool -> ${SEALED_FILE}"
elif [[ -f "${SEALED_FILE}" ]]; then
    log "[wat-bridge] hour already sealed (idempotent fast path)"
fi

# --- 4. Empty-hour short-circuit.
#
# After sealing, the empty-hour case is "no .sealed file at all". We
# also tolerate a sealed file with zero lines (a producer flushed an
# empty hour as a heartbeat). Either way: nothing to anchor.
if [[ ! -s "${SEALED_FILE}" ]]; then
    log "spool ${SEALED_FILE} is empty or missing; nothing to anchor"
    log "status=skipped event_count=0 hour_slot=${HOUR_SLOT}"
    exit 0
fi

EVENT_COUNT="$(wc -l < "${SEALED_FILE}" | tr -d ' ')"
log "event_count=${EVENT_COUNT} spool=${SEALED_FILE}"

# --- 5. Build the hour manifest via wakir-merkle.
#
# Pre-build invariant: the input file must be a ``.sealed`` artefact.
# This is enforced by the if-test above plus the script's input-file
# argument pointing at ``${SEALED_FILE}`` rather than the open
# ``${SPOOL_FILE}``. Day-5 contract still applies: ``wakir-merkle
# build`` writes a manifest in the format documented under
# ``docs/wat-manifest-spec.md``. Empty hours produce a manifest with
# ``merkle_root: null`` and skip the anchor.
MANIFEST_FILE="${HOUR_ARCHIVE}/manifest.json"
if ! wakir-merkle build \
        --hour "${HOUR_SLOT}" \
        --input-events "${SEALED_FILE}" \
        --output-manifest "${MANIFEST_FILE}"; then
    fail "wakir-merkle build failed for hour ${HOUR_SLOT}" 1
fi

# Pull the root out of the manifest. ``python -c`` is acceptable
# here because the venv is always available next to the driver. The
# null literal is mapped to an empty string so the empty-hour branch
# below is a clean string comparison.
ROOT_HEX="$(python -c "import json; r=json.load(open('${MANIFEST_FILE}'))['merkle_root']; print('' if r is None else r)")"
if [[ -z "${ROOT_HEX}" ]]; then
    log "merkle_root=null event_count=0 — empty hour, skipping anchor"
    log "anchor_status=skipped hour_slot=${HOUR_SLOT}"
    log "archive=${HOUR_ARCHIVE}"
    exit 0
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
