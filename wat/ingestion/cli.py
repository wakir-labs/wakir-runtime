# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Ingestion CLI helpers: invoked from ``scripts/wat-hourly.sh``.

Exposes a tiny argparse surface so the bash driver can call the
sealing helper without parsing Python ``__main__`` shims by hand.
A separate ``wakir-merkle build`` console script remains the
production data-path; this CLI is for pipeline orchestration only.

Subcommands
-----------

``seal``
    Seal a single hour-slot file (``<hour>.jsonl`` ->
    ``<hour>.jsonl.sealed``) per ``docs/wat-spool-spec.md`` §5. Used
    by the hourly cron at H_end + 5min.

``seal-due``
    Seal every hour whose late-frame window has elapsed. Useful for
    backfill / catch-up runs after a writer outage.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Optional, Sequence

from wat.ingestion.spool_writer import seal_due_hours, seal_hour


def _parse_now(value: Optional[str]) -> Optional[dt.datetime]:
    """Parse an optional override timestamp (RFC 3339, UTC)."""
    if value is None:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        raise ValueError(f"--now {value!r} requires a timezone (use Z)")
    return parsed.astimezone(dt.timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wakir-wat-ingestion",
        description="Hour-spool sealing helpers for the WAT bridge.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seal = sub.add_parser("seal", help="Seal a single hour-slot file.")
    p_seal.add_argument(
        "--spool-dir",
        required=True,
        help="Directory holding the open ``*.jsonl`` files.",
    )
    p_seal.add_argument(
        "--hour",
        required=True,
        help="Hour slot to seal, format ``YYYY-MM-DDTHH``.",
    )
    p_seal.add_argument(
        "--no-window",
        action="store_true",
        help=(
            "Skip the H_end+5min window check. Use only for backfill "
            "or replay; production cron must respect the window."
        ),
    )
    p_seal.add_argument(
        "--now",
        default=None,
        help="Override current UTC time for the window check (testing).",
    )

    p_due = sub.add_parser(
        "seal-due", help="Seal every hour past its late-frame window."
    )
    p_due.add_argument(
        "--spool-dir",
        required=True,
        help="Directory holding the open ``*.jsonl`` files.",
    )
    p_due.add_argument(
        "--now",
        default=None,
        help="Override current UTC time (testing).",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    now = _parse_now(args.now)

    if args.cmd == "seal":
        try:
            result = seal_hour(
                Path(args.spool_dir),
                args.hour,
                now=now,
                enforce_window=not args.no_window,
            )
        except RuntimeError as exc:
            print(f"seal error: {exc}", file=sys.stderr)
            return 2
        if result is None:
            print(f"seal: nothing to do for hour {args.hour} (empty hour)")
        else:
            print(f"seal: ok {result}")
        return 0

    if args.cmd == "seal-due":
        sealed = seal_due_hours(Path(args.spool_dir), now=now)
        for path in sealed:
            print(f"seal-due: {path}")
        if not sealed:
            print("seal-due: no eligible hours")
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
