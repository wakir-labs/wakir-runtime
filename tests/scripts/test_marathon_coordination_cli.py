# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/marathon-coordination-cli.py — Tag-43.

Hermetic, stdlib + pytest only. The CLI module is loaded via
importlib from its hyphenated path under ``scripts/phase-3c/``.

The substrate subprocess seam is stubbed in every test via the
``runner=`` keyword on ``main()`` / ``CLIContext`` so no real
subprocess is spawned. A small fake ``CompletedProcess`` mirrors
the ``subprocess.run`` return surface.

Scope (15 tests)
----------------

 1. test_module_loads_and_exports_public_surface
 2. test_validate_welle_accepts_1_through_7_and_rejects_others
 3. test_detect_sandbox_stub_mode_when_ssh_bin_true
 4. test_detect_sandbox_stub_mode_when_ssh_key_missing
 5. test_resolve_substrate_known_keys_and_welle_template
 6. test_resolve_substrate_unknown_key_raises_precond
 7. test_cmd_status_invokes_tracker_and_parses_table_rows
 8. test_cmd_status_returns_precond_when_tracker_missing
 9. test_cmd_probe_single_welle_dry_run_dispatches_bash
10. test_cmd_probe_all_aggregates_seven_results
11. test_cmd_dryrun_passes_up_to_welle_flag_through
12. test_cmd_cutover_dry_run_default_does_not_require_confirm
13. test_cmd_cutover_live_refused_without_confirm_in_stub_mode
14. test_cmd_signoff_writes_marker_and_is_idempotent_on_replay
15. test_cmd_complete_check_blocks_when_signoffs_missing_then_ready
16. test_cmd_complete_preview_does_not_write_marker
17. test_cmd_complete_live_refused_in_stub_mode
18. test_render_envelope_json_and_table_paths
19. test_main_smoke_status_table_output_and_exit_zero
20. test_main_rejects_unknown_subcommand_with_precond_exit_three
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "phase-3c" / "marathon-coordination-cli.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "marathon_coordination_cli", CLI_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cli = _load_cli_module()


# ---------------------------------------------------------------------------
# Test helpers — fake subprocess runner
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runner(
    *,
    rc: int = 0,
    stdout: str = "",
    stderr: str = "",
    record: Optional[List[Sequence[str]]] = None,
):
    """Return a subprocess.run-compatible callable.

    All calls record their argv into ``record`` (if provided) and
    return a ``_FakeCompleted`` with the configured fields.
    """

    def _call(argv, **kw):
        if record is not None:
            record.append(list(argv))
        return _FakeCompleted(returncode=rc, stdout=stdout, stderr=stderr)

    return _call


def _runner_by_path(mapping: Dict[str, _FakeCompleted]):
    """Return a runner that dispatches based on the argv[1]/argv[-1] suffix."""

    def _call(argv, **kw):
        argv = list(argv)
        for needle, completed in mapping.items():
            if any(needle in str(part) for part in argv):
                return completed
        return _FakeCompleted(returncode=0, stdout="", stderr="")

    return _call


def _seed_substrate_layout(tmp_path: Path, *, welle_probes=range(1, 8)) -> Path:
    """Create a faux repo layout under ``tmp_path`` with the substrate
    files the CLI expects to find. Returns the repo root."""

    root = tmp_path / "repo"
    (root / "scripts" / "phase-3c").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "state").mkdir(parents=True)

    (root / "scripts" / "phase-3c" / "marathon-aggregat-tracker.py").write_text(
        "# stub\n", encoding="utf-8"
    )
    (root / "scripts" / "phase-3c" / "cross-welle-cutover-generalprobe.py").write_text(
        "# stub\n", encoding="utf-8"
    )
    (root / "scripts" / "phase-3c" / "live-vm-cutover-drill.sh").write_text(
        "#!/usr/bin/env bash\n", encoding="utf-8"
    )
    for n in welle_probes:
        (root / "scripts" / "phase-3c" / f"welle-{n}-pre-cutover-probe.sh").write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )
    (root / ".github" / "workflows" / "phase-3-complete-marker.yml").write_text(
        "# stub\n", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    expected = {
        "SCHEMA_VERSION",
        "WELLE_INDEXES",
        "WELLE_METADATA",
        "SUBSTRATE_PATHS",
        "SUB_COMMANDS",
        "CONFIRMATION_PHRASE",
        "CLIContext",
        "Envelope",
        "PrecondError",
        "ConfirmationError",
        "validate_welle",
        "detect_sandbox_stub_mode",
        "resolve_substrate",
        "run_substrate",
        "cmd_status",
        "cmd_probe",
        "cmd_dryrun",
        "cmd_cutover",
        "cmd_signoff",
        "cmd_complete_check",
        "cmd_complete",
        "render_envelope",
        "build_parser",
        "main",
    }
    missing = expected - set(dir(cli))
    assert not missing, f"missing public symbols: {sorted(missing)}"
    assert cli.WELLE_INDEXES == (1, 2, 3, 4, 5, 6, 7)
    assert cli.CONFIRMATION_PHRASE == "I-CONFIRM-LIVE-CUTOVER"


def test_validate_welle_accepts_1_through_7_and_rejects_others():
    for n in range(1, 8):
        assert cli.validate_welle(n) == n
    for bad in (0, 8, -1, "x", None):
        with pytest.raises(cli.PrecondError):
            cli.validate_welle(bad)


def test_detect_sandbox_stub_mode_when_ssh_bin_true(tmp_path):
    env = {"WAKIR_SSH_BIN": "true"}
    assert cli.detect_sandbox_stub_mode(env) is True


def test_detect_sandbox_stub_mode_when_ssh_key_missing(tmp_path):
    key = tmp_path / "no-such-key"
    env = {"WAKIR_PILOT_SSH_KEY": str(key)}
    assert cli.detect_sandbox_stub_mode(env) is True

    key.write_text("ssh-key-blob\n", encoding="utf-8")
    env2 = {"WAKIR_PILOT_SSH_KEY": str(key)}
    assert cli.detect_sandbox_stub_mode(env2) is False


def test_resolve_substrate_known_keys_and_welle_template(tmp_path):
    root = tmp_path / "repo"
    tracker = cli.resolve_substrate(root, "tracker")
    assert tracker == root / "scripts" / "phase-3c" / "marathon-aggregat-tracker.py"

    probe = cli.resolve_substrate(root, "probe_template", welle=3)
    assert probe.name == "welle-3-pre-cutover-probe.sh"

    signoff = cli.resolve_substrate(root, "signoff_template", welle=5)
    assert signoff.name == "welle-5-sign-off.json"


def test_resolve_substrate_unknown_key_raises_precond(tmp_path):
    with pytest.raises(cli.PrecondError):
        cli.resolve_substrate(tmp_path, "nonexistent-substrate")
    with pytest.raises(cli.PrecondError):
        # missing welle for a templated key
        cli.resolve_substrate(tmp_path, "probe_template")


def test_cmd_status_invokes_tracker_and_parses_table_rows(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    fake_stdout = (
        "Marathon: 3/7 pending\n"
        "Welle 1 | pre-flight-green | v907_verify\n"
        "Welle 2 | pending          | svid_workload_identity\n"
        "Welle 3 | pending          | bridge_audit_writer\n"
    )
    record: List[Sequence[str]] = []
    ctx = cli.CLIContext(
        repo_root=root,
        stub_mode=True,
        runner=_runner(rc=0, stdout=fake_stdout, record=record),
    )
    env = cli.cmd_status(ctx)
    assert env.exit_code == 0
    assert env.verdict == "green"
    assert env.details["welle_states"][1] == "pre-flight-green"
    assert env.details["welle_states"][2] == "pending"
    # tracker invoked with --show-marathon
    assert any("--show-marathon" in part for part in record[0])


def test_cmd_status_returns_precond_when_tracker_missing(tmp_path):
    root = tmp_path / "empty-repo"
    root.mkdir()
    ctx = cli.CLIContext(repo_root=root, runner=_runner())
    env = cli.cmd_status(ctx)
    assert env.exit_code == 3
    assert env.verdict == "precond"


def test_cmd_probe_single_welle_dry_run_dispatches_bash(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    record: List[Sequence[str]] = []
    ctx = cli.CLIContext(
        repo_root=root,
        stub_mode=True,
        runner=_runner(rc=0, record=record),
    )
    env = cli.cmd_probe(ctx, welle=4, all_welles=False)
    assert env.exit_code == 0
    assert env.verdict == "green"
    assert env.welle == 4
    # First argv element should be "bash"; --dry-run must be present.
    assert record[0][0] == "bash"
    assert "--dry-run" in record[0]
    assert "welle-4-pre-cutover-probe.sh" in record[0][1]


def test_cmd_probe_all_aggregates_seven_results(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    # Seven calls; the third one returns rc=1 (caution).
    rcs = iter([0, 0, 1, 0, 0, 0, 0])

    def runner(argv, **kw):
        return _FakeCompleted(returncode=next(rcs))

    ctx = cli.CLIContext(repo_root=root, stub_mode=True, runner=runner)
    env = cli.cmd_probe(ctx, all_welles=True)
    assert env.exit_code == 1  # worst-of yellow
    assert env.verdict == "yellow"
    assert len(env.details["per_welle"]) == 7
    yellow = [x for x in env.details["per_welle"] if x["rc"] == 1]
    assert len(yellow) == 1 and yellow[0]["welle"] == 3


def test_cmd_dryrun_passes_up_to_welle_flag_through(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    record: List[Sequence[str]] = []
    ctx = cli.CLIContext(
        repo_root=root, stub_mode=True, runner=_runner(rc=0, record=record)
    )
    env = cli.cmd_dryrun(ctx, up_to_welle=3)
    assert env.exit_code == 0
    assert "--up-to-welle" in record[0]
    idx = list(record[0]).index("--up-to-welle")
    assert record[0][idx + 1] == "3"


def test_cmd_cutover_dry_run_default_does_not_require_confirm(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    record: List[Sequence[str]] = []
    ctx = cli.CLIContext(
        repo_root=root, stub_mode=True, runner=_runner(rc=0, record=record)
    )
    env = cli.cmd_cutover(ctx, welle=1, live=False)
    assert env.exit_code == 0
    assert env.verdict == "green"
    assert env.welle == 1
    assert "--dry-run" in record[0]
    assert "--live" not in record[0]


def test_cmd_cutover_live_refused_without_confirm_in_stub_mode(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    ctx = cli.CLIContext(
        repo_root=root, stub_mode=True, live=True, confirm=None, runner=_runner()
    )
    with pytest.raises(cli.ConfirmationError):
        cli.cmd_cutover(ctx, welle=2, live=True)


def test_cmd_signoff_writes_marker_and_is_idempotent_on_replay(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    ctx = cli.CLIContext(repo_root=root, stub_mode=True, runner=_runner())

    env1 = cli.cmd_signoff(ctx, welle=3, auditor="Henrik Voss")
    assert env1.exit_code == 0
    assert env1.verdict == "green"

    marker = root / "state" / "welle-3-sign-off.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["welle"] == 3
    assert payload["auditor"] == "Henrik Voss"
    assert payload["domain"] == "bridge_audit_writer"

    # Re-running yields yellow (idempotent; does not overwrite).
    env2 = cli.cmd_signoff(ctx, welle=3, auditor="Mira Kessler")
    assert env2.exit_code == 1
    assert env2.verdict == "yellow"
    # Payload unchanged.
    assert (
        json.loads(marker.read_text(encoding="utf-8"))["auditor"] == "Henrik Voss"
    )


def test_cmd_signoff_rejects_empty_auditor(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    ctx = cli.CLIContext(repo_root=root, runner=_runner())
    with pytest.raises(cli.PrecondError):
        cli.cmd_signoff(ctx, welle=1, auditor="   ")


def test_cmd_complete_check_blocks_when_signoffs_missing_then_ready(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    ctx = cli.CLIContext(repo_root=root, runner=_runner())

    env1 = cli.cmd_complete_check(ctx)
    assert env1.exit_code == 2  # all seven missing
    assert env1.verdict == "red"
    assert env1.details["missing"] == [1, 2, 3, 4, 5, 6, 7]

    # Populate all seven sign-off markers.
    for n in range(1, 8):
        (root / "state" / f"welle-{n}-sign-off.json").write_text(
            json.dumps({"welle": n, "status": "green"}) + "\n",
            encoding="utf-8",
        )

    env2 = cli.cmd_complete_check(ctx)
    assert env2.exit_code == 0
    assert env2.verdict == "ready"
    assert env2.details["signed"] == [1, 2, 3, 4, 5, 6, 7]


def test_cmd_complete_preview_does_not_write_marker(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    # Seed sign-offs so complete-check is ready.
    for n in range(1, 8):
        (root / "state" / f"welle-{n}-sign-off.json").write_text(
            json.dumps({"welle": n, "status": "green"}) + "\n",
            encoding="utf-8",
        )

    ctx = cli.CLIContext(repo_root=root, live=False, runner=_runner())
    env = cli.cmd_complete(ctx)
    assert env.exit_code == 0
    assert env.verdict == "ready"
    assert not (root / "state" / "phase-3-complete-marker.json").exists()
    assert env.details["mode"] == "preview"


def test_cmd_complete_live_refused_in_stub_mode(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    ctx = cli.CLIContext(
        repo_root=root,
        stub_mode=True,
        live=True,
        confirm=cli.CONFIRMATION_PHRASE,
        runner=_runner(),
    )
    with pytest.raises(cli.ConfirmationError):
        cli.cmd_complete(ctx)


def test_render_envelope_json_and_table_paths():
    env = cli.Envelope(
        schema_version=cli.SCHEMA_VERSION,
        command="status",
        timestamp_utc="2026-05-18T12:00:00Z",
        verdict="green",
        stub_mode=True,
        summary="ok",
        details={"k": "v"},
        exit_code=0,
    )
    js = cli.render_envelope(env, "json")
    parsed = json.loads(js)
    assert parsed["command"] == "status"
    assert parsed["verdict"] == "green"

    tbl = cli.render_envelope(env, "table")
    assert "Marathon-Coordination-CLI" in tbl
    assert "verdict       : green" in tbl

    with pytest.raises(cli.PrecondError):
        cli.render_envelope(env, "yaml")


def test_main_smoke_status_table_output_and_exit_zero(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    fake_stdout = "Marathon: 7/7 pending\nWelle 1 | pending | v907_verify\n"
    runner = _runner(rc=0, stdout=fake_stdout)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(
            ["--repo-root", str(root), "--format", "table", "status"],
            runner=runner,
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Marathon-Coordination-CLI :: status" in out
    assert "verdict       : green" in out


def test_main_rejects_unknown_subcommand_with_precond_exit_three(tmp_path):
    buf_err = io.StringIO()
    with redirect_stderr(buf_err):
        rc = cli.main(["--repo-root", str(tmp_path), "frobnicate"], runner=_runner())
    assert rc == 3


def test_main_signoff_writes_json_envelope_on_disk(tmp_path):
    root = _seed_substrate_layout(tmp_path)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(
            [
                "--repo-root",
                str(root),
                "--format",
                "json",
                "signoff",
                "--welle",
                "5",
                "--auditor",
                "Aisha Rahman",
            ],
            runner=_runner(),
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["command"] == "signoff"
    assert payload["welle"] == 5
    assert payload["verdict"] == "green"

    on_disk = json.loads(
        (root / "state" / "welle-5-sign-off.json").read_text(encoding="utf-8")
    )
    assert on_disk["welle"] == 5
    assert on_disk["auditor"] == "Aisha Rahman"


def test_main_cutover_live_without_top_level_live_returns_precond(tmp_path):
    root = _seed_substrate_layout(tmp_path)
    buf_err = io.StringIO()
    with redirect_stderr(buf_err):
        rc = cli.main(
            [
                "--repo-root",
                str(root),
                "cutover",
                "--welle",
                "1",
                "--live",
            ],
            runner=_runner(),
        )
    assert rc == 3
    assert "requires top-level --live" in buf_err.getvalue()
