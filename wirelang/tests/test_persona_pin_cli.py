# SPDX-License-Identifier: Apache-2.0
"""Operator CLI test pack for ``wakir-persona pin`` (Phase-1b
Sprint-6 Tag-4).

Covers the ``pin`` subcommand declared in :mod:`wirelang.persona.cli`.
The subcommand is a minimal-footprint shell-pipeline wrapper around
:func:`wirelang.persona.persona_canonical_form.read_canonical_subset`
plus :func:`wirelang.persona.compute_persona_hash_from_canonical` —
strict subset of ``inspect`` (no JSON envelope, no canonical-subset
echo) optimised for ``pin=$(wakir-persona pin file.md)`` capture.

Pin posture (vs. migrate / validate / inspect)
==============================================

- **migrate**: applies the registered migration chain. stdout = JSON.
- **validate**: structured validator; stdout = JSON report.
- **inspect**: read-only; stdout = ``PersonaInspectReport`` JSON.
  ``--emit-hash`` routes the pin to **stderr** (stdout stays the
  JSON envelope).
- **pin**: read-only; stdout = the V-907 persona-hash, one line,
  ``sha256:<64hex>\\n``. Nothing else. Failure semantics identical
  to ``inspect`` (exit 1 on extractor failure, exit 3 on missing
  file). The stdout-vs-stderr swap is the load-bearing distinction:
  ``pin=$(wakir-persona pin f.md)`` works as a one-liner without
  ``2>&1`` redirect gymnastics.

V-907-CLI-invariant
===================

For a v9 (no-op-chain) input:

    pin stdout
        == inspect --emit-hash --quiet stderr-pin
        == migrate --emit-hash stderr-last-line
        == PERSONA_HASH_PIN_V9

Coverage
========

- argparse surface (parser construction, ``pin`` subcommand
  argument shape, ``--quiet`` flag default, rejection of
  migrate-only / inspect-only flags)
- exit-code mapping (0 on extract-success, 1 on extract-failure,
  3 on missing file, 64 on argparse usage error)
- stdout shape: exactly one line, ``sha256:<64hex>\\n``, nothing else
- ``--quiet`` flag suppression (no progress line on stderr)
- progress line shape when not ``--quiet``
- V8 failure path (schema_version=persona-v0 is rejected by the
  canonical-subset extractor)
- byte-identity anchor: V9 stdout matches the frozen Rust-side
  pin fixture byte-for-byte (cross-language anchor)
- V-907-CLI-invariant: pin stdout == inspect --emit-hash --quiet
  stderr-pin == migrate --emit-hash stderr-last-line

Cross-language byte-parity with the Rust ``persona-cli`` crate is
anchored via the ``v1-pin.expected.txt`` / ``v9-pin.expected.txt``
fixtures under ``wirelang-rust/crates/persona-cli/tests/fixtures/``
— both the Python pack and the Rust pack assert byte-equality
against the same files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wirelang.persona.cli import (
    EXIT_INPUT_NOT_FOUND,
    EXIT_PIN_FAILED,
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
# loads via `include_str!`. The Sprint-6 Tag-4 byte-identity contract
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


def test_build_parser_accepts_pin_subcommand():
    """The ``pin`` subcommand is registered alongside migrate /
    validate / inspect."""
    parser = build_parser()
    namespace = parser.parse_args(["pin", str(V9_FIXTURE)])
    assert namespace.command == "pin"
    assert namespace.persona_file == V9_FIXTURE
    # Only --quiet is shared with the other subcommands; default
    # False mirrors migrate / validate / inspect.
    assert namespace.quiet is False


def test_build_parser_pin_subcommand_quiet_flag_parses():
    parser = build_parser()
    namespace = parser.parse_args(["pin", str(V9_FIXTURE), "--quiet"])
    assert namespace.command == "pin"
    assert namespace.quiet is True


def test_build_parser_pin_subcommand_rejects_emit_hash_flag():
    """``--emit-hash`` belongs to migrate / inspect; pin must reject it.

    Rationale: ``pin`` already emits the pin on stdout — an
    ``--emit-hash`` flag would be redundant noise. Keeping the surface
    closed prevents accidental flag-overload as the subcommand grows.
    """
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["pin", str(V9_FIXTURE), "--emit-hash"])


def test_build_parser_pin_subcommand_rejects_target_flag():
    """``--target`` belongs to migrate; pin must reject it."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["pin", str(V9_FIXTURE), "--target", "persona-v2"])


def test_build_parser_pin_subcommand_rejects_expect_hash_flag():
    """``--expect-hash`` belongs to migrate; pin must reject it."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["pin", str(V9_FIXTURE), "--expect-hash", PERSONA_HASH_PIN_V9]
        )


# ---------------------------------------------------------------------------
# Happy path: pin v9 -> success, exit 0, stdout = pin + newline
# ---------------------------------------------------------------------------


def test_pin_v9_returns_exit_code_0_and_pin_on_stdout(
    capsys: pytest.CaptureFixture[str],
):
    """V9 is a clean persona-v1 fixture; pin emits ``sha256:<64hex>\\n``
    on stdout and nothing else (with ``--quiet``)."""
    rc = main(["pin", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == f"{PERSONA_HASH_PIN_V9}\n", (
        f"stdout must be exactly the V9 pin + newline; got: {captured.out!r}"
    )
    # --quiet suppresses the progress line.
    assert captured.err == ""


def test_pin_v9_stdout_is_single_line_pin_only(
    capsys: pytest.CaptureFixture[str],
):
    """stdout shape: exactly one non-empty line, exactly the pin.

    Defensive belt against future "helpful" additions that would break
    ``pin=$(wakir-persona pin f.md)`` capture (e.g. accidental BOM,
    trailing whitespace, second newline).
    """
    rc = main(["pin", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    lines = captured.out.splitlines()
    assert len(lines) == 1, (
        f"stdout must be exactly one line; got {len(lines)}: {captured.out!r}"
    )
    assert lines[0] == PERSONA_HASH_PIN_V9
    assert captured.out.endswith("\n"), "stdout must terminate with \\n"


def test_pin_v9_stdout_has_no_json_envelope(
    capsys: pytest.CaptureFixture[str],
):
    """The load-bearing distinction from ``inspect``: no JSON.

    Pinning a regression here is what keeps the ``pin`` subcommand
    valuable as a shell-pipeline primitive: the moment stdout starts
    carrying JSON, the operator's ``$()`` capture breaks and they
    might as well use ``inspect --emit-hash --quiet 2>&1 >/dev/null``.
    """
    rc = main(["pin", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    # No JSON markers in stdout.
    assert "{" not in captured.out
    assert "}" not in captured.out
    assert "canonical_subset" not in captured.out
    assert "report_schema_version" not in captured.out


# ---------------------------------------------------------------------------
# Failure path: pin v8 -> schema_version=persona-v0 rejected, exit 1
# ---------------------------------------------------------------------------


def test_pin_v8_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
):
    """V8 carries schema_version=persona-v0; canonical-subset extractor
    rejects it. Pin is a read-only surface — it does not auto-migrate
    (use ``wakir-persona migrate`` for that)."""
    rc = main(["pin", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == EXIT_PIN_FAILED == 1
    # No stdout on the failure path; diagnostic goes to stderr.
    assert captured.out == ""
    assert "wakir-persona: pin failed" in captured.err
    assert "persona-v0" in captured.err


# ---------------------------------------------------------------------------
# Progress line on stderr when not --quiet
# ---------------------------------------------------------------------------


def test_pin_v9_progress_line_when_not_quiet(
    capsys: pytest.CaptureFixture[str],
):
    """Progress line on stderr carries the persona-hash; stdout
    remains exactly the pin."""
    rc = main(["pin", str(V9_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    # stdout is still just the pin (progress line goes to stderr).
    assert captured.out == f"{PERSONA_HASH_PIN_V9}\n"
    assert "wakir-persona: pinned" in captured.err
    assert PERSONA_HASH_PIN_V9 in captured.err
    assert str(V9_FIXTURE) in captured.err


# ---------------------------------------------------------------------------
# Missing-file path
# ---------------------------------------------------------------------------


def test_pin_missing_file_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["pin", "/var/empty/this-file-does-not-exist.md"])
    captured = capsys.readouterr()
    assert rc == EXIT_INPUT_NOT_FOUND == 3
    assert "not found" in captured.err
    # stdout stays empty so a downstream `$()` capture sees an empty
    # string rather than a stale partial value.
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Byte-identity anchors: V9 / V1 stdout matches the frozen Rust-side
# fixture byte-for-byte. Same fixture is loaded by Rust via
# `include_str!`. A drift on either side breaks the matching test on
# the other side.
# ---------------------------------------------------------------------------


def test_pin_v9_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V9 pin-stdout matches ``v9-pin.expected.txt`` byte-for-byte.
    Byte-identity anchor in the V-907-anchor pin-pack (Tag-4 entry).
    """
    rc = main(["pin", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    expected_path = RUST_FIXTURE_DIR / "v9-pin.expected.txt"
    expected = expected_path.read_text(encoding="utf-8")
    assert captured.out == expected, (
        "pin stdout drifted from the cross-language frozen fixture; "
        "Rust + Python diverged on the V9 anchor"
    )


def test_pin_v1_stdout_byte_identical_to_frozen_fixture(
    capsys: pytest.CaptureFixture[str],
):
    """V1 pin-stdout matches ``v1-pin.expected.txt`` byte-for-byte.

    Second byte-identity anchor (different name / description /
    tools list than V9) so a regression on a non-V9 canonical-subset
    shape also trips.
    """
    rc = main(["pin", str(V1_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    expected_path = RUST_FIXTURE_DIR / "v1-pin.expected.txt"
    expected = expected_path.read_text(encoding="utf-8")
    assert captured.out == expected, (
        "pin stdout drifted from the cross-language frozen fixture; "
        "Rust + Python diverged on the V1 anchor"
    )


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_pin_v9_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    """Two invocations yield byte-identical stdout (no global state
    leak, no time-dependent serialisation)."""
    rc1 = main(["pin", str(V9_FIXTURE), "--quiet"])
    out1 = capsys.readouterr().out
    rc2 = main(["pin", str(V9_FIXTURE), "--quiet"])
    out2 = capsys.readouterr().out
    assert rc1 == rc2 == 0
    assert out1 == out2


def test_pin_v1_idempotent_stdout(
    capsys: pytest.CaptureFixture[str],
):
    """Idempotence on the V1 anchor too (second-anchor surface)."""
    rc1 = main(["pin", str(V1_FIXTURE), "--quiet"])
    out1 = capsys.readouterr().out
    rc2 = main(["pin", str(V1_FIXTURE), "--quiet"])
    out2 = capsys.readouterr().out
    assert rc1 == rc2 == 0
    assert out1 == out2


# ---------------------------------------------------------------------------
# V-907-CLI-invariant: pin stdout == inspect --emit-hash --quiet
# stderr-pin == migrate --emit-hash stderr-last-line, all for a v9
# (no-op-chain) input.
# ---------------------------------------------------------------------------


def test_pin_stdout_matches_inspect_emit_hash_stderr_v9(
    capsys: pytest.CaptureFixture[str],
):
    """V-907-CLI-invariant arm 1: pin stdout equals inspect
    --emit-hash --quiet stderr-pin (without trailing newline noise)."""
    rc_pin = main(["pin", str(V9_FIXTURE), "--quiet"])
    pin_out = capsys.readouterr().out
    rc_inspect = main(["inspect", str(V9_FIXTURE), "--quiet", "--emit-hash"])
    inspect_err = capsys.readouterr().err
    assert rc_pin == rc_inspect == 0
    pin_value = pin_out.strip()
    # inspect's stderr is exactly the pin + newline.
    inspect_pin = inspect_err.strip()
    assert pin_value == inspect_pin == PERSONA_HASH_PIN_V9


def test_pin_stdout_matches_migrate_emit_hash_stderr_v9(
    capsys: pytest.CaptureFixture[str],
):
    """V-907-CLI-invariant arm 2: pin stdout equals migrate
    --emit-hash stderr-last-line (V9 is already persona-v1, so the
    migration chain is a no-op and the post-migrate hash equals
    the canonical-subset hash that pin emits)."""
    rc_pin = main(["pin", str(V9_FIXTURE), "--quiet"])
    pin_out = capsys.readouterr().out
    rc_migrate = main(["migrate", str(V9_FIXTURE), "--quiet", "--emit-hash"])
    migrate_err = capsys.readouterr().err
    assert rc_pin == rc_migrate == 0
    pin_value = pin_out.strip()
    # migrate's stderr last non-empty line is the pin.
    migrate_lines = [
        line for line in migrate_err.splitlines() if line.strip()
    ]
    assert migrate_lines, "migrate --emit-hash must emit a pin line"
    migrate_pin = migrate_lines[-1]
    assert pin_value == migrate_pin == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------------------
# Backward compatibility: the existing subcommands still work after
# the pin subcommand was added.
# ---------------------------------------------------------------------------


def test_migrate_subcommand_still_works_after_pin_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sanity check: adding ``pin`` did not break ``migrate``."""
    rc = main(["migrate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    # V9 migrates v1 -> v1 (no-op chain); stdout is the canonical
    # subset JSON.
    assert '"schema_version": "persona-v1"' in captured.out


def test_validate_subcommand_still_works_after_pin_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sanity check: adding ``pin`` did not break ``validate``."""
    rc = main(["validate", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert '"is_valid": true' in captured.out


def test_inspect_subcommand_still_works_after_pin_added(
    capsys: pytest.CaptureFixture[str],
):
    """Sanity check: adding ``pin`` did not break ``inspect``."""
    rc = main(["inspect", str(V9_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert '"report_schema_version": "persona-inspect-v1"' in captured.out
    assert f'"persona_hash": "{PERSONA_HASH_PIN_V9}"' in captured.out
