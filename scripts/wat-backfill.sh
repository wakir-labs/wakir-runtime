#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# WAT backfill driver: walk the receipt archive, attempt to upgrade
# every pending OTS receipt to a Bitcoin attestation, and surface
# anything that has aged past the soft window
# (WAT-Phase-1a-Spec §3.4, default 7 days) for human review.
#
# Triggered by ``wakir-wat-backfill.timer`` four times a day.
#
# Environment
# -----------
#
#   WAKIR_RECEIPT_ARCHIVE   archive root the hourly driver writes to
#   WAKIR_BACKFILL_MAX_AGE  optional override in days (default 7)
#
# Exit codes
# ----------
#
#   0   no soft-window breach this pass
#   1   at least one receipt has aged past the soft window — the
#       audit alarm channel should pick this up via journal grep
#   2   archive misconfigured

set -euo pipefail

log() { printf '[wat-backfill] %s\n' "$*"; }

[[ -n "${WAKIR_RECEIPT_ARCHIVE:-}" ]] \
    || { echo "[wat-backfill] ERROR: WAKIR_RECEIPT_ARCHIVE is unset" >&2; exit 2; }
[[ -d "${WAKIR_RECEIPT_ARCHIVE}" ]] \
    || { echo "[wat-backfill] ERROR: ${WAKIR_RECEIPT_ARCHIVE} is not a directory" >&2; exit 2; }

MAX_AGE="${WAKIR_BACKFILL_MAX_AGE:-7}"
log "archive=${WAKIR_RECEIPT_ARCHIVE} max_age_days=${MAX_AGE}"

python - "${WAKIR_RECEIPT_ARCHIVE}" "${MAX_AGE}" <<'PY'
import sys
from wat.anchor.backfill import process_pending_queue

archive, max_age = sys.argv[1], int(sys.argv[2])
results = process_pending_queue(archive, max_age_days=max_age)

breached = 0
for r in results:
    print(
        f"receipt={r.receipt_path} "
        f"finalised={r.finalised} "
        f"block={r.bitcoin_block_height} "
        f"age_days={r.age_days:.1f} "
        f"breached={r.soft_window_breached}"
    )
    if r.soft_window_breached:
        breached += 1

print(f"summary processed={len(results)} breached={breached}")
sys.exit(1 if breached else 0)
PY
