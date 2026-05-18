# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-42 Pre-Cutover Marathon
Dashboard workflow + aggregator + per-Welle envelope emitter.

Scope
-----

* Workflow YAML structural shape (triggers, matrix of 7 Welles,
  needs/aggregate, push path-filter).
* Per-Welle envelope-emitter contract (welle bounds, verdict
  enum, output schema).
* Marathon-aggregator decision rule walked across a representative
  truth-table.
* ADR-0066 calendar-plan pinning (KW-windows, pair-partners).
* Cross-coupling drift detection.
* Markdown step-summary renders the seven Welles + counts.
* End-to-end: write seven synthetic envelopes, call the aggregator
  binary on disk, assert verdict + step-summary contain expected
  rows.

Sandbox boundary: pure file-system reads + python imports + pyyaml.
No subprocess to gh, podman, or live-VM. The end-to-end test
does invoke ``python3`` via ``subprocess`` against the aggregator
script in-tree, which is hermetic (stdlib only).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3c-pre-cutover-marathon-dashboard.yml"
)
AGGREGATOR_SCRIPT = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_pre_cutover_marathon_dashboard.py"
)
EMITTER_SCRIPT = (
    REPO_ROOT / "tooling" / "ci" / "emit_marathon_probe_envelope.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_yaml() -> dict:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def aggregator():
    return _load_module(
        "_aggregate_pre_cutover_marathon_dashboard", AGGREGATOR_SCRIPT
    )


@pytest.fixture(scope="module")
def emitter():
    return _load_module(
        "_emit_marathon_probe_envelope", EMITTER_SCRIPT
    )


def _write_envelope(
    probe_dir: Path, welle: int, verdict: str, **overrides
) -> Path:
    """Helper: write a minimal valid per-Welle envelope."""
    body = {
        "schema_version": 1,
        "welle": welle,
        "component": f"comp-{welle}",
        "probe_script": f"scripts/phase-3c/welle-{welle}-pre-cutover-probe.sh",
        "probe_present": True,
        "exit_code": 0 if verdict == "GREEN" else 2,
        "verdict": verdict,
        "verdict_source": "test-synthetic",
        "details": "test envelope",
        "emitted_at_utc": "2026-05-18T00:00:00+00:00",
    }
    body.update(overrides)
    p = probe_dir / f"welle-{welle}.json"
    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Workflow YAML structure
# ---------------------------------------------------------------------------


def test_workflow_has_three_trigger_sources(workflow_yaml: dict) -> None:
    # PyYAML parses bare-key `on:` as Python bool True; the GitHub
    # workflow truly has the trigger key. Accept either.
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert isinstance(triggers, dict), f"no trigger map: {triggers!r}"
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "push" in triggers


def test_workflow_schedule_is_monday_06_utc(workflow_yaml: dict) -> None:
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    schedule = triggers["schedule"]
    crons = [entry["cron"] for entry in schedule]
    assert "0 6 * * 1" in crons, f"Mon 06:00 UTC cron missing: {crons}"


def test_workflow_push_paths_include_marathon_substrates(
    workflow_yaml: dict,
) -> None:
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    push = triggers["push"]
    paths = push["paths"]
    assert any("welle-*-pre-cutover-probe.sh" in p for p in paths)
    assert any("aggregate_pre_cutover_marathon_dashboard.py" in p for p in paths)
    assert any(
        "phase-3c-pre-cutover-marathon-dashboard.yml" in p for p in paths
    )


def test_workflow_has_welle_probe_matrix_of_seven(
    workflow_yaml: dict,
) -> None:
    job = workflow_yaml["jobs"]["welle-probe"]
    matrix = job["strategy"]["matrix"]
    include = matrix["include"]
    welle_indices = sorted(row["welle"] for row in include)
    assert welle_indices == [1, 2, 3, 4, 5, 6, 7]
    components = {row["welle"]: row["component"] for row in include}
    assert components[1] == "v907_verify"
    assert components[2] == "svid_workload_identity"
    assert components[3] == "bridge_audit_writer"
    assert components[4] == "state_backing"
    assert components[5] == "lifecycle_state_machine"
    assert components[6] == "subscribe_loop"
    assert components[7] == "recovery_workflow"


def test_workflow_aggregator_needs_probe_and_runs_always(
    workflow_yaml: dict,
) -> None:
    job = workflow_yaml["jobs"]["marathon-aggregate"]
    assert job["needs"] == "welle-probe"
    assert job["if"] == "always()"


def test_workflow_matrix_does_not_fail_fast(workflow_yaml: dict) -> None:
    # Critical: one Welle BLOCK must not cancel the other six legs.
    job = workflow_yaml["jobs"]["welle-probe"]
    assert job["strategy"]["fail-fast"] is False


# ---------------------------------------------------------------------------
# 2. ADR-0066 calendar plan pinning
# ---------------------------------------------------------------------------


def test_adr_0066_plan_pins_all_seven_welles(aggregator) -> None:
    plan = aggregator.ADR_0066_PLAN
    assert sorted(plan.keys()) == [1, 2, 3, 4, 5, 6, 7]
    # KW pinning per ADR-0066.
    assert plan[1]["cutover_kw"] == 24
    assert plan[2]["cutover_kw"] == 24
    assert plan[3]["cutover_kw"] == 25
    assert plan[4]["cutover_kw"] == 26
    assert plan[5]["cutover_kw"] == 26
    assert plan[6]["cutover_kw"] == 27
    assert plan[7]["cutover_kw"] == 27
    # KW-25 is the solo wave.
    assert plan[3]["cutover_mode"] == "solo"
    assert plan[3]["cutover_pair_partner"] is None
    # Doppel-welle pair partners.
    assert plan[1]["cutover_pair_partner"] == 2
    assert plan[2]["cutover_pair_partner"] == 1
    assert plan[4]["cutover_pair_partner"] == 5
    assert plan[5]["cutover_pair_partner"] == 4
    assert plan[6]["cutover_pair_partner"] == 7
    assert plan[7]["cutover_pair_partner"] == 6


def test_cross_coupling_pairs_match_adr_0066(aggregator) -> None:
    pairs = aggregator.CROSS_COUPLING_PAIRS
    welles = sorted([(a, b) for a, b, _ in pairs])
    assert welles == [(1, 2), (4, 5), (6, 7)]


# ---------------------------------------------------------------------------
# 3. Verdict normalisation + per-Welle envelope coercion
# ---------------------------------------------------------------------------


def test_normalise_verdict_handles_synonyms(aggregator) -> None:
    n = aggregator._normalise_verdict
    assert n("GREEN") == "GREEN"
    assert n("green") == "GREEN"
    assert n("READY") == "GREEN"
    assert n("ok") == "GREEN"
    assert n("CAUTION") == "CAUTION"
    assert n("warning") == "CAUTION"
    assert n("yellow") == "CAUTION"
    assert n("BLOCK") == "BLOCK"
    assert n("RED") == "BLOCK"
    assert n("fail") == "BLOCK"
    assert n("NOT-EXEC") == "NOT-EXEC"
    assert n("not_exec") == "NOT-EXEC"
    assert n("SKIP") == "NOT-EXEC"
    assert n("") == "BLOCK"          # unknown -> loud-fail
    assert n(None) == "NOT-EXEC"     # absent -> NOT-EXEC


def test_normalise_envelope_applies_pinned_plan(aggregator) -> None:
    out = aggregator._normalise_envelope(
        4,
        {"verdict": "green", "probe_present": "true", "exit_code": "0"},
    )
    assert out["welle"] == 4
    assert out["verdict"] == "GREEN"
    assert out["cutover_kw"] == 26
    assert out["cutover_pair_partner"] == 5
    assert out["cutover_mode"] == "parallel"
    assert out["probe_present"] is True
    assert out["exit_code"] == 0
    # Pinned component fallback when envelope omits one.
    out2 = aggregator._normalise_envelope(3, {"verdict": "BLOCK"})
    assert out2["component"] == "bridge_audit_writer"


# ---------------------------------------------------------------------------
# 4. Marathon-readiness decision rule
# ---------------------------------------------------------------------------


def test_decide_marathon_all_green_is_ready(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    assert aggregator.decide_marathon(verdicts) == "READY"


def test_decide_marathon_any_block_is_block(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    verdicts[3] = "BLOCK"
    assert aggregator.decide_marathon(verdicts) == "BLOCK"


def test_decide_marathon_three_soft_fail_is_block(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    verdicts[1] = "CAUTION"
    verdicts[3] = "NOT-EXEC"
    verdicts[5] = "CAUTION"
    assert aggregator.decide_marathon(verdicts) == "BLOCK"


def test_decide_marathon_one_or_two_soft_fail_is_caution(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    verdicts[2] = "CAUTION"
    assert aggregator.decide_marathon(verdicts) == "CAUTION"
    verdicts[4] = "NOT-EXEC"
    assert aggregator.decide_marathon(verdicts) == "CAUTION"


def test_decide_marathon_all_not_exec_is_not_ready(aggregator) -> None:
    verdicts = {w: "NOT-EXEC" for w in range(1, 8)}
    assert aggregator.decide_marathon(verdicts) == "NOT-READY"


def test_decide_marathon_truth_table_sample(aggregator) -> None:
    # Walk a representative subset of the truth table to make sure
    # the decision rule is monotone in BLOCK and soft-fail counts.
    # Full 4**7 = 16384 walk is overkill; sample 50 + corners.
    rng_inputs = [
        # (block-count, caution-count, not-exec-count, expected)
        (1, 0, 0, "BLOCK"),
        (0, 0, 7, "NOT-READY"),
        (0, 1, 1, "CAUTION"),
        (0, 2, 0, "CAUTION"),
        (0, 3, 0, "BLOCK"),
        (0, 0, 3, "BLOCK"),
        (0, 1, 2, "BLOCK"),
        (0, 0, 0, "READY"),
    ]
    for blocks, cautions, notexecs, expected in rng_inputs:
        greens = 7 - blocks - cautions - notexecs
        verdicts: dict[int, str] = {}
        idx = 1
        for _ in range(blocks):
            verdicts[idx] = "BLOCK"
            idx += 1
        for _ in range(cautions):
            verdicts[idx] = "CAUTION"
            idx += 1
        for _ in range(notexecs):
            verdicts[idx] = "NOT-EXEC"
            idx += 1
        for _ in range(greens):
            verdicts[idx] = "GREEN"
            idx += 1
        assert aggregator.decide_marathon(verdicts) == expected, (
            f"({blocks},{cautions},{notexecs}) -> "
            f"{aggregator.decide_marathon(verdicts)} != {expected}"
        )


# ---------------------------------------------------------------------------
# 5. Cross-coupling drift detection
# ---------------------------------------------------------------------------


def test_cross_coupling_all_green_no_drift(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    report = aggregator.cross_coupling_report(verdicts)
    assert all(c["drift"] is False for c in report)
    assert all(c["coupled"] for c in report)


def test_cross_coupling_one_pair_drifts(aggregator) -> None:
    verdicts = {w: "GREEN" for w in range(1, 8)}
    verdicts[5] = "BLOCK"   # Welle-4 + Welle-5 drift pair (KW-26).
    report = aggregator.cross_coupling_report(verdicts)
    by_pair = {tuple(c["pair"]): c for c in report}
    assert by_pair[(4, 5)]["drift"] is True
    assert by_pair[(1, 2)]["drift"] is False
    assert by_pair[(6, 7)]["drift"] is False


def test_cross_coupling_green_vs_not_exec_drift(aggregator) -> None:
    # One half GREEN, other NOT-EXEC = drift.
    verdicts = {w: "GREEN" for w in range(1, 8)}
    verdicts[7] = "NOT-EXEC"
    report = aggregator.cross_coupling_report(verdicts)
    by_pair = {tuple(c["pair"]): c for c in report}
    assert by_pair[(6, 7)]["drift"] is True


# ---------------------------------------------------------------------------
# 6. Envelope build + markdown render
# ---------------------------------------------------------------------------


def test_build_envelope_with_partial_input_marks_missing_as_not_exec(
    aggregator,
) -> None:
    # Only Welle-1 supplied; others should default to NOT-EXEC.
    envelopes = {
        1: {
            "verdict": "GREEN",
            "probe_present": True,
            "exit_code": 0,
        }
    }
    out = aggregator.build_envelope(envelopes, github_env={})
    by_welle = {row["welle"]: row for row in out["welle_verdicts"]}
    assert by_welle[1]["verdict"] == "GREEN"
    for w in range(2, 8):
        assert by_welle[w]["verdict"] == "NOT-EXEC"
    assert out["marathon_readiness"] == "BLOCK"   # 6 NOT-EXEC -> BLOCK


def test_render_markdown_contains_seven_welle_rows(aggregator) -> None:
    envelopes = {w: {"verdict": "GREEN", "probe_present": True} for w in range(1, 8)}
    envelope = aggregator.build_envelope(envelopes, github_env={})
    md = aggregator.render_markdown(envelope)
    # Heading + each Welle by name + counts line + windows table.
    assert "Pre-Cutover Marathon Dashboard" in md
    assert "`READY`" in md
    for component in (
        "v907_verify",
        "svid_workload_identity",
        "bridge_audit_writer",
        "state_backing",
        "lifecycle_state_machine",
        "subscribe_loop",
        "recovery_workflow",
    ):
        assert component in md, f"component {component} missing from md"
    assert "Cross-Welle Coupling" in md
    assert "Cutover-Day Windows" in md
    assert "GREEN=7" in md


# ---------------------------------------------------------------------------
# 7. End-to-end: invoke aggregator binary against synthetic envelopes
# ---------------------------------------------------------------------------


def test_aggregator_binary_end_to_end(tmp_path: Path) -> None:
    probe_dir = tmp_path / "probes"
    probe_dir.mkdir()
    for w in range(1, 8):
        _write_envelope(probe_dir, w, "GREEN")
    out_json = tmp_path / "verdict.json"
    out_md = tmp_path / "summary.md"
    rc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_SCRIPT),
            "--probe-dir",
            str(probe_dir),
            "--output",
            str(out_json),
            "--summary",
            str(out_md),
        ],
        check=False,
    ).returncode
    assert rc == 0
    envelope = json.loads(out_json.read_text(encoding="utf-8"))
    assert envelope["marathon_readiness"] == "READY"
    assert len(envelope["welle_verdicts"]) == 7
    summary = out_md.read_text(encoding="utf-8")
    assert "Pre-Cutover Marathon Dashboard" in summary
    assert "GREEN=7" in summary


def test_aggregator_binary_handles_missing_probe_dir(tmp_path: Path) -> None:
    # Empty (non-existent) probe dir -> all seven NOT-EXEC -> NOT-READY.
    out_json = tmp_path / "verdict.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_SCRIPT),
            "--probe-dir",
            str(tmp_path / "does-not-exist"),
            "--output",
            str(out_json),
        ],
        check=False,
    ).returncode
    assert rc == 0
    envelope = json.loads(out_json.read_text(encoding="utf-8"))
    assert envelope["marathon_readiness"] == "NOT-READY"
    assert envelope["verdict_counts"]["NOT-EXEC"] == 7


def test_aggregator_binary_corrupt_envelope_is_block(tmp_path: Path) -> None:
    probe_dir = tmp_path / "probes"
    probe_dir.mkdir()
    # Welles 1..6 green, Welle-7 corrupt.
    for w in range(1, 7):
        _write_envelope(probe_dir, w, "GREEN")
    (probe_dir / "welle-7.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    out_json = tmp_path / "verdict.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR_SCRIPT),
            "--probe-dir",
            str(probe_dir),
            "--output",
            str(out_json),
        ],
        check=False,
    ).returncode
    assert rc == 0
    envelope = json.loads(out_json.read_text(encoding="utf-8"))
    # Welle-7 corrupt envelope -> BLOCK verdict for that Welle ->
    # marathon BLOCK.
    assert envelope["marathon_readiness"] == "BLOCK"
    by_welle = {row["welle"]: row for row in envelope["welle_verdicts"]}
    assert by_welle[7]["verdict"] == "BLOCK"


# ---------------------------------------------------------------------------
# 8. Per-Welle envelope-emitter contract
# ---------------------------------------------------------------------------


def test_emitter_writes_well_formed_envelope(
    emitter, tmp_path: Path
) -> None:
    out = tmp_path / "welle-1.json"
    rc = emitter.main(
        [
            "emit",
            "--welle",
            "1",
            "--component",
            "v907_verify",
            "--probe-script",
            "scripts/phase-3c/welle-1-pre-cutover-probe.sh",
            "--probe-present",
            "true",
            "--exit-code",
            "0",
            "--verdict",
            "GREEN",
            "--verdict-source",
            "probe-exit-code",
            "--details",
            "dry-run synth",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["welle"] == 1
    assert body["component"] == "v907_verify"
    assert body["verdict"] == "GREEN"
    assert body["probe_present"] is True
    assert body["exit_code"] == 0


def test_emitter_rejects_invalid_welle_index(
    emitter, tmp_path: Path
) -> None:
    # argparse's choices=range(1,8) rejects 8 with SystemExit(2).
    with pytest.raises(SystemExit):
        emitter.main(
            [
                "emit",
                "--welle",
                "8",
                "--component",
                "x",
                "--probe-script",
                "x",
                "--probe-present",
                "true",
                "--verdict",
                "GREEN",
                "--verdict-source",
                "test",
                "--output",
                str(tmp_path / "x.json"),
            ]
        )


def test_emitter_rejects_invalid_verdict(emitter, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        emitter.main(
            [
                "emit",
                "--welle",
                "1",
                "--component",
                "x",
                "--probe-script",
                "x",
                "--probe-present",
                "true",
                "--verdict",
                "MAYBE",
                "--verdict-source",
                "test",
                "--output",
                str(tmp_path / "x.json"),
            ]
        )
