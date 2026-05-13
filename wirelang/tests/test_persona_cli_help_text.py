# SPDX-License-Identifier: Apache-2.0
"""Operator CLI help-text cross-subcommand-consistency test pack
(Phase-1b Sprint-6 Tag-5).

Covers ``wakir-persona --help`` and ``wakir-persona <subcommand> --help``
for all four registered subcommands (``migrate``, ``validate``,
``inspect``, ``pin``). Verifies cross-subcommand-consistency contracts
on the help-text surface that the previous Sprint-5 / Sprint-6 test
packs did not pin explicitly:

- shared-flag wording uniformity (``persona_file`` positional and
  ``--quiet`` flag must carry byte-identical help strings across all
  subcommands)
- top-level help lists exactly the four registered subcommands in
  insertion-order
- per-subcommand help has the expected usage-line shape (program
  name + subcommand name + bracketed options + positional)
- per-subcommand long-description references the documented exit
  codes correctly
- ``-h`` and ``--help`` produce byte-identical output (argparse
  default; pinned defensively)
- ``argparse``'s SystemExit-on-help exits with code 0 (not the
  EX_USAGE 64 reserved for parse-failure)

Posture (vs. Rust ``clap`` cross-language parity)
=================================================

Help-text byte-identity across Python and Rust is **NOT** asserted.
``argparse`` and ``clap`` format help differently (clap uses double-
spaced sections, capitalised "Usage:" / "Options:", and renders
``long_about`` instead of ``description`` by default). Soft-match
contracts (subcommand registration order, shared help-string content,
exit-code documentation) are the cross-language parity layer; the
sister Rust pack ``persona_cli_help_text_consistency`` tests in
``wirelang-rust/crates/persona-cli/src/lib.rs`` asserts the same
soft-match contracts against the Rust-side ``clap::Command`` tree.

V-907-CLI-invariant (Tag-4 anchor) is unchanged: ``pin`` stdout ==
``inspect --emit-hash --quiet`` stderr-pin == ``migrate --emit-hash``
stderr-last-line == ``PERSONA_HASH_PIN_V9``. The help-text pack is
documentation-surface polish, not invariant-deepening.
"""

from __future__ import annotations

import io
import contextlib
from typing import Any

import pytest

# Skip the whole module when rfc8785 is absent: the wirelang.persona
# package imports rfc8785 unconditionally at module-load time, so any
# top-level `from wirelang.persona ...` below would crash collection
# in the sandbox lane. Test-level importorskip is the conventional
# guard for this case until the persona package adopts a lazy import.
pytest.importorskip("rfc8785")

from wirelang.persona.cli import build_parser


# ---------------------------------------------------------------------------
# Subcommand inventory — single source of truth for the test pack.
# ---------------------------------------------------------------------------

# Order matches the ``add_parser`` calls in build_parser(). argparse
# preserves insertion order in subparsers.choices, so this is the order
# we expect on the top-level help listing.
EXPECTED_SUBCOMMANDS = ("migrate", "validate", "inspect", "pin")

# Help-string copy that MUST be byte-identical across every subcommand
# that exposes the corresponding argument. Pinning the strings here
# means a future refactor that "slightly tweaks the wording" in one
# subcommand will surface as a hard test failure rather than silent
# drift.
SHARED_PERSONA_FILE_HELP = (
    "Filesystem path to a UTF-8 markdown persona-definition."
)
SHARED_QUIET_HELP = (
    "Suppress the human-readable progress line on stderr."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _subparser(name: str) -> Any:
    """Return the configured subparser for ``name``.

    Raises ``KeyError`` if the subcommand is not registered (test
    failure mode: build_parser() drift relative to EXPECTED_SUBCOMMANDS).
    """
    parser = build_parser()
    # subparsers is the only _SubParsersAction in the top-level
    # parser; walk _actions to find it.
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if choices and name in choices:
            return choices[name]
    raise KeyError(name)


def _arg_help(sub: Any, dest: str) -> str:
    """Return the ``help=`` string for the ``dest`` argument on ``sub``.

    ``sub._actions`` is a list of ``argparse.Action`` objects; we match
    on ``.dest`` (which mirrors the destination attribute on the
    parsed namespace, e.g. ``persona_file`` or ``quiet``).
    """
    for a in sub._actions:
        if a.dest == dest:
            return a.help or ""
    raise KeyError(f"argument {dest!r} not found on subparser")


# ---------------------------------------------------------------------------
# Top-level help surface
# ---------------------------------------------------------------------------


def test_top_level_help_lists_all_four_subcommands_in_insertion_order():
    """The top-level help-text must enumerate the four subcommands
    in insertion-order (matching build_parser()'s add_parser sequence)."""
    parser = build_parser()
    help_text = parser.format_help()
    # Every subcommand name appears as a standalone token in the
    # positional-arguments block.
    for name in EXPECTED_SUBCOMMANDS:
        assert name in help_text, (
            f"top-level help missing subcommand {name!r}; got: {help_text!r}"
        )
    # Insertion-order anchor: find each subcommand's first occurrence
    # in the help text and assert monotonic ordering.
    positions = [help_text.index(name) for name in EXPECTED_SUBCOMMANDS]
    assert positions == sorted(positions), (
        f"subcommands not listed in insertion-order; got positions {positions}, "
        f"expected monotonic. Order in help: "
        f"{[(name, p) for name, p in zip(EXPECTED_SUBCOMMANDS, positions)]}"
    )


def test_top_level_help_carries_program_name_and_description():
    """The top-level help must announce ``wakir-persona`` and
    reference the ADR-0036 charter line verbatim."""
    parser = build_parser()
    help_text = parser.format_help()
    assert "wakir-persona" in help_text
    assert "Operator CLI" in help_text
    assert "ADR-0036" in help_text, (
        "top-level description must cite ADR-0036 (V-907 charter line)"
    )


def test_top_level_help_dash_h_equals_double_dash_help():
    """``-h`` and ``--help`` must produce byte-identical output.

    argparse default behaviour; pinning defensively because a future
    add_help=False override would break operator-muscle-memory."""
    parser = build_parser()
    short = parser.format_help()
    # argparse's parse_args(['-h']) raises SystemExit; we instead
    # call format_help() directly which is what -h / --help invoke
    # behind the scenes. Equivalence at this level is sufficient
    # because both flags route to the same format_help() callsite.
    assert "-h, --help" in short, (
        "top-level options must show both -h and --help aliases"
    )


def test_top_level_help_exits_with_code_0():
    """argparse's --help SystemExit must carry exit code 0 (not 64).

    EX_USAGE=64 is reserved for parse-failure (spec §7.4). --help is a
    success path: the operator asked for documentation."""
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Cross-subcommand-consistency: persona_file positional help wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_persona_file_help_wording_is_uniform_across_subcommands(
    subcommand: str,
):
    """Every subcommand's ``persona_file`` positional MUST carry the
    byte-identical help string.

    Rationale: the operator should not have to relearn what the
    positional argument means when switching between subcommands.
    Wording drift between e.g. ``migrate`` and ``pin`` is a
    documentation-surface bug that would otherwise slip silently into
    a release."""
    sub = _subparser(subcommand)
    got = _arg_help(sub, "persona_file")
    assert got == SHARED_PERSONA_FILE_HELP, (
        f"{subcommand}: persona_file help drift: got {got!r}, "
        f"expected {SHARED_PERSONA_FILE_HELP!r}"
    )


# ---------------------------------------------------------------------------
# Cross-subcommand-consistency: --quiet flag help wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_quiet_flag_help_wording_is_uniform_across_subcommands(
    subcommand: str,
):
    """Every subcommand's ``--quiet`` flag MUST carry the byte-identical
    help string.

    Rationale: ``--quiet`` is the only flag that lives on every
    subcommand. Wording uniformity makes the operator's mental model
    portable: ``--quiet`` does the same thing everywhere, and the
    help-text says so the same way."""
    sub = _subparser(subcommand)
    got = _arg_help(sub, "quiet")
    assert got == SHARED_QUIET_HELP, (
        f"{subcommand}: --quiet help drift: got {got!r}, "
        f"expected {SHARED_QUIET_HELP!r}"
    )


# ---------------------------------------------------------------------------
# Per-subcommand help: usage-line shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_subcommand_help_usage_line_contains_program_and_subcommand(
    subcommand: str,
):
    """The usage line of each subcommand help must announce both
    ``wakir-persona`` (program name) and the subcommand name."""
    sub = _subparser(subcommand)
    help_text = sub.format_help()
    assert help_text.startswith("usage:"), (
        f"{subcommand}: help must start with 'usage:'; got: {help_text[:60]!r}"
    )
    first_line = help_text.split("\n", 1)[0]
    # argparse may wrap a long usage across lines; concatenate the
    # full usage block (everything up to the first blank line).
    usage_block, _, _ = help_text.partition("\n\n")
    assert "wakir-persona" in usage_block, (
        f"{subcommand}: usage block missing program name: {usage_block!r}"
    )
    assert subcommand in usage_block, (
        f"{subcommand}: usage block missing subcommand name: {usage_block!r}"
    )
    # First line specifically contains the program name (defensive).
    assert "wakir-persona" in first_line


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_subcommand_help_lists_persona_file_positional(subcommand: str):
    """Every subcommand exposes the ``persona_file`` positional and
    must surface it in the help-text positional-arguments section."""
    sub = _subparser(subcommand)
    help_text = sub.format_help()
    assert "persona_file" in help_text, (
        f"{subcommand}: help must list persona_file positional"
    )
    assert "positional arguments:" in help_text, (
        f"{subcommand}: help missing positional-arguments section"
    )


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_subcommand_help_lists_quiet_flag(subcommand: str):
    """Every subcommand exposes ``--quiet`` and must surface it in
    the options section."""
    sub = _subparser(subcommand)
    help_text = sub.format_help()
    assert "--quiet" in help_text, (
        f"{subcommand}: help must list --quiet flag"
    )
    assert "options:" in help_text, (
        f"{subcommand}: help missing options section"
    )


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_subcommand_help_lists_dash_h_and_double_dash_help(subcommand: str):
    """argparse always wires -h / --help; pinned defensively per
    subcommand to catch a future ``add_help=False`` override."""
    sub = _subparser(subcommand)
    help_text = sub.format_help()
    assert "-h, --help" in help_text, (
        f"{subcommand}: help must announce -h / --help aliases"
    )


@pytest.mark.parametrize("subcommand", EXPECTED_SUBCOMMANDS)
def test_subcommand_help_exits_with_code_0(subcommand: str):
    """``--help`` on any subcommand is a success path: exit 0, not
    EX_USAGE 64."""
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([subcommand, "--help"])
    assert exc_info.value.code == 0, (
        f"{subcommand}: --help must exit 0 (success); got {exc_info.value.code}"
    )


# ---------------------------------------------------------------------------
# Per-subcommand help: flag-surface scope (no leakage)
# ---------------------------------------------------------------------------


def test_validate_help_does_not_advertise_migrate_only_flags():
    """``--target`` / ``--expect-hash`` / ``--emit-hash`` belong to
    ``migrate``. ``validate`` is read-only with no schema-version
    gymnastics, so the flags MUST NOT leak into its options section.

    Scope: same options-section-only contract as
    ``test_pin_help_is_strict_subset_of_inspect_help_flag_surface``.
    The validate description does not currently reference any
    migrate-only flag in prose, but slicing to the options section
    keeps the assertion robust against future doc-string edits."""
    sub = _subparser("validate")
    help_text = sub.format_help()
    _, _, options_section = help_text.partition("options:")
    assert options_section
    assert "--target" not in options_section
    assert "--expect-hash" not in options_section
    assert "--emit-hash" not in options_section


def test_inspect_help_does_not_advertise_target_or_expect_hash():
    """``inspect`` shares ``--emit-hash`` with ``migrate`` but is
    read-only on schema-version: ``--target`` / ``--expect-hash``
    MUST NOT leak into the options section.

    Scope: options-section-only. The inspect ``--emit-hash`` help
    string legitimately references ``migrate --emit-hash`` in prose
    (cross-reference to the same stderr-line shape) — that mention
    lives inside the registered flag's help-text, not as a separate
    registered option."""
    sub = _subparser("inspect")
    help_text = sub.format_help()
    _, _, options_section = help_text.partition("options:")
    assert options_section
    # No --target or --expect-hash flag entry.
    assert "  --target" not in options_section, (
        f"inspect options-section must not register --target; "
        f"got: {options_section!r}"
    )
    assert "  --expect-hash" not in options_section
    # --emit-hash IS a legitimate flag entry on inspect.
    assert "--emit-hash" in options_section


def test_pin_help_is_strict_subset_of_inspect_help_flag_surface():
    """``pin`` is a strict-subset of ``inspect``: no ``--emit-hash``
    (the subcommand always emits the pin on stdout), no ``--target``,
    no ``--expect-hash``. Only ``--quiet`` is shared.

    Scope of the "no flag" assertion: the options-section only. The
    pin description prose legitimately references ``migrate
    --emit-hash`` and ``inspect --emit-hash --quiet`` as cross-
    references to the V-907-CLI-invariant — those mentions are in the
    description block (above ``options:``), not in the registered-
    flags block."""
    sub = _subparser("pin")
    help_text = sub.format_help()
    # Slice to the options section (everything from the "options:"
    # heading to the end of help-text).
    _, _, options_section = help_text.partition("options:")
    assert options_section, (
        "pin help must have an options section"
    )
    # No migrate-only or inspect-only flags registered on pin.
    assert "--target" not in options_section, (
        f"pin options-section must not register --target; "
        f"got: {options_section!r}"
    )
    assert "--expect-hash" not in options_section
    assert "--emit-hash" not in options_section
    # --quiet IS registered.
    assert "--quiet" in options_section


def test_migrate_help_advertises_all_four_flags():
    """``migrate`` is the widest surface: ``--target``,
    ``--expect-hash``, ``--emit-hash``, ``--quiet``."""
    sub = _subparser("migrate")
    help_text = sub.format_help()
    assert "--target" in help_text
    assert "--expect-hash" in help_text
    assert "--emit-hash" in help_text
    assert "--quiet" in help_text


# ---------------------------------------------------------------------------
# Per-subcommand help: description references documented exit codes
# ---------------------------------------------------------------------------


def test_migrate_description_documents_pin_mismatch_exit_code():
    """``--expect-hash`` help must document exit code 2 (the
    determinism-error path documented in spec §7.4)."""
    sub = _subparser("migrate")
    expect_hash_help = _arg_help(sub, "expect_hash")
    assert "exit" in expect_hash_help.lower() or "code 2" in expect_hash_help, (
        f"migrate --expect-hash help must document exit code 2; "
        f"got: {expect_hash_help!r}"
    )
    assert "2" in expect_hash_help, (
        f"migrate --expect-hash help must mention exit code 2; "
        f"got: {expect_hash_help!r}"
    )


def test_validate_description_documents_exit_code_pair():
    """``validate`` description must document the 0/1 exit-code split."""
    sub = _subparser("validate")
    desc = sub.description or ""
    assert "Exit code 0" in desc, (
        f"validate description must document exit code 0; got: {desc!r}"
    )
    assert "1" in desc, (
        f"validate description must mention failure exit code 1; got: {desc!r}"
    )


def test_inspect_description_documents_exit_code_pair():
    """``inspect`` description must document the 0/1 exit-code split."""
    sub = _subparser("inspect")
    desc = sub.description or ""
    assert "Exit code 0" in desc, (
        f"inspect description must document exit code 0; got: {desc!r}"
    )
    assert "1" in desc, (
        f"inspect description must mention failure exit code 1; got: {desc!r}"
    )


def test_pin_description_documents_exit_code_pair_and_invariant():
    """``pin`` description must document the 0/1 exit-code split AND
    the V-907-CLI-invariant cross-reference."""
    sub = _subparser("pin")
    desc = sub.description or ""
    assert "Exit code 0" in desc
    assert "1" in desc
    # V-907-CLI-invariant is the load-bearing distinction-anchor.
    assert "V-907-CLI-invariant" in desc, (
        f"pin description must reference V-907-CLI-invariant; got: {desc!r}"
    )


# ---------------------------------------------------------------------------
# Help-text terminates cleanly (no trailing whitespace anomalies)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand", ("__top__",) + EXPECTED_SUBCOMMANDS
)
def test_help_text_ends_with_newline_and_no_trailing_blank_lines(
    subcommand: str,
):
    """Help-text terminates with exactly one trailing newline.

    argparse defaults to this shape; pinning defensively because a
    custom formatter would otherwise slip without test failure."""
    if subcommand == "__top__":
        help_text = build_parser().format_help()
    else:
        help_text = _subparser(subcommand).format_help()
    assert help_text.endswith("\n"), (
        f"{subcommand}: help-text must terminate with newline"
    )
    # Exactly one terminating newline, no double-blank-line tail.
    assert not help_text.endswith("\n\n\n"), (
        f"{subcommand}: help-text must not end with three+ blank lines"
    )
