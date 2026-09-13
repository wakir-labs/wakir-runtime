# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-76 - Welle-1..7 Production-Bringup-Verifier (Selin, persona-engine).

Tag-75 (PR #475) shipped Welle-7 producer-path (the **terminal** Welle
of the Phase-3c-Welle-Marathon). The producer-substrate now covers all
six per-Welle marker-families (cutover, sealing, snapshot-restore,
capability-token-rotation, cross-substrate-parity, final-sealing) plus
the disjoint pre-auditor-guard axis on Welle-3/7.

Tag-76 (this PR) adds the **cross-Welle Production-Bringup-Verifier**
(the seventh disjoint trigger-family in the audit-stream,
``trigger="phase-3-complete-verify"``):

* ``WelleStateProducer.handle_phase_3_complete_event`` -- read-only
  cross-Welle aggregate verifier. Checks that all required Wellen
  (default ``{1, 2, 3, 4, 5, 6, 7}``) are in canonical signed-off
  State with non-empty ``cutover_iso`` and ``signoff_iso``, and that
  cross-Welle ``cutover_iso`` ordering is monotone non-decreasing in
  welle_number. On green: emits a :class:`Phase3CompleteAuditRecord`
  (cross-Welle aggregate; disjoint from :class:`WelleAuditRecord`).
  On red: raises :class:`Phase3CompleteVerifierError`.

* ``wirelang.persona_engine.engine.handle_phase_3_complete_event`` --
  top-level sync handler.

* ``wirelang.persona_engine.engine_async.handle_phase_3_complete_event``
  -- async wrapper (default-loop thread-pool executor).

The verifier is the **engine-side gate-input** for the downstream
``PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7`` marker emission (per
``docs/quality-gates/phase-3c-doppel-welle-6-7.md`` §4.1). The marker
emission itself is audit-trail-consumer-territory (Henrik Internal
Audit Zone-N), NOT this verifier's responsibility.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69..75
producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), Phase-3-COMPLETE-
marker emission (audit-trail-consumer territory; this test pins the
engine-side verifier-record only), or container-infra (Kai-Domaene,
Zone-J). It pins the Tag-76 cross-Welle verifier shorthand.
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
    InvalidWelleNumberError,
    PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR,
    PHASE_3_COMPLETE_REQUIRED_WELLEN,
    PHASE_3_COMPLETE_TRIGGER,
    PHASE_3_COMPLETE_VERIFIED,
    PHASE_LITERAL,
    Phase3CompleteAuditRecord,
    Phase3CompleteVerifierError,
    SCHEMA_VERSION_PIN,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    StateFileShapeError,
    TimeInvariantViolationError,
    VALID_WELLE_NUMBERS,
    WelleProducerError,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69..75 layout).
# ---------------------------------------------------------------------------


CANONICAL_KW_ANCHOR = {
    1: "KW-22",
    2: "KW-23",
    3: "KW-25",
    4: "KW-26",
    5: "KW-26",
    6: "KW-26",
    7: "KW-27",
}


# Canonical post-cutover-sign-off ISO timestamps per Welle. Monotone
# non-decreasing in welle_number to satisfy the verifier invariant.
CANONICAL_CUTOVER_ISO = {
    1: "2026-05-27T08:00:00Z",
    2: "2026-06-03T08:00:00Z",
    3: "2026-06-17T08:00:00Z",
    4: "2026-06-24T08:00:00Z",
    5: "2026-06-24T08:30:00Z",
    6: "2026-06-24T09:00:00Z",
    7: "2026-07-01T08:00:00Z",
}
CANONICAL_SIGNOFF_ISO = {
    1: "2026-05-29T17:00:00Z",
    2: "2026-06-05T17:00:00Z",
    3: "2026-06-19T17:00:00Z",
    4: "2026-06-26T17:00:00Z",
    5: "2026-06-26T17:30:00Z",
    6: "2026-06-26T18:00:00Z",
    7: "2026-07-03T17:00:00Z",
}


def _signed_off_stub(welle_number: int) -> dict:
    return {
        "welle_number": welle_number,
        "schema_version": SCHEMA_VERSION_PIN,
        "phase": PHASE_LITERAL,
        "kw_cutover_anchor": CANONICAL_KW_ANCHOR[welle_number],
        "cutover_iso": CANONICAL_CUTOVER_ISO[welle_number],
        "signoff_iso": CANONICAL_SIGNOFF_ISO[welle_number],
        "status": STATUS_SIGNED_OFF,
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


def _seed_signed_off(state_dir: Path, welle_number: int) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = _signed_off_stub(welle_number)
    path = state_dir / f"welle-{welle_number}.json"
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _seed_all_signed_off(state_dir: Path) -> None:
    for w in range(1, 8):
        _seed_signed_off(state_dir, w)


def _seed_pending(state_dir: Path, welle_number: int) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = _signed_off_stub(welle_number)
    payload["status"] = STATUS_PENDING
    payload["cutover_iso"] = ""
    payload["signoff_iso"] = ""
    path = state_dir / f"welle-{welle_number}.json"
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return path


class _RecordingPhase3Emitter:
    """Records every Phase-3-COMPLETE record (for emit-assertion)."""

    def __init__(self) -> None:
        self.records: List[Phase3CompleteAuditRecord] = []

    def __call__(self, record: Phase3CompleteAuditRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# 1. Module-shape pins.
# ---------------------------------------------------------------------------


def test_phase_3_complete_required_wellen_is_canonical_set():
    assert PHASE_3_COMPLETE_REQUIRED_WELLEN == frozenset(range(1, 8))


def test_phase_3_complete_trigger_literal_is_disjoint_constant():
    assert PHASE_3_COMPLETE_TRIGGER == "phase-3-complete-verify"
    # Disjoint from all per-Welle trigger-literals (the six marker
    # families + vanilla sign-off + cutover) by spot-check.
    disjoint_set = {
        "cutover",
        "sign-off",
        "sealing",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
        "final-sealing",
        "rollback",
    }
    assert PHASE_3_COMPLETE_TRIGGER not in disjoint_set


def test_phase_3_complete_verified_literal_is_canonical():
    assert PHASE_3_COMPLETE_VERIFIED == "phase-3-complete-verified"


def test_phase_3_complete_canonical_kw_anchor_matches_run_order_table():
    # Per pre-cutover-acceptance-run-order.md §3 table.
    assert PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR == {
        1: "KW-22",
        2: "KW-23",
        3: "KW-25",
        4: "KW-26",
        5: "KW-26",
        6: "KW-26",
        7: "KW-27",
    }


def test_engine_module_exposes_phase_3_complete_handler():
    assert hasattr(engine_mod, "handle_phase_3_complete_event")
    assert callable(engine_mod.handle_phase_3_complete_event)


def test_engine_async_module_exposes_phase_3_complete_handler():
    assert hasattr(engine_async_mod, "handle_phase_3_complete_event")
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_phase_3_complete_event
    )


def test_sync_phase_3_complete_handler_is_not_a_coroutine():
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_phase_3_complete_event
    )


def test_phase_3_complete_verifier_error_inherits_from_welle_producer_error():
    assert issubclass(Phase3CompleteVerifierError, WelleProducerError)


# ---------------------------------------------------------------------------
# 2. Happy-path: all 7 Wellen signed-off -> green verdict.
# ---------------------------------------------------------------------------


def test_verifier_happy_path_all_seven_wellen_signed_off(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert isinstance(record, Phase3CompleteAuditRecord)
    assert record.verdict == PHASE_3_COMPLETE_VERIFIED
    assert record.trigger == PHASE_3_COMPLETE_TRIGGER
    assert record.verified_wellen == (1, 2, 3, 4, 5, 6, 7)
    assert record.earliest_cutover_iso == CANONICAL_CUTOVER_ISO[1]
    assert record.latest_signoff_iso == CANONICAL_SIGNOFF_ISO[7]
    assert record.verify_iso == "2026-07-03T18:00:00Z"


def test_verifier_emitter_recorded_on_green(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    emitter = _RecordingPhase3Emitter()
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
        phase_3_emitter=emitter,
    )
    assert len(emitter.records) == 1
    assert emitter.records[0] is record


def test_verifier_idempotent_double_call(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    producer = WelleStateProducer(state_dir=state_dir)
    r1 = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    r2 = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert r1 == r2
    # On-disk state is unchanged (read-only).
    on_disk_7 = json.loads(
        (state_dir / "welle-7.json").read_text(encoding="utf-8")
    )
    assert on_disk_7["status"] == STATUS_SIGNED_OFF


def test_verifier_canonical_json_bytes(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    blob = record.to_json_bytes()
    # Round-trip + canonical ordering check.
    parsed = json.loads(blob.decode("utf-8"))
    assert parsed["verdict"] == PHASE_3_COMPLETE_VERIFIED
    assert parsed["trigger"] == PHASE_3_COMPLETE_TRIGGER
    assert parsed["verified_wellen"] == [1, 2, 3, 4, 5, 6, 7]
    # Keys must be sorted alphabetically in canonical form.
    assert list(parsed.keys()) == sorted(parsed.keys())


# ---------------------------------------------------------------------------
# 3. Red verdicts: per-Welle preconditions.
# ---------------------------------------------------------------------------


def test_verifier_refuses_when_welle_pending(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    # Overwrite welle-4 to pending.
    _seed_pending(state_dir, 4)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "welle-4" in str(exc_info.value)
    assert "not signed-off" in str(exc_info.value)


def test_verifier_refuses_when_welle_in_progress(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    payload = _signed_off_stub(6)
    payload["status"] = STATUS_IN_PROGRESS
    payload["signoff_iso"] = ""
    (state_dir / "welle-6.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "welle-6" in str(exc_info.value)


def test_verifier_refuses_when_welle_rolled_back(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    payload = _signed_off_stub(2)
    payload["status"] = STATUS_ROLLED_BACK
    (state_dir / "welle-2.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "welle-2" in str(exc_info.value)
    assert "rolled-back" in str(exc_info.value)


def test_verifier_refuses_when_signed_off_but_cutover_iso_empty(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    payload = _signed_off_stub(3)
    payload["cutover_iso"] = ""
    (state_dir / "welle-3.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "welle-3" in str(exc_info.value)
    assert "cutover_iso" in str(exc_info.value)


def test_verifier_refuses_when_signed_off_but_signoff_iso_empty(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    payload = _signed_off_stub(5)
    payload["signoff_iso"] = ""
    (state_dir / "welle-5.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "welle-5" in str(exc_info.value)
    assert "signoff_iso" in str(exc_info.value)


def test_verifier_refuses_when_state_file_missing(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    (state_dir / "welle-7.json").unlink()
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises((StateFileShapeError, FileNotFoundError, OSError)):
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )


# ---------------------------------------------------------------------------
# 4. Red verdicts: cross-Welle invariants.
# ---------------------------------------------------------------------------


def test_verifier_refuses_when_cross_welle_cutover_non_monotone(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    # Corrupt: Welle-3 cutover BEFORE Welle-1 cutover -> monotonicity
    # violation between welle-1 and welle-2 (welle-2 ends up earlier
    # than welle-1's cutover).
    payload = _signed_off_stub(2)
    payload["cutover_iso"] = "2026-05-01T08:00:00Z"
    (state_dir / "welle-2.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError) as exc_info:
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
        )
    assert "monotonicity" in str(exc_info.value)


def test_verifier_tolerates_equal_cutover_iso_between_welles_4_5_6(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    # Welle-4/5/6 share KW-26 per canonical run-order; equal cutover_iso
    # MUST be tolerated (monotonicity is <=, not <).
    shared_cutover = "2026-06-24T08:00:00Z"
    for w in (4, 5, 6):
        payload = _signed_off_stub(w)
        payload["cutover_iso"] = shared_cutover
        (state_dir / f"welle-{w}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert record.verdict == PHASE_3_COMPLETE_VERIFIED


# ---------------------------------------------------------------------------
# 5. Parametric: required_wellen subset.
# ---------------------------------------------------------------------------


def test_verifier_parametric_subset_of_wellen(tmp_path):
    state_dir = tmp_path / "state"
    # Seed only welles 1, 2, 3 signed-off.
    for w in (1, 2, 3):
        _seed_signed_off(state_dir, w)
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-06-19T18:00:00Z",
        required_wellen=frozenset({1, 2, 3}),
    )
    assert record.verified_wellen == (1, 2, 3)
    assert record.earliest_cutover_iso == CANONICAL_CUTOVER_ISO[1]
    assert record.latest_signoff_iso == CANONICAL_SIGNOFF_ISO[3]


def test_verifier_refuses_empty_required_wellen(tmp_path):
    state_dir = tmp_path / "state"
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(Phase3CompleteVerifierError):
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
            required_wellen=frozenset(),
        )


def test_verifier_refuses_invalid_welle_number_in_required_set(tmp_path):
    state_dir = tmp_path / "state"
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidWelleNumberError):
        producer.handle_phase_3_complete_event(
            verify_iso="2026-07-03T18:00:00Z",
            required_wellen=frozenset({0, 1, 2}),
        )


def test_verifier_refuses_invalid_verify_iso(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_phase_3_complete_event(
            verify_iso="not-an-iso-timestamp",
        )


# ---------------------------------------------------------------------------
# 6. Top-level sync handler (engine.handle_phase_3_complete_event).
# ---------------------------------------------------------------------------


def test_sync_handle_phase_3_complete_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    record = engine_mod.handle_phase_3_complete_event(
        state_dir=state_dir,
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert isinstance(record, Phase3CompleteAuditRecord)
    assert record.verdict == PHASE_3_COMPLETE_VERIFIED
    assert record.verified_wellen == (1, 2, 3, 4, 5, 6, 7)


def test_sync_handle_phase_3_complete_event_emitter_recorded(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    emitter = _RecordingPhase3Emitter()
    record = engine_mod.handle_phase_3_complete_event(
        state_dir=state_dir,
        verify_iso="2026-07-03T18:00:00Z",
        phase_3_emitter=emitter,
    )
    assert len(emitter.records) == 1
    assert emitter.records[0].verdict == PHASE_3_COMPLETE_VERIFIED
    assert emitter.records[0] is record


def test_sync_handle_phase_3_complete_event_refuses_on_pending_welle(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    _seed_pending(state_dir, 1)
    with pytest.raises(Phase3CompleteVerifierError):
        engine_mod.handle_phase_3_complete_event(
            state_dir=state_dir,
            verify_iso="2026-07-03T18:00:00Z",
        )


# ---------------------------------------------------------------------------
# 7. Top-level async handler.
# ---------------------------------------------------------------------------


def test_async_handle_phase_3_complete_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)

    async def _run() -> Phase3CompleteAuditRecord:
        return await engine_async_mod.handle_phase_3_complete_event(
            state_dir=state_dir,
            verify_iso="2026-07-03T18:00:00Z",
        )

    record = asyncio.run(_run())
    assert isinstance(record, Phase3CompleteAuditRecord)
    assert record.verdict == PHASE_3_COMPLETE_VERIFIED
    assert record.verified_wellen == (1, 2, 3, 4, 5, 6, 7)


def test_async_handle_phase_3_complete_event_refuses_on_red(tmp_path):
    state_dir = tmp_path / "state"
    _seed_all_signed_off(state_dir)
    _seed_pending(state_dir, 7)

    async def _run() -> None:
        await engine_async_mod.handle_phase_3_complete_event(
            state_dir=state_dir,
            verify_iso="2026-07-03T18:00:00Z",
        )

    with pytest.raises(Phase3CompleteVerifierError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 8. Disjointness pins (the seventh trigger-family is disjoint).
# ---------------------------------------------------------------------------


def test_phase_3_complete_record_disjoint_from_welle_audit_record_by_trigger():
    """The cross-Welle aggregate record is distinguished from single-Welle
    records by trigger-literal."""
    record = Phase3CompleteAuditRecord(
        verdict=PHASE_3_COMPLETE_VERIFIED,
        verified_wellen=(1, 2, 3, 4, 5, 6, 7),
        earliest_cutover_iso=CANONICAL_CUTOVER_ISO[1],
        latest_signoff_iso=CANONICAL_SIGNOFF_ISO[7],
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert record.trigger == PHASE_3_COMPLETE_TRIGGER
    # The trigger is the seventh disjoint trigger-family. Spot-check
    # disjointness vs all six per-Welle marker-family trigger-literals.
    per_welle_triggers = {
        "cutover",
        "sign-off",
        "sealing",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
        "final-sealing",
        "rollback",
    }
    assert record.trigger not in per_welle_triggers


def test_phase_3_complete_required_set_covers_all_seven_marathon_wellen():
    # The canonical required-set is exactly the marathon-set.
    assert PHASE_3_COMPLETE_REQUIRED_WELLEN == VALID_WELLE_NUMBERS
    assert len(PHASE_3_COMPLETE_REQUIRED_WELLEN) == 7
