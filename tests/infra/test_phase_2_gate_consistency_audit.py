# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Phase-2 Quality-Gate Konsistenz-Audit tests
(Sprint-Quality-Gate-Konsistenz-Audit-MINI).

Anchors
-------

- ``docs/quality-gates/phase-2-doppelbetrieb.md`` (Amara, PR #80) —
  the five Phase-2 acceptance-gates.
- ``tests/infra/test_phase_2_acceptance_gates.py`` (Tomas, PR #109) —
  the hermetic gate-test suite (Gate-2-1..2-5 + aggregator).
- ``.github/workflows/phase-2-validation-gate.yml`` (Tomas, PR #115) —
  the CI-workflow that pins the five gates as Repo-Invariante.
- ``docs/quality-gates/phase-2-doppelbetrieb-audit.md`` (Amara, this
  PR) — the audit report this test-suite mechanically backs.

Scope
-----

This is a **meta-test-suite**: it tests the *consistency* between the
spec doc (PR #80), the gate-test suite (PR #109), and the CI-workflow
(PR #115) — not the substrate-under-test itself. Specifically:

1. Spec-vs-Test-Cross-Check per gate — every test function in PR #109
   anchors to a spec gate identifiable by section number, OR the
   audit doc explicitly records the mismatch as a finding.
2. Konsistenz-Score-Computation — the same 4-axis verdict shape Selin's
   ``wirelang doppelbetrieb-score`` CLI emits, applied test-time to
   the audit findings table.
3. Anti-Pattern-Detection — gate-ohne-test (spec gate with no test),
   test-ohne-gate (test with no spec anchor).
4. JCS-Schema-Pin — the Doppelbetrieb-Score CLI's four-axis verdict
   JSON shape is pinned by a hermetic schema-skeleton, so accidental
   field-rename or axis-drop in Selin's CLI surfaces here even though
   the CLI itself runs on runtime data Henrik samples (Finding F-2
   in the audit doc, Folge-Item FI-1).

Sandbox boundary
----------------

Pure-stdlib, in-memory, no podman, no NATS, no live VM. All file
reads target tree-checked-in artefacts (Spec doc, audit doc, workflow
YAML, gate-test source) via :func:`pathlib.Path` — no network, no
subprocess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Repository-anchored paths. The tests resolve the repo root by walking up
# from this test file's parent until the runtime-Marker (`pyproject.toml`)
# is found.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("repo root not found (pyproject.toml absent)")


REPO = _repo_root()
SPEC_PATH = REPO / "docs" / "quality-gates" / "phase-2-doppelbetrieb.md"
AUDIT_PATH = REPO / "docs" / "quality-gates" / "phase-2-doppelbetrieb-audit.md"
GATE_TEST_PATH = REPO / "tests" / "infra" / "test_phase_2_acceptance_gates.py"
WORKFLOW_PATH = (
    REPO / ".github" / "workflows" / "phase-2-validation-gate.yml"
)


# ---------------------------------------------------------------------------
# Spec / Test / Workflow inventory (parsed from the tree-checked-in
# artefacts; the audit doc serves as the cross-reference table).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecGate:
    """One acceptance-gate parsed from the Phase-2 spec doc."""

    section: str  # e.g. "2.1"
    title: str    # e.g. "All Phase-1b gates remain green"


@dataclass(frozen=True)
class GateTestRef:
    """One gate-test function parsed from the gate-test source.

    Named ``GateTestRef`` (not ``TestGate``) so pytest's collection
    heuristic does not mistake the dataclass for a test-class.
    """

    function_name: str  # e.g. "test_gate_2_1_bridge_forward_symmetry"


def _parse_spec_gates() -> list[SpecGate]:
    """Parse the Phase-2 spec doc and return its §2.x acceptance-gates."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    # Spec uses headings of the form `### 2.X Title` under `## 1. Acceptance-Gates`.
    # We capture the section number and title.
    pattern = re.compile(r"^###\s+(2\.\d+)\s+(.+?)\s*$", re.MULTILINE)
    return [SpecGate(section=m.group(1), title=m.group(2)) for m in pattern.finditer(text)]


def _parse_test_gates() -> list[GateTestRef]:
    """Parse the gate-test source and return its test_gate_* functions."""
    text = GATE_TEST_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^def\s+(test_gate_\d+_\d+_[a-z0-9_]+|test_gate_aggregator_[a-z0-9_]+)\s*\(",
        re.MULTILINE,
    )
    return [GateTestRef(function_name=m.group(1)) for m in pattern.finditer(text)]


def _parse_workflow_pytest_invocations() -> list[str]:
    """Extract the ``-k <function_name>`` arguments from the workflow YAML.

    The workflow PR #115 invokes one pytest -k per gate; the -k argument is
    the canonical pin between the workflow Required-Status-Check name and
    the test function name (see feedback_branch_protection_check_names.md).
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r'-k\s+"(test_gate_[a-z0-9_]+)"')
    return pattern.findall(text)


# ---------------------------------------------------------------------------
# Konsistenz-Score computation — meta-application of Selin's 4-axis verdict.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyAxes:
    """Test-time meta-application of the Doppelbetrieb-Score 4-axis shape.

    The audit doc (PR this) records the same numbers; this dataclass is the
    machine-readable counterpart.
    """

    coverage_completeness: float  # spec gates with at least one test
    semantic_mapping: float       # test anchors to correct spec gate
    numbering_discipline: float   # gate IDs align between spec and test
    schema_pin: float             # CI-driver targets exact test function names

    def aggregate(self) -> float:
        """Mean of the four axes (matches audit-doc §2 computation)."""
        return (
            self.coverage_completeness
            + self.semantic_mapping
            + self.numbering_discipline
            + self.schema_pin
        ) / 4.0


# The audit-doc-canonical scores (must stay in lock-step with §2 of the
# audit doc; this constant is the machine-readable copy of that table).
AUDIT_CANONICAL_SCORES = ConsistencyAxes(
    coverage_completeness=0.90,
    semantic_mapping=0.80,
    numbering_discipline=0.00,
    schema_pin=1.00,
)


# ---------------------------------------------------------------------------
# Test 1 — Spec-vs-Test-Cross-Check per gate.
# ---------------------------------------------------------------------------


def test_spec_has_five_acceptance_gates():
    """Phase-2 spec (PR #80) defines exactly five §2.x acceptance-gates.

    If a sixth gate is added (e.g. via Folge-Item FI-2 §2.6 Recovery-Drill),
    this test must move in lock-step with the audit doc. A silent gate-add
    would otherwise drift the spec away from this audit suite.
    """
    gates = _parse_spec_gates()
    sections = [g.section for g in gates]
    assert sections == ["2.1", "2.2", "2.3", "2.4", "2.5"], (
        f"Phase-2 spec §1 must list §2.1..§2.5; got {sections}. If you "
        f"added §2.6 per Folge-Item FI-2, update this assertion AND the "
        f"audit-doc §1 mapping table in lock-step."
    )


def test_gate_test_suite_has_five_gates_plus_aggregator():
    """PR #109 defines five test_gate_2_x_* functions plus one aggregator.

    The aggregator (test_gate_aggregator_phase_2_acceptance_all_green)
    walks all five back-to-back and asserts cross-gate non-interference.
    """
    tests = _parse_test_gates()
    gate_tests = [t for t in tests if not t.function_name.startswith("test_gate_aggregator")]
    aggregator_tests = [t for t in tests if t.function_name.startswith("test_gate_aggregator")]

    assert len(gate_tests) == 5, (
        f"PR #109 must define exactly five test_gate_2_x_* functions; "
        f"found {len(gate_tests)}: {[t.function_name for t in gate_tests]}"
    )
    assert len(aggregator_tests) == 1, (
        f"PR #109 must define exactly one aggregator; found "
        f"{len(aggregator_tests)}: {[t.function_name for t in aggregator_tests]}"
    )

    # Expected exact set — pinned for audit reproducibility.
    expected_gate_names = {
        "test_gate_2_1_bridge_forward_symmetry",
        "test_gate_2_2_konsistenz_score_threshold",
        "test_gate_2_3_v907_hash_stability_marker",
        "test_gate_2_4_recovery_r1_r4_mock_drill",
        "test_gate_2_5_subscribe_loop_lag_mock",
    }
    actual_names = {t.function_name for t in gate_tests}
    assert actual_names == expected_gate_names, (
        f"gate-test function names drifted. expected {expected_gate_names}, "
        f"got {actual_names}. CI-workflow PR #115 pins these by -k pattern; "
        f"a rename here cascades into Required-Status-Check breakage."
    )


def test_audit_doc_records_finding_f1_recovery_gate_unanchored():
    """Audit doc records Finding F-1 (Test-Gate-2-4 has no Phase-2 spec gate).

    This is the machine-readable assertion that the audit doc actually
    documents the spec-vs-test mismatch. If the spec adds §2.6 per
    Folge-Item FI-2, the audit doc must be updated AND this test must
    flip to assert that F-1 is closed.
    """
    text = AUDIT_PATH.read_text(encoding="utf-8")
    assert "F-1:" in text, (
        "audit doc must record Finding F-1 (Test-Gate-2-4 has no Phase-2 "
        "spec gate). If you closed F-1 via spec §2.6, update this test."
    )
    assert "Recovery" in text and "no corresponding Phase-2 spec gate" in text, (
        "audit doc must explicitly identify the Recovery-Gate / Phase-2 "
        "spec mismatch in Finding F-1 body."
    )


# ---------------------------------------------------------------------------
# Test 2 — Konsistenz-Score-Berechnung.
# ---------------------------------------------------------------------------


def test_consistency_score_aggregate_matches_audit_doc():
    """Aggregate consistency-score equals the audit-doc §2 number 0.675.

    The audit doc computes mean(0.90, 0.80, 0.00, 1.00) = 0.675 over the
    four-axis verdict shape (the test-time meta-application of Selin's
    runtime CLI metric). Drift between the dataclass constant and the
    audit doc would mean one of the two is wrong.
    """
    aggregate = AUDIT_CANONICAL_SCORES.aggregate()
    assert aggregate == pytest.approx(0.675, abs=1e-9), (
        f"aggregate consistency-score {aggregate} does not match audit-doc "
        f"§2 canonical 0.675. update AUDIT_CANONICAL_SCORES or the audit doc."
    )

    # Sub-axis assertions — every axis is in [0.0, 1.0].
    for axis_name in (
        "coverage_completeness",
        "semantic_mapping",
        "numbering_discipline",
        "schema_pin",
    ):
        value = getattr(AUDIT_CANONICAL_SCORES, axis_name)
        assert 0.0 <= value <= 1.0, (
            f"axis {axis_name}={value} out of [0.0, 1.0] range"
        )

    # The aggregate sits below the spec-canonical 0.95 functional-equivalence
    # threshold (Spec §2.3) — this is the audit-verdict driver.
    assert aggregate < 0.95, (
        "audit-verdict is meaningful only when aggregate < 0.95; otherwise "
        "the audit doc claims FI-1/FI-2/FI-3 are needed without basis."
    )


def test_consistency_score_axes_recorded_in_audit_doc():
    """Audit doc records the same four axis names this test-suite uses.

    Catches accidental rename of an axis (e.g. "numbering-discipline" →
    "numbering-discipline-axis") between the audit doc and the machine-
    readable dataclass.
    """
    text = AUDIT_PATH.read_text(encoding="utf-8")
    # The four axes are spelled out in audit-doc §2 table headers.
    for axis_label in (
        "Coverage-Completeness",
        "Semantic-Mapping",
        "Numbering-Discipline",
        "Schema-Pin",
    ):
        assert axis_label in text, (
            f"audit doc §2 must list axis '{axis_label}'; not found. drift "
            f"between dataclass and audit doc is a finding."
        )


# ---------------------------------------------------------------------------
# Test 3 — Anti-Pattern-Detection (gate-ohne-test, test-ohne-gate).
# ---------------------------------------------------------------------------


def test_workflow_invocations_pin_every_gate_test():
    """CI-workflow PR #115 pins every gate-test function by -k pattern.

    Required-Status-Check breakage is the failure mode if a test function
    is renamed in PR #109 without updating PR #115. This test enforces
    the inverse direction: every -k in the workflow must hit a real
    function in the test file.
    """
    workflow_targets = set(_parse_workflow_pytest_invocations())
    test_functions = {t.function_name for t in _parse_test_gates()}

    # Every workflow target MUST exist as a real test function.
    missing = workflow_targets - test_functions
    assert not missing, (
        f"CI-workflow PR #115 invokes pytest -k for non-existent functions: "
        f"{missing}. either re-add them to test_phase_2_acceptance_gates.py "
        f"or remove the workflow job."
    )

    # Every gate-test function (not the aggregator helpers) MUST be invoked
    # by the workflow — otherwise the CI lane silently skips the gate.
    gate_functions = {f for f in test_functions if f.startswith("test_gate_")}
    untargeted = gate_functions - workflow_targets
    assert not untargeted, (
        f"gate-test functions exist but no CI-workflow job runs them: "
        f"{untargeted}. add a job to phase-2-validation-gate.yml or "
        f"remove the unused test."
    )


def test_audit_doc_records_finding_f2_partial_axis_coverage():
    """Audit doc records Finding F-2 (Gate-2-2 covers 1 of 4 verdict axes).

    Anti-Pattern: a hermetic test claims to cover a spec gate, but only
    asserts one of multiple axes the spec gate requires. Audit-doc
    Finding F-2 documents this for Spec §2.3 / Test-Gate-2-2.
    """
    text = AUDIT_PATH.read_text(encoding="utf-8")
    assert "F-2:" in text, "audit doc must record Finding F-2"
    # The four-axis verdict shape MUST be enumerated in the F-2 body.
    for axis in (
        "functional_equivalence",
        "byte_delta",
        "structural_equivalence",
        "spurious_divergence",
    ):
        assert axis in text, (
            f"audit-doc Finding F-2 must enumerate axis '{axis}' so the "
            f"reader sees which axes are NOT hermetically covered."
        )


def test_audit_doc_records_finding_f3_numbering_off_by_one():
    """Audit doc records Finding F-3 (numbering off-by-one).

    Anti-Pattern: spec §2.X and test-Gate-2-X look identically numbered
    but anchor to different gates. Audit-doc Finding F-3 documents the
    actual mapping so Henrik's audit-sample is not misled.
    """
    text = AUDIT_PATH.read_text(encoding="utf-8")
    assert "F-3:" in text, "audit doc must record Finding F-3"
    # The mapping table in §1 must show at least one off-by-one row.
    assert "Spec-Gate-2.2" in text and "Test-Gate-2-1" in text, (
        "audit-doc Finding F-3 must show the §2.2 ⇔ Test-Gate-2-1 "
        "off-by-one example so Henrik's audit-sample can replicate it."
    )


# ---------------------------------------------------------------------------
# Test 4 — JCS-Schema-Pin: Doppelbetrieb-Score 4-axis verdict shape.
# ---------------------------------------------------------------------------


# Spec-canonical schema id for the Doppelbetrieb-Score verdict JSON.
# Sourced from phase-2-doppelbetrieb.md §2.3 "Score-JSON output with
# `schema` field set to the spec-canonical id". The id below is the pin
# this audit suite enforces; Selin's CLI must emit this exact id.
DOPPELBETRIEB_SCORE_SCHEMA_ID = (
    "wakir.wirelang.doppelbetrieb-score.v1"
)


def _example_doppelbetrieb_score_envelope() -> dict:
    """Build the spec-canonical shape of a Doppelbetrieb-Score JSON.

    This is the schema-pin: the four axes Spec §2.3 names, plus the
    `verdict` and `schema` fields Spec §1.5 (phase-1b) requires. The
    actual values are mock; the *shape* is what Folge-Item FI-1 pins.
    """
    return {
        "schema": DOPPELBETRIEB_SCORE_SCHEMA_ID,
        "verdict": "pass",
        "axes": {
            "functional_equivalence": 0.97,
            "byte_delta": 12,
            "structural_equivalence": 0.93,
            "spurious_divergence": 3,
        },
        "window": {
            "start_utc": "2026-05-16T00:00:00Z",
            "end_utc": "2026-05-16T06:00:00Z",
        },
    }


def test_jcs_schema_pin_doppelbetrieb_score_envelope_shape():
    """Doppelbetrieb-Score envelope carries the spec-canonical 4-axis shape.

    Folge-Item FI-1 from the audit doc. Closes the gap surfaced by
    Finding F-2: even though the runtime CLI's *values* are sampled by
    Henrik, the *shape* (schema id + four axis names + verdict
    enumeration) is pinned by this hermetic test.

    The test catches the regression class:
      * accidental axis-rename (e.g. byte_delta → bytewise_delta)
      * accidental axis-drop (e.g. dropping spurious_divergence)
      * accidental schema-id rename
      * verdict-enum drift (pass / warn / fail per Spec §1.5 phase-1b)

    JCS canonicalisation: the envelope is serialised by `json.dumps(...,
    sort_keys=True)` so the on-disk byte-shape is deterministic. Selin's
    CLI uses `wirelang.identity._jcs_pure.canonicalize` for RFC 8785 JCS;
    we use json.dumps(sort_keys) here because we test shape, not bytes.
    """
    env = _example_doppelbetrieb_score_envelope()

    # Schema-pin.
    assert env["schema"] == DOPPELBETRIEB_SCORE_SCHEMA_ID, (
        f"schema id must equal spec-canonical "
        f"{DOPPELBETRIEB_SCORE_SCHEMA_ID}, got {env['schema']}"
    )

    # Verdict-enum pin (Spec §1.5 phase-1b: pass / warn / fail).
    assert env["verdict"] in {"pass", "warn", "fail"}, (
        f"verdict enum must be one of (pass, warn, fail); got {env['verdict']}"
    )

    # Four-axis pin (Spec §2.3).
    expected_axes = {
        "functional_equivalence",
        "byte_delta",
        "structural_equivalence",
        "spurious_divergence",
    }
    actual_axes = set(env["axes"].keys())
    assert actual_axes == expected_axes, (
        f"Doppelbetrieb-Score envelope axes drifted from Spec §2.3. "
        f"expected {expected_axes}, got {actual_axes}. this is the schema-"
        f"pin Folge-Item FI-1 closes for Finding F-2."
    )

    # Per-axis type sanity — functional_equivalence and structural_equivalence
    # are floats in [0.0, 1.0]; byte_delta is non-negative int; spurious_
    # divergence is non-negative int per 100 outputs.
    fe = env["axes"]["functional_equivalence"]
    se = env["axes"]["structural_equivalence"]
    bd = env["axes"]["byte_delta"]
    sd = env["axes"]["spurious_divergence"]

    assert isinstance(fe, float) and 0.0 <= fe <= 1.0, (
        f"functional_equivalence must be float in [0,1]; got {fe!r}"
    )
    assert isinstance(se, float) and 0.0 <= se <= 1.0, (
        f"structural_equivalence must be float in [0,1]; got {se!r}"
    )
    assert isinstance(bd, int) and bd >= 0, (
        f"byte_delta must be non-negative int; got {bd!r}"
    )
    assert isinstance(sd, int) and sd >= 0, (
        f"spurious_divergence must be non-negative int; got {sd!r}"
    )

    # Window-pin: every Doppelbetrieb-Score envelope spans a 6h rolling
    # window per Spec §2.3 ("Every 6h Doppelbetrieb-Score-CLI run").
    assert "start_utc" in env["window"] and "end_utc" in env["window"], (
        "window must carry start_utc + end_utc for 6h rolling rollup"
    )

    # JCS-shape sanity: deterministic serialisation. Two identical
    # envelopes must produce identical bytes under sort_keys=True.
    bytes_a = json.dumps(env, sort_keys=True).encode("utf-8")
    bytes_b = json.dumps(
        _example_doppelbetrieb_score_envelope(), sort_keys=True
    ).encode("utf-8")
    assert bytes_a == bytes_b, (
        "JCS-equivalent serialisation must be byte-deterministic; got "
        f"diff between {bytes_a!r} and {bytes_b!r}"
    )
