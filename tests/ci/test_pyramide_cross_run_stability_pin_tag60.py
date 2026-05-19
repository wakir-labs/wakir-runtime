"""Tag-60 Pyramide Cross-Run Stability-Pin: helper + workflow + fixture tests.

Owner: Amara (QA).
Doc-Anchor: docs/quality-gates/pre-cutover-acceptance-run-order.md (Tag-57).
Helper:    tooling/ci/verify_pyramide_cross_run_stability.py.
Workflow:  .github/workflows/pyramide-cross-run-stability-pin-gate.yml.
Fixtures:  tests/ci/fixtures/green-*.json.

Anlass
------
Tag-57 PR #365 hat den Pre-Cutover-Acceptance-Pyramide Run-Order-Doc
plus den Verdict-Aggregator (per-Welle + Global) gepinnt. Tag-58 hat
das Cross-Layer Dependency-DAG verifiziert. Tag-60 macht aus dem
Aggregator-Envelope eine **deterministische** Quality-Gate-Signal-
Source: 3+ konsekutive Invocations auf identischem Input MUESSEN
byte-identische stdout-bytes emittieren.

Test-Klassen
------------
- Helper-Constants / Verdict-Schema
- Fixture-Loading (positive + negative paths)
- Cross-Run-Verify (STABLE / DRIFT / ERROR-paths)
- CLI surface (argparse, --json / human, exit-codes)
- Canonical fixture-suite (5 fixtures, all CROSS-RUN-STABLE)
- Workflow contract (job-display-name, path-filter, stages, etc.)
- Doc-Anchor presence

Sandbox
-------
Stdlib + pytest only. Helper invokes the aggregator via subprocess
(in-process python3). No network, no podman, no live-VM.

Cross-Review markers
--------------------
Zone-M: Engineering-personae via Tomas (Aggregator substrate-owner).
Zone-N: Henrik (Audit) - Verdict-determinism ist Audit-evidence-input.
"""

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import pathlib
import subprocess
import sys
from typing import Dict, List

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_pyramide_cross_run_stability.py"
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_pyramide_run_order_verdict.py"
)
FIXTURE_DIR = REPO_ROOT / "tests" / "ci" / "fixtures"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pyramide-cross-run-stability-pin-gate.yml"
)
DOC_PATH = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-cutover-acceptance-run-order.md"
)

CANONICAL_FIXTURES = [
    "green-welle-1-marathon-entry.json",
    "green-welle-2-doppel-entry.json",
    "green-welle-5-doppel-entry.json",
    "green-welle-7-doppel-final.json",
    "green-global-marathon-final.json",
]


# ---------------------------------------------------------------------------
# Helper-module loader
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def helper_module():
    """Import the helper under a stable module name."""
    spec = importlib.util.spec_from_file_location(
        "verify_pyramide_cross_run_stability_t60", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"helper not loadable: {HELPER_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Helper-Constants / Verdict-Schema
# ---------------------------------------------------------------------------


def test_helper_constants_pinned(helper_module):
    """Pin schema-version, doc-version, verdict-strings, exit-codes."""
    assert helper_module.SCHEMA_VERSION == "1.0.0"
    assert helper_module.DOC_VERSION == "tag-60"
    assert helper_module.VERDICT_STABLE == "CROSS-RUN-STABLE"
    assert helper_module.VERDICT_DRIFT == "CROSS-RUN-DRIFT"
    assert helper_module.VERDICT_ERROR == "CROSS-RUN-ERROR"
    assert helper_module.EXIT_STABLE == 0
    assert helper_module.EXIT_ERROR == 1
    assert helper_module.EXIT_DRIFT == 2
    # CROSS-RUN-DRIFT must use exit-code 2 (NOT 1) so it is distinguishable
    # from infra/parse errors at workflow level.
    assert helper_module.EXIT_DRIFT != helper_module.EXIT_ERROR


def test_helper_default_min_max_runs(helper_module):
    """3 <= DEFAULT_N_RUNS == MIN_N_RUNS and MAX is bounded."""
    assert helper_module.DEFAULT_N_RUNS == 3
    assert helper_module.MIN_N_RUNS == 3
    assert helper_module.MAX_N_RUNS >= 8
    assert helper_module.MIN_N_RUNS <= helper_module.DEFAULT_N_RUNS
    assert helper_module.DEFAULT_N_RUNS <= helper_module.MAX_N_RUNS


def test_helper_doc_anchor_is_tag57_run_order_doc(helper_module):
    """Helper points at Tag-57 doc, not a Tag-60-specific stub."""
    assert helper_module.DOC_ANCHOR == (
        "docs/quality-gates/pre-cutover-acceptance-run-order.md"
    )


# ---------------------------------------------------------------------------
# 2. Fixture-loading (positive + negative)
# ---------------------------------------------------------------------------


def test_fixture_load_welle_mode_ok(helper_module, tmp_path):
    fp = tmp_path / "f.json"
    fp.write_text(
        json.dumps(
            {
                "mode": "welle",
                "welle": 1,
                "layer_outcomes": {"L1-smoke": "GREEN"},
            }
        )
    )
    data = helper_module._load_fixture(fp)
    assert data["mode"] == "welle"
    assert data["welle"] == 1


def test_fixture_load_global_mode_ok(helper_module, tmp_path):
    fp = tmp_path / "g.json"
    fp.write_text(
        json.dumps(
            {
                "mode": "global",
                "layer_outcomes": {"L1-full": "GREEN"},
                "per_welle_verdicts": {str(i): "GREEN" for i in range(1, 8)},
            }
        )
    )
    data = helper_module._load_fixture(fp)
    assert data["mode"] == "global"


def test_fixture_load_rejects_invalid_mode(helper_module, tmp_path):
    fp = tmp_path / "bad.json"
    fp.write_text(json.dumps({"mode": "nope", "layer_outcomes": {}}))
    with pytest.raises(ValueError, match="mode"):
        helper_module._load_fixture(fp)


def test_fixture_load_rejects_welle_out_of_range(helper_module, tmp_path):
    fp = tmp_path / "bad.json"
    fp.write_text(
        json.dumps(
            {
                "mode": "welle",
                "welle": 99,
                "layer_outcomes": {"L1-smoke": "GREEN"},
            }
        )
    )
    with pytest.raises(ValueError, match="welle"):
        helper_module._load_fixture(fp)


def test_fixture_load_rejects_missing_file(helper_module, tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        helper_module._load_fixture(missing)


def test_fixture_load_rejects_global_without_per_welle(helper_module, tmp_path):
    fp = tmp_path / "g.json"
    fp.write_text(json.dumps({"mode": "global", "layer_outcomes": {}}))
    with pytest.raises(ValueError, match="per_welle_verdicts"):
        helper_module._load_fixture(fp)


# ---------------------------------------------------------------------------
# 3. Cross-Run-Verify (real aggregator)
# ---------------------------------------------------------------------------


def _welle_1_green_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    fp = tmp_path / "welle_1_green.json"
    fp.write_text(
        json.dumps(
            {
                "mode": "welle",
                "welle": 1,
                "layer_outcomes": {
                    "L1-smoke": "GREEN",
                    "L2-dryrun": "GREEN",
                    "L4-full": "GREEN",
                    "L5-full": "GREEN",
                    "L6-full": "GREEN",
                    "L2-live": "GREEN",
                    "L2-shadow": "GREEN",
                    "L2-record-validation": "GREEN",
                },
            }
        )
    )
    return fp


def test_cross_run_verify_welle1_green_is_stable(helper_module, tmp_path):
    fp = _welle_1_green_fixture(tmp_path)
    env = helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-STABLE"
    assert env["exit_code"] == 0
    assert env["n_runs"] == 3
    assert env["mode"] == "welle"
    assert env["welle_id"] == 1
    assert len(env["envelope_hashes"]) == 3
    assert len(set(env["envelope_hashes"])) == 1
    assert env["stable_hash"] == env["envelope_hashes"][0]
    assert env["drift_pairs"] == []
    assert isinstance(env["first_envelope"], dict)
    assert env["first_envelope"].get("verdict") == "GREEN"


def test_cross_run_verify_higher_n_still_stable(helper_module, tmp_path):
    fp = _welle_1_green_fixture(tmp_path)
    env = helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=8)
    assert env["verdict"] == "CROSS-RUN-STABLE"
    assert env["n_runs"] == 8
    assert len(env["envelope_hashes"]) == 8
    assert len(set(env["envelope_hashes"])) == 1


def test_cross_run_verify_global_green_is_stable(helper_module, tmp_path):
    fp = tmp_path / "global_green.json"
    fp.write_text(
        json.dumps(
            {
                "mode": "global",
                "per_welle_verdicts": {str(i): "GREEN" for i in range(1, 8)},
                "layer_outcomes": {
                    "L1-full": "GREEN",
                    "L3-full": "GREEN",
                    "live-verify-gate": "GREEN",
                },
            }
        )
    )
    env = helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-STABLE"
    assert env["mode"] == "global"
    assert env["welle_id"] is None


def test_cross_run_verify_rejects_runs_below_min(helper_module, tmp_path):
    fp = _welle_1_green_fixture(tmp_path)
    with pytest.raises(ValueError, match="n_runs"):
        helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=1)


def test_cross_run_verify_rejects_runs_above_max(helper_module, tmp_path):
    fp = _welle_1_green_fixture(tmp_path)
    with pytest.raises(ValueError, match="n_runs"):
        helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=999)


def test_cross_run_verify_missing_fixture_emits_error_envelope(
    helper_module, tmp_path
):
    """Missing fixture yields CROSS-RUN-ERROR envelope (not raise)."""
    missing = tmp_path / "nope.json"
    env = helper_module.cross_run_verify(REPO_ROOT, missing, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-ERROR"
    assert env["exit_code"] == 1
    assert env["envelope_hashes"] == []
    assert env["stable_hash"] is None
    assert any("fixture-load-error" in n for n in env["notes"])


def test_cross_run_verify_missing_aggregator_emits_error_envelope(
    helper_module, tmp_path
):
    """When aggregator helper is missing, verifier emits CROSS-RUN-ERROR."""
    fp = _welle_1_green_fixture(tmp_path)
    isolated_root = tmp_path / "isolated_root"
    isolated_root.mkdir()
    # No aggregator at isolated_root/tooling/ci/aggregate_..._verdict.py
    env = helper_module.cross_run_verify(isolated_root, fp, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-ERROR"
    assert env["exit_code"] == 1
    assert any("aggregator-missing" in n for n in env["notes"])


# ---------------------------------------------------------------------------
# 4. Drift-detection synthetic
# ---------------------------------------------------------------------------


def test_drift_detection_synthetic(helper_module, tmp_path):
    """Inject a fake aggregator that emits drifting stdout; verifier flags DRIFT."""
    fake_root = tmp_path / "fake_root"
    fake_dir = fake_root / "tooling" / "ci"
    fake_dir.mkdir(parents=True)
    fake_agg = fake_dir / "aggregate_pyramide_run_order_verdict.py"
    # The fake aggregator emits a counter-suffixed envelope so each
    # consecutive run hashes differently. It still exits 0 and emits
    # valid JSON so the verifier flags DRIFT (not ERROR).
    fake_agg.write_text(
        "import json, os, pathlib, sys, time\n"
        "counter_path = pathlib.Path(__file__).parent / 'counter.txt'\n"
        "n = 0\n"
        "if counter_path.is_file():\n"
        "    n = int(counter_path.read_text()) + 1\n"
        "counter_path.write_text(str(n))\n"
        "json.dump({'run_idx': n, 'verdict': 'GREEN'}, sys.stdout, sort_keys=True)\n"
        "sys.stdout.write('\\n')\n"
    )
    fp = _welle_1_green_fixture(tmp_path)
    env = helper_module.cross_run_verify(fake_root, fp, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-DRIFT"
    assert env["exit_code"] == 2
    assert len(env["envelope_hashes"]) == 3
    assert len(set(env["envelope_hashes"])) == 3
    # drift_pairs should record every distinct (a,b)
    assert len(env["drift_pairs"]) >= 1
    assert all(
        isinstance(p, list) and len(p) == 2 for p in env["drift_pairs"]
    )


def test_drift_pair_indices_are_within_bounds(helper_module, tmp_path):
    """Every drift_pair index must be in [0, n_runs)."""
    fake_root = tmp_path / "fake_root"
    fake_dir = fake_root / "tooling" / "ci"
    fake_dir.mkdir(parents=True)
    fake_agg = fake_dir / "aggregate_pyramide_run_order_verdict.py"
    fake_agg.write_text(
        "import json, pathlib, sys\n"
        "counter_path = pathlib.Path(__file__).parent / 'counter.txt'\n"
        "n = 0\n"
        "if counter_path.is_file():\n"
        "    n = int(counter_path.read_text()) + 1\n"
        "counter_path.write_text(str(n))\n"
        "json.dump({'n': n}, sys.stdout, sort_keys=True)\n"
        "sys.stdout.write('\\n')\n"
    )
    fp = _welle_1_green_fixture(tmp_path)
    env = helper_module.cross_run_verify(fake_root, fp, n_runs=4)
    assert env["verdict"] == "CROSS-RUN-DRIFT"
    for pair in env["drift_pairs"]:
        assert 0 <= pair[0] < pair[1] < env["n_runs"]


# ---------------------------------------------------------------------------
# 5. Hash function semantics
# ---------------------------------------------------------------------------


def test_hash_envelope_is_sha256_of_raw_bytes(helper_module):
    """_hash_envelope must hash raw UTF-8 stdout bytes."""
    sample = '{"a": 1, "b": [2, 3]}\n'
    expected = hashlib.sha256(sample.encode("utf-8")).hexdigest()
    got = helper_module._hash_envelope(sample)
    assert got == expected


def test_hash_envelope_distinguishes_whitespace(helper_module):
    """Whitespace drift must flip the hash (proof of byte-stability semantics)."""
    a = '{"a":1}'
    b = '{"a": 1}'
    assert helper_module._hash_envelope(a) != helper_module._hash_envelope(b)


# ---------------------------------------------------------------------------
# 6. CLI surface
# ---------------------------------------------------------------------------


def test_cli_emits_cross_run_stable_against_canonical_welle1(tmp_path):
    """End-to-end CLI invocation on a real fixture returns exit 0."""
    fp = FIXTURE_DIR / "green-welle-1-marathon-entry.json"
    assert fp.is_file()
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--fixture",
            str(fp),
            "--runs",
            "3",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, (
        f"CLI failed: rc={proc.returncode} stderr={proc.stderr}"
    )
    env = json.loads(proc.stdout)
    assert env["verdict"] == "CROSS-RUN-STABLE"
    assert env["exit_code"] == 0


def test_cli_human_output_includes_verdict_token(tmp_path):
    """Default (non-JSON) output must include 'verdict:' line."""
    fp = FIXTURE_DIR / "green-welle-1-marathon-entry.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--fixture",
            str(fp),
            "--runs",
            "3",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0
    assert "verdict:" in proc.stdout
    assert "CROSS-RUN-STABLE" in proc.stdout
    assert "stable_hash:" in proc.stdout


def test_cli_requires_fixture_argument():
    """argparse must require --fixture (no default)."""
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--runs", "3"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode != 0
    assert "fixture" in proc.stderr.lower() or "fixture" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# 7. Canonical fixture-suite end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", CANONICAL_FIXTURES)
def test_canonical_fixture_is_cross_run_stable(helper_module, fixture_name):
    """Every canonical fixture in tests/ci/fixtures/ must be CROSS-RUN-STABLE."""
    fp = FIXTURE_DIR / fixture_name
    assert fp.is_file(), f"canonical fixture missing: {fp}"
    env = helper_module.cross_run_verify(REPO_ROOT, fp, n_runs=3)
    assert env["verdict"] == "CROSS-RUN-STABLE", (
        f"{fixture_name} drifted: {env['notes']}"
    )
    assert env["exit_code"] == 0
    assert len(set(env["envelope_hashes"])) == 1


def test_canonical_fixture_set_is_complete():
    """The canonical fixture-set must contain exactly the 5 declared entries."""
    on_disk = {
        p.name for p in FIXTURE_DIR.glob("green-*.json") if p.is_file()
    }
    declared = set(CANONICAL_FIXTURES)
    assert on_disk == declared, (
        f"fixture-set drift: on_disk={on_disk} declared={declared}"
    )


def test_canonical_fixtures_cover_marathon_entry_doppel_and_global():
    """Coverage claim: 5 fixtures must cover Welle-1 entry, 2x Doppel, Welle-7 final, Global."""
    welles_covered: List[int] = []
    has_global = False
    for name in CANONICAL_FIXTURES:
        data = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        if data["mode"] == "welle":
            welles_covered.append(int(data["welle"]))
        else:
            has_global = True
    assert 1 in welles_covered, "Welle-1 marathon-entry missing"
    assert 7 in welles_covered, "Welle-7 final missing"
    # Doppel-Welle entries are {2,5,7} - we must cover at least 2 of them
    doppel = {2, 5, 7}
    assert len(set(welles_covered) & doppel) >= 2, (
        f"need >=2 Doppel-Welle fixtures, got {welles_covered}"
    )
    assert has_global, "Global fixture missing"


# ---------------------------------------------------------------------------
# 8. Workflow contract
# ---------------------------------------------------------------------------


def _read_workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_has_contracted_job_display_name():
    """Per feedback_branch_protection_check_names.md the job-display-name is the
    Required-Status-Check identifier and must be exact."""
    text = _read_workflow_text()
    assert (
        'name: "pyramide cross-run stability pin (5 fixtures, 3 runs each)"'
        in text
    ), "job-display-name drift"


def test_workflow_path_filter_covers_canonical_fixtures():
    text = _read_workflow_text()
    for name in CANONICAL_FIXTURES:
        assert (
            f"tests/ci/fixtures/{name}" in text
        ), f"path-filter missing {name}"


def test_workflow_path_filter_covers_helper_and_aggregator_and_self():
    text = _read_workflow_text()
    assert "tooling/ci/aggregate_pyramide_run_order_verdict.py" in text
    assert "tooling/ci/verify_pyramide_cross_run_stability.py" in text
    assert (
        ".github/workflows/pyramide-cross-run-stability-pin-gate.yml" in text
    )
    assert "tests/ci/test_pyramide_cross_run_stability_pin_tag60.py" in text


def test_workflow_permissions_read_only():
    text = _read_workflow_text()
    assert "permissions:" in text
    assert "contents: read" in text


def test_workflow_concurrency_does_not_cancel():
    text = _read_workflow_text()
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text


def test_workflow_uses_python_313():
    text = _read_workflow_text()
    assert 'python-version: "3.13"' in text


def test_workflow_invokes_helper_and_test_suite():
    text = _read_workflow_text()
    assert "tests/ci/test_pyramide_cross_run_stability_pin_tag60.py" in text
    assert "verify_pyramide_cross_run_stability.py" in text


def test_workflow_pins_deterministic_env():
    """PYTHONHASHSEED=0 and LC_ALL=C must be set on both stages so any drift
    in the aggregator's nested dict-ordering or locale-formatting is pinned."""
    text = _read_workflow_text()
    assert 'PYTHONHASHSEED: "0"' in text
    assert 'LC_ALL: "C"' in text


def test_workflow_runs_three_or_more_consecutive_runs():
    text = _read_workflow_text()
    assert "--runs 3" in text or "--runs\n            3" in text
    # Three is the MIN_N_RUNS contract; encoding it twice (display-name +
    # CLI invocation) makes drift visible.
    assert "3 runs each" in text


def test_workflow_has_workflow_dispatch_trigger():
    text = _read_workflow_text()
    assert "workflow_dispatch:" in text


def test_workflow_uploads_envelope_artifact():
    """Operator-readable evidence: the cross-run envelopes must be uploaded
    so Henrik (Audit) can pull the artifact post-hoc."""
    text = _read_workflow_text()
    assert "actions/upload-artifact@v4" in text
    assert "cross-run-stability-" in text


# ---------------------------------------------------------------------------
# 9. Doc-Anchor presence
# ---------------------------------------------------------------------------


def test_doc_anchor_file_exists():
    assert DOC_PATH.is_file(), f"Tag-57 doc missing at {DOC_PATH}"


def test_helper_doc_anchor_matches_module_docstring(helper_module):
    """The helper's DOC_ANCHOR constant must be cited in its module docstring."""
    assert helper_module.DOC_ANCHOR in (helper_module.__doc__ or "")


# ---------------------------------------------------------------------------
# 10. Cross-Review markers (Zone-M + Zone-N)
# ---------------------------------------------------------------------------


def test_workflow_doc_footer_marks_zone_m_and_zone_n():
    """Cross-Review markers are a Tag-60 disciplinary item per the dispatch
    auftrag; both must appear in the workflow comment header."""
    text = _read_workflow_text()
    assert "Zone-M" in text
    assert "Zone-N" in text


# ---------------------------------------------------------------------------
# 11. Determinism guard
# ---------------------------------------------------------------------------


def test_invoke_aggregator_pins_hashseed_and_locale(helper_module, tmp_path):
    """The verifier MUST set PYTHONHASHSEED=0 and LC_ALL=C so its own
    invocation of the aggregator is deterministic, regardless of the
    operator-shell env."""
    # Read the helper source and verify the env-pin literals are present.
    src = HELPER_PATH.read_text(encoding="utf-8")
    assert 'env["PYTHONHASHSEED"] = "0"' in src
    assert 'env["LC_ALL"] = "C"' in src
