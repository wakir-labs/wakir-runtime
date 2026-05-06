# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""OpenTimestamps anchor pipeline (skeleton).

Anchors hourly Merkle roots to Bitcoin via the OpenTimestamps free
public calendar servers (Alice, Bob, Finney, Catallaxy). Receipts
land in `meta/timestamps/wat/<YYYY-MM-DD>/<HH>.ots` next to a
`.root` and `.manifest.json` file that allow inclusion-proof
reconstruction without a Wakir-side database.

Phase 1a, day 1: signature scaffolding only. The hourly cron job and
the systemd timer that drives it land in `scripts/` in a later day.
"""

from __future__ import annotations

from pathlib import Path


def anchor_root(root: bytes, hour_dir: Path) -> Path:
    """Submit a Merkle root to OTS calendars and write the receipt.

    Writes a pending OTS receipt (`<HH>.ots`) into the per-hour
    directory and returns its path. The receipt is upgraded to a
    full Bitcoin attestation later by `upgrade_pending`.
    """
    raise NotImplementedError("Phase 1a, day 3+: OTS submission wiring pending")


def upgrade_pending(stamps_root: Path) -> int:
    """Walk pending OTS receipts and upgrade them to Bitcoin attestation.

    Mirrors the existing `scripts/ots-upgrade-weekly.sh` pattern from
    the parent corp repo, scoped to `meta/timestamps/wat/` here.
    Returns the number of receipts that were upgraded.
    """
    raise NotImplementedError("Phase 1a, day 3+: upgrade walker pending")
