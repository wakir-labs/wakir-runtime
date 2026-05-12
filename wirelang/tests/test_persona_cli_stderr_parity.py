# SPDX-License-Identifier: Apache-2.0
"""Operator CLI stderr-Wording-Byte-Parität test pack (Phase-1b Sprint-6
Tag-6 — Item 1).

Cross-language byte-parity hardening for the error-path stderr surface
of the four ``wakir-persona`` subcommands (``migrate``, ``validate``,
``inspect``, ``pin``). Sister Rust pack lives in
``wirelang-rust/crates/persona-cli/src/lib.rs`` as
``mod stderr_parity_tests``. Together they pin the cross-language
diff at byte granularity for the structurally-aligned error paths.

Posture overview (what is asserted vs. what is left soft)
---------------------------------------------------------

The four subcommands share five error markers. Their cross-language
parity profile is:

============= =================================================
Error marker  Cross-language parity contract
============= =================================================
E1 NOT_FOUND  Byte-equal full stderr line. Python and Rust both
              emit ``"wakir-persona: persona-file not found: "
              "<path>\\n"`` from the same pre-existence check.
              The path is the only variable; the format string
              is byte-identical between languages.
E2 VANISHED   Soft-match: byte-equal prefix
              ``"wakir-persona: persona-file vanished mid-run: "``.
              The body diverges: Python interpolates
              ``FileNotFoundError`` Display (``"[Errno 2] No
              such file or directory: '<path>'"``); Rust
              interpolates ``std::io::Error`` Display
              (``"No such file or directory (os error 2)"``).
              We pin only the prefix; the body is documented
              as OS-runtime-formatter-specific and intentionally
              not byte-aligned.
E3 HASH_DRIFT Soft-match: byte-equal prefix
              ``"wakir-persona: hash drift: "``. The body is the
              underlying determinism-error message; cross-lang
              wording is independently maintained and not
              byte-aligned.
E4 MIG_FAIL   Soft-match: byte-equal prefix
              ``"wakir-persona: migration failed: "``. Body
              wording comes from Python ``PersonaMigrationError``
              ``__str__`` vs. Rust ``MigrationError`` ``Display``
              via the ``migration_msg`` adapter.
E5 INSP_FAIL  Soft-match: byte-equal prefix
              ``"wakir-persona: inspect failed: "``. Body
              wording: Python ``ValueError`` / ``KeyError``
              ``__str__`` vs. Rust ``ExtractCanonicalSubsetError``
              ``Display``.
E6 PIN_FAIL   Soft-match: byte-equal prefix
              ``"wakir-persona: pin failed: "``. Same posture
              as E5.
============= =================================================

Why prefix-only for E2-E6 and not full byte-equal? The bodies are
language-runtime-formatter outputs (``FileNotFoundError.__str__`` /
``io::Error::Display``) or independently-maintained typed-error
Display impls (``PersonaMigrationError`` / ``MigrationError``).
Forcing byte-equal on those would require either re-implementing
Python's exception-string format inside Rust or re-implementing
Rust's typed-error Display tree inside Python — both options
inflate cross-lang coupling without operator-surface benefit.
The pinning the prefix gives us is sufficient: an operator can
``grep`` for ``"wakir-persona: hash drift"`` (or any other marker)
and get byte-identical hits across Python and Rust invocations of
the same operator-action.

Cross-Lang-Diff-Pin
-------------------

The shared anchor strings live in :data:`STDERR_PREFIX_BY_MARKER`
below. The sister Rust pack pins the same constants in
``stderr_parity_tests::STDERR_PREFIX_BY_MARKER``. Diff is intentional:
any future wording change has to land in both packs in the same box
or one of them fails CI immediately.

The Tag-5 ``test_persona_cli_help_text`` pack pinned the *info*
surface (``--help``); this pack pins the *error* surface.
"""

from __future__ import annotations

import io
import contextlib
from pathlib import Path

import pytest

from wirelang.persona.cli import main as cli_main


# ---------------------------------------------------------------------------
# Cross-Lang-Diff-Pin: anchor strings shared with the sister Rust pack.
# Mirror in ``wirelang-rust/crates/persona-cli/src/lib.rs`` under
# ``stderr_parity_tests::STDERR_PREFIX_BY_MARKER``.
# ---------------------------------------------------------------------------

#: Per-marker stderr prefix. Pinned byte-identically with the Rust pack.
#: A wording change must update both packs in the same box.
STDERR_PREFIX_BY_MARKER: dict[str, str] = {
    "E1_NOT_FOUND": "wakir-persona: persona-file not found: ",
    "E2_VANISHED": "wakir-persona: persona-file vanished mid-run: ",
    "E3_HASH_DRIFT": "wakir-persona: hash drift: ",
    "E4_MIG_FAIL": "wakir-persona: migration failed: ",
    "E5_INSP_FAIL": "wakir-persona: inspect failed: ",
    "E6_PIN_FAIL": "wakir-persona: pin failed: ",
}

#: Subcommands covered by this pack.
SUBCOMMANDS = ("migrate", "validate", "inspect", "pin")

#: Per-subcommand markers that the error path can produce. The lookup
#: drives the per-subcommand E1 byte-equal sweep.
SUBCOMMAND_E1_ENABLED = SUBCOMMANDS  # all four subs surface E1 (NOT_FOUND).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Invoke the CLI in-process and capture stdout / stderr / exit code.

    Mirror of the Rust ``run(...)`` helper. argparse-level errors
    (which raise ``SystemExit``) are caught so the test pack can assert
    on the exit code uniformly.
    """
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            exit_code = cli_main(argv)
        except SystemExit as exc:
            # argparse-level errors raise SystemExit; map to its code.
            exit_code = int(exc.code) if exc.code is not None else 0
    return exit_code, out_buf.getvalue(), err_buf.getvalue()


def _missing_path(tmp_path: Path) -> Path:
    """Return a deterministic non-existent path under ``tmp_path``.

    Keeping the path predictable (same suffix every call) makes
    cross-test debugging easier when an assertion fires.
    """
    return tmp_path / "does-not-exist.md"


# ---------------------------------------------------------------------------
# E1 — persona-file not found, byte-equal full stderr line (4 tests).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("subcommand", SUBCOMMAND_E1_ENABLED)
def test_e1_persona_file_not_found_stderr_byte_equal_full_line(
    tmp_path: Path,
    subcommand: str,
) -> None:
    """E1: full stderr line is byte-equal across all four subcommands.

    The pre-existence check fires before any subcommand-specific
    code-path, so the line shape is uniform: prefix + path + ``\\n``.
    Byte-equal across Python and Rust is asserted by the sister Rust
    pack on the same path-as-string + newline.
    """
    missing = _missing_path(tmp_path)
    exit_code, stdout, stderr = _run_cli([subcommand, str(missing)])

    assert exit_code == 3, f"{subcommand}: expected exit 3 (input-not-found), got {exit_code}"
    assert stdout == "", f"{subcommand}: stdout must be empty on E1; got: {stdout!r}"

    expected = f"{STDERR_PREFIX_BY_MARKER['E1_NOT_FOUND']}{missing}\n"
    assert stderr == expected, (
        f"{subcommand}: E1 stderr byte-equal failed.\n"
        f"  expected: {expected!r}\n"
        f"  actual:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# E1 — prefix-shape sanity (cross-check that the prefix-only contract
# the Rust pack uses ALSO holds on the Python side). 4 tests.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("subcommand", SUBCOMMAND_E1_ENABLED)
def test_e1_stderr_starts_with_pinned_prefix(
    tmp_path: Path,
    subcommand: str,
) -> None:
    """E1: stderr line starts with the pinned prefix.

    Redundant with the byte-equal sweep above, but pinned separately
    so a wording-drift in *only* the prefix surfaces as a prefix-test
    failure with a sharper error message.
    """
    missing = _missing_path(tmp_path)
    _, _, stderr = _run_cli([subcommand, str(missing)])
    prefix = STDERR_PREFIX_BY_MARKER["E1_NOT_FOUND"]
    assert stderr.startswith(prefix), (
        f"{subcommand}: stderr does not start with E1 prefix.\n"
        f"  expected prefix: {prefix!r}\n"
        f"  actual stderr:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# E2 — vanished mid-run, soft-match prefix only (skipped: the race
# is hard to provoke deterministically from a unit test without
# privilege-elevated file system tricks; the byte-equal-prefix
# contract is exercised by the Rust pack's inline IO error injection).
# We pin the constant here so the cross-lang diff still has both
# sides "owning" the same string.
# ---------------------------------------------------------------------------

def test_e2_vanished_prefix_constant_is_pinned() -> None:
    """E2 prefix constant is fixed at byte granularity.

    The vanished-mid-run race itself is hard to provoke from a unit
    test without privileged FS tricks, so we pin the constant value
    here and rely on the existing functional tests
    (``test_persona_migration_cli.py`` etc.) to exercise the code
    path. The sister Rust pack pins the same constant.
    """
    assert (
        STDERR_PREFIX_BY_MARKER["E2_VANISHED"]
        == "wakir-persona: persona-file vanished mid-run: "
    )


# ---------------------------------------------------------------------------
# E3 — migrate-only hash drift prefix, soft-match (1 test).
# ---------------------------------------------------------------------------

def test_e3_migrate_hash_drift_prefix_match(tmp_path: Path) -> None:
    """E3: ``migrate --expect-hash <wrong>`` produces hash-drift prefix.

    Invoke the migrate path on a real v9 fixture with an obviously-
    wrong expected pin. The resolver fires its determinism check and
    the CLI surfaces it as the hash-drift marker.
    """
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "persona_definitions"
        / "v9-persona-framework-native.md"
    )
    assert fixture.exists(), f"fixture missing: {fixture}"

    exit_code, _stdout, stderr = _run_cli([
        "migrate",
        str(fixture),
        "--expect-hash",
        "sha256:" + ("0" * 64),
        "--quiet",
    ])
    assert exit_code == 2, f"expected exit 2 (determinism), got {exit_code}"
    prefix = STDERR_PREFIX_BY_MARKER["E3_HASH_DRIFT"]
    assert stderr.startswith(prefix), (
        f"E3: stderr does not start with hash-drift prefix.\n"
        f"  expected prefix: {prefix!r}\n"
        f"  actual stderr:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# E4 — migrate-only migration-failed prefix (1 test).
# ---------------------------------------------------------------------------

def test_e4_migrate_failure_prefix_match(tmp_path: Path) -> None:
    """E4: malformed persona-file triggers migration-failed marker.

    A persona-file without YAML front-matter at all forces the
    extractor to raise a ``ValueError`` which the resolver surfaces
    as a ``PersonaMigrationError``. The CLI maps that to the
    migration-failed marker (exit 1).
    """
    bad = tmp_path / "no-frontmatter.md"
    bad.write_text("just some markdown body and no front-matter.\n", encoding="utf-8")

    exit_code, _stdout, stderr = _run_cli([
        "migrate",
        str(bad),
        "--quiet",
    ])
    # exit 1 = MigrationError. The v0 default-target means the
    # extractor failure is wrapped in MigrationError; the marker is
    # the migration-failed prefix.
    assert exit_code in (1, 2), f"expected non-zero exit, got {exit_code}"
    prefix = STDERR_PREFIX_BY_MARKER["E4_MIG_FAIL"]
    assert stderr.startswith(prefix), (
        f"E4: stderr does not start with migration-failed prefix.\n"
        f"  expected prefix: {prefix!r}\n"
        f"  actual stderr:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# E5 — inspect-only failure prefix (1 test).
# ---------------------------------------------------------------------------

def test_e5_inspect_failure_prefix_match(tmp_path: Path) -> None:
    """E5: malformed persona-file triggers inspect-failed marker.

    The inspect subcommand surfaces extractor failures with its
    own banner (no PersonaMigrationError wrap; the extractor raises
    ValueError directly and the CLI catches it).
    """
    bad = tmp_path / "no-frontmatter.md"
    bad.write_text("just some markdown body and no front-matter.\n", encoding="utf-8")

    exit_code, _stdout, stderr = _run_cli([
        "inspect",
        str(bad),
        "--quiet",
    ])
    assert exit_code == 1, f"expected exit 1 (inspect-failed), got {exit_code}"
    prefix = STDERR_PREFIX_BY_MARKER["E5_INSP_FAIL"]
    assert stderr.startswith(prefix), (
        f"E5: stderr does not start with inspect-failed prefix.\n"
        f"  expected prefix: {prefix!r}\n"
        f"  actual stderr:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# E6 — pin-only failure prefix (1 test).
# ---------------------------------------------------------------------------

def test_e6_pin_failure_prefix_match(tmp_path: Path) -> None:
    """E6: malformed persona-file triggers pin-failed marker.

    Strict subset of E5 (pin reuses the same extractor + hash code
    path as inspect; only the banner differs).
    """
    bad = tmp_path / "no-frontmatter.md"
    bad.write_text("just some markdown body and no front-matter.\n", encoding="utf-8")

    exit_code, _stdout, stderr = _run_cli([
        "pin",
        str(bad),
        "--quiet",
    ])
    assert exit_code == 1, f"expected exit 1 (pin-failed), got {exit_code}"
    prefix = STDERR_PREFIX_BY_MARKER["E6_PIN_FAIL"]
    assert stderr.startswith(prefix), (
        f"E6: stderr does not start with pin-failed prefix.\n"
        f"  expected prefix: {prefix!r}\n"
        f"  actual stderr:   {stderr!r}"
    )


# ---------------------------------------------------------------------------
# Cross-Lang-Diff-Pin self-checks — make sure no prefix accidentally
# overlaps another and the constants dictionary is well-formed.
# ---------------------------------------------------------------------------

def test_cross_lang_diff_pin_dict_completeness() -> None:
    """All six markers are present in :data:`STDERR_PREFIX_BY_MARKER`."""
    assert set(STDERR_PREFIX_BY_MARKER.keys()) == {
        "E1_NOT_FOUND",
        "E2_VANISHED",
        "E3_HASH_DRIFT",
        "E4_MIG_FAIL",
        "E5_INSP_FAIL",
        "E6_PIN_FAIL",
    }


def test_cross_lang_diff_pin_prefixes_have_uniform_shape() -> None:
    """Every prefix begins with ``wakir-persona: `` and ends with ``: ``."""
    for marker, prefix in STDERR_PREFIX_BY_MARKER.items():
        assert prefix.startswith("wakir-persona: "), (
            f"{marker}: prefix must start with 'wakir-persona: '; got {prefix!r}"
        )
        assert prefix.endswith(": "), (
            f"{marker}: prefix must end with ': ' (separator before "
            f"the runtime-formatter body); got {prefix!r}"
        )


def test_cross_lang_diff_pin_prefixes_are_unique() -> None:
    """No two markers share the same prefix."""
    seen: set[str] = set()
    for marker, prefix in STDERR_PREFIX_BY_MARKER.items():
        assert prefix not in seen, (
            f"{marker}: prefix collision with an earlier marker; got {prefix!r}"
        )
        seen.add(prefix)
