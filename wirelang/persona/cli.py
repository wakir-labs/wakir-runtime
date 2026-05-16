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

Sprint-6 Tag-4 added the ``pin`` subcommand (Phase-1c follow-up
item #1 from the Tag-3 inspect rapport): minimal-footprint
shell-pipeline wrapper that emits **only** the V-907 persona-hash
on stdout (``sha256:<64hex>\\n``) — no JSON, no canonical-subset
echo, no metadata. Mirror posture of ``inspect --emit-hash --quiet``
but with the pin routed to stdout instead of stderr so
``pin=$(wakir-persona pin file.md)`` works as a one-liner without
``2>&1`` redirect gymnastics. Reuses the inspect read-only-path
(canonical-subset extract + JCS-hash); failure semantics identical
(exit 1 on parse / extractor failure, exit 3 on missing file).

Sprint-Wirelang-Persona-Inspect-CLI-MINI (Amara PR #116 §5 +
ADR-0058) added the ``inspect-heartbeat`` subcommand: read-only
introspection of the *running* persona-engine heartbeat substrate.
Distinct from ``inspect`` / ``pin`` / ``validate`` (which all
operate on a persona-definition *file* — the static specification)
because ``inspect-heartbeat`` reads the *runtime* heartbeat state
of one or more persona-engine instances. The runtime state lives
in a directory of per-persona heartbeat JSON files (default
``/var/run/wakir-persona``, overridable via
``$WAKIR_PERSONA_HEARTBEAT_DIR`` or ``--heartbeat-dir`` for CI /
test harnesses); each file has filename ``<persona_slug>.heartbeat.json``
and is written by the engine at every heartbeat tick.

Heartbeat-report schema (``persona-heartbeat-v1``):

- ``persona_slug``: the persona-slug (e.g. ``"pengine"``)
- ``fsm_state``: one of the engine FSM states (``"spawning"``,
  ``"running"``, ``"draining"``, ``"recovering"``, ``"stopped"``,
  ``"unknown"``)
- ``last_heartbeat_at``: ISO-8601 UTC timestamp string, or
  ``null`` if the engine has not emitted a heartbeat yet
- ``v907_pin_current``: the V-907 persona-hash the engine
  currently reports running (``"sha256:<64hex>"`` or ``null``)
- ``v907_pin_expected``: the V-907 persona-hash the engine
  expects to be running per its deploy-time pin
  (``"sha256:<64hex>"`` or ``null``)
- ``v907_drift_detected``: ``true`` if
  ``v907_pin_current != v907_pin_expected`` (and both non-null);
  ``false`` otherwise. Motivated by ADR-0058 §156 (V-907-Hash-
  Drift Risk).
- ``subscribe_loop_active``: ``true`` if the NATS subscribe-loop
  task is alive at the heartbeat tick, ``false`` otherwise
- ``uptime_seconds``: integer seconds since the engine's spawn
  event, or ``null`` if unknown

The CLI is **read-only**: it never writes a heartbeat file. The
write-side lives in ``wirelang/persona_engine/engine.py``
(out-of-scope for this MINI sprint).

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

    wakir-persona pin <persona-file>
                      [--quiet]

    wakir-persona inspect-heartbeat
                          [--heartbeat]
                          [--json | --summary]
                          [--persona <slug>]
                          [--heartbeat-dir <path>]
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
  success (canonical subset + persona-hash emitted); ``pin`` success
  (persona-hash emitted on stdout); ``inspect-heartbeat`` success
  (one or more heartbeat reports emitted, no drift OR drift surfaced
  in the structured report without changing exit code — the report
  is the verdict, not the exit code).
- ``1``: ``migrate`` :class:`PersonaMigrationError`; ``validate``
  ``is_valid=False`` (one or more structured errors emitted);
  ``inspect`` / ``pin`` parse / canonical-subset-extraction failure
  (the persona-definition is unreadable as a canonical subset);
  ``inspect-heartbeat`` parse failure on a heartbeat-state JSON
  file (the file exists but is malformed).
- ``2``: ``migrate`` :class:`PersonaMigrationDeterminismError`
  (``--expect-hash`` mismatch). Not used by ``validate`` /
  ``inspect`` / ``pin`` / ``inspect-heartbeat``.
- ``3``: :class:`FileNotFoundError` on the ``<persona-file>``
  argument (all migration / inspect / pin / validate subcommands)
  OR ``--heartbeat-dir`` not found OR (with ``--persona``) the
  per-slug heartbeat-state file does not exist.
- ``64``: argparse usage error (mirrors Unix ``EX_USAGE``). Emitted
  by argparse itself on a parse failure.
"""

from __future__ import annotations

import argparse
import json
import os
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

#: Alias for the pin failure path (canonical-subset extraction failed).
#: Same posture as :data:`EXIT_INSPECT_FAILED` — ``pin`` shares the
#: inspect read-only-path, so the failure mapping is identical. One
#: ``$?`` check in a shell pipeline covers all four failure modes.
EXIT_PIN_FAILED = EXIT_MIGRATION_ERROR

#: ``report_schema_version`` value on the inspect-stdout report. Bumped
#: lock-step with breaking shape changes; the byte-identity fixtures
#: under ``wirelang-rust/crates/persona-cli/tests/fixtures/v*-inspected.
#: expected.json`` pin the v1 shape.
PERSONA_INSPECT_REPORT_SCHEMA_VERSION = "persona-inspect-v1"

#: ``report_schema_version`` value on the ``inspect-heartbeat``
#: stdout report. Bumped lock-step with breaking shape changes.
PERSONA_HEARTBEAT_REPORT_SCHEMA_VERSION = "persona-heartbeat-v1"

#: Default heartbeat-state directory. The engine writes one JSON
#: file per persona-slug at every heartbeat tick. Overridable via
#: ``$WAKIR_PERSONA_HEARTBEAT_DIR`` (env) or ``--heartbeat-dir``
#: (CLI flag, wins over env). Path lives under ``/var/run`` per
#: filesystem-hierarchy-standard convention for runtime state of
#: a system daemon.
DEFAULT_HEARTBEAT_DIR = Path("/var/run/wakir-persona")

#: Environment variable that overrides :data:`DEFAULT_HEARTBEAT_DIR`.
#: Set by the engine systemd unit + by CI test harnesses. Lower
#: precedence than the ``--heartbeat-dir`` CLI flag.
HEARTBEAT_DIR_ENV_VAR = "WAKIR_PERSONA_HEARTBEAT_DIR"

#: Filename suffix for per-persona heartbeat-state files. The
#: filename stem is the persona-slug (e.g. ``pengine.heartbeat.json``
#: for the pengine persona). Anchored as a constant so the engine
#: write-side (out-of-scope for this MINI sprint) and the CLI
#: read-side cannot drift independently.
HEARTBEAT_FILENAME_SUFFIX = ".heartbeat.json"

#: Canonical FSM-state set the engine may report on the
#: ``fsm_state`` heartbeat-field. Mirrored in
#: :mod:`wirelang.persona_engine.engine` (informally — there is no
#: formal Rust-enum yet, the Phase-1c re-write will introduce one).
#: ``"unknown"`` is the default when the heartbeat-state file is
#: present but the engine has not advanced past spawn-init.
PERSONA_FSM_STATES = (
    "spawning",
    "running",
    "draining",
    "recovering",
    "stopped",
    "unknown",
)

#: Required keys on a per-persona heartbeat-state JSON file. The
#: read-side rejects a file that is missing any of these keys with
#: exit-code 1 (``EXIT_HEARTBEAT_PARSE_FAILED``) so we never emit a
#: half-populated report.
HEARTBEAT_REQUIRED_KEYS = frozenset(
    {
        "persona_slug",
        "fsm_state",
        "last_heartbeat_at",
        "v907_pin_current",
        "v907_pin_expected",
        "subscribe_loop_active",
        "uptime_seconds",
    }
)

#: Exit code for the ``inspect-heartbeat`` parse-failure path
#: (a heartbeat-state JSON file is present but unreadable or
#: missing required keys). Same value as
#: :data:`EXIT_MIGRATION_ERROR` so one shell ``$?`` check branches
#: uniformly across all parse-failure modes in the CLI surface.
EXIT_HEARTBEAT_PARSE_FAILED = EXIT_MIGRATION_ERROR


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

    pin = subparsers.add_parser(
        "pin",
        help="Emit the V-907 persona-hash on stdout (minimal-footprint).",
        description=(
            "Run the read-only canonical-subset extractor + V-907 "
            "persona-hash on a persona-definition file and emit ONLY "
            "the persona-hash on stdout (one line, 'sha256:<64hex>\\n'). "
            "Designed for shell-pipeline capture: "
            "`pin=$(wakir-persona pin file.md)` is a clean one-liner "
            "with no JSON / 2>&1 redirect gymnastics. Exit code 0 on "
            "success, 1 on parse / extractor failure. "
            "V-907-CLI-invariant: stdout equals "
            "`migrate --emit-hash` stderr-last-line equals "
            "`inspect --emit-hash --quiet` stderr-pin."
        ),
    )
    pin.add_argument(
        "persona_file",
        type=Path,
        help="Filesystem path to a UTF-8 markdown persona-definition.",
    )
    pin.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable progress line on stderr.",
    )

    inspect_heartbeat = subparsers.add_parser(
        "inspect-heartbeat",
        help=(
            "Inspect the runtime heartbeat state of one or more "
            "persona-engine instances (read-only)."
        ),
        description=(
            "Read the per-persona heartbeat-state JSON files from "
            "the heartbeat directory (default "
            "/var/run/wakir-persona, overridable via "
            "$WAKIR_PERSONA_HEARTBEAT_DIR or --heartbeat-dir) and "
            "emit a PersonaHeartbeatReport on stdout. Default mode "
            "emits JSON; --summary emits a tabular human-readable "
            "summary. Default scope is ALL persona-engine instances "
            "in the heartbeat directory; --persona <slug> narrows "
            "to a single slug. Distinct from `inspect` / `pin` / "
            "`validate` (file-based on persona-definition specs) "
            "because this subcommand reads RUNTIME state, not the "
            "static specification. Anchored by Amara PR #116 §5 + "
            "ADR-0058 V-907-Hash-Drift Risk §156."
        ),
    )
    inspect_heartbeat.add_argument(
        "--heartbeat",
        action="store_true",
        default=True,
        help=(
            "Heartbeat-inspection mode (default, and currently the "
            "only supported mode). Anchored as an explicit flag so "
            "future modes (e.g. --recovery-history) can layer on "
            "without breaking the default-mode operator muscle "
            "memory."
        ),
    )
    output_group = inspect_heartbeat.add_mutually_exclusive_group()
    output_group.add_argument(
        "--json",
        dest="output_format",
        action="store_const",
        const="json",
        help=(
            "Emit the heartbeat report as JSON on stdout (default). "
            "Sorted keys, two-space indent, trailing newline; same "
            "byte-stable serialisation posture as inspect / validate."
        ),
    )
    output_group.add_argument(
        "--summary",
        dest="output_format",
        action="store_const",
        const="summary",
        help=(
            "Emit the heartbeat report as a one-line-per-persona "
            "tabular summary on stdout. Designed for interactive "
            "operator use (`watch wakir-persona inspect-heartbeat "
            "--summary`); not byte-stable across releases."
        ),
    )
    inspect_heartbeat.set_defaults(output_format="json")
    inspect_heartbeat.add_argument(
        "--persona",
        default=None,
        metavar="<slug>",
        help=(
            "Narrow the inspection scope to a single persona-slug. "
            "Default is ALL persona-engine instances in the "
            "heartbeat directory. The slug is matched against "
            "filename stems (e.g. --persona pengine reads "
            "pengine.heartbeat.json)."
        ),
    )
    inspect_heartbeat.add_argument(
        "--heartbeat-dir",
        default=None,
        type=Path,
        metavar="<path>",
        help=(
            "Path to the heartbeat-state directory. Wins over "
            f"${HEARTBEAT_DIR_ENV_VAR} (env) which wins over the "
            "default (/var/run/wakir-persona). Primary use is "
            "CI / test harnesses that point the CLI at a tmpdir."
        ),
    )
    inspect_heartbeat.add_argument(
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


def _run_pin(args: argparse.Namespace) -> int:
    """Execute the ``pin`` subcommand. Return a Unix exit code.

    Shell-pipeline-shaped variant of ``inspect --emit-hash --quiet``:

    - stdout = the V-907 persona-hash, one line, ``sha256:<64hex>\\n``.
      Nothing else. No JSON envelope, no canonical-subset echo, no
      metadata. The operator captures it directly:

          ``pin=$(wakir-persona pin file.md)``

      without the ``2>&1`` redirect dance that ``inspect --emit-hash
      --quiet`` would require (inspect routes the pin to stderr to
      keep the structured-JSON report on stdout).
    - stderr (default) = one progress line
      ``wakir-persona: pinned <file> -> <pin>``. Suppressed by
      ``--quiet``.

    Failure semantics identical to ``inspect``: extractor /
    canonicaliser exceptions map to :data:`EXIT_PIN_FAILED` (= 1),
    diagnostic goes to stderr as a one-line marker. Path-not-found
    maps to :data:`EXIT_INPUT_NOT_FOUND` (= 3) before any IO.

    V-907-CLI-invariant: this stdout equals
    ``inspect --emit-hash --quiet`` stderr-pin equals
    ``migrate --emit-hash`` stderr-last-line on a v9 (no-op-chain)
    input. The Tag-4 test pack pins all three forms against
    :data:`PERSONA_HASH_PIN_V9` for the V9 fixture.
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
        # read. Mirror of inspect / migrate / validate posture.
        print(
            f"wakir-persona: persona-file vanished mid-run: {exc}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    try:
        canonical_subset = read_canonical_subset(text)
    except (ValueError, KeyError) as exc:
        # Same exception surface as `_run_inspect`. Pin is a strict
        # subset of inspect's behaviour (only the hash, no JSON
        # envelope), so the failure marker reads identically.
        print(f"wakir-persona: pin failed: {exc}", file=sys.stderr)
        return EXIT_PIN_FAILED

    try:
        persona_hash = compute_persona_hash_from_canonical(canonical_subset)
    except (ValueError, TypeError) as exc:
        # Defensive belt: JCS canonicalisation should never fail on a
        # successfully-extracted canonical subset, but a hand-built
        # non-canonical input could still trip the type / value guards.
        print(f"wakir-persona: pin failed: {exc}", file=sys.stderr)
        return EXIT_PIN_FAILED

    # Minimal-footprint stdout: just the pin + newline. No JSON, no
    # canonical-subset echo. This is the load-bearing distinction from
    # `inspect`; see V-907-CLI-invariant in the docstring.
    print(persona_hash, file=sys.stdout)

    if not args.quiet:
        print(
            f"wakir-persona: pinned {persona_file} -> {persona_hash}",
            file=sys.stderr,
        )

    return 0


def _resolve_heartbeat_dir(cli_override: Path | None) -> Path:
    """Resolve the heartbeat-directory per precedence rules.

    Precedence (highest to lowest):

    1. ``--heartbeat-dir <path>`` CLI flag.
    2. ``$WAKIR_PERSONA_HEARTBEAT_DIR`` environment variable.
    3. :data:`DEFAULT_HEARTBEAT_DIR` (``/var/run/wakir-persona``).

    Returns a :class:`Path` without doing any existence check —
    callers handle ``EXIT_INPUT_NOT_FOUND`` mapping themselves.
    """
    if cli_override is not None:
        return cli_override
    env_value = os.environ.get(HEARTBEAT_DIR_ENV_VAR)
    if env_value:
        return Path(env_value)
    return DEFAULT_HEARTBEAT_DIR


def _read_heartbeat_file(path: Path) -> dict:
    """Read and structurally validate a single heartbeat-state file.

    Raises :class:`ValueError` on (a) JSON parse failure, (b) the
    top-level value not being an object, or (c) any required key
    from :data:`HEARTBEAT_REQUIRED_KEYS` missing. The caller maps
    :class:`ValueError` to exit-code
    :data:`EXIT_HEARTBEAT_PARSE_FAILED`.

    Returns the parsed dict augmented with the V-907 drift verdict:
    ``v907_drift_detected = (current is not None and expected is
    not None and current != expected)``. The drift verdict is
    derived by the read-side rather than written by the engine so
    a single source of truth lives in the CLI (the engine writes
    the two pins; the CLI computes the comparison). Motivated by
    ADR-0058 §156.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"heartbeat-file vanished mid-run: {exc}") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"heartbeat-file {path} top-level is not an object: "
            f"got {type(payload).__name__}"
        )

    missing = HEARTBEAT_REQUIRED_KEYS - set(payload.keys())
    if missing:
        # Sort for deterministic error message — important for
        # test pinning and operator-readable diagnostics.
        raise ValueError(
            f"heartbeat-file {path} missing required keys: "
            f"{sorted(missing)}"
        )

    # Defensive: an FSM-state outside the canonical set is not an
    # error (the engine may add states ahead of the CLI knowing
    # about them) but we still anchor the canonical set as a
    # constant for governance / dashboards. Drift verdict below.
    current = payload.get("v907_pin_current")
    expected = payload.get("v907_pin_expected")
    drift = (
        current is not None
        and expected is not None
        and current != expected
    )
    # Build a new dict in canonical key order rather than mutating
    # in place — keeps the JSON-serialisation byte-stable across
    # heartbeat-file write-side variation.
    return {
        "persona_slug": payload["persona_slug"],
        "fsm_state": payload["fsm_state"],
        "last_heartbeat_at": payload["last_heartbeat_at"],
        "v907_pin_current": current,
        "v907_pin_expected": expected,
        "v907_drift_detected": drift,
        "subscribe_loop_active": payload["subscribe_loop_active"],
        "uptime_seconds": payload["uptime_seconds"],
    }


def _enumerate_heartbeat_files(
    heartbeat_dir: Path, persona_slug: str | None
) -> list[Path]:
    """Enumerate heartbeat-state files in ``heartbeat_dir``.

    If ``persona_slug`` is given, return ``[<dir>/<slug>.heartbeat.
    json]`` (single-entry list, existence check by the caller).
    Otherwise return *all* ``*.heartbeat.json`` files in the
    directory, sorted by filename for byte-stable output ordering.
    """
    if persona_slug is not None:
        return [heartbeat_dir / f"{persona_slug}{HEARTBEAT_FILENAME_SUFFIX}"]
    return sorted(heartbeat_dir.glob(f"*{HEARTBEAT_FILENAME_SUFFIX}"))


def _build_heartbeat_report(reports: list[dict]) -> dict:
    """Assemble the ``persona-heartbeat-v1`` report envelope.

    Wraps the per-persona reports in a top-level envelope so the
    JSON shape is forward-compatible with envelope-level metadata
    (e.g. report-generated-at timestamp) we may add in a future
    schema-version. Keys:

    - ``personas``: list of per-persona report dicts, ordered by
      ``persona_slug`` for byte-stable cross-invocation parity.
    - ``report_schema_version``: ``"persona-heartbeat-v1"``.
    """
    return {
        "personas": sorted(reports, key=lambda r: r["persona_slug"]),
        "report_schema_version": PERSONA_HEARTBEAT_REPORT_SCHEMA_VERSION,
    }


def _serialise_heartbeat_report(report_dict: dict) -> str:
    """Serialise the heartbeat-report dict for stdout.

    Sorted keys + two-space indent + trailing newline. Identical
    posture to :func:`_serialise_inspect_report` so the same
    Rust ↔ Python byte-stability harness applies to the heartbeat
    report once the Phase-1c Rust mirror is built.
    """
    return json.dumps(report_dict, indent=2, sort_keys=True) + "\n"


def _format_heartbeat_summary(reports: list[dict]) -> str:
    """Render a human-readable tabular summary of the heartbeat reports.

    One line per persona-slug. Column-aligned. NOT byte-stable
    across releases (column widths may shift); operators use this
    for `watch`-style interactive monitoring, not for CI / parsers.

    Empty-list input renders a one-line ``<no personas>`` marker
    so the operator sees a clear "directory is empty" verdict
    instead of an empty stdout.
    """
    if not reports:
        return "<no personas>\n"

    header = (
        "PERSONA               FSM_STATE     "
        "LAST_HEARTBEAT_AT             "
        "V907_DRIFT  SUB_LOOP  UPTIME_S\n"
    )
    lines = [header]
    for r in sorted(reports, key=lambda r: r["persona_slug"]):
        slug = str(r["persona_slug"])[:20].ljust(20)
        fsm = str(r["fsm_state"])[:12].ljust(12)
        lhb_raw = r["last_heartbeat_at"]
        lhb = (str(lhb_raw) if lhb_raw is not None else "<never>")[:28].ljust(28)
        drift = "yes" if r["v907_drift_detected"] else "no"
        drift_col = drift.ljust(10)
        sub = "yes" if r["subscribe_loop_active"] else "no"
        sub_col = sub.ljust(8)
        uptime_raw = r["uptime_seconds"]
        uptime = str(uptime_raw) if uptime_raw is not None else "<unknown>"
        lines.append(
            f"{slug}  {fsm}  {lhb}  {drift_col}  {sub_col}  {uptime}\n"
        )
    return "".join(lines)


def _run_inspect_heartbeat(args: argparse.Namespace) -> int:
    """Execute the ``inspect-heartbeat`` subcommand. Return a Unix exit code.

    Read-only inspection of the runtime heartbeat substrate.
    Failure modes:

    - heartbeat-dir not found -> :data:`EXIT_INPUT_NOT_FOUND` (3)
    - ``--persona <slug>`` requested but the per-slug file does
      not exist -> :data:`EXIT_INPUT_NOT_FOUND` (3)
    - a heartbeat-state JSON file is malformed or missing required
      keys -> :data:`EXIT_HEARTBEAT_PARSE_FAILED` (1)

    The structured report itself is the verdict for drift detection;
    the exit code does NOT branch on ``v907_drift_detected`` (motivated
    by ADR-0058: drift is a known runtime condition that should be
    surfaced for downstream tooling to decide on, not a hard CLI
    failure).
    """
    heartbeat_dir = _resolve_heartbeat_dir(args.heartbeat_dir)

    if not heartbeat_dir.exists():
        print(
            f"wakir-persona: heartbeat-dir not found: {heartbeat_dir}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    files = _enumerate_heartbeat_files(heartbeat_dir, args.persona)

    # `--persona <slug>` requested but the per-slug file is missing.
    # Anchored as a distinct error path from "directory empty"
    # because the operator's mental model is different: asking for
    # a specific persona that does not exist is a usage error
    # (typo? not-yet-spawned?), whereas the all-personas scope
    # legitimately returns an empty list on a freshly-booted
    # substrate.
    if args.persona is not None and not files[0].exists():
        print(
            f"wakir-persona: heartbeat-file not found for persona "
            f"{args.persona!r}: {files[0]}",
            file=sys.stderr,
        )
        return EXIT_INPUT_NOT_FOUND

    reports: list[dict] = []
    for path in files:
        if not path.exists():
            # Glob-result-mid-run race: skip silently. The next tick
            # of `watch inspect-heartbeat` will re-enumerate.
            continue
        try:
            reports.append(_read_heartbeat_file(path))
        except ValueError as exc:
            print(
                f"wakir-persona: inspect-heartbeat parse failed: {exc}",
                file=sys.stderr,
            )
            return EXIT_HEARTBEAT_PARSE_FAILED

    if args.output_format == "summary":
        sys.stdout.write(_format_heartbeat_summary(reports))
    else:
        report = _build_heartbeat_report(reports)
        sys.stdout.write(_serialise_heartbeat_report(report))

    if not args.quiet:
        # Verdict-aware progress line: count + drift summary so an
        # interactive operator gets the answer without parsing JSON.
        drift_count = sum(1 for r in reports if r["v907_drift_detected"])
        scope = (
            f"persona={args.persona!r}"
            if args.persona is not None
            else f"all personas (n={len(reports)})"
        )
        verdict = (
            f"{drift_count} drift" if drift_count else "no drift"
        )
        print(
            f"wakir-persona: inspect-heartbeat {scope} -> {verdict}",
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
    if args.command == "pin":
        return _run_pin(args)
    if args.command == "inspect-heartbeat":
        return _run_inspect_heartbeat(args)

    # argparse with required=True on the subparser dest already
    # rejects unknown commands with exit code 2 from argparse's
    # error handler; this branch is defensive belt against future
    # subcommand additions that forget the dispatch wiring.
    parser.error(f"unknown command: {args.command!r}")
    return 64  # unreachable, parser.error raises SystemExit


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
