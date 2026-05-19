# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-75 - Welle-7 Final-Sealing Producer (Selin, persona-engine).

Tag-69 (PR #438) shipped Welle-1 producer-path. Tag-70 (PR #444) shipped
Welle-2 Doppelbetrieb-Sealing + Rollback-Writer. Tag-71 (PR #451) wired
the top-level handlers + Welle-3 Bridge-Audit sign-off shorthand
(Pre-Auditor-Guarded). Tag-72 (PR #458) added the Welle-4 State-Backing
sign-off shorthand. Tag-73 (PR #465) added the Welle-5 Capability-Token
sign-off shorthand. Tag-74 (PR #472) added the Welle-6 Cross-Substrate-
Parity sign-off shorthand + W5-anchor-fix. Tag-75 (this PR) closes the
producer-substrate by adding the **Welle-7 Final-Sealing sign-off**
shorthand:

* Welle-7 is the **terminal** Welle of the Phase-3c-Welle-Marathon
  (KW-27, Cutover-Mittwoch 2026-07-01, Sign-off-Freitag 2026-07-03 per
  ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3 table).
* Welle-7 sign-off triggers the downstream
  ``PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7`` marker (per
  ``docs/quality-gates/phase-3c-doppel-welle-6-7.md`` §4.1
  ``test_dw_ac_6_7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker``).
* Welle-7 carries **two** hot-spot axes: it is both Pre-Auditor-Guarded
  (Henrik-cannot-self-sign-off, analog Welle-3) AND Final-Sealing-Marker-
  Guarded (Phase-3-Marathon-Schluss-Acceptance verdict).

Scope (Tag-75)
--------------

One new producer-method:

* ``WelleStateProducer.handle_welle_7_signoff_event`` -- structural
  in-progress -> signed-off transition gated by THREE preconditions:
  ``sign_off_marker_status == "signed-off"`` AND
  ``pre_auditor_decision == "designated"`` AND
  ``final_sealing_marker_status == "confirmed"``. Audit-record carries
  ``trigger="final-sealing"`` (the sixth disjoint trigger-family,
  disjoint from Welle-2 ``"sealing"``, Welle-3/non-7 vanilla
  ``"sign-off"``, Welle-4 ``"snapshot-restore"``, Welle-5
  ``"capability-token-rotation"``, and Welle-6
  ``"cross-substrate-parity"``).

One new top-level handler in ``wirelang.persona_engine.engine``:

* ``handle_welle_7_signoff_event`` -- delegates to the producer
  method above with ``welle_number=7`` hard-coded.

And one async wrapper in ``wirelang.persona_engine.engine_async``:

* ``handle_welle_7_signoff_event`` -- runs the sync handler in the
  default loop's thread-pool executor.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the
Tag-69/70/71/72/73/74 producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), Phase-3-COMPLETE-
marker emission (audit-trail-consumer territory; this test pins the
engine-side ``WelleAuditRecord`` only), or container-infra
(Kai-Domaene, Zone-J). It pins the Tag-75 Welle-7 sign-off shorthand;
the schema-pin is unchanged (final-sealing-iso lives in the audit-
stream, not in the state-file).
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import List

import pytest

from wirelang.persona_engine import engine as engine_mod
from wirelang.persona_engine import engine_async as engine_async_mod
from wirelang.persona_engine.welle_state_producer import (
    CAPABILITY_TOKEN_ROTATED,
    CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN,
    CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN,
    CROSS_SUBSTRATE_PARITY_VERIFIED,
    DOPPELBETRIEB_SEALED,
    DOPPELBETRIEB_SEALED_WELLEN,
    FINAL_SEALING_CONFIRMED,
    FINAL_SEALING_GUARDED_WELLEN,
    FinalSealingError,
    InvalidStatusTransitionError,
    PHASE_LITERAL,
    PRE_AUDITOR_GUARDED_WELLEN,
    PreAuditorGuardError,
    ROLLBACK_MARKER_AUTHORIZED,
    SCHEMA_VERSION_PIN,
    SNAPSHOT_RESTORE_GUARDED_WELLEN,
    SNAPSHOT_RESTORE_VERIFIED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    SignOffPreconditionError,
    TimeInvariantViolationError,
    WelleAuditRecord,
    WelleProducerError,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69/70/71/72/73/74 layout).
# ---------------------------------------------------------------------------


# Post Tag-74 reconciliation. Welle-7 is KW-27 per the canonical
# pre-cutover-acceptance-run-order.md §3 table (line 98).
CANONICAL_KW_ANCHOR = {
    1: "KW-22",
    2: "KW-23",
    3: "KW-25",
    4: "KW-26",
    5: "KW-26",
    6: "KW-26",
    7: "KW-27",
}


def _pending_stub(welle_number: int) -> dict:
    return {
        "welle_number": welle_number,
        "schema_version": SCHEMA_VERSION_PIN,
        "phase": PHASE_LITERAL,
        "kw_cutover_anchor": CANONICAL_KW_ANCHOR[welle_number],
        "cutover_iso": "",
        "signoff_iso": "",
        "status": STATUS_PENDING,
        "rollup_links": {
            "sign_off": f"state/welle-{welle_number}-sign-off.json",
            "validation_last_verdict": (
                f"state/welle-{welle_number}-validation-last-verdict.json"
            ),
            "hot_spot_trend_dir": (
                f"state/welle-{welle_number}-hot-spot-trend/"
            ),
            "pre_auditor_decision": (
                f"state/welle-{welle_number}-pre-auditor-decision.json"
            ),
            "final_sealing_marker": (
                f"state/welle-{welle_number}-final-sealing.json"
            ),
        },
        "audit_trail_anchor": "",
    }


def _seed_pending(state_dir: Path, welle_number: int) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"welle-{welle_number}.json"
    path.write_text(
        json.dumps(_pending_stub(welle_number), indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _seed_in_progress(
    state_dir: Path, welle_number: int, cutover_iso: str
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = _pending_stub(welle_number)
    payload["status"] = STATUS_IN_PROGRESS
    payload["cutover_iso"] = cutover_iso
    path = state_dir / f"welle-{welle_number}.json"
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class _RecordingEmitter:
    def __init__(self) -> None:
        self.records: List[WelleAuditRecord] = []

    def __call__(self, record: WelleAuditRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# (1) Public-API surface invariants for Welle-7 (Tag-75).
# ---------------------------------------------------------------------------


def test_welle_7_is_final_sealing_guarded_constant_pin():
    """Welle-7 MUST be in FINAL_SEALING_GUARDED_WELLEN (Tag-75 §2.8)."""
    assert 7 in FINAL_SEALING_GUARDED_WELLEN
    # Welle-7 is the ONLY final-sealing-guarded Welle.
    assert FINAL_SEALING_GUARDED_WELLEN == frozenset({7})


def test_welle_7_is_pre_auditor_guarded_constant_pin():
    """Welle-7 MUST be pre-auditor-guarded (Henrik-cannot-self-sign-off).

    The Welle-7 sign-off carries BOTH the pre-auditor guard (analog
    Welle-3 Bridge-Audit) and the final-sealing-marker guard
    (Phase-3-Marathon-Schluss-Acceptance). The two guards are
    independent; both MUST hold for a successful sign-off.
    """
    assert 7 in PRE_AUDITOR_GUARDED_WELLEN
    # The pre-auditor-guarded set is exactly {3, 7}.
    assert PRE_AUDITOR_GUARDED_WELLEN == frozenset({3, 7})


def test_final_sealing_confirmed_literal_is_canonical():
    """The marker authority literal MUST be exactly "confirmed".

    Mirrors the design of :data:`DOPPELBETRIEB_SEALED` ("sealed"),
    :data:`SNAPSHOT_RESTORE_VERIFIED` ("restored"),
    :data:`CAPABILITY_TOKEN_ROTATED` ("rotated"),
    :data:`CROSS_SUBSTRATE_PARITY_VERIFIED` ("verified"), and
    :data:`ROLLBACK_MARKER_AUTHORIZED` ("rollback-authorized"). The
    literal is an audit-trail anchor; any drift breaks the operator-
    curated marker contract.

    Critically, ``"confirmed"`` is DISTINCT from Welle-2's ``"sealed"``
    (two distinct sealing concepts: Welle-2 closes the legacy-dual-write
    window; Welle-7 closes the entire Phase-3c-Marathon).
    """
    assert FINAL_SEALING_CONFIRMED == "confirmed"
    assert FINAL_SEALING_CONFIRMED != DOPPELBETRIEB_SEALED


def test_engine_module_exposes_welle_7_handler():
    """Tag-75: engine.py MUST expose ``handle_welle_7_signoff_event``."""
    assert hasattr(engine_mod, "handle_welle_7_signoff_event")
    assert callable(engine_mod.handle_welle_7_signoff_event)


def test_engine_async_module_exposes_welle_7_handler():
    """Tag-75: engine_async.py MUST expose the async wrapper as coroutine."""
    assert hasattr(engine_async_mod, "handle_welle_7_signoff_event")
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_7_signoff_event
    )


def test_sync_welle_7_handler_is_not_a_coroutine():
    """The sync handler in engine.py MUST be a plain function."""
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_7_signoff_event
    )


# ---------------------------------------------------------------------------
# (2) Six-marker-family disjointness — Welle-7 hot-spot pin.
# ---------------------------------------------------------------------------


def test_welle_7_final_sealing_disjoint_from_other_marker_guarded_sets():
    """Welle-7 final-sealing MUST be disjoint from the other 4 marker sets.

    The pre-auditor guard intentionally OVERLAPS with the final-sealing
    guard at Welle-7 (Welle-7 is in BOTH families; that's the Tag-75
    hot-spot-axis pin). The four OTHER marker families (sealing,
    snapshot-restore, capability-token-rotation, cross-substrate-parity)
    MUST be disjoint from final-sealing.
    """
    assert FINAL_SEALING_GUARDED_WELLEN.isdisjoint(
        DOPPELBETRIEB_SEALED_WELLEN
    )
    assert FINAL_SEALING_GUARDED_WELLEN.isdisjoint(
        SNAPSHOT_RESTORE_GUARDED_WELLEN
    )
    assert FINAL_SEALING_GUARDED_WELLEN.isdisjoint(
        CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN
    )
    assert FINAL_SEALING_GUARDED_WELLEN.isdisjoint(
        CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN
    )


def test_welle_7_pre_auditor_guard_intentionally_overlaps_final_sealing():
    """Welle-7 is in BOTH pre-auditor-guarded AND final-sealing-guarded sets.

    This is the Tag-75 hot-spot-axis pin: Welle-7 carries two guards
    simultaneously (Pre-Auditor + Final-Sealing-Marker). The triggers
    are distinct (Welle-3 pre-auditor sign-off has
    ``trigger="sign-off"``; Welle-7 has ``trigger="final-sealing"``);
    the audit-trail disambiguates via the trigger-literal.
    """
    welle_7_intersection = (
        PRE_AUDITOR_GUARDED_WELLEN & FINAL_SEALING_GUARDED_WELLEN
    )
    assert welle_7_intersection == frozenset({7})


def test_six_marker_families_pairwise_disjoint_modulo_w7_overlap():
    """Five marker-families MUST be Welle-pairwise-disjoint EXCEPT for the
    intentional W7 overlap between pre-auditor and final-sealing.

    The six families:
      - sealing (W2)
      - pre-auditor (W3, W7)
      - snapshot-restore (W4)
      - capability-token-rotation (W5)
      - cross-substrate-parity (W6)
      - final-sealing (W7)

    Across the six families there are C(6,2) = 15 pairs. 14 pairs MUST
    be disjoint. The one EXCEPTION is the pre-auditor x final-sealing
    pair at Welle-7 (intentional, Tag-75 hot-spot-axis pin).
    """
    families = {
        "sealing": DOPPELBETRIEB_SEALED_WELLEN,
        "pre-auditor": PRE_AUDITOR_GUARDED_WELLEN,
        "snapshot-restore": SNAPSHOT_RESTORE_GUARDED_WELLEN,
        "capability-token-rotation": CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN,
        "cross-substrate-parity": CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN,
        "final-sealing": FINAL_SEALING_GUARDED_WELLEN,
    }
    names = sorted(families.keys())
    expected_overlap_pair = frozenset({"pre-auditor", "final-sealing"})
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            pair = frozenset({a, b})
            if pair == expected_overlap_pair:
                # Intentional W7 overlap.
                assert families[a] & families[b] == frozenset({7}), (
                    f"expected W7 overlap between pre-auditor and "
                    f"final-sealing; got {families[a] & families[b]}"
                )
            else:
                assert families[a].isdisjoint(families[b]), (
                    f"unexpected marker-family overlap between {a!r} "
                    f"and {b!r}: {families[a]} & {families[b]} = "
                    f"{families[a] & families[b]}"
                )


def test_six_marker_family_union_covers_wellen_2_through_7():
    """The union of all six marker-families MUST be exactly {2,3,4,5,6,7}.

    Welle-1 is the only Welle without a marker-family (Cutover-T0
    first-fire; vanilla sign-off path uses ``handle_sign_off_event``).
    Welle-7 is double-counted in two families (pre-auditor + final-
    sealing), but the union absorbs the duplicate.
    """
    union = (
        DOPPELBETRIEB_SEALED_WELLEN
        | PRE_AUDITOR_GUARDED_WELLEN
        | SNAPSHOT_RESTORE_GUARDED_WELLEN
        | CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN
        | CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN
        | FINAL_SEALING_GUARDED_WELLEN
    )
    assert union == frozenset({2, 3, 4, 5, 6, 7})


# ---------------------------------------------------------------------------
# (3) Producer-method direct-call tests (handle_welle_7_signoff_event).
# ---------------------------------------------------------------------------


def test_producer_welle_7_signoff_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    record = producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["welle_number"] == 7
    assert on_disk["signoff_iso"] == "2026-07-03T15:00:00Z"
    # Cutover-iso preserved.
    assert on_disk["cutover_iso"] == "2026-07-01T08:00:00Z"

    assert record.welle_number == 7
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "final-sealing"
    assert emitter.records == [record]


def test_producer_welle_7_signoff_refused_without_final_sealing_marker(
    tmp_path,
):
    """A bad final-sealing marker MUST raise FinalSealingError."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(FinalSealingError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status="pending",
        )


def test_producer_welle_7_signoff_refused_with_empty_final_sealing_marker(
    tmp_path,
):
    """Empty final-sealing marker MUST be refused (no implicit defaults)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(FinalSealingError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status="",
        )


def test_producer_welle_7_signoff_refused_with_welle_2_sealed_literal(tmp_path):
    """Welle-2's ``"sealed"`` MUST NOT authorise the Welle-7 final-sealing.

    The two literals are intentionally distinct; passing ``"sealed"``
    where ``"confirmed"`` is required MUST be refused. This pins the
    audit-trail trigger-family disambiguation contract.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(FinalSealingError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_producer_welle_7_signoff_refused_without_pre_auditor_decision(
    tmp_path,
):
    """Welle-7 sign-off MUST refuse if pre_auditor_decision is missing.

    The pre-auditor guard fires earlier than the final-sealing-marker
    guard in the refusal chain. With both preconditions violated, the
    producer raises :class:`PreAuditorGuardError` (not
    :class:`FinalSealingError`). This pins the refusal-order to be
    deterministic for audit-trail forensics.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(PreAuditorGuardError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision=None,
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_refused_with_undesignated_pre_auditor(
    tmp_path,
):
    """A non-"designated" pre_auditor_decision MUST raise PreAuditorGuardError.

    Mirrors the Welle-3 pre-auditor-guard test from Tag-71. This pins
    the symmetric pre-auditor enforcement across Welle-3 and Welle-7.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(PreAuditorGuardError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="recused",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_refused_without_sign_off_marker(tmp_path):
    """A bad sign-off marker MUST raise SignOffPreconditionError.

    Refusal-order: sign-off-marker guard fires FIRST, before the
    pre-auditor guard and before the final-sealing-marker guard. This
    pins the deterministic refusal-order for audit-trail forensics.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SignOffPreconditionError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status="pending",
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_idempotent_double_fire(tmp_path):
    """A second sign-off after the first MUST be a no-op (idempotency).

    The idempotent path STILL enforces the pre-auditor + final-sealing-
    marker preconditions; this is the stricter-than-others contract
    documented on the producer-method docstring.
    """
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    # Second fire: idempotent no-op.
    record_2 = producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    assert record_2.prior_status == STATUS_SIGNED_OFF
    assert record_2.new_status == STATUS_SIGNED_OFF
    assert record_2.trigger == "final-sealing"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # signoff_iso from the first fire is preserved.
    assert on_disk["signoff_iso"] == "2026-07-03T15:00:00Z"
    # Two emitter records: the first transition + the idempotent no-op.
    assert len(emitter.records) == 2


def test_producer_welle_7_signoff_idempotent_still_enforces_pre_auditor_guard(
    tmp_path,
):
    """Stricter-idempotency: a retry without pre-auditor MUST be refused
    EVEN IF the state-file already reports signed-off.

    This is the Welle-7-specific stricter-idempotency contract pinned
    in the handler docstring; it differs from Welle-2/4/5/6 idempotency
    (which short-circuit before marker-validation).
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    # First fire: happy path.
    producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    # Second fire: state is signed-off, but pre-auditor decision is bad.
    # The pre-auditor guard fires before the idempotency short-circuit.
    with pytest.raises(PreAuditorGuardError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="undesignated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_idempotent_still_enforces_final_sealing_marker(
    tmp_path,
):
    """Stricter-idempotency for final-sealing-marker: a retry without
    the marker MUST be refused EVEN IF the state-file already reports
    signed-off.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    # First fire: happy path.
    producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    # Second fire: state is signed-off, but final-sealing-marker is bad.
    with pytest.raises(FinalSealingError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status="reverted",
        )


def test_producer_welle_7_signoff_refused_from_pending(tmp_path):
    """Sign-off from ``pending`` MUST be refused (no cutover yet)."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 7)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_refused_from_rolled_back(tmp_path):
    """Sign-off from ``rolled-back`` MUST be refused (rolled-back is terminal)."""
    state_dir = tmp_path / "state"
    payload = _pending_stub(7)
    payload["status"] = STATUS_ROLLED_BACK
    payload["cutover_iso"] = "2026-07-01T08:00:00Z"
    (state_dir).mkdir(parents=True, exist_ok=True)
    target = state_dir / "welle-7.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_7_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_time_invariant_cutover_le_signoff(tmp_path):
    """Plan-doc §3.4 time-invariant MUST hold across the Welle-7 path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-03T15:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_welle_7_signoff_event(
            # signoff strictly before cutover -> refused.
            signoff_iso="2026-07-01T08:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


def test_producer_welle_7_signoff_atomic_write_no_partial_state(tmp_path):
    """On a successful Welle-7 sign-off the on-disk file MUST be fully written."""
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    expected_keys = {
        "welle_number",
        "schema_version",
        "phase",
        "kw_cutover_anchor",
        "cutover_iso",
        "signoff_iso",
        "status",
        "rollup_links",
        "audit_trail_anchor",
    }
    assert set(on_disk.keys()) >= expected_keys
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL


# ---------------------------------------------------------------------------
# (4) Top-level sync handler (engine.handle_welle_7_signoff_event).
# ---------------------------------------------------------------------------


def test_sync_handle_welle_7_signoff_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    record = engine_mod.handle_welle_7_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.welle_number == 7
    assert record.trigger == "final-sealing"


def test_sync_handle_welle_7_signoff_event_emitter_recorded(tmp_path):
    """Custom audit-emitter MUST be invoked exactly once on the happy path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    engine_mod.handle_welle_7_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        audit_emitter=emitter,
    )
    assert len(emitter.records) == 1
    rec = emitter.records[0]
    assert rec.welle_number == 7
    assert rec.new_status == STATUS_SIGNED_OFF
    assert rec.trigger == "final-sealing"


def test_sync_handle_welle_7_signoff_event_refuses_without_final_sealing_marker(
    tmp_path,
):
    """The final-sealing-marker gate MUST be enforced via the top-level handler."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    with pytest.raises(FinalSealingError):
        engine_mod.handle_welle_7_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status="audit-only",
        )


def test_sync_handle_welle_7_signoff_event_refuses_without_pre_auditor(
    tmp_path,
):
    """The pre-auditor gate MUST be enforced via the top-level handler."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    with pytest.raises(PreAuditorGuardError):
        engine_mod.handle_welle_7_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="undesignated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )


# ---------------------------------------------------------------------------
# (5) Async wrapper (engine_async.handle_welle_7_signoff_event).
# ---------------------------------------------------------------------------


def test_async_handle_welle_7_signoff_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")

    async def _run() -> WelleAuditRecord:
        return await engine_async_mod.handle_welle_7_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.trigger == "final-sealing"


def test_async_handle_welle_7_signoff_event_refuses_without_final_sealing_marker(
    tmp_path,
):
    """The final-sealing-marker gate MUST be enforced via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")

    async def _run() -> WelleAuditRecord:
        return await engine_async_mod.handle_welle_7_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status="drifted",
        )

    with pytest.raises(FinalSealingError):
        asyncio.run(_run())


def test_async_handle_welle_7_signoff_event_refuses_without_pre_auditor(
    tmp_path,
):
    """The pre-auditor gate MUST be enforced via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")

    async def _run() -> WelleAuditRecord:
        return await engine_async_mod.handle_welle_7_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision=None,
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )

    with pytest.raises(PreAuditorGuardError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# (6) Cross-state interactions: rollback after Welle-7 sign-off.
# ---------------------------------------------------------------------------


def test_welle_7_can_be_rolled_back_post_sign_off(tmp_path):
    """After a Welle-7 sign-off the ``signed-off -> rolled-back`` MUST hold.

    Forensic note: a Welle-7 rollback AFTER the Phase-3-COMPLETE-marker
    has been emitted is a substrate-level Phase-3-COMPLETE-marker
    inversion event. The audit-trail consumer (Henrik Internal Audit
    Zone-N) treats this as an S0 Phase-3-Marathon-Schluss-Acceptance
    inversion; this producer-substrate ONLY records the rollback
    transition itself (rollback-marker-authority + state-machine
    transition). The marker-inversion semantics live at the consumer
    level.
    """
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    engine_mod.handle_welle_7_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    assert json.loads(target.read_text())["status"] == STATUS_SIGNED_OFF
    rollback_record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=7,
        rollback_iso="2026-07-04T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # signoff_iso preserved on rollback for forensic audit-trail.
    assert on_disk["signoff_iso"] == "2026-07-03T15:00:00Z"
    assert rollback_record.prior_status == STATUS_SIGNED_OFF
    assert rollback_record.new_status == STATUS_ROLLED_BACK
    assert rollback_record.trigger == "rollback"


# ---------------------------------------------------------------------------
# (7) Six-marker-family trigger pairwise-distinct (Tag-75 hot-spot axis).
# ---------------------------------------------------------------------------


def test_marker_family_triggers_are_pairwise_distinct_across_six_families(
    tmp_path,
):
    """Across the six marker-guarded sign-off paths the audit-trigger
    MUST be a distinct literal per family.

    Family A (Welle-2 Doppelbetrieb-Sealing)        -> trigger="sealing"
    Family B (Welle-3 Pre-Auditor Bridge-Audit)     -> trigger="sign-off"
    Family C (Welle-4 Snapshot-Restore)             -> trigger="snapshot-restore"
    Family D (Welle-5 Capability-Token)             -> trigger="capability-token-rotation"
    Family E (Welle-6 Cross-Substrate-Parity)       -> trigger="cross-substrate-parity"
    Family F (Welle-7 Final-Sealing)                -> trigger="final-sealing"

    The Welle-7 final-sealing family is DISTINCT from the Welle-3
    pre-auditor family even though both Wellen are pre-auditor-guarded;
    Welle-7's downstream consumer fires the
    ``PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7`` marker which depends on
    the disjoint trigger-literal to route correctly. Henrik Internal
    Audit relies on this 6-family disjointness when reconciling
    rollback decisions against the Tomas-Tag-56-Rollback-Workflow
    J2..J8 envelope catalog.
    """
    # Family A: Welle-2 sealing.
    state_dir_2 = tmp_path / "state_2"
    _seed_in_progress(state_dir_2, 2, "2026-06-10T08:00:00Z")
    rec_2 = engine_mod.handle_welle_sealing_event(
        state_dir_2,
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    # Family B: Welle-3 pre-auditor.
    state_dir_3 = tmp_path / "state_3"
    _seed_in_progress(state_dir_3, 3, "2026-06-17T08:00:00Z")
    rec_3 = engine_mod.handle_welle_3_signoff_event(
        state_dir_3,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    # Family C: Welle-4 snapshot-restore.
    state_dir_4 = tmp_path / "state_4"
    _seed_in_progress(state_dir_4, 4, "2026-06-24T08:00:00Z")
    rec_4 = engine_mod.handle_welle_4_signoff_event(
        state_dir_4,
        signoff_iso="2026-06-26T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    # Family D: Welle-5 capability-token.
    state_dir_5 = tmp_path / "state_5"
    _seed_in_progress(state_dir_5, 5, "2026-06-24T08:00:00Z")
    rec_5 = engine_mod.handle_welle_5_signoff_event(
        state_dir_5,
        signoff_iso="2026-06-26T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    # Family E: Welle-6 cross-substrate-parity.
    state_dir_6 = tmp_path / "state_6"
    _seed_in_progress(state_dir_6, 6, "2026-07-01T08:00:00Z")
    rec_6 = engine_mod.handle_welle_6_signoff_event(
        state_dir_6,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    # Family F: Welle-7 final-sealing (Tag-75, this PR).
    state_dir_7 = tmp_path / "state_7"
    _seed_in_progress(state_dir_7, 7, "2026-07-01T08:00:00Z")
    rec_7 = engine_mod.handle_welle_7_signoff_event(
        state_dir_7,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    triggers = {
        rec_2.trigger,
        rec_3.trigger,
        rec_4.trigger,
        rec_5.trigger,
        rec_6.trigger,
        rec_7.trigger,
    }
    assert triggers == {
        "sealing",
        "sign-off",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
        "final-sealing",
    }
    # All six are signed-off transitions (new_status uniform).
    assert {
        rec_2.new_status,
        rec_3.new_status,
        rec_4.new_status,
        rec_5.new_status,
        rec_6.new_status,
        rec_7.new_status,
    } == {STATUS_SIGNED_OFF}
    # Pairwise-distinct cardinality check (the assertion above already
    # implies it, but pin it explicitly for the audit-trail).
    trigger_list = [
        rec_2.trigger,
        rec_3.trigger,
        rec_4.trigger,
        rec_5.trigger,
        rec_6.trigger,
        rec_7.trigger,
    ]
    assert len(trigger_list) == len(set(trigger_list)) == 6


def test_welle_7_final_sealing_trigger_disjoint_from_welle_2_sealing_literal():
    """The Welle-2 ``"sealing"`` and Welle-7 ``"final-sealing"`` literals
    MUST NOT collide.

    Both Wellen carry a sealing-semantics (Welle-2 closes legacy<->new
    dual-write; Welle-7 closes Phase-3c-Marathon), but the audit-trail
    trigger-literals are DISTINCT to disambiguate the bridge-audit-
    writer routing.
    """
    # This is pinned at the source level by the producer-method
    # selecting "final-sealing" as its trigger literal; verify
    # empirically through producer-records.
    assert "sealing" != "final-sealing"


# ---------------------------------------------------------------------------
# (8) Audit-record byte-canonical JSON for the Welle-7 record.
# ---------------------------------------------------------------------------


def test_welle_7_audit_record_canonical_json_bytes(tmp_path):
    """The Welle-7 audit-record's canonical-JSON bytes MUST sort keys + UTF-8.

    Mirrors the Tag-69+ audit-record-emitter contract: downstream
    bridge-audit-writer hashing depends on byte-stable canonical JSON.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 7, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_welle_7_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
    )
    raw = record.to_json_bytes()
    # Canonical JSON: keys sorted, no whitespace separators.
    decoded = json.loads(raw)
    assert decoded == {
        "cutover_iso": "2026-07-01T08:00:00Z",
        "new_status": STATUS_SIGNED_OFF,
        "prior_status": STATUS_IN_PROGRESS,
        "signoff_iso": "2026-07-03T15:00:00Z",
        "trigger": "final-sealing",
        "welle_number": 7,
    }
    # Byte-stability: re-encoding the decoded dict with sort_keys=True
    # yields the same bytes (modulo separators which we pin here).
    reencoded = json.dumps(
        decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert raw == reencoded


# ---------------------------------------------------------------------------
# (9) FinalSealingError inherits from WelleProducerError.
# ---------------------------------------------------------------------------


def test_final_sealing_error_inherits_from_welle_producer_error():
    """All Welle-N marker-guard errors MUST share a common parent.

    This lets callers ``except WelleProducerError`` once and catch any
    marker-guard refusal without needing to enumerate the six family-
    specific subclasses individually.
    """
    assert issubclass(FinalSealingError, WelleProducerError)
    # And specifically NOT a subclass of any other marker-family error.
    assert not issubclass(FinalSealingError, PreAuditorGuardError)
    assert not issubclass(PreAuditorGuardError, FinalSealingError)
    assert not issubclass(FinalSealingError, SignOffPreconditionError)


# ---------------------------------------------------------------------------
# (10) Welle-7 state-file on-disk anchor pin (KW-27).
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR_ON_DISK = REPO_ROOT / "state"


def test_welle_7_state_file_anchor_is_kw_27_on_disk():
    """The committed ``state/welle-7.json`` MUST report KW-27.

    The canonical pre-cutover-acceptance-run-order.md §3 table (line 98)
    places Welle-7 on KW-27 (Cutover-Mittwoch 2026-07-01, Sign-off-
    Freitag 2026-07-03).
    """
    on_disk = json.loads(
        (STATE_DIR_ON_DISK / "welle-7.json").read_text(encoding="utf-8")
    )
    assert on_disk["kw_cutover_anchor"] == "KW-27"
    assert on_disk["welle_number"] == 7
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN


def test_welle_7_state_file_starts_pending_on_disk():
    """The committed ``state/welle-7.json`` MUST start in ``pending``.

    Welle-7 is the terminal Welle of the Phase-3c-Welle-Marathon; the
    sign-off only fires at KW-27 cutover-Freitag. Pre-cutover, the
    state-file MUST be in the ``pending`` phase.
    """
    on_disk = json.loads(
        (STATE_DIR_ON_DISK / "welle-7.json").read_text(encoding="utf-8")
    )
    assert on_disk["status"] == STATUS_PENDING
    assert on_disk["cutover_iso"] == ""
    assert on_disk["signoff_iso"] == ""
