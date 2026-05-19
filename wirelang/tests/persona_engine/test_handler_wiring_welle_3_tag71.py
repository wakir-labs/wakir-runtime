# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-71 - engine.py / engine_async.py Top-Level Handler-Wiring + Welle-3 (Selin).

Tag-69 (PR #438) shipped the Welle-1 producer-path. Tag-70 (PR #444)
shipped Welle-2 Doppelbetrieb-Sealing + Rollback-Writer. Tag-71 (this
PR) wires the producer-substrate into the engine-side event-dispatch
surface as top-level free functions and adds the Welle-3 Bridge-Audit
sign-off shorthand (KW-24 Fr, Pre-Auditor-Gate aktiv).

Scope (Tag-71)
--------------

Three top-level handlers in ``wirelang.persona_engine.engine``:

* ``handle_welle_sealing_event`` -- delegates to
  ``WelleStateProducer.handle_welle_2_sealing_event``.
* ``handle_welle_rollback_event`` -- delegates to
  ``WelleStateProducer.handle_rollback_event``.
* ``handle_welle_3_signoff_event`` -- delegates to
  ``WelleStateProducer.handle_sign_off_event`` with ``welle_number=3``
  (Bridge-Audit Welle, pre-auditor-guarded).

And three async wrappers in ``wirelang.persona_engine.engine_async``
that run the sync handlers in the default loop's thread-pool executor.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69 / Tag-70
producer-test conventions.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-substrate
design (Reza-Domaene, Zone-L), or container-infra (Kai-Domaene,
Zone-J). It pins the Tag-71 add-on handler-wiring surface and reuses
the Tag-67 schema-pin verbatim (no schema changes).
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
    DoppelbetriebSealingError,
    PHASE_LITERAL,
    PRE_AUDITOR_GUARDED_WELLEN,
    PreAuditorGuardError,
    ROLLBACK_MARKER_AUTHORIZED,
    RollbackAuthorityError,
    SCHEMA_VERSION_PIN,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_SIGNED_OFF,
    SignOffPreconditionError,
    WelleAuditRecord,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69 / Tag-70 layout).
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


def _seed_in_progress(state_dir: Path, welle_number: int, cutover_iso: str) -> Path:
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


def test_engine_module_exposes_top_level_handlers():
    """Tag-71: engine.py MUST expose the three top-level handlers."""
    assert hasattr(engine_mod, "handle_welle_sealing_event")
    assert hasattr(engine_mod, "handle_welle_rollback_event")
    assert hasattr(engine_mod, "handle_welle_3_signoff_event")
    assert callable(engine_mod.handle_welle_sealing_event)
    assert callable(engine_mod.handle_welle_rollback_event)
    assert callable(engine_mod.handle_welle_3_signoff_event)


def test_engine_async_module_exposes_top_level_handlers():
    """Tag-71: engine_async.py MUST expose the three async wrappers."""
    assert hasattr(engine_async_mod, "handle_welle_sealing_event")
    assert hasattr(engine_async_mod, "handle_welle_rollback_event")
    assert hasattr(engine_async_mod, "handle_welle_3_signoff_event")
    # All three async-module entry-points are coroutine functions.
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_sealing_event
    )
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_rollback_event
    )
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_3_signoff_event
    )


def test_sync_handlers_are_not_coroutine_functions():
    """Sync handlers in engine.py are plain functions, not coroutines."""
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_sealing_event
    )
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_rollback_event
    )
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_3_signoff_event
    )


def test_welle_3_is_pre_auditor_guarded_constant_pin():
    """Welle-3 MUST be in PRE_AUDITOR_GUARDED_WELLEN (plan-doc §2.2).

    This test pins the precondition that the Tag-71 Welle-3 sign-off
    shorthand depends on (Henrik-cannot-self-sign-off invariant).
    """
    assert 3 in PRE_AUDITOR_GUARDED_WELLEN


# ---------------------------------------------------------------------------
# handle_welle_sealing_event (sync) -- Welle-2 Doppelbetrieb-Sealing.
# ---------------------------------------------------------------------------


def test_handle_welle_sealing_event_delegates_to_producer(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 2, "2026-06-10T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_sealing_event(
        state_dir,
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        audit_emitter=emitter,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["welle_number"] == 2
    assert on_disk["signoff_iso"] == "2026-06-10T14:30:00Z"

    assert record.welle_number == 2
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "sealing"
    assert emitter.records == [record]


def test_handle_welle_sealing_event_refused_without_sealed_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 2, "2026-06-10T08:00:00Z")
    with pytest.raises(DoppelbetriebSealingError):
        engine_mod.handle_welle_sealing_event(
            state_dir,
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status="not-sealed",
        )


def test_handle_welle_sealing_event_refused_without_sign_off_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 2, "2026-06-10T08:00:00Z")
    with pytest.raises(SignOffPreconditionError):
        engine_mod.handle_welle_sealing_event(
            state_dir,
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_PENDING,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        )


def test_handle_welle_sealing_event_uses_noop_emitter_when_none(tmp_path):
    """When ``audit_emitter`` is None the handler MUST still complete.

    The default is the module-private no-op emitter (so callers that
    don't wire a bridge-audit-writer don't break).
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 2, "2026-06-10T08:00:00Z")
    record = engine_mod.handle_welle_sealing_event(
        state_dir,
        signoff_iso="2026-06-10T14:30:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
        audit_emitter=None,
    )
    assert record.trigger == "sealing"
    assert record.new_status == STATUS_SIGNED_OFF


# ---------------------------------------------------------------------------
# handle_welle_rollback_event (sync) -- Rollback-Writer.
# ---------------------------------------------------------------------------


def test_handle_welle_rollback_event_pending_to_rolled_back(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 4)
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=4,
        rollback_iso="2026-06-12T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
        audit_emitter=emitter,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    assert on_disk["welle_number"] == 4
    # Rollback preserves cutover_iso / signoff_iso (here empty).
    assert on_disk["cutover_iso"] == ""
    assert on_disk["signoff_iso"] == ""

    assert record.welle_number == 4
    assert record.prior_status == STATUS_PENDING
    assert record.new_status == STATUS_ROLLED_BACK
    assert record.trigger == "rollback"
    assert emitter.records == [record]


def test_handle_welle_rollback_event_in_progress_to_rolled_back(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-13T09:00:00Z")
    record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=5,
        rollback_iso="2026-06-13T11:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # Cutover-iso preserved for forensic audit-trail.
    assert on_disk["cutover_iso"] == "2026-06-13T09:00:00Z"
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_ROLLED_BACK


def test_handle_welle_rollback_event_refused_without_authority(tmp_path):
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 6)
    with pytest.raises(RollbackAuthorityError):
        engine_mod.handle_welle_rollback_event(
            state_dir,
            welle_number=6,
            rollback_iso="2026-06-14T10:00:00Z",
            rollback_marker_status="some-other-marker",
        )


def test_handle_welle_rollback_event_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 7)
    engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=7,
        rollback_iso="2026-06-15T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    first_bytes = target.read_bytes()
    record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=7,
        rollback_iso="2026-06-15T11:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_ROLLED_BACK
    assert record.new_status == STATUS_ROLLED_BACK
    assert record.trigger == "rollback"


# ---------------------------------------------------------------------------
# handle_welle_3_signoff_event (sync) -- Bridge-Audit Welle, KW-24 Fr.
# ---------------------------------------------------------------------------


def test_handle_welle_3_signoff_event_happy_path_with_designated_pre_auditor(
    tmp_path,
):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        audit_emitter=emitter,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 3
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["signoff_iso"] == "2026-06-13T15:00:00Z"

    assert record.welle_number == 3
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "sign-off"
    assert emitter.records == [record]


def test_handle_welle_3_signoff_event_refused_without_pre_auditor(tmp_path):
    """Welle-3 sign-off refused when pre_auditor_decision is missing."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    with pytest.raises(PreAuditorGuardError):
        engine_mod.handle_welle_3_signoff_event(
            state_dir,
            signoff_iso="2026-06-13T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision=None,
        )


def test_handle_welle_3_signoff_event_refused_with_bad_pre_auditor_value(
    tmp_path,
):
    """Pre-auditor-decision must be exactly ``"designated"``."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    with pytest.raises(PreAuditorGuardError):
        engine_mod.handle_welle_3_signoff_event(
            state_dir,
            signoff_iso="2026-06-13T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="self-designated",
        )


def test_handle_welle_3_signoff_event_refused_without_sign_off_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    with pytest.raises(SignOffPreconditionError):
        engine_mod.handle_welle_3_signoff_event(
            state_dir,
            signoff_iso="2026-06-13T15:00:00Z",
            sign_off_marker_status=STATUS_PENDING,
            pre_auditor_decision="designated",
        )


def test_handle_welle_3_signoff_event_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    first_bytes = target.read_bytes()
    record = engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T16:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "sign-off"


def test_handle_welle_3_signoff_event_hardcodes_welle_number_3(tmp_path):
    """The Welle-3 shorthand MUST always write welle-3.json regardless
    of which other state-files exist in state_dir."""
    state_dir = tmp_path / "state"
    # Seed welle-3 plus a sibling (welle-4) that should NOT be touched.
    target_3 = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    target_4 = _seed_in_progress(state_dir, 4, "2026-06-13T08:00:00Z")
    sibling_before = target_4.read_bytes()

    engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )

    sibling_after = target_4.read_bytes()
    assert sibling_before == sibling_after, "welle-4 must be untouched"
    on_disk_3 = json.loads(target_3.read_text(encoding="utf-8"))
    assert on_disk_3["welle_number"] == 3
    assert on_disk_3["status"] == STATUS_SIGNED_OFF


# ---------------------------------------------------------------------------
# Schema-pin discipline: handlers MUST NOT mutate schema-pinned fields.
# ---------------------------------------------------------------------------


def test_handlers_preserve_schema_pin_after_welle_3_signoff(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL
    assert on_disk["welle_number"] == 3
    assert on_disk["kw_cutover_anchor"] == CANONICAL_KW_ANCHOR[3]


def test_handlers_preserve_schema_pin_after_rollback(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_pending(state_dir, 6)
    engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=6,
        rollback_iso="2026-06-14T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL
    # Schema-pin: rollback MUST NOT add new top-level keys.
    expected_keys = set(_pending_stub(6).keys())
    assert set(on_disk.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Async wrappers (engine_async.py).
# ---------------------------------------------------------------------------


def test_async_handle_welle_sealing_event_delegates(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 2, "2026-06-10T08:00:00Z")
    emitter = _RecordingEmitter()

    async def _run():
        return await engine_async_mod.handle_welle_sealing_event(
            state_dir,
            signoff_iso="2026-06-10T14:30:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            doppelbetrieb_sealed_marker_status=DOPPELBETRIEB_SEALED,
            audit_emitter=emitter,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.welle_number == 2
    assert record.trigger == "sealing"
    assert emitter.records == [record]


def test_async_handle_welle_rollback_event_delegates(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-13T09:00:00Z")

    async def _run():
        return await engine_async_mod.handle_welle_rollback_event(
            state_dir,
            welle_number=5,
            rollback_iso="2026-06-13T11:00:00Z",
            rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.trigger == "rollback"


def test_async_handle_welle_3_signoff_event_delegates(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")

    async def _run():
        return await engine_async_mod.handle_welle_3_signoff_event(
            state_dir,
            signoff_iso="2026-06-13T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision="designated",
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 3
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.trigger == "sign-off"


def test_async_handle_welle_3_signoff_event_refuses_without_pre_auditor(tmp_path):
    """Pre-auditor-gate enforced even via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")

    async def _run():
        await engine_async_mod.handle_welle_3_signoff_event(
            state_dir,
            signoff_iso="2026-06-13T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            pre_auditor_decision=None,
        )

    with pytest.raises(PreAuditorGuardError):
        asyncio.run(_run())


def test_async_handle_welle_rollback_event_refuses_without_authority(tmp_path):
    """Rollback-authority-marker gate enforced even via the async path."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 6)

    async def _run():
        await engine_async_mod.handle_welle_rollback_event(
            state_dir,
            welle_number=6,
            rollback_iso="2026-06-14T10:00:00Z",
            rollback_marker_status="bogus-marker",
        )

    with pytest.raises(RollbackAuthorityError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Audit-record canonical-bytes round-trip via the handler-wiring layer.
# ---------------------------------------------------------------------------


def test_audit_record_emitted_via_handler_is_canonical_byte_stable(tmp_path):
    """The audit-record canonical-bytes serialisation MUST be stable
    regardless of whether the producer is reached via a direct call or
    via the Tag-71 top-level handler wrapper. Doppelbetrieb-Vergleich
    invariant: dispatch-shim MUST NOT alter the audit-stream content."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 3, "2026-06-13T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_3_signoff_event(
        state_dir,
        signoff_iso="2026-06-13T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
        audit_emitter=emitter,
    )
    canonical = record.to_json_bytes()
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed == {
        "cutover_iso": "2026-06-13T08:00:00Z",
        "new_status": STATUS_SIGNED_OFF,
        "prior_status": STATUS_IN_PROGRESS,
        "signoff_iso": "2026-06-13T15:00:00Z",
        "trigger": "sign-off",
        "welle_number": 3,
    }
    # Key-order is canonical (sort_keys=True) and the emitter saw exactly
    # one record (no spurious double-emit through the wrapper).
    assert [r.trigger for r in emitter.records] == ["sign-off"]
