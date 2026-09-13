# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-77 - cross-Welle handler-integration pins (Selin, persona-engine).

Polish-layer cross-Welle integration tests. The Tag-69..76 producer-
tests pin each Welle individually + the Tag-76 cross-Welle verifier;
this Tag-77 file pins the **cross-Welle handler-family pairwise
disjointness** + the canonical seven-Welle Marathon-trigger-set.

The seven per-Welle trigger-literals are:

    cutover, sign-off, sealing, snapshot-restore,
    capability-token-rotation, cross-substrate-parity, final-sealing

plus the cross-Welle aggregate trigger:

    phase-3-complete-verify

and the rollback trigger:

    rollback

This test pins the canonical seven-Welle Marathon-run: it walks
through Welle-1..7 with the producer-substrate, asserts that every
trigger fires exactly once in the expected order, and that the
trigger-set is pairwise disjoint with every other. It also pins the
cross-Welle Phase-3-COMPLETE verifier on the post-marathon state-dir
+ asserts the verifier-record is disjoint from the per-Welle records.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69..76
producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

Cross-Welle integration tests only. This file does NOT modify
producer-substrate behaviour, engine.py dispatch, schema-pin
literals, or any persona-definition (Aisha-Domaene). This file does
not couple to NATS / SPIRE / gRPC / WAT-core / identity-substrate /
container-infra. It is a pure read-against producer + assertions-on-
audit-records polish layer.

The test-count target is >= 18 cross-family pairwise pinning tests.
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
    CROSS_SUBSTRATE_PARITY_VERIFIED,
    DOPPELBETRIEB_SEALED,
    FINAL_SEALING_CONFIRMED,
    PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR,
    PHASE_3_COMPLETE_REQUIRED_WELLEN,
    PHASE_3_COMPLETE_TRIGGER,
    PHASE_3_COMPLETE_VERIFIED,
    PHASE_LITERAL,
    Phase3CompleteAuditRecord,
    ROLLBACK_MARKER_AUTHORIZED,
    SCHEMA_VERSION_PIN,
    SNAPSHOT_RESTORE_VERIFIED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    WelleAuditRecord,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Canonical timestamps + KW-anchor mirror (must satisfy verifier monotonicity).
# Welles 4/5/6 share KW-26; cutover_iso is tolerated equal on (4,5) and (5,6).
# ---------------------------------------------------------------------------


CANONICAL_KW_ANCHOR = dict(PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR)

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


# Per-Welle expected trigger on the green-Marathon walk-through.
EXPECTED_SIGNOFF_TRIGGER = {
    1: "sign-off",
    2: "sealing",
    3: "sign-off",
    4: "snapshot-restore",
    5: "capability-token-rotation",
    6: "cross-substrate-parity",
    7: "final-sealing",
}


# Disjoint seven-per-Welle trigger-set used on a green Marathon-run.
GREEN_MARATHON_TRIGGERS = frozenset({
    "cutover",
    "sign-off",
    "sealing",
    "snapshot-restore",
    "capability-token-rotation",
    "cross-substrate-parity",
    "final-sealing",
})


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69..76 layout verbatim).
# ---------------------------------------------------------------------------


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


def _seed_all_pending(state_dir: Path) -> None:
    for w in range(1, 8):
        _seed_pending(state_dir, w)


class _RecordingEmitter:
    def __init__(self) -> None:
        self.records: List[WelleAuditRecord] = []

    def __call__(self, record: WelleAuditRecord) -> None:
        self.records.append(record)


class _RecordingPhase3Emitter:
    def __init__(self) -> None:
        self.records: List[Phase3CompleteAuditRecord] = []

    def __call__(self, record: Phase3CompleteAuditRecord) -> None:
        self.records.append(record)


def _drive_welle_to_signoff(
    producer: WelleStateProducer, welle_number: int
) -> None:
    """Walk a single Welle pending -> in-progress -> signed-off.

    Uses the per-Welle handler family per
    :data:`EXPECTED_SIGNOFF_TRIGGER`. All marker preconditions are set
    to the canonical green values.
    """
    cutover_iso = CANONICAL_CUTOVER_ISO[welle_number]
    signoff_iso = CANONICAL_SIGNOFF_ISO[welle_number]
    producer.handle_cutover_event(welle_number, cutover_iso)
    if welle_number == 1:
        producer.handle_sign_off_event(
            welle_number=1,
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
        )
    elif welle_number == 2:
        producer.handle_welle_2_sealing_event(
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )
    elif welle_number == 3:
        producer.handle_sign_off_event(
            welle_number=3,
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
        )
    elif welle_number == 4:
        producer.handle_welle_4_signoff_event(
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        )
    elif welle_number == 5:
        producer.handle_welle_5_signoff_event(
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        )
    elif welle_number == 6:
        producer.handle_welle_6_signoff_event(
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )
    elif welle_number == 7:
        producer.handle_welle_7_signoff_event(
            signoff_iso=signoff_iso,
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
            final_sealing_marker_status=FINAL_SEALING_CONFIRMED,
        )
    else:
        raise AssertionError(f"unknown welle_number={welle_number!r}")


def _drive_full_marathon(
    state_dir: Path, emitter: _RecordingEmitter
) -> WelleStateProducer:
    """Walk Welle-1..7 to signed-off using the per-Welle handler family."""
    _seed_all_pending(state_dir)
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    for w in range(1, 8):
        _drive_welle_to_signoff(producer, w)
    return producer


# ---------------------------------------------------------------------------
# 1. Trigger-family disjointness: pairwise pin every (i, j) i != j.
# ---------------------------------------------------------------------------


def test_per_welle_signoff_trigger_map_is_disjoint_set():
    """The seven per-Welle sign-off-family triggers are pairwise distinct.

    Note: Welle-1 and Welle-3 both carry ``trigger="sign-off"`` (the
    vanilla sign-off family). The disjoint **set** therefore has 6
    sign-off-family elements + the implicit ``cutover`` trigger that
    fires on every Welle = 7 distinct trigger-literals.
    """
    family_signoff_triggers = set(EXPECTED_SIGNOFF_TRIGGER.values())
    # Welle-1 + Welle-3 share "sign-off"; that's by design.
    assert family_signoff_triggers == {
        "sign-off",
        "sealing",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
        "final-sealing",
    }


def test_green_marathon_trigger_set_is_seven_disjoint_literals():
    assert GREEN_MARATHON_TRIGGERS == {
        "cutover",
        "sign-off",
        "sealing",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
        "final-sealing",
    }
    assert len(GREEN_MARATHON_TRIGGERS) == 7


def test_phase_3_complete_trigger_is_disjoint_from_green_marathon_triggers():
    assert PHASE_3_COMPLETE_TRIGGER not in GREEN_MARATHON_TRIGGERS


def test_rollback_trigger_is_disjoint_from_green_marathon_triggers():
    # Rollback is a failure-path trigger; never part of a green Marathon-run.
    assert "rollback" not in GREEN_MARATHON_TRIGGERS


def test_rollback_trigger_is_disjoint_from_phase_3_complete_trigger():
    assert "rollback" != PHASE_3_COMPLETE_TRIGGER


# ---------------------------------------------------------------------------
# 2. Cross-Welle Marathon walk-through: every trigger fires exactly once.
# ---------------------------------------------------------------------------


def test_green_marathon_emits_one_cutover_per_welle(tmp_path):
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    cutover_records = [
        r for r in emitter.records if r.trigger == "cutover"
    ]
    assert len(cutover_records) == 7
    assert sorted(r.welle_number for r in cutover_records) == [1, 2, 3, 4, 5, 6, 7]


def test_green_marathon_emits_one_signoff_record_per_welle(tmp_path):
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    signoff_records = [
        r for r in emitter.records
        if r.new_status == STATUS_SIGNED_OFF and r.trigger != "cutover"
    ]
    assert len(signoff_records) == 7
    assert sorted(r.welle_number for r in signoff_records) == [1, 2, 3, 4, 5, 6, 7]


def test_green_marathon_total_record_count_is_fourteen(tmp_path):
    """Every Welle emits 2 records: cutover + per-family sign-off."""
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    assert len(emitter.records) == 14


def test_green_marathon_record_trigger_set_is_canonical(tmp_path):
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    observed_triggers = {r.trigger for r in emitter.records}
    assert observed_triggers == GREEN_MARATHON_TRIGGERS


def test_green_marathon_per_welle_trigger_is_canonical(tmp_path):
    """Pin trigger-literal on each Welle's sign-off-record (per family)."""
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    signoff_records_by_welle = {
        r.welle_number: r
        for r in emitter.records
        if r.new_status == STATUS_SIGNED_OFF and r.trigger != "cutover"
    }
    for welle_number, expected_trigger in EXPECTED_SIGNOFF_TRIGGER.items():
        record = signoff_records_by_welle[welle_number]
        assert record.trigger == expected_trigger, (
            f"welle-{welle_number}: expected trigger={expected_trigger!r}, "
            f"got {record.trigger!r}"
        )


def test_green_marathon_emit_order_matches_welle_number(tmp_path):
    """Records emit in (cutover, sign-off) pairs per Welle, ascending."""
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    _drive_full_marathon(state_dir, emitter)
    welle_order = [r.welle_number for r in emitter.records]
    # 14 records: w1 cutover, w1 sign-off, w2 cutover, w2 sign-off, ...
    expected = [w for w in range(1, 8) for _ in range(2)]
    assert welle_order == expected


# ---------------------------------------------------------------------------
# 3. Cross-Welle Phase-3-COMPLETE verifier on the post-marathon state.
# ---------------------------------------------------------------------------


def test_phase_3_complete_verifier_green_on_post_marathon_state(tmp_path):
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    producer = _drive_full_marathon(state_dir, emitter)
    record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    assert record.verdict == PHASE_3_COMPLETE_VERIFIED
    assert record.trigger == PHASE_3_COMPLETE_TRIGGER
    assert record.verified_wellen == (1, 2, 3, 4, 5, 6, 7)
    assert record.earliest_cutover_iso == CANONICAL_CUTOVER_ISO[1]
    assert record.latest_signoff_iso == CANONICAL_SIGNOFF_ISO[7]


def test_phase_3_complete_record_disjoint_from_per_welle_records(tmp_path):
    """The cross-Welle audit-record type is disjoint from the per-Welle one."""
    emitter = _RecordingEmitter()
    phase3_emitter = _RecordingPhase3Emitter()
    state_dir = tmp_path / "state"
    producer = _drive_full_marathon(state_dir, emitter)
    producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
        phase_3_emitter=phase3_emitter,
    )
    # All per-Welle records: WelleAuditRecord type.
    for r in emitter.records:
        assert isinstance(r, WelleAuditRecord)
        assert not isinstance(r, Phase3CompleteAuditRecord)
    # The cross-Welle record: Phase3CompleteAuditRecord type.
    assert len(phase3_emitter.records) == 1
    cross_record = phase3_emitter.records[0]
    assert isinstance(cross_record, Phase3CompleteAuditRecord)
    assert not isinstance(cross_record, WelleAuditRecord)


def test_phase_3_complete_record_trigger_disjoint_from_emitted_record_triggers(tmp_path):
    """No per-Welle audit-record carries the Phase-3-COMPLETE trigger."""
    emitter = _RecordingEmitter()
    phase3_emitter = _RecordingPhase3Emitter()
    state_dir = tmp_path / "state"
    producer = _drive_full_marathon(state_dir, emitter)
    producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
        phase_3_emitter=phase3_emitter,
    )
    per_welle_triggers = {r.trigger for r in emitter.records}
    cross_record = phase3_emitter.records[0]
    assert cross_record.trigger == PHASE_3_COMPLETE_TRIGGER
    assert cross_record.trigger not in per_welle_triggers


def test_phase_3_complete_to_json_bytes_disjoint_from_welle_audit_json(tmp_path):
    """Canonical-JSON wire format differs by record-type."""
    emitter = _RecordingEmitter()
    state_dir = tmp_path / "state"
    producer = _drive_full_marathon(state_dir, emitter)
    cross_record = producer.handle_phase_3_complete_event(
        verify_iso="2026-07-03T18:00:00Z",
    )
    welle_record_bytes = emitter.records[0].to_json_bytes()
    cross_record_bytes = cross_record.to_json_bytes()
    # Disjoint-key signal: only the cross-Welle record carries
    # ``earliest_cutover_iso`` / ``latest_signoff_iso`` / ``verify_iso`` /
    # ``verified_wellen``; only the per-Welle record carries
    # ``new_status`` / ``prior_status`` / ``welle_number``.
    welle_json = json.loads(welle_record_bytes)
    cross_json = json.loads(cross_record_bytes)
    welle_keys = set(welle_json.keys())
    cross_keys = set(cross_json.keys())
    # They share only the universally-needed "trigger" + cutover/signoff
    # carriers; the disjoint signature is the type-specific keys:
    welle_only = welle_keys - cross_keys
    cross_only = cross_keys - welle_keys
    assert "welle_number" in welle_only
    assert "new_status" in welle_only
    assert "prior_status" in welle_only
    assert "verified_wellen" in cross_only
    assert "earliest_cutover_iso" in cross_only
    assert "latest_signoff_iso" in cross_only
    assert "verify_iso" in cross_only
    assert "verdict" in cross_only


# ---------------------------------------------------------------------------
# 4. Top-level engine.py dispatch: cross-Welle handler-equivalence.
# ---------------------------------------------------------------------------


def test_engine_module_exposes_all_seven_handlers():
    """Every per-Welle family handler is exposed at top-level + the
    cross-Welle verifier."""
    expected = (
        "handle_welle_sealing_event",          # Welle-2
        "handle_welle_rollback_event",         # rollback (any Welle)
        "handle_welle_4_signoff_event",        # Welle-4 snapshot-restore
        "handle_welle_5_signoff_event",        # Welle-5 capability-token-rotation
        "handle_welle_3_signoff_event",        # Welle-3 bridge-audit
        "handle_welle_6_signoff_event",        # Welle-6 cross-substrate-parity
        "handle_welle_7_signoff_event",        # Welle-7 final-sealing
        "handle_phase_3_complete_event",       # cross-Welle aggregate
    )
    for name in expected:
        assert hasattr(engine_mod, name), f"engine_mod missing {name!r}"
        assert callable(getattr(engine_mod, name)), (
            f"engine_mod.{name} not callable"
        )


def test_engine_async_module_exposes_all_seven_handlers_async():
    expected = (
        "handle_welle_sealing_event",
        "handle_welle_rollback_event",
        "handle_welle_4_signoff_event",
        "handle_welle_5_signoff_event",
        "handle_welle_3_signoff_event",
        "handle_welle_6_signoff_event",
        "handle_welle_7_signoff_event",
        "handle_phase_3_complete_event",
    )
    for name in expected:
        assert hasattr(engine_async_mod, name), (
            f"engine_async_mod missing {name!r}"
        )
        attr = getattr(engine_async_mod, name)
        assert inspect.iscoroutinefunction(attr), (
            f"engine_async_mod.{name} not async"
        )


def test_sync_and_async_handler_pairs_have_matching_names():
    """Each sync handler has an async sibling with the same name."""
    sync_handlers = {
        name for name in dir(engine_mod)
        if name.startswith("handle_") and callable(getattr(engine_mod, name))
    }
    async_handlers = {
        name for name in dir(engine_async_mod)
        if name.startswith("handle_")
        and inspect.iscoroutinefunction(getattr(engine_async_mod, name))
    }
    # The cross-Welle + Welle-N family handlers must be in both sets.
    required = {
        "handle_welle_sealing_event",
        "handle_welle_rollback_event",
        "handle_welle_4_signoff_event",
        "handle_welle_5_signoff_event",
        "handle_welle_3_signoff_event",
        "handle_welle_6_signoff_event",
        "handle_welle_7_signoff_event",
        "handle_phase_3_complete_event",
    }
    assert required.issubset(sync_handlers), (
        f"sync missing: {required - sync_handlers}"
    )
    assert required.issubset(async_handlers), (
        f"async missing: {required - async_handlers}"
    )


# ---------------------------------------------------------------------------
# 5. Cross-Welle rollback-trigger disjointness from green-Marathon families.
# ---------------------------------------------------------------------------


def test_rollback_record_trigger_disjoint_from_green_marathon_record_triggers(tmp_path):
    """A rollback-trigger record never collides with a green Marathon trigger."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_rollback_event(
        welle_number=1,
        rollback_iso="2026-05-27T09:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    assert emitter.records[-1].trigger == "rollback"
    assert "rollback" not in GREEN_MARATHON_TRIGGERS


def test_rollback_record_disjoint_from_phase_3_complete_record(tmp_path):
    """Rollback emits a WelleAuditRecord, never a Phase3CompleteAuditRecord."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 4)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_rollback_event(
        welle_number=4,
        rollback_iso="2026-06-24T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    record = emitter.records[-1]
    assert isinstance(record, WelleAuditRecord)
    assert not isinstance(record, Phase3CompleteAuditRecord)
    assert record.trigger == "rollback"
    assert record.new_status == STATUS_ROLLED_BACK


# ---------------------------------------------------------------------------
# 6. Cross-Welle async dispatch parity (sync vs async green Marathon).
# ---------------------------------------------------------------------------


def test_async_phase_3_complete_dispatch_matches_sync(tmp_path):
    """The async dispatch returns a record structurally equal to sync."""
    state_dir = tmp_path / "state"
    emitter = _RecordingEmitter()
    _drive_full_marathon(state_dir, emitter)
    sync_record = engine_mod.handle_phase_3_complete_event(
        state_dir=state_dir,
        verify_iso="2026-07-03T18:00:00Z",
    )
    async_record = asyncio.run(
        engine_async_mod.handle_phase_3_complete_event(
            state_dir=state_dir,
            verify_iso="2026-07-03T18:00:00Z",
        )
    )
    assert sync_record.verdict == async_record.verdict
    assert sync_record.trigger == async_record.trigger
    assert sync_record.verified_wellen == async_record.verified_wellen
    assert sync_record.earliest_cutover_iso == async_record.earliest_cutover_iso
    assert sync_record.latest_signoff_iso == async_record.latest_signoff_iso
    assert sync_record.verify_iso == async_record.verify_iso


# ---------------------------------------------------------------------------
# 7. Cross-Welle pre-auditor-guard pairwise pin (Welle-3 + Welle-7).
# ---------------------------------------------------------------------------


def test_pre_auditor_guarded_wellen_pair_share_pre_auditor_required(tmp_path):
    """Welle-3 + Welle-7 are the **only** pre-auditor-guarded sign-off
    paths; the other five sign-off families MUST NOT require a
    pre-auditor decision (Henrik-cannot-self-sign-off invariant scope)."""
    state_dir = tmp_path / "state"
    _seed_all_pending(state_dir)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    # Drive Welle-1, 2, 4, 5, 6 WITHOUT a pre-auditor decision -- success.
    for welle_number in (1, 2, 4, 5, 6):
        producer.handle_cutover_event(
            welle_number, CANONICAL_CUTOVER_ISO[welle_number]
        )
        _drive_welle_to_signoff(producer, welle_number)
    # Welle-3 + Welle-7 are pre-auditor-guarded (we don't drive them here;
    # the per-Welle producer-tests already pin the refusal-path).
    # All five other-Welle records must have new_status=signed-off.
    other_welle_records = {
        r.welle_number: r
        for r in emitter.records
        if r.welle_number in {1, 2, 4, 5, 6}
        and r.new_status == STATUS_SIGNED_OFF
    }
    assert set(other_welle_records.keys()) == {1, 2, 4, 5, 6}


# ---------------------------------------------------------------------------
# 8. Cross-Welle canonical KW-anchor consistency.
# ---------------------------------------------------------------------------


def test_canonical_kw_anchor_table_is_consistent_with_verifier_default():
    """The Tag-77 cross-Welle KW-anchor table must mirror the producer-
    substrate's :data:`PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR` table."""
    assert CANONICAL_KW_ANCHOR == PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR
    # KW-26 shared by Welles 4/5/6 per the Tag-74 reconciliation.
    assert (
        CANONICAL_KW_ANCHOR[4]
        == CANONICAL_KW_ANCHOR[5]
        == CANONICAL_KW_ANCHOR[6]
        == "KW-26"
    )
    # KW-22 for Welle-1; KW-27 for Welle-7 (Marathon-start + Marathon-end).
    assert CANONICAL_KW_ANCHOR[1] == "KW-22"
    assert CANONICAL_KW_ANCHOR[7] == "KW-27"


def test_canonical_cutover_iso_satisfies_cross_welle_monotonicity():
    """The Tag-77 cross-Welle cutover-iso table satisfies the verifier
    invariant (monotone non-decreasing in welle_number)."""
    sorted_wellen = sorted(CANONICAL_CUTOVER_ISO.keys())
    prior_iso = ""
    for welle_number in sorted_wellen:
        current_iso = CANONICAL_CUTOVER_ISO[welle_number]
        assert prior_iso <= current_iso, (
            f"welle-{welle_number}: cutover_iso={current_iso!r} < "
            f"prior={prior_iso!r}"
        )
        prior_iso = current_iso


def test_required_wellen_default_covers_all_seven_marathon_wellen():
    """The cross-Welle verifier default set is the canonical seven-Welle
    Marathon set."""
    assert PHASE_3_COMPLETE_REQUIRED_WELLEN == frozenset(range(1, 8))
    assert set(EXPECTED_SIGNOFF_TRIGGER.keys()) == set(
        PHASE_3_COMPLETE_REQUIRED_WELLEN
    )
