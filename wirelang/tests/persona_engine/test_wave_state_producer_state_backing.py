# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-72 - Welle-4 State-Backing Producer + Top-Level Handler (Selin).

Tag-69 (PR #438) shipped the Welle-1 producer-path. Tag-70 (PR #444)
shipped Welle-2 Doppelbetrieb-Sealing + Rollback-Writer. Tag-71
(PR #451) wired the top-level handlers + Welle-3 Bridge-Audit sign-off
shorthand. Tag-72 (this PR) adds the **Welle-4 State-Backing sign-off**
shorthand (KW-25 Mo) with the snapshot-restore-marker precondition
(Tomas-Tag-56-Rollback-Workflow §J4).

Scope (Tag-72)
--------------

One new producer-method:

* ``WelleStateProducer.handle_welle_4_signoff_event`` -- structural
  in-progress -> signed-off transition gated by two markers:
  ``sign_off_marker_status == "signed-off"`` AND
  ``snapshot_restore_marker_status == "restored"``. Audit-record
  carries ``trigger="snapshot-restore"`` (disambiguates from Welle-2
  ``trigger="sealing"`` and vanilla ``trigger="sign-off"``).

One new top-level handler in ``wirelang.persona_engine.engine``:

* ``handle_welle_4_signoff_event`` -- delegates to the producer
  method above with ``welle_number=4`` hard-coded (State-Backing
  Welle, KW-25 Mo).

And one async wrapper in ``wirelang.persona_engine.engine_async``:

* ``handle_welle_4_signoff_event`` -- runs the sync handler in the
  default loop's thread-pool executor.

Pre-boot Backend-Decision-Order verification
--------------------------------------------

Welle-4 binds the ``state_backing`` rust<->python BackendDecision
(per the Tag-57 emit-order-pin, the 10-BackendDecision-Manifest-Parity
contract). This test-suite pins the Welle-4 <-> state_backing binding
at the structural level (``SNAPSHOT_RESTORE_GUARDED_WELLEN == {4}``)
without coupling to the rust_backend_switch substrate directly --
the binding-check is the state-file conventions verifier's job,
not the producer-substrate's.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69 / Tag-70 /
Tag-71 producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-substrate
design (Reza-Domaene, Zone-L), or container-infra (Kai-Domaene,
Zone-J). It pins the Tag-72 add-on Welle-4 sign-off shorthand and
reuses the Tag-67 schema-pin verbatim (no schema changes; the
snapshot-restore-iso lives in the audit-stream, not in the
state-file).
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
    DOPPELBETRIEB_SEALED,
    DOPPELBETRIEB_SEALED_WELLEN,
    PHASE_LITERAL,
    PRE_AUDITOR_GUARDED_WELLEN,
    SCHEMA_VERSION_PIN,
    SNAPSHOT_RESTORE_GUARDED_WELLEN,
    SNAPSHOT_RESTORE_VERIFIED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    SignOffPreconditionError,
    SnapshotRestoreError,
    WelleAuditRecord,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69 / Tag-70 / Tag-71 layout).
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
            "snapshot_restore_marker": (
                f"state/welle-{welle_number}-snapshot-restore.json"
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
# Public-API surface invariants.
# ---------------------------------------------------------------------------


def test_welle_4_is_snapshot_restore_guarded_constant_pin():
    """Welle-4 MUST be in SNAPSHOT_RESTORE_GUARDED_WELLEN (Tag-72 §2.5).

    This pins the precondition that the Tag-72 Welle-4 sign-off
    shorthand depends on (snapshot-restore-marker gate; the 10th
    pre-boot BackendDecision binds to Welle-4 per the
    Tag-57-emit-order-pin).
    """
    assert 4 in SNAPSHOT_RESTORE_GUARDED_WELLEN
    # Welle-4 is the ONLY snapshot-restore-guarded Welle.
    assert SNAPSHOT_RESTORE_GUARDED_WELLEN == frozenset({4})


def test_welle_4_disjoint_from_other_marker_guarded_welle_sets():
    """Welle-4 MUST NOT overlap with the other marker-guarded sets.

    Each marker-guard family (sealing for W2, pre-auditor for W3/W7,
    snapshot-restore for W4) MUST be disjoint -- a single Welle
    cannot have two simultaneous marker-families without ambiguating
    the audit-stream trigger field.
    """
    assert SNAPSHOT_RESTORE_GUARDED_WELLEN.isdisjoint(
        DOPPELBETRIEB_SEALED_WELLEN
    )
    assert SNAPSHOT_RESTORE_GUARDED_WELLEN.isdisjoint(
        PRE_AUDITOR_GUARDED_WELLEN
    )


def test_snapshot_restore_verified_literal_is_canonical():
    """The marker authority literal MUST be exactly "restored".

    Mirrors the design of :data:`DOPPELBETRIEB_SEALED` ("sealed") and
    :data:`ROLLBACK_MARKER_AUTHORIZED` ("rollback-authorized"). The
    literal is an audit-trail anchor; any drift breaks the
    operator-curated marker contract.
    """
    assert SNAPSHOT_RESTORE_VERIFIED == "restored"


def test_engine_module_exposes_welle_4_handler():
    """Tag-72: engine.py MUST expose ``handle_welle_4_signoff_event``."""
    assert hasattr(engine_mod, "handle_welle_4_signoff_event")
    assert callable(engine_mod.handle_welle_4_signoff_event)


def test_engine_async_module_exposes_welle_4_handler():
    """Tag-72: engine_async.py MUST expose the async wrapper as coroutine."""
    assert hasattr(engine_async_mod, "handle_welle_4_signoff_event")
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_4_signoff_event
    )


def test_sync_welle_4_handler_is_not_a_coroutine():
    """The sync handler in engine.py MUST be a plain function."""
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_4_signoff_event
    )


# ---------------------------------------------------------------------------
# Producer-method direct-call tests (handle_welle_4_signoff_event).
# ---------------------------------------------------------------------------


def test_producer_welle_4_signoff_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    record = producer.handle_welle_4_signoff_event(
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["welle_number"] == 4
    assert on_disk["signoff_iso"] == "2026-06-16T15:00:00Z"
    # Cutover-iso preserved.
    assert on_disk["cutover_iso"] == "2026-06-16T08:00:00Z"

    assert record.welle_number == 4
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "snapshot-restore"
    assert emitter.records == [record]


def test_producer_welle_4_signoff_refused_without_snapshot_restore_marker(
    tmp_path,
):
    """A bad snapshot-restore-marker MUST raise SnapshotRestoreError."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SnapshotRestoreError):
        producer.handle_welle_4_signoff_event(
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status="pending",
        )


def test_producer_welle_4_signoff_refused_with_empty_snapshot_restore_marker(
    tmp_path,
):
    """Empty snapshot-restore-marker MUST be refused (no implicit defaults)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SnapshotRestoreError):
        producer.handle_welle_4_signoff_event(
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status="",
        )


def test_producer_welle_4_signoff_refused_without_sign_off_marker(tmp_path):
    """sign-off-marker still has to be signed-off (both gates required)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SignOffPreconditionError):
        producer.handle_welle_4_signoff_event(
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_PENDING,
            snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        )


def test_producer_welle_4_signoff_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_welle_4_signoff_event(
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    first_bytes = target.read_bytes()
    record = producer.handle_welle_4_signoff_event(
        signoff_iso="2026-06-16T16:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "snapshot-restore"


# ---------------------------------------------------------------------------
# handle_welle_4_signoff_event (sync top-level handler).
# ---------------------------------------------------------------------------


def test_handle_welle_4_signoff_event_delegates_to_producer(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        audit_emitter=emitter,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 4
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["signoff_iso"] == "2026-06-16T15:00:00Z"

    assert record.welle_number == 4
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "snapshot-restore"
    assert emitter.records == [record]


def test_handle_welle_4_signoff_event_refused_without_snapshot_restore_marker(
    tmp_path,
):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    with pytest.raises(SnapshotRestoreError):
        engine_mod.handle_welle_4_signoff_event(
            state_dir,
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status="rolled-back",
        )


def test_handle_welle_4_signoff_event_refused_without_sign_off_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    with pytest.raises(SignOffPreconditionError):
        engine_mod.handle_welle_4_signoff_event(
            state_dir,
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_PENDING,
            snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        )


def test_handle_welle_4_signoff_event_uses_noop_emitter_when_none(tmp_path):
    """Default ``audit_emitter=None`` MUST not break the handler."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    record = engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        audit_emitter=None,
    )
    assert record.trigger == "snapshot-restore"
    assert record.new_status == STATUS_SIGNED_OFF


def test_handle_welle_4_signoff_event_hardcodes_welle_number_4(tmp_path):
    """The Welle-4 shorthand MUST always write welle-4.json regardless
    of which other state-files exist in state_dir.

    Sibling welle-3 / welle-5 files MUST remain byte-untouched (the
    snapshot-restore-marker is Welle-4-specific; misbinding to W3/W5
    would silently corrupt the cross-Welle ordering invariant).
    """
    state_dir = tmp_path / "state"
    target_3 = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    target_4 = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    target_5 = _seed_in_progress(state_dir, 5, "2026-06-17T08:00:00Z")
    sibling_3_before = target_3.read_bytes()
    sibling_5_before = target_5.read_bytes()

    engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )

    assert target_3.read_bytes() == sibling_3_before, (
        "welle-3 must be untouched by a welle-4 sign-off"
    )
    assert target_5.read_bytes() == sibling_5_before, (
        "welle-5 must be untouched by a welle-4 sign-off"
    )
    on_disk_4 = json.loads(target_4.read_text(encoding="utf-8"))
    assert on_disk_4["welle_number"] == 4
    assert on_disk_4["status"] == STATUS_SIGNED_OFF


def test_handle_welle_4_signoff_event_idempotent_via_top_level(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    first_bytes = target.read_bytes()
    record = engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T17:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "snapshot-restore"


# ---------------------------------------------------------------------------
# Schema-pin discipline: handler MUST NOT mutate schema-pinned fields.
# ---------------------------------------------------------------------------


def test_handlers_preserve_schema_pin_after_welle_4_signoff(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    pre_keys = set(_pending_stub(4).keys())
    engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # Schema-pin literals unchanged.
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL
    assert on_disk["welle_number"] == 4
    assert on_disk["kw_cutover_anchor"] == CANONICAL_KW_ANCHOR[4]
    # No new top-level keys added (snapshot-restore-iso lives in the
    # audit-stream, NOT in the state-file).
    assert set(on_disk.keys()) == pre_keys


# ---------------------------------------------------------------------------
# State-Backing Pre-Boot Order verification (Tag-57 emit-order-pin).
# ---------------------------------------------------------------------------


def test_welle_4_snapshot_restore_audit_trigger_disambiguates_from_sealing(
    tmp_path,
):
    """The Welle-4 audit-record trigger MUST be "snapshot-restore", not
    "sign-off" or "sealing".

    This is critical for downstream audit-stream consumers (Henrik
    Internal Audit) to distinguish the three Welle marker-families
    when reconciling rollback-decisions.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    emitter = _RecordingEmitter()
    engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        audit_emitter=emitter,
    )
    assert len(emitter.records) == 1
    assert emitter.records[0].trigger == "snapshot-restore"
    # Anti-Drift: trigger MUST NOT collide with Welle-2 sealing.
    assert emitter.records[0].trigger != "sealing"
    # Anti-Drift: trigger MUST NOT be the vanilla sign-off literal.
    assert emitter.records[0].trigger != "sign-off"


def test_welle_4_state_backing_pre_boot_order_pin_audit_canonical_bytes(
    tmp_path,
):
    """Audit-record canonical-bytes MUST be stable for the Welle-4 path.

    The 10th pre-boot BackendDecision (state_backing rust<->python)
    binds to Welle-4 per the Tag-57-emit-order-pin. The audit-stream
    that captures this binding MUST be canonical-byte-stable across
    direct-producer vs. top-level-handler dispatch paths
    (Doppelbetrieb-Vergleich invariant; the dispatch-shim MUST NOT
    alter the audit-stream).
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
        audit_emitter=emitter,
    )
    canonical = record.to_json_bytes()
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed == {
        "cutover_iso": "2026-06-16T08:00:00Z",
        "new_status": STATUS_SIGNED_OFF,
        "prior_status": STATUS_IN_PROGRESS,
        "signoff_iso": "2026-06-16T15:00:00Z",
        "trigger": "snapshot-restore",
        "welle_number": 4,
    }
    # Single record (no spurious double-emit through the wrapper).
    assert [r.trigger for r in emitter.records] == ["snapshot-restore"]


# ---------------------------------------------------------------------------
# Async wrapper (engine_async.py).
# ---------------------------------------------------------------------------


def test_async_handle_welle_4_signoff_event_delegates(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    emitter = _RecordingEmitter()

    async def _run():
        return await engine_async_mod.handle_welle_4_signoff_event(
            state_dir,
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
            audit_emitter=emitter,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 4
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.trigger == "snapshot-restore"
    assert emitter.records == [record]


def test_async_handle_welle_4_signoff_event_refuses_without_snapshot_marker(
    tmp_path,
):
    """The snapshot-restore-marker gate MUST be enforced via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")

    async def _run():
        await engine_async_mod.handle_welle_4_signoff_event(
            state_dir,
            signoff_iso="2026-06-16T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            snapshot_restore_marker_status="not-restored",
        )

    with pytest.raises(SnapshotRestoreError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Cross-state interactions: rollback after Welle-4 sign-off still allowed.
# ---------------------------------------------------------------------------


def test_welle_4_can_be_rolled_back_post_sign_off(tmp_path):
    """After a Welle-4 sign-off the post-sign-off rollback transition
    (``signed-off -> rolled-back``) MUST still be available.

    This pins plan-doc §3.1 ``signed-off -> rolled-back`` invariant
    on the Welle-4 substrate -- the snapshot-restore-marker gate does
    not change the rollback-substrate's behaviour (rollback is gated
    by its own ``rollback-authorized`` marker).
    """
    from wirelang.persona_engine.welle_state_producer import (
        ROLLBACK_MARKER_AUTHORIZED,
    )

    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 4, "2026-06-16T08:00:00Z")
    engine_mod.handle_welle_4_signoff_event(
        state_dir,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    assert json.loads(target.read_text())["status"] == STATUS_SIGNED_OFF
    # Post-sign-off rollback.
    rollback_record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=4,
        rollback_iso="2026-06-17T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # signoff_iso preserved on rollback for forensic audit-trail.
    assert on_disk["signoff_iso"] == "2026-06-16T15:00:00Z"
    assert rollback_record.prior_status == STATUS_SIGNED_OFF
    assert rollback_record.new_status == STATUS_ROLLED_BACK
    assert rollback_record.trigger == "rollback"


# ---------------------------------------------------------------------------
# Marker-family disambiguation: trigger field across the three Welle families.
# ---------------------------------------------------------------------------


def test_marker_family_triggers_are_pairwise_distinct(tmp_path):
    """Across the three marker-guarded sign-off paths the audit-trigger
    MUST be a distinct literal per family.

    Family A (Welle-2 Doppelbetrieb-Sealing) -> trigger="sealing"
    Family B (Welle-3/7 Pre-Auditor)          -> trigger="sign-off"
    Family C (Welle-4 Snapshot-Restore)       -> trigger="snapshot-restore"

    Henrik Internal Audit relies on this disambiguation when
    reconciling rollback decisions against the
    Tomas-Tag-56-Rollback-Workflow J2..J8 envelope catalog.
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
    _seed_in_progress(state_dir_3, 3, "2026-06-13T08:00:00Z")
    rec_3 = engine_mod.handle_welle_3_signoff_event(
        state_dir_3,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    # Family C: Welle-4 snapshot-restore (Tag-72).
    state_dir_4 = tmp_path / "state_4"
    _seed_in_progress(state_dir_4, 4, "2026-06-16T08:00:00Z")
    rec_4 = engine_mod.handle_welle_4_signoff_event(
        state_dir_4,
        signoff_iso="2026-06-16T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    triggers = {rec_2.trigger, rec_3.trigger, rec_4.trigger}
    assert triggers == {"sealing", "sign-off", "snapshot-restore"}
    # All three are signed-off transitions (new_status uniform).
    assert {rec_2.new_status, rec_3.new_status, rec_4.new_status} == {
        STATUS_SIGNED_OFF
    }
