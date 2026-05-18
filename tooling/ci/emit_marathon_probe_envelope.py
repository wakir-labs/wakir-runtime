#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit a per-Welle probe envelope for the marathon-dashboard.

Called once per matrix-leg of
``phase-3c-pre-cutover-marathon-dashboard.yml`` to write a small JSON
envelope that the marathon-aggregator picks up. Keeping the emitter
separate from the workflow YAML avoids nested heredocs and makes the
envelope schema testable in hermetic isolation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


VALID_VERDICTS = ("GREEN", "CAUTION", "BLOCK", "NOT-EXEC")


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "yes", "on")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Emit a per-Welle marathon-probe envelope."
    )
    p.add_argument("--welle", type=int, required=True, choices=range(1, 8))
    p.add_argument("--component", required=True)
    p.add_argument("--probe-script", required=True)
    p.add_argument(
        "--probe-present",
        required=True,
        help="One of true|false.",
    )
    p.add_argument(
        "--exit-code",
        type=int,
        default=None,
        help="Probe exit code (omit when probe-present=false).",
    )
    p.add_argument("--verdict", required=True, choices=VALID_VERDICTS)
    p.add_argument("--verdict-source", required=True)
    p.add_argument("--details", default="")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv[1:])

    envelope = {
        "schema_version": 1,
        "welle": args.welle,
        "component": args.component,
        "probe_script": args.probe_script,
        "probe_present": _parse_bool(args.probe_present),
        "exit_code": args.exit_code,
        "verdict": args.verdict,
        "verdict_source": args.verdict_source,
        "details": args.details,
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
