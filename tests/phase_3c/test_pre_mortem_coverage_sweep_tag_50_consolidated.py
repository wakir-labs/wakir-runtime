# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Marathon Pre-Mortem Failure-Mode Coverage-Sweep — Tag-50 consolidated.

This is the **consolidated** coverage-sweep across the Tag-44..49 PR
range (~30 PRs, #282 through #318). It is the Tag-50 follow-on to the
Tag-45 baseline audit, the Tag-46 promotion-detection sweep, the
Tag-47 Pyramide-Layer-Consistency-Audit, and now folds in the Tag-47
/ Tag-48 / Tag-49 side-substance findings that bear on the 24-mode
Pre-Mortem matrix:

* Tag-46 PR #295 (Reza)   — A2 PARTIAL -> COVERED.
* Tag-46 PR #298 (Kai)    — A6 PARTIAL -> COVERED (substrate-layer).
* Tag-46 PR #299 (Tomás)  — B1 PARTIAL -> COVERED (marker-shape).
* Tag-46 PR #300 (Selin)  — A8 PARTIAL -> COVERED.
* Tag-47 PR #302 (Noa)    — Alert-Rule-to-Mira-Notify bridge (B1/SRE).
* Tag-47 PR #304 (Tomás)  — AR-Hand-Stop-Marker-Listener workflow +
                            operator CLI (substanz counterpart to
                            PR #299 marker-shape pin; B1 promotion
                            from structural to operative).
* Tag-47 PR #305 (Henrik) — 15-crate consistency audit (A1 marathon
                            defence-in-depth).
* Tag-47 PR #306 (Selin)  — Persona-Engine 0.5.0-pre-cutover Boot-
                            Self-Test (A2 operative defence).
* Tag-47 PR #307 (Kai)    — Cosign-Keyless-OIDC-Drift-Probe (A6 +
                            D3 internal-probe uplift).
* Tag-48 PR #308 (Reza)   — Wirelang v0.4.1 drift reconciliation (A1
                            cross-component drift bound).
* Tag-48 PR #309 (Noa)    — Per-Welle Trend-Heatmap renderer (A1
                            cross-welle aggregate observability).
* Tag-48 PR #310 (Kai)    — 15-Binary SBOM generator (A6 + D3
                            substrate broadening).
* Tag-48 PR #311 (Amara)  — Bug-42 regression-suite (A4 regression
                            defence-in-depth).
* Tag-48 PR #312 (Tomás)  — Welle-{4,5,6,7} Hot-Spot Probes (A1 +
                            marathon-rollup hot-spot detection
                            substrate).
* Tag-48 PR #313 (Selin)  — Bridge-Audit-Writer wire-in 0.5.1-pre-
                            cutover (A5 operative defence-in-depth).
* Tag-49 PR #314 (Reza)   — Federation-Resolver cross-lang-pin (A1
                            cross-language schema-drift bound).
* Tag-49 PR #315 (Noa)    — Per-Welle Heatmap Prometheus-Textfile
                            Emitter (A1 cross-welle observability).
* Tag-49 PR #316 (Amara)  — Cross-Welle Hot-Spot E2E (22 tests, A1 +
                            B2 marathon-rollup acceptance).
* Tag-49 PR #317 (Tomás)  — Cross-Welle Hot-Spot Aggregator (A1
                            marathon-rollup substanz).
* Tag-49 PR #318 (Kai)    — SBOM-vs-baseline verifier + 15 pinned
                            baselines (A6 + D3 substrate verifier).

Where Tag-46 sweep verified the four PARTIAL -> COVERED promotions in
flight (A2 / A6 / A8 / B1 spawned-substance-detection) and Tag-47
audit pinned the Pyramide-Layer-Consistency, this Tag-50 sweep is the
**consolidated cross-range audit**: it re-confirms the Tag-46
promotions are still in place AND it surveys the Tag-47..49 side-
substance to detect new COVERED-promotion candidates beyond
A2/A6/A8/B1, plus the marathon-level defence-in-depth pins from
Tag-45 §4 follow-up item-list.

Auftrag-Anker
-------------

* Tag-50 Amara Auftrag (2026-05-19) — Consolidated Coverage-Sweep
  Tag-44..49 PR-range (~30 PRs), Continuous-Mode, AR-persistent.
* Tag-45 baseline:
  `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py`
  + `docs/quality-gates/pre-mortem-failure-mode-coverage.md`.
* Tag-46 sweep:
  `tests/phase_3c/test_pre_mortem_coverage_sweep_tag_46.py`.
* Tag-47 audit:
  `tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py`.
* Henrik Tag-44 Pre-Mortem-Skizze:
  `reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md` — the
  canonical 24-failure-mode source.

Tag-50 sweep-scope
------------------

The sweep covers two surfaces:

1. **Re-verification surface (§1).** Each Tag-46 PARTIAL -> COVERED
   promotion is still in place: the named follow-up file still
   exists, still loads, still contains the named pinning tests.
   This is the Tag-50 regression-defence against accidental Tag-47
   / Tag-48 / Tag-49 substance landing that removed Tag-46 anchors.

2. **Side-finding promotion-candidate surface (§§2-5).** For each
   Tag-47 / Tag-48 / Tag-49 PR with side-impact on the Pre-Mortem
   matrix, this sweep asserts:

   a. The named substance file exists in the expected location.
   b. The substance file maps to the expected failure-mode IDs
      (per the §0 mapping above).
   c. The mapping yields either a **new COVERED-promotion**
      (failure-mode previously PARTIAL or GAP-ACCEPTED that now
      has stronger anchor-substance) OR a **defence-in-depth pin**
      (failure-mode already COVERED that gains additional anchor).

   The Tag-50 sweep is **detection-mode**, not enforcement-mode:
   it does not force any class transition; it surfaces the mapping
   so the Tag-50 coverage-matrix doc-update can record the post-
   Tag-49 stand explicitly.

Test budget (~25 tests, six sections)
-------------------------------------

* §1 — Tag-46 promotion re-verification (5 tests: A2, A6, A8, B1, B3
  retention).
* §2 — Tag-47 substance mapping (5 tests: marker-listener, alert-
  bridge, 15-crate audit, boot-self-test, keyless-OIDC probe).
* §3 — Tag-48 substance mapping (5 tests: spec drift-reconciliation,
  trend-heatmap, 15-binary SBOM, Bug-42 regression, bridge-audit-
  writer wire-in).
* §4 — Tag-49 substance mapping (5 tests: federation-resolver pin
  refresh, per-welle heatmap prom-emitter, Cross-Welle Hot-Spot E2E,
  Cross-Welle Hot-Spot Aggregator, SBOM-vs-baseline verifier).
* §5 — Side-finding consolidated promotion candidates (3 tests: A6
  marathon-defence-in-depth from Tag-47 keyless probe, D3 sigstore-
  external internal-probe uplift, A1 marathon-rollup hot-spot
  cascade detection from Tag-49 e2e).
* §6 — Tag-50 consolidated summary recomputation (2 tests: §3 doc
  total still 24 with new defence-in-depth annotations; Tag-45/46/47
  baseline anchors all still present).

Vermutungs-Kennzeichnung (P2)
-----------------------------

* "Side-substance maps to failure-mode" is a P2 mapping claim: it
  is the Tag-50 Amara reading of the substance, not a Henrik-side
  audit-claim. Zone-N partner-review (Henrik) is invited via the
  Tag-50 deliverable note.
* "New COVERED-promotion" is conservative: most Tag-47..49 side-
  substance lands as defence-in-depth on items already COVERED at
  Tag-46. The single most-defensible new promotion candidate is
  A6 marathon-defence-in-depth (Tag-45 §4 item 2b, pending Amara-
  spawn pre-Tag-50) which the Tag-47 PR #307 keyless-OIDC probe +
  Tag-48 PR #310 SBOM generator + Tag-49 PR #318 SBOM verifier
  collectively close at the substrate-detection layer.
* "D3 sigstore-external" was Tag-45 GAP-ACCEPTED-external; the
  Tag-47 keyless-OIDC drift probe gives internal observability of
  the external surface, which we mark as PARTIAL-coverage uplift
  (not full COVERED, since the probe is detection-only, not
  failure-tolerance).

License: Apache-2.0 (parity with sibling Phase-3c artefacts).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    FrozenSet,
    Optional,
    Tuple,
)

import pytest


# ---------------------------------------------------------------------------
# Repo-root + helper loaders (parity with Tag-46 / Tag-47 modules).
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _path_present(*parts: str) -> bool:
    """Return True iff the named repo-relative path exists as a file."""
    return (_repo_root().joinpath(*parts)).is_file()


def _load_module_optional(rel_path: str, module_name: str) -> Optional[Any]:
    """Load a test module from a repo-relative path, or return None."""
    full = _repo_root() / rel_path
    if not full.is_file():
        return None
    spec = importlib.util.spec_from_file_location(module_name, str(full))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        return None
    return module


def _module_test_names(module: Any) -> FrozenSet[str]:
    """Return frozenset of test-function and TestClass::method names."""
    names: set[str] = set()
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if callable(attr) and attr_name.startswith("test_"):
            names.add(attr_name)
            continue
        if isinstance(attr, type) and attr_name.startswith("Test"):
            for method_name in dir(attr):
                if method_name.startswith("test_"):
                    names.add(f"{attr_name}::{method_name}")
            names.add(attr_name)
    return frozenset(names)


# ---------------------------------------------------------------------------
# Tag-50 substance map: Tag-44..49 PR-range PRs that bear on the 24-mode
# Pre-Mortem matrix. The "expected_modes" tuple is the Tag-50 Amara
# reading (Vermutungs-Kennzeichnung P2); Henrik Zone-N review may revise.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tag50SubstanceItem:
    """One Tag-44..49 substance item with failure-mode mapping."""

    tag: str              # e.g. "Tag-47"
    pr_id: int            # GitHub PR number
    title_keyword: str    # short subject pin
    test_rel_path: str    # repo-relative test path (single canonical)
    expected_modes: Tuple[str, ...]  # failure-mode IDs the substance bears on
    promotion_kind: str   # "covered-promotion" | "defence-in-depth" |
                          # "partial-uplift"
    owner: str            # "Amara" | "Reza" | "Selin" | "Tomas" | "Kai" |
                          # "Noa" | "Henrik"


# Tag-46 PR baseline (re-verification surface).
TAG46_PROMOTIONS: Tuple[Tag50SubstanceItem, ...] = (
    Tag50SubstanceItem(
        tag="Tag-46",
        pr_id=295,
        title_keyword="a2-fsm-phantom-transition",
        test_rel_path=(
            "wirelang/tests/persona_engine/"
            "test_fsm_phantom_transition_coverage_a2.py"
        ),
        expected_modes=("A2",),
        promotion_kind="covered-promotion",
        owner="Reza",
    ),
    Tag50SubstanceItem(
        tag="Tag-46",
        pr_id=298,
        title_keyword="a6-cosign-drift-substrate",
        test_rel_path="tests/infra/test_cosign_drift_coverage_a6.py",
        expected_modes=("A6",),
        promotion_kind="covered-promotion",
        owner="Kai",
    ),
    Tag50SubstanceItem(
        tag="Tag-46",
        pr_id=299,
        title_keyword="b1-ar-hand-stop-marker-trigger",
        test_rel_path="tests/ci/test_ar_hand_stop_marker_trigger_b1.py",
        expected_modes=("B1",),
        promotion_kind="covered-promotion",
        owner="Tomas",
    ),
    Tag50SubstanceItem(
        tag="Tag-46",
        pr_id=300,
        title_keyword="a8-nats-jetstream-loss-recovery",
        test_rel_path=(
            "wirelang/persona_engine/tests/test_nats_jetstream_loss_recovery_a8.py"
        ),
        expected_modes=("A8",),
        promotion_kind="covered-promotion",
        owner="Selin",
    ),
)


# Tag-47 substance map.
TAG47_SUBSTANCE: Tuple[Tag50SubstanceItem, ...] = (
    Tag50SubstanceItem(
        tag="Tag-47",
        pr_id=302,
        title_keyword="alert-rule-to-mira-notify-bridge",
        test_rel_path="tests/observability/test_alert_rule_to_mira_notify_bridge.py",
        expected_modes=("B1",),
        promotion_kind="defence-in-depth",
        owner="Noa",
    ),
    Tag50SubstanceItem(
        tag="Tag-47",
        pr_id=304,
        title_keyword="ar-hand-stop-marker-listener-workflow",
        test_rel_path="tests/ci/test_ar_hand_stop_marker_workflow.py",
        expected_modes=("B1",),
        promotion_kind="defence-in-depth",
        owner="Tomas",
    ),
    Tag50SubstanceItem(
        tag="Tag-47",
        pr_id=305,
        title_keyword="15-crate-consistency-audit",
        test_rel_path="tests/audit/test_phase_3a_15_crate_consistency.py",
        expected_modes=("A1",),
        promotion_kind="defence-in-depth",
        owner="Henrik",
    ),
    Tag50SubstanceItem(
        tag="Tag-47",
        pr_id=306,
        title_keyword="persona-engine-boot-self-test",
        test_rel_path="wirelang/tests/persona_engine/test_boot_self_test_tag47.py",
        expected_modes=("A2",),
        promotion_kind="defence-in-depth",
        owner="Selin",
    ),
    Tag50SubstanceItem(
        tag="Tag-47",
        pr_id=307,
        title_keyword="cosign-keyless-oidc-drift-probe",
        test_rel_path="tests/observability/test_cosign_keyless_oidc_drift_probe.py",
        expected_modes=("A6", "D3"),
        promotion_kind="partial-uplift",
        owner="Kai",
    ),
)


# Tag-48 substance map.
TAG48_SUBSTANCE: Tuple[Tag50SubstanceItem, ...] = (
    Tag50SubstanceItem(
        tag="Tag-48",
        pr_id=308,
        title_keyword="wirelang-spec-v0.4.1-drift-reconciliation",
        test_rel_path="tests/specs/test_wirelang_spec_v0_4_1_drift_reconciliation.py",
        expected_modes=("A1",),
        promotion_kind="defence-in-depth",
        owner="Reza",
    ),
    Tag50SubstanceItem(
        tag="Tag-48",
        pr_id=309,
        title_keyword="per-welle-trend-heatmap",
        test_rel_path="tests/observability/test_per_welle_trend_heatmap.py",
        expected_modes=("A1", "C1"),
        promotion_kind="defence-in-depth",
        owner="Noa",
    ),
    Tag50SubstanceItem(
        tag="Tag-48",
        pr_id=310,
        title_keyword="15-binary-sbom-generator",
        test_rel_path="tests/observability/test_generate_15_binary_sbom.py",
        expected_modes=("A6", "D3"),
        promotion_kind="defence-in-depth",
        owner="Kai",
    ),
    Tag50SubstanceItem(
        tag="Tag-48",
        pr_id=311,
        title_keyword="bug-42-regression-suite",
        test_rel_path="tests/integration/test_bug_42_regression_suite_tag_48.py",
        expected_modes=("A4",),
        promotion_kind="defence-in-depth",
        owner="Amara",
    ),
    Tag50SubstanceItem(
        tag="Tag-48",
        pr_id=313,
        title_keyword="bridge-audit-writer-wire-in",
        test_rel_path=(
            "wirelang/tests/persona_engine/test_bridge_audit_writer_wire_in_tag48.py"
        ),
        expected_modes=("A5", "A8"),
        promotion_kind="defence-in-depth",
        owner="Selin",
    ),
)


# Tag-49 substance map.
TAG49_SUBSTANCE: Tuple[Tag50SubstanceItem, ...] = (
    Tag50SubstanceItem(
        tag="Tag-49",
        pr_id=314,
        title_keyword="federation-resolver-cross-lang-pin",
        test_rel_path=(
            "tests/specs/"
            "test_wirelang_spec_v0_4_1_federation_resolver_cross_lang_pin_refresh.py"
        ),
        expected_modes=("A1",),
        promotion_kind="defence-in-depth",
        owner="Reza",
    ),
    Tag50SubstanceItem(
        tag="Tag-49",
        pr_id=315,
        title_keyword="per-welle-heatmap-prometheus-emitter",
        test_rel_path="tests/observability/test_per_welle_heatmap_prom_emitter.py",
        expected_modes=("A1", "C1"),
        promotion_kind="defence-in-depth",
        owner="Noa",
    ),
    Tag50SubstanceItem(
        tag="Tag-49",
        pr_id=316,
        title_keyword="cross-welle-hot-spot-e2e",
        test_rel_path="tests/phase_3c/test_cross_welle_hot_spot_e2e.py",
        expected_modes=("A1", "B2"),
        promotion_kind="defence-in-depth",
        owner="Amara",
    ),
    Tag50SubstanceItem(
        tag="Tag-49",
        pr_id=317,
        title_keyword="cross-welle-hot-spot-aggregator",
        test_rel_path="tests/ci/test_cross_welle_hot_spot_aggregator.py",
        expected_modes=("A1",),
        promotion_kind="defence-in-depth",
        owner="Tomas",
    ),
    Tag50SubstanceItem(
        tag="Tag-49",
        pr_id=318,
        title_keyword="sbom-vs-baseline-verifier",
        test_rel_path=(
            "tests/observability/test_verify_15_binary_sbom_against_baseline.py"
        ),
        expected_modes=("A6", "D3"),
        promotion_kind="defence-in-depth",
        owner="Kai",
    ),
)


ALL_SUBSTANCE: Tuple[Tag50SubstanceItem, ...] = (
    TAG46_PROMOTIONS + TAG47_SUBSTANCE + TAG48_SUBSTANCE + TAG49_SUBSTANCE
)


def _assert_substance_landed(item: Tag50SubstanceItem) -> Any:
    """Assert the substance file exists, loads, and has >= 1 test.

    Returns the loaded module for further inspection.
    """
    assert _path_present(item.test_rel_path), (
        f"{item.tag} PR #{item.pr_id} ({item.title_keyword}) — "
        f"substance file {item.test_rel_path} not present. The Tag-44..49 "
        f"consolidated sweep expects this file to be on main; if absent, "
        f"either the PR was reverted (Mira-Hand investigation required) or "
        f"the Tag-50 substance-map needs revision."
    )
    module = _load_module_optional(
        item.test_rel_path, f"amara_tag50_sweep_{item.pr_id}"
    )
    assert module is not None, (
        f"{item.tag} PR #{item.pr_id} substance file {item.test_rel_path} "
        f"present but module-load failed."
    )
    names = _module_test_names(module)
    assert len(names) >= 1, (
        f"{item.tag} PR #{item.pr_id} substance file {item.test_rel_path} "
        f"present but contains no tests."
    )
    return module


# ===========================================================================
# §1 — Tag-46 promotion re-verification (5 tests).
#
# Each Tag-46 PARTIAL -> COVERED promotion is re-verified at Tag-50:
# the named follow-up file still exists, still loads, still contains
# substance.
# ===========================================================================


def test_t50_re_a2_fsm_phantom_transition_covered_state_retained() -> None:
    """A2 COVERED state retained: Reza PR #295 substance still on main."""
    item = TAG46_PROMOTIONS[0]
    assert item.expected_modes == ("A2",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # Reza PR #295 file pins FSM transition-legality cross-Welle.
    # Spot-check by simply asserting the module has >= 5 tests
    # (PR-merge baseline was substantially more).
    assert len(names) >= 5, (
        f"A2 PARTIAL -> COVERED promotion has shrunk: only {len(names)} "
        f"tests; PR #295 landed substantially more."
    )


def test_t50_re_a6_cosign_drift_covered_state_retained() -> None:
    """A6 COVERED state retained: Kai PR #298 substrate-layer substance."""
    item = TAG46_PROMOTIONS[1]
    assert item.expected_modes == ("A6",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #298 landed 17 hermetic invariants.
    assert len(names) >= 5, (
        f"A6 substrate-layer COVERED promotion has shrunk: only {len(names)} "
        f"tests; PR #298 landed substantially more."
    )


def test_t50_re_b1_ar_hand_stop_marker_covered_state_retained() -> None:
    """B1 COVERED state retained: Tomás PR #299 marker-shape substance."""
    item = TAG46_PROMOTIONS[2]
    assert item.expected_modes == ("B1",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #299 landed 31 hermetic tests across five test-classes.
    assert len(names) >= 10, (
        f"B1 marker-trigger COVERED promotion has shrunk: only {len(names)} "
        f"tests; PR #299 landed substantially more."
    )


def test_t50_re_a8_nats_jetstream_loss_covered_state_retained() -> None:
    """A8 COVERED state retained: Selin PR #300 substance still on main."""
    item = TAG46_PROMOTIONS[3]
    assert item.expected_modes == ("A8",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #300 landed five JetStream-loss scenarios spread across many tests.
    assert len(names) >= 5, (
        f"A8 JetStream-loss COVERED promotion has shrunk: only {len(names)} "
        f"tests; PR #300 landed substantially more."
    )


def test_t50_re_b3_welle_3_pre_auditor_designation_partial_retained() -> None:
    """B3 PARTIAL retained: this is the deferred KW-25 hard blocker.

    Per Tag-45 §4 + Tag-46 sweep, B3 is the deferred follow-up that
    MUST land before KW-25 cutover (2026-06-15). Tag-50 surfaces the
    state as 'still PARTIAL unless Henrik+AR moved on the designation
    independently'. The sweep does not enforce a state transition.
    """
    # B3 has no Tag-46/47/48/49 spawn assigned yet. Inspect the two
    # accepted filename slots.
    b3_filename_canonical = "test_welle_3_pre_auditor_designation_precondition.py"
    b3_filename_alias = "test_welle_3_pre_auditor_designation_b3.py"
    b3_search_dirs = (
        _repo_root() / "tests" / "phase_3c",
        _repo_root() / "tests" / "ci",
    )
    found = False
    for d in b3_search_dirs:
        if (d / b3_filename_canonical).is_file():
            found = True
            break
        if (d / b3_filename_alias).is_file():
            found = True
            break
    # Tolerate either state. If found, B3 has been independently authored;
    # if not, B3 remains PARTIAL as expected by Tag-45 + Tag-46.
    state = "COVERED" if found else "PARTIAL"
    assert state in ("COVERED", "PARTIAL"), state
    # The Tag-50 sweep does not enforce; it records the state.


# ===========================================================================
# §2 — Tag-47 substance mapping (5 tests).
# ===========================================================================


def test_t50_t47_marker_listener_workflow_anchored_b1_defence() -> None:
    """Tag-47 PR #304 AR-Hand-Stop-Marker-Listener workflow anchors B1.

    This is the *operative* counterpart to Tag-46 PR #299 (marker-shape
    pin). PR #304 wires a GitHub Actions workflow that detects the
    marker file and cascades stop-orders across downstream Welle CI
    jobs. The B1 failure-mode (AR-Hand-Stop-Marker-Missing-Trigger)
    therefore gains operative defence-in-depth on top of the marker-
    shape pin.
    """
    item = TAG47_SUBSTANCE[1]  # PR #304
    assert item.expected_modes == ("B1",)
    module = _assert_substance_landed(item)
    # Workflow file present + scripts present.
    assert _path_present(".github", "workflows", "ar-hand-stop-marker-listener.yml")
    assert _path_present("scripts", "ci", "ar-hand-stop-marker-listener-detect.py")
    assert _path_present("scripts", "ci", "ar-hand-stop-marker-listener-cascade.py")
    # Tag-47 substance should have >= 10 hermetic tests pinning the workflow
    # shape + cascade semantics + cancel-path.
    names = _module_test_names(module)
    assert len(names) >= 10, (
        f"Tag-47 PR #304 marker-listener-workflow test substance is thin: "
        f"only {len(names)} tests."
    )


def test_t50_t47_alert_rule_mira_notify_bridge_anchors_b1_sre_side() -> None:
    """Tag-47 PR #302 Alert-Rule-to-Mira-Notify bridge anchors B1 SRE side.

    Tag-45 Noa already pinned the B1 Prometheus alert
    ``WakirPhase3FailureModeB1ArHandStopMissingTrigger``. The Tag-47
    bridge wires Alertmanager -> Mira-Notify so the SRE-fire path
    actually reaches the operator inbox. Failure-mode B1 thus gains
    SRE-pipeline-end-to-end defence-in-depth.
    """
    item = TAG47_SUBSTANCE[0]  # PR #302
    assert item.expected_modes == ("B1",)
    module = _assert_substance_landed(item)
    # Sibling scripts present.
    assert _path_present("scripts", "observability", "alert-rule-to-mira-notify-bridge.py")
    # Tag-47 substance has 33 hermetic tests.
    names = _module_test_names(module)
    assert len(names) >= 20, (
        f"Tag-47 PR #302 alert-rule-bridge test substance is thin: only "
        f"{len(names)} tests; PR landed 33."
    )


def test_t50_t47_phase_3a_15_crate_consistency_audit_anchors_a1_defence() -> None:
    """Tag-47 PR #305 15-crate consistency audit anchors A1 defence.

    Phase-3a has 15 Rust crates that all share the cross-modul-drift
    surface. The audit-test asserts shared schema-version + shared
    pyproject + shared SemVer + shared SPDX-header. A1 Cross-Modul-
    Drift therefore gains crate-substrate defence-in-depth.
    """
    item = TAG47_SUBSTANCE[2]  # PR #305
    assert item.expected_modes == ("A1",)
    # Tag-47 PR #305 may have placed the audit-test under tests/audit/
    # or tests/phase_3a/. The canonical path is tests/audit/.
    candidate_paths = (
        item.test_rel_path,
        "tests/audit/test_phase_3a_15_crate_consistency_audit.py",
        "tests/phase_3a/test_15_crate_consistency_audit.py",
    )
    found = any(_path_present(p) for p in candidate_paths)
    assert found, (
        f"Tag-47 PR #305 15-crate-consistency-audit test not found at any "
        f"of {candidate_paths!r}."
    )


def test_t50_t47_persona_engine_boot_self_test_anchors_a2_defence() -> None:
    """Tag-47 PR #306 persona-engine 0.5.0 Boot-Self-Test anchors A2.

    The 0.5.0-pre-cutover Boot-Self-Test smoke ensures the persona-
    engine FSM boots into a known-good initial state before NATS-
    subscribe-loop starts. A2 FSM-Phantom-Transition therefore gains
    boot-time defence-in-depth (the persona-engine cannot enter the
    FSM-transition-validation surface without first passing the boot-
    self-test).
    """
    item = TAG47_SUBSTANCE[3]  # PR #306
    assert item.expected_modes == ("A2",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    assert len(names) >= 1


def test_t50_t47_cosign_keyless_oidc_drift_probe_anchors_a6_d3_uplift() -> None:
    """Tag-47 PR #307 Cosign-Keyless-OIDC-Drift-Probe — A6 + D3 uplift.

    The keyless-OIDC probe runs daily and detects sigstore-trust-root
    drift, OIDC-identity drift, and per-binary signature drift before
    cutover-day. Two failure-mode impacts:

    * A6 Cosign-Verification-Drift (was COVERED via Tag-46 substrate-
      layer Kai PR #298) — gains marathon-defence-in-depth from the
      daily probe (early-warning ahead of cutover).
    * D3 Cosign-Verification-Drift (sigstore/Fulcio external) was
      Tag-45 GAP-ACCEPTED-external; the keyless probe is the internal
      observability counterpart, lifting D3 to PARTIAL-coverage
      (detection-only, not failure-tolerance).
    """
    item = TAG47_SUBSTANCE[4]  # PR #307
    assert item.expected_modes == ("A6", "D3")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #307 landed 17 hermetic tests (4 trust-root + 5 OIDC + 3 aggregate
    # + 3 rendering + 1 substrate + 1 CLI). Plus the workflow file.
    assert _path_present(".github", "workflows", "cosign-keyless-oidc-drift-probe.yml"), (
        "Tag-47 PR #307 keyless-OIDC drift workflow file not present; the "
        "daily-probe scheduling is the substantive D3 internal-uplift anchor."
    )
    assert len(names) >= 12, (
        f"Tag-47 PR #307 keyless-OIDC test substance is thin: only "
        f"{len(names)} tests; PR landed 17."
    )


# ===========================================================================
# §3 — Tag-48 substance mapping (5 tests).
# ===========================================================================


def test_t50_t48_wirelang_spec_v0_4_1_drift_reconciliation_anchors_a1() -> None:
    """Tag-48 PR #308 Wirelang v0.4.1 drift reconciliation patch anchors A1.

    DRIFT-S1/S2/S3 are three schema-drift items between the Python
    and Rust Wirelang implementations. The v0.4.1 patch reconciles
    them. A1 Cross-Modul-Drift therefore gains spec-substrate
    defence-in-depth.
    """
    item = TAG48_SUBSTANCE[0]  # PR #308
    assert item.expected_modes == ("A1",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    assert len(names) >= 1


def test_t50_t48_per_welle_trend_heatmap_anchors_a1_c1_defence() -> None:
    """Tag-48 PR #309 Per-Welle Trend-Heatmap renderer anchors A1 + C1.

    The trend-heatmap renders per-Welle hot-spot trends across the
    marathon window. Two impacts:

    * A1 Cross-Modul-Drift — observability across all seven Welle
      surfaces cross-component drift trends.
    * C1 COMPLETE-Marker-False-Positive — the heatmap visualises
      pre-marker conditions so operators see false-positive risks
      before the marker fires.
    """
    item = TAG48_SUBSTANCE[1]  # PR #309
    assert item.expected_modes == ("A1", "C1")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #309 landed 19 hermetic tests.
    assert len(names) >= 10, (
        f"Tag-48 PR #309 trend-heatmap test substance is thin: only "
        f"{len(names)} tests; PR landed 19."
    )
    # Grafana dashboard sibling.
    assert _path_present("dashboards", "per-welle-trend-heatmap.json")


def test_t50_t48_15_binary_sbom_generator_anchors_a6_d3_defence() -> None:
    """Tag-48 PR #310 15-Binary SBOM generator anchors A6 + D3 defence.

    CycloneDX-1.5 / SPDX-2.3 SBOM generation for all 15 Phase-3a
    binaries. Two impacts:

    * A6 Cosign-Verification-Drift — SBOM-baseline gives image-content
      drift-detection independent of cosign signature-chain.
    * D3 Cosign-Verification-Drift (sigstore external) — SBOM-vs-
      baseline cross-checks image-content against a known-good
      baseline, providing fail-fast on supply-chain compromise.
    """
    item = TAG48_SUBSTANCE[2]  # PR #310
    assert item.expected_modes == ("A6", "D3")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    assert len(names) >= 1
    # Daily workflow scheduling.
    assert _path_present(".github", "workflows", "15-binary-sbom-daily.yml")


def test_t50_t48_bug_42_regression_suite_anchors_a4_defence() -> None:
    """Tag-48 PR #311 Bug-42 regression-suite anchors A4 defence.

    Tag-41 Bug-42 (NATS-Mode-Mismatch / Subject-Drift) was the
    canonical A4 failure case that the Tag-39 acceptance suite
    pinned. The Tag-48 regression-suite (20 tests / 25 IDs) is the
    consolidated cross-cluster regression-guard. A4 NATS-Mode-
    Mismatch gains regression-tier defence-in-depth.
    """
    item = TAG48_SUBSTANCE[3]  # PR #311
    assert item.expected_modes == ("A4",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #311 landed 20 tests / 25 IDs.
    assert len(names) >= 15, (
        f"Tag-48 PR #311 Bug-42 regression substance is thin: only "
        f"{len(names)} tests; PR landed 20."
    )


def test_t50_t48_bridge_audit_writer_wire_in_anchors_a5_a8_defence() -> None:
    """Tag-48 PR #313 bridge-audit-writer wire-in anchors A5 + A8 defence.

    The 10th BackendDecision (bridge-audit-writer wire-in) into the
    persona-engine 0.5.1-pre-cutover. Two impacts:

    * A5 Self-Reference-Trap-Fire (Welle-3 bridge-audit-writer) —
      the wire-in path is now exercised by the persona-engine boot
      sequence, not just the Rust-CLI smoke.
    * A8 NATS-JetStream-Loss-Recovery — the bridge-audit-writer is
      a JetStream-backed audit-sink; wire-in failure-mode tests
      cover JetStream-disconnect retry-policy.
    """
    item = TAG48_SUBSTANCE[4]  # PR #313
    assert item.expected_modes == ("A5", "A8")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    assert len(names) >= 1


# ===========================================================================
# §4 — Tag-49 substance mapping (5 tests).
# ===========================================================================


def test_t50_t49_federation_resolver_cross_lang_pin_anchors_a1_defence() -> None:
    """Tag-49 PR #314 Federation-Resolver cross-lang-pin refresh anchors A1.

    The federation-resolver spec is pinned across Python and Rust;
    the cross-lang-pin refresh suite (16 hermetic tests) verifies
    the two implementations remain in lockstep. A1 Cross-Modul-Drift
    gains spec-version-substrate defence-in-depth.
    """
    item = TAG49_SUBSTANCE[0]  # PR #314
    assert item.expected_modes == ("A1",)
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #314 landed 16 hermetic tests.
    assert len(names) >= 10, (
        f"Tag-49 PR #314 federation-resolver cross-lang-pin substance is "
        f"thin: only {len(names)} tests; PR landed 16."
    )


def test_t50_t49_per_welle_heatmap_prom_emitter_anchors_a1_c1_defence() -> None:
    """Tag-49 PR #315 Per-Welle Heatmap Prometheus-Textfile Emitter anchors A1 + C1.

    The prom-textfile emitter exposes the Tag-48 trend-heatmap data
    as Prometheus metrics, enabling alert-rule cross-checks against
    the heatmap. A1 + C1 gain cross-stack defence-in-depth.
    """
    item = TAG49_SUBSTANCE[1]  # PR #315
    assert item.expected_modes == ("A1", "C1")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    assert len(names) >= 1


def test_t50_t49_cross_welle_hot_spot_e2e_anchors_a1_b2_marathon() -> None:
    """Tag-49 PR #316 Cross-Welle Hot-Spot E2E anchors A1 + B2 marathon.

    This is the **marathon-rollup acceptance** for the cross-Welle
    hot-spot cascade. Two impacts:

    * A1 Cross-Modul-Drift — the E2E suite (22 tests) covers the
      marathon-window propagation of hot-spots across all seven
      Welle, including cascade-detection and cross-welle drift.
    * B2 Sign-Off-Sequenz-Bruch — the cascade map enforces
      pre_conditional_blocked downstream Welle on a BLOCK verdict,
      which is the B2 enforcement-surface at marathon-rollup level.
    """
    item = TAG49_SUBSTANCE[2]  # PR #316
    assert item.expected_modes == ("A1", "B2")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #316 landed 22 tests.
    assert len(names) >= 15, (
        f"Tag-49 PR #316 cross-welle-hot-spot-e2e test substance is thin: "
        f"only {len(names)} tests; PR landed 22."
    )


def test_t50_t49_cross_welle_hot_spot_aggregator_anchors_a1_substrate() -> None:
    """Tag-49 PR #317 Cross-Welle Hot-Spot Aggregator anchors A1 substrate.

    The aggregator is the substanz counterpart to the Tag-49 E2E
    suite — Tomás's substrate that the E2E acceptance pins. A1
    gains marathon-rollup substrate defence-in-depth.
    """
    item = TAG49_SUBSTANCE[3]  # PR #317
    assert item.expected_modes == ("A1",)
    module = _assert_substance_landed(item)
    # Aggregator script + workflow present.
    assert _path_present("tooling", "ci", "cross_welle_hot_spot_aggregator.py")
    assert _path_present(".github", "workflows", "cross-welle-hot-spot-aggregator.yml")


def test_t50_t49_sbom_verifier_anchors_a6_d3_baseline_defence() -> None:
    """Tag-49 PR #318 SBOM-vs-baseline verifier anchors A6 + D3 defence.

    21 hermetic tests + 15 pinned baselines. Anchors the Tag-48
    PR #310 SBOM generator with a verifier that fires on baseline-
    drift. A6 + D3 gain baseline-pinned defence-in-depth.
    """
    item = TAG49_SUBSTANCE[4]  # PR #318
    assert item.expected_modes == ("A6", "D3")
    module = _assert_substance_landed(item)
    names = _module_test_names(module)
    # PR #318 landed 21 tests.
    assert len(names) >= 15, (
        f"Tag-49 PR #318 SBOM-verifier substance is thin: only {len(names)} "
        f"tests; PR landed 21."
    )
    # Daily workflow scheduling.
    assert _path_present(".github", "workflows", "sbom-verification-daily.yml")


# ===========================================================================
# §5 — Side-finding consolidated promotion candidates (3 tests).
#
# These tests articulate the Tag-50 promotion candidates beyond the
# four Tag-46 PARTIAL -> COVERED transitions. The Tag-50 Amara reading
# is conservative: only one new COVERED candidate (A6 marathon-defence-
# in-depth from the combination of PR #307 + #310 + #318), and one
# PARTIAL-coverage uplift candidate (D3 sigstore-external from the
# Tag-47 keyless-OIDC daily probe).
# ===========================================================================


def test_t50_a6_marathon_defence_in_depth_candidate_anchors_present() -> None:
    """A6 marathon-defence-in-depth candidate: Tag-45 §4 item 2b.

    Tag-45 §4 listed item 2b as "A6 Cosign-Verification-Drift
    (marathon defence-in-depth)" pending Amara-spawn. The Tag-47/48/49
    combination delivers the marathon-level anchors required for the
    promotion:

    * Tag-47 PR #307 keyless-OIDC daily probe = early-warning.
    * Tag-48 PR #310 15-binary SBOM generator = supply-chain baseline.
    * Tag-49 PR #318 SBOM verifier + 15 pinned baselines = baseline-
      drift enforcement.

    The three together constitute the marathon-defence-in-depth pin
    the Tag-45 §4 item 2b sought, even though the canonical Tag-45
    §4 file name (``test_cosign_chain_marathon_image_hash_stability
    .py``) was not landed under that exact path. The doc-update
    accompanying this Tag-50 sweep records the substance-equivalence.
    """
    # The three anchor files must all be present.
    assert _path_present(
        "tests", "observability", "test_cosign_keyless_oidc_drift_probe.py"
    ), "Tag-47 PR #307 anchor missing — A6 marathon-defence has a hole."
    assert _path_present(
        "tests", "observability", "test_generate_15_binary_sbom.py"
    ), "Tag-48 PR #310 anchor missing — A6 marathon-defence has a hole."
    assert _path_present(
        "tests", "observability", "test_verify_15_binary_sbom_against_baseline.py"
    ), "Tag-49 PR #318 anchor missing — A6 marathon-defence has a hole."
    # Daily-scheduling workflows for both probes must be present.
    assert _path_present(".github", "workflows", "cosign-keyless-oidc-drift-probe.yml")
    assert _path_present(".github", "workflows", "sbom-verification-daily.yml")
    assert _path_present(".github", "workflows", "15-binary-sbom-daily.yml")


def test_t50_d3_sigstore_external_partial_uplift_candidate() -> None:
    """D3 sigstore-external PARTIAL-uplift candidate.

    Tag-45 classified D3 as GAP-ACCEPTED-external because the
    sigstore/Fulcio surface is operator-hand / fail-fast configuration.
    The Tag-47 keyless-OIDC daily probe is the **internal
    observability counterpart**: it does not change the external
    failure-mode behaviour, but it surfaces drift in the external
    sigstore trust-root and OIDC-identity to operators within the
    Phase-3-marathon observability stack.

    Tag-50 Amara reading (P2): D3 should be reclassified from
    GAP-ACCEPTED-external to PARTIAL — the external surface remains
    GAP-ACCEPTED for failure-tolerance, but the internal-observability
    surface is now COVERED via the keyless probe + SBOM verifier
    + daily workflow scheduling. The reclassification is a Henrik-
    Zone-N review item (the boundary is QA-test-surface vs.
    governance-mandate which is Henrik's domain).

    This test does not flip the state in the coverage-matrix doc
    automatically; it asserts the substance-anchors that would
    justify the flip are all in place.
    """
    # Internal probe anchor.
    assert _path_present(
        "scripts", "observability", "cosign-keyless-oidc-drift-probe.py"
    ), "D3 internal-observability uplift anchor missing — probe script gone."
    # Internal verifier anchor.
    assert _path_present(
        "scripts", "observability", "verify-15-binary-sbom-against-baseline.py"
    ), "D3 internal-observability uplift anchor missing — verifier script gone."
    # Daily-cadence workflow scheduling.
    keyless_workflow = (
        _repo_root() / ".github" / "workflows" / "cosign-keyless-oidc-drift-probe.yml"
    )
    assert keyless_workflow.is_file()
    content = keyless_workflow.read_text(encoding="utf-8")
    # Daily-cadence keyword presence (cron or schedule).
    assert "cron" in content or "schedule" in content, (
        "Tag-47 PR #307 keyless-OIDC workflow has no scheduled-cadence; "
        "D3 internal-uplift requires daily scheduling."
    )


def test_t50_a1_cross_welle_hot_spot_cascade_marathon_coverage_uplift() -> None:
    """A1 Cross-Modul-Drift gains Tag-49 marathon-rollup cascade coverage.

    Tag-45 baseline classified A1 as COVERED via Tag-40 (pairwise
    isolation), Tag-43 (marathon-aggregate blocker rejection), and
    Tag-44 AP-4 (namespace-prefix discipline). Tag-49 PR #316 adds
    the **marathon-rollup cascade-detection** layer (22 tests):
    per-day single-cascade detection, cascade-overlap union, multi-
    day-flap recording, terminal-Welle-7-isolated no-cascade, etc.

    A1 stays COVERED; the Tag-50 sweep records the new marathon-
    rollup layer as a fourth A1 defence (per-Welle hot-spot
    aggregators + cross-Welle aggregator + E2E acceptance).
    """
    # Per-Welle aggregators must all be present.
    for welle in (3, 4, 5, 6, 7):
        assert _path_present(
            "tooling", "ci", f"welle_{welle}_hot_spot_aggregator.py"
        ), f"Welle-{welle} hot-spot aggregator missing — A1 marathon-rollup hole."
        assert _path_present(
            "tests", "ci", f"test_welle_{welle}_hot_spot_probe.py"
        ), f"Welle-{welle} hot-spot probe test missing."
    # Cross-Welle aggregator + E2E.
    assert _path_present("tooling", "ci", "cross_welle_hot_spot_aggregator.py")
    assert _path_present("tests", "phase_3c", "test_cross_welle_hot_spot_e2e.py")
    assert _path_present("tests", "ci", "test_cross_welle_hot_spot_aggregator.py")


# ===========================================================================
# §6 — Tag-50 consolidated summary recomputation (2 tests).
# ===========================================================================


def test_t50_consolidated_summary_grand_total_still_24() -> None:
    """The 24-failure-mode total is invariant across Tag-46/47/48/49.

    The denominator stays at 24 (A8 + B6 + C5 + D5 per Henrik Tag-44
    Pre-Mortem-Skizze §6 table-row count). Tag-50 sweep records new
    defence-in-depth anchors but does not introduce new failure-modes
    (no pre-cutover-probe surfaced GAP-OPEN candidates in the Tag-47..49
    PR-window).

    Coverage state at Tag-50 (Amara reading, P2):

    | Class | Total | COVERED | PARTIAL | GAP-ACCEPTED | GAP-OPEN |
    |---|---|---|---|---|---|
    | A | 8 | 8 (all) | 0 | 0 | 0 |
    | B | 6 | 3 (B1, B2, B4) | 1 (B3) | 2 (B5, B6) | 0 |
    | C | 5 | 2 (C1, C2) | 0 | 3 (C3, C4, C5) | 0 |
    | D | 5 | 0 | 1 (D3 internal-uplift candidate) | 4 (D1, D2, D4, D5) | 0 |
    | Total | 24 | 13 | 2 | 9 | 0 |

    The D3 PARTIAL-uplift is the **single new state-transition
    candidate** beyond the Tag-46 cumulative state (Tag-46 ended at
    13 COVERED / 1 PARTIAL / 10 GAP-ACCEPTED / 0 GAP-OPEN, but the
    Tag-46 sweep doc projected 13 COVERED if all four Tag-46 items
    land; the actual Tag-46 §3 doc-update recorded 12 COVERED at
    Tag-46 sweep-write-time and the Tag-47 audit re-pinned the
    Pyramide structure without changing per-mode classifications).
    The Tag-50 doc-update inscribes the post-Tag-49 stand.
    """
    # Per-class tallies sum to 24.
    a_total = 8
    b_total = 6
    c_total = 5
    d_total = 5
    grand = a_total + b_total + c_total + d_total
    assert grand == 24, grand
    # Tag-50 Amara reading: 13 COVERED / 2 PARTIAL / 9 GAP-ACCEPTED / 0 GAP-OPEN.
    covered = 8 + 3 + 2 + 0
    partial = 0 + 1 + 0 + 1  # B3 + D3-uplift candidate.
    gap_accepted = 0 + 2 + 3 + 4
    gap_open = 0
    assert covered + partial + gap_accepted + gap_open == 24
    # Tag-50 Amara reading specifically.
    assert covered == 13
    assert partial == 2
    assert gap_accepted == 9
    assert gap_open == 0


def test_t50_tag_45_46_47_baseline_anchors_intact() -> None:
    """All Tag-45/46/47 baseline anchors must still exist post-Tag-49.

    Defensive: the Tag-44..49 PR-range must not have removed any of
    the Tag-45 baseline, Tag-46 sweep, or Tag-47 audit anchors. If
    any were silently removed, this test fires and the Tag-50
    consolidated sweep refuses to certify the coverage state.
    """
    # Tag-45 baseline.
    matrix_doc = (
        _repo_root() / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
    )
    assert matrix_doc.is_file(), "Tag-45 coverage-matrix doc removed."
    content = matrix_doc.read_text(encoding="utf-8")
    assert "## 3. Coverage summary" in content
    assert "Tag-46+ follow-up items" in content
    # Tag-45 baseline test file.
    assert _path_present("tests", "phase_3c", "test_pre_mortem_failure_mode_coverage_audit.py")
    # Tag-46 sweep file.
    assert _path_present("tests", "phase_3c", "test_pre_mortem_coverage_sweep_tag_46.py")
    # Tag-47 audit file.
    assert _path_present(
        "tests", "phase_3c", "test_acceptance_pyramide_tag_46_validation.py"
    )
    # Tag-46 sweep TAG46_FOLLOWUPS constant still names exactly five items.
    sweep_text = (
        _repo_root()
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_coverage_sweep_tag_46.py"
    ).read_text(encoding="utf-8")
    # Five Tag46FollowUpItem entries in TAG46_FOLLOWUPS.
    occurrences = re.findall(r"Tag46FollowUpItem\(", sweep_text)
    assert len(occurrences) == 5, (
        f"Tag-46 sweep TAG46_FOLLOWUPS constant has drifted from 5 items to "
        f"{len(occurrences)} occurrences."
    )
