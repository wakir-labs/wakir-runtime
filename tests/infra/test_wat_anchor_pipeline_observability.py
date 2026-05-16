# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/wat-anchor-pipeline-observability.py.

Hermetic — no real ``wakir-anchor`` CLI, no real textfile-collector
directory. Drives the observability script's public functions against
fabricated CLI-output fixtures and asserts:

  - CLI-output JSON parsing (well-formed, trailing-log-prefix, garbage).
  - Receipt-field extraction with safe defaults for missing keys.
  - Spool-totals fall back to single-receipt counts when the CLI omits
    the ``spool_totals`` block.
  - Diagnostic-flag computation (schema-drift on unknown version or
    state, no drift on the happy path).
  - Snapshot construction handles: CLI missing on PATH, CLI exits
    non-zero, CLI exits zero with garbage stdout, CLI exits zero with
    valid JSON.
  - Prometheus exposition format: gauge schema matches the docs/
    appendix, null-ages render as -1, null-block-heights render as 0.
  - End-to-end ``main`` writes the textfile atomically.

The script is stdlib-only and lives outside the python package tree
under ``scripts/``. We import it via importlib.util so the hyphenated
filename stays legal.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Import the observability script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "wat-anchor-pipeline-observability.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "wat_anchor_pipeline_observability", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


obs = _load_module()


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------


def good_receipt_json(
    *,
    schema_version: int = 1,
    verifier_state: str = "finalized",
    bitcoin_block_height: int = 850000,
    calendar_attestations: int = 3,
    age_seconds_since_anchor: int = 3600,
    age_seconds_since_finalized: int = 1800,
    spool_finalized: int = 250,
    spool_pending: int = 2,
    spool_failed: int = 0,
) -> Dict[str, Any]:
    """Return the canonical ``--latest --json`` output for tests."""
    return {
        "schema_version": schema_version,
        "receipt_path": "meta/timestamps/wat/2026-05-16/root.bin.ots",
        "anchor_root_hex": (
            "abcdef0123456789abcdef0123456789"
            "abcdef0123456789abcdef0123456789"
        ),
        "verifier_state": verifier_state,
        "bitcoin_block_height": bitcoin_block_height,
        "bitcoin_block_hash": (
            "00000000000000000003b" + "0" * 44
        ),
        "calendar_attestations": calendar_attestations,
        "anchor_timestamp_utc": "2026-05-16T19:00:00+00:00",
        "finalized_timestamp_utc": "2026-05-16T19:30:00+00:00",
        "age_seconds_since_anchor": age_seconds_since_anchor,
        "age_seconds_since_finalized": age_seconds_since_finalized,
        "spool_totals": {
            "finalized": spool_finalized,
            "pending": spool_pending,
            "failed": spool_failed,
        },
    }


def pending_receipt_json() -> Dict[str, Any]:
    """A receipt that is still pending — null block height + finalized age."""
    return {
        "schema_version": 1,
        "receipt_path": "meta/timestamps/wat/2026-05-16/pending.bin.ots",
        "anchor_root_hex": (
            "fedcba9876543210fedcba9876543210"
            "fedcba9876543210fedcba9876543210"
        ),
        "verifier_state": "pending",
        "bitcoin_block_height": None,
        "bitcoin_block_hash": None,
        "calendar_attestations": 2,
        "anchor_timestamp_utc": "2026-05-16T20:30:00+00:00",
        "finalized_timestamp_utc": None,
        "age_seconds_since_anchor": 1500,
        "age_seconds_since_finalized": None,
        "spool_totals": {
            "finalized": 100,
            "pending": 1,
            "failed": 0,
        },
    }


# ---------------------------------------------------------------------------
# parse_cli_output
# ---------------------------------------------------------------------------


def test_parse_cli_output_well_formed_returns_dict() -> None:
    payload = json.dumps(good_receipt_json())
    parsed = obs.parse_cli_output(payload)
    assert parsed is not None
    assert parsed["schema_version"] == 1
    assert parsed["verifier_state"] == "finalized"


def test_parse_cli_output_empty_returns_none() -> None:
    assert obs.parse_cli_output("") is None
    assert obs.parse_cli_output("   \n  ") is None


def test_parse_cli_output_handles_log_prefix_before_json() -> None:
    """Older CLI fixtures occasionally emit a log line before the JSON."""
    payload = (
        "INFO: anchor-receipt subcommand starting\n"
        + json.dumps(good_receipt_json())
        + "\n"
    )
    parsed = obs.parse_cli_output(payload)
    assert parsed is not None
    assert parsed["verifier_state"] == "finalized"


def test_parse_cli_output_garbage_returns_none() -> None:
    assert obs.parse_cli_output("not json at all") is None
    assert obs.parse_cli_output("{ malformed") is None


def test_parse_cli_output_non_dict_returns_none() -> None:
    # A JSON array is valid JSON but not a receipt object.
    assert obs.parse_cli_output("[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# extract_receipt
# ---------------------------------------------------------------------------


def test_extract_receipt_full_shape() -> None:
    obj = good_receipt_json()
    rec = obs.extract_receipt(obj)
    assert rec["schema_version"] == 1
    assert rec["verifier_state"] == "finalized"
    assert rec["bitcoin_block_height"] == 850000
    assert rec["calendar_attestations"] == 3
    assert rec["age_seconds_since_anchor"] == 3600
    assert rec["age_seconds_since_finalized"] == 1800
    assert rec["spool_finalized"] == 250
    assert rec["spool_pending"] == 2
    assert rec["spool_failed"] == 0


def test_extract_receipt_missing_keys_get_safe_defaults() -> None:
    rec = obs.extract_receipt({})
    assert rec["schema_version"] is None
    assert rec["verifier_state"] == ""
    assert rec["bitcoin_block_height"] is None
    assert rec["calendar_attestations"] == 0
    assert rec["age_seconds_since_anchor"] is None
    assert rec["spool_finalized"] == 0
    assert rec["spool_pending"] == 0
    assert rec["spool_failed"] == 0


def test_extract_receipt_missing_spool_totals_derives_from_state() -> None:
    """Without ``spool_totals`` the script derives a 1-of-state-X estimate."""
    obj = good_receipt_json()
    obj.pop("spool_totals")
    rec = obs.extract_receipt(obj)
    # State was "finalized" -> spool_finalized=1, the others zero.
    assert rec["spool_finalized"] == 1
    assert rec["spool_pending"] == 0
    assert rec["spool_failed"] == 0


def test_extract_receipt_pending_state_no_spool_derives_to_pending() -> None:
    obj = pending_receipt_json()
    obj.pop("spool_totals")
    rec = obs.extract_receipt(obj)
    assert rec["spool_pending"] == 1
    assert rec["spool_finalized"] == 0
    assert rec["spool_failed"] == 0


def test_extract_receipt_pending_keeps_null_block_height_and_finalized_age() -> None:
    rec = obs.extract_receipt(pending_receipt_json())
    assert rec["bitcoin_block_height"] is None
    assert rec["age_seconds_since_finalized"] is None
    assert rec["age_seconds_since_anchor"] == 1500


def test_extract_receipt_wrong_type_fields_get_safe_defaults() -> None:
    """Defend against a CLI that emits the wrong type for a field."""
    obj: Dict[str, Any] = {
        "schema_version": "1",  # string, not int — drift signal
        "verifier_state": True,  # boolean, not str
        "bitcoin_block_height": "850000",  # string, not int
        "calendar_attestations": "three",  # garbage string
    }
    rec = obs.extract_receipt(obj)
    # All wrong-typed fields fall back to safe defaults.
    assert rec["schema_version"] is None
    assert rec["verifier_state"] == ""
    assert rec["bitcoin_block_height"] is None
    assert rec["calendar_attestations"] == 0


# ---------------------------------------------------------------------------
# diagnose_receipt
# ---------------------------------------------------------------------------


def test_diagnose_receipt_happy_path_no_drift() -> None:
    rec = obs.extract_receipt(good_receipt_json())
    diag = obs.diagnose_receipt(rec)
    assert diag["schema_drift"] == 0.0


def test_diagnose_receipt_unknown_schema_version_flags_drift() -> None:
    obj = good_receipt_json(schema_version=99)
    rec = obs.extract_receipt(obj)
    diag = obs.diagnose_receipt(rec)
    assert diag["schema_drift"] == 1.0


def test_diagnose_receipt_unknown_verifier_state_flags_drift() -> None:
    obj = good_receipt_json(verifier_state="zombie")
    rec = obs.extract_receipt(obj)
    diag = obs.diagnose_receipt(rec)
    assert diag["schema_drift"] == 1.0


def test_diagnose_receipt_pending_is_not_drift() -> None:
    rec = obs.extract_receipt(pending_receipt_json())
    diag = obs.diagnose_receipt(rec)
    assert diag["schema_drift"] == 0.0


# ---------------------------------------------------------------------------
# build_snapshot — drives the subprocess path via tiny shell-script fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cli_dir(tmp_path: Path) -> Path:
    """Build a directory holding the fake CLI scripts."""
    d = tmp_path / "fakecli"
    d.mkdir()
    return d


def _make_fake_cli(
    fake_cli_dir: Path, name: str, exit_code: int, stdout: str
) -> Path:
    """Write a tiny shell script that exits with ``exit_code`` and prints ``stdout``."""
    script = fake_cli_dir / name
    # Escape single quotes via the standard shell concat trick.
    safe_stdout = stdout.replace("'", "'\"'\"'")
    script.write_text(
        f"#!/bin/sh\nprintf '%s' '{safe_stdout}'\nexit {exit_code}\n"
    )
    script.chmod(0o755)
    return script


def test_build_snapshot_cli_unavailable_sets_unavailable_flag(
    tmp_path: Path,
) -> None:
    """Pointing the script at a non-existent binary sets cli_unavailable."""
    command = (str(tmp_path / "definitely-not-here"),)
    receipt, flags = obs.build_snapshot(command)
    assert flags["cli_unavailable"] == 1.0
    assert flags["cli_failure"] == 0.0
    assert receipt["spool_finalized"] == 0


def test_build_snapshot_cli_non_zero_sets_failure_flag(
    fake_cli_dir: Path,
) -> None:
    script = _make_fake_cli(
        fake_cli_dir, "wakir-anchor-fail", exit_code=2, stdout=""
    )
    receipt, flags = obs.build_snapshot((str(script),))
    assert flags["cli_unavailable"] == 0.0
    assert flags["cli_failure"] == 1.0
    assert receipt["spool_finalized"] == 0


def test_build_snapshot_cli_garbage_output_sets_failure_flag(
    fake_cli_dir: Path,
) -> None:
    script = _make_fake_cli(
        fake_cli_dir,
        "wakir-anchor-garbage",
        exit_code=0,
        stdout="not even close to json",
    )
    receipt, flags = obs.build_snapshot((str(script),))
    assert flags["cli_failure"] == 1.0
    assert receipt["spool_finalized"] == 0


def test_build_snapshot_happy_path_parses_full_receipt(
    fake_cli_dir: Path,
) -> None:
    payload = json.dumps(good_receipt_json())
    script = _make_fake_cli(
        fake_cli_dir, "wakir-anchor-ok", exit_code=0, stdout=payload
    )
    receipt, flags = obs.build_snapshot((str(script),))
    assert flags["cli_unavailable"] == 0.0
    assert flags["cli_failure"] == 0.0
    assert flags["schema_drift"] == 0.0
    assert receipt["spool_finalized"] == 250
    assert receipt["bitcoin_block_height"] == 850000


def test_build_snapshot_schema_drift_flag_propagates(
    fake_cli_dir: Path,
) -> None:
    payload = json.dumps(good_receipt_json(schema_version=999))
    script = _make_fake_cli(
        fake_cli_dir, "wakir-anchor-drift", exit_code=0, stdout=payload
    )
    _receipt, flags = obs.build_snapshot((str(script),))
    assert flags["schema_drift"] == 1.0
    assert flags["cli_failure"] == 0.0  # CLI ran fine, schema is the issue


# ---------------------------------------------------------------------------
# render_textfile
# ---------------------------------------------------------------------------


def test_render_textfile_happy_path_emits_documented_schema() -> None:
    rec = obs.extract_receipt(good_receipt_json())
    flags = obs.diagnose_receipt(rec)
    out = obs.render_textfile(rec, flags, scrape_ts_utc=1_747_400_000)
    # Every documented gauge name appears.
    for gauge in (
        "wat_anchor_finalized_count",
        "wat_anchor_pending_count",
        "wat_anchor_failed_count",
        "wat_anchor_calendar_attestations",
        "wat_last_anchor_age_seconds",
        "wat_last_finalized_age_seconds",
        "wat_bitcoin_block_height_latest",
        "wat_anchor_pipeline_schema_drift",
        "wat_anchor_cli_unavailable",
        "wat_anchor_pipeline_cli_failure",
        "wat_anchor_pipeline_scrape_timestamp_seconds",
    ):
        assert f"# TYPE {gauge} gauge\n" in out, gauge
        assert f"{gauge} " in out, gauge
    # Spot-check the numeric body matches the fixture.
    assert "wat_anchor_finalized_count 250\n" in out
    assert "wat_anchor_pending_count 2\n" in out
    assert "wat_bitcoin_block_height_latest 850000\n" in out
    assert "wat_anchor_pipeline_scrape_timestamp_seconds 1747400000\n" in out


def test_render_textfile_pending_renders_negative_ages_for_null() -> None:
    rec = obs.extract_receipt(pending_receipt_json())
    flags = obs.diagnose_receipt(rec)
    out = obs.render_textfile(rec, flags, scrape_ts_utc=1_747_400_000)
    # Pending receipt: anchor age known, finalized age null -> -1.
    assert "wat_last_anchor_age_seconds 1500\n" in out
    assert "wat_last_finalized_age_seconds -1\n" in out
    # Block height null -> 0.
    assert "wat_bitcoin_block_height_latest 0\n" in out


def test_render_textfile_unavailable_cli_zero_gauges_and_unavailable_flag() -> None:
    """When the CLI is unavailable the snapshot is the zero-shape."""
    rec = obs.empty_snapshot()
    flags = {"schema_drift": 0.0, "cli_unavailable": 1.0, "cli_failure": 0.0}
    out = obs.render_textfile(rec, flags, scrape_ts_utc=1_747_400_000)
    assert "wat_anchor_finalized_count 0\n" in out
    assert "wat_anchor_pending_count 0\n" in out
    assert "wat_anchor_cli_unavailable 1\n" in out
    assert "wat_anchor_pipeline_cli_failure 0\n" in out
    assert "wat_last_anchor_age_seconds -1\n" in out


def test_render_textfile_schema_drift_flag_renders_one() -> None:
    rec = obs.extract_receipt(good_receipt_json(schema_version=99))
    flags = obs.diagnose_receipt(rec)
    out = obs.render_textfile(rec, flags, scrape_ts_utc=1_747_400_000)
    assert "wat_anchor_pipeline_schema_drift 1\n" in out


def test_render_textfile_help_lines_present_for_every_gauge() -> None:
    rec = obs.extract_receipt(good_receipt_json())
    flags = obs.diagnose_receipt(rec)
    out = obs.render_textfile(rec, flags, scrape_ts_utc=1_747_400_000)
    # Every TYPE line must have a HELP partner directly above.
    lines = out.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("# TYPE "):
            assert idx >= 1
            assert lines[idx - 1].startswith("# HELP "), (idx, lines[idx - 1])


# ---------------------------------------------------------------------------
# resolve_cli_command + argparse plumbing
# ---------------------------------------------------------------------------


def test_resolve_cli_command_default_returns_canonical_tuple() -> None:
    cmd = obs.resolve_cli_command(None)
    assert cmd == obs.DEFAULT_CLI_COMMAND
    assert cmd[0] == "wakir-anchor"


def test_resolve_cli_command_empty_string_returns_default() -> None:
    cmd = obs.resolve_cli_command("   ")
    assert cmd == obs.DEFAULT_CLI_COMMAND


def test_resolve_cli_command_splits_on_whitespace() -> None:
    cmd = obs.resolve_cli_command("python3 -m wat.cmd.anchor_cli --latest --json")
    assert cmd == (
        "python3",
        "-m",
        "wat.cmd.anchor_cli",
        "--latest",
        "--json",
    )


# ---------------------------------------------------------------------------
# main — atomic write
# ---------------------------------------------------------------------------


def test_main_dry_run_writes_to_stdout_no_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "wat.prom"
    rc = obs.main(
        [
            "--textfile-output",
            str(target),
            "--cli-command",
            str(tmp_path / "missing-cli"),
            "--now",
            "1747400000",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert "wat_anchor_cli_unavailable 1\n" in captured
    assert not target.exists()


def test_main_writes_textfile_atomically(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out" / "wat.prom"
    rc = obs.main(
        [
            "--textfile-output",
            str(target),
            "--cli-command",
            str(tmp_path / "missing-cli"),
            "--now",
            "1747400000",
        ]
    )
    assert rc == 0
    assert target.is_file()
    content = target.read_text()
    assert "wat_anchor_pipeline_scrape_timestamp_seconds 1747400000\n" in content
    assert "wat_anchor_cli_unavailable 1\n" in content
    # Confirm no .tmp leftover beside the target.
    leftovers = [
        p.name for p in target.parent.iterdir() if p.name != target.name
    ]
    assert leftovers == [], leftovers


def test_main_with_happy_cli_subprocess_writes_correct_gauges(
    tmp_path: Path,
) -> None:
    payload = json.dumps(good_receipt_json())
    script = tmp_path / "wakir-anchor"
    safe_payload = payload.replace("'", "'\"'\"'")
    script.write_text(
        f"#!/bin/sh\nprintf '%s' '{safe_payload}'\nexit 0\n"
    )
    script.chmod(0o755)

    target = tmp_path / "out" / "wat.prom"
    rc = obs.main(
        [
            "--textfile-output",
            str(target),
            "--cli-command",
            str(script),
            "--now",
            "1747400000",
        ]
    )
    assert rc == 0
    content = target.read_text()
    assert "wat_anchor_finalized_count 250\n" in content
    assert "wat_anchor_pending_count 2\n" in content
    assert "wat_bitcoin_block_height_latest 850000\n" in content
    assert "wat_anchor_cli_unavailable 0\n" in content
    assert "wat_anchor_pipeline_cli_failure 0\n" in content
    assert "wat_anchor_pipeline_schema_drift 0\n" in content


def test_main_with_unwritable_output_returns_two(
    tmp_path: Path,
) -> None:
    # Point at a path whose parent is a regular file, not a directory.
    bad_parent = tmp_path / "not-a-dir"
    bad_parent.write_text("file, not directory")
    target = bad_parent / "wat.prom"
    rc = obs.main(
        [
            "--textfile-output",
            str(target),
            "--cli-command",
            str(tmp_path / "missing-cli"),
            "--now",
            "1747400000",
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# _format_value — defensive numeric rendering
# ---------------------------------------------------------------------------


def test_format_value_renders_ints_and_floats() -> None:
    assert obs._format_value(0) == "0"
    assert obs._format_value(42) == "42"
    assert obs._format_value(-1) == "-1"
    assert obs._format_value(3.0) == "3"
    assert obs._format_value(0.5) == "0.5"
    # Bool is an int subclass; defend against truthiness leaking in.
    assert obs._format_value(True) == "1"
    assert obs._format_value(False) == "0"
    # Non-numeric values render as 0 (gauge stays additive).
    assert obs._format_value("garbage") == "0"
    assert obs._format_value(None) == "0"
    # NaN does not render NaN — it renders 0.
    assert obs._format_value(float("nan")) == "0"
