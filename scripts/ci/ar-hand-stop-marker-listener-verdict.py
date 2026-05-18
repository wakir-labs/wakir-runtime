#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""AR-Hand-Stop-Marker Listener — Verdict-Emit-Step.

Emits the ``ar-hand-stop-listener-verdict.json`` artifact that the
upload-artifact step uploads. The verdict file captures every
piece of information the listener observed in this run so that
post-mortem analysis (Henrik Internal-Audit) can reconstruct the
reaction chain.

Schema
------

```
{
  "schema_version": "1",
  "listener_run_ts": "<utc-RFC3339>",
  "marker": {
    "welle": int,
    "trigger": "<string>",
    "ts": "<utc-RFC3339>",
    "operator": "<string>",
    "filename": "<repo-relative-path>"
  },
  "cancel_plan": {
    "welle_targets": [<filenames>],
    "cascade_targets": [<filenames>],
    "marathon_targets": [<filenames>],
    "cascade_blocked_welle": [<int>]
  },
  "dry_run": bool
}
```

Sandbox-Boundary
----------------

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone


SCHEMA_VERSION = "1"


def build_verdict(
    *,
    welle: int,
    trigger: str,
    marker_ts: str,
    operator: str,
    marker_filename: str,
    welle_targets: list[str],
    cascade_targets: list[str],
    marathon_targets: list[str],
    cascade_blocked_welle: list[int],
    dry_run: bool,
    listener_run_ts: datetime | None = None,
) -> dict[str, object]:
    """Compose the verdict payload (pure function, fully testable)."""

    run_ts = listener_run_ts or datetime.now(tz=timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "listener_run_ts": run_ts.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "marker": {
            "welle": welle,
            "trigger": trigger,
            "ts": marker_ts,
            "operator": operator,
            "filename": marker_filename,
        },
        "cancel_plan": {
            "welle_targets": list(welle_targets),
            "cascade_targets": list(cascade_targets),
            "marathon_targets": list(marathon_targets),
            "cascade_blocked_welle": list(cascade_blocked_welle),
        },
        "dry_run": bool(dry_run),
    }


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _decode_string_list(raw: str) -> list[str]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"value must be JSON-encoded list: {raw!r} ({exc})")
    if not isinstance(decoded, list):
        raise ValueError(f"value must be a JSON list: {raw!r}")
    return [str(item) for item in decoded]


def _decode_int_list(raw: str) -> list[int]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"value must be JSON-encoded list: {raw!r} ({exc})")
    if not isinstance(decoded, list):
        raise ValueError(f"value must be a JSON list: {raw!r}")
    return [int(item) for item in decoded]


def _parse_dry_run(raw: str) -> bool:
    return raw.strip().lower() == "true"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ar-hand-stop-marker-listener-verdict")
    p.add_argument("--welle", required=True, type=int)
    p.add_argument("--trigger", required=True)
    p.add_argument("--marker-ts", required=True)
    p.add_argument("--operator", required=True)
    p.add_argument("--marker-filename", required=True)
    p.add_argument("--welle-targets", required=True)
    p.add_argument("--cascade-targets", required=True)
    p.add_argument("--marathon-targets", required=True)
    p.add_argument("--cascade-blocked-welle", required=True)
    p.add_argument("--dry-run", default="false")
    p.add_argument("--out", required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        verdict = build_verdict(
            welle=args.welle,
            trigger=args.trigger,
            marker_ts=args.marker_ts,
            operator=args.operator,
            marker_filename=args.marker_filename,
            welle_targets=_decode_string_list(args.welle_targets),
            cascade_targets=_decode_string_list(args.cascade_targets),
            marathon_targets=_decode_string_list(args.marathon_targets),
            cascade_blocked_welle=_decode_int_list(args.cascade_blocked_welle),
            dry_run=_parse_dry_run(args.dry_run),
        )
    except ValueError as exc:
        print(f"ERROR: verdict build failed: {exc}", file=sys.stderr)
        return 2

    out_path = pathlib.Path(args.out)
    out_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"verdict written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
