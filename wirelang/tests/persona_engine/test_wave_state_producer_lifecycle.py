# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-73 - Welle-5 Capability-Token Producer + Top-Level Handler (Selin).

Tag-69 (PR #438) shipped the Welle-1 producer-path. Tag-70 (PR #444)
shipped Welle-2 Doppelbetrieb-Sealing + Rollback-Writer. Tag-71
(PR #451) wired the top-level handlers + Welle-3 Bridge-Audit sign-off
shorthand. Tag-72 (PR #458) added the Welle-4 State-Backing sign-off
shorthand. Tag-73 (this PR) adds the **Welle-5 Capability-Token sign-off**
shorthand (KW-25 Fr 2026-06-19, Reza-Zone-L) with the capability-token-
rotation-marker precondition (kw-24-welle-1-7-acceptance-criteria §5
probes W5-S1..S4).

Scope (Tag-73)
--------------

One new producer-method:

* ``WelleStateProducer.handle_welle_5_signoff_event`` -- structural
  in-progress -> signed-off transition gated by two markers:
  ``sign_off_marker_status == "signed-off"`` AND
  ``capability_token_rotation_marker_status == "rotated"``. Audit-record
  carries ``trigger="capability-token-rotation"`` (disambiguates from
  Welle-2 ``trigger="sealing"``, Welle-3/7 ``trigger="sign-off"``, and
  Welle-4 ``trigger="snapshot-restore"``).

One new top-level handler in ``wirelang.persona_engine.engine``:

* ``handle_welle_5_signoff_event`` -- delegates to the producer
  method above with ``welle_number=5`` hard-coded (Capability-Token
  Welle, KW-25 Fr 2026-06-19).

And one async wrapper in ``wirelang.persona_engine.engine_async``:

* ``handle_welle_5_signoff_event`` -- runs the sync handler in the
  default loop's thread-pool executor.

Capability-Token enforce-mode anchor
------------------------------------

Welle-5 binds the capability-token enforce-mode flip (audit-only-mode
-> enforce-mode) per kw-24-welle-1-7-acceptance-criteria §5. This
test-suite pins the Welle-5 <-> capability-token binding at the
structural level (``CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN == {5}``)
without coupling to the capability-token-enforce-validate workflow
directly -- the workflow-side validation is the
``tooling/ci/welle_5_hot_spot_aggregator.py`` (probe W5-S1) job, not
the producer-substrate's.

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69 / Tag-70 /
Tag-71 / Tag-72 producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), capability-token
substrate design (Reza-Domaene, Zone-L -- the rotation-marker contract
is Reza's; Selin only consumes the literal), or container-infra
(Kai-Domaene, Zone-J). It pins the Tag-73 add-on Welle-5 sign-off
shorthand and reuses the Tag-67 schema-pin verbatim (no schema changes;
the capability-token-rotation-iso lives in the audit-stream, not in the
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
    CAPABILITY_TOKEN_ROTATED,
    CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN,
    CapabilityTokenRotationError,
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
    WelleAuditRecord,
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69 / Tag-70 / Tag-71 / Tag-72 layout).
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
            "capability_token_rotation_marker": (
                "state/capability-token-rotation-drill.json"
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


def test_welle_5_is_capability_token_guarded_constant_pin():
    """Welle-5 MUST be in CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN (Tag-73 §2.6).

    This pins the precondition that the Tag-73 Welle-5 sign-off
    shorthand depends on (capability-token-rotation-marker gate per
    kw-24-welle-1-7-acceptance-criteria §5 probe W5-S4).
    """
    assert 5 in CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN
    # Welle-5 is the ONLY capability-token-rotation-guarded Welle.
    assert CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN == frozenset({5})


def test_welle_5_disjoint_from_other_marker_guarded_welle_sets():
    """Welle-5 MUST NOT overlap with the other marker-guarded sets.

    Each marker-guard family (sealing for W2, pre-auditor for W3/W7,
    snapshot-restore for W4, capability-token-rotation for W5) MUST be
    disjoint -- a single Welle cannot have two simultaneous marker-
    families without ambiguating the audit-stream trigger field.
    """
    assert CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN.isdisjoint(
        DOPPELBETRIEB_SEALED_WELLEN
    )
    assert CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN.isdisjoint(
        PRE_AUDITOR_GUARDED_WELLEN
    )
    assert CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN.isdisjoint(
        SNAPSHOT_RESTORE_GUARDED_WELLEN
    )


def test_capability_token_rotated_literal_is_canonical():
    """The marker authority literal MUST be exactly "rotated".

    Mirrors the design of :data:`DOPPELBETRIEB_SEALED` ("sealed"),
    :data:`SNAPSHOT_RESTORE_VERIFIED` ("restored"), and
    :data:`ROLLBACK_MARKER_AUTHORIZED` ("rollback-authorized"). The
    literal is an audit-trail anchor; any drift breaks the
    operator-curated marker contract.
    """
    assert CAPABILITY_TOKEN_ROTATED == "rotated"


def test_engine_module_exposes_welle_5_handler():
    """Tag-73: engine.py MUST expose ``handle_welle_5_signoff_event``."""
    assert hasattr(engine_mod, "handle_welle_5_signoff_event")
    assert callable(engine_mod.handle_welle_5_signoff_event)


def test_engine_async_module_exposes_welle_5_handler():
    """Tag-73: engine_async.py MUST expose the async wrapper as coroutine."""
    assert hasattr(engine_async_mod, "handle_welle_5_signoff_event")
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_5_signoff_event
    )


def test_sync_welle_5_handler_is_not_a_coroutine():
    """The sync handler in engine.py MUST be a plain function."""
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_5_signoff_event
    )


# ---------------------------------------------------------------------------
# Producer-method direct-call tests (handle_welle_5_signoff_event).
# ---------------------------------------------------------------------------


def test_producer_welle_5_signoff_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    record = producer.handle_welle_5_signoff_event(
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["welle_number"] == 5
    assert on_disk["signoff_iso"] == "2026-06-19T15:00:00Z"
    # Cutover-iso preserved.
    assert on_disk["cutover_iso"] == "2026-06-19T08:00:00Z"

    assert record.welle_number == 5
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "capability-token-rotation"
    assert emitter.records == [record]


def test_producer_welle_5_signoff_refused_without_rotation_marker(tmp_path):
    """A bad rotation-marker MUST raise CapabilityTokenRotationError."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(CapabilityTokenRotationError):
        producer.handle_welle_5_signoff_event(
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status="audit-only",
        )


def test_producer_welle_5_signoff_refused_with_empty_rotation_marker(tmp_path):
    """Empty rotation-marker MUST be refused (no implicit defaults)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(CapabilityTokenRotationError):
        producer.handle_welle_5_signoff_event(
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status="",
        )


def test_producer_welle_5_signoff_refused_without_sign_off_marker(tmp_path):
    """sign-off-marker still has to be signed-off (both gates required)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SignOffPreconditionError):
        producer.handle_welle_5_signoff_event(
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_PENDING,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        )


def test_producer_welle_5_signoff_idempotent_on_double_fire(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_welle_5_signoff_event(
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    first_bytes = target.read_bytes()
    record = producer.handle_welle_5_signoff_event(
        signoff_iso="2026-06-19T16:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "capability-token-rotation"


def test_producer_welle_5_signoff_refused_from_pending(tmp_path):
    """pending -> signed-off is forbidden (must go via in-progress first)."""
    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 5)
    producer = WelleStateProducer(state_dir=state_dir)
    from wirelang.persona_engine.welle_state_producer import (
        InvalidStatusTransitionError,
    )

    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_5_signoff_event(
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        )


# ---------------------------------------------------------------------------
# handle_welle_5_signoff_event (sync top-level handler).
# ---------------------------------------------------------------------------


def test_handle_welle_5_signoff_event_delegates_to_producer(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        audit_emitter=emitter,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 5
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["signoff_iso"] == "2026-06-19T15:00:00Z"

    assert record.welle_number == 5
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "capability-token-rotation"
    assert emitter.records == [record]


def test_handle_welle_5_signoff_event_refused_without_rotation_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    with pytest.raises(CapabilityTokenRotationError):
        engine_mod.handle_welle_5_signoff_event(
            state_dir,
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status="rolled-back",
        )


def test_handle_welle_5_signoff_event_refused_without_sign_off_marker(tmp_path):
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    with pytest.raises(SignOffPreconditionError):
        engine_mod.handle_welle_5_signoff_event(
            state_dir,
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_PENDING,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        )


def test_handle_welle_5_signoff_event_uses_noop_emitter_when_none(tmp_path):
    """Default ``audit_emitter=None`` MUST not break the handler."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    record = engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        audit_emitter=None,
    )
    assert record.trigger == "capability-token-rotation"
    assert record.new_status == STATUS_SIGNED_OFF


def test_handle_welle_5_signoff_event_hardcodes_welle_number_5(tmp_path):
    """The Welle-5 shorthand MUST always write welle-5.json regardless
    of which other state-files exist in state_dir.

    Sibling welle-4 / welle-6 files MUST remain byte-untouched (the
    capability-token-rotation-marker is Welle-5-specific; misbinding to
    W4/W6 would silently corrupt the cross-Welle ordering invariant).
    """
    state_dir = tmp_path / "state"
    target_4 = _seed_in_progress(state_dir, 4, "2026-06-15T08:00:00Z")
    target_5 = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    target_6 = _seed_in_progress(state_dir, 6, "2026-06-26T08:00:00Z")
    sibling_4_before = target_4.read_bytes()
    sibling_6_before = target_6.read_bytes()

    engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )

    assert target_4.read_bytes() == sibling_4_before, (
        "welle-4 must be untouched by a welle-5 sign-off"
    )
    assert target_6.read_bytes() == sibling_6_before, (
        "welle-6 must be untouched by a welle-5 sign-off"
    )
    on_disk_5 = json.loads(target_5.read_text(encoding="utf-8"))
    assert on_disk_5["welle_number"] == 5
    assert on_disk_5["status"] == STATUS_SIGNED_OFF


def test_handle_welle_5_signoff_event_idempotent_via_top_level(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    first_bytes = target.read_bytes()
    record = engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T17:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    second_bytes = target.read_bytes()
    assert first_bytes == second_bytes
    assert record.prior_status == STATUS_SIGNED_OFF
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "capability-token-rotation"


# ---------------------------------------------------------------------------
# Schema-pin discipline: handler MUST NOT mutate schema-pinned fields.
# ---------------------------------------------------------------------------


def test_handlers_preserve_schema_pin_after_welle_5_signoff(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    pre_keys = set(_pending_stub(5).keys())
    engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # Schema-pin literals unchanged.
    assert on_disk["schema_version"] == SCHEMA_VERSION_PIN
    assert on_disk["phase"] == PHASE_LITERAL
    assert on_disk["welle_number"] == 5
    assert on_disk["kw_cutover_anchor"] == CANONICAL_KW_ANCHOR[5]
    # No new top-level keys added (capability-token-rotation-iso lives
    # in the audit-stream, NOT in the state-file).
    assert set(on_disk.keys()) == pre_keys


# ---------------------------------------------------------------------------
# Capability-Token enforce-mode anchor verification.
# ---------------------------------------------------------------------------


def test_welle_5_capability_token_audit_trigger_disambiguates_from_others(
    tmp_path,
):
    """The Welle-5 audit-record trigger MUST be "capability-token-rotation",
    not "sign-off", "sealing", or "snapshot-restore".

    This is critical for downstream audit-stream consumers (Henrik
    Internal Audit) to distinguish the four Welle marker-families
    when reconciling rollback-decisions.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    emitter = _RecordingEmitter()
    engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        audit_emitter=emitter,
    )
    assert len(emitter.records) == 1
    assert emitter.records[0].trigger == "capability-token-rotation"
    # Anti-Drift: trigger MUST NOT collide with the other marker-families.
    assert emitter.records[0].trigger != "sealing"
    assert emitter.records[0].trigger != "sign-off"
    assert emitter.records[0].trigger != "snapshot-restore"


def test_welle_5_capability_token_audit_canonical_bytes(tmp_path):
    """Audit-record canonical-bytes MUST be stable for the Welle-5 path.

    The capability-token enforce-mode flip (audit-only-mode ->
    enforce-mode) binds to Welle-5 per kw-24-welle-1-7-acceptance-
    criteria §5. The audit-stream that captures this binding MUST be
    canonical-byte-stable across direct-producer vs. top-level-handler
    dispatch paths (Doppelbetrieb-Vergleich invariant; the dispatch-shim
    MUST NOT alter the audit-stream).
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    emitter = _RecordingEmitter()
    record = engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        audit_emitter=emitter,
    )
    canonical = record.to_json_bytes()
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed == {
        "cutover_iso": "2026-06-19T08:00:00Z",
        "new_status": STATUS_SIGNED_OFF,
        "prior_status": STATUS_IN_PROGRESS,
        "signoff_iso": "2026-06-19T15:00:00Z",
        "trigger": "capability-token-rotation",
        "welle_number": 5,
    }
    # Single record (no spurious double-emit through the wrapper).
    assert [r.trigger for r in emitter.records] == [
        "capability-token-rotation"
    ]


# ---------------------------------------------------------------------------
# Async wrapper (engine_async.py).
# ---------------------------------------------------------------------------


def test_async_handle_welle_5_signoff_event_delegates(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    emitter = _RecordingEmitter()

    async def _run():
        return await engine_async_mod.handle_welle_5_signoff_event(
            state_dir,
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
            audit_emitter=emitter,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["welle_number"] == 5
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.trigger == "capability-token-rotation"
    assert emitter.records == [record]


def test_async_handle_welle_5_signoff_event_refuses_without_rotation_marker(
    tmp_path,
):
    """The rotation-marker gate MUST be enforced via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")

    async def _run():
        await engine_async_mod.handle_welle_5_signoff_event(
            state_dir,
            signoff_iso="2026-06-19T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status="not-rotated",
        )

    with pytest.raises(CapabilityTokenRotationError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Cross-state interactions: rollback after Welle-5 sign-off still allowed.
# ---------------------------------------------------------------------------


def test_welle_5_can_be_rolled_back_post_sign_off(tmp_path):
    """After a Welle-5 sign-off the post-sign-off rollback transition
    (``signed-off -> rolled-back``) MUST still be available.

    This pins plan-doc §3.1 ``signed-off -> rolled-back`` invariant
    on the Welle-5 substrate -- the capability-token-rotation-marker
    gate does not change the rollback-substrate's behaviour (rollback
    is gated by its own ``rollback-authorized`` marker).
    """
    from wirelang.persona_engine.welle_state_producer import (
        ROLLBACK_MARKER_AUTHORIZED,
    )

    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 5, "2026-06-19T08:00:00Z")
    engine_mod.handle_welle_5_signoff_event(
        state_dir,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    assert json.loads(target.read_text())["status"] == STATUS_SIGNED_OFF
    # Post-sign-off rollback.
    rollback_record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=5,
        rollback_iso="2026-06-20T10:00:00Z",
        rollback_marker_status=ROLLBACK_MARKER_AUTHORIZED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_ROLLED_BACK
    # signoff_iso preserved on rollback for forensic audit-trail.
    assert on_disk["signoff_iso"] == "2026-06-19T15:00:00Z"
    assert rollback_record.prior_status == STATUS_SIGNED_OFF
    assert rollback_record.new_status == STATUS_ROLLED_BACK
    assert rollback_record.trigger == "rollback"


# ---------------------------------------------------------------------------
# Marker-family disambiguation: trigger field across the four Welle families.
# ---------------------------------------------------------------------------


def test_marker_family_triggers_are_pairwise_distinct_across_four_families(
    tmp_path,
):
    """Across the four marker-guarded sign-off paths the audit-trigger
    MUST be a distinct literal per family.

    Family A (Welle-2 Doppelbetrieb-Sealing)   -> trigger="sealing"
    Family B (Welle-3/7 Pre-Auditor)            -> trigger="sign-off"
    Family C (Welle-4 Snapshot-Restore)         -> trigger="snapshot-restore"
    Family D (Welle-5 Capability-Token)         -> trigger="capability-token-rotation"

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
    # Family D: Welle-5 capability-token (Tag-73).
    state_dir_5 = tmp_path / "state_5"
    _seed_in_progress(state_dir_5, 5, "2026-06-19T08:00:00Z")
    rec_5 = engine_mod.handle_welle_5_signoff_event(
        state_dir_5,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    triggers = {rec_2.trigger, rec_3.trigger, rec_4.trigger, rec_5.trigger}
    assert triggers == {
        "sealing",
        "sign-off",
        "snapshot-restore",
        "capability-token-rotation",
    }
    # All four are signed-off transitions (new_status uniform).
    assert {
        rec_2.new_status,
        rec_3.new_status,
        rec_4.new_status,
        rec_5.new_status,
    } == {STATUS_SIGNED_OFF}


def test_welle_5_signoff_time_invariant_cutover_le_signoff(tmp_path):
    """Plan-doc §3.4 time-invariant MUST hold across the Welle-5 path:
    ``cutover_iso <= signoff_iso``. A backwards-in-time sign-off (before
    cutover) MUST be refused.
    """
    from wirelang.persona_engine.welle_state_producer import (
        TimeInvariantViolationError,
    )

    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 5, "2026-06-19T15:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_welle_5_signoff_event(
            # signoff strictly before cutover -> refused.
            signoff_iso="2026-06-19T08:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
        )
