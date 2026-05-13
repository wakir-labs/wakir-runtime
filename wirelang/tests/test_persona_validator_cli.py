# SPDX-License-Identifier: Apache-2.0
"""Operator CLI test pack for ``wakir-persona validate`` (Phase-1b
Sprint-6 Tag-2).

Covers the ``validate`` subcommand declared in
:mod:`wirelang.persona.cli`. The subcommand is a thin wrapper around
:func:`wirelang.persona.validate_persona`; the bulk of defensive
coverage lives in ``test_persona_validator.py``. This pack focuses
on the CLI shim layer specifically:

- argparse surface (parser construction, ``validate`` subcommand
  argument shape, ``--quiet`` flag default)
- exit-code mapping (0 on ``is_valid``, 1 on ``not is_valid``, 3 on
  missing file, 64 on argparse usage error)
- stdout JSON shape (the ``PersonaValidationReport.to_canonical_dict()``
  serialised with sorted keys, two-space indent, trailing newline)
- ``--quiet`` flag suppression (no progress line on stderr)
- progress line shape when not ``--quiet`` (``valid`` vs
  ``invalid: N error(s)``)
- non-existent-file path

Cross-language byte-parity anchor with the Rust ``persona-cli``
crate is asserted in Rust-side tests (see
``wirelang-rust/crates/persona-cli/src/lib.rs`` ``validate_tests``
module); the expected-fixture JSON files in
``wirelang-rust/crates/persona-cli/tests/fixtures/`` are byte-frozen
copies of this CLI's stdout for V8 / V9 fixtures.
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
    EXIT_VALIDATION_FAILED,
    build_parser,
    main,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "persona_definitions"
)
V8_FIXTURE = FIXTURE_DIR / "v8-persona-pre-framework.md"
V9_FIXTURE = FIXTURE_DIR / "v9-persona-framework-native.md"


# ---------------------------------------------------------------------------
# Parser surface
# ---------------------------------------------------------------------------


def test_build_parser_accepts_validate_subcommand():
    """The ``validate`` subcommand is registered alongside ``migrate``."""
    parser = build_parser()
    namespace = parser.parse_args(["validate", str(V9_FIXTURE)])
    assert namespace.command == "validate"
    assert namespace.persona_file == V9_FIXTURE
    # --quiet defaults to False (parity with migrate subcommand).
    assert namespace.quiet is False


def test_build_parser_validate_subcommand_quiet_flag_parses():
    parser = build_parser()
    namespace = parser.parse_args(["validate", str(V9_FIXTURE), "--quiet"])
    assert namespace.command == "validate"
    assert namespace.quiet is True


def test_build_parser_validate_subcommand_rejects_unknown_flag():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["validate", str(V9_FIXTURE), "--target", "persona-v2"]
        )


# ---------------------------------------------------------------------------
# Happy path: validate v9 -> is_valid=True, exit 0
# ---------------------------------------------------------------------------


def test_validate_v9_returns_exit_code_0_and_valid_report(
    capsys: pytest.CaptureFixture[str],
):
    """V9 is a valid persona-v1 fixture; report.is_valid must be True."""
    rc = main(["validate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["is_valid"] is True
    assert payload["schema_version"] == "persona-v1"
    assert payload["schema_supported"] is True
    assert payload["errors"] == []
    assert payload["report_schema_version"] == "persona-validation-v1"
    # --quiet suppresses the progress line.
    assert captured.err == ""


def test_validate_v9_stdout_sorted_and_newline_terminated(
    capsys: pytest.CaptureFixture[str],
):
    """stdout JSON has lexical key order and terminates with ``\\n``."""
    rc = main(["validate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.endswith("\n"), "stdout must end with newline"
    # Top-level keys in lexical order. "errors" must precede "is_valid".
    errors_pos = captured.out.find('"errors"')
    is_valid_pos = captured.out.find('"is_valid"')
    assert 0 <= errors_pos < is_valid_pos, (
        f"expected sorted key order; got errors@{errors_pos} "
        f"is_valid@{is_valid_pos}"
    )


# ---------------------------------------------------------------------------
# Failure path: validate v8 -> is_valid=False, exit 1
# ---------------------------------------------------------------------------


def test_validate_v8_returns_exit_code_1_and_invalid_report(
    capsys: pytest.CaptureFixture[str],
):
    """V8 carries schema_version=persona-v0 which is unsupported."""
    rc = main(["validate", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_VALIDATION_FAILED == 1
    payload = json.loads(captured.out)
    assert payload["is_valid"] is False
    assert payload["schema_version"] == "persona-v0"
    assert payload["schema_supported"] is False
    assert len(payload["errors"]) == 1
    err = payload["errors"][0]
    assert err["code"] == "schema-version-unsupported"
    assert err["detail"] == "persona-v0"
    # --quiet suppresses the progress line.
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Progress line on stderr when not --quiet
# ---------------------------------------------------------------------------


def test_validate_v9_progress_line_when_not_quiet(
    capsys: pytest.CaptureFixture[str],
):
    """Progress line on stderr carries the ``valid`` verdict."""
    rc = main(["validate", str(V9_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "wakir-persona: validated" in captured.err
    assert "-> valid" in captured.err


def test_validate_v8_progress_line_carries_invalid_count(
    capsys: pytest.CaptureFixture[str],
):
    """Progress line on stderr counts the structured errors."""
    rc = main(["validate", str(V8_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == EXIT_VALIDATION_FAILED
    assert "wakir-persona: validated" in captured.err
    assert "-> invalid: 1 error(s)" in captured.err


# ---------------------------------------------------------------------------
# Missing-file path
# ---------------------------------------------------------------------------


def test_validate_missing_file_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["validate", "/var/empty/this-file-does-not-exist.md"])
    captured = capsys.readouterr()
    assert rc == EXIT_INPUT_NOT_FOUND == 3
    assert "not found" in captured.err


# ---------------------------------------------------------------------------
# Cross-language byte-parity anchor: stdout JSON for V9 matches the
# frozen Rust-side fixture (the same fixture is loaded by the Rust
# `persona-cli` test pack with `include_str!`). A drift on either side
# breaks the matching test on the other side.
# ---------------------------------------------------------------------------


# Rust-fixture-tree relative to this test file. Walking up via
# resolve().parents[N] avoids assumptions about cwd at pytest invocation.
RUST_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "wirelang-rust"
    / "crates"
    / "persona-cli"
    / "tests"
    / "fixtures"
)


def test_validate_v9_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V9 validator-stdout matches `v9-validated.expected.json` byte-
    for-byte. The fixture is the byte-parity anchor that the Rust
    `persona-cli` crate loads via `include_str!`; a drift here either
    means the Python CLI changed or the fixture needs re-freezing.
    """
    rc = main(["validate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    expected = (RUST_FIXTURE_DIR / "v9-validated.expected.json").read_text(
        encoding="utf-8"
    )
    assert captured.out == expected, (
        "Python validate stdout drifted from frozen v9-validated.expected.json"
    )


def test_validate_v8_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V8 validator-stdout matches `v8-validated.expected.json`
    byte-for-byte."""
    rc = main(["validate", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_VALIDATION_FAILED
    expected = (RUST_FIXTURE_DIR / "v8-validated.expected.json").read_text(
        encoding="utf-8"
    )
    assert captured.out == expected, (
        "Python validate stdout drifted from frozen v8-validated.expected.json"
    )


# ---------------------------------------------------------------------------
# Idempotence: validate is a pure read; a second invocation returns
# byte-identical stdout.
# ---------------------------------------------------------------------------


def test_validate_v9_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    """Two back-to-back validate calls yield byte-identical stdout."""
    main(["validate", str(V9_FIXTURE), "--quiet"])
    first = capsys.readouterr().out
    main(["validate", str(V9_FIXTURE), "--quiet"])
    second = capsys.readouterr().out
    assert first == second


def test_validate_v8_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    main(["validate", str(V8_FIXTURE), "--quiet"])
    first = capsys.readouterr().out
    main(["validate", str(V8_FIXTURE), "--quiet"])
    second = capsys.readouterr().out
    assert first == second


# ---------------------------------------------------------------------------
# Backward compatibility: existing migrate subcommand still works after
# the validate subcommand was added.
# ---------------------------------------------------------------------------


def test_migrate_subcommand_still_works_after_validate_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sprint-6 Tag-2 must not regress the migrate subcommand."""
    rc = main(["migrate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v1"
