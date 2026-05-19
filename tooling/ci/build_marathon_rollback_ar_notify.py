#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Build the AR-Hand ntfy notify-payload for the Phase-3-Marathon-
Rollback workflow (Tag-56).

The J11 job in ``phase-3-marathon-rollback.yml`` calls this helper
to write a ntfy-shaped JSON envelope. The workflow itself does NOT
POST to ntfy.sh by design — the operator-hand curl-POSTs the
artifact to ``ntfy.sh/wakir-ar-hand``. Separation of concerns:
CI prepares the payload deterministically, operator fires the
notification when ratifying the rollback.

ntfy.sh accepts a JSON POST with these top-level fields (per
ntfy.sh/docs/publish/#publish-as-json):

  * topic   — required; the channel name
  * title   — short headline
  * message — body text
  * priority — 1..5 (5 = max)
  * tags    — list of strings

We add a non-standard top-level ``manifest_summary`` field carrying
the structured rollback-run data. ntfy.sh ignores unknown top-level
fields, so the payload stays valid for direct POST.

Priority mapping
----------------

* READY   -> priority 3 (default), tag "white_check_mark"
* PARTIAL -> priority 4, tag "warning"
* FAILED  -> priority 5 (max), tag "rotating_light"

Hermetic
--------

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOPIC = "wakir-ar-hand"

VALID_VERDICTS = ("READY", "PARTIAL", "FAILED")

PRIORITY_MAP = {
    "READY": 3,
    "PARTIAL": 4,
    "FAILED": 5,
}

TAG_MAP = {
    "READY": ["white_check_mark", "marathon-rollback"],
    "PARTIAL": ["warning", "marathon-rollback"],
    "FAILED": ["rotating_light", "marathon-rollback"],
}


def build_payload(
    cycle_id: str,
    actor: str,
    reason: str,
    verdict: str,
    mode: str,
    manifest: dict,
) -> dict:
    if verdict not in VALID_VERDICTS:
        # Unknown verdict treated as FAILED for notification-priority
        # purposes — better to wake the AR than silently miss the
        # failure mode.
        verdict = "FAILED"
    priority = PRIORITY_MAP[verdict]
    tags = TAG_MAP[verdict]
    counts = manifest.get("counts", {})
    snapshot_restore = manifest.get("snapshot_restore_status", "n/a")
    title = f"Marathon-Rollback {verdict} ({mode})"
    message_lines = [
        f"Cycle: {cycle_id}",
        f"Actor: {actor}",
        f"Reason: {reason}",
        f"Mode: {mode}",
        (
            f"Counts: green={counts.get('green', 0)} "
            f"yellow={counts.get('yellow', 0)} "
            f"red={counts.get('red', 0)} "
            f"skipped={counts.get('skipped', 0)}"
        ),
        f"Snapshot-restore: {snapshot_restore}",
    ]
    return {
        "schema_version": 1,
        "kind": "marathon-rollback-ar-hand-notify-payload",
        "topic": TOPIC,
        "title": title,
        "message": "\n".join(message_lines),
        "priority": priority,
        "tags": tags,
        "manifest_summary": {
            "rollback_cycle_id": cycle_id,
            "verdict": verdict,
            "actor": actor,
            "reason": reason,
            "mode": mode,
            "welle_results": manifest.get("welle_results", {}),
            "counts": counts,
            "snapshot_restore_status": snapshot_restore,
        },
        "operator_curl_hint": (
            f"curl -fsSL -X POST -H 'Content-Type: application/json' "
            f"-d @ar-hand-notify-payload.json https://ntfy.sh"
        ),
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cycle-id", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--verdict", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv[1:])

    if not args.manifest.is_file():
        # Manifest not present: emit a degraded-mode payload so the
        # AR still wakes up; this is the "the aggregator itself
        # broke" failure mode.
        manifest_data: dict = {
            "counts": {"green": 0, "yellow": 0, "red": 0, "skipped": 7},
            "welle_results": {},
            "snapshot_restore_status": "n/a",
            "note": f"manifest file not present at {args.manifest}",
        }
        verdict = "FAILED"
    else:
        manifest_data = json.loads(args.manifest.read_text(encoding="utf-8"))
        verdict = args.verdict or manifest_data.get("verdict", "FAILED")

    payload = build_payload(
        cycle_id=args.cycle_id,
        actor=args.actor,
        reason=args.reason,
        verdict=verdict,
        mode=args.mode,
        manifest=manifest_data,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
