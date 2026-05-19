#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit an OTS-anchor stub marker for a persona-engine manifest hash.

Tag-57 OPEN-K2 closeout (from Selin's Tag-56 0.5.2-final audit, PR #362):

  > OPEN-K2: OTS-anchor of manifest hash via WAT spool (Tomás Zone-K)

This helper is the **audit-only stub** for the future OTS-anchor wiring
of persona-engine manifest hashes via the WAT spool. It computes the
SHA-256 of a manifest file (e.g. ``MANIFEST-0.5.2-final-pre-cutover.md``),
records the intent-to-anchor in a marker JSON file under
``tooling/ots/markers/``, and emits a WAT-spool envelope describing the
anchor request.

**Audit-only.** This helper does NOT call out to an OpenTimestamps
calendar server. The Sandbox-boundary is explicitly preserved:

  * No network I/O.
  * No subprocess calls to ``ots`` CLI.
  * No filesystem writes outside the marker output directory.

The Operator-Hand picks up the marker file in a later runbook step
and runs the real ``ots stamp`` invocation on a host that has network
access to the OTS calendar. The marker file then gets the real
``.ots`` proof attached (out-of-band, Phase-3c-Schritt-N+1).

Schema (v1) — JSON marker emitted to ``--marker-out``
-----------------------------------------------------

  {
    "schema_version": 1,
    "kind": "manifest-hash-ots-anchor-marker",
    "mode": "audit-only",
    "manifest_path": "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
    "manifest_sha256": "<64-hex>",
    "manifest_size_bytes": 12345,
    "wat_spool_envelope": {
      "schema_version": 1,
      "kind": "ots-anchor-request",
      "manifest_sha256": "<64-hex>",
      "requested_at_utc": "2026-05-19T...",
      "actor": "<github.actor|local>",
      "anchor_target": "opentimestamps-calendar"
    },
    "emitted_at_utc": "2026-05-19T...",
    "anchors": {
      "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
      "selin_tag_56_audit": "decisions/0062-..."
    },
    "operator_hand_next_step": (
      "Run `ots stamp <marker_out>` on a network-attached host; "
      "attach resulting .ots proof to this marker out-of-band."
    )
  }

Exit codes
----------

  * 0 — marker emitted successfully.
  * 1 — manifest file not found / unreadable.
  * 2 — usage error.

Hermetic
--------

stdlib only. ``argparse``, ``hashlib``, ``json``, ``pathlib``,
``datetime``, ``os``, ``sys``. No third-party imports. No network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable


MODE_AUDIT_ONLY: str = "audit-only"
ANCHOR_TARGET_OTS_CALENDAR: str = "opentimestamps-calendar"


def compute_sha256(path: Path) -> tuple[str, int]:
    """Return (hex-digest, byte-size) for the file at ``path``.

    Streams the file in 64 KiB chunks to keep memory flat.
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def build_marker(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    manifest_size_bytes: int,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Assemble the marker dict for the given manifest hash."""
    rel_manifest = (
        str(manifest_path.relative_to(repo_root))
        if manifest_path.is_absolute() and repo_root in manifest_path.parents
        else str(manifest_path)
    )
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": "manifest-hash-ots-anchor-marker",
        "mode": MODE_AUDIT_ONLY,
        "manifest_path": rel_manifest,
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": "ots-anchor-request",
            "manifest_sha256": manifest_sha256,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "selin_tag_56_audit": (
                "tag-56 PR #362 OPEN-K2 (persona-engine 0.5.2-final "
                "production-readiness audit)"
            ),
        },
        "operator_hand_next_step": (
            "Run `ots stamp <marker_out>` on a network-attached host; "
            "attach resulting .ots proof to this marker out-of-band."
        ),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emit_manifest_hash_ots_marker",
        description=(
            "Emit an audit-only OTS-anchor marker for a persona-engine "
            "manifest hash (Tag-57 OPEN-K2, audit-only mode)."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the manifest file to hash.",
    )
    parser.add_argument(
        "--marker-out",
        type=Path,
        required=True,
        help="Output JSON marker path (parent dir will be mkdir -p'd).",
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("GITHUB_ACTOR", "local"),
        help="Actor identifier (default: $GITHUB_ACTOR or 'local').",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Override emitted_at_utc / requested_at_utc (ISO-8601). "
            "Useful for deterministic tests."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.manifest.is_file():
        print(
            f"emit_manifest_hash_ots_marker: --manifest not a file: "
            f"{args.manifest}",
            file=sys.stderr,
        )
        return 1

    try:
        sha256_hex, size_bytes = compute_sha256(args.manifest)
    except OSError as exc:
        print(
            f"emit_manifest_hash_ots_marker: read failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if args.now is None:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
    else:
        # ``fromisoformat`` accepts ``+00:00`` and naive forms; we
        # coerce naive to UTC.
        now_utc = _dt.datetime.fromisoformat(args.now)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)

    marker = build_marker(
        manifest_path=args.manifest,
        manifest_sha256=sha256_hex,
        manifest_size_bytes=size_bytes,
        actor=args.actor,
        now_utc=now_utc,
        repo_root=args.repo_root,
    )

    args.marker_out.parent.mkdir(parents=True, exist_ok=True)
    args.marker_out.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
        f"sha256={sha256_hex} size={size_bytes} -> {args.marker_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
