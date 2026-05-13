# SPDX-License-Identifier: Apache-2.0
"""Operator CLI test pack for ``wakir-persona inspect`` (Phase-1b
Sprint-6 Tag-3).

Covers the ``inspect`` subcommand declared in
:mod:`wirelang.persona.cli`. The subcommand is a thin wrapper around
:func:`wirelang.persona.persona_canonical_form.read_canonical_subset`
plus :func:`wirelang.persona.compute_persona_hash_from_canonical`.

Inspect posture (vs. migrate / validate)
========================================

- **migrate**: applies the registered migration chain. Writes the
  migrated canonical subset on stdout.
- **validate**: runs the structured validator (errors -> report).
  Writes a ``PersonaValidationReport`` on stdout, exit-codes the
  ``is_valid`` flag.
- **inspect**: pure read-only, no migration, no validation. Writes
  a ``PersonaInspectReport`` = ``{canonical_subset, persona_hash,
  report_schema_version}`` on stdout. Failure on this surface means
  the file is unreadable as a canonical subset (missing front-matter,
  schema_version unsupported, ...) -> exit 1.

Coverage
========

- argparse surface (parser construction, ``inspect`` subcommand
  argument shape, ``--quiet`` and ``--emit-hash`` flag defaults)
- exit-code mapping (0 on extract-success, 1 on extract-failure, 3
  on missing file, 64 on argparse usage error)
- stdout JSON shape (the ``PersonaInspectReport`` serialised with
  sorted keys, two-space indent, trailing newline)
- ``--quiet`` flag suppression (no progress line on stderr)
- ``--emit-hash`` writes the V-907 pin to stderr in
  ``sha256:<64hex>`` form
- progress line shape when not ``--quiet``
- non-existent-file path
- V8 failure path (schema_version=persona-v0 is rejected by the
  canonical-subset extractor)
- byte-identity anchor: V9 stdout matches the frozen Rust-side
  fixture byte-for-byte (cross-language anchor)

Cross-language byte-parity with the Rust ``persona-cli`` crate is
anchored via the ``v1-inspected.expected.json`` /
``v9-inspected.expected.json`` fixtures under
``wirelang-rust/crates/persona-cli/tests/fixtures/`` — both the
Python pack and the Rust pack assert byte-equality against the same
files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Skip the whole module when rfc8785 is absent: the wirelang.persona
# package imports rfc8785 unconditionally at module-load time, so any
# top-level `from wirelang.persona ...` below would crash collection
# in the sandbox lane. Test-level importorskip is the conventional
# guard for this case until the persona package adopts a lazy import.
pytest.importorskip("rfc8785")

from wirelang.persona.cli import (
    EXIT_INPUT_NOT_FOUND,
    EXIT_INSPECT_FAILED,
    PERSONA_INSPECT_REPORT_SCHEMA_VERSION,
    build_parser,
    main,
)
from wirelang.persona._internal.pin_pack_constants import PERSONA_HASH_PIN_V9


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "persona_definitions"
)
V1_FIXTURE = FIXTURE_DIR / "v1-persona-ceo.md"
V8_FIXTURE = FIXTURE_DIR / "v8-persona-pre-framework.md"
V9_FIXTURE = FIXTURE_DIR / "v9-persona-framework-native.md"

# Cross-language byte-fixture root — same path the Rust test pack
# loads via `include_str!`. The Sprint-6 Tag-3 byte-identity contract
# pins V1 + V9 stdout on both sides.
RUST_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "wirelang-rust"
    / "crates"
    / "persona-cli"
    / "tests"
    / "fixtures"
)


# ---------------------------------------------------------------------------
# Parser surface
# ---------------------------------------------------------------------------


def test_build_parser_accepts_inspect_subcommand():
    """The ``inspect`` subcommand is registered alongside migrate / validate."""
    parser = build_parser()
    namespace = parser.parse_args(["inspect", str(V9_FIXTURE)])
    assert namespace.command == "inspect"
    assert namespace.persona_file == V9_FIXTURE
    # Flags default to False (parity with migrate / validate).
    assert namespace.quiet is False
    assert namespace.emit_hash is False


def test_build_parser_inspect_subcommand_quiet_flag_parses():
    parser = build_parser()
    namespace = parser.parse_args(["inspect", str(V9_FIXTURE), "--quiet"])
    assert namespace.command == "inspect"
    assert namespace.quiet is True


def test_build_parser_inspect_subcommand_emit_hash_flag_parses():
    parser = build_parser()
    namespace = parser.parse_args(["inspect", str(V9_FIXTURE), "--emit-hash"])
    assert namespace.command == "inspect"
    assert namespace.emit_hash is True


def test_build_parser_inspect_subcommand_rejects_unknown_flag():
    """``--target`` belongs to migrate; inspect must reject it."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["inspect", str(V9_FIXTURE), "--target", "persona-v2"]
        )


def test_build_parser_inspect_subcommand_rejects_expect_hash_flag():
    """``--expect-hash`` belongs to migrate; inspect must reject it.

    Rationale: inspect is read-only; if the operator wants to assert
    a pin they can capture stderr from ``--emit-hash`` and compare
    in shell, or use ``migrate --expect-hash`` to combine the
    extract + pin-check + migrate in one shot.
    """
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["inspect", str(V9_FIXTURE), "--expect-hash", PERSONA_HASH_PIN_V9]
        )


# ---------------------------------------------------------------------------
# Happy path: inspect v9 -> success, exit 0, report carries V9 pin
# ---------------------------------------------------------------------------


def test_inspect_v9_returns_exit_code_0_and_report(
    capsys: pytest.CaptureFixture[str],
):
    """V9 is a clean persona-v1 fixture; inspect extracts cleanly."""
    rc = main(["inspect", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["report_schema_version"] == PERSONA_INSPECT_REPORT_SCHEMA_VERSION
    assert payload["report_schema_version"] == "persona-inspect-v1"
    assert payload["persona_hash"] == PERSONA_HASH_PIN_V9
    # canonical_subset top-level keys: name, description, tools,
    # schema_version, identity_pinned.
    canonical = payload["canonical_subset"]
    assert canonical["schema_version"] == "persona-v1"
    assert canonical["name"] == "pre-framework-agent"
    assert isinstance(canonical["tools"], list)
    assert "identity_pinned" in canonical
    # --quiet suppresses the progress line.
    assert captured.err == ""


def test_inspect_v9_stdout_sorted_and_newline_terminated(
    capsys: pytest.CaptureFixture[str],
):
    """stdout JSON has lexical key order and terminates with ``\\n``.

    Top-level keys in lexical order: ``canonical_subset`` < ``persona_hash``
    < ``report_schema_version``.
    """
    rc = main(["inspect", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.endswith("\n"), "stdout must end with newline"
    cs_pos = captured.out.find('"canonical_subset"')
    ph_pos = captured.out.find('"persona_hash"')
    rsv_pos = captured.out.find('"report_schema_version"')
    assert 0 <= cs_pos < ph_pos < rsv_pos, (
        "expected sorted key order; got "
        f"cs@{cs_pos} ph@{ph_pos} rsv@{rsv_pos}"
    )


# ---------------------------------------------------------------------------
# Failure path: inspect v8 -> schema_version=persona-v0 rejected, exit 1
# ---------------------------------------------------------------------------


def test_inspect_v8_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
):
    """V8 carries schema_version=persona-v0; canonical-subset extractor
    rejects it. Inspect is a read-only surface — it does not auto-
    migrate (use ``wakir-persona migrate`` for that)."""
    rc = main(["inspect", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_INSPECT_FAILED == 1
    # No stdout on the failure path; diagnostic goes to stderr.
    assert captured.out == ""
    assert "wakir-persona: inspect failed" in captured.err
    assert "persona-v0" in captured.err


# ---------------------------------------------------------------------------
# --emit-hash: writes V-907 pin to stderr
# ---------------------------------------------------------------------------


def test_inspect_v9_emit_hash_writes_pin_to_stderr(
    capsys: pytest.CaptureFixture[str],
):
    """``--emit-hash`` emits the V-907 pin on stderr, mirror of
    ``migrate --emit-hash``."""
    rc = main(["inspect", str(V9_FIXTURE), "--quiet", "--emit-hash"])
    captured = capsys.readouterr()
    assert rc == 0
    # Stderr is exactly the pin (newline-terminated).
    nonempty = [line for line in captured.err.splitlines() if line.strip()]
    assert nonempty == [PERSONA_HASH_PIN_V9], (
        f"stderr must be exactly the V9 pin; got: {captured.err!r}"
    )
    # The pin in stdout must equal the pin emitted on stderr (single
    # source of truth — both come from the same compute call).
    payload = json.loads(captured.out)
    assert payload["persona_hash"] == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------------------
# Progress line on stderr when not --quiet
# ---------------------------------------------------------------------------


def test_inspect_v9_progress_line_when_not_quiet(
    capsys: pytest.CaptureFixture[str],
):
    """Progress line on stderr carries the persona-hash."""
    rc = main(["inspect", str(V9_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "wakir-persona: inspected" in captured.err
    assert PERSONA_HASH_PIN_V9 in captured.err


# ---------------------------------------------------------------------------
# Missing-file path
# ---------------------------------------------------------------------------


def test_inspect_missing_file_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["inspect", "/var/empty/this-file-does-not-exist.md"])
    captured = capsys.readouterr()
    assert rc == EXIT_INPUT_NOT_FOUND == 3
    assert "not found" in captured.err


# ---------------------------------------------------------------------------
# Byte-identity anchors: V9 stdout matches the frozen Rust-side fixture
# byte-for-byte. Same fixture is loaded by Rust via `include_str!`. A
# drift on either side breaks the matching test on the other side.
# ---------------------------------------------------------------------------


def test_inspect_v9_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V9 inspect-stdout matches ``v9-inspected.expected.json`` byte-
    for-byte. Byte-identity anchor V10 in the V-907-anchor pin-pack."""
    rc = main(["inspect", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    expected = (RUST_FIXTURE_DIR / "v9-inspected.expected.json").read_text(
        encoding="utf-8"
    )
    assert captured.out == expected, (
        "Python inspect stdout drifted from frozen "
        "v9-inspected.expected.json"
    )


def test_inspect_v1_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V1 inspect-stdout matches ``v1-inspected.expected.json`` byte-
    for-byte. Second byte-identity anchor (V11 in the V-907 pin-pack)
    so a regression on a non-V9 canonical-subset shape (different
    name, description, tools list) also trips."""
    rc = main(["inspect", str(V1_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    expected = (RUST_FIXTURE_DIR / "v1-inspected.expected.json").read_text(
        encoding="utf-8"
    )
    assert captured.out == expected, (
        "Python inspect stdout drifted from frozen "
        "v1-inspected.expected.json"
    )


# ---------------------------------------------------------------------------
# Idempotence: inspect is a pure read; a second invocation returns
# byte-identical stdout.
# ---------------------------------------------------------------------------


def test_inspect_v9_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    """Two back-to-back inspect calls yield byte-identical stdout."""
    main(["inspect", str(V9_FIXTURE), "--quiet"])
    first = capsys.readouterr().out
    main(["inspect", str(V9_FIXTURE), "--quiet"])
    second = capsys.readouterr().out
    assert first == second


def test_inspect_v1_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    main(["inspect", str(V1_FIXTURE), "--quiet"])
    first = capsys.readouterr().out
    main(["inspect", str(V1_FIXTURE), "--quiet"])
    second = capsys.readouterr().out
    assert first == second


# ---------------------------------------------------------------------------
# Cross-subcommand consistency: inspect's persona_hash equals migrate's
# --emit-hash output on the same fixture (V-907 invariant).
# ---------------------------------------------------------------------------


def test_inspect_persona_hash_matches_migrate_emit_hash_v9(
    capsys: pytest.CaptureFixture[str],
):
    """V-907 invariant: inspect.persona_hash == migrate.--emit-hash for
    a v9 -> v1 no-op migration.

    The V9 fixture is already persona-v1, so the migration chain is
    a no-op; the post-migrate hash equals the canonical-subset hash
    that inspect emits.
    """
    main(["migrate", str(V9_FIXTURE), "--quiet", "--emit-hash"])
    migrate_stderr = capsys.readouterr().err
    migrate_pin = [
        line for line in migrate_stderr.splitlines() if line.strip()
    ][-1]
    main(["inspect", str(V9_FIXTURE), "--quiet"])
    inspect_stdout = capsys.readouterr().out
    inspect_payload = json.loads(inspect_stdout)
    assert inspect_payload["persona_hash"] == migrate_pin == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------------------
# Backward compatibility: migrate + validate subcommands still work
# after the inspect subcommand was added.
# ---------------------------------------------------------------------------


def test_migrate_subcommand_still_works_after_inspect_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sprint-6 Tag-3 must not regress the migrate subcommand."""
    rc = main(["migrate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v1"


def test_validate_subcommand_still_works_after_inspect_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sprint-6 Tag-3 must not regress the validate subcommand."""
    rc = main(["validate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["is_valid"] is True
