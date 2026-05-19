#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Verify every Containerfile FROM line carries an ``@sha256:<hex>`` digest pin.

Tag-57 OPEN-K1 closeout (from Selin's Tag-56 0.5.2-final audit, PR #362):

  > OPEN-K1: Containerfile base-image SHA digest (Tomás Zone-K)

The audit found that several runtime Containerfiles still carry
``DIGEST_PENDING_*_REVIEW`` placeholders in their FROM lines. Those
placeholders are themselves a deliberate marker that the structural
pin-pattern is in place even when the live-digest has not yet been
resolved by ``resolve-image-pins-ci``. The risk OPEN-K1 closes is
**digest-less FROM regressions** — somebody removes the ``@sha256:...``
suffix entirely and the image-build silently pins to ``:tag``-mutable
upstream.

This helper enforces the structural invariant as a Repo-Gate:

  * Every ``FROM`` line in ``infra/**/Containerfile*`` MUST have the
    ``image@sha256:<64-hex|placeholder-token>`` shape.
  * Allowed placeholder tokens are explicitly listed (DIGEST_PENDING_*
    family) so that the Welle-N rotation pattern keeps working.
  * Any FROM line with ``:tag`` only (no ``@sha256:...``) fails the
    gate.
  * Multi-stage builds (``FROM ... AS builder``) are handled.
  * ``FROM scratch`` is the only digest-exempt token.

Schema (v1) — JSON report emitted to ``--report``
-------------------------------------------------

  {
    "schema_version": 1,
    "kind": "containerfile-base-image-digest-pin-report",
    "scanned_at_utc": "2026-05-19T...",
    "containerfile_count": 11,
    "from_line_count": 17,
    "violations": [
      {
        "path": "infra/foo/Containerfile",
        "line_no": 42,
        "line": "FROM docker.io/library/python:3.13-slim",
        "reason": "missing-digest"
      }
    ],
    "placeholders": [
      {
        "path": "infra/persona-engine/Containerfile.real",
        "line_no": 145,
        "token": "DIGEST_PENDING_TOMAS_REVIEW"
      }
    ],
    "verdict": "PASS" | "FAIL"
  }

Exit codes
----------

  * 0 — no violations (placeholders allowed, reported as info).
  * 1 — at least one digest-less FROM found.
  * 2 — usage / IO error.

Hermetic
--------

stdlib only. ``argparse``, ``json``, ``pathlib``, ``re``, ``sys``,
``datetime``. No third-party imports. No network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Iterable


# Allowed placeholder tokens — Welle-rotation pattern keeps these around
# until ``resolve-image-pins-ci`` replaces them with live digests.
ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "DIGEST_PENDING_TOMAS_REVIEW",
        "DIGEST_PENDING_KAI_REVIEW",
        "DIGEST_PENDING_SELIN_REVIEW",
        "DIGEST_PENDING_NOA_REVIEW",
        "DIGEST_PENDING_REZA_REVIEW",
    }
)

# FROM line shape — three legal patterns:
#   1. ``FROM scratch`` (no digest required)
#   2. ``FROM <image>@sha256:<64-hex>`` (real digest pin)
#   3. ``FROM <image>@sha256:<allowed-placeholder-token>`` (Welle-rotation)
# Optional ``:tag`` between image and ``@sha256`` is allowed.
# Optional ``AS <stage>`` suffix for multi-stage builds is allowed.

_FROM_RE = re.compile(r"^\s*FROM\s+(?P<rest>.+?)\s*$", re.IGNORECASE)
_SCRATCH_RE = re.compile(r"^scratch(\s+AS\s+\S+)?\s*$", re.IGNORECASE)
_DIGEST_RE = re.compile(
    r"^(?P<image>[^@\s]+)"
    r"@sha256:(?P<digest>[A-Za-z0-9_]+)"
    r"(\s+AS\s+\S+)?\s*$"
)
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def find_containerfiles(repo_root: Path) -> list[Path]:
    """Return all Containerfile* paths under ``infra/`` (recursive)."""
    infra = repo_root / "infra"
    if not infra.exists():
        return []
    return sorted(p for p in infra.rglob("Containerfile*") if p.is_file())


def scan_containerfile(path: Path) -> tuple[list[dict], list[dict], int]:
    """Scan one Containerfile.

    Returns ``(violations, placeholders, from_line_count)``.
    """
    violations: list[dict] = []
    placeholders: list[dict] = []
    from_line_count = 0

    text = path.read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        # Skip comment lines (a ``#``-prefixed line that contains
        # ``FROM`` is documentation, not a real build instruction).
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        m = _FROM_RE.match(raw)
        if not m:
            continue
        from_line_count += 1
        rest = m.group("rest")

        if _SCRATCH_RE.match(rest):
            continue

        dm = _DIGEST_RE.match(rest)
        if not dm:
            violations.append(
                {
                    "path": str(path),
                    "line_no": line_no,
                    "line": raw.rstrip(),
                    "reason": "missing-digest",
                }
            )
            continue

        digest = dm.group("digest")
        if _HEX_DIGEST_RE.match(digest):
            continue
        if digest in ALLOWED_PLACEHOLDERS:
            placeholders.append(
                {
                    "path": str(path),
                    "line_no": line_no,
                    "token": digest,
                }
            )
            continue
        violations.append(
            {
                "path": str(path),
                "line_no": line_no,
                "line": raw.rstrip(),
                "reason": f"unknown-digest-token:{digest}",
            }
        )

    return violations, placeholders, from_line_count


def build_report(repo_root: Path) -> dict:
    """Walk all infra-tree Containerfiles and assemble the report."""
    files = find_containerfiles(repo_root)
    all_violations: list[dict] = []
    all_placeholders: list[dict] = []
    total_from_lines = 0

    for path in files:
        v, p, n = scan_containerfile(path)
        # Normalize paths to repo-relative for stable JSON output.
        rel = path.relative_to(repo_root)
        for entry in v:
            entry["path"] = str(rel)
        for entry in p:
            entry["path"] = str(rel)
        all_violations.extend(v)
        all_placeholders.extend(p)
        total_from_lines += n

    return {
        "schema_version": 1,
        "kind": "containerfile-base-image-digest-pin-report",
        "scanned_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "containerfile_count": len(files),
        "from_line_count": total_from_lines,
        "violations": all_violations,
        "placeholders": all_placeholders,
        "verdict": "FAIL" if all_violations else "PASS",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_containerfile_base_image_digest",
        description=(
            "Verify every Containerfile FROM line in infra/ carries a "
            "sha256 digest pin (Tag-57 OPEN-K1)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout (report-only mode).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.repo_root.is_dir():
        print(
            f"verify_containerfile_base_image_digest: --repo-root not a dir: "
            f"{args.repo_root}",
            file=sys.stderr,
        )
        return 2

    report = build_report(args.repo_root)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if not args.quiet:
        print(
            f"verify_containerfile_base_image_digest: "
            f"{report['containerfile_count']} Containerfile(s), "
            f"{report['from_line_count']} FROM line(s), "
            f"{len(report['violations'])} violation(s), "
            f"{len(report['placeholders'])} placeholder(s), "
            f"verdict={report['verdict']}"
        )
        for v in report["violations"]:
            print(
                f"  VIOLATION {v['path']}:{v['line_no']} "
                f"reason={v['reason']} :: {v['line']}",
                file=sys.stderr,
            )

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
