# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Server-side verification CLI (skeleton).

This is the operator-facing convenience verifier that runs against
a local WAT manifest store. The public, offline brand-proof verifier
is shipped separately under `wakir_verify/` in Apache-2.0 form
(Phase 1a KW 23 deliverable).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def verify_event(event_id: str, manifest_dir: Path) -> bool:
    """Verify a single event by reconstructing its inclusion proof.

    Looks up the event in the per-hour manifest, recomputes the
    leaf hash, walks the inclusion path to the stored root, then
    verifies the OTS receipt against a Bitcoin block header.
    Returns True iff every step matches.
    """
    raise NotImplementedError("Phase 1a, day 4+: verification path pending")


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code (0 on success)."""
    raise NotImplementedError("Phase 1a, day 4+: argparse wiring pending")


if __name__ == "__main__":
    raise SystemExit(main())
