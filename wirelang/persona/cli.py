# SPDX-License-Identifier: Apache-2.0
"""Operator CLI for the persona self-migration converter.

Phase-1b Sprint-2 Tag-3 implementation (S2-T1-06). Thin wrapper around
:func:`wirelang.persona.migrate_persona` for ad-hoc operator use,
CI-pipeline integration, and the wakir-runtime self-migration shell
scripts ADR-0036 anticipates.

Synopsis
========

::

    wakir-persona migrate <persona-file>
                          [--target persona-v1]
                          [--expect-hash <pin>]
                          [--emit-hash]
                          [--quiet]

See ``wirelang/specs/self-migration-konverter-spec.md`` §7 for the
full operator surface (inputs, outputs, exit codes, examples).

Posture
=======

The CLI is a thin shim. All migration logic lives in
:mod:`wirelang.persona.persona_migration`; the CLI's only jobs are
argparse parsing, file IO, JSON serialisation of the canonical
subset, and exit-code mapping. There is no business logic in this
module — keeping the CLI thin keeps the Phase-1c Rust re-write
boundary clean.

Exit codes
==========

Per spec §7.4:

- ``0``: success (and pin-match if ``--expect-hash`` was supplied).
- ``1``: :class:`PersonaMigrationError` (chain not resolvable,
  malformed input, ...).
- ``2``: :class:`PersonaMigrationDeterminismError` (``--expect-hash``
  mismatch).
- ``3``: :class:`FileNotFoundError` on the ``<persona-file>`` argument.
- ``64``: argparse usage error (mirrors Unix ``EX_USAGE``). Emitted
  by argparse itself on a parse failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from wirelang.persona.persona_hash import compute_persona_hash_from_canonical
from wirelang.persona.persona_migration import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PERSONA_SCHEMA_VERSION_LIST,
    PersonaMigrationDeterminismError,
    PersonaMigrationError,
    migrate_persona,
)


#: Exit code emitted on :class:`PersonaMigrationError` (chain failure).
EXIT_MIGRATION_ERROR = 1

#: Exit code emitted on :class:`PersonaMigrationDeterminismError`
#: (``--expect-hash`` disagreement).
EXIT_DETERMINISM_ERROR = 2

#: Exit code emitted when the ``<persona-file>`` argument does not
#: exist on disk.
EXIT_INPUT_NOT_FOUND = 3


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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a Unix exit code.

    Wired into ``pyproject.toml`` ``[project.scripts]`` as
    ``wakir-persona = "wirelang.persona.cli:main"``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "migrate":
        return _run_migrate(args)

    # argparse with required=True on the subparser dest already
    # rejects unknown commands with exit code 2 from argparse's
    # error handler; this branch is defensive belt against future
    # subcommand additions that forget the dispatch wiring.
    parser.error(f"unknown command: {args.command!r}")
    return 64  # unreachable, parser.error raises SystemExit


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
