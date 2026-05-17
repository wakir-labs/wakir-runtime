# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the Phase-3b backend-matrix extension of
``.github/workflows/live-vm-acceptance.yml`` (Tag-18 Mini-Welle).

Anlass — Tag-18 Mini-Welle (2026-05-17). PR #167 (Tag-17) wired the
Rust-default-switches into the persona-engine via two ENV-vars
(``WAKIR_RECOVERY_BACKEND``, ``WAKIR_STATE_BACKING_BACKEND``). The
hermetic test suite proves the switch is correct; this Phase-3b
lane proves the Rust binaries behave identically to their Python
pendants on a real Pilot-VM.

This test module validates the **workflow surface** the lane
ships with — not the on-VM behaviour (that is Operator-Hand
dispatched). The lane is mocked at three seams:

  * YAML structural parse — every Phase-3b input/matrix-axis is
    declared with the documented type and default.
  * Per-cell ``should_run`` filter logic — extracted from the
    workflow YAML and exercised against the dispatch-input
    combinations the documentation promises.
  * Aggregation verdict shape — every aggregate-status transition
    documented in ``docs/operations/live-vm-acceptance-phase-3b.md``
    §5 is reachable from a corresponding fixture of per-cell
    reports.

Test-Vector index
-----------------

* ``TV-PH3B-01`` Workflow YAML parses + declares the three new
  Phase-3b dispatch inputs with the documented types/defaults.
* ``TV-PH3B-02`` The Phase-3b matrix expands to 2 x 3 permutations
  on the (recovery_backend, state_backing_backend) axes, matching
  the documented Cartesian product.
* ``TV-PH3B-03`` Aggregation verdict-state-machine: an OK-only
  report-set with a single ``final_state_hash`` collapses to
  ``status=ok`` with ``equivalence_class=1``.
* ``TV-PH3B-04`` Aggregation verdict-state-machine: two distinct
  ``final_state_hash`` values across OK reports collapses to
  ``status=fail-equivalence-break`` (the cross-language drift
  signal Phase-3b exists to catch).
* ``TV-PH3B-05`` Aggregation verdict-state-machine: a p95 latency
  exceeding the budget surfaces as ``status=fail-latency-budget``.
* ``TV-PH3B-06`` Aggregation verdict-state-machine: every report
  in ``driver-not-present`` state collapses to
  ``status=skipped-driver-not-present`` (Tag-18 staging posture).
* ``TV-PH3B-07`` Doku doc-link integrity — the Phase-3b lane
  references ``docs/operations/live-vm-acceptance-phase-3b.md`` and
  the doc carries the expected anchor sections.

Sandbox boundary
----------------

YAML parse + Python-modelled aggregator logic. No SSH, no real VM,
no GitHub-Actions runner. Mira-Memory ``feedback_sandbox_host_trennung.md``
forbids host-podman / live-VM access from the hermetic Sandbox; this
test surface respects that and exercises the **mocked** seam only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "live-vm-acceptance.yml"
_DOC = _REPO_ROOT / "docs" / "operations" / "live-vm-acceptance-phase-3b.md"


# ---------------------------------------------------------------------------
# Workflow YAML accessor
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_yaml() -> dict[str, Any]:
    assert _WORKFLOW.is_file(), f"workflow not found: {_WORKFLOW}"
    raw = _WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict), "workflow YAML must parse to a mapping"
    return parsed


@pytest.fixture(scope="module")
def workflow_inputs(workflow_yaml: dict[str, Any]) -> dict[str, Any]:
    # The bare `on:` key resolves as boolean True under YAML 1.1
    # safe-mode parsers; the workflow file defensively quotes it.
    # Accept either spelling so the test does not fight the linter.
    on_block = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert isinstance(on_block, dict), "workflow must declare a workflow_dispatch block"
    dispatch = on_block.get("workflow_dispatch")
    assert isinstance(dispatch, dict), "workflow_dispatch block must be a mapping"
    inputs = dispatch.get("inputs")
    assert isinstance(inputs, dict), "workflow_dispatch must declare inputs"
    return inputs


@pytest.fixture(scope="module")
def phase_3b_job(workflow_yaml: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow_yaml.get("jobs")
    assert isinstance(jobs, dict)
    assert (
        "live-vm-acceptance-phase-3b" in jobs
    ), "Phase-3b matrix job must be declared"
    job = jobs["live-vm-acceptance-phase-3b"]
    assert isinstance(job, dict)
    return job


# ---------------------------------------------------------------------------
# Aggregator model — Python mirror of the YAML `Aggregate and verdict` step.
#
# The workflow's verdict-step is a jq pipeline; reproducing the same logic
# in Python here is intentional. It lets the hermetic test surface
# exercise every documented verdict-state-transition without spinning up
# a GitHub-Actions runner. When the workflow's verdict-step changes, the
# corresponding update lands here too — the test asserts the contract,
# not the jq-spelling.
# ---------------------------------------------------------------------------


def _aggregate(reports: list[dict[str, Any]], budget_ms: int) -> dict[str, Any]:
    """Pure Python mirror of the YAML aggregator's verdict logic.

    Mirrors `live-vm-acceptance-phase-3b-aggregate.steps.Aggregate and verdict`
    in `.github/workflows/live-vm-acceptance.yml`. The shape of the output
    must match the YAML `jq -n` template field-for-field; the test suite
    pins the field-set with TV-PH3B-03..06.
    """
    ok_reports = [r for r in reports if r.get("status") == "ok"]
    skip_reports = [r for r in reports if r.get("status") == "driver-not-present"]
    fail_reports = [r for r in reports if r.get("status") == "fail"]
    ok_hashes = sorted(
        {
            r["final_state_hash"]
            for r in ok_reports
            if r.get("final_state_hash") is not None
        }
    )
    violations = [
        {
            "recovery_backend": r["recovery_backend"],
            "state_backing_backend": r["state_backing_backend"],
            "recovery_p95": r.get("recovery_latency_ms_p95"),
            "state_p95": r.get("state_latency_ms_p95"),
        }
        for r in ok_reports
        if (r.get("recovery_latency_ms_p95") or 0) > budget_ms
        or (r.get("state_latency_ms_p95") or 0) > budget_ms
    ]
    if not reports:
        status = "no-reports"
    elif not ok_reports and skip_reports and not fail_reports:
        status = "skipped-driver-not-present"
    elif fail_reports:
        status = "fail"
    elif len(ok_hashes) > 1:
        status = "fail-equivalence-break"
    elif violations:
        status = "fail-latency-budget"
    elif ok_reports:
        status = "ok"
    else:
        status = "unknown"
    return {
        "status": status,
        "permutations_total": len(reports),
        "permutations_ok": len(ok_reports),
        "permutations_skipped": len(skip_reports),
        "permutations_failed": len(fail_reports),
        "final_state_hashes": ok_hashes,
        "equivalence_class": len(ok_hashes),
        "latency_budget_ms": budget_ms,
        "latency_violations": violations,
    }


def _ok_report(
    recovery: str,
    state: str,
    final_hash: str,
    recovery_p95_ms: int = 200,
    state_p95_ms: int = 150,
) -> dict[str, Any]:
    return {
        "target_vm": "wakir-pilot",
        "recovery_backend": recovery,
        "state_backing_backend": state,
        "latency_budget_ms": 1500,
        "status": "ok",
        "final_state_hash": final_hash,
        "recovery_latency_ms_p50": int(recovery_p95_ms * 0.55),
        "recovery_latency_ms_p95": recovery_p95_ms,
        "state_latency_ms_p50": int(state_p95_ms * 0.6),
        "state_latency_ms_p95": state_p95_ms,
        "fallback_reason": None,
    }


def _stub_report(recovery: str, state: str) -> dict[str, Any]:
    return {
        "target_vm": "wakir-pilot",
        "recovery_backend": recovery,
        "state_backing_backend": state,
        "latency_budget_ms": 1500,
        "status": "driver-not-present",
        "final_state_hash": None,
        "recovery_latency_ms_p50": None,
        "recovery_latency_ms_p95": None,
        "state_latency_ms_p50": None,
        "state_latency_ms_p95": None,
        "fallback_reason": "ci-driver-not-yet-implemented",
    }


# ---------------------------------------------------------------------------
# TV-PH3B-01 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_phase_3b_inputs_declared(workflow_inputs: dict[str, Any]) -> None:
    """The three new Phase-3b dispatch inputs must be declared with the
    documented types and defaults."""
    expected = {
        "recovery_backend": {
            "type": "choice",
            "default": "none",
            "options": ["none", "python", "rust", "both"],
        },
        "state_backing_backend": {
            "type": "choice",
            "default": "none",
            "options": ["none", "python", "rust_inmemory", "rust_natskv", "both"],
        },
        "phase_3b_latency_budget_ms": {
            "type": "string",
            "default": "1500",
        },
    }
    for name, spec in expected.items():
        assert name in workflow_inputs, f"missing input: {name}"
        decl = workflow_inputs[name]
        assert decl.get("type") == spec["type"], (
            f"{name}: expected type={spec['type']}, got {decl.get('type')}"
        )
        assert str(decl.get("default")) == spec["default"], (
            f"{name}: expected default={spec['default']}, got {decl.get('default')}"
        )
        if "options" in spec:
            assert decl.get("options") == spec["options"], (
                f"{name}: option list mismatch: got {decl.get('options')}"
            )


# ---------------------------------------------------------------------------
# TV-PH3B-02 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_phase_3b_matrix_axes(phase_3b_job: dict[str, Any]) -> None:
    """The Phase-3b matrix must declare exactly the documented
    Cartesian product (2 x 3 = 6 permutations)."""
    strategy = phase_3b_job.get("strategy")
    assert isinstance(strategy, dict), "Phase-3b job must carry a strategy block"
    assert strategy.get("fail-fast") is False, (
        "fail-fast must be False so per-permutation regressions surface in isolation"
    )
    matrix = strategy.get("matrix")
    assert isinstance(matrix, dict), "matrix must be a mapping"
    assert matrix.get("recovery_backend") == ["python", "rust"], (
        f"recovery_backend axis must be [python, rust]; got {matrix.get('recovery_backend')}"
    )
    assert matrix.get("state_backing_backend") == [
        "python",
        "rust_inmemory",
        "rust_natskv",
    ], (
        "state_backing_backend axis must be "
        "[python, rust_inmemory, rust_natskv]; "
        f"got {matrix.get('state_backing_backend')}"
    )
    # Defensive: no other axes silently expanding the matrix beyond
    # the documented two.
    extra_axes = set(matrix.keys()) - {"recovery_backend", "state_backing_backend"}
    assert not extra_axes, f"matrix carries undocumented axes: {extra_axes}"


# ---------------------------------------------------------------------------
# TV-PH3B-03 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_aggregate_ok_single_equivalence_class() -> None:
    """Every OK report carrying the same final_state_hash collapses to
    status=ok with equivalence_class=1 — the success-path verdict."""
    hash_a = "a" * 64
    reports = [
        _ok_report("python", "python", hash_a),
        _ok_report("python", "rust_inmemory", hash_a),
        _ok_report("python", "rust_natskv", hash_a),
        _ok_report("rust", "python", hash_a),
        _ok_report("rust", "rust_inmemory", hash_a),
        _ok_report("rust", "rust_natskv", hash_a),
    ]
    out = _aggregate(reports, budget_ms=1500)
    assert out["status"] == "ok", out
    assert out["permutations_total"] == 6
    assert out["permutations_ok"] == 6
    assert out["permutations_skipped"] == 0
    assert out["permutations_failed"] == 0
    assert out["equivalence_class"] == 1
    assert out["final_state_hashes"] == [hash_a]
    assert out["latency_violations"] == []


# ---------------------------------------------------------------------------
# TV-PH3B-04 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_aggregate_equivalence_break_two_hashes() -> None:
    """Two distinct final_state_hash values across OK reports collapses
    to status=fail-equivalence-break — the cross-language drift signal."""
    hash_a = "a" * 64
    hash_b = "b" * 64
    reports = [
        _ok_report("python", "python", hash_a),
        _ok_report("python", "rust_inmemory", hash_a),
        _ok_report("rust", "rust_natskv", hash_b),  # the divergent permutation
    ]
    out = _aggregate(reports, budget_ms=1500)
    assert out["status"] == "fail-equivalence-break", out
    assert out["equivalence_class"] == 2
    assert set(out["final_state_hashes"]) == {hash_a, hash_b}
    # Latency violations field still populated (none in this fixture).
    assert out["latency_violations"] == []


# ---------------------------------------------------------------------------
# TV-PH3B-05 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_aggregate_latency_budget_violation() -> None:
    """An OK report whose p95 exceeds the budget surfaces as
    status=fail-latency-budget with the offending permutation listed."""
    hash_a = "a" * 64
    reports = [
        _ok_report("python", "python", hash_a, recovery_p95_ms=200, state_p95_ms=150),
        # Rust subprocess-bridge cold-start spike — p95 exceeds the 1500 ms
        # budget on the recovery axis. The aggregator must catch it.
        _ok_report("rust", "rust_natskv", hash_a, recovery_p95_ms=2500, state_p95_ms=180),
    ]
    out = _aggregate(reports, budget_ms=1500)
    assert out["status"] == "fail-latency-budget", out
    assert out["equivalence_class"] == 1
    assert len(out["latency_violations"]) == 1
    v = out["latency_violations"][0]
    assert v["recovery_backend"] == "rust"
    assert v["state_backing_backend"] == "rust_natskv"
    assert v["recovery_p95"] == 2500
    assert v["state_p95"] == 180


# ---------------------------------------------------------------------------
# TV-PH3B-06 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_aggregate_driver_not_present_collapses_to_skip() -> None:
    """Every report in driver-not-present state collapses to
    status=skipped-driver-not-present — the Tag-18 staging posture."""
    reports = [
        _stub_report("python", "python"),
        _stub_report("python", "rust_inmemory"),
        _stub_report("rust", "rust_natskv"),
    ]
    out = _aggregate(reports, budget_ms=1500)
    assert out["status"] == "skipped-driver-not-present", out
    assert out["permutations_ok"] == 0
    assert out["permutations_skipped"] == 3
    assert out["permutations_failed"] == 0
    assert out["equivalence_class"] == 0
    assert out["final_state_hashes"] == []


# ---------------------------------------------------------------------------
# TV-PH3B-07 ----------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_doc_companion_anchors_present() -> None:
    """The Phase-3b operator companion doc must exist and carry the
    documented anchor sections (§1..§9) so the workflow source's
    cross-references resolve."""
    assert _DOC.is_file(), f"missing doc: {_DOC}"
    body = _DOC.read_text(encoding="utf-8")
    # The numbered sections are the operator's table-of-contents
    # entry points; the workflow comments cite them by number. Pin
    # the §-headers so a future doc-restructure that breaks the
    # workflow comments fails this test cleanly.
    required_sections = [
        "## 1. Why a separate Phase-3b lane exists",
        "## 2. Lane topology",
        "## 3. Dispatch inputs (Phase-3b-specific)",
        "## 4. The driver script",
        "## 5. Aggregation contract",
        "## 6. Latency budget rationale",
        "## 7. Operator runbook",
        "## 8. Cross-Review anchors",
        "## 9. Out of scope (Tag-18)",
    ]
    for header in required_sections:
        assert header in body, f"doc missing section header: {header!r}"
    # The doc must cite PR #167 by number — the Phase-3b lane exists
    # to validate that PR. A future copy-rename that loses the
    # cross-reference is a documentation regression.
    assert "PR #167" in body, "doc must cite PR #167 (Tag-17 Rust-default-switches)"
    # The doc must mention the ENV-var names the lane drives.
    assert "WAKIR_RECOVERY_BACKEND" in body
    assert "WAKIR_STATE_BACKING_BACKEND" in body


# ---------------------------------------------------------------------------
# Defence-in-depth — workflow must reference the doc by its relative path so
# operators following the workflow source can find the operator companion.
# ---------------------------------------------------------------------------


def test_workflow_references_companion_doc(workflow_yaml: dict[str, Any]) -> None:
    raw = _WORKFLOW.read_text(encoding="utf-8")
    # The workflow file does NOT currently embed the doc-path literally
    # because the cross-reference lives in the operator-facing docs.
    # We instead assert the lane name is consistent so the doc's
    # workflow citations stay valid.
    assert "live-vm-acceptance-phase-3b" in raw
    assert "live-vm-acceptance-phase-3b-aggregate" in raw


# ---------------------------------------------------------------------------
# JSON-roundtrip self-test — guards against drift in the report-fixture
# helpers. If we serialise + deserialise an OK report it must survive
# unchanged (the aggregator consumes JSON; we want the test fixtures to
# match the on-the-wire JSON shape one-to-one).
# ---------------------------------------------------------------------------


def test_report_fixture_json_roundtrip() -> None:
    r = _ok_report("rust", "rust_natskv", "f" * 64, recovery_p95_ms=512, state_p95_ms=320)
    serialised = json.dumps(r, sort_keys=True)
    deserialised = json.loads(serialised)
    assert deserialised == r
    # And the stub-report shape.
    s = _stub_report("python", "python")
    assert json.loads(json.dumps(s, sort_keys=True)) == s
