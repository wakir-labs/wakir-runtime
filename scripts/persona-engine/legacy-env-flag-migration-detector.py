#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Legacy ENV-Flag Migration Detector (Tag-51).

Repo-wide scanner that locates lingering usages of the
v0.4.0 / v0.4.1 ``WAKIR_PE_*_BACKEND`` ENV-flag family
(deprecated by Wirelang Spec v0.4.2 PR #320, Tag-50) and emits a
machine-readable migration report.

Posture
-------

* **stdlib-only.** No third-party imports. The detector is meant
  to run inside the same hermetic sandbox-CI lane as the rest of
  the persona-engine tooling.
* **Read-only.** The detector never rewrites source files. The
  migration is a human operation; the detector's job is to
  surface the targets and the canonical successor for each.
* **Deterministic.** Identical repo trees produce byte-identical
  JSON output. File-order is a sorted ``os.walk`` traversal;
  per-file findings are ordered by line number.
* **Defensive vs. Spec drift.** The migration mapping below is
  pinned to the Wirelang Spec v0.4.2 §6 deprecation table. The
  detector self-tests the mapping on every invocation
  (``--self-test``) to catch silent drift between spec and tool.

What the detector flags
-----------------------

Any text occurrence of one of the nine legacy flag names from
Spec v0.4.2 §6 ("Operator migration guidance (ENV-flag names)"):

  * ``WAKIR_PE_V907_BACKEND``
  * ``WAKIR_PE_SVID_BACKEND``
  * ``WAKIR_PE_BRIDGE_AUDIT_BACKEND``
  * ``WAKIR_PE_STATE_BACKING_BACKEND``
  * ``WAKIR_PE_FSM_BACKEND``
  * ``WAKIR_PE_SUBSCRIBE_LOOP_BACKEND``
  * ``WAKIR_PE_RECOVERY_BACKEND``
  * ``WAKIR_PE_ANCHOR_EMITTER_BACKEND``
  * ``WAKIR_PE_CANONICAL_FORM_BACKEND``

Additionally, the generic family wildcard ``WAKIR_PE_*_BACKEND``
(the literal regex ``WAKIR_PE_[A-Z0-9_]+_BACKEND``) catches any
future flag added under the deprecated prefix that the table does
not explicitly enumerate; such a finding carries an explicit
``mapping_status: "unknown-prefix"`` marker so the operator knows
the detector cannot auto-suggest a successor.

What the detector excludes (by default)
---------------------------------------

The legacy names legitimately appear in:

  * Spec files (``wirelang/specs/wirelang-spec-v0-4.md``,
    ``wirelang-spec-v0-4-1.md``, ``wirelang-spec-v0-4-2.md``)
    where they document the deprecation history.
  * Spec-drift test suites
    (``tests/specs/test_wirelang_spec_v0_4_1_*``,
    ``tests/specs/test_wirelang_spec_v0_4_2_*``) where they
    assert spec-text contains / does not contain the legacy
    names per the §8 invariants.
  * The detector itself and its own hermetic test suite (this
    file plus ``tests/scripts/test_legacy_env_flag_migration_
    detector.py``).
  * The Tag-51 daily-workflow YAML (which names the detector).

These paths are excluded by the built-in DEFAULT_EXCLUDES list.
Pass ``--include-spec-files`` for a full audit that surfaces the
spec-text occurrences too (useful when the spec itself needs a
v0.4.3 deprecation cleanup pass).

Migration mapping
-----------------

The mapping table is sourced verbatim from Spec v0.4.2 §6 (Tag-50
PR #320). Each entry carries:

  * ``legacy``       — the deprecated flag name.
  * ``canonical``    — the v0.4.2 successor (string), or a list
                       of strings when the deprecation splits
                       into multiple canonical flags
                       (bridge-audit), or ``None`` when the flag
                       is removed without replacement
                       (canonical_form, see §4.1 FN-1).
  * ``note``         — short prose anchored in the spec text.

The mapping is intentionally **flat** (no nested config tree)
because the migration is mechanical and the detector consumer
(operator with a Quadlet drop-in or a shell-env file) wants to
read the table once.

Tri-state exit code
-------------------

  * ``0``  — no legacy-flag findings in scanned paths.
  * ``1``  — findings exist; informational mode (default). The
             daily-workflow surfaces this in the step-summary
             but does not fail CI on it (matches the Phase-3c
             informational-baseline pattern).
  * ``2``  — findings exist AND ``--fail-on-find`` was passed.
             Used by PR-time gating once the migration is
             expected complete (post-Tag-55 cutover, TBD).

Exit code ``3`` is reserved for ``--self-test`` failure (mapping
drift vs. Spec v0.4.2 §6). Exit code ``4`` is reserved for
detector internal errors (path-not-found, etc.).

Anchors
-------

  * Wirelang Spec v0.4.2 §6 (deprecation table) — Tag-50 PR #320.
  * ADR-0065 — Phase-3c cutover sequence.
  * Tag-51 inbox / Tomas+Reza cross-review-zone-1.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


# ----------------------------------------------------------------------
# Migration mapping (Wirelang Spec v0.4.2 §6, Tag-50 PR #320)
# ----------------------------------------------------------------------
#
# Each row spells out:
#   legacy           v0.4.0 / v0.4.1 deprecated name
#   canonical        v0.4.2 successor (str | list[str] | None)
#   note             short anchor to spec §
#
# The "bridge-audit" row carries a list because the v0.4.2 split
# attaches the writer flag to one binary and a separate diff
# companion to another; the replay + forward variants have no
# wired ENV-flag in v0.4.2 (the deprecation-table notes this
# verbatim).
#
# The "canonical_form" row carries ``None`` because §4.1 FN-1
# explicitly removes the flag; the parity-oracle-circularity
# argument (§5.7) is the substantive reason no successor is
# wired.

MIGRATION_MAPPING: dict[str, dict[str, Any]] = {
    "WAKIR_PE_V907_BACKEND": {
        "canonical": "WAKIR_V907_VERIFY_BACKEND",
        "note": "Spec v0.4.2 §6 row 1; V-907 verify backend.",
    },
    "WAKIR_PE_SVID_BACKEND": {
        "canonical": "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
        "note": "Spec v0.4.2 §6 row 2; SVID workload identity.",
    },
    "WAKIR_PE_BRIDGE_AUDIT_BACKEND": {
        "canonical": [
            "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
            "WAKIR_BRIDGE_DIFF_BACKEND",
        ],
        "note": (
            "Spec v0.4.2 §6 row 3; bridge-audit splits into writer "
            "and diff companion. Replay + forward variants have no "
            "wired flag in v0.4.2."
        ),
    },
    "WAKIR_PE_STATE_BACKING_BACKEND": {
        "canonical": "WAKIR_STATE_BACKING_BACKEND",
        "note": "Spec v0.4.2 §6 row 4; state-backing backend.",
    },
    "WAKIR_PE_FSM_BACKEND": {
        "canonical": "WAKIR_FSM_BACKEND",
        "note": "Spec v0.4.2 §6 row 5; lifecycle FSM backend.",
    },
    "WAKIR_PE_SUBSCRIBE_LOOP_BACKEND": {
        "canonical": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
        "note": "Spec v0.4.2 §6 row 6; subscribe-loop backend.",
    },
    "WAKIR_PE_RECOVERY_BACKEND": {
        "canonical": "WAKIR_RECOVERY_BACKEND",
        "note": "Spec v0.4.2 §6 row 7; recovery-workflow backend.",
    },
    "WAKIR_PE_ANCHOR_EMITTER_BACKEND": {
        "canonical": "WAKIR_ANCHOR_EMITTER_BACKEND",
        "note": (
            "Spec v0.4.2 §6 row 8; anchor-emitter (was informal in "
            "v0.4.1, never normative)."
        ),
    },
    "WAKIR_PE_CANONICAL_FORM_BACKEND": {
        "canonical": None,
        "note": (
            "Spec v0.4.2 §6 row 9; removed in v0.4.2 (§4.1 FN-1). "
            "Parity-oracle-circularity for JCS primitive — see "
            "§5.7. No successor flag is wired."
        ),
    },
}

# Wildcard regex for forward-compatibility: catches any
# ``WAKIR_PE_*_BACKEND`` form not enumerated in the table above.
# The capture group is the full flag identifier.
LEGACY_PREFIX_RE = re.compile(r"WAKIR_PE_[A-Z0-9_]+_BACKEND")

# Default-excluded path prefixes (relative to repo root). These are
# the locations where legacy names legitimately appear and where a
# default scan should not raise false positives. The semantics are
# "starts-with"; the operator can pass ``--include-spec-files`` to
# disable this list.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/",
    ".github/workflows/persona-engine-legacy-env-flag-migration-daily.yml",
    "wirelang/specs/wirelang-spec-v0-4.md",
    "wirelang/specs/wirelang-spec-v0-4-1.md",
    "wirelang/specs/wirelang-spec-v0-4-2.md",
    "tests/specs/",
    "scripts/persona-engine/legacy-env-flag-migration-detector.py",
    "tests/scripts/test_legacy_env_flag_migration_detector.py",
)

# File-extension allowlist for scanning. Binary files (images,
# tarballs, etc.) are skipped. The list deliberately covers the
# common text formats that operator-environment definitions live in.
SCAN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".rs",
        ".sh",
        ".bash",
        ".zsh",
        ".yml",
        ".yaml",
        ".toml",
        ".md",
        ".txt",
        ".json",
        ".env",
        ".cfg",
        ".ini",
        ".service",
        ".container",
        ".network",
        ".volume",
        ".kube",
        ".env-example",
        ".tmpl",
        ".j2",
    }
)


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Finding:
    """One legacy-flag occurrence located by the scanner."""

    path: str
    line: int
    column: int
    legacy_flag: str
    line_text: str
    mapping_status: str  # "mapped" | "unknown-prefix" | "removed"
    canonical: str | list[str] | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "legacy_flag": self.legacy_flag,
            "line_text": self.line_text,
            "mapping_status": self.mapping_status,
            "canonical": self.canonical,
            "note": self.note,
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _relpath(p: Path, root: Path) -> str:
    """POSIX-style path relative to ``root`` (deterministic across OS)."""
    rp = p.resolve().relative_to(root.resolve())
    return rp.as_posix()


def _is_excluded(rel: str, excludes: Iterable[str]) -> bool:
    """Return True iff ``rel`` starts with any of the excluded prefixes."""
    return any(rel == ex or rel.startswith(ex) for ex in excludes)


def _iter_scan_files(
    root: Path,
    excludes: Iterable[str],
    extensions: Iterable[str] | None = None,
) -> Iterator[Path]:
    """Yield repo files to scan in deterministic (sorted) order.

    Walks ``root`` top-down, prunes excluded directories early to
    keep the walk cheap on large trees, and yields only files whose
    extension is in ``SCAN_EXTENSIONS``.
    """

    ext_set = (
        frozenset(extensions) if extensions is not None else SCAN_EXTENSIONS
    )
    excl_tuple = tuple(excludes)

    for dirpath, dirnames, filenames in os.walk(root):
        # Sort in-place so the walk is deterministic.
        dirnames.sort()
        filenames.sort()

        # Prune excluded directories early. We compute each dir's
        # relpath against ``root``; if it matches an exclude prefix
        # we drop it from ``dirnames`` (which mutates the walk).
        pruned: list[str] = []
        for d in list(dirnames):
            try:
                rel = _relpath(Path(dirpath) / d, root)
            except ValueError:
                # Path is outside root (symlink chasing). Skip.
                continue
            if _is_excluded(rel + "/", excl_tuple):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for fname in filenames:
            p = Path(dirpath) / fname
            if p.suffix not in ext_set:
                continue
            try:
                rel = _relpath(p, root)
            except ValueError:
                continue
            if _is_excluded(rel, excl_tuple):
                continue
            yield p


def _classify(flag: str) -> tuple[str, str | list[str] | None, str]:
    """Return (mapping_status, canonical, note) for a legacy flag."""

    if flag in MIGRATION_MAPPING:
        entry = MIGRATION_MAPPING[flag]
        canonical = entry["canonical"]
        note = entry["note"]
        if canonical is None:
            return ("removed", None, note)
        return ("mapped", canonical, note)

    # Unknown WAKIR_PE_*_BACKEND form (e.g. a future flag added
    # under the deprecated prefix). The detector cannot auto-suggest
    # a successor; the operator must consult the spec.
    return (
        "unknown-prefix",
        None,
        (
            "No mapping in Spec v0.4.2 §6 table; unknown legacy "
            "WAKIR_PE_*_BACKEND form. Consult Spec v0.4.2 §6 and "
            "open a Tag-N follow-up if a new canonical name is "
            "required."
        ),
    )


def _emit_deprecation_warning(count: int, stream: Any) -> None:
    """Emit a single-line deprecation warning to ``stream``.

    Format is deliberately stable so log-aggregators can match it.
    """

    if count <= 0:
        return
    plural = "" if count == 1 else "s"
    msg = (
        f"DeprecationWarning: {count} legacy WAKIR_PE_*_BACKEND "
        f"usage{plural} detected. Migrate to canonical "
        f"WAKIR_*_BACKEND names per Wirelang Spec v0.4.2 §6. "
        f"See https://github.com/wakir-labs/wakir-runtime/pulls "
        f"PR #320 (Tag-50)."
    )
    print(msg, file=stream)


# ----------------------------------------------------------------------
# Core scan
# ----------------------------------------------------------------------


def scan_file(path: Path, root: Path) -> list[Finding]:
    """Return all legacy-flag findings inside ``path``."""

    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return findings

    rel = _relpath(path, root)
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in LEGACY_PREFIX_RE.finditer(line):
            flag = m.group(0)
            status, canonical, note = _classify(flag)
            findings.append(
                Finding(
                    path=rel,
                    line=lineno,
                    column=m.start() + 1,
                    legacy_flag=flag,
                    line_text=line.rstrip(),
                    mapping_status=status,
                    canonical=canonical,
                    note=note,
                )
            )
    return findings


def scan_repo(
    root: Path,
    excludes: Iterable[str] | None = None,
    extensions: Iterable[str] | None = None,
) -> list[Finding]:
    """Scan ``root`` and return all findings in deterministic order."""

    excl = list(DEFAULT_EXCLUDES) if excludes is None else list(excludes)
    all_findings: list[Finding] = []
    for p in _iter_scan_files(root, excl, extensions):
        all_findings.extend(scan_file(p, root))
    return all_findings


def build_report(
    findings: list[Finding],
    root: Path,
    include_spec_files: bool,
) -> dict[str, Any]:
    """Assemble the JSON report shape consumed by the daily workflow."""

    per_flag: dict[str, int] = {}
    per_path: dict[str, int] = {}
    for f in findings:
        per_flag[f.legacy_flag] = per_flag.get(f.legacy_flag, 0) + 1
        per_path[f.path] = per_path.get(f.path, 0) + 1

    return {
        "tool": "legacy-env-flag-migration-detector",
        "tool_version": "tag-51-v1",
        "spec_anchor": "wirelang-spec-v0.4.2 §6",
        "scan_root": str(root.resolve()),
        "include_spec_files": include_spec_files,
        "total_findings": len(findings),
        "per_flag": dict(sorted(per_flag.items())),
        "per_path": dict(sorted(per_path.items())),
        "findings": [f.to_dict() for f in findings],
        "mapping": {
            k: {
                "canonical": v["canonical"],
                "note": v["note"],
            }
            for k, v in MIGRATION_MAPPING.items()
        },
    }


# ----------------------------------------------------------------------
# Self-test (mapping vs. Spec v0.4.2 §6)
# ----------------------------------------------------------------------


def self_test() -> tuple[bool, list[str]]:
    """Verify the mapping table is self-consistent.

    The detector cannot reach the live spec file at runtime (the
    sandbox-CI lane runs without network access and the spec path
    is not guaranteed to be next to the script), so this self-test
    is a structural-invariant check, not a spec-text diff. The
    spec-text diff lives in the hermetic test
    ``tests/scripts/test_legacy_env_flag_migration_detector.py``
    which runs against the in-tree spec file.

    Invariants checked:

      * Exactly 9 entries (Spec §6 table has 9 rows).
      * Every legacy key starts with ``WAKIR_PE_`` and ends with
        ``_BACKEND``.
      * Every canonical entry is either ``None``, a non-empty
        string starting with ``WAKIR_`` and ending with
        ``_BACKEND``, or a non-empty list of such strings.
      * No canonical entry contains ``WAKIR_PE_`` (the canonical
        names dropped the ``PE`` infix per §6).
      * Every entry carries a non-empty ``note``.
    """

    errors: list[str] = []

    if len(MIGRATION_MAPPING) != 9:
        errors.append(
            f"expected 9 entries, found {len(MIGRATION_MAPPING)}"
        )

    for legacy, entry in MIGRATION_MAPPING.items():
        if not legacy.startswith("WAKIR_PE_"):
            errors.append(f"legacy {legacy!r} missing WAKIR_PE_ prefix")
        if not legacy.endswith("_BACKEND"):
            errors.append(f"legacy {legacy!r} missing _BACKEND suffix")

        canonical = entry.get("canonical")
        note = entry.get("note", "")

        if not note:
            errors.append(f"entry {legacy!r} has empty note")

        if canonical is None:
            continue
        if isinstance(canonical, str):
            canonical_list: list[str] = [canonical]
        elif isinstance(canonical, list):
            if not canonical:
                errors.append(f"entry {legacy!r} has empty canonical list")
                continue
            canonical_list = canonical
        else:
            errors.append(
                f"entry {legacy!r} canonical has unsupported type "
                f"{type(canonical).__name__}"
            )
            continue

        for c in canonical_list:
            if not isinstance(c, str) or not c:
                errors.append(
                    f"entry {legacy!r} canonical element {c!r} invalid"
                )
                continue
            if "WAKIR_PE_" in c:
                errors.append(
                    f"entry {legacy!r} canonical {c!r} retains "
                    f"WAKIR_PE_ infix"
                )
            if not c.startswith("WAKIR_"):
                errors.append(
                    f"entry {legacy!r} canonical {c!r} missing WAKIR_ prefix"
                )
            if not c.endswith("_BACKEND"):
                errors.append(
                    f"entry {legacy!r} canonical {c!r} missing _BACKEND "
                    f"suffix"
                )

    return (len(errors) == 0, errors)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="legacy-env-flag-migration-detector",
        description=(
            "Scan a repository for v0.4.0 / v0.4.1 "
            "WAKIR_PE_*_BACKEND legacy ENV-flag usages and "
            "emit a Wirelang-Spec-v0.4.2 §6 migration report."
        ),
    )
    p.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan (default: cwd).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Path to write the JSON report. If omitted, the report "
            "is printed to stdout."
        ),
    )
    p.add_argument(
        "--include-spec-files",
        action="store_true",
        help=(
            "Disable the built-in DEFAULT_EXCLUDES list and scan the "
            "spec files, spec-drift test suites, the detector itself "
            "and the Tag-51 daily-workflow YAML too. Useful for a "
            "full audit when preparing a v0.4.3 spec cleanup."
        ),
    )
    p.add_argument(
        "--fail-on-find",
        action="store_true",
        help=(
            "Exit with code 2 if any finding is reported. Default "
            "is informational (exit 1 on findings, 0 otherwise)."
        ),
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the stderr deprecation-warning summary.",
    )
    p.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the mapping-table structural self-test and exit. "
            "Exit code 0 on pass, 3 on failure."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.self_test:
        ok, errors = self_test()
        if ok:
            print("self-test: OK", file=sys.stderr)
            return 0
        print("self-test: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 3

    root = args.root
    if not root.exists() or not root.is_dir():
        print(
            f"error: --root {root!s} is not an existing directory",
            file=sys.stderr,
        )
        return 4

    # NB: pass an explicit empty list (not None) when --include-spec-
    # files is set; ``scan_repo(excludes=None)`` treats None as
    # "fall back to DEFAULT_EXCLUDES" by design.
    excludes: list[str] = [] if args.include_spec_files else list(
        DEFAULT_EXCLUDES
    )
    findings = scan_repo(root, excludes=excludes)
    report = build_report(
        findings, root, include_spec_files=bool(args.include_spec_files)
    )

    if not args.quiet:
        _emit_deprecation_warning(len(findings), sys.stderr)

    out_text = json.dumps(report, indent=2, sort_keys=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text, encoding="utf-8")
    else:
        sys.stdout.write(out_text)

    if not findings:
        return 0
    if args.fail_on_find:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
