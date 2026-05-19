#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Strict-mode CAUTION -> BLOCK verdict upgrade for the Tag-55 AR-Hand
pre-cutover-final-sanity-gate trigger workflow.

Tag-55 (``.github/workflows/pre-cutover-final-sanity-gate-ar-trigger.yml``)
exposes the ``allow_caution`` workflow_dispatch input. When the AR-Hand
fires the gate with ``allow_caution=false``, a CAUTION verdict is
upgraded to BLOCK so the operator-hand can demand strict-green for
marathon-start.

The Tag-53 aggregator script writes the verdict envelope on disk; this
helper re-reads it, mutates the ``verdict`` field, and records two
audit fields:

  * ``ar_trigger_strict_mode``      - boolean flag set to ``True``.
  * ``ar_trigger_original_verdict`` - the pre-upgrade verdict
                                       (always ``"CAUTION"`` in
                                       practice; we record it
                                       verbatim for audit clarity).

Hermetic: stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def upgrade(input_path: Path) -> None:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    original = data.get("verdict", "UNKNOWN")
    data["verdict"] = "BLOCK"
    data["ar_trigger_strict_mode"] = True
    data["ar_trigger_original_verdict"] = original
    input_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Verdict-envelope JSON path to upgrade in-place.",
    )
    args = p.parse_args(argv[1:])
    if not args.input.is_file():
        print(f"verdict file not found: {args.input}", file=sys.stderr)
        return 2
    upgrade(args.input)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
