# SPDX-License-Identifier: BUSL-1.1
"""Tests for Multi-Marker-Policy-Composition (Sprint-8 Tag-3).

Covers reduction-paths for the four marker families
(``RevokeEvent``, ``UnrevokeEvent``, ``ReIssuanceEvent``,
``CaveatOverrideEvent``, ``BridgeRevokedEvent``) under
:func:`wirelang.federation.marker_composition.reduce_marker_stack`.

Test naming convention: ``T-MC-NN`` for the canonical reduction
paths, ``T-MC-edge-NN`` for the edge cases. All tests are pure
(no I/O, no clock, no mocked NATS).

Cross-review-hook: Tests do NOT depend on the
:class:`UnrevokeAuditMarker` envelope-layer dataclass from
:mod:`wirelang.schemas.capability_policy_nats_kv_backend`; the
composition axis runs on its own event surface that mirrors the
envelope semantics without coupling to the NATS-KV record.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wirelang.federation.cross_org_attenuation_verifier import (
    BridgeRevocationMarker,
)
from wirelang.federation.marker_composition import (
    AuditTraceEntry,
    BridgeRevokedEvent,
    CaveatOverrideEvent,
    CompositionState,
    CompositionVerdict,
    EffectiveVerdict,
    MarkerCompositionArgumentError,
    MarkerCompositionConflictError,
    MarkerStack,
    ReIssuanceEvent,
    RevokeEvent,
    UnrevokeEvent,
    reduce_marker_stack,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


T0 = datetime(2026, 5, 13, 1, 0, tzinfo=timezone.utc)


def _t(offset_minutes: int) -> datetime:
    return T0 + timedelta(minutes=offset_minutes)


CAVEAT_ORIGINAL = (
    ("peer_org", ("org-a", "org-b")),
    ("max_depth", (3,)),
)
CAVEAT_NARROWED = (("peer_org", ("org-a", "org-b")),)


# ---------------------------------------------------------------------------
# T-MC-01: empty stack -> ACTIVE
# ---------------------------------------------------------------------------


def test_t_mc_01_empty_stack_yields_active() -> None:
    stack = MarkerStack(
        token_id="tok-1",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.effective == EffectiveVerdict.ACTIVE
    assert verdict.bridge_blocked is False
    assert verdict.revoked_at is None
    assert verdict.revocation_reason is None
    assert verdict.new_token_id is None
    assert verdict.narrowed_caveat_set is None
    assert verdict.audit_trace == ()
    assert verdict.wat_anchor_chain == ()


# ---------------------------------------------------------------------------
# T-MC-02: single revoke -> REVOKED
# ---------------------------------------------------------------------------


def test_t_mc_02_single_revoke_yields_revoked() -> None:
    revoke = RevokeEvent(
        event_at=_t(10),
        revocation_reason="operator-test",
        wat_anchor_manifest_id="manifest-1",
    )
    stack = MarkerStack(
        token_id="tok-2",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke,),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.REVOKED
    assert verdict.effective == EffectiveVerdict.REVOKED
    assert verdict.revoked_at == _t(10)
    assert verdict.revocation_reason == "operator-test"
    assert verdict.audit_trace == (
        AuditTraceEntry(
            event_at=_t(10),
            tie_break=0,
            event_kind="revoke",
            outcome="transition:active->revoked",
            wat_anchor_manifest_id="manifest-1",
        ),
    )
    assert verdict.wat_anchor_chain == ("manifest-1",)


# ---------------------------------------------------------------------------
# T-MC-03: revoke + unrevoke -> ACTIVE (with audit trace)
# ---------------------------------------------------------------------------


def test_t_mc_03_revoke_then_unrevoke_yields_active_with_audit() -> None:
    revoke = RevokeEvent(event_at=_t(10), revocation_reason="rollback")
    unrevoke = UnrevokeEvent(
        event_at=_t(20),
        previous_revoked_at=_t(10),
        unrevoke_reason="operator-deliberate",
    )
    stack = MarkerStack(
        token_id="tok-3",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, unrevoke),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.effective == EffectiveVerdict.ACTIVE
    assert verdict.revoked_at is None
    assert verdict.revocation_reason is None
    assert len(verdict.audit_trace) == 2
    assert verdict.audit_trace[0].event_kind == "revoke"
    assert verdict.audit_trace[0].outcome == "transition:active->revoked"
    assert verdict.audit_trace[1].event_kind == "unrevoke"
    assert verdict.audit_trace[1].outcome == "transition:revoked->active"


# ---------------------------------------------------------------------------
# T-MC-04: revoke + re-issuance -> RE_ISSUED (terminal)
# ---------------------------------------------------------------------------


def test_t_mc_04_revoke_then_reissuance_yields_re_issued() -> None:
    revoke = RevokeEvent(event_at=_t(10), revocation_reason="key-rotation")
    reissue = ReIssuanceEvent(
        event_at=_t(20),
        new_token_id="tok-4-v2",
        re_issuance_reason="key-rotation",
    )
    stack = MarkerStack(
        token_id="tok-4",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, reissue),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.RE_ISSUED
    assert verdict.effective == EffectiveVerdict.RE_ISSUED
    assert verdict.new_token_id == "tok-4-v2"
    assert verdict.revoked_at is None
    assert verdict.audit_trace[1].outcome == (
        "transition:revoked->re_issued(new_token_id='tok-4-v2')"
    )


# ---------------------------------------------------------------------------
# T-MC-05: bridge revoked before mint -> BRIDGE_BLOCKED
# ---------------------------------------------------------------------------


def test_t_mc_05_bridge_revoked_before_mint_yields_bridge_blocked() -> None:
    # Bridge revoked at T0-5min (strictly before mint T0).
    # bridge_was_revoked_for_mint uses revoked_at <= minted_at => True.
    marker = BridgeRevocationMarker(
        source_ftd_id="ftd-a",
        target_ftd_id="ftd-b",
        revoked_at=_t(-5),
    )
    bridge = BridgeRevokedEvent(marker=marker, wat_anchor_manifest_id="m-br-1")
    stack = MarkerStack(
        token_id="tok-5",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(bridge,),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.bridge_blocked is True
    assert verdict.effective == EffectiveVerdict.BRIDGE_BLOCKED
    assert verdict.audit_trace[0].event_kind == "bridge_revoked"
    assert verdict.audit_trace[0].outcome == "bridge_block_armed"
    assert verdict.wat_anchor_chain == ("m-br-1",)


# ---------------------------------------------------------------------------
# T-MC-06: bridge revoked AFTER mint -> ACTIVE (bridge block skipped)
# ---------------------------------------------------------------------------


def test_t_mc_06_bridge_revoked_after_mint_yields_active() -> None:
    marker = BridgeRevocationMarker(
        source_ftd_id="ftd-a",
        target_ftd_id="ftd-b",
        revoked_at=_t(10),  # strictly after mint at T0
    )
    bridge = BridgeRevokedEvent(marker=marker)
    stack = MarkerStack(
        token_id="tok-6",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(bridge,),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.bridge_blocked is False
    assert verdict.effective == EffectiveVerdict.ACTIVE
    assert verdict.audit_trace[0].outcome == "bridge_block_skipped:revoked_after_mint"


# ---------------------------------------------------------------------------
# T-MC-07: caveat-override -> CAVEAT_OVERRIDDEN with narrowed set
# ---------------------------------------------------------------------------


def test_t_mc_07_caveat_override_yields_caveat_overridden() -> None:
    override = CaveatOverrideEvent(
        event_at=_t(15),
        original_caveat_set=CAVEAT_ORIGINAL,
        narrowed_caveat_set=CAVEAT_NARROWED,
        override_reason="issuer-narrowed-policy",
    )
    stack = MarkerStack(
        token_id="tok-7",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(override,),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.CAVEAT_OVERRIDDEN
    assert verdict.effective == EffectiveVerdict.CAVEAT_OVERRIDDEN
    assert verdict.narrowed_caveat_set == CAVEAT_NARROWED
    assert verdict.audit_trace[0].event_kind == "caveat_override"


# ---------------------------------------------------------------------------
# T-MC-08: complex lifecycle - revoke + unrevoke + bridge-block
# ---------------------------------------------------------------------------


def test_t_mc_08_revoke_unrevoke_bridge_block_yields_bridge_blocked() -> None:
    # Lifecycle ends ACTIVE; bridge revoked before mint => BRIDGE_BLOCKED.
    marker = BridgeRevocationMarker(
        source_ftd_id="ftd-a",
        target_ftd_id="ftd-b",
        revoked_at=_t(-5),
    )
    bridge = BridgeRevokedEvent(marker=marker)
    revoke = RevokeEvent(event_at=_t(10))
    unrevoke = UnrevokeEvent(event_at=_t(20), previous_revoked_at=_t(10))
    stack = MarkerStack(
        token_id="tok-8",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, bridge, unrevoke),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.bridge_blocked is True
    assert verdict.effective == EffectiveVerdict.BRIDGE_BLOCKED
    # Bridge sorts to position 0 by event_at (-5 < 10 < 20).
    assert verdict.audit_trace[0].event_kind == "bridge_revoked"
    assert verdict.audit_trace[1].event_kind == "revoke"
    assert verdict.audit_trace[2].event_kind == "unrevoke"


# ---------------------------------------------------------------------------
# T-MC-09: revoke + bridge_block (no unrevoke) -> REVOKED takes precedence
# ---------------------------------------------------------------------------


def test_t_mc_09_revoke_plus_bridge_yields_revoked() -> None:
    marker = BridgeRevocationMarker(
        source_ftd_id="ftd-a",
        target_ftd_id="ftd-b",
        revoked_at=_t(-5),
    )
    bridge = BridgeRevokedEvent(marker=marker)
    revoke = RevokeEvent(event_at=_t(10), revocation_reason="revoked-with-bridge")
    stack = MarkerStack(
        token_id="tok-9",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, bridge),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.REVOKED
    assert verdict.bridge_blocked is True
    # REVOKED supersedes BRIDGE_BLOCKED in the effective fold.
    assert verdict.effective == EffectiveVerdict.REVOKED
    assert verdict.revocation_reason == "revoked-with-bridge"


# ---------------------------------------------------------------------------
# T-MC-10: determinism - same stack reduces byte-equal across calls
# ---------------------------------------------------------------------------


def test_t_mc_10_determinism_byte_equal_across_calls() -> None:
    revoke = RevokeEvent(event_at=_t(10), revocation_reason="a")
    unrevoke = UnrevokeEvent(event_at=_t(20), previous_revoked_at=_t(10))
    stack = MarkerStack(
        token_id="tok-10",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, unrevoke),
    )
    v1 = reduce_marker_stack(stack)
    v2 = reduce_marker_stack(stack)
    assert v1 == v2


# ---------------------------------------------------------------------------
# T-MC-11: out-of-order arrivals reduce by event_at (sort-stable)
# ---------------------------------------------------------------------------


def test_t_mc_11_out_of_order_events_sort_to_same_verdict() -> None:
    revoke = RevokeEvent(event_at=_t(10))
    unrevoke = UnrevokeEvent(event_at=_t(20), previous_revoked_at=_t(10))
    # Insert in reverse arrival order.
    stack_forward = MarkerStack(
        token_id="tok-11",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, unrevoke),
    )
    stack_reverse = MarkerStack(
        token_id="tok-11",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(unrevoke, revoke),
    )
    v_forward = reduce_marker_stack(stack_forward)
    v_reverse = reduce_marker_stack(stack_reverse)
    assert v_forward == v_reverse
    assert v_forward.state == CompositionState.ACTIVE


# ---------------------------------------------------------------------------
# T-MC-12: complex 4-marker lifecycle (revoke -> unrevoke -> revoke -> re-issuance)
# ---------------------------------------------------------------------------


def test_t_mc_12_full_lifecycle_revoke_unrevoke_revoke_reissuance() -> None:
    r1 = RevokeEvent(event_at=_t(10), revocation_reason="first")
    u1 = UnrevokeEvent(event_at=_t(20), previous_revoked_at=_t(10))
    r2 = RevokeEvent(event_at=_t(30), revocation_reason="key-rotation")
    ri = ReIssuanceEvent(
        event_at=_t(40),
        new_token_id="tok-12-v2",
        re_issuance_reason="key-rotation",
    )
    stack = MarkerStack(
        token_id="tok-12",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(r1, u1, r2, ri),
    )
    verdict = reduce_marker_stack(stack)
    assert verdict.state == CompositionState.RE_ISSUED
    assert verdict.effective == EffectiveVerdict.RE_ISSUED
    assert verdict.new_token_id == "tok-12-v2"
    assert len(verdict.audit_trace) == 4
    assert [e.event_kind for e in verdict.audit_trace] == [
        "revoke",
        "unrevoke",
        "revoke",
        "re_issuance",
    ]


# ---------------------------------------------------------------------------
# T-MC-edge-01: unrevoke with mismatched previous_revoked_at raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_01_unrevoke_mismatched_previous_raises_conflict() -> None:
    revoke = RevokeEvent(event_at=_t(10))
    unrevoke = UnrevokeEvent(event_at=_t(20), previous_revoked_at=_t(11))
    stack = MarkerStack(
        token_id="tok-e1",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, unrevoke),
    )
    with pytest.raises(
        MarkerCompositionConflictError, match="does not match"
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-02: re-issuance on active token raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_02_reissuance_on_active_raises_conflict() -> None:
    ri = ReIssuanceEvent(event_at=_t(10), new_token_id="tok-e2-v2")
    stack = MarkerStack(
        token_id="tok-e2",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(ri,),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="re-issuance requires a prior revoke",
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-03: caveat-override with broken causal chain raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_03_caveat_override_mismatched_original_raises_conflict() -> None:
    other = (("max_depth", (5,)),)
    override = CaveatOverrideEvent(
        event_at=_t(10),
        original_caveat_set=other,
        narrowed_caveat_set=CAVEAT_NARROWED,
    )
    stack = MarkerStack(
        token_id="tok-e3",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(override,),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="caveat causal-chain is broken",
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-04: duplicate ordering key raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_04_duplicate_ordering_key_raises_conflict() -> None:
    r1 = RevokeEvent(event_at=_t(10), tie_break=0)
    # Same event_at + same tie_break => non-deterministic ordering.
    r2 = RevokeEvent(event_at=_t(10), tie_break=0, revocation_reason="dup")
    stack = MarkerStack(
        token_id="tok-e4",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(r1, r2),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="duplicate ordering key",
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-05: argument validation - naive datetime raises ArgumentError
# ---------------------------------------------------------------------------


def test_t_mc_edge_05_naive_datetime_raises_argument_error() -> None:
    with pytest.raises(
        MarkerCompositionArgumentError,
        match="must be timezone-aware",
    ):
        RevokeEvent(event_at=datetime(2026, 5, 13, 1, 0))


# ---------------------------------------------------------------------------
# T-MC-edge-06: caveat override without original_caveat_set raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_06_caveat_override_without_original_raises_conflict() -> None:
    override = CaveatOverrideEvent(
        event_at=_t(10),
        original_caveat_set=CAVEAT_ORIGINAL,
        narrowed_caveat_set=CAVEAT_NARROWED,
    )
    stack = MarkerStack(
        token_id="tok-e6",
        minted_at=T0,
        original_caveat_set=None,
        events=(override,),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="requires MarkerStack.original_caveat_set",
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-07: revoke after re-issuance raises (terminal state)
# ---------------------------------------------------------------------------


def test_t_mc_edge_07_revoke_after_reissuance_raises_conflict() -> None:
    revoke = RevokeEvent(event_at=_t(10))
    reissue = ReIssuanceEvent(event_at=_t(20), new_token_id="tok-e7-v2")
    revoke2 = RevokeEvent(event_at=_t(30))
    stack = MarkerStack(
        token_id="tok-e7",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, reissue, revoke2),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="terminal state 're_issued'",
    ):
        reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# T-MC-edge-08: unrevoke not strictly after revoke raises
# ---------------------------------------------------------------------------


def test_t_mc_edge_08_unrevoke_at_same_event_at_raises_conflict() -> None:
    # Same event_at but different tie_break to bypass duplicate-key check.
    revoke = RevokeEvent(event_at=_t(10), tie_break=0)
    unrevoke = UnrevokeEvent(
        event_at=_t(10), previous_revoked_at=_t(10), tie_break=1
    )
    stack = MarkerStack(
        token_id="tok-e8",
        minted_at=T0,
        original_caveat_set=CAVEAT_ORIGINAL,
        events=(revoke, unrevoke),
    )
    with pytest.raises(
        MarkerCompositionConflictError,
        match="not strictly after prior revoke",
    ):
        reduce_marker_stack(stack)
