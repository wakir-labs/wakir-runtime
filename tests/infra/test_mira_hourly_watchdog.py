# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/mira-hourly-watchdog.py — Sprint-Hourly-Wrapper-MINI.

Hermetic — no real systemd, no real /var/lib/node_exporter, no
real persona-engine, no real Anthropic API. Drives the watchdog's
public functions against fabricated telemetry + log fixtures and
asserts:

  - The Phase-2a-Folgeartefakt aggregator chain integrates into
    the watchdog cycle: a healthy ENV-toggle + non-empty log
    substrate -> subprocess invocation, env-disabled -> no
    invocation, missing aggregator script -> graceful tolerance,
    missing log substrate -> graceful skip.
  - The aggregator chain reports back a structured-dict shape
    suitable for ingestion by the operator stderr trail.
  - The combined watchdog + aggregator output pattern is stable
    so downstream parsers (Kai's node-exporter substrate, the
    operator's eyeballs) can rely on it.

The watchdog script is stdlib-only and lives outside the python
package tree under ``scripts/``. We import it via importlib.util
so the hyphenated filename stays legal.

Scope clarifier: this module's net-new coverage targets the
aggregator-integration surface introduced by the
hourly-wrapper-erweiterung-MINI sprint. Older unit-level
behaviour (telemetry parsing, textfile rendering, ntfy edge
detection) is exercised end-to-end via the combined-output test
at the tail of this module rather than duplicated here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Import the watchdog script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_PATH = REPO_ROOT / "scripts" / "mira-hourly-watchdog.py"


def _load_watchdog_module():
    spec = importlib.util.spec_from_file_location(
        "mira_hourly_watchdog", WATCHDOG_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


watchdog = _load_watchdog_module()


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------


def _write_log(path: Path, *, content: str = '{"event":"ok"}\n') -> Path:
    """Create a non-empty persona-engine log substrate fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_fake_aggregator(
    dest_dir: Path,
    name: str,
    *,
    exit_code: int = 0,
    stdout: str = "",
) -> Path:
    """Drop an executable stand-in script with deterministic exit shape.

    The watchdog invokes aggregator scripts via ``sys.executable
    <path>``, so a plain ``.py`` file that imports nothing and
    exits with a chosen code is the smallest possible stand-in
    that exercises the subprocess plumbing.
    """
    script = dest_dir / name
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
    return script


def _telemetry_record(
    *,
    ts_utc: str = "2026-05-16T19:00:00+00:00",
    is_error: bool = False,
    num_turns: int = 12,
    duration_ms: int = 18000,
    total_cost_usd: float = 0.42,
) -> Dict[str, Any]:
    return {
        "timestamp_utc": ts_utc,
        "is_error": is_error,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
        "total_cost_usd": total_cost_usd,
        "session_id": "hermetic-test",
    }


def _write_telemetry(path: Path, records: List[Dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r) for r in records) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test 1 — Aggregator integration with mock subprocess
# ---------------------------------------------------------------------------


def test_aggregator_chain_invokes_both_aggregators_in_order(
    tmp_path: Path,
) -> None:
    """Healthy enable -> both aggregators invoked, results captured.

    Asserts the subprocess plumbing surface: each aggregator is
    invoked exactly once, the order is cost-first then cache-rate,
    and the structured-report carries one result entry per
    aggregator with ``ok=True`` and the expected reason string.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _write_fake_aggregator(scripts_dir, "per-model-cost-aggregator.py")
    _write_fake_aggregator(scripts_dir, "cache-hit-rate-aggregator.py")
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")

    invoked: List[str] = []
    real_run = subprocess.run

    def _spy_run(cmd, *args, **kwargs):
        # Capture which aggregator filename ran; delegate to the
        # real subprocess so the exit-code path stays exercised.
        invoked.append(Path(cmd[1]).name)
        return real_run(cmd, *args, **kwargs)

    with mock.patch.object(watchdog.subprocess, "run", side_effect=_spy_run):
        report = watchdog.run_hourly_aggregator_chain(
            scripts_dir=scripts_dir,
            persona_engine_log_path=log_path,
            env={},  # ENV unset -> log-substrate-gated default-on
        )

    assert report["enabled"] is True
    assert report["enable_reason"] == "env-default-enabled"
    assert invoked == [
        "per-model-cost-aggregator.py",
        "cache-hit-rate-aggregator.py",
    ]
    assert len(report["results"]) == 2
    assert all(r["ok"] is True for r in report["results"])
    assert (
        report["results"][0]["reason"]
        == "aggregator-ok:per-model-cost-aggregator.py"
    )
    assert (
        report["results"][1]["reason"]
        == "aggregator-ok:cache-hit-rate-aggregator.py"
    )


# ---------------------------------------------------------------------------
# Test 2 — ENV toggle (1 / 0 / unset / unknown)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_value,expected_enabled,expected_reason_prefix",
    [
        ("1", True, "env-enabled-explicit"),
        ("true", True, "env-enabled-explicit"),
        ("on", True, "env-enabled-explicit"),
        ("0", False, "env-disabled"),
        ("false", False, "env-disabled"),
        ("off", False, "env-disabled"),
        ("no", False, "env-disabled"),
        ("garbage", True, "env-unknown-value-default-on"),
    ],
)
def test_env_toggle_decides_aggregator_chain(
    tmp_path: Path,
    env_value: str,
    expected_enabled: bool,
    expected_reason_prefix: str,
) -> None:
    """ENV-toggle matrix: explicit-on / explicit-off / unknown-default-on.

    Critical reliability invariant: an operator with shell access
    must be able to silence the aggregator chain at the systemd-
    unit ``Environment=`` line without code edits, and the gate
    must record *why* it took its decision so a post-incident
    review can reconstruct the operator intent without re-running.
    """
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")
    enabled, reason = watchdog._hourly_aggregators_enabled(
        env={watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: env_value},
        persona_engine_log_path=log_path,
    )
    assert enabled is expected_enabled
    assert reason.startswith(expected_reason_prefix)


def test_env_toggle_explicit_enabled_overrides_missing_log(
    tmp_path: Path,
) -> None:
    """env=1 forces the chain even without a log substrate.

    Useful for hermetic CI smoke runs that drive the aggregators
    with their own ``--log-path`` overrides while the watchdog
    sits upstream.
    """
    missing_log = tmp_path / "nope" / "persona-engine.jsonl"
    enabled, reason = watchdog._hourly_aggregators_enabled(
        env={watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: "1"},
        persona_engine_log_path=missing_log,
    )
    assert enabled is True
    assert reason == "env-enabled-explicit"


# ---------------------------------------------------------------------------
# Test 3 — Missing aggregator script tolerance
# ---------------------------------------------------------------------------


def test_missing_aggregator_script_is_tolerated(tmp_path: Path) -> None:
    """A missing aggregator file -> ok=False with diagnostic reason.

    The watchdog's primary mission (textfile + state + ntfy) must
    not be jeopardised by a Folgeartefakt aggregator that has
    been removed or renamed mid-deployment. We assert the chain
    returns a structured-report -- not a raised exception -- and
    the failure reason names the missing file so an operator can
    chase it.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    # Drop only one of the two expected aggregators.
    _write_fake_aggregator(scripts_dir, "per-model-cost-aggregator.py")
    # cache-hit-rate-aggregator.py deliberately absent.
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")

    report = watchdog.run_hourly_aggregator_chain(
        scripts_dir=scripts_dir,
        persona_engine_log_path=log_path,
        env={watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: "1"},
    )

    assert report["enabled"] is True
    assert len(report["results"]) == 2
    # First aggregator present -> ok.
    assert report["results"][0]["ok"] is True
    # Second aggregator missing -> ok=False, reason names the file.
    assert report["results"][1]["ok"] is False
    assert "aggregator-missing" in report["results"][1]["reason"]
    assert "cache-hit-rate-aggregator.py" in report["results"][1]["reason"]


def test_aggregator_nonzero_exit_is_tolerated(tmp_path: Path) -> None:
    """A non-zero exit from an aggregator is reported, not raised.

    Same reliability principle as the missing-script case: the
    watchdog cycle completes, but the structured-report carries
    the failure so the downstream operator stream can alert.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _write_fake_aggregator(
        scripts_dir, "per-model-cost-aggregator.py", exit_code=0
    )
    _write_fake_aggregator(
        scripts_dir, "cache-hit-rate-aggregator.py", exit_code=7
    )
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")

    report = watchdog.run_hourly_aggregator_chain(
        scripts_dir=scripts_dir,
        persona_engine_log_path=log_path,
        env={watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: "1"},
    )

    assert report["results"][0]["ok"] is True
    assert report["results"][1]["ok"] is False
    assert "aggregator-nonzero" in report["results"][1]["reason"]
    assert "rc=7" in report["results"][1]["reason"]


# ---------------------------------------------------------------------------
# Test 4 — Missing-log-dir tolerance (graceful skip)
# ---------------------------------------------------------------------------


def test_missing_log_substrate_skips_chain_gracefully(tmp_path: Path) -> None:
    """No log file -> chain disabled, no subprocess invoked.

    The default deployment posture is "enable if logs exist". A
    fresh deployment with no Anthropic traffic yet must not page
    on absent aggregator output; the chain skips silently with a
    machine-readable reason.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _write_fake_aggregator(scripts_dir, "per-model-cost-aggregator.py")
    _write_fake_aggregator(scripts_dir, "cache-hit-rate-aggregator.py")
    missing_log = tmp_path / "logs" / "persona-engine.jsonl"

    with mock.patch.object(watchdog.subprocess, "run") as run_mock:
        report = watchdog.run_hourly_aggregator_chain(
            scripts_dir=scripts_dir,
            persona_engine_log_path=missing_log,
            env={},
        )

    assert report["enabled"] is False
    assert report["enable_reason"] == "log-substrate-empty"
    assert report["results"] == []
    run_mock.assert_not_called()


def test_empty_log_file_skips_chain(tmp_path: Path) -> None:
    """A zero-byte log file is treated as 'no traffic yet'."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    log_path = tmp_path / "logs" / "persona-engine.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    enabled, reason = watchdog._hourly_aggregators_enabled(
        env={},
        persona_engine_log_path=log_path,
    )
    assert enabled is False
    assert reason == "log-substrate-empty"


# ---------------------------------------------------------------------------
# Test 5 — Combined watchdog + aggregator output pattern (end-to-end)
# ---------------------------------------------------------------------------


def test_main_end_to_end_emits_combined_watchdog_and_chain_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end ``main()``: textfile + state + aggregator-report on stderr.

    Asserts the combined output contract three downstream readers
    rely on:

      1. The Prometheus textfile at ``--textfile-output`` exists,
         is atomically replaced (no .tmp leftover), and carries
         the four documented gauges.
      2. The state file at ``--state-file`` is a valid JSON dict.
      3. The aggregator-chain stderr line is a single line prefixed
         ``mira-hourly-watchdog: aggregator-chain `` followed by
         a JSON object that round-trips through ``json.loads``.

    Run mode: a known-good telemetry record + a non-empty
    persona-engine log substrate + the env explicitly enabled so
    the chain reliably fires regardless of CI cwd.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _write_fake_aggregator(scripts_dir, "per-model-cost-aggregator.py")
    _write_fake_aggregator(scripts_dir, "cache-hit-rate-aggregator.py")
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")
    telemetry_path = _write_telemetry(
        tmp_path / "infra" / "mira-hourly-telemetry.jsonl",
        [_telemetry_record()],
    )
    textfile_path = tmp_path / "out" / "mira_hourly_watchdog.prom"
    state_path = tmp_path / "state" / "mira-hourly-watchdog-state.json"

    # Pin "now" to 60s after the telemetry timestamp so age math is
    # deterministic and the watchdog reports healthy.
    # 2026-05-16T19:00:00+00:00 = epoch 1778958000
    now_epoch = 1778958060  # 2026-05-16T19:01:00+00:00

    env_overlay = {
        watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: "1",
    }
    with mock.patch.dict(os.environ, env_overlay, clear=False):
        rc = watchdog.main(
            [
                "--telemetry-path",
                str(telemetry_path),
                "--textfile-output",
                str(textfile_path),
                "--state-file",
                str(state_path),
                "--persona-engine-log-path",
                str(log_path),
                "--scripts-dir",
                str(scripts_dir),
                "--now",
                str(now_epoch),
            ]
        )
    assert rc == 0

    # (1) textfile
    text = textfile_path.read_text(encoding="utf-8")
    assert "mira_hourly_last_tick_age_seconds 60" in text
    assert "mira_hourly_last_tick_success 1" in text
    assert "mira_hourly_consecutive_abort_count 0" in text
    assert "mira_hourly_watchdog_unhealthy 0" in text
    # Atomic write -> no .tmp leftover next to the target.
    leftovers = list(textfile_path.parent.glob(textfile_path.name + ".*.tmp"))
    assert leftovers == [], f"atomic_write left tmp files: {leftovers}"

    # (2) state
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["unhealthy"] is False
    assert state["consecutive_abort_count"] == 0

    # (3) aggregator-chain stderr line
    err = capsys.readouterr().err
    chain_lines = [
        line
        for line in err.splitlines()
        if line.startswith("mira-hourly-watchdog: aggregator-chain {")
    ]
    assert len(chain_lines) == 1, (
        f"expected exactly one aggregator-chain stderr line, got: {err!r}"
    )
    payload = chain_lines[0][len("mira-hourly-watchdog: aggregator-chain ") :]
    chain = json.loads(payload)
    assert chain["enabled"] is True
    assert chain["enable_reason"] == "env-enabled-explicit"
    assert {r["script"] for r in chain["results"]} == {
        "per-model-cost-aggregator.py",
        "cache-hit-rate-aggregator.py",
    }
    assert all(r["ok"] is True for r in chain["results"])


def test_main_skip_aggregators_flag_suppresses_chain(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--skip-aggregators`` short-circuits the chain even when ENV=1.

    Single-invocation opt-out for hermetic CI smoke runs that only
    exercise the watchdog signal. Asserted via the absence of the
    aggregator-chain stderr line *and* the presence of the skip-
    notice line.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    # Aggregators present so absence-skip cannot be confused with
    # the skip-flag path.
    _write_fake_aggregator(scripts_dir, "per-model-cost-aggregator.py")
    _write_fake_aggregator(scripts_dir, "cache-hit-rate-aggregator.py")
    log_path = _write_log(tmp_path / "logs" / "persona-engine.jsonl")
    telemetry_path = _write_telemetry(
        tmp_path / "infra" / "mira-hourly-telemetry.jsonl",
        [_telemetry_record()],
    )
    textfile_path = tmp_path / "out" / "mira_hourly_watchdog.prom"
    state_path = tmp_path / "state" / "mira-hourly-watchdog-state.json"

    env_overlay = {watchdog.HOURLY_AGGREGATORS_ENABLED_ENV: "1"}
    with mock.patch.dict(os.environ, env_overlay, clear=False):
        rc = watchdog.main(
            [
                "--telemetry-path",
                str(telemetry_path),
                "--textfile-output",
                str(textfile_path),
                "--state-file",
                str(state_path),
                "--persona-engine-log-path",
                str(log_path),
                "--scripts-dir",
                str(scripts_dir),
                "--skip-aggregators",
                "--now",
                "1778958060",
            ]
        )
    assert rc == 0
    err = capsys.readouterr().err
    assert "aggregator-chain skipped via --skip-aggregators" in err
    chain_lines = [
        line
        for line in err.splitlines()
        if line.startswith("mira-hourly-watchdog: aggregator-chain {")
    ]
    assert chain_lines == []
