# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-74 - Welle-6 Cross-Substrate-Parity Producer + W5-Anchor-Fix (Selin).

Tag-69 (PR #438) shipped Welle-1 producer-path. Tag-70 (PR #444) shipped
Welle-2 Doppelbetrieb-Sealing + Rollback-Writer. Tag-71 (PR #451) wired
the top-level handlers + Welle-3 Bridge-Audit sign-off shorthand.
Tag-72 (PR #458) added the Welle-4 State-Backing sign-off shorthand.
Tag-73 (PR #465) added the Welle-5 Capability-Token sign-off shorthand.
Tag-74 (this PR) does two things:

1. **W5-Anchor-Fix:** the Tag-68 render-helper-default mapped Welle-4
   and Welle-5 to ``KW-25``; the operational Source-of-Truth
   ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3 table
   places both on ``KW-26`` (Doppel-Welle-4+5 cutover-Mittwoch
   2026-06-24, sign-off-Freitag 2026-06-26). The Tag-74 fix aligns the
   helper-default + committed state-files; the reconciliation rule is
   captured in ``docs/persona-engine/welle-5-kw-anchor-reconciliation-
   tag74.md``.
2. **Welle-6 Cross-Substrate-Parity sign-off** shorthand: a new
   producer-method + top-level sync/async handler-pair gated by the
   ``cross_substrate_parity_marker_status == "verified"`` precondition.
   Audit-record carries ``trigger="cross-substrate-parity"`` (a fifth
   disjoint trigger family).

Scope (Tag-74)
--------------

One new producer-method:

* ``WelleStateProducer.handle_welle_6_signoff_event`` -- structural
  in-progress -> signed-off transition gated by two markers:
  ``sign_off_marker_status == "signed-off"`` AND
  ``cross_substrate_parity_marker_status == "verified"``. Audit-record
  carries ``trigger="cross-substrate-parity"`` (disambiguates from
  Welle-2 ``trigger="sealing"``, Welle-3/7 ``trigger="sign-off"``,
  Welle-4 ``trigger="snapshot-restore"``, and Welle-5
  ``trigger="capability-token-rotation"``).

One new top-level handler in ``wirelang.persona_engine.engine``:

* ``handle_welle_6_signoff_event`` -- delegates to the producer
  method above with ``welle_number=6`` hard-coded.

And one async wrapper in ``wirelang.persona_engine.engine_async``:

* ``handle_welle_6_signoff_event`` -- runs the sync handler in the
  default loop's thread-pool executor.

Plus a W5-anchor-fix verification block (helper-map + state-file
alignment to the §3 table).

Hermetic envelope
-----------------

No network. No NATS, no SPIRE, no gRPC. No subprocess. Pure in-process
file I/O against ``tmp_path`` fixtures. Mirrors the Tag-69 / Tag-70 /
Tag-71 / Tag-72 / Tag-73 producer-test conventions verbatim.

Scope discipline (Selin)
------------------------

This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), cross-substrate-
parity-workflow design (Tomas + Kai joint surface; this test pins the
engine-side marker-literal contract only), or container-infra
(Kai-Domaene, Zone-J). It pins the Tag-74 Welle-6 sign-off shorthand
and the W5-anchor-fix engine-side alignment; the schema-pin is
unchanged (cross-substrate-parity-iso lives in the audit-stream, not
in the state-file).
"""

from __future__ import annotations

import asyncio
import importlib.util
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
    CapabilityTokenRotationError,
    CrossSubstrateParityError,
    DOPPELBETRIEB_SEALED,
    DOPPELBETRIEB_SEALED_WELLEN,
    PHASE_LITERAL,
    PRE_AUDITOR_GUARDED_WELLEN,
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
    WelleStateProducer,
)


# ---------------------------------------------------------------------------
# Helpers (mirror Tag-69 / Tag-70 / Tag-71 / Tag-72 / Tag-73 layout).
# ---------------------------------------------------------------------------


# Post Tag-74 reconciliation: W4 and W5 anchor moved KW-25 -> KW-26.
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
            "cross_substrate_parity_marker": (
                f"state/welle-{welle_number}-cross-substrate-parity.json"
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


# Repo root for the W5-anchor-fix on-disk verifications.
REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_STUB_PATH = REPO_ROOT / "tooling" / "ci" / "render_engine_state_file_stub.py"
STATE_DIR_ON_DISK = REPO_ROOT / "state"


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "render_engine_state_file_stub_tag74_test",
        HELPER_STUB_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# (1) Public-API surface invariants for Welle-6 (Tag-74).
# ---------------------------------------------------------------------------


def test_welle_6_is_cross_substrate_parity_guarded_constant_pin():
    """Welle-6 MUST be in CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN (Tag-74 §2.7).

    This pins the precondition that the Tag-74 Welle-6 sign-off
    shorthand depends on (cross-substrate-parity-marker gate per
    Tomas' ``cross-substrate-parity-gate`` workflow).
    """
    assert 6 in CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN
    # Welle-6 is the ONLY cross-substrate-parity-guarded Welle.
    assert CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN == frozenset({6})


def test_cross_substrate_parity_verified_literal_is_canonical():
    """The marker authority literal MUST be exactly "verified".

    Mirrors the design of :data:`DOPPELBETRIEB_SEALED` ("sealed"),
    :data:`SNAPSHOT_RESTORE_VERIFIED` ("restored"),
    :data:`CAPABILITY_TOKEN_ROTATED` ("rotated"), and
    :data:`ROLLBACK_MARKER_AUTHORIZED` ("rollback-authorized"). The
    literal is an audit-trail anchor; any drift breaks the operator-
    curated marker contract.
    """
    assert CROSS_SUBSTRATE_PARITY_VERIFIED == "verified"


def test_engine_module_exposes_welle_6_handler():
    """Tag-74: engine.py MUST expose ``handle_welle_6_signoff_event``."""
    assert hasattr(engine_mod, "handle_welle_6_signoff_event")
    assert callable(engine_mod.handle_welle_6_signoff_event)


def test_engine_async_module_exposes_welle_6_handler():
    """Tag-74: engine_async.py MUST expose the async wrapper as coroutine."""
    assert hasattr(engine_async_mod, "handle_welle_6_signoff_event")
    assert inspect.iscoroutinefunction(
        engine_async_mod.handle_welle_6_signoff_event
    )


def test_sync_welle_6_handler_is_not_a_coroutine():
    """The sync handler in engine.py MUST be a plain function."""
    assert not inspect.iscoroutinefunction(
        engine_mod.handle_welle_6_signoff_event
    )


# ---------------------------------------------------------------------------
# (2) Marker-guarded-Wellen-set disjointness (5-family pairwise).
# ---------------------------------------------------------------------------


def test_welle_6_disjoint_from_other_marker_guarded_welle_sets():
    """Welle-6 MUST NOT overlap with the other marker-guarded sets.

    Each marker-guard family (sealing for W2, pre-auditor for W3/W7,
    snapshot-restore for W4, capability-token-rotation for W5, cross-
    substrate-parity for W6) MUST be disjoint -- a single Welle cannot
    have two simultaneous marker-families without ambiguating the
    audit-stream trigger field.
    """
    assert CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN.isdisjoint(
        DOPPELBETRIEB_SEALED_WELLEN
    )
    assert CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN.isdisjoint(
        PRE_AUDITOR_GUARDED_WELLEN
    )
    assert CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN.isdisjoint(
        SNAPSHOT_RESTORE_GUARDED_WELLEN
    )
    assert CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN.isdisjoint(
        CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN
    )


def test_all_five_marker_families_pairwise_disjoint():
    """Each pair of marker-guard families MUST be disjoint (5-choose-2 = 10 pairs).

    This is the structural-level pin that no Welle can be claimed by
    two marker-families simultaneously (audit-trigger disambiguation
    invariant; Henrik Internal Audit Zone-N relies on this).
    """
    families = {
        "sealing": DOPPELBETRIEB_SEALED_WELLEN,
        "pre-auditor": PRE_AUDITOR_GUARDED_WELLEN,
        "snapshot-restore": SNAPSHOT_RESTORE_GUARDED_WELLEN,
        "capability-token-rotation": CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN,
        "cross-substrate-parity": CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN,
    }
    names = sorted(families.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            assert families[a].isdisjoint(families[b]), (
                f"marker-family overlap between {a!r} and {b!r}: "
                f"{families[a]} & {families[b]} = "
                f"{families[a] & families[b]}"
            )


def test_marker_family_union_covers_expected_wellen():
    """The union of all five marker-families MUST be exactly {2,3,4,5,6,7}.

    Welle-1 is the only Welle without a marker-family (Cutover-T0
    first-fire; vanilla sign-off path uses ``handle_sign_off_event``).
    All other Wellen carry a marker-family.
    """
    union = (
        DOPPELBETRIEB_SEALED_WELLEN
        | PRE_AUDITOR_GUARDED_WELLEN
        | SNAPSHOT_RESTORE_GUARDED_WELLEN
        | CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN
        | CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN
    )
    assert union == frozenset({2, 3, 4, 5, 6, 7})


# ---------------------------------------------------------------------------
# (3) Producer-method direct-call tests (handle_welle_6_signoff_event).
# ---------------------------------------------------------------------------


def test_producer_welle_6_signoff_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    record = producer.handle_welle_6_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert on_disk["welle_number"] == 6
    assert on_disk["signoff_iso"] == "2026-07-03T15:00:00Z"
    # Cutover-iso preserved.
    assert on_disk["cutover_iso"] == "2026-07-01T08:00:00Z"

    assert record.welle_number == 6
    assert record.prior_status == STATUS_IN_PROGRESS
    assert record.new_status == STATUS_SIGNED_OFF
    assert record.trigger == "cross-substrate-parity"
    assert emitter.records == [record]


def test_producer_welle_6_signoff_refused_without_parity_marker(tmp_path):
    """A bad parity-marker MUST raise CrossSubstrateParityError."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(CrossSubstrateParityError):
        producer.handle_welle_6_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status="drifted",
        )


def test_producer_welle_6_signoff_refused_with_empty_parity_marker(tmp_path):
    """Empty parity-marker MUST be refused (no implicit defaults)."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(CrossSubstrateParityError):
        producer.handle_welle_6_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status="",
        )


def test_producer_welle_6_signoff_refused_without_sign_off_marker(tmp_path):
    """A bad sign-off marker MUST raise SignOffPreconditionError.

    The two marker preconditions are independent: the sign-off-marker
    guard fires before the parity-marker guard. This pins the
    refusal-order to be identical to the Tag-72 Welle-4 /
    Tag-73 Welle-5 designs.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(SignOffPreconditionError):
        producer.handle_welle_6_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status="pending",
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )


def test_producer_welle_6_signoff_idempotent_double_fire(tmp_path):
    """A second sign-off after the first MUST be a no-op (idempotency)."""
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    producer = WelleStateProducer(state_dir=state_dir, audit_emitter=emitter)
    producer.handle_welle_6_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    # Second fire: idempotent no-op.
    record_2 = producer.handle_welle_6_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    assert record_2.prior_status == STATUS_SIGNED_OFF
    assert record_2.new_status == STATUS_SIGNED_OFF
    assert record_2.trigger == "cross-substrate-parity"
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    # signoff_iso from the first fire is preserved.
    assert on_disk["signoff_iso"] == "2026-07-03T15:00:00Z"
    # Two emitter records: the first transition + the idempotent no-op.
    assert len(emitter.records) == 2


def test_producer_welle_6_signoff_refused_from_pending(tmp_path):
    """Sign-off from ``pending`` MUST be refused (no cutover yet).

    Plan-doc §3.1: the only valid prior state for a sign-off is
    ``in-progress`` (post-Cutover-T0). ``pending -> signed-off`` is
    forbidden.
    """
    from wirelang.persona_engine.welle_state_producer import (
        InvalidStatusTransitionError,
    )

    state_dir = tmp_path / "state"
    _seed_pending(state_dir, 6)
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_6_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )


def test_producer_welle_6_signoff_refused_from_rolled_back(tmp_path):
    """Sign-off from ``rolled-back`` MUST be refused (rolled-back is terminal)."""
    from wirelang.persona_engine.welle_state_producer import (
        InvalidStatusTransitionError,
    )

    state_dir = tmp_path / "state"
    payload = _pending_stub(6)
    payload["status"] = STATUS_ROLLED_BACK
    payload["cutover_iso"] = "2026-07-01T08:00:00Z"
    (state_dir).mkdir(parents=True, exist_ok=True)
    target = state_dir / "welle-6.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(InvalidStatusTransitionError):
        producer.handle_welle_6_signoff_event(
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )


def test_producer_welle_6_signoff_time_invariant_cutover_le_signoff(tmp_path):
    """Plan-doc §3.4 time-invariant MUST hold across the Welle-6 path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-03T15:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    with pytest.raises(TimeInvariantViolationError):
        producer.handle_welle_6_signoff_event(
            # signoff strictly before cutover -> refused.
            signoff_iso="2026-07-01T08:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )


def test_producer_welle_6_signoff_atomic_write_no_partial_state(tmp_path):
    """On a successful Welle-6 sign-off the on-disk file MUST be fully written.

    The producer-substrate uses temp-file + rename(2) for atomic
    writes (plan-doc §3.3). This test verifies the post-write state
    is fully valid JSON with the full nine schema-pin keys.
    """
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    producer.handle_welle_6_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
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
# (4) Top-level sync handler (engine.handle_welle_6_signoff_event).
# ---------------------------------------------------------------------------


def test_sync_handle_welle_6_signoff_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    record = engine_mod.handle_welle_6_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.welle_number == 6
    assert record.trigger == "cross-substrate-parity"


def test_sync_handle_welle_6_signoff_event_emitter_recorded(tmp_path):
    """Custom audit-emitter MUST be invoked exactly once on the happy path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    emitter = _RecordingEmitter()
    engine_mod.handle_welle_6_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        audit_emitter=emitter,
    )
    assert len(emitter.records) == 1
    rec = emitter.records[0]
    assert rec.welle_number == 6
    assert rec.new_status == STATUS_SIGNED_OFF
    assert rec.trigger == "cross-substrate-parity"


def test_sync_handle_welle_6_signoff_event_refuses_without_parity_marker(
    tmp_path,
):
    """The parity-marker gate MUST be enforced via the top-level handler."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    with pytest.raises(CrossSubstrateParityError):
        engine_mod.handle_welle_6_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status="audit-only",
        )


# ---------------------------------------------------------------------------
# (5) Async wrapper (engine_async.handle_welle_6_signoff_event).
# ---------------------------------------------------------------------------


def test_async_handle_welle_6_signoff_event_happy_path(tmp_path):
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")

    async def _run() -> WelleAuditRecord:
        return await engine_async_mod.handle_welle_6_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
        )

    record = asyncio.run(_run())
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["status"] == STATUS_SIGNED_OFF
    assert record.trigger == "cross-substrate-parity"


def test_async_handle_welle_6_signoff_event_refuses_without_parity_marker(
    tmp_path,
):
    """The parity-marker gate MUST be enforced via the async path."""
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")

    async def _run() -> WelleAuditRecord:
        return await engine_async_mod.handle_welle_6_signoff_event(
            state_dir,
            signoff_iso="2026-07-03T15:00:00Z",
            sign_off_marker_status=STATUS_SIGNED_OFF,
            cross_substrate_parity_marker_status="drifted",
        )

    with pytest.raises(CrossSubstrateParityError):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# (6) Cross-state interactions: rollback after Welle-6 sign-off.
# ---------------------------------------------------------------------------


def test_welle_6_can_be_rolled_back_post_sign_off(tmp_path):
    """After a Welle-6 sign-off the ``signed-off -> rolled-back`` MUST hold."""
    state_dir = tmp_path / "state"
    target = _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    engine_mod.handle_welle_6_signoff_event(
        state_dir,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    assert json.loads(target.read_text())["status"] == STATUS_SIGNED_OFF
    rollback_record = engine_mod.handle_welle_rollback_event(
        state_dir,
        welle_number=6,
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
# (7) Five-marker-family trigger pairwise-distinct.
# ---------------------------------------------------------------------------


def test_marker_family_triggers_are_pairwise_distinct_across_five_families(
    tmp_path,
):
    """Across the five marker-guarded sign-off paths the audit-trigger
    MUST be a distinct literal per family.

    Family A (Welle-2 Doppelbetrieb-Sealing)   -> trigger="sealing"
    Family B (Welle-3/7 Pre-Auditor)            -> trigger="sign-off"
    Family C (Welle-4 Snapshot-Restore)         -> trigger="snapshot-restore"
    Family D (Welle-5 Capability-Token)         -> trigger="capability-token-rotation"
    Family E (Welle-6 Cross-Substrate-Parity)   -> trigger="cross-substrate-parity"

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
    _seed_in_progress(state_dir_3, 3, "2026-06-17T08:00:00Z")
    rec_3 = engine_mod.handle_welle_3_signoff_event(
        state_dir_3,
        signoff_iso="2026-06-19T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        pre_auditor_decision="designated",
    )
    # Family C: Welle-4 snapshot-restore (Tag-72).
    state_dir_4 = tmp_path / "state_4"
    _seed_in_progress(state_dir_4, 4, "2026-06-24T08:00:00Z")
    rec_4 = engine_mod.handle_welle_4_signoff_event(
        state_dir_4,
        signoff_iso="2026-06-26T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        snapshot_restore_marker_status=SNAPSHOT_RESTORE_VERIFIED,
    )
    # Family D: Welle-5 capability-token (Tag-73).
    state_dir_5 = tmp_path / "state_5"
    _seed_in_progress(state_dir_5, 5, "2026-06-24T08:00:00Z")
    rec_5 = engine_mod.handle_welle_5_signoff_event(
        state_dir_5,
        signoff_iso="2026-06-26T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        capability_token_rotation_marker_status=CAPABILITY_TOKEN_ROTATED,
    )
    # Family E: Welle-6 cross-substrate-parity (Tag-74, this PR).
    state_dir_6 = tmp_path / "state_6"
    _seed_in_progress(state_dir_6, 6, "2026-07-01T08:00:00Z")
    rec_6 = engine_mod.handle_welle_6_signoff_event(
        state_dir_6,
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    triggers = {
        rec_2.trigger,
        rec_3.trigger,
        rec_4.trigger,
        rec_5.trigger,
        rec_6.trigger,
    }
    assert triggers == {
        "sealing",
        "sign-off",
        "snapshot-restore",
        "capability-token-rotation",
        "cross-substrate-parity",
    }
    # All five are signed-off transitions (new_status uniform).
    assert {
        rec_2.new_status,
        rec_3.new_status,
        rec_4.new_status,
        rec_5.new_status,
        rec_6.new_status,
    } == {STATUS_SIGNED_OFF}
    # Pairwise-distinct cardinality check (the assertion above already
    # implies it, but pin it explicitly for the audit-trail).
    trigger_list = [
        rec_2.trigger,
        rec_3.trigger,
        rec_4.trigger,
        rec_5.trigger,
        rec_6.trigger,
    ]
    assert len(trigger_list) == len(set(trigger_list)) == 5


# ---------------------------------------------------------------------------
# (8) W5-Anchor-Fix verification (Tag-74 Teil 1).
# ---------------------------------------------------------------------------


def test_w5_anchor_fix_helper_module_maps_welle_5_to_kw_26():
    """Tag-74 Teil 1 W5-anchor-fix MUST land in the helper-default map.

    The Source-of-Truth ``pre-cutover-acceptance-run-order.md`` §3
    table (line 96) places Welle-5 on KW-26. The Tag-68 helper-default
    previously mapped Welle-5 to KW-25; Tag-74 aligns it to KW-26.
    """
    module = _load_helper_module()
    assert module.CANONICAL_KW_ANCHOR[5] == "KW-26"


def test_w5_anchor_fix_helper_module_maps_welle_4_to_kw_26():
    """Tag-74 Teil 1 W5-anchor-fix folds Welle-4 alignment as well.

    The §3 table (line 95) places Welle-4 on KW-26 (Doppel-Welle-4+5).
    The Tag-68 helper-default previously mapped Welle-4 to KW-25;
    Tag-74 aligns it to KW-26 in lockstep with the Welle-5 fix.
    """
    module = _load_helper_module()
    assert module.CANONICAL_KW_ANCHOR[4] == "KW-26"


def test_w5_anchor_fix_state_file_welle_5_kw_26_on_disk():
    """The committed ``state/welle-5.json`` MUST report KW-26 post Tag-74."""
    on_disk = json.loads(
        (STATE_DIR_ON_DISK / "welle-5.json").read_text(encoding="utf-8")
    )
    assert on_disk["kw_cutover_anchor"] == "KW-26"


def test_w5_anchor_fix_state_file_welle_4_kw_26_on_disk():
    """The committed ``state/welle-4.json`` MUST report KW-26 post Tag-74."""
    on_disk = json.loads(
        (STATE_DIR_ON_DISK / "welle-4.json").read_text(encoding="utf-8")
    )
    assert on_disk["kw_cutover_anchor"] == "KW-26"


def test_w5_anchor_fix_helper_map_matches_state_files_on_disk():
    """The helper-default map MUST match the committed state-files for ALL Wellen.

    Post Tag-74 this includes the W4+W5 alignment. The
    ``test_state_file_producer_plan_tag68.py::
    test_helper_stub_canonical_kw_anchor_map_matches_disk`` test pins
    this property structurally; this Tag-74 test re-pins it inside the
    Tag-74 test-suite as a defence-in-depth against future drift on
    either side of the helper-default vs state-file boundary.
    """
    module = _load_helper_module()
    for n in range(1, 8):
        on_disk = json.loads(
            (STATE_DIR_ON_DISK / f"welle-{n}.json").read_text(encoding="utf-8")
        )
        assert module.CANONICAL_KW_ANCHOR[n] == on_disk["kw_cutover_anchor"], (
            f"helper-default disagrees with on-disk state for welle-{n}: "
            f"helper={module.CANONICAL_KW_ANCHOR[n]!r} vs "
            f"on-disk={on_disk['kw_cutover_anchor']!r}"
        )


def test_w5_anchor_fix_reconciliation_doc_committed():
    """The Tag-74 reconciliation doc MUST exist at the canonical path."""
    reconciliation_doc = (
        REPO_ROOT
        / "docs"
        / "persona-engine"
        / "welle-5-kw-anchor-reconciliation-tag74.md"
    )
    assert reconciliation_doc.exists(), (
        f"Tag-74 reconciliation doc missing at {reconciliation_doc}; "
        "the engine-side audit-trail anchor for the W4+W5 KW-anchor "
        "alignment lives in this file."
    )
    body = reconciliation_doc.read_text(encoding="utf-8")
    # Pin the Source-of-Truth resolution rule and the W4+W5 KW-26 fix.
    assert "pre-cutover-acceptance-run-order.md" in body
    assert "KW-26" in body
    assert "Welle-5" in body or "welle-5" in body
    assert "Welle-4" in body or "welle-4" in body


# ---------------------------------------------------------------------------
# (9) Audit-record byte-canonical JSON for the Welle-6 record.
# ---------------------------------------------------------------------------


def test_welle_6_audit_record_canonical_json_bytes(tmp_path):
    """The Welle-6 audit-record's canonical-JSON bytes MUST sort keys + UTF-8.

    Mirrors the Tag-69+ audit-record-emitter contract: downstream
    bridge-audit-writer hashing depends on byte-stable canonical JSON.
    """
    state_dir = tmp_path / "state"
    _seed_in_progress(state_dir, 6, "2026-07-01T08:00:00Z")
    producer = WelleStateProducer(state_dir=state_dir)
    record = producer.handle_welle_6_signoff_event(
        signoff_iso="2026-07-03T15:00:00Z",
        sign_off_marker_status=STATUS_SIGNED_OFF,
        cross_substrate_parity_marker_status=CROSS_SUBSTRATE_PARITY_VERIFIED,
    )
    raw = record.to_json_bytes()
    # Canonical JSON: keys sorted, no whitespace separators.
    decoded = json.loads(raw)
    assert decoded == {
        "cutover_iso": "2026-07-01T08:00:00Z",
        "new_status": STATUS_SIGNED_OFF,
        "prior_status": STATUS_IN_PROGRESS,
        "signoff_iso": "2026-07-03T15:00:00Z",
        "trigger": "cross-substrate-parity",
        "welle_number": 6,
    }
    # Byte-stability: re-encoding the decoded dict with sort_keys=True
    # yields the same bytes (modulo separators which we pin here).
    reencoded = json.dumps(
        decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert raw == reencoded


# ---------------------------------------------------------------------------
# (10) CrossSubstrateParityError inherits from WelleProducerError.
# ---------------------------------------------------------------------------


def test_cross_substrate_parity_error_inherits_from_welle_producer_error():
    """All Welle-N marker-guard errors MUST share a common parent.

    This lets callers ``except WelleProducerError`` once and catch
    any marker-guard refusal without needing to enumerate the five
    family-specific subclasses individually.
    """
    from wirelang.persona_engine.welle_state_producer import (
        WelleProducerError,
    )

    assert issubclass(CrossSubstrateParityError, WelleProducerError)
    # And specifically NOT a subclass of any other marker-family error
    # (the five families are independent).
    assert not issubclass(
        CrossSubstrateParityError, CapabilityTokenRotationError
    )
    assert not issubclass(
        CapabilityTokenRotationError, CrossSubstrateParityError
    )
