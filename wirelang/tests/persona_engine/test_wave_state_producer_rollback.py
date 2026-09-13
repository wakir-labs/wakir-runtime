# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-70 - Welle-2 Doppelbetrieb-Sealing + Rollback-Writer (Selin).

Tag-69 (PR #438) shipped the Welle-1 producer-path
(``handle_cutover_event``, ``handle_sign_off_event``). Tag-70
extends the producer-substrate with:

* **Welle-2 Doppelbetrieb-Sealing** sign-off variant
  (``handle_welle_2_sealing_event``) per plan-doc §2.3 -- the
  KW-24 Mi legacy-vs-new dual-write window closure. Welle-2
  sign-off additionally requires the
  ``doppelbetrieb_sealed_marker_status == "sealed"`` precondition
  (refusal-to-write otherwise).
* **Rollback-Writer** (``handle_rollback_event``) per plan-doc §2.4
  / §3.1 -- covers ``pending -> rolled-back``, ``in-progress ->
  rolled-back``, ``signed-off -> rolled-back``. Authorised only
  by ``rollback_marker_status == "rollback-authorized"``.
  Terminal: ``rolled-back -> *`` rejected via the lifecycle-state-
  machine's existing forbidden-transition guard.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure
in-process file I/O against ``tmp_path`` fixtures. The producer-
substrate is stdlib-only.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J). It pins the Tag-70 add-on
producer-substrate (persona-engine domain, Selin) and reuses the
Tag-67 schema-pin verbatim (no schema changes).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from wirelang.persona_engine.welle_state_producer import (
    ALLOWED_TRANSITIONS,
    DOPPELBETRIEB_SEALED,
    DOPPELBETRIEB_SEALED_WELLEN,
    DoppelbetriebSealingError,
    InvalidStatusTransitionError,
    InvalidWelleNumberError,
    PHASE_LITERAL,
    ROLLBACK_MARKER_AUTHORIZED,
    RollbackAuthorityError,
    SCHEMA_VERSION_PIN,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    SignOffPreconditionError,
    TimeInvariantViolationError,
    WelleAuditRecord,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror tag-69 layout; Welle-N parametric stubs).
# ---------------------------------------------------------------------------


CANONICAL_KW_ANCHOR = {
    1: "KW-22",
    2: "KW-23",
    3: "KW-25",
    4: "KW-25",
    5: "KW-25",
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


class _RecordingEmitter:
    def __init__(self) -> None:
        self.records: List[WelleAuditRecord] = []

    def __call__(self, record: WelleAuditRecord) -> None:
        self.records.append(record)


# ---------------------------------------------------------------------------
# Public-API surface invariants (Tag-70 add-ons).
# ---------------------------------------------------------------------------


def test_tag70_module_exposes_new_public_constants():
    """Tag-70 adds three new public literals."""
    assert ROLLBACK_MARKER_AUTHORIZED == "rollback-authorized"
    assert DOPPELBETRIEB_SEALED == "sealed"
    assert DOPPELBETRIEB_SEALED_WELLEN == frozenset({2})


def test_tag70_allowed_transitions_unchanged_from_tag69():
    """Tag-70 must NOT silently extend the lifecycle-state-machine.

    Rollback already had its three transitions in
    ALLOWED_TRANSITIONS (Tag-69). Tag-70 only adds *handlers*,
    not new transitions.
    """
    assert ALLOWED_TRANSITIONS == frozenset(
        {
            (STATUS_PENDING, STATUS_IN_PROGRESS),
            (STATUS_PENDING, STATUS_ROLLED_BACK),
            (STATUS_IN_PROGRESS, STATUS_SIGNED_OFF),
            (STATUS_IN_PROGRESS, STATUS_ROLLED_BACK),
            (STATUS_SIGNED_OFF, STATUS_ROLLED_BACK),
        }
    )


# ---------------------------------------------------------------------------
# Welle-2 Doppelbetrieb-Sealing sign-off (plan-doc §2.3).
# ---------------------------------------------------------------------------


def test_welle_2_sealing_transitions_in_progress_to_signed_off(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 2)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)

    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    record = producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["cutover_iso"] == "2026-06-10T08:00:00Z"
    assert on_disk["signoff_iso"] == "2026-06-10T14:30:00Z"
    assert on_disk["welle_number"] == 2
    assert on_disk["kw_cutover_anchor"] == "KW-23"

    assert record.welle_number == 2
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "sealing"
    # Two emissions: cutover then sealing.
    assert [r.trigger for r in emitter.records] == ["cutover", "sealing"]


def test_welle_2_sealing_refused_without_sealed_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    with pytest.raises(DoppelbetriebSealingError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status="not-sealed",
        )


def test_welle_2_sealing_refused_without_sign_off_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    with pytest.raises(SignOffPreconditionError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_PENDING,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_welle_2_sealing_is_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    first_bytes = target.read_bytes()
    record = producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "sealing"


def test_welle_2_sealing_refused_with_bad_iso(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10",  # not RFC 3339 second-precision
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_welle_2_sealing_refused_on_signoff_before_cutover(tmp_path):
    """Plan-doc §3.4 time-invariant: cutover_iso <= signoff_iso."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T14:00:00Z"
    )
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10T08:00:00Z",  # before cutover
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_welle_2_sealing_refused_when_status_still_pending(tmp_path):
    """No cutover first => sign-off path refused (forbidden transition)."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


# ---------------------------------------------------------------------------
# Rollback-Writer (plan-doc §2.4 / §3.1).
# ---------------------------------------------------------------------------


def test_rollback_pending_to_rolled_back(tmp_path):
    """Plan-doc §3.1: pending -> rolled-back (pre-cutover rollback)."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 3)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)

    record = producer.handle_rollback_event(
        welle_number=3,
        rollback_iso="2026-06-15T09:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # cutover_iso and signoff_iso preserved (empty here -- pre-cutover).
    assert on_disk["cutover_iso"] == ""
    assert on_disk["signoff_iso"] == ""

    assert record.welle_number == 3
    assert record.prior_status == STATUS_PENDING
    assert record.new_status == STATUS_ROLLED_BACK
    assert record.trigger == "rollback"
    assert len(emitter.records) == 1


def test_rollback_in_progress_to_rolled_back(tmp_path):
    """Plan-doc §3.1: in-progress -> rolled-back (mid-Welle rollback)."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 4)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=4, cutover_iso="2026-06-17T08:00:00Z"
    )

    record = producer.handle_rollback_event(
        welle_number=4,
        rollback_iso="2026-06-17T11:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # Forensic preservation: the cutover-iso stays on disk.
    assert on_disk["cutover_iso"] == "2026-06-17T08:00:00Z"
    assert on_disk["signoff_iso"] == ""
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_ROLLED_BACK


def test_rollback_signed_off_to_rolled_back(tmp_path):
    """Plan-doc §3.1: signed-off -> rolled-back (post-sign-off rollback)."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 5)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=5, cutover_iso="2026-06-18T08:00:00Z"
    )
    producer.handle_sign_off_event(
        welle_number=5,
        signoff_iso="2026-06-18T16:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
    )

    record = producer.handle_rollback_event(
        welle_number=5,
        rollback_iso="2026-06-19T09:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # Both forensic timestamps preserved on signed-off rollback.
    assert on_disk["cutover_iso"] == "2026-06-18T08:00:00Z"
    assert on_disk["signoff_iso"] == "2026-06-18T16:00:00Z"
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_ROLLED_BACK


def test_rollback_refused_without_authority_marker(tmp_path):
    """Tag-70 §2.4: rollback-marker authority is mandatory."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(RollbackAuthorityError):
        producer.handle_rollback_event(
            welle_number=1,
            rollback_iso="2026-05-21T10:00:00Z",
            rollback_marker_status="not-authorized",
        )


def test_rollback_refused_with_empty_authority_marker(tmp_path):
    """Empty string is not the authority literal."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(RollbackAuthorityError):
        producer.handle_rollback_event(
            welle_number=1,
            rollback_iso="2026-05-21T10:00:00Z",
            rollback_marker_status="",
        )


def test_rollback_is_idempotent_on_double_fire(tmp_path):
    """Rolled-back is terminal: double-fire is no-op."""
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 6)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_rollback_event(
        welle_number=6,
        rollback_iso="2026-06-25T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    first_bytes = target.read_bytes()
    record = producer.handle_rollback_event(
        welle_number=6,
        rollback_iso="2026-06-25T11:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_ROLLED_BACK
    assert record.new_status == STATUS_ROLLED_BACK


def test_rollback_is_terminal_no_state_change_on_further_events(tmp_path):
    """Plan-doc §3.2: rolled-back -> * is forbidden.

    After a rollback, the state-file MUST remain at rolled-back
    regardless of further cutover/sign-off/sealing attempts. The
    handlers achieve this via two layers:

    * idempotency-guards (cutover/sign-off return no-op
      audit-records for non-pending / non-in-progress prior-states,
      preserving the on-disk bytes), and
    * explicit forbidden-transition guards in
      :func:`_check_transition` that fire when the handler does
      reach the transition-check path (sealing after rollback,
      since sealing must explicitly hit the in-progress ->
      signed-off transition-check).
    """
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_rollback_event(
        welle_number=2,
        rollback_iso="2026-06-10T11:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk_after_rollback = target.read_bytes()

    # Cutover after rollback => idempotent no-op (NOT a state change).
    record = producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T12:00:00Z"
    )
    assert target.read_bytes() == on_disk_after_rollback
    assert record.prior_status == STATUS_ROLLED_BACK
    assert record.new_status == STATUS_ROLLED_BACK

    # Sealing after rollback => explicit forbidden-transition guard
    # (sealing reaches _check_transition since the in-progress path
    # is mandatory; rolled-back -> signed-off is not in
    # ALLOWED_TRANSITIONS).
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_2_sealing_event(
            signoff_iso="2026-06-10T13:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_rollback_refused_with_bad_welle_number(tmp_path):
    state_dir = tmp_path / "state"
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidWelleNumberError):
        producer.handle_rollback_event(
            welle_number=8,
            rollback_iso="2026-05-21T10:00:00Z",
            rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
        )


def test_rollback_refused_with_bad_iso(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_rollback_event(
            welle_number=1,
            rollback_iso="not-an-iso",
            rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
        )


# ---------------------------------------------------------------------------
# Audit-record emit-contract (Tag-70 add-ons).
# ---------------------------------------------------------------------------


def test_audit_record_trigger_field_sealing_round_trips_via_canonical_bytes(
    tmp_path,
):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    sealing_record = emitter.records[-1]
    payload = sealing_record.to_json_bytes()
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed["trigger"] == "sealing"
    assert parsed["welle_number"] == 2
    assert parsed["new_status"] == STATUS_SIGNED_OFF
    # Canonical: keys sorted, compact separators.
    assert payload == json.dumps(
        parsed, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def test_audit_record_trigger_field_rollback_round_trips_via_canonical_bytes(
    tmp_path,
):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 1)
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_rollback_event(
        welle_number=1,
        rollback_iso="2026-05-21T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    rollback_record = emitter.records[-1]
    payload = rollback_record.to_json_bytes()
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed["trigger"] == "rollback"
    assert parsed["welle_number"] == 1
    assert parsed["new_status"] == STATUS_ROLLED_BACK
    assert parsed["prior_status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Atomic-write semantics for the new handlers.
# ---------------------------------------------------------------------------


def test_rollback_leaves_no_temp_files_on_success(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 7)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_rollback_event(
        welle_number=7,
        rollback_iso="2026-07-01T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    leftovers = [p for p in state_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_welle_2_sealing_leaves_no_temp_files_on_success(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    leftovers = [p for p in state_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Cross-Welle parametric coverage (rollback works on all seven Wellen).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("welle_number", sorted(range(1, 8)))
def test_rollback_works_for_all_seven_wellen_from_pending(
    welle_number, tmp_path
):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, welle_number)
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_rollback_event(
        welle_number=welle_number,
        rollback_iso="2026-07-01T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    assert record.welle_number == welle_number
    assert record.prior_status == STATUS_PENDING
    assert record.new_status == STATUS_ROLLED_BACK


# ---------------------------------------------------------------------------
# Schema-pin compliance (Tag-70 must NOT introduce new state-file keys).
# ---------------------------------------------------------------------------


def test_rollback_does_not_add_schema_keys(tmp_path):
    """The rolled-back state-file MUST share key-set with pending stub.

    Tag-70 add-ons must not silently extend the schema -- the
    schema is the Tag-67 pin.
    """
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 1)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_rollback_event(
        welle_number=1,
        rollback_iso="2026-05-21T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    pending_keys = set(_pending_stub(1).keys())
    assert set(on_disk.keys()) == pending_keys


def test_welle_2_sealing_does_not_add_schema_keys(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 2)
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_cutover_event(
        welle_number=2, cutover_iso="2026-06-10T08:00:00Z"
    )
    producer.handle_welle_2_sealing_event(
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    pending_keys = set(_pending_stub(2).keys())
    assert set(on_disk.keys()) == pending_keys
