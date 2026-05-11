# SPDX-License-Identifier: Apache-2.0
"""Operator CLI for the persona self-migration converter + validator + inspect.

Phase-1b Sprint-2 Tag-3 implementation (S2-T1-06). Thin wrapper around
:func:`wirelang.persona.migrate_persona` for ad-hoc operator use,
CI-pipeline integration, and the wakir-runtime self-migration shell
scripts ADR-0036 anticipates.

Sprint-6 Tag-2 added the ``validate`` subcommand (Phase-1c follow-up
#1 from the Tag-1 Crate-7 rapport): thin shim over
:func:`wirelang.persona.validate_persona` that emits the structured
:class:`PersonaValidationReport` as canonical-subset JSON on stdout
and maps ``is_valid`` to exit-code 0 / 1.

Sprint-6 Tag-3 added the ``inspect`` subcommand (Phase-1c follow-up
items #1 + #8): read-only sister of ``migrate`` / ``validate``. Runs
no migration, no validation — only the canonical-subset extractor
and the V-907 persona-hash. Emits a ``PersonaInspectReport``
(``report_schema_version=persona-inspect-v1``) on stdout containing
``canonical_subset`` + ``persona_hash`` + ``persona_file``. Maps a
parser/extractor failure to exit 1 (the persona-definition was
unreadable as a canonical subset).

Synopsis
========

::

    wakir-persona migrate <persona-file>
                          [--target {persona-v0,persona-v1,persona-v2}]
                          [--expect-hash <pin>]
                          [--emit-hash]
                          [--quiet]

    wakir-persona validate <persona-file>
                           [--quiet]

    wakir-persona inspect <persona-file>
                          [--emit-hash]
                          [--quiet]

The ``--target`` choice list is sourced from
:data:`wirelang.persona.PERSONA_SCHEMA_VERSION_LIST`. Phase-1b
Sprint-3 Tag-3 extended the list with ``persona-v2``; Tag-4 then
contracted the v2-target operator surface explicitly via
``tests/test_persona_migration_cli_v2_target.py`` (single-step
v9->v2, multi-step v8->v0->v1->v2 chain, ``--expect-hash`` against
the V8/V9-MIGRATED-V2 pin, forward-only-rejection negative).
The default ``--target`` is :data:`PERSONA_SCHEMA_VERSION_LATEST`,
which deliberately remains at ``persona-v1`` until ADR-0029-Annex
content ratification or the T-B Default-Lock window resolves.

See ``wirelang/specs/self-migration-konverter-spec.md`` §7 for the
full operator surface (inputs, outputs, exit codes, examples).

Posture
=======

The CLI is a thin shim. All migration logic lives in
:mod:`wirelang.persona.persona_migration`; all validation logic
lives in :mod:`wirelang.persona.persona_validator`. The CLI's only
jobs are argparse parsing, file IO, JSON serialisation of the
canonical subset / report, and exit-code mapping. There is no
business logic in this module — keeping the CLI thin keeps the
Phase-1c Rust re-write boundary clean (mirror crate ``persona-cli``
re-implements only the same shim).

Exit codes
==========

Per spec §7.4:

- ``0``: ``migrate`` success (and pin-match if ``--expect-hash`` was
  supplied); ``validate`` success (``is_valid=True``); ``inspect``
  success (canonical subset + persona-hash emitted).
- ``1``: ``migrate`` :class:`PersonaMigrationError`; ``validate``
  ``is_valid=False`` (one or more structured errors emitted);
  ``inspect`` parse / canonical-subset-extraction failure (the
  persona-definition is unreadable as a canonical subset).
- ``2``: ``migrate`` :class:`PersonaMigrationDeterminismError`
  (``--expect-hash`` mismatch). Not used by ``validate`` / ``inspect``.
- ``3``: :class:`FileNotFoundError` on the ``<persona-file>``
  argument (all three subcommands).
- ``64``: argparse usage error (mirrors Unix ``EX_USAGE``). Emitted
  by argparse itself on a parse failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from wirelang.persona.persona_canonical_form import read_canonical_subset
from wirelang.persona.persona_hash import compute_persona_hash_from_canonical
from wirelang.persona.persona_migration import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PERSONA_SCHEMA_VERSION_LIST,
    PersonaMigrationDeterminismError,
    PersonaMigrationError,
    migrate_persona,
)
from wirelang.persona.persona_validator import validate_persona


#: Exit code emitted on :class:`PersonaMigrationError` (chain failure)
#: and on ``validate`` when ``is_valid=False``. Sprint-6 Tag-2 re-uses
#: the same 1-bit "operation failed" exit code for the validator's
#: failure branch (mirror of `git diff --exit-code` convention: 1 means
#: "the question has the negative answer").
EXIT_MIGRATION_ERROR = 1

#: Exit code emitted on :class:`PersonaMigrationDeterminismError`
#: (``--expect-hash`` disagreement). Not used by ``validate``.
EXIT_DETERMINISM_ERROR = 2

#: Exit code emitted when the ``<persona-file>`` argument does not
#: exist on disk.
EXIT_INPUT_NOT_FOUND = 3

#: Alias for the validator failure path. Conceptually distinct from
#: a migration chain failure but mapped to the same code so a single
#: ``$?`` check in a shell pipeline branches the same way.
EXIT_VALIDATION_FAILED = EXIT_MIGRATION_ERROR

#: Alias for the inspect failure path (canonical-subset extraction
#: failed). Same posture as :data:`EXIT_VALIDATION_FAILED` — one
#: shell-script ``$?`` check covers all three failure modes.
EXIT_INSPECT_FAILED = EXIT_MIGRATION_ERROR

#: ``report_schema_version`` value on the inspect-stdout report. Bumped
#: lock-step with breaking shape changes; the byte-identity fixtures
#: under ``wirelang-rust/crates/persona-cli/tests/fixtures/v*-inspected.
#: expected.json`` pin the v1 shape.
PERSONA_INSPECT_REPORT_SCHEMA_VERSION = "persona-inspect-v1"


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser.

    Exposed at module scope so tests can introspect the parser
    surface (option names, defaults) without invoking
    :func:`main`.
    """
    parser = argparse.ArgumentParser(
        prog="wakir-persona",
        description=(
            "Operator CLI for the V-907 persona self-migration "
            "converter (ADR-0036)."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="<command>",
    )

    migrate = subparsers.add_parser(
        "migrate",
        help="Migrate a persona-definition file to the target schema-version.",
        description=(
            "Run the registered migration chain on a persona-definition "
            "file and emit the canonical-subset dict on stdout as JSON. "
            "See wirelang/specs/self-migration-konverter-spec.md §7."
        ),
    )
    migrate.add_argument(
        "persona_file",
        type=Path,
        help="Filesystem path to a UTF-8 markdown persona-definition.",
    )
    migrate.add_argument(
        "--target",
        default=PERSONA_SCHEMA_VERSION_LATEST,
        choices=PERSONA_SCHEMA_VERSION_LIST,
        help=(
            "Target schema-version for the migration chain "
            "(default: %(default)s)."
        ),
    )
    migrate.add_argument(
        "--expect-hash",
        default=None,
        metavar="<pin>",
        help=(
            "Optional post-migration persona-hash pin. Accepts both "
            "bare 64-hex and full 'sha256:<64hex>' form. A mismatch "
            "exits with code 2."
        ),
    )
    migrate.add_argument(
        "--emit-hash",
        action="store_true",
        help=(
            "Emit the post-migration persona-hash on stderr in "
            "'sha256:<64hex>' form, suitable for shell capture."
        ),
    )
    migrate.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable progress line on stderr.",
    )

    validate = subparsers.add_parser(
        "validate",
        help="Validate a persona-definition file (read-only, no migration).",
        description=(
            "Run the read-only persona-validator on a persona-definition "
            "file and emit the canonical-subset PersonaValidationReport "
            "on stdout as JSON. Exit code 0 if is_valid, 1 if not. "
            "See wirelang/persona/persona_validator.py for the report "
            "schema (persona-validation-v1)."
        ),
    )
    validate.add_argument(
        "persona_file",
        type=Path,
        help="Filesystem path to a UTF-8 markdown persona-definition.",
    )
    validate.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable progress line on stderr.",
    )

    inspect = subparsers.add_parser(
        "inspect",
        help="Inspect a persona-definition file (read-only canonical-subset + hash).",
        description=(
            "Run the read-only canonical-subset extractor + V-907 "
            "persona-hash on a persona-definition file and emit the "
            "PersonaInspectReport on stdout as JSON. Exit code 0 on "
            "success, 1 on parse / extractor failure. See "
            "wirelang/persona/persona_canonical_form.py for the "
            "canonical-subset shape (persona-inspect-v1)."
        ),
    )
    inspect.add_argument(
        "persona_file",
        type=Path,
        help="Filesystem path to a UTF-8 markdown persona-definition.",
    )
    inspect.add_argument(
        "--emit-hash",
        action="store_true",
        help=(
            "Emit the V-907 persona-hash on stderr in "
            "'sha256:<64hex>' form, suitable for shell capture. Same "
            "stderr-line shape as `migrate --emit-hash`."
        ),
    )
    inspect.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable progress line on stderr.",
    )

    return parser


def _serialise_canonical_subset(canonical_subset: dict) -> str:
    """Serialise the migrated canonical subset for stdout.

    Sorted keys plus two-space indent, terminating newline. Sorted
    output keeps the CLI byte-stable across Python versions (Python
    dict insertion order is deterministic since 3.7, but two operators
    eyeballing the same migration output benefit from a sort).

    This is **not** the V-907 canonical form — that is JCS, produced
    by :func:`compute_persona_hash_from_canonical`. The CLI stdout is
    a developer-readable view of the same data.
    """
    return json.dumps(canonical_subset, indent=2, sort_keys=True) + "\n"


def _run_migrate(args: argparse.Namespace) -> int:
    """Execute the ``migrate`` subcommand. Return a Unix exit code."""
    persona_file: Path = args.persona_file
    if not persona_file.exists():
        print(
            f"wakir-persona: persona-file not found: {persona_file}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    try:
        migrated = migrate_persona(
            persona_file,
            target_schema_version=args.target,
            expected_post_migration_hash=args.expect_hash,
        )
    except PersonaMigrationDeterminismError as exc:
        # Determinism error wins over the more general migration
        # error: it is a stronger signal (the chain ran cleanly,
        # only the pin disagrees).
        print(f"wakir-persona: hash drift: {exc}", file=sys.stderr)
        return EXIT_DETERMINISM_ERROR
    except PersonaMigrationError as exc:
        print(f"wakir-persona: migration failed: {exc}", file=sys.stderr)
        return EXIT_MIGRATION_ERROR
    except FileNotFoundError as exc:
        # Path was deleted between the existence check and the read,
        # or migrate_persona's own internal Path handling raised.
        print(
            f"wakir-persona: persona-file vanished mid-run: {exc}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    sys.stdout.write(_serialise_canonical_subset(migrated))

    if args.emit_hash:
        # Re-hash the migrated dict for the operator. The hash is
        # cheap (sub-millisecond) and keeps the CLI surface small —
        # we do not need to plumb the hash out of migrate_persona,
        # which only computes it internally when --expect-hash is set.
        post_hash = compute_persona_hash_from_canonical(migrated)
        print(post_hash, file=sys.stderr)

    if not args.quiet:
        # One progress line on stderr keeps interactive use
        # informative without polluting stdout for pipelines.
        print(
            f"wakir-persona: migrated {persona_file} -> {args.target}",
            file=sys.stderr,
        )
    return 0


def _serialise_validation_report(report_dict: dict) -> str:
    """Serialise the validation-report canonical dict for stdout.

    Sorted keys + two-space indent + trailing newline. Identical
    posture to :func:`_serialise_canonical_subset` so a Rust ↔ Python
    byte-stability harness can re-use the same expected-fixture
    pattern.

    The input dict comes from
    :meth:`PersonaValidationReport.to_canonical_dict`; we re-sort
    here defensively in case the upstream contract ever loosens.
    """
    return json.dumps(report_dict, indent=2, sort_keys=True) + "\n"


def _run_validate(args: argparse.Namespace) -> int:
    """Execute the ``validate`` subcommand. Return a Unix exit code."""
    persona_file: Path = args.persona_file
    if not persona_file.exists():
        print(
            f"wakir-persona: persona-file not found: {persona_file}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    try:
        report = validate_persona(persona_file)
    except FileNotFoundError as exc:
        # Path was deleted between the existence check and the read.
        # Mirrors the migrate subcommand's mid-run race posture.
        print(
            f"wakir-persona: persona-file vanished mid-run: {exc}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    sys.stdout.write(_serialise_validation_report(report.to_canonical_dict()))

    if not args.quiet:
        # One progress line on stderr mirrors the migrate subcommand.
        # Verdict-first format ("valid" or "invalid: N error(s)") so an
        # interactive operator gets the answer without parsing the JSON.
        verdict = (
            "valid"
            if report.is_valid
            else f"invalid: {len(report.errors)} error(s)"
        )
        print(
            f"wakir-persona: validated {persona_file} -> {verdict}",
            file=sys.stderr,
        )

    return 0 if report.is_valid else EXIT_VALIDATION_FAILED


def _serialise_inspect_report(report_dict: dict) -> str:
    """Serialise the inspect-report canonical dict for stdout.

    Sorted keys + two-space indent + trailing newline. Identical
    posture to :func:`_serialise_canonical_subset` /
    :func:`_serialise_validation_report` so the Rust ↔ Python
    byte-stability harness can re-use the same expected-fixture
    pattern (V8 / V9 `.expected.json` files under
    ``wirelang-rust/crates/persona-cli/tests/fixtures/``).
    """
    return json.dumps(report_dict, indent=2, sort_keys=True) + "\n"


def _build_inspect_report(
    canonical_subset: dict,
    persona_hash: str,
) -> dict:
    """Assemble the ``persona-inspect-v1`` report dict.

    Keys (lexicographic order is enforced at serialisation time by
    :func:`_serialise_inspect_report`, but we keep insertion order
    stable here too for ``preserve_order``-friendly readers):

    - ``canonical_subset``: the V-907 canonical-subset dict produced
      by :func:`read_canonical_subset`. JSON-serialisable; the shape
      is anchored by ``persona_canonical_form.extract_canonical_subset``
      and the V8 / V9 fixtures.
    - ``persona_hash``: the V-907 ``"sha256:<64hex>"`` pin computed
      over the canonical subset. By construction this equals the
      Sprint-4 ``PERSONA_HASH_PIN_V9`` for the V9 fixture.
    - ``report_schema_version``: ``"persona-inspect-v1"``. Bumped
      lock-step with breaking shape changes.

    Deliberately **no** ``persona_file`` field: the path-as-passed
    would break the cross-language byte-identity anchor between
    Python (pytest cwd) and Rust (cargo manifest dir) invocations,
    and the operator can recover the path from the stderr progress
    line anyway. Keeping the report path-free also makes inspect-
    pipeline composition trivial (cat / sort / diff over the
    JSON blob across files of identical canonical content).
    """
    return {
        "canonical_subset": canonical_subset,
        "persona_hash": persona_hash,
        "report_schema_version": PERSONA_INSPECT_REPORT_SCHEMA_VERSION,
    }


def _run_inspect(args: argparse.Namespace) -> int:
    """Execute the ``inspect`` subcommand. Return a Unix exit code.

    Mirror posture of :func:`_run_validate` but with a different
    failure semantics: parser / extractor exceptions on the canonical
    subset (missing front-matter, malformed YAML, missing required
    keys) map to :data:`EXIT_INSPECT_FAILED` (1) rather than being
    accumulated into a structured-report. The rationale: inspect is
    a debugging / pipeline-introspection tool, not a governance
    gate; if the file is unreadable the right answer is a non-zero
    exit + a one-line stderr marker, not a JSON report-of-errors.
    """
    persona_file: Path = args.persona_file
    if not persona_file.exists():
        print(
            f"wakir-persona: persona-file not found: {persona_file}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    try:
        text = persona_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        # Mid-run race: vanished between the existence check and the
        # read. Mirror of migrate / validate posture.
        print(
            f"wakir-persona: persona-file vanished mid-run: {exc}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    try:
        canonical_subset = read_canonical_subset(text)
    except (ValueError, KeyError) as exc:
        # ValueError covers PersonaFrontmatterMissingError /
        # PersonaFrontmatterMalformedError / unsupported-schema_version;
        # KeyError covers missing required canonical-subset keys.
        # Both are surfaced under one "inspect failed" banner: an
        # operator running `wakir-persona inspect` on a broken file
        # wants the diagnostic + non-zero exit, not a stack trace.
        print(f"wakir-persona: inspect failed: {exc}", file=sys.stderr)
        return EXIT_INSPECT_FAILED

    try:
        persona_hash = compute_persona_hash_from_canonical(canonical_subset)
    except (ValueError, TypeError) as exc:
        # JCS canonicalisation failure on an unserialisable subset
        # (should be unreachable on a successfully-extracted subset
        # but kept defensive for hand-built non-canonical inputs).
        print(f"wakir-persona: inspect failed: {exc}", file=sys.stderr)
        return EXIT_INSPECT_FAILED

    report = _build_inspect_report(canonical_subset, persona_hash)
    sys.stdout.write(_serialise_inspect_report(report))

    if args.emit_hash:
        # Same stderr-line shape as `migrate --emit-hash` so a shell
        # script can pipe either subcommand into the same capture:
        # `pin=$(wakir-persona inspect file.md --emit-hash --quiet 2>&1 >/dev/null)`.
        print(persona_hash, file=sys.stderr)

    if not args.quiet:
        print(
            f"wakir-persona: inspected {persona_file} -> {persona_hash}",
            file=sys.stderr,
        )

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a Unix exit code.

    Wired into ``pyproject.toml`` ``[project.scripts]`` as
    ``wakir-persona = "wirelang.persona.cli:main"``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        return _run_migrate(args)
    if args.command == "validate":
        return _run_validate(args)
    if args.command == "inspect":
        return _run_inspect(args)

    # argparse with required=True on the subparser dest already
    # rejects unknown commands with exit code 2 from argparse's
    # error handler; this branch is defensive belt against future
    # subcommand additions that forget the dispatch wiring.
    parser.error(f"unknown command: {args.command!r}")
    return 64  # unreachable, parser.error raises SystemExit


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
