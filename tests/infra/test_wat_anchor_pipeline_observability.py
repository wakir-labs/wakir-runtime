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
import math
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


# ---------------------------------------------------------------------------
# Per-anchor latency-histogram path (Tag-12 mini-welle).
# Exercises: window-size resolution, JSONL parsing, percentile correctness,
# histogram bucketization, JSON+Prom rendering, main() dispatch.
# ---------------------------------------------------------------------------


def _make_latency_line(
    *,
    enqueue_ms: float = 5.0,
    ots_ms: float = 250.0,
    post_commit_ms: float = 8.0,
    wat_write_ms: float = 12.0,
    anchor_root_hex: str = "00" * 32,
    timestamp: str = "2026-05-17T00:00:00+00:00",
) -> str:
    """Build one JSONL line in the contractual producer shape."""
    return (
        json.dumps(
            {
                "anchor_root_hex": anchor_root_hex,
                "timestamp": timestamp,
                "stages": {
                    "enqueue_to_pre_ots_ms": enqueue_ms,
                    "ots_call_ms": ots_ms,
                    "post_ots_commit_ms": post_commit_ms,
                    "wat_write_ms": wat_write_ms,
                },
            }
        )
        + "\n"
    )


# ---- resolve_window_size: CLI > ENV > default --------------------------


def test_resolve_window_size_cli_wins_over_env_and_default() -> None:
    assert obs.resolve_window_size(42, env={"WAKIR_OBS_WINDOW_SIZE": "7"}) == 42


def test_resolve_window_size_env_wins_when_cli_unset() -> None:
    assert obs.resolve_window_size(None, env={"WAKIR_OBS_WINDOW_SIZE": "250"}) == 250


def test_resolve_window_size_falls_back_to_default_for_garbage_env() -> None:
    assert obs.resolve_window_size(None, env={"WAKIR_OBS_WINDOW_SIZE": "abc"}) == obs.DEFAULT_WINDOW_SIZE
    assert obs.resolve_window_size(None, env={"WAKIR_OBS_WINDOW_SIZE": "0"}) == obs.DEFAULT_WINDOW_SIZE
    assert obs.resolve_window_size(None, env={"WAKIR_OBS_WINDOW_SIZE": "-5"}) == obs.DEFAULT_WINDOW_SIZE


def test_resolve_window_size_defaults_to_100() -> None:
    assert obs.resolve_window_size(None, env={}) == 100
    assert obs.DEFAULT_WINDOW_SIZE == 100


def test_resolve_window_size_zero_cli_falls_back_to_default() -> None:
    assert obs.resolve_window_size(0, env={}) == obs.DEFAULT_WINDOW_SIZE


# ---- read_latency_samples: file-tail with parse-defense ---------------


def test_read_latency_samples_missing_file_returns_empty(tmp_path: Path) -> None:
    assert obs.read_latency_samples(tmp_path / "does-not-exist.jsonl", window=10) == []


def test_read_latency_samples_empty_file_returns_empty(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text("")
    assert obs.read_latency_samples(src, window=10) == []


def test_read_latency_samples_zero_window_returns_empty(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(_make_latency_line())
    assert obs.read_latency_samples(src, window=0) == []


def test_read_latency_samples_returns_stage_seconds_dicts(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(_make_latency_line(enqueue_ms=10, ots_ms=500, post_commit_ms=4, wat_write_ms=2))
    samples = obs.read_latency_samples(src, window=10)
    assert len(samples) == 1
    # ms -> seconds conversion.
    assert samples[0]["enqueue_to_pre_ots"] == pytest.approx(0.010)
    assert samples[0]["ots_call"] == pytest.approx(0.500)
    assert samples[0]["post_ots_commit"] == pytest.approx(0.004)
    assert samples[0]["wat_write"] == pytest.approx(0.002)


def test_read_latency_samples_skips_malformed_lines(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(
        "not json\n"
        + _make_latency_line(ots_ms=100)
        + "[1, 2, 3]\n"  # JSON but not a dict
        + _make_latency_line(ots_ms=200)
        + '{"stages": "not a dict"}\n'  # dict but stages isn't
        + '{"stages": {"ots_call_ms": "garbage"}}\n'  # missing other stages
        + _make_latency_line(ots_ms=300)
    )
    samples = obs.read_latency_samples(src, window=10)
    # Three well-formed lines, others skipped.
    assert len(samples) == 3
    ots_values = [s["ots_call"] for s in samples]
    assert ots_values == [pytest.approx(0.1), pytest.approx(0.2), pytest.approx(0.3)]


def test_read_latency_samples_rejects_negative_and_nan(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(
        _make_latency_line(ots_ms=-50)  # negative -> rejected
        + json.dumps(
            {
                "anchor_root_hex": "00" * 32,
                "stages": {
                    "enqueue_to_pre_ots_ms": 1,
                    "ots_call_ms": float("nan"),
                    "post_ots_commit_ms": 1,
                    "wat_write_ms": 1,
                },
            }
        )
        + "\n"
        + _make_latency_line(ots_ms=100)  # this one is fine
    )
    samples = obs.read_latency_samples(src, window=10)
    assert len(samples) == 1
    assert samples[0]["ots_call"] == pytest.approx(0.1)


def test_read_latency_samples_returns_last_window_only(tmp_path: Path) -> None:
    """When the file has more lines than the window, we keep the most recent."""
    src = tmp_path / "lat.jsonl"
    src.write_text("".join(_make_latency_line(ots_ms=i) for i in range(1, 21)))
    samples = obs.read_latency_samples(src, window=5)
    assert len(samples) == 5
    # The window is the *last* five lines: ots_ms 16..20.
    ots_values = [s["ots_call"] * 1000.0 for s in samples]
    assert ots_values == pytest.approx([16, 17, 18, 19, 20])


def test_read_latency_samples_full_window_exact(tmp_path: Path) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text("".join(_make_latency_line(ots_ms=i) for i in range(1, 101)))
    samples = obs.read_latency_samples(src, window=100)
    assert len(samples) == 100


# ---- compute_percentile: nearest-rank correctness ---------------------


def test_compute_percentile_empty_returns_zero() -> None:
    assert obs.compute_percentile([], 50) == 0.0
    assert obs.compute_percentile([], 99) == 0.0


def test_compute_percentile_single_value_all_quantiles_same() -> None:
    assert obs.compute_percentile([0.42], 50) == 0.42
    assert obs.compute_percentile([0.42], 95) == 0.42
    assert obs.compute_percentile([0.42], 99) == 0.42


def test_compute_percentile_known_values_nearest_rank() -> None:
    # 10 values: 1..10. p50 nearest-rank = ceil(0.5*10)=5 -> idx 4 -> value 5.
    values = list(range(1, 11))
    assert obs.compute_percentile(values, 50) == 5
    # p95 = ceil(0.95*10)=10 -> idx 9 -> value 10.
    assert obs.compute_percentile(values, 95) == 10
    # p99 = ceil(0.99*10)=10 -> idx 9 -> value 10.
    assert obs.compute_percentile(values, 99) == 10
    # p10 = ceil(0.10*10)=1 -> idx 0 -> value 1.
    assert obs.compute_percentile(values, 10) == 1
    # p0 -> min.
    assert obs.compute_percentile(values, 0) == 1
    # p100 -> max.
    assert obs.compute_percentile(values, 100) == 10


def test_compute_percentile_handles_unsorted_input() -> None:
    values = [9, 1, 7, 3, 5, 2, 8, 4, 6, 10]
    assert obs.compute_percentile(values, 50) == 5
    assert obs.compute_percentile(values, 95) == 10


def test_compute_percentile_clamps_out_of_range() -> None:
    values = [1.0, 2.0, 3.0]
    assert obs.compute_percentile(values, -10) == 1.0  # clamped to 0
    assert obs.compute_percentile(values, 200) == 3.0  # clamped to 100


# ---- bucketize: Prometheus-style cumulative buckets -------------------


def test_bucketize_empty_emits_zero_counts_with_inf_terminator() -> None:
    buckets = obs.bucketize([])
    # Every bucket count is zero; final entry is +Inf with count 0.
    assert all(c == 0 for (_le, c) in buckets)
    assert math.isinf(buckets[-1][0])
    assert buckets[-1][1] == 0


def test_bucketize_monotonic_cumulative() -> None:
    values = [0.001, 0.05, 0.3, 1.5, 4.0]
    buckets = obs.bucketize(values)
    counts = [c for (_le, c) in buckets]
    # Cumulative -> monotonic non-decreasing.
    assert all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))
    # Final +Inf count equals total.
    assert counts[-1] == len(values)


def test_bucketize_known_distribution() -> None:
    # All five values fit inside le=5.0. The le=0.005 bucket catches the
    # 0.001 sample only.
    values = [0.001, 0.05, 0.3, 1.5, 4.0]
    buckets = dict(obs.bucketize(values))
    assert buckets[0.005] == 1
    assert buckets[0.05] == 2
    assert buckets[0.5] == 3
    assert buckets[5.0] == 5
    assert buckets[float("inf")] == 5


# ---- summarize_window + summarize_stage ------------------------------


def test_summarize_window_empty_returns_zero_shape() -> None:
    summary = obs.summarize_window([])
    assert summary["window_size"] == 0
    for stage in obs.PIPELINE_STAGES:
        s = summary["stages"][stage]
        assert s["count"] == 0
        assert s["sum_seconds"] == 0.0
        assert s["p50_seconds"] == 0.0
        assert s["p95_seconds"] == 0.0
        assert s["p99_seconds"] == 0.0


def test_summarize_window_single_sample_percentiles_equal_value() -> None:
    samples = [{"enqueue_to_pre_ots": 0.005, "ots_call": 0.5, "post_ots_commit": 0.008, "wat_write": 0.012}]
    summary = obs.summarize_window(samples)
    assert summary["window_size"] == 1
    assert summary["stages"]["ots_call"]["count"] == 1
    assert summary["stages"]["ots_call"]["p50_seconds"] == 0.5
    assert summary["stages"]["ots_call"]["p95_seconds"] == 0.5
    assert summary["stages"]["ots_call"]["p99_seconds"] == 0.5


def test_summarize_window_full_window_p50_p95_p99_correct() -> None:
    # 100 samples in the ots_call stage: linearly spaced 1ms..100ms.
    samples = [
        {
            "enqueue_to_pre_ots": 0.001,
            "ots_call": i / 1000.0,
            "post_ots_commit": 0.001,
            "wat_write": 0.001,
        }
        for i in range(1, 101)
    ]
    summary = obs.summarize_window(samples)
    s = summary["stages"]["ots_call"]
    assert s["count"] == 100
    # Nearest-rank: p50 -> idx 49 (value 50 ms), p95 -> idx 94 (95 ms),
    # p99 -> idx 98 (99 ms).
    assert s["p50_seconds"] == pytest.approx(0.050)
    assert s["p95_seconds"] == pytest.approx(0.095)
    assert s["p99_seconds"] == pytest.approx(0.099)


def test_summarize_window_partial_sample_skipped_per_stage() -> None:
    """A sample missing a stage value contributes nothing to that stage."""
    samples = [
        {"enqueue_to_pre_ots": 0.01, "ots_call": 0.1, "post_ots_commit": 0.02, "wat_write": 0.03},
        # second sample missing ots_call -> ots_call window stays at 1.
        {"enqueue_to_pre_ots": 0.02, "post_ots_commit": 0.04, "wat_write": 0.05},
    ]
    summary = obs.summarize_window(samples)
    assert summary["stages"]["ots_call"]["count"] == 1
    assert summary["stages"]["enqueue_to_pre_ots"]["count"] == 2


# ---- render_json_summary: shape + JSON-safety -------------------------


def test_render_json_summary_emits_valid_json_with_all_stages() -> None:
    samples = [
        {"enqueue_to_pre_ots": 0.005, "ots_call": 0.25, "post_ots_commit": 0.008, "wat_write": 0.012}
    ] * 10
    summary = obs.summarize_window(samples)
    payload = obs.render_json_summary(summary, scrape_ts_utc=1_747_500_000)
    doc = json.loads(payload)
    assert doc["schema_version"] == 1
    assert doc["scrape_timestamp_seconds"] == 1_747_500_000
    assert doc["window_size"] == 10
    for stage in obs.PIPELINE_STAGES:
        assert stage in doc["stages"]
        s = doc["stages"][stage]
        assert s["count"] == 10
        assert "p50_seconds" in s
        assert "p95_seconds" in s
        assert "p99_seconds" in s
        assert "buckets" in s
        # +Inf bucket is rendered as the string "+Inf" (JSON-safe).
        assert s["buckets"][-1]["le"] == "+Inf"


def test_render_json_summary_empty_window_renders_zero_shape() -> None:
    summary = obs.summarize_window([])
    payload = obs.render_json_summary(summary, scrape_ts_utc=1_747_500_000)
    doc = json.loads(payload)
    assert doc["window_size"] == 0
    for stage in obs.PIPELINE_STAGES:
        assert doc["stages"][stage]["count"] == 0


# ---- render_prom_histogram: format shape -----------------------------


def test_render_prom_histogram_emits_required_lines() -> None:
    samples = [
        {"enqueue_to_pre_ots": 0.005, "ots_call": 0.25, "post_ots_commit": 0.008, "wat_write": 0.012}
    ] * 10
    summary = obs.summarize_window(samples)
    out = obs.render_prom_histogram(summary, scrape_ts_utc=1_747_500_000)
    # Histogram type header present.
    assert "# TYPE wat_anchor_stage_latency_seconds histogram\n" in out
    # One bucket series per stage.
    for stage in obs.PIPELINE_STAGES:
        assert f'wat_anchor_stage_latency_seconds_bucket{{stage="{stage}",le="+Inf"}} 10\n' in out
        assert f'wat_anchor_stage_latency_seconds_count{{stage="{stage}"}} 10\n' in out
        # _sum series exists.
        assert f'wat_anchor_stage_latency_seconds_sum{{stage="{stage}"}}' in out
    # Pre-computed percentile gauges present per stage.
    for stage in obs.PIPELINE_STAGES:
        assert f'wat_anchor_stage_latency_p50_seconds{{stage="{stage}"}}' in out
        assert f'wat_anchor_stage_latency_p95_seconds{{stage="{stage}"}}' in out
        assert f'wat_anchor_stage_latency_p99_seconds{{stage="{stage}"}}' in out
    # Window-size + scrape-timestamp sidecars.
    assert "wat_anchor_latency_window_size 10\n" in out
    assert "wat_anchor_latency_scrape_timestamp_seconds 1747500000\n" in out


def test_render_prom_histogram_empty_window_still_emits_required_headers() -> None:
    summary = obs.summarize_window([])
    out = obs.render_prom_histogram(summary, scrape_ts_utc=1_747_500_000)
    assert "# TYPE wat_anchor_stage_latency_seconds histogram\n" in out
    for stage in obs.PIPELINE_STAGES:
        # All bucket counts are zero when the window is empty.
        assert f'wat_anchor_stage_latency_seconds_bucket{{stage="{stage}",le="+Inf"}} 0\n' in out
        assert f'wat_anchor_stage_latency_seconds_count{{stage="{stage}"}} 0\n' in out
    assert "wat_anchor_latency_window_size 0\n" in out


def test_render_prom_histogram_buckets_are_cumulative_per_stage() -> None:
    # Construct ots_call values that exercise the bucket boundaries.
    ots_values = [0.001, 0.003, 0.05, 0.4, 7.0]  # buckets: 0.005,0.005,0.05,0.5,10
    samples = [
        {"enqueue_to_pre_ots": 0.001, "ots_call": v, "post_ots_commit": 0.001, "wat_write": 0.001}
        for v in ots_values
    ]
    summary = obs.summarize_window(samples)
    out = obs.render_prom_histogram(summary, scrape_ts_utc=1_747_500_000)
    # le=0.005 -> 2 samples (0.001, 0.003)
    assert 'wat_anchor_stage_latency_seconds_bucket{stage="ots_call",le="0.005"} 2\n' in out
    # le=0.05 -> 3 samples
    assert 'wat_anchor_stage_latency_seconds_bucket{stage="ots_call",le="0.05"} 3\n' in out
    # le=0.5 -> 4 samples
    assert 'wat_anchor_stage_latency_seconds_bucket{stage="ots_call",le="0.5"} 4\n' in out
    # le=+Inf -> 5 samples
    assert 'wat_anchor_stage_latency_seconds_bucket{stage="ots_call",le="+Inf"} 5\n' in out


# ---- main() dispatch on --format -------------------------------------


def test_main_format_json_dry_run_emits_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(_make_latency_line(ots_ms=250) * 3)
    rc = obs.main(
        [
            "--format",
            "json",
            "--latency-source",
            str(src),
            "--window",
            "10",
            "--now",
            "1747500000",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    doc = json.loads(captured)
    assert doc["schema_version"] == 1
    assert doc["window_size"] == 3
    assert doc["stages"]["ots_call"]["count"] == 3
    assert doc["stages"]["ots_call"]["p99_seconds"] == pytest.approx(0.25)


def test_main_format_prom_writes_textfile(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lat.jsonl"
    src.write_text(_make_latency_line(ots_ms=100) * 4)
    target = tmp_path / "out" / "wat-lat.prom"
    rc = obs.main(
        [
            "--format",
            "prom",
            "--latency-source",
            str(src),
            "--window",
            "10",
            "--textfile-output",
            str(target),
            "--now",
            "1747500000",
        ]
    )
    assert rc == 0
    content = target.read_text()
    assert "# TYPE wat_anchor_stage_latency_seconds histogram\n" in content
    assert 'wat_anchor_stage_latency_seconds_count{stage="ots_call"} 4\n' in content
    assert "wat_anchor_latency_window_size 4\n" in content
    assert "wat_anchor_latency_scrape_timestamp_seconds 1747500000\n" in content


def test_main_format_json_to_stdout_when_textfile_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON + default textfile-output -> stdout (no clobber of receipt-emitter file)."""
    src = tmp_path / "lat.jsonl"
    src.write_text(_make_latency_line(ots_ms=50) * 2)
    rc = obs.main(
        [
            "--format",
            "json",
            "--latency-source",
            str(src),
            "--window",
            "10",
            "--now",
            "1747500000",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["window_size"] == 2


def test_main_legacy_path_unchanged_without_format(
    tmp_path: Path,
) -> None:
    """Omitting --format keeps the legacy receipt-emitter behavior (Tag-9 contract)."""
    target = tmp_path / "out" / "wat.prom"
    rc = obs.main(
        [
            "--textfile-output",
            str(target),
            "--cli-command",
            str(tmp_path / "missing-cli"),
            "--now",
            "1747500000",
        ]
    )
    assert rc == 0
    content = target.read_text()
    # Legacy gauge surface still present.
    assert "wat_anchor_cli_unavailable 1\n" in content
    assert "wat_anchor_pipeline_scrape_timestamp_seconds 1747500000\n" in content
    # New histogram series is *not* in the legacy path.
    assert "wat_anchor_stage_latency_seconds" not in content


def test_main_window_env_picked_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WAKIR_OBS_WINDOW_SIZE is honored when --window is unset."""
    src = tmp_path / "lat.jsonl"
    src.write_text("".join(_make_latency_line(ots_ms=i) for i in range(1, 21)))
    monkeypatch.setenv("WAKIR_OBS_WINDOW_SIZE", "5")
    rc = obs.main(
        [
            "--format",
            "json",
            "--latency-source",
            str(src),
            "--now",
            "1747500000",
            "--dry-run",
        ]
    )
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["window_size"] == 5
