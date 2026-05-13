# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Console-script entry point for the Doppel-Audit-Trail bridge writer.

Usage:

.. code-block::

    wakir-bridge-audit-write \\
        --persona tomas \\
        --action pr-open \\
        --payload-file /tmp/event.json \\
        --spool-root /var/lib/wakir/spool \\
        --activity-log /var/home/fred/AI-Corp/activity-log.md \\
        [--ref "PR#42 wakir-runtime"] \\
        [--event-time 2026-05-13T08:30:00Z]

Behaviour
---------

- Reads the canonical payload from ``--payload-file`` (raw bytes),
  computes ``SHA-256`` over its contents, and forwards the hex digest
  as ``payload_hash``.
- Calls :func:`wat.anchor.bridge_audit_writer.write_bridge_audit` with
  the assembled arguments.
- Prints the resulting ``BridgeWriteResult`` as one JSON line on
  stdout (script-friendly for the pilot operator's grep loops).
- Exit code: ``0`` on ``status=ok``, ``1`` on any failure status.

The CLI is intentionally minimal — it is the operator-hand smoke-test
companion for the pilot phase, not the production hot-path. Production
producers (Phase-2) will call ``write_bridge_audit`` directly from the
Wirelang frame submitter.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from wat.anchor.bridge_audit_writer import write_bridge_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wakir-bridge-audit-write",
        description=(
            "Append one persona-activity event to both audit sinks "
            "(WAT spool + Pre-Framework activity-log.md) atomically."
        ),
    )
    parser.add_argument(
        "--persona",
        required=True,
        help="Persona slug (e.g. tomas, reza, mira).",
    )
    parser.add_argument(
        "--action",
        required=True,
        help="Action type (e.g. pr-open, adr-vote, hourly-tick).",
    )
    parser.add_argument(
        "--payload-file",
        required=True,
        type=Path,
        help="Path to the event payload file. SHA-256 is computed over its raw bytes.",
    )
    parser.add_argument(
        "--spool-root",
        required=True,
        type=Path,
        help="Root directory for per-persona WAT spool sub-directories.",
    )
    parser.add_argument(
        "--activity-log",
        required=True,
        type=Path,
        help="Path to the Pre-Framework activity-log.md file.",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Optional Bezug reference (e.g. 'PR#42 wakir-runtime').",
    )
    parser.add_argument(
        "--event-time",
        default=None,
        help="RFC-3339 UTC timestamp; defaults to current wall-clock UTC.",
    )
    return parser


def _result_to_dict(result) -> dict:
    """Render a BridgeWriteResult as a JSON-serialisable dict.

    Paths are coerced to strings; the dataclass-frozen ``Path`` fields
    do not serialise via the default ``json.dumps`` path.
    """
    raw = dataclasses.asdict(result)
    if raw.get("wat_spool_path") is not None:
        raw["wat_spool_path"] = str(raw["wat_spool_path"])
    raw["activity_log_path"] = str(raw["activity_log_path"])
    return raw


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    payload_bytes = args.payload_file.read_bytes()
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()

    metadata: dict = {}
    if args.ref:
        metadata["ref"] = args.ref

    result = write_bridge_audit(
        persona_id=args.persona,
        action_type=args.action,
        payload_hash=payload_hash,
        metadata=metadata,
        spool_root=args.spool_root,
        activity_log_path=args.activity_log,
        event_time=args.event_time,
    )

    sys.stdout.write(json.dumps(_result_to_dict(result), sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
