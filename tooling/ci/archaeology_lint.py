#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Fail the build when development archaeology re-enters the public tree.

ADR-0072 sub-item 4d asks that sprint counters, development-day anchors
and internal persona names stay out of the published surface. Sweeping
once is easy; staying swept is not, which is what this lint is for.

Scope decision (W5, recorded here because it is the load-bearing choice):
the sweep regex used during the cleanup is deliberately *wider* than the
regex enforced here. `Welle`, `Cutover`, `KW-NN` and `Marathon` are not
enforced, because three independent zone sweeps found the same thing —
those four words survive in living code as metric names, alert-group
names, routing classes, state-file names and function identifiers, not
as archaeology. Enforcing them would have produced roughly 180 allowlist
entries whose only content is "this is a name, not a diary entry", and an
allowlist that large stops being read. What is enforced is the vocabulary
that has no legitimate reason to appear in a published artefact.

Allowlist (`.archaeology-allowlist.yaml`): every entry needs `path` and
`reason`, plus exactly one justification:

  * `pinned_by` — a test or tool that nails the literal byte-for-byte.
    Removing the literal means changing that pin in the same commit.
  * `deferred_to` — the zone that owns the file, for literals this sweep
    could not remove without editing another zone's surface. Temporary
    by construction and listed in the report on every run.

An entry with neither, or with both, is a schema error and fails the
lint: the point of the file is that every exception names its reason.

Usage:  python tooling/ci/archaeology_lint.py [--report]
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / ".archaeology-allowlist.yaml"

#: Enforced vocabulary. Case-sensitive on purpose: `mira-notify` is a
#: shipped component, `Mira` is a person.
ENFORCED_PATTERN = (
    r"Tag-[0-9]+"
    r"|Sprint-?[0-9]*"
    r"|AR-Hand"
    r"|Watch-Day"
    r"|Skizze"
    r"|Aufsichtsrat"
    r"|Mira"
    r"|Henrik"
    r"|Tom[aá]s"
    r"|Reza"
    r"|Kai\b"
    r"|Selin"
    r"|Amara"
    r"|Noa\b"
    r"|Lena"
    r"|J[uú]lia"
    r"|Priya"
    r"|Daniel"
    r"|Aisha"
)

#: Never scanned. `docs/archive/` is the designated resting place for
#: retired material and is excluded by ADR-0072 itself.
EXCLUDED_PREFIXES = (
    "docs/archive/",
    ".archaeology-allowlist.yaml",
    "tooling/ci/archaeology_lint.py",
    "tests/ci/test_archaeology_lint.py",
)

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2",
    ".ots", ".bin", ".gz", ".zip", ".tar", ".whl", ".so",
}


@dataclass(frozen=True)
class Entry:
    path: str
    reason: str
    pinned_by: str | None
    deferred_to: str | None

    @property
    def kind(self) -> str:
        return "pinned" if self.pinned_by else "deferred"


class AllowlistError(Exception):
    """The allowlist file itself is malformed."""


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[Entry]:
    if not path.is_file():
        raise AllowlistError(f"allowlist not found: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if doc.get("version") != 1:
        raise AllowlistError("allowlist: `version: 1` is required")
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list):
        raise AllowlistError("allowlist: `entries` must be a list")

    entries: list[Entry] = []
    for index, raw in enumerate(raw_entries):
        where = f"entries[{index}]"
        if not isinstance(raw, dict):
            raise AllowlistError(f"{where}: entry must be a mapping")
        unknown = set(raw) - {"path", "reason", "pinned_by", "deferred_to"}
        if unknown:
            raise AllowlistError(f"{where}: unknown field(s) {sorted(unknown)}")
        path_glob = raw.get("path")
        reason = raw.get("reason")
        pinned_by = raw.get("pinned_by")
        deferred_to = raw.get("deferred_to")
        if not isinstance(path_glob, str) or not path_glob.strip():
            raise AllowlistError(f"{where}: `path` is required")
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistError(f"{where} ({path_glob}): `reason` is required")
        if pinned_by and deferred_to:
            raise AllowlistError(
                f"{where} ({path_glob}): `pinned_by` and `deferred_to` are "
                "mutually exclusive — say which one it is"
            )
        if not pinned_by and not deferred_to:
            raise AllowlistError(
                f"{where} ({path_glob}): needs `pinned_by` (name the test or "
                "tool that nails the literal) or `deferred_to` (name the zone "
                "that owns it). An exception without a reason is not an "
                "exception, it is a leak"
            )
        for field_name, value in (("pinned_by", pinned_by), ("deferred_to", deferred_to)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise AllowlistError(f"{where} ({path_glob}): `{field_name}` must be a non-empty string")
        entries.append(Entry(path_glob, reason, pinned_by, deferred_to))
    return entries


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def is_scanned(path: str) -> bool:
    if path.startswith(EXCLUDED_PREFIXES):
        return False
    return Path(path).suffix.lower() not in BINARY_SUFFIXES


def matches(path: str, entries: list[Entry]) -> Entry | None:
    for entry in entries:
        if fnmatch.fnmatch(path, entry.path):
            return entry
        # A trailing `/**` should also cover the directory's direct children
        # on platforms where fnmatch does not cross separators implicitly.
        if entry.path.endswith("/**") and path.startswith(entry.path[:-2]):
            return entry
    return None


def scan(entries: list[Entry]) -> tuple[dict[str, list[str]], set[str], set[str]]:
    """Return (violations, covered globs, files matched by a deferred entry)."""
    pattern = re.compile(ENFORCED_PATTERN)
    violations: dict[str, list[str]] = {}
    used: set[str] = set()
    deferred_hits: set[str] = set()
    for path in tracked_files():
        if not is_scanned(path):
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        hits = [
            f"{lineno}: {line.strip()[:120]}"
            for lineno, line in enumerate(text.split("\n"), start=1)
            if pattern.search(line)
        ]
        if not hits:
            continue
        entry = matches(path, entries)
        if entry is None:
            violations[path] = hits
        else:
            used.add(entry.path)
            if entry.kind == "deferred":
                deferred_hits.add(path)
    return violations, used, deferred_hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true",
                        help="print the allowlist inventory and exit 0")
    args = parser.parse_args(argv)

    try:
        entries = load_allowlist()
    except AllowlistError as exc:
        print(f"archaeology-lint: {exc}", file=sys.stderr)
        return 2

    violations, used, deferred_hits = scan(entries)
    stale = [e.path for e in entries if e.path not in used]

    pinned = sum(1 for e in entries if e.kind == "pinned")
    deferred = len(entries) - pinned
    print(
        f"archaeology-lint: {len(entries)} allowlist entries "
        f"({pinned} pinned, {deferred} deferred), "
        f"{len(deferred_hits)} files still carrying deferred literals."
    )

    if args.report:
        for entry in entries:
            marker = f"pinned_by={entry.pinned_by}" if entry.pinned_by else f"deferred_to={entry.deferred_to}"
            print(f"  {entry.path}\n      {marker}\n      {entry.reason}")
        return 0

    if stale:
        print(
            "archaeology-lint: allowlist entries that no longer match anything "
            "— delete them, the tree got cleaner:",
            file=sys.stderr,
        )
        for path_glob in stale:
            print(f"  {path_glob}", file=sys.stderr)
        return 1

    if violations:
        print(
            f"archaeology-lint: development archaeology in {len(violations)} "
            "file(s) outside the allowlist:",
            file=sys.stderr,
        )
        for path in sorted(violations):
            print(f"\n  {path}", file=sys.stderr)
            for hit in violations[path][:5]:
                print(f"    {hit}", file=sys.stderr)
            if len(violations[path]) > 5:
                print(f"    ... {len(violations[path]) - 5} more", file=sys.stderr)
        print(
            "\nResolution: remove the literal, or add an allowlist entry to "
            "`.archaeology-allowlist.yaml` naming the test that pins it "
            "(`pinned_by`) or the zone that owns it (`deferred_to`).",
            file=sys.stderr,
        )
        return 1

    print("archaeology-lint: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
