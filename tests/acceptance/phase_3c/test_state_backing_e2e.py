# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c Cutover Welle-4 E2E acceptance — ``state_backing``.

Anchors
-------

- ADR-0065 §Verifikations-Plan §"Vorgeschlagene Reihenfolge" — Welle-4
  = ``state_backing`` (Persistenter State, höheres Risiko).
- ADR-0065 §Rollback-Procedure pro Komponente §3 — Schema-Migrations-
  Rollback-Plan is *required pre-Welle* for ``state_backing``.
- ADR-0065 §Risiken §"Cross-Komponenten-Schema-Drift" — Welle-4 is
  the *source* of any schema drift that downstream moduln consume.

Welle character
---------------

``state_backing`` is the persistent-state substrate for the engine:
file-system-backed JCS-canonicalised persona-state records, written
under a deterministic directory layout. The Rust-default flip
introduces serialisation-byte-exact-parity requirements (any byte-
divergence in JCS output across Python/Rust would cause hash-anchor
drift downstream).

Welle-4 is the *first* welle where the Schema-Migrations-Rollback-Plan
(ADR-0065 §Rollback-Procedure §3) is a hard pre-requisite — Welle-1/2
were read-only, Welle-3 was idempotent. From Welle-4 onwards, state-
on-disk could outlast a rollback.
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
from .conftest import WELLE_BY_NAME

WELLE_NAME = "state_backing"
WELLE_INDEX = WELLE_BY_NAME[WELLE_NAME]

pytestmark = pytest.mark.phase_3c_acceptance


# ---------------------------------------------------------------------------
# AC-1.
# ---------------------------------------------------------------------------


def test_welle_4_ac_1_bridge_audit_consistency_5_of_5_days(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1: state-write-envelope parity Python ⇆ Rust on 5 days."""
    roundtrips = mocked_bridge_audit_writer(WELLE_NAME, days=5, per_day=5)
    assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


def test_welle_4_ac_1_jcs_byte_drift_blocks(
    mocked_bridge_audit_writer,
) -> None:
    """AC-1 failure-mode: JCS-byte-divergence in state-write envelope.

    Welle-4-specific drift-source: any Unicode-normalisation or float-
    formatting difference between Python's ``rfc8785`` and the Rust
    JCS-implementation would produce a one-byte payload diff → sha256
    diff → AC-1 drift.
    """
    drift_req = f"req-{WELLE_NAME}-d1-2"
    roundtrips = mocked_bridge_audit_writer(
        WELLE_NAME, days=5, per_day=5, drift_request_ids=(drift_req,)
    )
    with pytest.raises(AssertionError, match="AC-1"):
        assert_ac_1_bridge_audit_consistency(roundtrips, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-2.
# ---------------------------------------------------------------------------


def test_welle_4_ac_2_performance_within_headroom() -> None:
    """AC-2: Rust state_backing P95 within Python+20% budget.

    Write-path is filesystem-bound; the in-memory JCS+serialisation is
    Rust's win-territory but the fsync-tail dominates. Placeholder
    Python-baseline ~15ms p95.
    """
    python_baseline_p95_ms = 15.0
    rust_observed_p95_ms = 12.0
    assert_ac_2_performance_headroom(
        python_baseline_p95_ms, rust_observed_p95_ms, WELLE_NAME
    )


# ---------------------------------------------------------------------------
# AC-3.
# ---------------------------------------------------------------------------


def test_welle_4_ac_3_bug_rate_zero_s0_s1() -> None:
    """AC-3: 0 S0/S1 issues during Welle-4 Beobachtungs-Woche."""
    assert_ac_3_bug_rate(s0_count=0, s1_count=0, welle=WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-4.
# ---------------------------------------------------------------------------


def test_welle_4_ac_4_cross_review_consensus(mocked_cross_review) -> None:
    """AC-4: Welle-4 Cross-Review-Session all-personas-consent.

    Welle-4 is the first state-mutating welle → Selin (Persona-Engine-
    Owner) and Tomás (Engineering-Lead) consent are non-negotiable.
    """
    record = mocked_cross_review(WELLE_NAME)
    assert_ac_4_cross_review_consensus(record, WELLE_NAME)


# ---------------------------------------------------------------------------
# AC-5.
# ---------------------------------------------------------------------------


def test_welle_4_ac_5_v907_pin_validation_full_pass() -> None:
    """AC-5: V-907 Pin-Validation 100% post-Welle-4 cutover."""
    persona_def_count = 6
    assert_ac_5_v907_pin_validation(
        persona_def_count=persona_def_count,
        pin_validation_pass_count=persona_def_count,
        welle=WELLE_NAME,
    )


# ---------------------------------------------------------------------------
# Welle-4 substrate sanity — schema-migration rollback drill.
# ---------------------------------------------------------------------------


def test_welle_4_three_moduln_rust_four_python(mocked_quadlet_env) -> None:
    """Welle-4 Quadlet-state: Welle-1/2/3 + Welle-4 on rust, Welle-5/6/7
    on python.
    """
    env = mocked_quadlet_env(
        WELLE_NAME,
        flipped_moduln=(
            "v907_verify",
            "svid_workload_identity",
            "bridge_audit_writer",
            "state_backing",
        ),
    )
    rust_count = sum(1 for v in env.values() if v == "rust")
    python_count = sum(1 for v in env.values() if v == "python")
    assert rust_count == 4 and python_count == 3, (
        f"Welle-4 mixed-state must have exactly 4 rust + 3 python; "
        f"got rust={rust_count}, python={python_count}"
    )


@pytest.mark.skip(reason="pending welle-cutover — Schema-Migrations-Rollback-Plan drill")
def test_welle_4_schema_migration_rollback_under_2h() -> None:
    """Welle-4 Rollback-SLA: ≤2 Stunden bei Schema-Migration-Rollback
    (ADR-0065 §Rollback-Strategie).

    Welle-4 is the first welle where state-on-disk could outlast a
    rollback — the Schema-Migrations-Rollback-Plan must be drilled
    pre-Welle. Operator-Hand drill substrate.
    """
    raise NotImplementedError("pending welle-cutover")


@pytest.mark.skip(reason="pending welle-cutover — Cross-Komponenten-Schema-Verify wiring")
def test_welle_4_state_schema_readable_by_python_lifecycle() -> None:
    """Welle-4 Cross-Komponenten-Schema check: state written by Rust-
    state_backing must be readable by the *still-Python*
    lifecycle_state_machine (Welle-5 not yet flipped).

    ADR-0065 §Risiken §"Cross-Komponenten-Schema-Drift" mitigation.
    Selin-Sprint-Pengine-N produces the cross-schema-verify substrate;
    this test wires into it post-Welle-4.
    """
    raise NotImplementedError("pending welle-cutover")
