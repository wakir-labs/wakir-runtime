# SPDX-License-Identifier: Apache-2.0
"""Operator CLI test pack (Phase-1b Sprint-2 Tag-3, S2-T1-06).

Covers the ``wakir-persona migrate`` entry-point declared in
``pyproject.toml`` and implemented in
:mod:`wirelang.persona.cli`.

The CLI is a thin wrapper over :func:`migrate_persona`; the bulk of
defensive coverage lives in
``test_persona_migration_edge_cases.py`` and
``test_persona_migration_roundtrip.py``. This pack focuses on the
shim layer specifically:

- argparse surface (parser construction, choices, required subcommand)
- exit-code mapping per spec §7.4 (0 / 1 / 2 / 3)
- stdout JSON shape
- stderr ``--emit-hash`` output
- ``--quiet`` flag suppression
- ``--expect-hash`` happy path and drift path
- non-existent-file path
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

from wirelang.persona._internal.pin_pack_constants import (
    PERSONA_HASH_PIN_V9,
)
from wirelang.persona.cli import (
    EXIT_DETERMINISM_ERROR,
    EXIT_INPUT_NOT_FOUND,
    EXIT_MIGRATION_ERROR,
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


def test_build_parser_returns_subcommand_required_parser():
    parser = build_parser()
    # Without args, parse_args raises SystemExit because the
    # subcommand is required.
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([])
    assert excinfo.value.code != 0


def test_build_parser_migrate_subcommand_choices_match_schema_versions():
    parser = build_parser()
    # --target's `choices` must equal the schema-version list so that
    # invalid targets fail at argparse time rather than deep inside
    # the resolver.
    namespace = parser.parse_args(["migrate", str(V8_FIXTURE)])
    assert namespace.command == "migrate"
    assert namespace.target == "persona-v1"  # default
    assert namespace.expect_hash is None
    assert namespace.emit_hash is False
    assert namespace.quiet is False


def test_build_parser_migrate_subcommand_rejects_unknown_target():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["migrate", str(V8_FIXTURE), "--target", "persona-v99"]
        )


# ---------------------------------------------------------------------------
# Happy path: migrate v8 -> v1
# ---------------------------------------------------------------------------


def test_migrate_v8_to_v1_emits_canonical_subset_json_on_stdout(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["migrate", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    # stdout is JSON-decodable and carries the lifted schema_version.
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v1"
    # --quiet suppresses the human progress line; --emit-hash is not
    # set, so stderr should be empty.
    assert captured.err == ""


def test_migrate_v8_to_v1_stdout_is_sorted_and_terminates_with_newline(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["migrate", str(V8_FIXTURE), "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.endswith("\n")
    # Sorted keys: a regex-free check that the top-level keys appear
    # in lexical order in the rendered JSON. We look for a specific
    # pair we know must be present in the v8 canonical subset.
    desc_pos = captured.out.find('"description"')
    name_pos = captured.out.find('"name"')
    assert 0 < desc_pos < name_pos


def test_migrate_emit_hash_writes_pin_to_stderr(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["migrate", str(V8_FIXTURE), "--quiet", "--emit-hash"])
    captured = capsys.readouterr()
    assert rc == 0
    # stderr last non-empty line is the post-migration hash.
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert stderr_lines == [PERSONA_HASH_PIN_V9]


def test_migrate_progress_line_on_stderr_when_not_quiet(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["migrate", str(V8_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "wakir-persona: migrated" in captured.err
    assert "persona-v1" in captured.err


# ---------------------------------------------------------------------------
# --expect-hash: happy + drift
# ---------------------------------------------------------------------------


def test_migrate_expect_hash_full_form_passes(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(
        [
            "migrate",
            str(V8_FIXTURE),
            "--quiet",
            "--expect-hash",
            PERSONA_HASH_PIN_V9,
        ]
    )
    assert rc == 0


def test_migrate_expect_hash_bare_hex_form_passes(
    capsys: pytest.CaptureFixture[str],
):
    bare_hex = PERSONA_HASH_PIN_V9.removeprefix("sha256:")
    rc = main(
        [
            "migrate",
            str(V8_FIXTURE),
            "--quiet",
            "--expect-hash",
            bare_hex,
        ]
    )
    assert rc == 0


def test_migrate_expect_hash_drift_returns_exit_code_2(
    capsys: pytest.CaptureFixture[str],
):
    wrong_pin = "sha256:" + ("0" * 64)
    rc = main(
        [
            "migrate",
            str(V8_FIXTURE),
            "--quiet",
            "--expect-hash",
            wrong_pin,
        ]
    )
    captured = capsys.readouterr()
    assert rc == EXIT_DETERMINISM_ERROR
    assert "hash drift" in captured.err


# ---------------------------------------------------------------------------
# Migration-error and not-found exit codes
# ---------------------------------------------------------------------------


def test_migrate_persona_file_does_not_exist_returns_exit_code_3(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    missing = tmp_path / "does-not-exist.md"
    rc = main(["migrate", str(missing)])
    captured = capsys.readouterr()
    assert rc == EXIT_INPUT_NOT_FOUND
    assert "not found" in captured.err


def test_migrate_irreparable_frontmatter_returns_exit_code_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    # No closing fence — the converter wraps the front-matter parse
    # failure as PersonaMigrationError.
    bad = tmp_path / "irreparable.md"
    bad.write_text("---\nname: x\n", encoding="utf-8")
    rc = main(["migrate", str(bad)])
    captured = capsys.readouterr()
    assert rc == EXIT_MIGRATION_ERROR
    assert "migration failed" in captured.err


def test_migrate_unknown_target_via_resolver_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    # We cannot reach the resolver's "unknown target" branch through
    # argparse (--target choices block it), so we exercise the
    # equivalent failure mode: a dict input with an unknown
    # source schema_version. Build a minimal raw-markdown input that
    # carries an unknown schema_version and write it to disk.
    bad = tmp_path / "unknown-source.md"
    bad.write_text(
        "---\n"
        "name: x\n"
        'description: "x"\n'
        "tools: []\n"
        "schema_version: persona-vX\n"
        "identity_pinned:\n"
        "  cross_review_zones: []\n"
        "  authority:\n"
        "    push_remote: false\n"
        "    budget_cap_eur_per_month: 0\n"
        "    sub_delegation: false\n"
        "  hierarchy:\n"
        "    reports_to: cto\n"
        "    escalation: cto\n"
        "---\n"
        "\n"
        "# Body.\n",
        encoding="utf-8",
    )
    rc = main(["migrate", str(bad)])
    captured = capsys.readouterr()
    assert rc == EXIT_MIGRATION_ERROR
    assert "migration failed" in captured.err


# ---------------------------------------------------------------------------
# Idempotence via CLI: v9 -> v1 (same version)
# ---------------------------------------------------------------------------


def test_migrate_v9_to_v1_is_no_op(
    capsys: pytest.CaptureFixture[str],
):
    rc = main(["migrate", str(V9_FIXTURE), "--quiet", "--emit-hash"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "persona-v1"
    stderr_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert stderr_lines == [PERSONA_HASH_PIN_V9]
