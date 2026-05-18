# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the AR-Hand-Stop-Cascade Live-Test workflow.

Tag-52 Tomás Substanz-Counterpart zum Tag-46 PR #299 (B1-Schema /
State-Machine) und Tag-47 PR #304 (Listener-Workflow + Helper).

Tag-46 hat das Marker-File-Schema und Cascade-Coupling als
Property-Tests gegen synthetische Snapshots gepinnt. Tag-47 hat den
Listener-Workflow + die vier Helper-Scripts (detect / cascade /
cancel / verdict) + die Marker-Set-CLI geliefert und schon eine
Hermetic-Suite (43 Tests) drangehaengt. Was bisher fehlte: ein
End-to-End-Gate, das die GANZE Cascade in einem realen
GitHub-Actions-Runner ablaufen laesst — vom Marker-CLI-Aufruf ueber
einen synthetisierten Push-Event zum Detect-Step, ueber die
Cascade-Compute-Logik zum Cancel-Step (mit Stub-gh-Binary, damit
kein echter Live-Cancel passiert) zum Verdict-Artifact.

Diese Suite pruft:

  * **Workflow-YAML-Struktur** (Trigger-Surface, paths-Filter,
    concurrency, permissions, schedule, hermetic-Posture).
  * **Stub-gh-Binary-Contract** (gleiche Endpoint-Schemata wie der
    echte Cancel-Helper sie ruft).
  * **In-Process-End-to-End-Driver** der die drei Live-Scenarios A
    (Welle-3 ohne Sign-Off), B (Welle-3 MIT Sign-Off) und C
    (Welle-7 ohne Downstream) nachstellt — gegen die echten
    Helper-Module, ohne Subprozess. Das pinnt den Stub-Vertrag
    UND die Cascade-Tabelle gegen Drift.
  * **Rejection-Probes** (oob welle, unknown trigger).

Sandbox-Boundary: stdlib + pytest + PyYAML. Kein Subprozess. Der
Live-Test-Workflow im YAML laeuft natuerlich subprozess-basiert
auf einem ubuntu-24.04 Runner; diese Tests pinnen die *Substanz*
hinter dem Wire-Protokoll.

Anchors
-------

  * ``.github/workflows/ar-hand-stop-cascade-live-test.yml`` (this file under test).
  * ``.github/workflows/ar-hand-stop-marker-listener.yml`` (Tag-47).
  * ``scripts/ci/ar-hand-stop-marker-set.py`` (Tag-47).
  * ``scripts/ci/ar-hand-stop-marker-listener-detect.py`` (Tag-47).
  * ``scripts/ci/ar-hand-stop-marker-listener-cascade.py`` (Tag-47).
  * ``scripts/ci/ar-hand-stop-marker-listener-cancel.py`` (Tag-47).
  * ``scripts/ci/ar-hand-stop-marker-listener-verdict.py`` (Tag-47).
  * Tag-46 ``tests/ci/test_ar_hand_stop_marker_trigger_b1.py``.
  * Tag-47 ``tests/ci/test_ar_hand_stop_marker_workflow.py``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Repo anchors + module loader.
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKFLOW_PATH = (
    _REPO_ROOT
    / ".github"
    / "workflows"
    / "ar-hand-stop-cascade-live-test.yml"
)
_LISTENER_PATH = (
    _REPO_ROOT
    / ".github"
    / "workflows"
    / "ar-hand-stop-marker-listener.yml"
)
_SCRIPTS_DIR = _REPO_ROOT / "scripts" / "ci"
_CLI_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-set.py"
_DETECT_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-detect.py"
_CASCADE_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-cascade.py"
_CANCEL_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-cancel.py"
_VERDICT_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-verdict.py"


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def marker_set_mod() -> Any:
    return _load("marker_set_t52", _CLI_SCRIPT)


@pytest.fixture(scope="module")
def detect_mod() -> Any:
    return _load("listener_detect_t52", _DETECT_SCRIPT)


@pytest.fixture(scope="module")
def cascade_mod() -> Any:
    return _load("listener_cascade_t52", _CASCADE_SCRIPT)


@pytest.fixture(scope="module")
def cancel_mod() -> Any:
    return _load("listener_cancel_t52", _CANCEL_SCRIPT)


@pytest.fixture(scope="module")
def verdict_mod() -> Any:
    return _load("listener_verdict_t52", _VERDICT_SCRIPT)


@pytest.fixture(scope="module")
def workflow_yaml() -> dict[str, Any]:
    import yaml  # PyYAML is in the runner default + dev-extras

    raw = _WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


# ---------------------------------------------------------------------------
# Test-class 1: Workflow-File-Exists + YAML-Structure (3 tests).
# ---------------------------------------------------------------------------


class TestWorkflowArtefactPresence:
    def test_workflow_file_exists(self) -> None:
        assert _WORKFLOW_PATH.exists(), (
            f"missing cascade-live-test workflow: {_WORKFLOW_PATH}"
        )

    def test_workflow_has_spdx_header(self) -> None:
        head = _WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()[:3]
        # REUSE-IgnoreStart
        spdx_marker = "SPDX-License-Identifier: Apache-2.0"
        # REUSE-IgnoreEnd
        assert any(spdx_marker in line for line in head), (
            f"workflow head missing SPDX: {head!r}"
        )

    def test_workflow_yaml_parses(self, workflow_yaml: dict[str, Any]) -> None:
        assert isinstance(workflow_yaml, dict)
        assert workflow_yaml.get("name") == "ar-hand-stop-cascade-live-test"


# ---------------------------------------------------------------------------
# Test-class 2: Trigger-Surface (5 tests).
# ---------------------------------------------------------------------------


class TestWorkflowTriggerSurface:
    def test_push_trigger_paths_cover_listener_and_helpers(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        # YAML's `on:` becomes True when parsed as a bare keyword in some
        # versions of PyYAML; allow both forms.
        on = workflow_yaml.get("on") or workflow_yaml.get(True)
        push = on["push"]
        paths = push["paths"]
        for required in (
            ".github/workflows/ar-hand-stop-cascade-live-test.yml",
            ".github/workflows/ar-hand-stop-marker-listener.yml",
            "scripts/ci/ar-hand-stop-marker-set.py",
            "scripts/ci/ar-hand-stop-marker-listener-detect.py",
            "scripts/ci/ar-hand-stop-marker-listener-cascade.py",
            "scripts/ci/ar-hand-stop-marker-listener-cancel.py",
            "scripts/ci/ar-hand-stop-marker-listener-verdict.py",
            "tests/ci/test_ar_hand_stop_marker_trigger_b1.py",
            "tests/ci/test_ar_hand_stop_marker_workflow.py",
            "tests/ci/test_ar_hand_stop_cascade_live_test.py",
        ):
            assert required in paths, (
                f"push.paths missing required path: {required}"
            )

    def test_pull_request_trigger_present(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        on = workflow_yaml.get("on") or workflow_yaml.get(True)
        assert "pull_request" in on
        pr = on["pull_request"]
        assert pr.get("branches") == ["main"]
        # Same paths-filter as push (drift would be a smell).
        assert pr.get("paths") == on["push"]["paths"]

    def test_workflow_dispatch_scenario_input(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        on = workflow_yaml.get("on") or workflow_yaml.get(True)
        wd = on["workflow_dispatch"]
        inputs = wd["inputs"]
        assert "scenario" in inputs
        scen = inputs["scenario"]
        assert scen["type"] == "string"
        assert scen["default"] == "all"

    def test_schedule_trigger_present(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        on = workflow_yaml.get("on") or workflow_yaml.get(True)
        sched = on["schedule"]
        assert isinstance(sched, list) and len(sched) == 1
        cron = sched[0]["cron"]
        # Sanity-check the cron is a five-field expression.
        parts = cron.split()
        assert len(parts) == 5, f"schedule cron malformed: {cron!r}"

    def test_permissions_minimal_read(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        perms = workflow_yaml.get("permissions") or {}
        assert perms.get("contents") == "read"
        # Cascade-live-test MUST NOT request `actions: write` — it never
        # cancels real runs. That privilege belongs to the listener-
        # workflow exclusively.
        assert "actions" not in perms, (
            "cascade-live-test must not escalate to actions:write"
        )


# ---------------------------------------------------------------------------
# Test-class 3: Job + Step Composition (4 tests).
# ---------------------------------------------------------------------------


class TestWorkflowJobComposition:
    def test_job_exists_and_runs_on_ubuntu(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        jobs = workflow_yaml["jobs"]
        assert "cascade-live-test" in jobs
        job = jobs["cascade-live-test"]
        assert job["runs-on"].startswith("ubuntu-")
        assert isinstance(job.get("timeout-minutes"), int)
        assert job["timeout-minutes"] <= 30

    def test_required_steps_present_and_ordered(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        job = workflow_yaml["jobs"]["cascade-live-test"]
        step_names = [step.get("name", "") for step in job["steps"]]
        expected_substrings = (
            "Checkout",
            "Set up Python",
            "Install pytest",
            "Prepare live-test scratch dir",
            "Scenario A",
            "Scenario B",
            "Scenario C",
            "Rejection probes",
            "Hermetic regression-suite",
            "Upload cascade live-test artifacts",
        )
        positions: list[int] = []
        for sub in expected_substrings:
            matches = [i for i, n in enumerate(step_names) if sub in n]
            assert matches, f"missing step matching {sub!r} in {step_names!r}"
            positions.append(matches[0])
        assert positions == sorted(positions), (
            f"steps out of order: {list(zip(expected_substrings, positions))}"
        )

    def test_each_scenario_step_gated_by_scenario_env(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        job = workflow_yaml["jobs"]["cascade-live-test"]
        gated = 0
        for step in job["steps"]:
            name = step.get("name") or ""
            if name.startswith("Scenario "):
                cond = step.get("if") or ""
                assert (
                    "env.SCENARIO" in cond
                    or "github.event.inputs.scenario" in cond
                ), f"scenario step missing scenario-env gate: {name!r} -> {cond!r}"
                gated += 1
        assert gated == 3, f"expected 3 scenario steps, found {gated}"

    def test_upload_artifact_always_runs(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        job = workflow_yaml["jobs"]["cascade-live-test"]
        last = job["steps"][-1]
        # YAML `if: always()` parses as a bare string.
        assert last.get("if") == "always()"
        assert "actions/upload-artifact" in last.get("uses", "")


# ---------------------------------------------------------------------------
# Test-class 4: gh-Stub Contract Compatibility (4 tests).
# ---------------------------------------------------------------------------
#
# The cascade-live-test embeds a Python gh-stub in a heredoc. We
# extract it, write it to a tmp_path, and pin its behaviour against
# the *real* call patterns the cancel-helper emits. If the helper's
# wire-protocol drifts, this test fails loudly.


def _extract_gh_stub_source() -> str:
    raw = _WORKFLOW_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"cat > \"\$\{LIVE_DIR\}/stub-bin/gh\" <<'STUB_EOF'\n(.*?)\n          STUB_EOF",
        raw,
        re.DOTALL,
    )
    assert m, "could not locate gh-stub heredoc in workflow"
    # Strip the leading 10-space indent from the heredoc body (matches
    # the workflow's run-block indent).
    body = textwrap.dedent(m.group(1))
    return body


@pytest.fixture(scope="module")
def gh_stub_path(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    stub_src = _extract_gh_stub_source()
    base = tmp_path_factory.mktemp("gh-stub")
    stub = base / "gh"
    stub.write_text(stub_src, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return stub


class TestGhStubContract:
    def test_stub_lists_in_flight_for_arbitrary_workflow(
        self, gh_stub_path: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        env = os.environ.copy()
        env["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        result = subprocess.run(
            [
                sys.executable,
                str(gh_stub_path),
                "api",
                "/repos/wakir-labs/wakir-runtime/actions/workflows/"
                "phase-3c-welle-3-validation.yml/runs?status=in_progress&per_page=100",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        payload = json.loads(result.stdout)
        assert payload["total_count"] == 1
        runs = payload["workflow_runs"]
        assert len(runs) == 1
        assert runs[0]["status"] == "in_progress"
        assert runs[0]["name"] == "phase-3c-welle-3-validation.yml"
        assert isinstance(runs[0]["id"], int) and runs[0]["id"] > 0

    def test_stub_returns_empty_for_queued_and_waiting(
        self, gh_stub_path: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        env = os.environ.copy()
        env["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        for status in ("queued", "waiting"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(gh_stub_path),
                    "api",
                    f"/repos/wakir-labs/wakir-runtime/actions/workflows/"
                    f"phase-3c-welle-3-validation.yml/runs?status={status}",
                ],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            payload = json.loads(result.stdout)
            assert payload == {"total_count": 0, "workflow_runs": []}

    def test_stub_accepts_cancel_post(
        self, gh_stub_path: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        env = os.environ.copy()
        env["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        result = subprocess.run(
            [
                sys.executable,
                str(gh_stub_path),
                "api",
                "-X",
                "POST",
                "/repos/wakir-labs/wakir-runtime/actions/runs/12345/cancel",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        # Empty stdout, exit-0.
        assert result.returncode == 0
        assert result.stdout == ""
        # The invocation MUST be logged.
        log = (tmp_path / "stub.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(log) == 1
        entry = json.loads(log[0])
        assert entry["argv"][:3] == ["api", "-X", "POST"]
        assert entry["argv"][3].endswith("/actions/runs/12345/cancel")

    def test_stub_rejects_unknown_subcommand(
        self, gh_stub_path: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        env = os.environ.copy()
        env["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        result = subprocess.run(
            [sys.executable, str(gh_stub_path), "auth", "status"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 2
        assert "unsupported subcommand" in result.stderr


# ---------------------------------------------------------------------------
# Test-class 5: In-Process E2E Driver for the three scenarios (5 tests).
# ---------------------------------------------------------------------------


def _set_marker(
    *,
    marker_set_mod: Any,
    state_dir: pathlib.Path,
    welle: int,
    trigger: str,
    ts: str,
    operator: str = "mira",
) -> tuple[str, dict[str, Any]]:
    when = marker_set_mod._parse_ts(ts)
    filename = marker_set_mod.build_marker_filename(welle, when)
    payload = marker_set_mod.build_marker_payload(
        welle=welle, trigger=trigger, operator=operator, when=when
    )
    marker_set_mod.write_marker(
        state_dir=state_dir,
        filename=filename,
        payload=payload,
        force=False,
    )
    return filename, payload


def _make_push_event(state_dir_rel: str, marker_filename: str) -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "commits": [
            {
                "id": "deadbeef",
                "added": [f"{state_dir_rel}/{marker_filename}"],
                "modified": [],
            }
        ],
    }


class TestE2EScenarioDriver:
    def test_scenario_a_full_cascade_welle_3_no_signoff(
        self,
        marker_set_mod: Any,
        detect_mod: Any,
        cascade_mod: Any,
        verdict_mod: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        repo_root = tmp_path
        state_dir_rel = "state-a"
        state_dir = repo_root / state_dir_rel
        filename, _ = _set_marker(
            marker_set_mod=marker_set_mod,
            state_dir=state_dir,
            welle=3,
            trigger="Cross-Modul-Drift",
            ts="2026-05-19T12:00:00Z",
        )
        event_payload = _make_push_event(state_dir_rel, filename)
        # Detect step (in-process)
        detected = detect_mod.detect_from_push_event(
            event_payload, repo_root=repo_root
        )
        assert detected["welle"] == "3"
        assert detected["trigger"] == "Cross-Modul-Drift"
        assert detected["filename"] == f"{state_dir_rel}/{filename}"
        # Cascade compute
        cascade = cascade_mod.compute_cascade(
            welle=3, state_dir=state_dir
        )
        assert cascade["sign_off_present"] is False
        assert "phase-3c-welle-3-validation.yml" in cascade["welle_targets"]
        assert (
            "phase-3c-welle-3-hot-spot-probe.yml" in cascade["welle_targets"]
        )
        assert cascade["cascade_blocked_welle"] == [4, 5, 6, 7]
        # cascade_targets has 4 downstream wellen, each one workflow:
        assert len(cascade["cascade_targets"]) == 4
        assert len(cascade["marathon_targets"]) == 6
        # Verdict
        verdict = verdict_mod.build_verdict(
            welle=3,
            trigger="Cross-Modul-Drift",
            marker_ts="2026-05-19T12:00:00Z",
            operator="mira",
            marker_filename=f"{state_dir_rel}/{filename}",
            welle_targets=cascade["welle_targets"],
            cascade_targets=cascade["cascade_targets"],
            marathon_targets=cascade["marathon_targets"],
            cascade_blocked_welle=cascade["cascade_blocked_welle"],
            dry_run=False,
            listener_run_ts=datetime(2026, 5, 19, 12, 5, 0, tzinfo=timezone.utc),
        )
        assert verdict["schema_version"] == "1"
        assert verdict["listener_run_ts"] == "2026-05-19T12:05:00Z"
        assert verdict["marker"]["welle"] == 3
        assert verdict["cancel_plan"]["cascade_blocked_welle"] == [4, 5, 6, 7]

    def test_scenario_b_signoff_short_circuits_cascade(
        self,
        marker_set_mod: Any,
        cascade_mod: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        repo_root = tmp_path
        state_dir_rel = "state-b"
        state_dir = repo_root / state_dir_rel
        state_dir.mkdir(parents=True)
        # Sign-off file present.
        sign_off = state_dir / "ar-hand-stop-sign-off-welle-3.json"
        sign_off.write_text(
            json.dumps(
                {
                    "welle": 3,
                    "sign_off_ts": "2026-05-19T14:00:00Z",
                    "operator": "mira",
                    "lifted_trigger": "Cross-Modul-Drift",
                }
            ),
            encoding="utf-8",
        )
        # Re-emit marker
        _set_marker(
            marker_set_mod=marker_set_mod,
            state_dir=state_dir,
            welle=3,
            trigger="Self-Reference-Trap-Fire",
            ts="2026-05-19T13:00:00Z",
        )
        cascade = cascade_mod.compute_cascade(welle=3, state_dir=state_dir)
        assert cascade["sign_off_present"] is True
        assert cascade["cascade_targets"] == []
        assert cascade["cascade_blocked_welle"] == []
        # welle_targets and marathon_targets are unchanged by sign-off.
        assert len(cascade["welle_targets"]) == 2
        assert len(cascade["marathon_targets"]) == 6

    def test_scenario_c_welle_7_no_downstream(
        self,
        marker_set_mod: Any,
        detect_mod: Any,
        cascade_mod: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        repo_root = tmp_path
        state_dir_rel = "state-c"
        state_dir = repo_root / state_dir_rel
        filename, _ = _set_marker(
            marker_set_mod=marker_set_mod,
            state_dir=state_dir,
            welle=7,
            trigger="POST_HASH != PRE_HASH",
            ts="2026-05-19T15:00:00Z",
        )
        event_payload = _make_push_event(state_dir_rel, filename)
        detected = detect_mod.detect_from_push_event(
            event_payload, repo_root=repo_root
        )
        assert detected["welle"] == "7"
        cascade = cascade_mod.compute_cascade(welle=7, state_dir=state_dir)
        assert cascade["cascade_targets"] == []
        assert cascade["cascade_blocked_welle"] == []
        assert len(cascade["welle_targets"]) == 1
        assert cascade["welle_targets"][0] == "phase-3c-welle-7-validation.yml"

    def test_scenario_a_cancel_total_seen_matches_target_count(
        self,
        marker_set_mod: Any,
        cascade_mod: Any,
        cancel_mod: Any,
        gh_stub_path: pathlib.Path,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo_root = tmp_path
        state_dir_rel = "state-cancel"
        state_dir = repo_root / state_dir_rel
        _set_marker(
            marker_set_mod=marker_set_mod,
            state_dir=state_dir,
            welle=3,
            trigger="Cross-Modul-Drift",
            ts="2026-05-19T12:00:00Z",
        )
        cascade = cascade_mod.compute_cascade(welle=3, state_dir=state_dir)
        # Drive cancel-step via its public driver function.
        env = os.environ.copy()
        env["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        # Use the gh-stub as a Python interpreter — we need to invoke
        # python <stub> so the cancel-helper's subprocess call works.
        # Easier: write a wrapper that python invokes.
        wrapper = tmp_path / "gh-wrap"
        wrapper.write_text(
            f"#!/usr/bin/env bash\nexec {sys.executable} {gh_stub_path} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(
            wrapper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
        )
        # Inject env into subprocess via os.environ
        prev_log = os.environ.get("GH_STUB_LOG")
        os.environ["GH_STUB_LOG"] = str(tmp_path / "stub.jsonl")
        try:
            argv = [
                "--welle-targets",
                json.dumps(cascade["welle_targets"]),
                "--cascade-targets",
                json.dumps(cascade["cascade_targets"]),
                "--marathon-targets",
                json.dumps(cascade["marathon_targets"]),
                "--gh-repo",
                "wakir-labs/wakir-runtime",
                "--gh-binary",
                str(wrapper),
            ]
            rc = cancel_mod.main(argv)
        finally:
            if prev_log is None:
                os.environ.pop("GH_STUB_LOG", None)
            else:
                os.environ["GH_STUB_LOG"] = prev_log
        assert rc == 0
        captured = capsys.readouterr().out
        # 2 welle + 4 cascade + 6 marathon = 12.
        assert "TOTAL runs-seen=12 cancelled=12" in captured

    def test_dispatch_event_input_path(
        self,
        marker_set_mod: Any,
        detect_mod: Any,
        tmp_path: pathlib.Path,
    ) -> None:
        # workflow_dispatch path should also resolve the marker even
        # without a push-event payload.
        repo_root = tmp_path
        state_dir = repo_root / "state"
        filename, _ = _set_marker(
            marker_set_mod=marker_set_mod,
            state_dir=state_dir,
            welle=5,
            trigger="NATS-Consumer-Lag",
            ts="2026-05-19T10:00:00Z",
        )
        detected = detect_mod.detect_from_dispatch(
            dispatch_welle="5",
            dispatch_filename="",
            repo_root=repo_root,
        )
        assert detected["welle"] == "5"
        assert detected["filename"] == f"state/{filename}"


# ---------------------------------------------------------------------------
# Test-class 6: Rejection-Probes (3 tests).
# ---------------------------------------------------------------------------


class TestRejectionProbes:
    def test_marker_set_rejects_unknown_trigger(
        self, marker_set_mod: Any, tmp_path: pathlib.Path
    ) -> None:
        rc = marker_set_mod.main(
            [
                "--welle",
                "3",
                "--trigger",
                "this-is-not-a-real-trigger",
                "--operator",
                "mira",
                "--ts",
                "2026-05-19T12:00:00Z",
                "--repo",
                str(tmp_path),
                "--state-dir",
                "state",
                "--dry-run",
            ]
        )
        assert rc == 2

    def test_marker_set_rejects_oob_welle(
        self, marker_set_mod: Any, tmp_path: pathlib.Path
    ) -> None:
        rc = marker_set_mod.main(
            [
                "--welle",
                "8",
                "--trigger",
                "Cross-Modul-Drift",
                "--operator",
                "mira",
                "--ts",
                "2026-05-19T12:00:00Z",
                "--repo",
                str(tmp_path),
                "--state-dir",
                "state",
                "--dry-run",
            ]
        )
        assert rc == 2

    def test_cascade_rejects_oob_welle(
        self, cascade_mod: Any, tmp_path: pathlib.Path
    ) -> None:
        out_path = tmp_path / "out"
        out_path.write_text("", encoding="utf-8")
        rc = cascade_mod.main(
            [
                "--welle",
                "0",
                "--state-dir",
                "state",
                "--out",
                str(out_path),
                "--repo-root",
                str(tmp_path),
            ]
        )
        assert rc == 2


# ---------------------------------------------------------------------------
# Test-class 7: Cross-Test Consistency (2 tests).
# ---------------------------------------------------------------------------


class TestCrossTestConsistency:
    def test_workflow_lists_all_helper_scripts_in_paths_filter(
        self, workflow_yaml: dict[str, Any]
    ) -> None:
        """The cascade-live-test workflow's path-filter MUST include
        every helper script + the listener workflow itself. If a new
        helper is added without updating the live-test, the live-test
        would silently miss the regression surface.
        """
        on = workflow_yaml.get("on") or workflow_yaml.get(True)
        push_paths = set(on["push"]["paths"])
        for helper in (
            _CLI_SCRIPT.relative_to(_REPO_ROOT).as_posix(),
            _DETECT_SCRIPT.relative_to(_REPO_ROOT).as_posix(),
            _CASCADE_SCRIPT.relative_to(_REPO_ROOT).as_posix(),
            _CANCEL_SCRIPT.relative_to(_REPO_ROOT).as_posix(),
            _VERDICT_SCRIPT.relative_to(_REPO_ROOT).as_posix(),
            _LISTENER_PATH.relative_to(_REPO_ROOT).as_posix(),
        ):
            assert helper in push_paths, (
                f"cascade-live-test paths-filter missing {helper}"
            )

    def test_workflow_runs_hermetic_suites_back_to_back(self) -> None:
        """The hermetic regression-suite step must invoke all three
        suites (B1 / Tag-47 / Tag-52) so a single failure stops the
        gate.
        """
        raw = _WORKFLOW_PATH.read_text(encoding="utf-8")
        for sibling in (
            "tests/ci/test_ar_hand_stop_marker_trigger_b1.py",
            "tests/ci/test_ar_hand_stop_marker_workflow.py",
            "tests/ci/test_ar_hand_stop_cascade_live_test.py",
        ):
            assert sibling in raw, (
                f"hermetic regression-suite step missing reference to {sibling}"
            )
