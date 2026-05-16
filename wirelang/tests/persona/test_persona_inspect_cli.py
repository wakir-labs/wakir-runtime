# SPDX-License-Identifier: Apache-2.0
"""Hermetic test pack for ``wakir-persona inspect-heartbeat``.

Anchored by Sprint-Wirelang-Persona-Inspect-CLI-MINI
(Amara PR #116 §5 + ADR-0058 V-907-Hash-Drift Risk §156).

Distinct from ``wirelang/tests/test_persona_inspect_cli.py``
(top-level), which covers the file-based ``inspect`` subcommand
on persona-definition specifications. This pack covers the
``inspect-heartbeat`` subcommand which reads RUNTIME heartbeat
state (the running engine's per-tick JSON state files) and is
therefore conceptually disjoint:

- ``inspect``           = static spec inspection (file-based)
- ``inspect-heartbeat`` = runtime state inspection (state-dir-based)

Hermetic posture
================

All tests use ``tmp_path`` (pytest's fixture-managed throwaway
directory) for the heartbeat-directory. No reads from the
real ``/var/run/wakir-persona``. No network. No subprocess. The
CLI ``main()`` entrypoint is invoked in-process with explicit
argv. ``capsys`` captures stdout / stderr.

Test coverage (10 tests, ≥8 required by sprint contract)
========================================================

1. ``test_inspect_heartbeat_parser_surface`` —
   parser introspection: subcommand exists, default flags shape
2. ``test_inspect_heartbeat_empty_dir_is_zero_exit_empty_personas`` —
   freshly-booted substrate: dir exists but no heartbeat files.
3. ``test_inspect_heartbeat_single_persona_no_drift`` —
   single persona-file, current pin equals expected pin.
4. ``test_inspect_heartbeat_drift_detected`` —
   single persona-file, current pin disagrees with expected pin.
5. ``test_inspect_heartbeat_persona_filter_narrows_scope`` —
   directory with three files; ``--persona`` selects one.
6. ``test_inspect_heartbeat_persona_filter_missing_file_exits_3`` —
   ``--persona <slug>`` but the per-slug file does not exist.
7. ``test_inspect_heartbeat_heartbeat_dir_not_found_exits_3`` —
   ``--heartbeat-dir`` points at a non-existent path.
8. ``test_inspect_heartbeat_malformed_json_exits_1`` —
   a heartbeat-state file is corrupt JSON.
9. ``test_inspect_heartbeat_missing_required_key_exits_1`` —
   a heartbeat-state file is missing a required key.
10. ``test_inspect_heartbeat_summary_mode_emits_table`` —
    ``--summary`` emits a tabular (non-JSON) report on stdout.
11. ``test_inspect_heartbeat_env_var_overrides_default_dir`` —
    ``$WAKIR_PERSONA_HEARTBEAT_DIR`` env-var honoured;
    ``--heartbeat-dir`` wins over env.
12. ``test_inspect_heartbeat_byte_stable_json_sort_order`` —
    multi-persona JSON output is sorted by persona_slug for
    byte-stable cross-invocation parity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirelang.persona.cli import (
    DEFAULT_HEARTBEAT_DIR,
    EXIT_HEARTBEAT_PARSE_FAILED,
    EXIT_INPUT_NOT_FOUND,
    HEARTBEAT_DIR_ENV_VAR,
    HEARTBEAT_FILENAME_SUFFIX,
    HEARTBEAT_REQUIRED_KEYS,
    PERSONA_FSM_STATES,
    PERSONA_HEARTBEAT_REPORT_SCHEMA_VERSION,
    build_parser,
    main,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_heartbeat_file(
    heartbeat_dir: Path,
    persona_slug: str,
    *,
    fsm_state: str = "running",
    last_heartbeat_at: str | None = "2026-05-16T19:00:00Z",
    v907_pin_current: str | None = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000001"
    ),
    v907_pin_expected: str | None = (
        "sha256:0000000000000000000000000000000000000000000000000000000000000001"
    ),
    subscribe_loop_active: bool = True,
    uptime_seconds: int | None = 3600,
) -> Path:
    """Write a synthetic heartbeat-state file. Returns the path written.

    Defaults yield a no-drift "healthy" heartbeat. Tests override
    individual fields for the drift / unknown / parse-failure paths.
    """
    payload = {
        "persona_slug": persona_slug,
        "fsm_state": fsm_state,
        "last_heartbeat_at": last_heartbeat_at,
        "v907_pin_current": v907_pin_current,
        "v907_pin_expected": v907_pin_expected,
        "subscribe_loop_active": subscribe_loop_active,
        "uptime_seconds": uptime_seconds,
    }
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    path = heartbeat_dir / f"{persona_slug}{HEARTBEAT_FILENAME_SUFFIX}"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Parser-surface introspection
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_parser_surface() -> None:
    """Parser exposes the inspect-heartbeat subcommand with the
    expected flag shape: --heartbeat default-True, --json default
    (output_format="json"), --persona / --heartbeat-dir / --quiet
    optional.
    """
    parser = build_parser()

    # Bare invocation: defaults all in place.
    ns = parser.parse_args(["inspect-heartbeat"])
    assert ns.command == "inspect-heartbeat"
    assert ns.heartbeat is True
    assert ns.output_format == "json"
    assert ns.persona is None
    assert ns.heartbeat_dir is None
    assert ns.quiet is False

    # --summary flips output_format.
    ns_summary = parser.parse_args(["inspect-heartbeat", "--summary"])
    assert ns_summary.output_format == "summary"

    # --json is the explicit-mode counterpart to --summary.
    ns_json = parser.parse_args(["inspect-heartbeat", "--json"])
    assert ns_json.output_format == "json"

    # --json and --summary are mutually exclusive.
    with pytest.raises(SystemExit):
        parser.parse_args(["inspect-heartbeat", "--json", "--summary"])


# ---------------------------------------------------------------------------
# 2. Empty heartbeat-directory (substrate booted, no personas yet)
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_empty_dir_is_zero_exit_empty_personas(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing-but-empty heartbeat-dir is NOT an error. The
    report emits a zero-personas envelope and exit-0.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    heartbeat_dir.mkdir()

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(heartbeat_dir), "--quiet"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload == {
        "personas": [],
        "report_schema_version": PERSONA_HEARTBEAT_REPORT_SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# 3. Single persona, no drift
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_single_persona_no_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single heartbeat-file whose current-pin == expected-pin
    yields v907_drift_detected=False and exit-0.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    _write_heartbeat_file(heartbeat_dir, "pengine")

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(heartbeat_dir), "--quiet"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert len(payload["personas"]) == 1
    entry = payload["personas"][0]
    assert entry["persona_slug"] == "pengine"
    assert entry["fsm_state"] == "running"
    assert entry["v907_drift_detected"] is False
    assert entry["subscribe_loop_active"] is True
    # Required keys are all present on the per-persona dict.
    assert HEARTBEAT_REQUIRED_KEYS.issubset(set(entry.keys()))


# ---------------------------------------------------------------------------
# 4. Drift detection (ADR-0058 §156 anchor)
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_drift_detected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat-file with disagreeing current/expected pins
    yields v907_drift_detected=True. Exit-code remains 0: drift is
    surfaced in the report, not signalled by exit code (the report
    is the verdict per ADR-0058 §156).
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    _write_heartbeat_file(
        heartbeat_dir,
        "pengine",
        v907_pin_current=(
            "sha256:dead000000000000000000000000000000000000000000000000000000000000"
        ),
        v907_pin_expected=(
            "sha256:beef000000000000000000000000000000000000000000000000000000000000"
        ),
    )

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(heartbeat_dir)]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    entry = payload["personas"][0]
    assert entry["v907_drift_detected"] is True
    # Progress line on stderr surfaces the drift count.
    assert "1 drift" in captured.err


# ---------------------------------------------------------------------------
# 5. --persona filter narrows scope
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_persona_filter_narrows_scope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat-dir with three files and ``--persona pengine``
    yields exactly one persona-entry in the report.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    _write_heartbeat_file(heartbeat_dir, "pengine")
    _write_heartbeat_file(heartbeat_dir, "kai")
    _write_heartbeat_file(heartbeat_dir, "aisha")

    exit_code = main(
        [
            "inspect-heartbeat",
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--persona",
            "pengine",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert len(payload["personas"]) == 1
    assert payload["personas"][0]["persona_slug"] == "pengine"


# ---------------------------------------------------------------------------
# 6. --persona <slug> but file missing -> exit 3
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_persona_filter_missing_file_exits_3(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--persona <slug>`` against a dir without that slug's file
    exits 3 with a 'heartbeat-file not found for persona' stderr.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    heartbeat_dir.mkdir()

    exit_code = main(
        [
            "inspect-heartbeat",
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--persona",
            "nonexistent-slug",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_INPUT_NOT_FOUND
    assert "nonexistent-slug" in captured.err
    assert "heartbeat-file not found" in captured.err


# ---------------------------------------------------------------------------
# 7. Heartbeat-dir does not exist -> exit 3
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_heartbeat_dir_not_found_exits_3(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--heartbeat-dir`` pointing at a non-existent path exits 3."""
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    missing = tmp_path / "does-not-exist"

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(missing)]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_INPUT_NOT_FOUND
    assert "heartbeat-dir not found" in captured.err


# ---------------------------------------------------------------------------
# 8. Malformed JSON -> exit 1
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_malformed_json_exits_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat-state file with corrupt JSON exits 1
    (EXIT_HEARTBEAT_PARSE_FAILED).
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    heartbeat_dir.mkdir()
    (heartbeat_dir / f"pengine{HEARTBEAT_FILENAME_SUFFIX}").write_text(
        "{this is not valid json", encoding="utf-8"
    )

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(heartbeat_dir)]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_HEARTBEAT_PARSE_FAILED
    assert "inspect-heartbeat parse failed" in captured.err


# ---------------------------------------------------------------------------
# 9. Missing required key -> exit 1
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_missing_required_key_exits_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat-state file missing a required key exits 1 with
    the missing-key list in the stderr diagnostic.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    heartbeat_dir.mkdir()
    # Missing fsm_state + uptime_seconds; the rest of the keys are
    # populated so we exercise the structural-validation path
    # rather than the JSON-parse path.
    incomplete = {
        "persona_slug": "pengine",
        "last_heartbeat_at": "2026-05-16T19:00:00Z",
        "v907_pin_current": None,
        "v907_pin_expected": None,
        "subscribe_loop_active": False,
    }
    (heartbeat_dir / f"pengine{HEARTBEAT_FILENAME_SUFFIX}").write_text(
        json.dumps(incomplete), encoding="utf-8"
    )

    exit_code = main(
        ["inspect-heartbeat", "--heartbeat-dir", str(heartbeat_dir)]
    )
    captured = capsys.readouterr()

    assert exit_code == EXIT_HEARTBEAT_PARSE_FAILED
    assert "missing required keys" in captured.err
    assert "fsm_state" in captured.err
    assert "uptime_seconds" in captured.err


# ---------------------------------------------------------------------------
# 10. --summary mode emits a tabular report
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_summary_mode_emits_table(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--summary`` emits a tabular (non-JSON) report. We assert
    on shape markers (column header tokens, persona-slugs present)
    rather than byte-exact lines because the summary format is
    declared NOT byte-stable across releases.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    _write_heartbeat_file(heartbeat_dir, "pengine")
    _write_heartbeat_file(heartbeat_dir, "kai", fsm_state="draining")

    exit_code = main(
        [
            "inspect-heartbeat",
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--summary",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    # Header tokens present.
    assert "PERSONA" in captured.out
    assert "FSM_STATE" in captured.out
    assert "V907_DRIFT" in captured.out
    # Both persona-slugs rendered.
    assert "pengine" in captured.out
    assert "kai" in captured.out
    # Output is NOT JSON.
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)


# ---------------------------------------------------------------------------
# 11. Env-var precedence: --heartbeat-dir > env > default
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_env_var_overrides_default_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """$WAKIR_PERSONA_HEARTBEAT_DIR is honoured when no CLI flag
    is given; the CLI flag wins over the env-var when both are set.
    """
    env_dir = tmp_path / "env-dir"
    cli_dir = tmp_path / "cli-dir"
    _write_heartbeat_file(env_dir, "from-env")
    _write_heartbeat_file(cli_dir, "from-cli")

    # 11a) env-var only: result reflects env-dir contents.
    monkeypatch.setenv(HEARTBEAT_DIR_ENV_VAR, str(env_dir))
    exit_env = main(["inspect-heartbeat", "--quiet"])
    captured_env = capsys.readouterr()
    payload_env = json.loads(captured_env.out)
    assert exit_env == 0
    assert [p["persona_slug"] for p in payload_env["personas"]] == ["from-env"]

    # 11b) env-var + CLI flag: CLI flag wins.
    exit_cli = main(
        [
            "inspect-heartbeat",
            "--heartbeat-dir",
            str(cli_dir),
            "--quiet",
        ]
    )
    captured_cli = capsys.readouterr()
    payload_cli = json.loads(captured_cli.out)
    assert exit_cli == 0
    assert [p["persona_slug"] for p in payload_cli["personas"]] == ["from-cli"]

    # Sanity: the default-dir constant is the documented path so
    # operators reading the help-text and the constant agree.
    assert DEFAULT_HEARTBEAT_DIR == Path("/var/run/wakir-persona")


# ---------------------------------------------------------------------------
# 12. Multi-persona JSON output is sorted by persona_slug (byte-stability)
# ---------------------------------------------------------------------------


def test_inspect_heartbeat_byte_stable_json_sort_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The personas list in the JSON output is sorted by persona_slug
    alphabetically, independent of file-creation order. This is the
    cross-invocation byte-stability anchor for the Phase-1c Rust
    mirror.
    """
    monkeypatch.delenv(HEARTBEAT_DIR_ENV_VAR, raising=False)
    heartbeat_dir = tmp_path / "wakir-persona"
    # Create out of alphabetical order: zara, aisha, mira.
    _write_heartbeat_file(heartbeat_dir, "zara")
    _write_heartbeat_file(heartbeat_dir, "aisha")
    _write_heartbeat_file(heartbeat_dir, "mira")

    exit_code = main(
        [
            "inspect-heartbeat",
            "--heartbeat-dir",
            str(heartbeat_dir),
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    slugs = [p["persona_slug"] for p in payload["personas"]]
    assert slugs == sorted(slugs)
    assert slugs == ["aisha", "mira", "zara"]

    # FSM-state canonical set is exposed as a constant so operators
    # / dashboards can pin it. Asserted here so a drift in the
    # constant trips this pack (cheap canary).
    assert "running" in PERSONA_FSM_STATES
    assert "unknown" in PERSONA_FSM_STATES
