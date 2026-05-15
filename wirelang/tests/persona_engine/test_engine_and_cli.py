# SPDX-License-Identifier: BUSL-1.1
"""Tests for the PersonaEngine orchestrator + CLI surface."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wirelang.persona_engine import __version__
from wirelang.persona_engine.cli import (
    EXIT_ENV_MISCONFIG,
    EXIT_INPUT_NOT_FOUND,
    EXIT_SUCCESS,
    build_parser,
    run_healthcheck,
    run_spawn,
    run_version,
)
from wirelang.persona_engine.engine import (
    ENGINE_VERSION,
    ENGINE_VARIANT,
    EnvContractError,
    PersonaEngine,
    resolve_env,
)


SAMPLE_AXIS_A = """---
name: tomas
description: Sample test persona
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

Body.
"""


# -------------------- engine version / variant --------------------


def test_engine_version_is_pilot_real():
    assert ENGINE_VERSION == "0.4.2-pilot"
    assert ENGINE_VARIANT == "real"
    assert __version__ == "0.4.2-pilot"


# -------------------- env resolution --------------------


def test_resolve_env_missing_persona_id_raises():
    with pytest.raises(EnvContractError):
        resolve_env(persona_id=None, env={})


def test_resolve_env_missing_org_id_raises():
    with pytest.raises(EnvContractError):
        resolve_env(
            persona_id="tomas",
            env={},
        )


def test_resolve_env_minimal_succeeds(tmp_path):
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
    }
    contract = resolve_env(env=env)
    assert contract.persona_id == "tomas"
    assert contract.org_id == "acme"
    # Default axis-A path under /etc/wakir/persona.
    assert contract.axis_a_path == Path("/etc/wakir/persona/tomas.md")


def test_resolve_env_axis_a_override(tmp_path):
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
        "WAKIR_PERSONA_AXIS_A_PATH": str(tmp_path / "tomas.md"),
    }
    contract = resolve_env(env=env)
    assert contract.axis_a_path == tmp_path / "tomas.md"


def test_resolve_env_persona_id_arg_overrides():
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
    }
    contract = resolve_env(persona_id="custom", env=env)
    assert contract.persona_id == "custom"


# -------------------- engine orchestration --------------------


def _engine_with_axis_a(tmp_path: Path) -> PersonaEngine:
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
        "WAKIR_PERSONA_AXIS_A_PATH": str(axis_a),
    }
    contract = resolve_env(env=env)
    return PersonaEngine(env_contract=contract, log_sink=io.StringIO())


def test_engine_boot_succeeds_with_valid_axis_a(tmp_path):
    engine = _engine_with_axis_a(tmp_path)
    engine.boot()
    assert engine.v907_result is not None
    assert engine.v907_result.mode == "real"
    assert engine.v907_result.pin.startswith("sha256:")
    assert engine.svid_probe is not None  # probed (socket absent in sandbox)


def test_engine_spawn_emits_first_engineering_output(tmp_path):
    engine = _engine_with_axis_a(tmp_path)
    engine.boot()
    engine.spawn()
    assert engine.fsm.state == "running"
    assert engine.bridge_writer is not None
    # The first emission was during spawn.
    log = engine.log_sink.getvalue()
    assert "engineering-output-emission-first" in log


def test_engine_despawn_clean_returns_uninstantiated(tmp_path):
    engine = _engine_with_axis_a(tmp_path)
    engine.boot()
    engine.spawn()
    engine.despawn_clean_run()
    assert engine.fsm.state == "uninstantiated"


# -------------------- CLI parser --------------------


def test_cli_parser_has_three_subcommands():
    p = build_parser()
    # Parser internals — just verify the three subcommands parse.
    args = p.parse_args(["spawn", "--persona-slug", "tomas"])
    assert args.command == "spawn"
    args = p.parse_args(["healthcheck"])
    assert args.command == "healthcheck"
    args = p.parse_args(["version"])
    assert args.command == "version"


def test_cli_version_returns_real_version(capsys):
    p = build_parser()
    args = p.parse_args(["version"])
    rc = run_version(args)
    out = capsys.readouterr().out
    assert rc == EXIT_SUCCESS
    assert "0.4.2-pilot" in out
    assert "real" in out


def test_cli_healthcheck_succeeds_with_persona_def_dir_present():
    """Healthcheck checks /etc/wakir/persona dir presence.

    In sandbox the dir does not exist; the cheap check returns 1.
    We patch the path to a real tmp dir to verify success path."""
    p = build_parser()
    args = p.parse_args(["healthcheck"])
    with patch(
        "wirelang.persona_engine.cli.Path",
        side_effect=lambda x: Path("/tmp"),  # always-exists
    ):
        rc = run_healthcheck(args)
    assert rc == EXIT_SUCCESS


def test_cli_spawn_missing_axis_a_returns_input_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv(
        "WAKIR_PERSONA_AXIS_A_PATH", str(tmp_path / "no-such.md")
    )
    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas", "--one-shot"])
    rc = run_spawn(args)
    assert rc == EXIT_INPUT_NOT_FOUND


def test_cli_spawn_missing_env_returns_env_misconfig(monkeypatch):
    monkeypatch.delenv("WAKIR_PERSONA_ID", raising=False)
    monkeypatch.delenv("WAKIR_ORG_ID", raising=False)
    p = build_parser()
    args = p.parse_args(["spawn", "--one-shot"])
    rc = run_spawn(args)
    assert rc == EXIT_ENV_MISCONFIG


def test_cli_spawn_one_shot_runs_full_cycle(tmp_path, monkeypatch):
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # force in-memory fence
    p = build_parser()
    args = p.parse_args(
        ["spawn", "--persona-slug", "tomas", "--one-shot"]
    )
    rc = run_spawn(args)
    assert rc == EXIT_SUCCESS


# -------------------- entrypoint shim (subprocess smoke) --------------------


def test_entrypoint_shim_runs_via_subprocess(tmp_path):
    """Smoke-test the bin/persona-engine-real shim via subprocess."""
    shim = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "persona-engine"
        / "bin"
        / "persona-engine-real"
    )
    assert shim.is_file()
    assert os.access(shim, os.X_OK)
    # Add the runtime tree to PYTHONPATH so the shim's lazy import works
    # outside the container.
    runtime_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(runtime_root)
    proc = subprocess.run(
        [sys.executable, str(shim), "version"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "0.4.2-pilot" in proc.stdout
