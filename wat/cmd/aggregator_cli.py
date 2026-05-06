# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Aggregator CLI skeleton.

Wire-frame for the hourly anchor flow. The eventual command will:

1. Read frame events from ``--input-file`` (one canonical JSON
   object per line).
2. Compute leaf hashes via :func:`wat.merkle.aggregator.compute_leaf_hash`.
3. Build the Merkle tree, write the receipt manifest to
   ``--output-receipt``.
4. Hand the root off to the OTS anchor pipeline (``wat.anchor``).

Phase 1a, day 2: argparse surface only. Body raises NotImplementedError
so callers wired against the CLI signature break loudly rather than
silently producing empty receipts. The body lands together with the
OTS anchor pipeline in day 3.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser.

    Exposed as a top-level helper so tests and the verify-CLI can
    introspect the option surface without invoking ``main``.
    """
    parser = argparse.ArgumentParser(
        prog="wat-aggregate",
        description=(
            "Aggregate Wirelang frame events into an hourly Merkle "
            "tree and emit a receipt manifest for OTS anchoring."
        ),
    )
    parser.add_argument(
        "--input-file",
        required=True,
        help="Path to a JSONL file with one canonical event per line.",
    )
    parser.add_argument(
        "--output-receipt",
        required=True,
        help=(
            "Path where the receipt manifest (JSON with root hash, "
            "leaf list, and proof index) will be written."
        ),
    )
    parser.add_argument(
        "--hour",
        default=None,
        help=(
            "Optional UTC hour label (YYYY-MM-DDTHH) used in receipt "
            "metadata. Defaults to the timestamp of the first event."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code (0 on success)."""
    parser = build_parser()
    parser.parse_args(argv)
    raise NotImplementedError(
        "Phase 1a, day 3+: aggregator wiring lands with the OTS anchor pipeline."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
