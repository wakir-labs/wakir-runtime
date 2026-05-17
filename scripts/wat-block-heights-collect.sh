#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT block-heights collection driver.
#
# Walks a directory tree of OTS receipts, attempts ``ots upgrade`` on
# each one, parses ``ots info`` output for Bitcoin block heights, and
# writes a balance report (counts pending vs finalised, lists block
# heights per calendar). Designed for two roles:
#
#   1. After a Tag-22-style smoke run, populate the audit log with
#      the actual Bitcoin block heights that anchor the hour.
#   2. As an operator one-shot during incident response, when the
#      backfill timer is paused and a human wants to see which
#      receipts have made it onto the chain.
#
# The script never re-submits to a calendar — only ``upgrade`` calls.
# That keeps it polite against the public OTS infrastructure (the
# backfill daemon does the same; this script is a manual mirror with
# nicer reporting).
#
# Usage
# -----
#
#   bash scripts/wat-block-heights-collect.sh [archive-dir] [report-path]
#
# Defaults
# --------
#
#   archive-dir  WAKIR_RECEIPT_ARCHIVE if set, else
#                ./meta/timestamps/wat
#   report-path  ./meta/timestamps/wat/_reports/block-heights-<utc>.md
#
# Exit codes
# ----------
#
#   0  walk completed (some receipts may still be pending; that's fine)
#   1  no receipts found under the archive root
#   2  archive misconfigured (missing directory)
#   3  ``ots`` binary not on PATH

set -euo pipefail

log() { printf '[wat-block-heights] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Argument and environment handling
# ---------------------------------------------------------------------------

ARCHIVE_DIR="${1:-${WAKIR_RECEIPT_ARCHIVE:-./meta/timestamps/wat}}"
TS_UTC="$(date -u '+%Y%m%dT%H%M%SZ')"
DEFAULT_REPORT="${ARCHIVE_DIR}/_reports/block-heights-${TS_UTC}.md"
REPORT_PATH="${2:-${DEFAULT_REPORT}}"

if [[ ! -d "${ARCHIVE_DIR}" ]]; then
    printf '[wat-block-heights] ERROR: archive %s does not exist\n' \
        "${ARCHIVE_DIR}" >&2
    exit 2
fi

if ! command -v ots >/dev/null 2>&1; then
    printf '[wat-block-heights] ERROR: ots CLI not on PATH\n' >&2
    exit 3
fi

mkdir -p "$(dirname "${REPORT_PATH}")"

log "archive=${ARCHIVE_DIR}"
log "report=${REPORT_PATH}"

# ---------------------------------------------------------------------------
# Walk and upgrade
# ---------------------------------------------------------------------------

# Gather all .ots receipts. ``-print0`` + ``read -d ''`` keeps paths
# with spaces working, which is unlikely in production but harmless.
RECEIPTS=()
while IFS= read -r -d '' receipt; do
    RECEIPTS+=("${receipt}")
done < <(find "${ARCHIVE_DIR}" -type f -name '*.ots' -print0 | sort -z)

if [[ "${#RECEIPTS[@]}" -eq 0 ]]; then
    log "no .ots receipts found under ${ARCHIVE_DIR}"
    exit 1
fi

log "found ${#RECEIPTS[@]} receipt(s); running ots upgrade on each"

declare -i FINALISED=0
declare -i PENDING=0
declare -a REPORT_ROWS=()

for receipt in "${RECEIPTS[@]}"; do
    # Upgrade is idempotent. Failures here usually mean a transient
    # calendar timeout, not a corruption — log and move on.
    if ! ots upgrade "${receipt}" >/dev/null 2>&1; then
        log "warn: ots upgrade non-zero for ${receipt} (continuing)"
    fi

    # Parse ots info for block heights and pending markers per calendar.
    #
    # NOTE on pipefail (Tag-14 fix): with ``set -euo pipefail`` an empty
    # ``grep`` (no matches) returns exit 1 inside a ``$(...)`` substitution
    # and kills the whole script before the report block ever runs. That
    # is exactly the pending-receipt path. We therefore wrap each pipeline
    # in ``|| true`` so a no-match grep yields an empty string and the
    # script continues to the report. The trailing ``|| true`` after
    # ``paste`` is technically redundant once the inner grep is permitted
    # to return non-zero, but kept for paranoia.
    INFO_BLOB="$(ots info "${receipt}" 2>&1 || true)"
    HEIGHTS="$( { printf '%s\n' "${INFO_BLOB}" \
        | grep -E 'BitcoinBlockHeaderAttestation\([0-9]+\)' || true; } \
        | sed -E 's/.*BitcoinBlockHeaderAttestation\(([0-9]+)\).*/\1/' \
        | sort -un | paste -sd, - )"
    PENDING_CALS="$( { printf '%s\n' "${INFO_BLOB}" \
        | grep -E 'PendingAttestation' || true; } \
        | sed -E "s/.*PendingAttestation\('([^']+)'\).*/\1/" \
        | sort -u | paste -sd, - )"

    REL="${receipt#${ARCHIVE_DIR}/}"
    # In a finalised receipt the original ``PendingAttestation`` lines
    # are kept inside the proof tree (every calendar branch has a
    # ``verify PendingAttestation`` followed by a
    # ``verify BitcoinBlockHeaderAttestation``). We therefore only
    # surface pending-calendar names when the receipt has NO bitcoin
    # heights — otherwise every finalised receipt would falsely look
    # like it still has pending calendars.
    if [[ -n "${HEIGHTS}" ]]; then
        FINALISED+=1
        REPORT_ROWS+=("| ${REL} | finalised | ${HEIGHTS} | (n/a) |")
        log "finalised ${REL} heights=${HEIGHTS}"
    else
        PENDING+=1
        REPORT_ROWS+=("| ${REL} | pending | (none) | ${PENDING_CALS:-(unknown)} |")
        log "pending   ${REL}"
    fi
done

# ---------------------------------------------------------------------------
# Write report
# ---------------------------------------------------------------------------

{
    # ``awk`` is used throughout to dodge ``printf``'s leading-dash
    # flag parsing — rows like ``--> `` and the table separator ``|---``
    # otherwise look like printf options.
    awk 'BEGIN { print "<!--" }'
    # REUSE-IgnoreStart
    awk 'BEGIN { print "SPDX-License-Identifier: CC-BY-4.0" }'
    awk 'BEGIN { print "SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors" }'
    # REUSE-IgnoreEnd
    awk 'BEGIN { print "-->" ; print "" }'
    awk 'BEGIN { print "# WAT block-heights report" ; print "" }'
    awk -v t="${TS_UTC}" 'BEGIN { printf "Generated: %s\n", t }'
    awk -v a="${ARCHIVE_DIR}" 'BEGIN { printf "Archive: `%s`\n", a }'
    awk -v n="${#RECEIPTS[@]}" -v f="${FINALISED}" -v p="${PENDING}" \
        'BEGIN { printf "Receipts walked: %d (finalised %d, still pending %d)\n\n", n, f, p }'
    awk 'BEGIN { print "| receipt | status | bitcoin block height(s) | pending calendar(s) |" }'
    awk 'BEGIN { print "|---------|--------|--------------------------|---------------------|" }'
    for row in "${REPORT_ROWS[@]}"; do
        awk -v r="${row}" 'BEGIN { print r }'
    done
} > "${REPORT_PATH}"

log "report written: ${REPORT_PATH}"
log "summary: receipts=${#RECEIPTS[@]} finalised=${FINALISED} pending=${PENDING}"
exit 0
