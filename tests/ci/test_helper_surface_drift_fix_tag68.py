#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-68 Helper-Surface-Drift-Fix tests (Tomas, dev-engineering).

Pins the helper-surface contracts added in Tag-68 so the Tag-67
Pre-Cutover Live-Smoke (Noa, PR #425) Stage 2 + Stage 4 stop
emitting drift signals on Cutover-Eve:

  Stage 2 was yellow because Tag-57
  ``verify_watch_day_cron_pre_fire_readiness.py`` lacked a ``pin``
  mode (the Live-Smoke invokes ``--mode pin``).

  Stage 4 was red because Tag-62
  ``simulate_watch_day_operator_trigger.py`` lacked an ``emit``
  mode/subcommand (the Live-Smoke invokes ``--mode emit --output X``
  and inspects the resulting envelope for keys
  ``{event, workflow, ref, inputs}``).

This Tag-68 fix is additive: existing subcommand-style invocations
of the Tag-62 helper (``pre-trigger | trigger | post-trigger |
aggregate``) keep working, and Tag-57's ``all|cron|paths|routing``
modes are untouched.

The tests below cover:

  - the new Tag-57 ``pin`` mode happy-path on the live workflow,
    plus drift detection (cron drift, path-filter drift, workflow
    absence) by exercising the verifier against a synthetic
    workflow text;
  - the new Tag-62 ``emit`` mode envelope shape on both subcommand-
    style and ``--mode``-flag-style invocation surfaces;
  - argparse rewrite logic for ``--mode <name>`` to subcommand
    translation;
  - that the Live-Smoke workflow's stage-2 + stage-4 exact CLI
    invocations succeed on the current substrate (regression-pin
    for the actual caller-shape).

Anchor: Tag-68 Pre-KW-24 Cutover-Eve Helper-Surface-Drift-Fix.
Author: Tomas Reinhart (dev-engineering, Matrix-Lead).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve repo root from this test file's location.
REPO_ROOT = Path(__file__).resolve().parents[2]
TAG57_HELPER = REPO_ROOT / "tooling/ci/verify_watch_day_cron_pre_fire_readiness.py"
TAG62_HELPER = REPO_ROOT / "tooling/ci/simulate_watch_day_operator_trigger.py"

# Make helpers importable as modules so we can call their internals
# directly without paying subprocess cost for every shape assertion.
sys.path.insert(0, str(REPO_ROOT / "tooling/ci"))

import verify_watch_day_cron_pre_fire_readiness as tag57  # noqa: E402
import simulate_watch_day_operator_trigger as tag62  # noqa: E402


# ---------------------------------------------------------------------------
# Stage 2 / Tag-57 ``pin`` mode
# ---------------------------------------------------------------------------


def test_tag57_pin_mode_registered_in_argparse() -> None:
    """The Tag-57 helper's ``--mode`` argument must accept ``pin``."""
    parser = next(
        a for a in (sys.modules[tag57.__name__],) if a
    )
    # Build the actual parser by invoking with --help and inspecting
    # choices via subprocess (cleanest, avoids reaching into argparse
    # internals).
    result = subprocess.run(
        [sys.executable, str(TAG57_HELPER), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "pin" in result.stdout, "pin not advertised in --help output"


def test_tag57_pin_mode_green_on_current_substrate() -> None:
    """``--mode pin`` returns green/exit-0 on the current main HEAD."""
    result = subprocess.run(
        [sys.executable, str(TAG57_HELPER), "--mode", "pin"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"pin mode non-zero on current substrate: stderr={result.stderr}"
    )
    envelope = json.loads(result.stdout)
    assert envelope["mode"] == "pin"
    assert envelope["verdict"] == "READY"
    assert envelope["stages"]["pin"]["status"] == "green"
    assert envelope["stages"]["pin"]["cron_exact_match"] is True


def test_tag57_pin_mode_envelope_keys() -> None:
    """Pin envelope has the canonical schema we depend on."""
    result = subprocess.run(
        [sys.executable, str(TAG57_HELPER), "--mode", "pin"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    envelope = json.loads(result.stdout)
    for k in ("schema_version", "tag", "tool", "mode", "verdict", "stages"):
        assert k in envelope, f"missing top-level key {k}"
    pin = envelope["stages"]["pin"]
    for k in (
        "status",
        "workflow_present",
        "cron_expression",
        "cron_exact_match",
        "push_paths_complete",
        "pull_request_paths_complete",
        "push_pr_drift",
        "notes",
    ):
        assert k in pin, f"missing pin-stage key {k}"


def test_tag57_pin_red_when_workflow_absent(tmp_path: Path) -> None:
    """If the workflow file is gone, pin returns red/BLOCK."""
    # Synthesize a non-existent path; the helper opens it via
    # args.workflow.read_text and bails with exit 1 BEFORE reaching
    # the pin branch. That's intentional: missing substrate is
    # workflow-cant-read = exit 1 (red equivalent).
    result = subprocess.run(
        [
            sys.executable,
            str(TAG57_HELPER),
            "--mode",
            "pin",
            "--workflow",
            str(tmp_path / "does-not-exist.yml"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1, "missing workflow must be BLOCK (exit 1)"
    assert "cannot read workflow" in result.stderr


def test_tag57_pin_yellow_on_cron_drift(tmp_path: Path) -> None:
    """Cron drift with substrate present is yellow/CAUTION."""
    drifted = tmp_path / "drifted.yml"
    drifted.write_text(
        "\n".join(
            [
                "on:",
                "  schedule:",
                '    - cron: "0 6 * * 2"',  # drift: 06:00 not 05:00
                "  push:",
                "    paths:",
            ]
            + [
                f'      - "{p}"' for p in tag57.CANONICAL_PATH_FILTER_SET
            ]
            + [
                "  pull_request:",
                "    paths:",
            ]
            + [
                f'      - "{p}"' for p in tag57.CANONICAL_PATH_FILTER_SET
            ]
        )
        + "\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(TAG57_HELPER),
            "--mode",
            "pin",
            "--workflow",
            str(drifted),
            "--spec",
            "docs/observability/pre-cutover-watch-day-spec.md",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2, (
        f"cron drift must be CAUTION (exit 2), got {result.returncode}: "
        f"stderr={result.stderr}"
    )
    envelope = json.loads(result.stdout)
    assert envelope["verdict"] == "CAUTION"
    assert envelope["stages"]["pin"]["status"] == "yellow"
    assert envelope["stages"]["pin"]["cron_exact_match"] is False


def test_tag57_pin_yellow_on_path_filter_drift(tmp_path: Path) -> None:
    """Missing canonical path-filter substrate is yellow."""
    drifted = tmp_path / "drifted.yml"
    # Drop one canonical substrate from pull_request.paths.
    partial = list(tag57.CANONICAL_PATH_FILTER_SET[:-1])
    drifted.write_text(
        "\n".join(
            [
                "on:",
                "  schedule:",
                '    - cron: "0 5 * * 2"',
                "  push:",
                "    paths:",
            ]
            + [f'      - "{p}"' for p in tag57.CANONICAL_PATH_FILTER_SET]
            + [
                "  pull_request:",
                "    paths:",
            ]
            + [f'      - "{p}"' for p in partial]
        )
        + "\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(TAG57_HELPER),
            "--mode",
            "pin",
            "--workflow",
            str(drifted),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["stages"]["pin"]["pull_request_paths_complete"] is False
    assert envelope["stages"]["pin"]["push_paths_complete"] is True


def test_tag57_pin_red_on_missing_cron(tmp_path: Path) -> None:
    """Workflow without any cron line is red/BLOCK."""
    drifted = tmp_path / "nocron.yml"
    drifted.write_text("on:\n  push:\n    paths: []\n")
    result = subprocess.run(
        [
            sys.executable,
            str(TAG57_HELPER),
            "--mode",
            "pin",
            "--workflow",
            str(drifted),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1, "absent cron line must be BLOCK"
    envelope = json.loads(result.stdout)
    assert envelope["stages"]["pin"]["status"] == "red"
    assert "schedule_cron_missing" in envelope["stages"]["pin"]["notes"]


# ---------------------------------------------------------------------------
# Stage 4 / Tag-62 ``emit`` mode
# ---------------------------------------------------------------------------


def test_tag62_emit_subcommand_writes_canonical_envelope(tmp_path: Path) -> None:
    """``emit --output X`` writes the canonical dispatch envelope JSON."""
    out = tmp_path / "envelope.json"
    result = subprocess.run(
        [sys.executable, str(TAG62_HELPER), "emit", "--output", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"emit failed: stderr={result.stderr}"
    payload = json.loads(out.read_text(encoding="utf-8"))
    # Live-Smoke Stage 4 asserts this exact required-key-set.
    required = {"event", "workflow", "ref", "inputs"}
    assert required.issubset(payload.keys()), (
        f"emit envelope missing required keys: have {set(payload)}, need {required}"
    )
    assert payload["event"] == "workflow_dispatch"


def test_tag62_emit_mode_flag_style_works(tmp_path: Path) -> None:
    """``--mode emit --output X`` (the Live-Smoke caller-shape) works."""
    out = tmp_path / "envelope.json"
    result = subprocess.run(
        [
            sys.executable,
            str(TAG62_HELPER),
            "--mode",
            "emit",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"--mode-flag emit failed: stderr={result.stderr}"
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["event"] == "workflow_dispatch"
    assert payload["workflow"] == tag62.CANONICAL_WORKFLOW


def test_tag62_emit_mode_equal_style_works(tmp_path: Path) -> None:
    """``--mode=emit`` syntax also routes correctly."""
    out = tmp_path / "envelope.json"
    result = subprocess.run(
        [
            sys.executable,
            str(TAG62_HELPER),
            "--mode=emit",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert out.is_file()


def test_tag62_emit_envelope_self_check_aligned_with_stage_trigger() -> None:
    """The emitted envelope must pass the Stage-2 trigger validator.

    Single-source contract: build_dispatch_envelope() output is what
    stage_trigger() asserts as canonical. Drift between the two
    would break Tag-67 Stage 4 silently.
    """
    envelope = tag62.build_dispatch_envelope()
    result = tag62.stage_trigger(envelope)
    assert result.status == tag62.STAGE_GREEN, (
        f"canonical envelope failed self-check: notes={result.notes}"
    )


def test_tag62_existing_subcommands_still_work() -> None:
    """Tag-68 fix must NOT break existing pre-trigger/trigger/etc."""
    result = subprocess.run(
        [sys.executable, str(TAG62_HELPER), "trigger"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    # Stage 2 trigger on canonical inputs is green (exit 0).
    assert result.returncode == 0
    assert "stage_trigger: green" in result.stdout


def test_tag62_rewrite_mode_flag_passthrough() -> None:
    """Unknown --mode values are left alone for argparse to reject."""
    # Use the private helper directly to verify the rewrite logic.
    rewritten = tag62._rewrite_mode_flag(["--mode", "nonsense", "--output", "x"])
    assert rewritten == ["--mode", "nonsense", "--output", "x"]


def test_tag62_rewrite_mode_flag_subcommand_pristine() -> None:
    """Subcommand-style invocation is not rewritten."""
    rewritten = tag62._rewrite_mode_flag(["emit", "--output", "x"])
    assert rewritten == ["emit", "--output", "x"]


def test_tag62_rewrite_mode_flag_emit_translated() -> None:
    """``--mode emit ...`` becomes ``emit ...``."""
    rewritten = tag62._rewrite_mode_flag(["--mode", "emit", "--output", "x"])
    assert rewritten == ["emit", "--output", "x"]


# ---------------------------------------------------------------------------
# End-to-end Live-Smoke caller-shape regression-pin
# ---------------------------------------------------------------------------


def test_live_smoke_stage_2_exact_invocation_green() -> None:
    """Reproduces the exact Stage-2 shell call from the Live-Smoke YAML."""
    result = subprocess.run(
        [
            sys.executable,
            "tooling/ci/verify_watch_day_cron_pre_fire_readiness.py",
            "--mode",
            "pin",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    # Live-Smoke maps rc=0 -> green, rc=2 -> yellow, else red.
    # We require green (rc=0) on Tag-68 main HEAD.
    assert result.returncode == 0, (
        "Stage 2 caller-shape must be green on Tag-68 substrate; "
        f"got rc={result.returncode} stderr={result.stderr}"
    )


def test_live_smoke_stage_4_exact_invocation_writes_required_keys(
    tmp_path: Path,
) -> None:
    """Reproduces the exact Stage-4 shell call + key-set assertion."""
    out = tmp_path / "stage4_envelope.json"
    result = subprocess.run(
        [
            sys.executable,
            "tooling/ci/simulate_watch_day_operator_trigger.py",
            "--mode",
            "emit",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    required = {"event", "workflow", "ref", "inputs"}
    assert required.issubset(payload.keys())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
