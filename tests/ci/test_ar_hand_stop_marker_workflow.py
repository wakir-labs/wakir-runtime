# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the AR-Hand-Stop-Marker Listener-Workflow.

Tag-47 Tomás Substanz-Counterpart zum Tag-46 PR #299
``test_ar_hand_stop_marker_trigger_b1.py`` (Schema + State-Machine).
Diese Suite pruft die *operative* Realisierung:

  * Marker-Set CLI (``scripts/ci/ar-hand-stop-marker-set.py``)
    schreibt das Marker-File schema-konform und gibt einen
    Audit-Trail-Append aus.
  * Listener-Workflow YAML-Datei ist schema-konform (paths-trigger,
    permissions, concurrency).
  * Detect-Step extrahiert aus dem push-event und dispatch-input.
  * Cascade-Step rechnet B2-Cascade-Coupling korrekt aus, beachtet
    Sign-Off-Files.
  * Cancel-Step ist stub-fähig (gh-Binary-Override) und ruft die
    richtigen Endpoints.
  * Verdict-Step emittiert ein schema-konformes JSON-Artifact.

Sandbox-Boundary: pure stdlib + ``pytest`` + ``yaml`` (PyYAML, in
runner-default). Keine Live-GitHub-Calls, keine podman, keine
NATS. Subprozess-Aufrufe gehen ueber eine Stub-Binary.

Anchors:
  - Tag-47 Tomás Auftrag (Continuous-Mode, 2026-05-18).
  - Tag-46 B1 Coverage-Test (PR #299).
  - Operator-Cheat-Sheet §I.
  - Welle-3 Runbook §6 (exit-3 protocol).
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

import pytest


# ---------------------------------------------------------------------------
# Repository anchors + module loader.
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts" / "ci"
_WORKFLOW_FILE = (
    _REPO_ROOT / ".github" / "workflows" / "ar-hand-stop-marker-listener.yml"
)
_CLI_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-set.py"
_DETECT_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-detect.py"
_CASCADE_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-cascade.py"
_CANCEL_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-cancel.py"
_VERDICT_SCRIPT = _SCRIPTS_DIR / "ar-hand-stop-marker-listener-verdict.py"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def marker_set_mod():
    return _load("marker_set", _CLI_SCRIPT)


@pytest.fixture(scope="module")
def detect_mod():
    return _load("listener_detect", _DETECT_SCRIPT)


@pytest.fixture(scope="module")
def cascade_mod():
    return _load("listener_cascade", _CASCADE_SCRIPT)


@pytest.fixture(scope="module")
def cancel_mod():
    return _load("listener_cancel", _CANCEL_SCRIPT)


@pytest.fixture(scope="module")
def verdict_mod():
    return _load("listener_verdict", _VERDICT_SCRIPT)


# ---------------------------------------------------------------------------
# 1. Repo-Layout: artefacts exist where the workflow expects them.
# ---------------------------------------------------------------------------


class TestArtefactLayout:
    """All five artefacts MUST live at the path the workflow uses."""

    def test_listener_workflow_file_present(self):
        assert _WORKFLOW_FILE.is_file(), (
            f"listener workflow missing at {_WORKFLOW_FILE}"
        )

    def test_marker_set_cli_present_and_executable(self):
        assert _CLI_SCRIPT.is_file()
        # CLI shebang allows ``python3 path`` invocation either way; we
        # do not require the +x bit to be set in the repo (CI invokes
        # via ``python <path>``), but the shebang MUST be present.
        head = _CLI_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert head.startswith("#!/usr/bin/env python3"), head

    def test_listener_helper_scripts_present(self):
        for script in (
            _DETECT_SCRIPT,
            _CASCADE_SCRIPT,
            _CANCEL_SCRIPT,
            _VERDICT_SCRIPT,
        ):
            assert script.is_file(), f"missing helper: {script}"


# ---------------------------------------------------------------------------
# 2. Listener-Workflow YAML shape.
# ---------------------------------------------------------------------------


class TestWorkflowSchema:
    """The YAML file pins paths, permissions, and the cancel-step."""

    @pytest.fixture(scope="class")
    def workflow(self):
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load(_WORKFLOW_FILE.read_text(encoding="utf-8"))

    def test_workflow_has_push_trigger_with_marker_path(self, workflow):
        # PyYAML parses the bare key ``on`` as a Python bool ``True``;
        # accept both spellings to stay robust.
        on_block = workflow.get("on") or workflow.get(True)
        assert on_block is not None, "workflow must define an 'on' trigger"
        push = on_block.get("push")
        assert push is not None, "workflow must trigger on push"
        assert "main" in push.get("branches", []), (
            "listener must only react to pushes on main"
        )
        paths = push.get("paths") or []
        assert any(
            "ar-hand-stop-welle" in p and p.startswith("state/")
            for p in paths
        ), f"paths filter must include state/ar-hand-stop-welle-*: {paths}"

    def test_workflow_has_workflow_dispatch_inputs(self, workflow):
        on_block = workflow.get("on") or workflow.get(True)
        dispatch = on_block.get("workflow_dispatch")
        assert dispatch is not None, "must allow operator-hand replay"
        inputs = dispatch.get("inputs") or {}
        assert "welle" in inputs
        assert "marker_filename" in inputs
        assert "dry_run" in inputs

    def test_workflow_has_actions_write_permission(self, workflow):
        perms = workflow.get("permissions") or {}
        assert perms.get("actions") == "write", (
            "must grant actions:write to cancel runs"
        )
        # Defence-in-depth: contents stays read-only.
        assert perms.get("contents", "read") == "read"

    def test_workflow_concurrency_is_not_cancel_in_progress(self, workflow):
        conc = workflow.get("concurrency")
        assert conc is not None
        # The listener MUST NEVER cancel itself mid-run, else a fast
        # second marker would race-cancel the first reaction.
        assert conc.get("cancel-in-progress") is False, conc

    def test_workflow_invokes_all_four_helper_scripts(self):
        # We re-read the raw YAML text; structural assertions above
        # validate semantics, this one validates the wiring is in place.
        raw = _WORKFLOW_FILE.read_text(encoding="utf-8")
        for helper in (
            "ar-hand-stop-marker-listener-detect.py",
            "ar-hand-stop-marker-listener-cascade.py",
            "ar-hand-stop-marker-listener-cancel.py",
            "ar-hand-stop-marker-listener-verdict.py",
        ):
            assert helper in raw, (
                f"workflow does not invoke helper script {helper}"
            )

    def test_workflow_uploads_verdict_artifact(self, workflow):
        jobs = workflow["jobs"]
        step_names: list[str] = []
        for job in jobs.values():
            for step in job.get("steps", []) or []:
                step_names.append(step.get("uses") or step.get("name") or "")
        assert any(
            "upload-artifact" in s for s in step_names
        ), step_names


# ---------------------------------------------------------------------------
# 3. Marker-Set CLI: filename + payload + audit-line.
# ---------------------------------------------------------------------------


class TestMarkerSetCLI:
    """The operator-CLI MUST be schema-faithful to Cheat-Sheet §I."""

    def test_filename_pattern(self, marker_set_mod):
        when = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        name = marker_set_mod.build_marker_filename(3, when)
        assert name == "ar-hand-stop-welle-3-20260519.json"
        assert marker_set_mod.MARKER_FILENAME_RE.match(name)

    def test_payload_schema(self, marker_set_mod):
        when = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        payload = marker_set_mod.build_marker_payload(
            welle=4,
            trigger="POST_HASH != PRE_HASH detected in welle-4 soak",
            operator="mira",
            when=when,
        )
        assert payload == {
            "welle": 4,
            "trigger": "POST_HASH != PRE_HASH detected in welle-4 soak",
            "ts": "2026-05-19T12:00:00Z",
            "operator": "mira",
        }

    def test_payload_rejects_unknown_trigger(self, marker_set_mod):
        when = datetime(2026, 5, 19, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="trigger token not recognised"):
            marker_set_mod.build_marker_payload(
                welle=1,
                trigger="random-string-that-is-not-a-cheat-sheet-token",
                operator="mira",
                when=when,
            )

    def test_payload_rejects_welle_oob(self, marker_set_mod):
        when = datetime(2026, 5, 19, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="welle out of range"):
            marker_set_mod.build_marker_payload(
                welle=8,
                trigger="Cross-Modul-Drift",
                operator="mira",
                when=when,
            )

    def test_audit_log_line_includes_marker_and_trigger(self, marker_set_mod):
        when = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        filename = marker_set_mod.build_marker_filename(3, when)
        line = marker_set_mod.build_activity_log_line(
            welle=3,
            trigger="OTS-Anchor-Emission-Stop im Welle-3-Soak",
            operator="mira",
            marker_filename=filename,
            when=when,
        )
        assert "OTS-Anchor-Emission-Stop" in line
        assert filename in line
        assert "ar-hand-stop-sign-off-welle-3.json" in line
        assert "2026-05-19T12:00:00Z" in line

    def test_write_marker_creates_state_dir_and_file(
        self, marker_set_mod, tmp_path
    ):
        when = datetime(2026, 5, 19, tzinfo=timezone.utc)
        filename = marker_set_mod.build_marker_filename(2, when)
        payload = marker_set_mod.build_marker_payload(
            welle=2,
            trigger="Self-Reference-Trap-Fire in welle-2",
            operator="mira",
            when=when,
        )
        target = marker_set_mod.write_marker(
            state_dir=tmp_path / "state",
            filename=filename,
            payload=payload,
            force=False,
        )
        assert target.exists()
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        assert on_disk == payload

    def test_write_marker_refuses_overwrite_without_force(
        self, marker_set_mod, tmp_path
    ):
        when = datetime(2026, 5, 19, tzinfo=timezone.utc)
        filename = marker_set_mod.build_marker_filename(5, when)
        payload = marker_set_mod.build_marker_payload(
            welle=5,
            trigger="FSM-Phantom-Transition welle-5",
            operator="mira",
            when=when,
        )
        marker_set_mod.write_marker(
            state_dir=tmp_path / "state",
            filename=filename,
            payload=payload,
            force=False,
        )
        with pytest.raises(FileExistsError):
            marker_set_mod.write_marker(
                state_dir=tmp_path / "state",
                filename=filename,
                payload=payload,
                force=False,
            )
        # Force overwrites without raising.
        marker_set_mod.write_marker(
            state_dir=tmp_path / "state",
            filename=filename,
            payload=payload,
            force=True,
        )

    def test_cli_dry_run_prints_payload_and_writes_nothing(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        cmd = [
            sys.executable,
            str(_CLI_SCRIPT),
            "--welle",
            "3",
            "--trigger",
            "Cross-Modul-Drift > 0 baseline",
            "--operator",
            "mira",
            "--repo",
            str(repo),
            "--ts",
            "2026-05-19T08:00:00Z",
            "--dry-run",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "DRY-RUN" in result.stdout
        assert "ar-hand-stop-welle-3-20260519.json" in result.stdout
        assert "Cross-Modul-Drift" in result.stdout
        # Nothing should be on disk.
        assert not (repo / "state").exists()

    def test_cli_writes_marker_and_prints_push_sequence(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        cmd = [
            sys.executable,
            str(_CLI_SCRIPT),
            "--welle",
            "6",
            "--trigger",
            "NATS-Consumer-Lag P95 > 500ms welle-6",
            "--operator",
            "mira",
            "--repo",
            str(repo),
            "--ts",
            "2026-05-19T09:30:00Z",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        target = repo / "state" / "ar-hand-stop-welle-6-20260519.json"
        assert target.exists()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["welle"] == 6
        assert payload["operator"] == "mira"
        assert "NATS-Consumer-Lag" in payload["trigger"]
        # Push-sequence hint MUST be printed.
        for hint in (
            "git add",
            "git commit",
            "git push origin main",
            "ar-hand-stop-marker-listener.yml",
        ):
            assert hint in result.stdout, hint

    def test_cli_list_triggers_lists_ten_tokens(self):
        cmd = [sys.executable, str(_CLI_SCRIPT), "--list-triggers",
               "--welle", "1", "--trigger", "Cross-Modul-Drift"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        tokens = [
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        assert len(tokens) == 10, tokens
        # Spot-check vocabulary against cheat-sheet §I.
        assert "Cross-Modul-Drift" in tokens
        assert "OTS-Anchor-Emission-Stop" in tokens
        assert "Cosign-Verify-Fail" in tokens

    def test_parse_marker_filename_round_trip(self, marker_set_mod):
        when = datetime(2026, 5, 19, tzinfo=timezone.utc)
        name = marker_set_mod.build_marker_filename(7, when)
        welle, yyyymmdd = marker_set_mod.parse_marker_filename(name)
        assert welle == 7
        assert yyyymmdd == "20260519"
        with pytest.raises(ValueError):
            marker_set_mod.parse_marker_filename("not-a-marker.json")


# ---------------------------------------------------------------------------
# 4. Detect-step: from push payload and from workflow_dispatch.
# ---------------------------------------------------------------------------


class TestDetectStep:
    def _setup_repo(
        self, root: pathlib.Path, welle: int, yyyymmdd: str, trigger: str
    ) -> pathlib.Path:
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        marker = state / f"ar-hand-stop-welle-{welle}-{yyyymmdd}.json"
        marker.write_text(
            json.dumps(
                {
                    "welle": welle,
                    "trigger": trigger,
                    "ts": "2026-05-19T08:00:00Z",
                    "operator": "mira",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return marker

    def test_detect_from_push_event_picks_marker(
        self, detect_mod, tmp_path
    ):
        repo = tmp_path
        self._setup_repo(repo, 3, "20260519", "OTS-Anchor-Emission-Stop")
        payload = {
            "commits": [
                {
                    "added": ["state/ar-hand-stop-welle-3-20260519.json"],
                    "modified": [],
                }
            ]
        }
        mapping = detect_mod.detect_from_push_event(payload, repo_root=repo)
        assert mapping["welle"] == "3"
        assert mapping["trigger"] == "OTS-Anchor-Emission-Stop"
        assert mapping["filename"].endswith(
            "ar-hand-stop-welle-3-20260519.json"
        )

    def test_detect_from_push_event_no_marker_raises(
        self, detect_mod, tmp_path
    ):
        payload = {"commits": [{"added": ["docs/random.md"], "modified": []}]}
        with pytest.raises(LookupError, match="no AR-Hand-Stop-Marker"):
            detect_mod.detect_from_push_event(payload, repo_root=tmp_path)

    def test_detect_from_dispatch_finds_newest_for_welle(
        self, detect_mod, tmp_path
    ):
        # Two markers, same welle, different dates: newest wins.
        self._setup_repo(tmp_path, 4, "20260510", "POST_HASH != PRE_HASH old")
        self._setup_repo(tmp_path, 4, "20260519", "POST_HASH != PRE_HASH new")
        mapping = detect_mod.detect_from_dispatch(
            dispatch_welle="4",
            dispatch_filename="",
            repo_root=tmp_path,
        )
        assert mapping["welle"] == "4"
        assert "new" in mapping["trigger"]
        assert mapping["filename"].endswith(
            "ar-hand-stop-welle-4-20260519.json"
        )

    def test_detect_from_dispatch_rejects_oob_welle(
        self, detect_mod, tmp_path
    ):
        with pytest.raises(ValueError, match="dispatch welle out of range"):
            detect_mod.detect_from_dispatch(
                dispatch_welle="9",
                dispatch_filename="",
                repo_root=tmp_path,
            )

    def test_detect_from_dispatch_with_explicit_filename(
        self, detect_mod, tmp_path
    ):
        self._setup_repo(tmp_path, 5, "20260519", "FSM-Phantom-Transition")
        mapping = detect_mod.detect_from_dispatch(
            dispatch_welle="5",
            dispatch_filename="ar-hand-stop-welle-5-20260519.json",
            repo_root=tmp_path,
        )
        assert mapping["welle"] == "5"

    def test_write_outputs_handles_kv_pairs(
        self, detect_mod, tmp_path
    ):
        out = tmp_path / "outputs"
        detect_mod.write_outputs(
            out,
            {
                "welle": "3",
                "trigger": "OTS-Anchor-Emission-Stop",
                "ts": "2026-05-19T08:00:00Z",
                "operator": "mira",
                "filename": "state/ar-hand-stop-welle-3-20260519.json",
            },
        )
        body = out.read_text(encoding="utf-8")
        # Each kv on its own line, parse-back round-trip.
        lines = [l for l in body.strip().splitlines() if l]
        assert len(lines) == 5
        as_dict = dict(line.split("=", 1) for line in lines)
        assert as_dict["welle"] == "3"
        assert as_dict["trigger"] == "OTS-Anchor-Emission-Stop"

    def test_write_outputs_rejects_newline_in_value(
        self, detect_mod, tmp_path
    ):
        out = tmp_path / "outputs"
        with pytest.raises(ValueError, match="contains newline"):
            detect_mod.write_outputs(
                out, {"trigger": "line1\nline2"}
            )


# ---------------------------------------------------------------------------
# 5. Cascade-step: B2-coupling + sign-off short-circuit.
# ---------------------------------------------------------------------------


class TestCascadeStep:
    def test_cascade_for_welle_3_blocks_welle_4_through_7(
        self, cascade_mod, tmp_path
    ):
        state = tmp_path / "state"
        state.mkdir()
        result = cascade_mod.compute_cascade(welle=3, state_dir=state)
        assert "phase-3c-welle-3-validation.yml" in result["welle_targets"]
        # Welle-3 has a second workflow (hot-spot probe).
        assert (
            "phase-3c-welle-3-hot-spot-probe.yml" in result["welle_targets"]
        )
        # Cascade: welle-4..7 ALL appear.
        for downstream in (4, 5, 6, 7):
            wf = f"phase-3c-welle-{downstream}-validation.yml"
            assert wf in result["cascade_targets"], wf
        assert result["cascade_blocked_welle"] == [4, 5, 6, 7]
        # Marathon workflows are always blocked while a stop is open.
        assert (
            "phase-3c-pre-cutover-daily-probe.yml"
            in result["marathon_targets"]
        )
        assert result["sign_off_present"] is False

    def test_cascade_signed_off_short_circuits_downstream(
        self, cascade_mod, tmp_path
    ):
        state = tmp_path / "state"
        state.mkdir()
        # Place sign-off for welle-3; cascade for welle-3 then must
        # NOT include downstream Wellen.
        (state / "ar-hand-stop-sign-off-welle-3.json").write_text(
            '{"status":"signed-off"}'
        )
        result = cascade_mod.compute_cascade(welle=3, state_dir=state)
        assert result["welle_targets"]  # welle itself still listed
        assert result["cascade_targets"] == []
        assert result["cascade_blocked_welle"] == []
        assert result["sign_off_present"] is True
        # Marathon still paused because marker WAS set (audit-trail).
        assert result["marathon_targets"], (
            "marathon must still be paused even after sign-off; "
            "operator-hand re-enables explicitly"
        )

    def test_cascade_for_welle_7_has_no_downstream(
        self, cascade_mod, tmp_path
    ):
        state = tmp_path / "state"
        state.mkdir()
        result = cascade_mod.compute_cascade(welle=7, state_dir=state)
        assert result["welle_targets"] == [
            "phase-3c-welle-7-validation.yml"
        ]
        assert result["cascade_targets"] == []
        assert result["cascade_blocked_welle"] == []

    def test_cascade_rejects_oob_welle(self, cascade_mod, tmp_path):
        state = tmp_path / "state"
        state.mkdir()
        with pytest.raises(ValueError, match="welle out of range"):
            cascade_mod.compute_cascade(welle=8, state_dir=state)
        with pytest.raises(ValueError, match="welle out of range"):
            cascade_mod.compute_cascade(welle=0, state_dir=state)

    def test_cascade_workflow_inventory_covers_all_seven_wellen(
        self, cascade_mod
    ):
        # Lock the workflow-inventory shape so adding a Welle-N
        # without updating the inventory fails the test-suite, not
        # the production cancel-step.
        keys = sorted(cascade_mod.WELLE_VALIDATION_WORKFLOWS.keys())
        assert keys == [1, 2, 3, 4, 5, 6, 7]
        for k, files in cascade_mod.WELLE_VALIDATION_WORKFLOWS.items():
            assert files, f"welle {k} has no workflow files pinned"
            for fn in files:
                assert fn.endswith(".yml"), fn

    def test_cascade_outputs_are_json_decodable_strings(
        self, cascade_mod, tmp_path
    ):
        state = tmp_path / "state"
        state.mkdir()
        out = tmp_path / "outputs"
        out.touch()
        result = cascade_mod.compute_cascade(welle=2, state_dir=state)
        cascade_mod._emit_outputs(out, result)
        body = out.read_text(encoding="utf-8")
        lines = dict(
            l.split("=", 1) for l in body.strip().splitlines() if l
        )
        # All four list-valued outputs round-trip through json.loads.
        for key in (
            "welle_targets",
            "cascade_targets",
            "marathon_targets",
            "cascade_blocked_welle",
        ):
            decoded = json.loads(lines[key])
            assert isinstance(decoded, list)


# ---------------------------------------------------------------------------
# 6. Cancel-step: gh-binary stub captures the expected invocations.
# ---------------------------------------------------------------------------


class TestCancelStep:
    @pytest.fixture
    def gh_stub(self, tmp_path):
        """A stub ``gh`` binary that records argv and replies with JSON.

        The stub's reply schema mimics
        ``gh api /repos/.../workflows/<name>/runs?status=in_progress``
        for the welle-3-validation workflow, and otherwise echos an
        empty ``workflow_runs`` list. Cancel calls always succeed.
        """

        log_path = tmp_path / "gh-stub.log"
        stub = tmp_path / "gh"
        stub.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json, sys, pathlib
                log = pathlib.Path({str(log_path)!r})
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(" ".join(sys.argv[1:]) + "\\n")
                argv = sys.argv[1:]
                # gh api ... /actions/runs/<id>/cancel  -> empty success
                if any("/cancel" in a for a in argv):
                    print("{{}}")
                    sys.exit(0)
                # gh api ... /workflows/<name>/runs?status=<s>
                target = next(
                    (a for a in argv if "/workflows/" in a and "/runs" in a),
                    "",
                )
                if "welle-3-validation.yml" in target and "in_progress" in target:
                    print(json.dumps({{
                        "workflow_runs": [
                            {{"id": 1001, "status": "in_progress",
                              "name": "Phase-3c Welle-3 Validation"}}
                        ]
                    }}))
                    sys.exit(0)
                print(json.dumps({{"workflow_runs": []}}))
                """
            ),
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
        return stub, log_path

    def test_cancel_target_list_invokes_gh_and_returns_counts(
        self, cancel_mod, gh_stub
    ):
        stub, log = gh_stub
        seen, cancelled = cancel_mod.cancel_target_list(
            targets=["phase-3c-welle-3-validation.yml"],
            gh_repo="wakir-labs/wakir-runtime",
            gh_binary=str(stub),
            label="welle",
        )
        assert seen == 1
        assert cancelled == 1
        log_body = log.read_text(encoding="utf-8")
        # Both list-runs and cancel-runs invocations must appear.
        assert "/workflows/phase-3c-welle-3-validation.yml/runs" in log_body
        assert "/actions/runs/1001/cancel" in log_body

    def test_cancel_target_list_empty_for_no_in_flight_runs(
        self, cancel_mod, gh_stub
    ):
        stub, _ = gh_stub
        seen, cancelled = cancel_mod.cancel_target_list(
            targets=["phase-3c-welle-1-validation.yml"],
            gh_repo="wakir-labs/wakir-runtime",
            gh_binary=str(stub),
            label="welle",
        )
        assert seen == 0
        assert cancelled == 0

    def test_decode_targets_rejects_bad_json(self, cancel_mod):
        with pytest.raises(ValueError, match="target list must be JSON"):
            cancel_mod._decode_targets("not-json")

    def test_cancel_main_drives_all_three_target_groups(
        self, cancel_mod, gh_stub
    ):
        stub, log = gh_stub
        rc = cancel_mod.main(
            [
                "--welle-targets",
                json.dumps(["phase-3c-welle-3-validation.yml"]),
                "--cascade-targets",
                json.dumps(["phase-3c-welle-4-validation.yml"]),
                "--marathon-targets",
                json.dumps(["phase-3c-pre-cutover-daily-probe.yml"]),
                "--gh-repo",
                "wakir-labs/wakir-runtime",
                "--gh-binary",
                str(stub),
            ]
        )
        assert rc == 0
        body = log.read_text(encoding="utf-8")
        for wf in (
            "phase-3c-welle-3-validation.yml",
            "phase-3c-welle-4-validation.yml",
            "phase-3c-pre-cutover-daily-probe.yml",
        ):
            assert wf in body, wf


# ---------------------------------------------------------------------------
# 7. Verdict-step: schema + idempotency.
# ---------------------------------------------------------------------------


class TestVerdictStep:
    def test_build_verdict_pins_schema(self, verdict_mod):
        listener_ts = datetime(2026, 5, 19, 9, 0, 0, tzinfo=timezone.utc)
        verdict = verdict_mod.build_verdict(
            welle=3,
            trigger="OTS-Anchor-Emission-Stop",
            marker_ts="2026-05-19T08:00:00Z",
            operator="mira",
            marker_filename="state/ar-hand-stop-welle-3-20260519.json",
            welle_targets=["phase-3c-welle-3-validation.yml"],
            cascade_targets=["phase-3c-welle-4-validation.yml"],
            marathon_targets=["phase-3c-pre-cutover-daily-probe.yml"],
            cascade_blocked_welle=[4, 5, 6, 7],
            dry_run=False,
            listener_run_ts=listener_ts,
        )
        # Top-level keys are stable.
        assert set(verdict.keys()) == {
            "schema_version",
            "listener_run_ts",
            "marker",
            "cancel_plan",
            "dry_run",
        }
        assert verdict["schema_version"] == "1"
        assert verdict["listener_run_ts"] == "2026-05-19T09:00:00Z"
        assert verdict["marker"]["trigger"] == "OTS-Anchor-Emission-Stop"
        assert verdict["cancel_plan"]["cascade_blocked_welle"] == [
            4, 5, 6, 7
        ]
        assert verdict["dry_run"] is False

    def test_verdict_cli_writes_file_and_is_json_loadable(
        self, verdict_mod, tmp_path
    ):
        out = tmp_path / "verdict.json"
        rc = verdict_mod.main(
            [
                "--welle",
                "3",
                "--trigger",
                "OTS-Anchor-Emission-Stop",
                "--marker-ts",
                "2026-05-19T08:00:00Z",
                "--operator",
                "mira",
                "--marker-filename",
                "state/ar-hand-stop-welle-3-20260519.json",
                "--welle-targets",
                json.dumps(["phase-3c-welle-3-validation.yml"]),
                "--cascade-targets",
                json.dumps([]),
                "--marathon-targets",
                json.dumps(["phase-3c-pre-cutover-daily-probe.yml"]),
                "--cascade-blocked-welle",
                json.dumps([]),
                "--dry-run",
                "true",
                "--out",
                str(out),
            ]
        )
        assert rc == 0
        body = json.loads(out.read_text(encoding="utf-8"))
        assert body["dry_run"] is True
        assert body["marker"]["welle"] == 3
        # cascade_blocked_welle empty -> sign-off already present
        # OR cascade not reached. Either way: schema is intact.
        assert body["cancel_plan"]["cascade_blocked_welle"] == []

    def test_verdict_rejects_non_json_list_input(self, verdict_mod):
        with pytest.raises(ValueError, match="JSON-encoded list"):
            verdict_mod._decode_string_list("not-json")
        with pytest.raises(ValueError, match="JSON-encoded list"):
            verdict_mod._decode_int_list("not-json")


# ---------------------------------------------------------------------------
# 8. Sandbox-Boundary: scripts MUST run without any network or gh-binary.
# ---------------------------------------------------------------------------


class TestSandboxBoundary:
    def test_marker_set_stdlib_only(self):
        """The marker-set CLI must not import 3rd-party packages."""

        body = _CLI_SCRIPT.read_text(encoding="utf-8")
        # No requests, no gh, no PyYAML in the marker-set CLI.
        assert "import requests" not in body
        assert "import yaml" not in body
        assert "from yaml " not in body

    def test_helper_scripts_stdlib_only(self):
        for script in (
            _DETECT_SCRIPT,
            _CASCADE_SCRIPT,
            _VERDICT_SCRIPT,
        ):
            body = script.read_text(encoding="utf-8")
            assert "import requests" not in body, script
            assert "import yaml" not in body, script

    def test_cancel_script_only_external_surface_is_subprocess(self):
        # The cancel-script intentionally calls gh via subprocess. The
        # test ensures no direct HTTP client is wired in alongside —
        # subprocess is the only external surface (and the test-suite
        # stubs it).
        body = _CANCEL_SCRIPT.read_text(encoding="utf-8")
        assert "import requests" not in body
        assert "urllib.request" not in body
        assert "import subprocess" in body
