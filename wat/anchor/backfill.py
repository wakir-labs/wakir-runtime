# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Backfill daemon for pending OTS receipts.

Walks a directory tree of pending OTS receipts and attempts to
upgrade each one to a finalised Bitcoin attestation. Pending receipts
older than a configurable soft window (default seven days, per
WAT-Phase-1a-Spec §3.4) are flagged for the audit alarm channel —
the daemon itself only surfaces the flag in its return value; the
hourly driver decides what to do with it.

Designed to run from a systemd timer (weekly) and from the per-hour
driver immediately after a fresh anchor (so a pending receipt that
happened to land just before a Bitcoin confirmation gets upgraded on
the next hour rather than waiting a week).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from pathlib import Path
from typing import List, Optional

from wat.anchor.ots_anchor import (
    AnchorError,
    UpgradedReceipt,
    upgrade_pending,
)

#: Default soft window before a pending receipt triggers the audit
#: alarm. WAT-Phase-1a-Spec §3.4: "If a pending receipt has not been
#: upgraded to a Bitcoin attestation within seven days, surface it
#: for human review."
DEFAULT_SOFT_WINDOW_DAYS: int = 7

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class UpgradeResult:
    """Outcome of attempting to upgrade a single pending receipt."""

    receipt_path: Path
    finalised: bool
    bitcoin_block_height: Optional[int]
    age_days: float
    soft_window_breached: bool
    error: Optional[str] = None


def _receipt_age_days(receipt_path: Path, *, now: Optional[dt.datetime] = None) -> float:
    """Return the age of ``receipt_path`` in days based on mtime."""
    now = now or dt.datetime.now(tz=dt.timezone.utc)
    mtime = dt.datetime.fromtimestamp(
        receipt_path.stat().st_mtime, tz=dt.timezone.utc
    )
    return (now - mtime).total_seconds() / 86400.0


def process_pending_queue(
    receipts_dir: str | Path,
    max_age_days: int = DEFAULT_SOFT_WINDOW_DAYS,
    *,
    now: Optional[dt.datetime] = None,
) -> List[UpgradeResult]:
    """Walk ``receipts_dir`` and upgrade each pending ``.ots`` receipt.

    Parameters
    ----------
    receipts_dir:
        Directory tree to walk (recursive). Any file ending in
        ``.ots`` is considered a candidate.
    max_age_days:
        Soft window in days; receipts older than this that are still
        pending are flagged via ``soft_window_breached=True``.

    Returns
    -------
    list of UpgradeResult
        One entry per receipt attempted, in deterministic
        sort-by-path order.
    """
    base = Path(receipts_dir)
    if not base.exists():
        logger.warning("backfill: receipts_dir %s does not exist", base)
        return []

    receipts = sorted(p for p in base.rglob("*.ots") if p.is_file())
    out: List[UpgradeResult] = []
    for receipt in receipts:
        age = _receipt_age_days(receipt, now=now)
        try:
            upgraded: UpgradedReceipt = upgrade_pending(receipt)
        except AnchorError as exc:
            logger.warning("backfill: upgrade failed for %s: %s", receipt, exc)
            out.append(
                UpgradeResult(
                    receipt_path=receipt,
                    finalised=False,
                    bitcoin_block_height=None,
                    age_days=age,
                    soft_window_breached=age > max_age_days,
                    error=str(exc),
                )
            )
            continue

        finalised = upgraded.is_finalised
        breached = (not finalised) and (age > max_age_days)
        if breached:
            logger.error(
                "backfill: receipt %s pending for %.1f days (soft window %d)",
                receipt,
                age,
                max_age_days,
            )
        out.append(
            UpgradeResult(
                receipt_path=receipt,
                finalised=finalised,
                bitcoin_block_height=upgraded.bitcoin_block_height,
                age_days=age,
                soft_window_breached=breached,
            )
        )
    return out


__all__ = [
    "DEFAULT_SOFT_WINDOW_DAYS",
    "UpgradeResult",
    "process_pending_queue",
]
