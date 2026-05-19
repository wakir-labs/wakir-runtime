# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Tag-60 engine-version-drift scanner (Selin, Persona-Engine).

Mira's Tag-59 Hot-Fix #381 had to sweep four drift layers (engine_async.py,
cli.py docstring, 7 hardcoded-literal test-files, and the historical
release-notes test that only covered engine.py + __version__.py). Tag-60
closes that gap with a hermetic scanner + a 15-test pin in
``wirelang/tests/persona_engine/test_engine_version_drift_full_coverage_tag60.py``.

Substrate ownership (Selin, ADR-0036/0043/0065/0066):

* This scanner is Persona-Engine-Owner substrate. It does NOT modify
  persona definitions (Aisha-Domaene, ADR-0043), WAT-core logic
  (Tomas-Domaene, Zone-K), identity-substrate design (Reza-Domaene,
  Zone-L), or container-infra (Kai-Domaene, Zone-J).
* It is a pure stdlib helper. No third-party deps, no network, no
  subprocess. Deterministic byte-shape output sorted by (path, line).

Scan inputs (Tag-60 auftrag wording, verbatim):

1. ``wirelang/persona_engine/*.py``                    — production code
2. ``wirelang/persona_engine/**/*.md``                  — narrative docs
3. ``wirelang/tests/persona_engine/*.py`` (except      — hermetic tests
   allowlisted release-notes-tests)

Target stale literals:

    STALE_VERSIONS = ("0.5.0-pilot", "0.5.1-pre-cutover",
                      "0.5.2-final-pre-cutover", "0.5.3-rc1")

The canonical active version (``0.5.3``, per
``wirelang/persona_engine/__version__.py`` — Tag-62 rc1-suffix-drop)
is NEVER flagged. Tag-62 extended the hunted set to include
``0.5.3-rc1`` as the most recent stale literal, with the allowlist
covering the legitimate rc1-surviving artefacts (the Tag-59
V-907-baseline JSON, the Tag-58/59/60/61 hermetic-test fixtures,
and the historical rc1 release-notes file under
``docs/persona-engine/`` which is outside the scan-glob anyway).

Allowlist mechanic
------------------
A JSON sidecar at ``tooling/ci/engine-version-drift-allowlist.json``
lists legitimate stale-literal contexts per repo-relative file path.
The schema is:

    {
      "_schema": {...},
      "entries": [
        {
          "path": "wirelang/persona_engine/MANIFEST-0.5.0-pre-cutover.md",
          "categories": ["historical-manifest"],
          "reason": "..."
        }
      ]
    }

A scan-finding is suppressed if and only if its repo-relative path
matches an allowlist entry's ``path`` exactly AND the entry's
``categories`` list is non-empty. Categories are advisory metadata
for human review (the scanner does not enforce per-category
predicates), but every legitimate exception must be motivated in
the ``reason`` field. The legitimate categories are:

* ``historical-manifest`` — the file IS a frozen manifest of an
  older engine version.
* ``historical-pin-pack-reference`` — the file is a per-version
  verifier that intentionally references its own manifest filename.
* ``release-notes-negative-assertion`` — the test asserts the stale
  literal is NOT present and therefore must mention it.
* ``historical-migration-narrative`` — free-form prose in docstrings
  describing past migrations.
* ``v907-baseline-pin`` — the JSON baseline file pins historical
  hash inputs that contain version strings.
* ``manifest-historical-comment`` — single-line comment in production
  code referencing a past version transition for narrative purposes
  only — never an active version claim.

CLI
---
::

    python tooling/ci/scan_engine_version_drift.py [--repo-root PATH]
        [--allowlist PATH] [--strict]

Exit codes
~~~~~~~~~~

* ``0`` — no un-allowlisted drift findings.
* ``1`` — at least one un-allowlisted finding (or ``--strict`` and
  any finding at all, allowlisted or not).
* ``2`` — invariant violation (allowlist parse error, missing scan
  root, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Canonical constants. Bump in lockstep with __version__.py.
# ---------------------------------------------------------------------------

#: The active engine version. Never flagged. Tag-62 dropped the rc1
#: suffix; the rc1 literal joins ``STALE_VERSIONS`` below.
ACTIVE_VERSION = "0.5.3"

#: Stale version literals the Tag-60/Tag-62 scanner hunts. Ordered
#: longest-first so substring overlap (e.g. ``0.5.2-final-pre-cutover``
#: contains ``0.5.2``) does not double-count matches: the scanner
#: records the longest match per (path, line, col). Tag-62 added
#: ``0.5.3-rc1`` as the most recent stale literal; the allowlist below
#: covers the legitimate rc1-surviving contexts.
STALE_VERSIONS: tuple[str, ...] = (
    "0.5.2-final-pre-cutover",  # len 23
    "0.5.1-pre-cutover",        # len 17
    "0.5.0-pilot",              # len 11
    "0.5.3-rc1",                # len 9
)

#: Repo-relative scan roots. Glob patterns are evaluated against
#: ``repo_root``.
SCAN_GLOBS: tuple[str, ...] = (
    "wirelang/persona_engine/*.py",
    "wirelang/persona_engine/*.md",
    "wirelang/persona_engine/**/*.md",
    "wirelang/persona_engine/v907-hash-baseline.json",
    "wirelang/tests/persona_engine/*.py",
)

#: Legitimate allowlist categories. The scanner accepts any non-empty
#: subset of this set per entry; unknown categories trigger an
#: invariant error so typos do not silently suppress findings.
LEGITIMATE_CATEGORIES: frozenset[str] = frozenset(
    {
        "historical-manifest",
        "historical-pin-pack-reference",
        "release-notes-negative-assertion",
        "historical-migration-narrative",
        "v907-baseline-pin",
        "manifest-historical-comment",
    }
)

#: Default allowlist path (repo-relative).
DEFAULT_ALLOWLIST_RELPATH = "tooling/ci/engine-version-drift-allowlist.json"


# ---------------------------------------------------------------------------
# Data structures.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One stale-literal hit in one file at one (line, col) position."""

    path: str  # repo-relative POSIX path
    line: int  # 1-indexed
    col: int  # 1-indexed
    literal: str  # the matched stale version literal
    line_text: str  # full line content, stripped of trailing newline

    def as_record(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "literal": self.literal,
            "line_text": self.line_text,
        }


@dataclass
class AllowlistEntry:
    path: str
    categories: tuple[str, ...]
    reason: str


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    allowlisted: list[Finding] = field(default_factory=list)

    def all_findings(self) -> list[Finding]:
        return list(self.findings) + list(self.allowlisted)


# ---------------------------------------------------------------------------
# Allowlist parsing.
# ---------------------------------------------------------------------------


class AllowlistError(Exception):
    """Raised when the allowlist JSON fails schema validation."""


def load_allowlist(allowlist_path: Path) -> dict[str, AllowlistEntry]:
    """Parse the allowlist JSON into a ``{repo_relpath: entry}`` map.

    Raises ``AllowlistError`` on schema violation. The check is
    deliberately strict: unknown categories, duplicate paths, missing
    fields all fail loudly so a typo cannot silently widen the
    suppression surface.
    """
    if not allowlist_path.is_file():
        raise AllowlistError(f"allowlist file not found: {allowlist_path}")
    try:
        raw = json.loads(allowlist_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"allowlist not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise AllowlistError("allowlist root must be a JSON object")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise AllowlistError("allowlist 'entries' must be a list")

    result: dict[str, AllowlistEntry] = {}
    for idx, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            raise AllowlistError(f"entry {idx} is not a JSON object")
        path = item.get("path")
        cats = item.get("categories")
        reason = item.get("reason")
        if not isinstance(path, str) or not path:
            raise AllowlistError(f"entry {idx} missing 'path' string")
        if not isinstance(cats, list) or not cats:
            raise AllowlistError(
                f"entry {idx} ({path}) missing non-empty 'categories'"
            )
        if not all(isinstance(c, str) for c in cats):
            raise AllowlistError(
                f"entry {idx} ({path}) has non-string category"
            )
        unknown = set(cats) - LEGITIMATE_CATEGORIES
        if unknown:
            raise AllowlistError(
                f"entry {idx} ({path}) has unknown categories: "
                f"{sorted(unknown)}; legitimate set is "
                f"{sorted(LEGITIMATE_CATEGORIES)}"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistError(
                f"entry {idx} ({path}) missing non-empty 'reason'"
            )
        if path in result:
            raise AllowlistError(f"duplicate allowlist entry: {path}")
        result[path] = AllowlistEntry(
            path=path, categories=tuple(cats), reason=reason
        )
    return result


# ---------------------------------------------------------------------------
# Scanning core.
# ---------------------------------------------------------------------------


def iter_scan_files(repo_root: Path) -> Iterable[Path]:
    """Yield absolute paths of every file matched by ``SCAN_GLOBS``.

    The traversal is deterministic: globs are evaluated in declared
    order and each glob's hits are sorted lexicographically.
    """
    seen: set[Path] = set()
    for pattern in SCAN_GLOBS:
        # rglob does not honour leading-slash semantics; use glob for
        # non-recursive patterns and the rglob form for ``**`` patterns.
        if "**" in pattern:
            base_part, _, tail = pattern.partition("**/")
            base = repo_root / base_part.rstrip("/")
            if not base.is_dir():
                continue
            for hit in sorted(base.rglob(tail)):
                if hit.is_file() and hit not in seen:
                    seen.add(hit)
                    yield hit
        else:
            for hit in sorted(repo_root.glob(pattern)):
                if hit.is_file() and hit not in seen:
                    seen.add(hit)
                    yield hit


def scan_file(path: Path, repo_root: Path) -> list[Finding]:
    """Scan a single file for ``STALE_VERSIONS`` literals.

    Returns one Finding per (line, col) hit. Longest-match-first
    ordering on ``STALE_VERSIONS`` ensures the longer literal is
    recorded when a line contains both (e.g. a comment that names the
    full 0.5.2-final-pre-cutover string also matches 0.5.0-pilot as a
    substring of 0.5.0-pilot only if it actually contains 0.5.0-pilot;
    the ordering is a guard for future literal additions).
    """
    rel = path.relative_to(repo_root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Track positions already claimed by a longer literal to avoid
        # double-reporting overlapping substrings.
        claimed: list[tuple[int, int]] = []
        for literal in STALE_VERSIONS:
            start = 0
            while True:
                idx = line.find(literal, start)
                if idx < 0:
                    break
                end = idx + len(literal)
                if any(c_start <= idx < c_end for c_start, c_end in claimed):
                    start = end
                    continue
                claimed.append((idx, end))
                findings.append(
                    Finding(
                        path=rel,
                        line=lineno,
                        col=idx + 1,
                        literal=literal,
                        line_text=line,
                    )
                )
                start = end
    findings.sort(key=lambda f: (f.line, f.col, f.literal))
    return findings


def scan_repo(
    repo_root: Path,
    allowlist: dict[str, AllowlistEntry],
) -> ScanResult:
    """Walk the configured scan-globs and partition findings.

    Findings on a path that has an allowlist entry land in
    ``result.allowlisted``; everything else lands in ``result.findings``.
    """
    result = ScanResult()
    for path in iter_scan_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        hits = scan_file(path, repo_root)
        if not hits:
            continue
        if rel in allowlist:
            result.allowlisted.extend(hits)
        else:
            result.findings.extend(hits)
    result.findings.sort(key=lambda f: (f.path, f.line, f.col))
    result.allowlisted.sort(key=lambda f: (f.path, f.line, f.col))
    return result


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scan_engine_version_drift",
        description=(
            "Tag-60 Persona-Engine version-drift scanner. Hunts stale "
            f"version literals {sorted(STALE_VERSIONS)} across the "
            "persona_engine package, manifests, and tests. Active "
            f"version {ACTIVE_VERSION} is never flagged."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help=(
            "Repo root to scan. Defaults to the resolved parent of this "
            "script's tooling/ci/ directory."
        ),
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help=(
            "Allowlist JSON path. Defaults to "
            f"{DEFAULT_ALLOWLIST_RELPATH} under the resolved repo-root."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Fail even if every finding is allowlisted. Use this to "
            "verify the allowlist is not silently suppressing new "
            "drift."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit findings as JSON instead of human-readable text.",
    )
    return parser


def _default_repo_root() -> Path:
    # tooling/ci/scan_engine_version_drift.py -> repo root is parents[2].
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    repo_root = (args.repo_root or _default_repo_root()).resolve()
    allowlist_path = (
        args.allowlist
        if args.allowlist is not None
        else repo_root / DEFAULT_ALLOWLIST_RELPATH
    )
    if not repo_root.is_dir():
        print(f"ERROR: repo root not a directory: {repo_root}", file=sys.stderr)
        return 2
    try:
        allowlist = load_allowlist(allowlist_path)
    except AllowlistError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    result = scan_repo(repo_root, allowlist)

    if args.json:
        payload = {
            "active_version": ACTIVE_VERSION,
            "stale_literals_hunted": list(STALE_VERSIONS),
            "findings_unallowlisted": [
                f.as_record() for f in result.findings
            ],
            "findings_allowlisted": [
                f.as_record() for f in result.allowlisted
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if result.findings:
            print(
                f"Tag-60 drift scanner: {len(result.findings)} "
                "un-allowlisted findings:"
            )
            for f in result.findings:
                print(f"  {f.path}:{f.line}:{f.col}  {f.literal}")
                print(f"      | {f.line_text.strip()}")
        else:
            print(
                "Tag-60 drift scanner: clean (no un-allowlisted findings)."
            )
        print(
            f"  ({len(result.allowlisted)} allowlisted hits across "
            f"{len({f.path for f in result.allowlisted})} files.)"
        )

    if result.findings:
        return 1
    if args.strict and result.allowlisted:
        # Strict-mode informs the operator the allowlist is non-empty;
        # exit-1 is the right signal that the situation is not pristine.
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    raise SystemExit(main())
