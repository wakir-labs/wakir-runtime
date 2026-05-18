# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-45 Welle-3 Hot-Spot probe aggregator.

Scope
-----

* Workflow YAML structural shape (triggers, sandbox posture, no
  required-status-check listing).
* Aggregator: verdict-normalisation, indicator evaluators
  (SRT / CWP / IOP / IIA-1130), hot-spot aggregation, envelope
  shape, markdown rendering, notify-feed append.
* End-to-end: write a synthetic input JSON, invoke the aggregator
  script via subprocess, assert envelope + markdown contents.
* ADR-0066 calendar pinning for Welle-3 (KW-25 solo, Mon
  2026-06-15 08:00..10:00 CEST).
* Pre-Mortem anchor block presence + cross-Welle target set.

Sandbox boundary: pure file-system reads + python imports + pyyaml.
The end-to-end test invokes ``python3`` via subprocess against the
aggregator script in-tree, which is hermetic (stdlib only -- no
network, no podman, no SSH, no gh).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3c-welle-3-hot-spot-probe.yml"
)
AGGREGATOR_SCRIPT = (
    REPO_ROOT / "tooling" / "ci" / "welle_3_hot_spot_aggregator.py"
)
FIXTURE_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "fixtures"
    / "welle-3-hot-spot"
    / "sandbox-stub-input.json"
)


# ---------------------------------------------------------------------------
# Module import helper -- we load the aggregator as a module so we can
# exercise its functions directly without going through subprocess.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "welle_3_hot_spot_aggregator", AGGREGATOR_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Workflow YAML structural shape
# ---------------------------------------------------------------------------


def test_workflow_yaml_parses_and_has_required_keys():
    assert WORKFLOW_PATH.is_file(), f"workflow not at {WORKFLOW_PATH}"
    # PyYAML parses GitHub-Actions' `on:` as bool-True under safe_load
    # default, so we just check the top-level shape.
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert doc.get("name") == "phase-3c-welle-3-hot-spot-probe"
    # `on` may be parsed as the python bool True due to YAML 1.1 -- handle both.
    on_key = "on" if "on" in doc else True
    triggers = doc[on_key]
    assert isinstance(triggers, dict)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert "push" in triggers
    assert "pull_request" in triggers
    schedule = triggers["schedule"]
    assert isinstance(schedule, list)
    assert any(item.get("cron") == "30 6 * * *" for item in schedule)
    jobs = doc.get("jobs", {})
    assert "hot-spot-probe" in jobs
    job = jobs["hot-spot-probe"]
    assert job.get("runs-on") == "ubuntu-latest"
    perms = doc.get("permissions", {})
    assert perms == {"contents": "read"}
    concurrency = doc.get("concurrency", {})
    assert concurrency.get("group") == "phase-3c-welle-3-hot-spot-probe"


def test_workflow_yaml_does_not_list_required_status_check_disclaimer():
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The comment header must explicitly disclaim required-status-check
    # listing per feedback_branch_protection_check_names.md.
    assert "Not a required status check" in text


def test_workflow_yaml_hermetic_no_external_commands_in_steps():
    """Hermetic guarantee: the YAML steps must not invoke podman / cosign /
    ssh / gh. Comment lines (starting with #) may discuss them; only step
    bodies are checked."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    suspect = ("podman", "cosign", "gh api", "gh pr ")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Inside a step block: `run:` content is what we care about.
        low = stripped.lower()
        for needle in suspect:
            assert needle not in low, (
                f"hermetic violation: step line invokes {needle!r}: {line!r}"
            )


# ---------------------------------------------------------------------------
# 2. Aggregator -- verdict normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GREEN", "GREEN"),
        ("green", "GREEN"),
        ("ok", "GREEN"),
        ("PASS", "GREEN"),
        ("WARN", "CAUTION"),
        ("warning", "CAUTION"),
        ("yellow", "CAUTION"),
        ("BLOCK", "BLOCK"),
        ("FAIL", "BLOCK"),
        ("red", "BLOCK"),
        ("error", "BLOCK"),
        ("NOT-EXEC", "NOT-EXEC"),
        ("not_exec", "NOT-EXEC"),
        ("skipped", "NOT-EXEC"),
        ("", "NOT-EXEC"),
        (None, "NOT-EXEC"),
        ("garbage", "BLOCK"),
    ],
)
def test_normalise_verdict(aggregator_module, raw, expected):
    assert aggregator_module._normalise_verdict(raw) == expected


# ---------------------------------------------------------------------------
# 3. SRT (Self-Reference-Trap) evaluator
# ---------------------------------------------------------------------------


def test_evaluate_srt_block_at_pre_mortem_threshold(aggregator_module):
    # Pre-Mortem worst-case is +340% spike -- 4.4x baseline.
    block = {
        "event_rate_per_min": 440.0,
        "baseline_event_rate_per_min": 100.0,
    }
    out = aggregator_module.evaluate_srt(block)
    assert out["verdict"] == "BLOCK"
    assert out["multiplier"] == 4.4
    assert "3.4" in out["rationale"] or "BLOCK threshold" in out["rationale"]


def test_evaluate_srt_caution_at_2x(aggregator_module):
    block = {
        "event_rate_per_min": 200.0,
        "baseline_event_rate_per_min": 100.0,
    }
    out = aggregator_module.evaluate_srt(block)
    assert out["verdict"] == "CAUTION"
    assert out["multiplier"] == 2.0


def test_evaluate_srt_green_below_threshold(aggregator_module):
    block = {
        "event_rate_per_min": 110.0,
        "baseline_event_rate_per_min": 100.0,
    }
    out = aggregator_module.evaluate_srt(block)
    assert out["verdict"] == "GREEN"
    assert out["multiplier"] == 1.1


def test_evaluate_srt_not_exec_on_missing_block(aggregator_module):
    out = aggregator_module.evaluate_srt(None)
    assert out["verdict"] == "NOT-EXEC"
    assert "no SRT block" in out["rationale"]


def test_evaluate_srt_not_exec_on_missing_rate(aggregator_module):
    out = aggregator_module.evaluate_srt({"baseline_event_rate_per_min": 100.0})
    assert out["verdict"] == "NOT-EXEC"


def test_evaluate_srt_handles_zero_baseline(aggregator_module):
    # Zero baseline => can't compute multiplier; falls through to NOT-EXEC.
    out = aggregator_module.evaluate_srt(
        {"event_rate_per_min": 50.0, "baseline_event_rate_per_min": 0.0}
    )
    assert out["verdict"] == "NOT-EXEC"


# ---------------------------------------------------------------------------
# 4. CWP (Cross-Welle-Propagation-Risk) evaluator
# ---------------------------------------------------------------------------


def test_evaluate_cwp_block_when_welle_3_block(aggregator_module):
    out = aggregator_module.evaluate_cwp(
        "BLOCK",
        {4: "GREEN", 5: "GREEN", 7: "GREEN"},
    )
    assert out["verdict"] == "BLOCK"
    assert "Welle-3 itself is BLOCK" in out["rationale"]


def test_evaluate_cwp_block_when_downstream_block(aggregator_module):
    out = aggregator_module.evaluate_cwp(
        "GREEN",
        {4: "BLOCK", 5: "GREEN", 7: "GREEN"},
    )
    assert out["verdict"] == "BLOCK"
    assert "Welle-[4]" in out["rationale"]
    assert out["downstream_block_set"] == [4]


def test_evaluate_cwp_caution_when_downstream_caution(aggregator_module):
    out = aggregator_module.evaluate_cwp(
        "GREEN",
        {4: "CAUTION", 5: "GREEN", 7: "CAUTION"},
    )
    assert out["verdict"] == "CAUTION"
    assert sorted(out["downstream_caution_set"]) == [4, 7]


def test_evaluate_cwp_green_all_aligned(aggregator_module):
    out = aggregator_module.evaluate_cwp(
        "GREEN",
        {4: "GREEN", 5: "GREEN", 7: "GREEN"},
    )
    assert out["verdict"] == "GREEN"


def test_evaluate_cwp_not_exec_when_welle_3_not_exec(aggregator_module):
    out = aggregator_module.evaluate_cwp(
        "NOT-EXEC",
        {4: "GREEN", 5: "GREEN", 7: "GREEN"},
    )
    assert out["verdict"] == "NOT-EXEC"


# ---------------------------------------------------------------------------
# 5. IOP (Independent-Oracle-Probe) doppelbetrieb evaluator
# ---------------------------------------------------------------------------


def test_evaluate_iop_agreement_green(aggregator_module):
    out = aggregator_module.evaluate_iop(
        "GREEN", {"verdict": "GREEN", "source": "external"}
    )
    assert out["verdict"] == "GREEN"
    assert out["agreement_score"] == 1.0


def test_evaluate_iop_disagreement_green_block_is_block(aggregator_module):
    out = aggregator_module.evaluate_iop(
        "GREEN", {"verdict": "BLOCK", "source": "external"}
    )
    assert out["verdict"] == "BLOCK"
    assert out["agreement_score"] == 0.0
    assert "GREEN-vs-BLOCK" in out["rationale"]


def test_evaluate_iop_partial_disagreement(aggregator_module):
    out = aggregator_module.evaluate_iop(
        "GREEN", {"verdict": "CAUTION", "source": "external"}
    )
    assert out["verdict"] == "CAUTION"
    assert out["agreement_score"] == 0.5


def test_evaluate_iop_not_exec_when_no_block(aggregator_module):
    out = aggregator_module.evaluate_iop("GREEN", None)
    assert out["verdict"] == "NOT-EXEC"


def test_evaluate_iop_not_exec_when_independent_missing(aggregator_module):
    out = aggregator_module.evaluate_iop(
        "GREEN", {"source": "external-stream"}
    )
    assert out["verdict"] == "NOT-EXEC"


# ---------------------------------------------------------------------------
# 6. IIA-1130 evaluator
# ---------------------------------------------------------------------------


def test_iia_1130_external_pre_auditor_green(aggregator_module):
    out = aggregator_module.evaluate_iia_1130(
        {"ar_decision": "external_pre_auditor_designated"}
    )
    assert out["verdict"] == "GREEN"
    assert "B3 risk mitigated" in out["rationale"]


def test_iia_1130_henrik_default_path_block(aggregator_module):
    out = aggregator_module.evaluate_iia_1130(
        {"ar_decision": "henrik_default_path"}
    )
    assert out["verdict"] == "BLOCK"
    assert "IIA-1130 conflict" in out["rationale"]


def test_iia_1130_pending_caution(aggregator_module):
    out = aggregator_module.evaluate_iia_1130({"ar_decision": "pending"})
    assert out["verdict"] == "CAUTION"


def test_iia_1130_decision_blocked_block(aggregator_module):
    out = aggregator_module.evaluate_iia_1130(
        {"ar_decision": "decision_blocked"}
    )
    assert out["verdict"] == "BLOCK"


def test_iia_1130_absent_not_exec(aggregator_module):
    out = aggregator_module.evaluate_iia_1130(None)
    assert out["verdict"] == "NOT-EXEC"


def test_iia_1130_unknown_decision_treated_as_absent(aggregator_module):
    out = aggregator_module.evaluate_iia_1130(
        {"ar_decision": "some_made_up_state"}
    )
    assert out["ar_decision"] == "absent"
    assert out["verdict"] == "NOT-EXEC"


# ---------------------------------------------------------------------------
# 7. Hot-spot aggregation rule
# ---------------------------------------------------------------------------


def test_aggregate_hot_spot_all_green(aggregator_module):
    assert (
        aggregator_module.aggregate_hot_spot(["GREEN", "GREEN", "GREEN", "GREEN"])
        == "GREEN"
    )


def test_aggregate_hot_spot_any_block_dominates(aggregator_module):
    assert (
        aggregator_module.aggregate_hot_spot(["GREEN", "GREEN", "BLOCK", "GREEN"])
        == "BLOCK"
    )


def test_aggregate_hot_spot_caution_over_green(aggregator_module):
    assert (
        aggregator_module.aggregate_hot_spot(["GREEN", "CAUTION", "GREEN", "GREEN"])
        == "CAUTION"
    )


def test_aggregate_hot_spot_all_not_exec(aggregator_module):
    assert (
        aggregator_module.aggregate_hot_spot(
            ["NOT-EXEC", "NOT-EXEC", "NOT-EXEC", "NOT-EXEC"]
        )
        == "NOT-EXEC"
    )


def test_aggregate_hot_spot_mixed_green_not_exec_is_caution(aggregator_module):
    # Incomplete observation -> caution.
    assert (
        aggregator_module.aggregate_hot_spot(
            ["GREEN", "GREEN", "NOT-EXEC", "GREEN"]
        )
        == "CAUTION"
    )


# ---------------------------------------------------------------------------
# 8. Envelope build + ADR-0066 pinning
# ---------------------------------------------------------------------------


def test_build_envelope_shape_and_calendar_pinning(aggregator_module):
    inputs = {
        "welle_3_probe": {"verdict": "GREEN"},
        "downstream_probes": {
            "4": {"verdict": "GREEN"},
            "5": {"verdict": "GREEN"},
            "7": {"verdict": "GREEN"},
        },
        "self_reference_trap": {
            "event_rate_per_min": 100.0,
            "baseline_event_rate_per_min": 100.0,
        },
        "independent_oracle": {"verdict": "GREEN", "source": "ext"},
        "iia_1130": {"ar_decision": "external_pre_auditor_designated"},
    }
    env = aggregator_module.build_envelope(inputs, today_iso="2026-05-18")
    assert env["welle"] == 3
    assert env["component"] == "bridge_audit_writer"
    assert env["cutover_kw"] == 25
    # Welle-3 cutover-window must be Mon 2026-06-15 08:00..10:00 CEST.
    assert env["cutover_day_window"] == (
        "2026-06-15T08:00:00+02:00/2026-06-15T10:00:00+02:00"
    )
    assert env["snapshot_date"] == "2026-05-18"
    assert env["hot_spot_verdict"] == "GREEN"
    assert env["workflow"] == "phase-3c-welle-3-hot-spot-probe"
    assert env["tag"] == "Tag-45"
    # Pre-Mortem anchor must reference the right file + failure modes.
    anchor = env["pre_mortem_anchor"]
    assert anchor["report"].endswith(
        "phase-3-marathon-pre-mortem-2026-05-18.md"
    )
    assert "A5" in anchor["failure_modes"]
    assert "B3" in anchor["failure_modes"]
    assert anchor["cross_welle_targets"] == [4, 5, 7]


def test_build_envelope_worst_case_scenario(aggregator_module):
    # The Pre-Mortem worst-case: SRT firing + downstream BLOCK +
    # IOP disagreement + IIA-1130 pending.  Expect BLOCK.
    inputs = {
        "welle_3_probe": {"verdict": "GREEN"},
        "downstream_probes": {
            "4": {"verdict": "BLOCK"},
            "5": {"verdict": "CAUTION"},
            "7": {"verdict": "NOT-EXEC"},
        },
        "self_reference_trap": {
            "event_rate_per_min": 440.0,
            "baseline_event_rate_per_min": 100.0,
        },
        "independent_oracle": {"verdict": "BLOCK", "source": "ext"},
        "iia_1130": {"ar_decision": "pending"},
    }
    env = aggregator_module.build_envelope(inputs)
    assert env["hot_spot_verdict"] == "BLOCK"
    indicators = env["indicators"]
    assert indicators["self_reference_trap"]["verdict"] == "BLOCK"
    assert indicators["cross_welle_propagation_risk"]["verdict"] == "BLOCK"
    assert indicators["independent_oracle_probe"]["verdict"] == "BLOCK"
    assert indicators["iia_1130_pre_auditor_decision"]["verdict"] == "CAUTION"


def test_build_envelope_sandbox_stub_input_is_not_exec(aggregator_module):
    # The shipped fixture is all-NOT-EXEC; verdict must be NOT-EXEC
    # (not CAUTION) when *every* indicator is NOT-EXEC.
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    env = aggregator_module.build_envelope(data)
    assert env["hot_spot_verdict"] == "NOT-EXEC"


# ---------------------------------------------------------------------------
# 9. Markdown rendering
# ---------------------------------------------------------------------------


def test_render_markdown_contains_all_indicators(aggregator_module):
    inputs = {
        "welle_3_probe": {"verdict": "GREEN"},
        "downstream_probes": {
            "4": {"verdict": "GREEN"},
            "5": {"verdict": "GREEN"},
            "7": {"verdict": "GREEN"},
        },
        "self_reference_trap": {
            "event_rate_per_min": 100.0,
            "baseline_event_rate_per_min": 100.0,
        },
        "independent_oracle": {"verdict": "GREEN", "source": "ext"},
        "iia_1130": {"ar_decision": "external_pre_auditor_designated"},
    }
    env = aggregator_module.build_envelope(inputs, today_iso="2026-05-18")
    md = aggregator_module.render_markdown(env)
    assert "Welle-3 Hot-Spot Probe" in md
    assert "2026-05-18" in md
    assert "Self-Reference-Trap" in md
    assert "Cross-Welle-Propagation-Risk" in md
    assert "Independent-Oracle-Probe" in md
    assert "IIA-1130 Pre-Auditor-Decision" in md
    assert "Welle-4" in md
    assert "Welle-5" in md
    assert "Welle-7" in md
    assert "bridge_audit_writer" in md
    assert "KW-25" in md
    assert "GREEN" in md


# ---------------------------------------------------------------------------
# 10. Notify-feed append
# ---------------------------------------------------------------------------


def test_append_notify_skips_green(aggregator_module, tmp_path):
    env = {
        "hot_spot_verdict": "GREEN",
        "emitted_at_utc": "2026-05-18T06:30:00+00:00",
        "snapshot_date": "2026-05-18",
        "workflow": "phase-3c-welle-3-hot-spot-probe",
        "welle_3_verdict": "GREEN",
        "indicators": {
            "self_reference_trap": {"verdict": "GREEN"},
            "cross_welle_propagation_risk": {"verdict": "GREEN"},
            "independent_oracle_probe": {"verdict": "GREEN"},
            "iia_1130_pre_auditor_decision": {"verdict": "GREEN"},
        },
        "github_run_id": "42",
    }
    notify_path = tmp_path / "notify.jsonl"
    appended = aggregator_module.append_notify(notify_path, env)
    assert appended is False
    assert not notify_path.exists()


def test_append_notify_writes_on_caution_and_block(aggregator_module, tmp_path):
    env_caution = {
        "hot_spot_verdict": "CAUTION",
        "emitted_at_utc": "2026-05-18T06:30:00+00:00",
        "snapshot_date": "2026-05-18",
        "workflow": "phase-3c-welle-3-hot-spot-probe",
        "welle_3_verdict": "GREEN",
        "indicators": {
            "self_reference_trap": {"verdict": "GREEN"},
            "cross_welle_propagation_risk": {"verdict": "CAUTION"},
            "independent_oracle_probe": {"verdict": "GREEN"},
            "iia_1130_pre_auditor_decision": {"verdict": "GREEN"},
        },
        "github_run_id": "42",
    }
    notify_path = tmp_path / "notify.jsonl"
    assert aggregator_module.append_notify(notify_path, env_caution) is True

    env_block = dict(env_caution)
    env_block["hot_spot_verdict"] = "BLOCK"
    env_block["emitted_at_utc"] = "2026-05-19T06:30:00+00:00"
    env_block["snapshot_date"] = "2026-05-19"
    assert aggregator_module.append_notify(notify_path, env_block) is True

    lines = notify_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    events = [json.loads(line) for line in lines]
    assert events[0]["hot_spot_verdict"] == "CAUTION"
    assert events[1]["hot_spot_verdict"] == "BLOCK"
    assert events[1]["snapshot_date"] == "2026-05-19"
    # Every notify-event must carry the four indicator verdicts.
    for ev in events:
        assert set(ev["indicator_verdicts"].keys()) == {
            "self_reference_trap",
            "cross_welle_propagation_risk",
            "independent_oracle_probe",
            "iia_1130_pre_auditor_decision",
        }


# ---------------------------------------------------------------------------
# 11. End-to-end subprocess invocation
# ---------------------------------------------------------------------------


def test_aggregator_subprocess_end_to_end_sandbox_stub(tmp_path):
    output_json = tmp_path / "out" / "envelope.json"
    output_md = tmp_path / "out" / "summary.md"
    notify_path = tmp_path / "state" / "notify.jsonl"
    rc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_SCRIPT),
            "--input-json",
            str(FIXTURE_PATH),
            "--today",
            "2026-05-18",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--notify-path",
            str(notify_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert output_json.is_file()
    assert output_md.is_file()
    env = json.loads(output_json.read_text(encoding="utf-8"))
    assert env["welle"] == 3
    assert env["hot_spot_verdict"] == "NOT-EXEC"
    # NOT-EXEC verdict triggers a notify-event (only GREEN skips).
    assert notify_path.is_file()
    line = notify_path.read_text(encoding="utf-8").strip()
    assert json.loads(line)["hot_spot_verdict"] == "NOT-EXEC"


def test_aggregator_subprocess_exit_on_block_returns_nonzero(tmp_path):
    # Build a BLOCK input on disk and assert --exit-on-block returns 2.
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "welle_3_probe": {"verdict": "BLOCK"},
                "downstream_probes": {
                    "4": {"verdict": "GREEN"},
                    "5": {"verdict": "GREEN"},
                    "7": {"verdict": "GREEN"},
                },
                "self_reference_trap": {
                    "event_rate_per_min": 100.0,
                    "baseline_event_rate_per_min": 100.0,
                },
                "independent_oracle": {
                    "verdict": "BLOCK",
                    "source": "ext",
                },
                "iia_1130": {
                    "ar_decision": "external_pre_auditor_designated"
                },
            }
        ),
        encoding="utf-8",
    )
    output_json = tmp_path / "out.json"
    output_md = tmp_path / "out.md"
    rc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_SCRIPT),
            "--input-json",
            str(input_path),
            "--today",
            "2026-05-18",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
            "--exit-on-block",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 2, (rc.returncode, rc.stderr)
    env = json.loads(output_json.read_text(encoding="utf-8"))
    assert env["hot_spot_verdict"] == "BLOCK"


# ---------------------------------------------------------------------------
# 12. Fixture sanity
# ---------------------------------------------------------------------------


def test_fixture_present_and_parseable():
    assert FIXTURE_PATH.is_file(), f"fixture missing at {FIXTURE_PATH}"
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # All four indicator-input keys must be present even in stub-mode.
    for key in (
        "welle_3_probe",
        "downstream_probes",
        "self_reference_trap",
        "independent_oracle",
        "iia_1130",
    ):
        assert key in data, f"fixture missing key: {key}"
    # Downstream must enumerate 4, 5, 7.
    assert set(data["downstream_probes"].keys()) == {"4", "5", "7"}
