#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Pre-commit SPDX-header check for newly-added substance files.

Tag-32 EXT-AUDIT-FOLGE companion hook. Reads the list of staged
files passed by ``pre-commit`` on the command line, filters down to
*added* files (status ``A`` from ``git diff --cached --name-status``)
and verifies every survivor carries an ``SPDX-License-Identifier:``
marker within the first 4 KiB.

Why "added only" (not modified)
-------------------------------
Legacy churn — bug-fixes in pre-existing files that already happen
to lack a header — should not block a developer's commit. The server-
side ``license-gate.yml`` (ADR-0061 Schritt 8) enforces the full-tree
invariant. The pre-commit hook is the *first line of defense* that
keeps the drift surface from growing during the developer's flow.

Exit codes
----------
* ``0``: all newly-added substance files carry an SPDX header (or no
  files require checking).
* ``1``: at least one newly-added file is missing the SPDX header.
  The hook prints a per-file diagnostic to stderr.

Self-contained
--------------
This module uses only the Python standard library, so the hook does
not need any extra dependency-install step in ``pre-commit``'s venv.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Files whose SPDX-presence is enforced by this hook. The list mirrors
# the file-types-of-substance enumerated in the server-side license-
# gate path-filter (`.github/workflows/license-gate.yml`).
SUBSTANCE_SUFFIXES = frozenset(
    {
        ".py",
        ".rs",
        ".sh",
        ".toml",
        ".yml",
        ".yaml",
        ".md",
    }
)

# Paths under these prefixes are out-of-scope for the SPDX-check.
# `LICENSES/` holds upstream-verbatim license texts (Apache, BUSL,
# CC-BY); `meta/timestamps/` holds OTS attestation blobs; vendored
# trees do not carry our headers.
SKIP_PREFIXES = (
    "LICENSES/",
    "meta/timestamps/",
    ".github/ISSUE_TEMPLATE/",
    "vendor/",
)

# Read up to 4 KiB — long enough to cover any sensible file head
# without slurping huge generated artefacts.
HEAD_BYTES = 4096

# SPDX token is split to avoid a self-referential false-positive in
# `reuse lint` (the lint scans Python source for SPDX-tag patterns
# and would otherwise flag this module as carrying *two* identifiers).
SPDX_TOKEN = "SPDX-License" + "-Identifier:"


def list_added_files() -> set[str]:
    """Return the set of files with status ``A`` in the staged index."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-status", "--diff-filter=A"],
            text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        print(
            f"pre-commit-spdx-header-check: git diff failed: {exc}",
            file=sys.stderr,
        )
        return set()
    added: set[str] = set()
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].startswith("A"):
            added.add(parts[1])
    return added


def is_in_scope(path: str) -> bool:
    """True if the path should be SPDX-checked."""
    if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in SUBSTANCE_SUFFIXES


def has_spdx_header(path: Path) -> bool:
    """True if the file head carries ``SPDX-License-Identifier:``."""
    try:
        with path.open("rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        # Symlink to a non-existent target, missing file in the
        # middle of a rename, etc. Treat as missing.
        return False
    return SPDX_TOKEN.encode("ascii") in head


def main(argv: list[str]) -> int:
    # `pre-commit` passes the staged-file paths positionally. The
    # hook intersection (only-added) drops everything else.
    candidate_paths = set(argv[1:])
    added = list_added_files()

    to_check = sorted(
        path
        for path in candidate_paths
        if path in added and is_in_scope(path)
    )

    repo_root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for rel in to_check:
        abs_path = repo_root / rel
        if not has_spdx_header(abs_path):
            violations.append(rel)

    if violations:
        print(
            "pre-commit-spdx-header-check: missing SPDX-License-Identifier "
            "in newly-added file(s):",
            file=sys.stderr,
        )
        for rel in violations:
            print(f"  {rel}", file=sys.stderr)
        print(
            "\nResolution: prepend the canonical header (Apache-2.0 default; "
            "BUSL-1.1 inside BSL sub-trees per REUSE.toml).",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main(sys.argv))
# REUSE-IgnoreEnd
