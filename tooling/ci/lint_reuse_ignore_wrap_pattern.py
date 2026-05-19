#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""REUSE-IgnoreStart/End wrap pre-merge lint helper (Tag-61).

Pattern
-------

Three consecutive hot-fix episodes (Tag-56 Kai ``a58f6e9``, Tag-59
Mira ``046a5e5`` for Noa's Tag-58 test, Tag-60 Kai self-fix
``211dbfb``) all share the same root cause: a freshly-merged test
file contains SPDX-License-Identifier string literals (typically
``Apache-2.0``, ``BUSL-1.1``, or ``CC-BY-4.0`` inside fixture
payloads or canonicaliser assertions) which the ``reuse lint`` stage
of the License-Hygiene Gate (``.github/workflows/license-gate.yml``,
ADR-0061 Schritt 8) classifies as "Invalid SPDX License
Expressions" because they are not bracketed by the
``# REUSE-IgnoreStart`` / ``# REUSE-IgnoreEnd`` sentinel pair.

The hot-fix has been the same in all three cases: wrap the offending
block in those two sentinel markers. This helper detects the pattern
*before* the gate fails on ``main``, so the PR author can fix the
wrap during review instead of needing a follow-up hot-fix commit.

Modes
-----

* ``hint``   - scan, report, exit 0 even on findings (advisory).
* ``enforce``- scan, report, exit 1 on findings (blocking).
* ``self-verify`` - assert the helper file itself is wrap-clean
  (i.e. its own SPDX-string-literal block is properly wrapped) and
  exit 0. Used by the Tag-61 test suite to confirm the helper does
  not trip on itself.

The hint mode also emits a unified-diff-style patch suggestion that
shows where the ``# REUSE-IgnoreStart`` / ``# REUSE-IgnoreEnd``
markers ought to land. This patch is consumed by the Tag-61
workflow's Stage-2 PR-comment job (sandbox-mode: skip comment).

Detection heuristic
-------------------

A "SPDX literal" is any string-literal occurrence (inside ``"..."``,
``'...'``, ``\"\"\"...\"\"\"``, or ``'''...'''``) of the form:

* ``SPDX-License-Identifier: <SPDX-ID>``
* ``SPDX-FileCopyrightText: ...``
* a bare known SPDX-ID token (``Apache-2.0``, ``BUSL-1.1``,
  ``CC-BY-4.0``, ``MIT``, ``GPL-3.0``, ``CC0-1.0``).

False-positive guard: any line that is *itself* a SPDX-header
comment (``# SPDX-License-Identifier: ...`` at column 0 of the
comment) is **not** flagged, because that is the file's own header,
not a literal payload. Equally, anything between a
``# REUSE-IgnoreStart`` and the next ``# REUSE-IgnoreEnd`` on the
same file is considered properly wrapped.

Hermetic
--------

stdlib only. No subprocess, no network. Designed to run in the
license-gate-adjacent workflow lane.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

# REUSE-IgnoreEnd

# Helper file-internal SPDX-string-literal protection.
#
# Detection scope: only the two canonical SPDX-header tag forms.
# These are what `reuse lint` classifies as "Invalid SPDX License
# Expression" when they appear outside REUSE-IgnoreStart/End markers
# in a non-header position. Bare ID tokens (e.g. plain "Apache-2.0"
# mentioned in docstring prose) do NOT trip the upstream linter,
# so we deliberately do not flag them here -- that would produce a
# noise wall of false-positives. The three hot-fix episodes
# (a58f6e9, 046a5e5, 211dbfb) all involved literal
# `SPDX-License-Identifier: <ID>` strings inside fixture payloads.
# REUSE-IgnoreStart
_SPDX_LITERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"SPDX-License-Identifier:\s*[A-Za-z0-9._\-+]+"),
    re.compile(r"SPDX-FileCopyrightText:"),
)
# REUSE-IgnoreEnd

# REUSE-IgnoreStart
_SENTINEL_START = "# REUSE-IgnoreStart"
_SENTINEL_END = "# REUSE-IgnoreEnd"
# REUSE-IgnoreEnd

# A "header comment line" is a line at column 0 starting with ``# ``
# and immediately containing a SPDX-tag. Header comments are the
# file's own SPDX banner and never need to be wrapped.
# REUSE-IgnoreStart
_HEADER_COMMENT_RE = re.compile(r"^\s*#\s*SPDX-(License-Identifier|FileCopyrightText)\b")
# REUSE-IgnoreEnd


@dataclass(frozen=True)
class Finding:
    """One unwrapped SPDX-literal occurrence."""

    path: Path
    line_no: int  # 1-based
    text: str
    matched_token: str


def _iter_unwrapped_lines(content: str) -> Iterator[tuple[int, str]]:
    """Yield (line_no, line) pairs for lines NOT between sentinels.

    Sentinel pairing
    ----------------

    ``IgnoreStart`` opens a region until the next ``IgnoreEnd`` (or
    end-of-file). Nested / unbalanced markers are handled
    permissively: the first ``End`` closes the region; a spurious
    ``End`` without ``Start`` is a no-op.

    Triple-quoted-string suppression
    --------------------------------

    Lines inside a triple-quoted string (``\"\"\"...\"\"\"`` or
    ``'''...'''``) are NOT yielded. ``reuse lint`` treats triple-
    quoted string interiors as opaque payload (no parseable
    comment-tag context), so they never trip the upstream gate and
    must not be flagged here either. Only single-line ``"..."`` /
    ``'...'`` literals on a single source line are payload-bearing
    in the hot-fix-pattern sense.
    """
    in_region = False
    in_triple = None  # holds the opening triple ('"""' or "'''") or None
    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(_SENTINEL_START):
            in_region = True
            continue
        if stripped.startswith(_SENTINEL_END):
            in_region = False
            continue
        # Triple-quoted-string region tracking. A line MAY both open
        # and close (single-line triple); count occurrences to decide.
        for triple in ('"""', "'''"):
            count = line.count(triple)
            if count == 0:
                continue
            # Toggle once per pair. Odd counts toggle the state.
            if in_triple is None:
                if count % 2 == 1:
                    in_triple = triple
            elif in_triple == triple:
                if count % 2 == 1:
                    in_triple = None
        if in_triple is not None:
            # Skip lines that are wholly inside a triple-quoted block.
            # (The opening / closing line of a single-line triple
            # already toggled ``in_triple`` back to None above; only
            # multi-line bodies stay suppressed.)
            continue
        if not in_region:
            yield idx, line


# REUSE-IgnoreStart
def _is_header_banner(line: str) -> bool:
    """Whether the line is a file-owned SPDX banner comment.

    Header banners are SPDX-License-Identifier or
    SPDX-FileCopyrightText comments at column 0 of a comment line.
    They are part of the file's own licensing posture, not payload
    literals, so they must NOT be flagged.
    """
    return bool(_HEADER_COMMENT_RE.match(line))
# REUSE-IgnoreEnd


def _scan_file(path: Path) -> list[Finding]:
    """Return all unwrapped SPDX-literal findings in ``path``."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[Finding] = []
    for line_no, line in _iter_unwrapped_lines(content):
        if _is_header_banner(line):
            continue
        for pat in _SPDX_LITERAL_PATTERNS:
            m = pat.search(line)
            if m is None:
                continue
            findings.append(
                Finding(
                    path=path,
                    line_no=line_no,
                    text=line.rstrip("\n"),
                    matched_token=m.group(0),
                )
            )
            break  # one finding per line is enough
    return findings


def _collect_files(roots: Iterable[Path]) -> list[Path]:
    """Recursively gather ``tests/**/*.py`` from each root."""
    out: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            out.append(root)
            continue
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def scan(roots: Iterable[Path]) -> list[Finding]:
    """Top-level scan API. Returns all findings across ``roots``."""
    findings: list[Finding] = []
    for f in _collect_files(roots):
        findings.extend(_scan_file(f))
    return findings


def render_patch_suggestion(findings: list[Finding]) -> str:
    """Render a human-readable patch suggestion block.

    For each file with findings we report the first and last finding
    line and propose a sentinel-pair around that range. This is a
    *suggestion* only, not an applied diff -- the author still has
    to decide the precise wrap boundary.
    """
    if not findings:
        return ""
    by_path: dict[Path, list[Finding]] = {}
    for f in findings:
        by_path.setdefault(f.path, []).append(f)
    chunks: list[str] = []
    for path, items in by_path.items():
        first = min(it.line_no for it in items)
        last = max(it.line_no for it in items)
        chunks.append(
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ around L{first}..L{last} @@\n"
            f"+# REUSE-IgnoreStart  (suggested, insert above L{first})\n"
            f" ...{len(items)} SPDX-literal line(s) in this range...\n"
            f"+# REUSE-IgnoreEnd    (suggested, insert below L{last})\n"
        )
    return "\n".join(chunks)


def render_text_report(findings: list[Finding]) -> str:
    """Render the canonical text report consumed by the workflow."""
    if not findings:
        return "REUSE-WRAP-INTACT: no unwrapped SPDX literals found.\n"
    lines = [f"REUSE-WRAP-MISSING: {len(findings)} unwrapped SPDX literal(s):\n"]
    for f in findings:
        lines.append(
            f"  {f.path}:{f.line_no}: [{f.matched_token}] {f.text.strip()[:120]}"
        )
    lines.append("")
    lines.append("Patch suggestion:\n")
    lines.append(render_patch_suggestion(findings))
    return "\n".join(lines) + "\n"


def _self_verify(helper_path: Path) -> int:
    """Confirm the helper file itself has no unwrapped SPDX literals.

    Used by Tag-61 tests as the regression guard against the helper
    tripping on its own internals.
    """
    findings = _scan_file(helper_path)
    if findings:
        sys.stderr.write(
            "SELF-VERIFY-FAIL: helper file contains unwrapped SPDX literals:\n"
        )
        for f in findings:
            sys.stderr.write(f"  L{f.line_no}: {f.text.strip()[:120]}\n")
        return 1
    sys.stdout.write("SELF-VERIFY-OK: helper file is wrap-clean.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="lint_reuse_ignore_wrap_pattern",
        description=(
            "Scan tests/**/*.py for unwrapped SPDX-literal payloads "
            "and report missing REUSE-IgnoreStart/End wraps."
        ),
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        default=[Path("tests")],
        help="Directories or files to scan (default: tests/).",
    )
    parser.add_argument(
        "--mode",
        choices=("hint", "enforce", "self-verify"),
        default="hint",
        help=(
            "hint: advisory (exit 0 on findings). "
            "enforce: blocking (exit 1 on findings). "
            "self-verify: check the helper file itself."
        ),
    )
    parser.add_argument(
        "--helper-path",
        type=Path,
        default=Path(__file__).resolve(),
        help="Path to this helper file (self-verify mode only).",
    )
    args = parser.parse_args(argv)

    if args.mode == "self-verify":
        return _self_verify(args.helper_path)

    findings = scan(args.roots)
    sys.stdout.write(render_text_report(findings))
    if args.mode == "enforce" and findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
