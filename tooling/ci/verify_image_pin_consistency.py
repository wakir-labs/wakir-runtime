#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Every file that pins the same image tag must pin the same digest.

Why this file exists
--------------------

``digest-verify python:3.13-slim`` in ``cosign-verify-images.yml``
extracted the pin with::

    grep -oE 'docker\\.io/library/python:[^@ "]+@sha256:[^ "]+' \\
        infra/spire/federation/provisioner/Containerfile | head -n1

One file, and of that file the first match. The python base layer is
pinned in **three** files. So a change that refreshed the provisioner
Containerfile alone turned the check **green** — and green there is a
statement about the pins, not about one line of one file. A gate that
reports green on evidence it never read is worse than no gate: it
replaces not-knowing with false confidence.

The live check cannot close that gap on its own, because "is this pin
current?" depends on a third party's release calendar and on network
access. But the *cheap half* of the question needs neither: if three
files claim to pin ``python:3.13-slim`` and they disagree with each
other, at most one of them can be right, and we know that from disk
alone. That is what this module decides — hermetically, on the pull
request surface, where the change that causes the divergence is.

The rule
--------

For every ``<image>:<tag>`` that appears with an ``@sha256:`` pin
anywhere on the consuming surface: **all committed digests for that
image and tag must be byte-identical.**

Two deliberate boundaries:

* ``docker.io/library/nats:2.11-alpine`` and ``nats:2.11-alpine`` are
  the same image. They are pinned in ``quadlet/wakir-nats.container``
  and ``compose/nats.yaml`` respectively, so a checker that compared
  the literal strings would have put them in two groups of one and
  never compared them at all. References are normalised before
  grouping.

* A ``DIGEST_PENDING_*`` placeholder is **not** counted as a
  conflicting digest. A placeholder is an unresolved site, not a wrong
  one, and the structural gate
  ``tooling/ci/verify_containerfile_base_image_digest.py`` already owns
  which placeholder tokens are legal. Placeholders are reported so the
  mixed state stays visible; they do not fail this check. The one case
  in the tree on 2026-09-21 —
  ``ghcr.io/wakir-labs/wakir-provisioner:0.1.2`` pinned by digest in
  ``quadlet/wakir-nats-kv-bucket-init.container`` and by placeholder in
  ``quadlet/wakir-recovery-drill-anchor.container`` — is therefore
  reported and not failed; it is owned by another cross-review zone.

What this deliberately does not do
----------------------------------

It never touches the network. It cannot tell you whether a digest is
current, whether it is signed, or whether it still exists in the
registry — all three are live questions, and the third one is not
hypothetical (see the done-brief for 2026-09-21). This half says only:
the tree does not contradict itself.

Schema (v1) — JSON report emitted to ``--report``
-------------------------------------------------

  {
    "schema_version": 1,
    "kind": "image-pin-consistency-report",
    "scanned_at_utc": "2026-09-21T...",
    "file_count": 21,
    "pin_count": 34,
    "group_count": 14,
    "groups": [
      {
        "image": "docker.io/library/python",
        "tag": "3.13-slim",
        "digests": ["sha256:8d9d..."],
        "placeholder_tokens": [],
        "sites": [{"path": "...", "line_no": 95, "digest": "sha256:8d9d..."}]
      }
    ],
    "violations": [
      {
        "image": "docker.io/library/python",
        "tag": "3.13-slim",
        "reason": "divergent-digests",
        "digests": ["sha256:aaa...", "sha256:bbb..."],
        "sites": [...]
      }
    ],
    "verdict": "PASS" | "FAIL"
  }

Exit codes
----------

  * 0 — no group has two different committed digests.
  * 1 — at least one group is self-contradictory.
  * 2 — usage / IO error.

Hermetic
--------

stdlib only. No network, no registry client, no third-party imports.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Iterable


#: Directory roots that hold the *consuming* surface — the files a
#: deployment or a build actually reads. ``tests/`` and ``docs/`` are
#: out of scope on purpose: a fixture digest and a digest quoted in
#: historical prose are not pins, and treating them as pins is how a
#: lint earns its way into somebody's skip list.
SCAN_ROOTS: tuple[str, ...] = ("infra", "quadlet", "compose")

#: Filename shapes that carry pins.
FILE_GLOBS: tuple[str, ...] = (
    "Containerfile*",
    "*.container",
    "*.yaml",
    "*.yml",
)

#: Path fragments excluded anywhere under the scan roots.
EXCLUDED_PARTS: frozenset[str] = frozenset({"tests", "test", "__pycache__"})

#: ``<image>[:<tag>]@sha256:<digest-or-placeholder>``.
#:
#: The digest alternation mirrors
#: ``verify_containerfile_base_image_digest.py``: a 64-hex digest or an
#: uppercase ``DIGEST_PENDING_*`` token. Anything else is not a pin this
#: module recognises, and the structural gate is the one that complains
#: about it.
_PIN_RE = re.compile(
    r"(?P<image>[a-z0-9][a-z0-9._-]*(?:/[a-z0-9._-]+)*)"
    r"(?::(?P<tag>[A-Za-z0-9._-]+))?"
    r"@sha256:(?P<digest>[a-f0-9]{64}|DIGEST_PENDING_[A-Z][A-Z0-9_]*)"
)

_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: Registry prefixes that name the same image as the bare form.
#: ``nats:2.11-alpine`` (compose) and
#: ``docker.io/library/nats:2.11-alpine`` (Quadlet) are one image.
_DOCKER_LIBRARY_PREFIX = "docker.io/library/"
_DOCKER_PREFIX = "docker.io/"


def normalise_image(image: str) -> str:
    """Canonical name for an image reference without tag or digest.

    Docker Hub official images may be written bare (``nats``), under
    the library path (``docker.io/library/nats``), or with the registry
    only (``docker.io/nats``). All three denote one repository.
    """
    if image.startswith(_DOCKER_LIBRARY_PREFIX):
        return image[len(_DOCKER_LIBRARY_PREFIX) :]
    if image.startswith(_DOCKER_PREFIX) and image.count("/") == 1:
        return image[len(_DOCKER_PREFIX) :]
    return image


def iter_scan_files(repo_root: Path) -> list[Path]:
    """Every file on the consuming surface, deduplicated and sorted."""
    seen: set[Path] = set()
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for pattern in FILE_GLOBS:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                rel_parts = set(path.relative_to(repo_root).parts[:-1])
                if rel_parts & EXCLUDED_PARTS:
                    continue
                seen.add(path)
    return sorted(seen)


def extract_pins(path: Path, repo_root: Path) -> list[dict]:
    """Every pin in one file. Comment lines are skipped.

    A pin quoted in a comment is documentation — frequently
    documentation *about* a pin that changed — and comparing it with
    the live directive is how a checker starts reporting history as
    drift.
    """
    pins: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return pins
    rel = str(path.relative_to(repo_root))
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("#"):
            continue
        for match in _PIN_RE.finditer(raw):
            image = normalise_image(match.group("image"))
            pins.append(
                {
                    "path": rel,
                    "line_no": line_no,
                    "image": image,
                    "tag": match.group("tag") or "",
                    "digest": match.group("digest"),
                }
            )
    return pins


def build_report(repo_root: Path) -> dict:
    """Group every pin by image+tag and judge each group."""
    files = iter_scan_files(repo_root)
    pins: list[dict] = []
    for path in files:
        pins.extend(extract_pins(path, repo_root))

    grouped: dict[tuple[str, str], list[dict]] = {}
    for pin in pins:
        grouped.setdefault((pin["image"], pin["tag"]), []).append(pin)

    groups: list[dict] = []
    violations: list[dict] = []
    for (image, tag), sites in sorted(grouped.items()):
        digests = sorted(
            {s["digest"] for s in sites if _HEX_DIGEST_RE.match(s["digest"])}
        )
        placeholders = sorted(
            {s["digest"] for s in sites if not _HEX_DIGEST_RE.match(s["digest"])}
        )
        site_records = [
            {"path": s["path"], "line_no": s["line_no"], "digest": s["digest"]}
            for s in sites
        ]
        groups.append(
            {
                "image": image,
                "tag": tag,
                "digests": [f"sha256:{d}" for d in digests],
                "placeholder_tokens": placeholders,
                "sites": site_records,
            }
        )
        if len(digests) > 1:
            violations.append(
                {
                    "image": image,
                    "tag": tag,
                    "reason": "divergent-digests",
                    "digests": [f"sha256:{d}" for d in digests],
                    "sites": site_records,
                }
            )

    return {
        "schema_version": 1,
        "kind": "image-pin-consistency-report",
        "scanned_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "file_count": len(files),
        "pin_count": len(pins),
        "group_count": len(groups),
        "groups": groups,
        "violations": violations,
        "verdict": "FAIL" if violations else "PASS",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_image_pin_consistency",
        description=(
            "Verify that every file pinning the same image tag pins the "
            "same digest (hermetic, tree-wide)."
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
            f"verify_image_pin_consistency: --repo-root not a dir: "
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
            f"verify_image_pin_consistency: "
            f"{report['file_count']} file(s), "
            f"{report['pin_count']} pin(s), "
            f"{report['group_count']} image+tag group(s), "
            f"{len(report['violations'])} violation(s), "
            f"verdict={report['verdict']}"
        )
        for violation in report["violations"]:
            ref = f"{violation['image']}:{violation['tag']}"
            print(
                f"  VIOLATION {ref} pinned at {len(violation['digests'])} "
                f"different digests:",
                file=sys.stderr,
            )
            for site in violation["sites"]:
                print(
                    f"    {site['path']}:{site['line_no']} -> "
                    f"sha256:{site['digest']}",
                    file=sys.stderr,
                )

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
