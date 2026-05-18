#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pre-commit ``REUSE.toml`` annotation-drift check.

Tag-32 EXT-AUDIT-FOLGE companion hook. Triggered whenever ``REUSE.toml``
itself is staged. Verifies two invariants:

  1. ``REUSE.toml`` parses as valid TOML.

  2. Every ``[[annotations]]`` entry with a ``path = "..."`` glob has
     at least one matching file on disk. A stale annotation (typically
     introduced by a rename or deletion that forgot to update the
     REUSE manifest) is a license-lineage drift and is rejected.

The check is intentionally narrow — it does *not* validate that every
matched file actually carries the annotated SPDX identifier; that is
the job of ``reuse lint`` (Layer 1). The drift-check catches the
class of bug that ``reuse lint`` silently tolerates: annotations that
match zero files.

Standard library only — no extra dependency-install step needed.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REUSE_TOML = REPO_ROOT / "REUSE.toml"


def _glob_to_pathlib(pattern: str) -> str:
    """Normalize a REUSE-3.0 path-glob to pathlib's accepted form.

    REUSE-3.0 globs use ``**`` for "any number of path components".
    Pathlib's :meth:`Path.glob` honours that with the recursive glob.
    Trailing ``/**`` matches "all files in the sub-tree". We just
    strip a leading ``./`` if any author wrote one.
    """
    if pattern.startswith("./"):
        return pattern[2:]
    return pattern


def matches_any_file(pattern: str, root: Path) -> bool:
    """True if ``pattern`` (a REUSE.toml path-glob) matches any file."""
    normalised = _glob_to_pathlib(pattern)
    # `Path.glob` happily accepts `**` semantics. For literal
    # (non-glob) paths we still iterate to mirror semantics, so a
    # single missing literal file is also flagged.
    try:
        for match in root.glob(normalised):
            if match.is_file():
                return True
    except (OSError, ValueError):
        # Malformed pattern — let the violation list capture it.
        return False
    return False


def main() -> int:
    if not REUSE_TOML.is_file():
        # REUSE.toml gone? That is a bigger problem than drift —
        # surface a clear error.
        print(
            "pre-commit-reuse-toml-drift-check: REUSE.toml is missing.",
            file=sys.stderr,
        )
        return 1

    try:
        with REUSE_TOML.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"pre-commit-reuse-toml-drift-check: REUSE.toml is not valid "
            f"TOML: {exc}",
            file=sys.stderr,
        )
        return 1

    annotations = data.get("annotations", []) or []
    if not isinstance(annotations, list):
        print(
            "pre-commit-reuse-toml-drift-check: REUSE.toml [[annotations]] "
            "is not an array.",
            file=sys.stderr,
        )
        return 1

    violations: list[tuple[int, str]] = []
    for idx, entry in enumerate(annotations):
        path = entry.get("path") if isinstance(entry, dict) else None
        if not path or not isinstance(path, str):
            # Non-path annotations (e.g. SPDX-PackageName at the top
            # level) are stored in the toplevel dict, not under
            # `annotations`, so this branch should not fire in well-
            # formed REUSE.toml. We still guard it.
            continue
        if not matches_any_file(path, REPO_ROOT):
            violations.append((idx, path))

    if violations:
        print(
            "pre-commit-reuse-toml-drift-check: REUSE.toml has stale "
            "[[annotations]] (no files match):",
            file=sys.stderr,
        )
        for idx, path in violations:
            print(f"  #{idx}: path = \"{path}\"", file=sys.stderr)
        print(
            "\nResolution: either restore the missing file(s) or remove "
            "the stale annotation block from REUSE.toml.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
