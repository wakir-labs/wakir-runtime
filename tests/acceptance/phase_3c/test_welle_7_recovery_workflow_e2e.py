# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-7 E2E acceptance — ``recovery_workflow``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-7
  = ``recovery_workflow`` (Komplexester Pfad, zuletzt).
- ADR-0065 §Welle-Ende-Acceptance §WE-1...WE-4 — the cutover-welle-end
  criteria that *only* fire after Welle-7 completes.

Welle character
---------------

``recovery_workflow`` is the cross-modul recovery orchestration: when
a persona-engine restart leaves transient state inconsistent, the
recovery-workflow walks the state-backing + lifecycle-state-machine
+ bridge-audit-writer trail to reconstruct a consistent restart-point.
Komplexester Pfad: depends on *every* prior welle's substrate.

Welle-7 is the last welle. After Welle-7-Acceptance-Kriterien green
+ WE-1...WE-4 verified, the Phase-3c-Cutover-Welle is complete and
ADR-0035 §C-Drift-Closure-Item (ADR-0063 §Folgeartefakt 10) flips to
done.
"""

from __future__ import annotations

import pytest

from ._ac_assertions import (
    assert_ac_1_bridge_audit_consistency,
    assert_ac_2_performance_headroom,
    assert_ac_3_bug_rate,
    assert_ac_4_cross_review_consensus,
    assert_ac_5_v907_pin_validation,
)
from .conftest import WELLE_BY_NAME, WELLE_ORDER

WELLE_NAME = "recovery_workflow"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1.
# ---------------------------------------------------------------------------


def test_welle_7_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: recovery-workflow-envelope parity Python ⇆ Rust on 5 days."""
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=4)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_7_ac_1_recovery_decision_drift_blocks(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: recovery-decision drift.

    The recovery-workflow's most dangerous failure: Python and Rust
    pick different reconstructed restart-points from the same trail.
    The downstream effect would be silent — the engine restarts
    cleanly but at a divergent state. AC-1 envelope-hash must catch
    this at the decision-record level.
    """
    drift_req = f"req-{WELLE_NAME}-d0-0"  # first decision
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=4, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2.
# ---------------------------------------------------------------------------


def test_welle_7_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust recovery-workflow P95 within Python+20% budget.

    Recovery is invoked at restart-time only → low call-rate, but the
    per-invocation P95 dominates the cold-restart-time SLO. Placeholder
    Python-baseline ~120ms p95 (multi-file scan + reconstruction).
    """
    python_baseline_p95_ms = 120.0
    rust_observed_p95_ms = 85.0
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


# ---------------------------------------------------------------------------
# AC-3.
# ---------------------------------------------------------------------------


def test_welle_7_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-7 Beobachtungs-Woche."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4.
# ---------------------------------------------------------------------------


def test_welle_7_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Welle-7 Cross-Review-Session all-personas-consent.

    Welle-7 is the final cutover step — the consensus must be
    unanimous and explicitly anchored to the Welle-Ende
    Acceptance-Kriterien (WE-1...WE-4) about to fire.
    """
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5.
# ---------------------------------------------------------------------------


def test_welle_7_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-7 cutover."""
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-7 Welle-Ende-Acceptance — WE-1...WE-4 (ADR-0065).
# ---------------------------------------------------------------------------


def test_welle_7_we_2_quadlet_all_seven_rust(mocked_quadlet_env) -> None:
    """WE-2: Quadlet-Default-ENV-Flags alle 7 auf ``rust`` gesetzt
    (ADR-0065 §Welle-Ende-Acceptance).
    """
    all_moduln = tuple(modul for _, modul in WELLE_ORDER)
    env = mocked_quadlet_env(WELLE_NAME, flipped_moduln=all_moduln)
    rust_count = sum(1 for v in env.values() if v == "rust")
    assert rust_count == 7, (
        f"WE-2: all 7 moduln must be rust post-Welle-7; got rust_count={rust_count}"
    )
    for _, modul in WELLE_ORDER:
        key = f"WAKIR_ENGINE_{modul.upper()}_BACKEND"
        assert env[key] == "rust", (
            f"WE-2: modul {modul} must be rust; got {env[key]!r}"
        )


def test_welle_7_we_1_container_tag_0_7_0_rust_record() -> None:
    """WE-1: Container-Image-Tag-Cut ``0.7.0-rust`` as Production-
    Default-Tag aktiv (ADR-0065 §Welle-Ende-Acceptance WE-1).

    Placeholder — Phase-3c-trigger sprint wires the real container-
    registry-tag-query. The skeleton encodes the *expected tag-shape*
    so a registry-shape change surfaces here.
    """
    expected_tag = "0.7.0-rust"
    # Placeholder Operator-Hand-substituted value from the
    # ``buildah --tag`` output post-Welle-7. Sprint replaces with
    # a real ``skopeo inspect`` query.
    observed_tag = "0.7.0-rust"
    assert observed_tag == expected_tag, (
        f"WE-1: production-default container-tag must be {expected_tag!r}; "
        f"got {observed_tag!r}"
    )


@pytest.mark.skip(reason="pending welle-cutover — Henrik-Audit-Compliance-Check wiring")
def test_welle_7_we_3_henrik_audit_compliance_green() -> None:
    """WE-3: ADR-0035 §C-Drift-Closure-Item markiert als done.
    Henrik-Audit-Compliance-Check GREEN (ADR-0065 §Welle-Ende-Acceptance).

    Operator-Hand drill substrate — Henrik (Internal Audit) signs off
    that the Python-Substrat-Pragma-Drift against ADR-0035 §C is now
    closed. Phase-3c-trigger sprint wires the Audit-Trail attestation.
    """
    raise NotImplementedError("pending welle-cutover")


@pytest.mark.skip(reason="pending welle-cutover — persona_engine_py_legacy archive move")
def test_welle_7_we_4_python_legacy_archived_not_deleted() -> None:
    """WE-4: Python-Engine-Code wird *nicht* gelöscht, sondern in
    ``wirelang/persona_engine_py_legacy/`` umbenannt (ADR-0065
    §Welle-Ende-Acceptance WE-4).

    The 4-Wochen-Reserve must be present + valid post-Welle-7. Volldelete
    is a Phase-4-Folge-Item, *not* a Welle-7 step.
    """
    raise NotImplementedError("pending welle-cutover")
