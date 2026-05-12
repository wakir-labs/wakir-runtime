# SPDX-License-Identifier: Apache-2.0
"""Tests for the Phase-2 Sprint-7 Tag-4 Capability-Attenuation-Chain-
Verifier (``wirelang.federation.capability_attenuation_chain_verifier``).

Test inventory (T-CACV-01..09):

- T-CACV-01 happy-path verify (3-hop local + cross-org chain) ->
  :class:`VerifiedAttenuationChain` with stable ``chain_hash``,
  ``CHAIN_VERIFICATION_SCHEMA`` carried.
- T-CACV-02 attenuation-order violation by index regress ->
  :class:`AttenuationOrderViolationError` with structured
  ``link_position`` / ``previous_index`` / ``current_index``.
- T-CACV-03 attenuation-order violation by issued_at regress ->
  :class:`AttenuationOrderViolationError`.
- T-CACV-04 stale link by ``max_link_age_seconds`` exceeded ->
  :class:`StaleAttenuationReplayError` with ``cause="age_exceeded"``.
- T-CACV-05 stale link by ``expires_at`` past now ->
  :class:`StaleAttenuationReplayError` with ``cause="expired"``.
- T-CACV-06 cross-org boundary violation (pointer not local AND
  not the attested peer pointer) ->
  :class:`CrossOrgBoundaryViolationError`.
- T-CACV-07 cross-org boundary violation (peer resolver returns
  None for attested pointer) ->
  :class:`CrossOrgBoundaryViolationError`.
- T-CACV-08 revoked-link denial (Sprint-6 Tag-1 revocation
  precedence applied per-hop) ->
  :class:`AttenuationLinkRevokedError`.
- T-CACV-09 idempotent re-verify produces byte-equal
  :attr:`VerifiedAttenuationChain.chain_hash` despite different
  ``verified_at``.

All tests are hermetic: no network, no FS. The verifier consumes
Protocol fakes built from the production-module test fixtures
(``_FixedPeerResolver``, ``_RaisingPeerResolver``).

ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pytest

from wirelang.federation.capability_attenuation_chain_verifier import (
    CHAIN_VERIFICATION_SCHEMA,
    DEFAULT_MAX_LINK_AGE_SECONDS,
    AttenuationChainShapeError,
    AttenuationLink,
    AttenuationLinkRevokedError,
    AttenuationOrderViolationError,
    CapabilityAttenuationChainVerifier,
    CrossOrgBoundaryViolationError,
    ResolvedAttenuationLink,
    StaleAttenuationReplayError,
    VerifiedAttenuationChain,
    _FixedPeerResolver,
    _RaisingPeerResolver,
)
from wirelang.federation.multi_org_substrate import (
    MultiOrgRouteAttestation,
)
from wirelang.federation.n2_evaluator import (
    RouteRegistryEntry,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


_NOW = _utc(2026, 5, 12, 22, 0)


def _fixed_clock(now: datetime = _NOW):
    def _clock() -> datetime:
        return now

    return _clock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_ROUTE_ID = "wakir->partner-a->treasury-attenuation-2026-05"
_PEER_TRUST_DOMAIN = "partner-a.example"
_PEER_DID = "did:web:partner-a.example"
_PEER_BUNDLE_URL = "https://partner-a.example/.well-known/spiffe-bundle"
_PEER_POLICY_POINTER = (
    "https://partner-a.example/.well-known/wakir-capability-policy#pa-issuer-2026"
)

_LOCAL_ISSUER = "wakir.local"
_LOCAL_POINTER_A = "wakir.local::policy-a"
_LOCAL_POINTER_B = "wakir.local::policy-b"


def _entry(route_id: str = _ROUTE_ID) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        source_ftd_id="ftd-wakir-2026",
        active_from=_utc(2026, 5, 12),
        active_until=_utc(2027, 5, 12),
        wat_anchor_manifest_id="wat-manifest-2026-05-12",
    )


def _attestation(
    route_id: str = _ROUTE_ID,
    *,
    peer_pointer: Optional[str] = _PEER_POLICY_POINTER,
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        peer_wat_anchor_manifest_id="peer-wat-manifest-2026-05-12",
        peer_trust_bundle_url=_PEER_BUNDLE_URL,
        peer_capability_policy_pointer=peer_pointer,
        is_mock=False,
    )


def _local_policy(
    registered_by: str = _LOCAL_ISSUER,
    *,
    revoked_at: Optional[datetime] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=("kid-2026-05",),
        allowed_triples=(("layer-3-capability-token", "*"),),
        not_before=_utc(2026, 1, 1),
        not_after=_utc(2027, 1, 1),
        disabled=False,
        note=None,
        revoked_at=revoked_at,
        revocation_reason=("test-revocation" if revoked_at else None),
    )


def _peer_policy(
    registered_by: str = "partner-a.example",
    *,
    revoked_at: Optional[datetime] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=("partner-kid-2026",),
        allowed_triples=(("layer-3-capability-token", "*"),),
        not_before=_utc(2026, 1, 1),
        not_after=_utc(2027, 1, 1),
        disabled=False,
        note=None,
        revoked_at=revoked_at,
        revocation_reason=("test-revocation" if revoked_at else None),
    )


def _local_registry_with_policies(
    *policies: CapabilityPolicy,
) -> CapabilityPolicyRegistry:
    registry = CapabilityPolicyRegistry()
    for p in policies:
        registry.add_policy(p)
    return registry


def _three_hop_chain(
    *,
    now: datetime = _NOW,
) -> Tuple[AttenuationLink, ...]:
    """A canonical 3-hop chain: two local hops then one cross-org
    hop landing on the attested peer pointer."""
    base = now - timedelta(minutes=30)
    return (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base,
            expires_at=base + timedelta(hours=2),
            registered_by=_LOCAL_ISSUER,
        ),
        AttenuationLink(
            attenuation_index=1,
            policy_pointer=_LOCAL_POINTER_B,
            issued_at=base + timedelta(minutes=5),
            expires_at=base + timedelta(hours=2),
            registered_by=_LOCAL_ISSUER,
        ),
        AttenuationLink(
            attenuation_index=2,
            policy_pointer=_PEER_POLICY_POINTER,
            issued_at=base + timedelta(minutes=10),
            expires_at=base + timedelta(hours=2),
            registered_by=None,
        ),
    )


def _build_verifier(
    *,
    registry: Optional[CapabilityPolicyRegistry] = None,
    peer_policies: Optional[dict] = None,
    peer_resolver=None,
    max_link_age_seconds: int = DEFAULT_MAX_LINK_AGE_SECONDS,
    clock=None,
) -> CapabilityAttenuationChainVerifier:
    reg = registry if registry is not None else _local_registry_with_policies(
        _local_policy(),
    )
    if peer_resolver is None and peer_policies is not None:
        peer_resolver = _FixedPeerResolver(policies=peer_policies)
    return CapabilityAttenuationChainVerifier(
        source_registry=reg,
        peer_resolver=peer_resolver,
        max_link_age_seconds=max_link_age_seconds,
        clock=clock or _fixed_clock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_t_cacv_01_happy_path_three_hop_local_plus_cross_org() -> None:
    """A well-formed 3-hop chain (two local hops + one cross-org
    hop landing on the attested peer pointer) yields a
    :class:`VerifiedAttenuationChain` with the schema URI carried
    and a non-empty chain hash.
    """
    verifier = _build_verifier(
        peer_policies={
            (_ROUTE_ID, _PEER_POLICY_POINTER): _peer_policy(),
        },
    )
    result = verifier.verify(
        entry=_entry(),
        attestation=_attestation(),
        chain=_three_hop_chain(),
    )
    assert isinstance(result, VerifiedAttenuationChain)
    assert result.attestation_route_id == _ROUTE_ID
    assert result.chain_schema == CHAIN_VERIFICATION_SCHEMA
    assert isinstance(result.chain_hash, bytes)
    assert len(result.chain_hash) == 32  # BLAKE2b-256
    assert len(result.resolved_links) == 3
    # The first two hops resolve locally, the third hop crosses.
    assert result.resolved_links[0].is_cross_org is False
    assert result.resolved_links[1].is_cross_org is False
    assert result.resolved_links[2].is_cross_org is True
    for rl in result.resolved_links:
        assert isinstance(rl, ResolvedAttenuationLink)
        assert isinstance(rl.policy, CapabilityPolicy)
    assert result.verified_at == _NOW
    assert result.max_link_age_seconds == DEFAULT_MAX_LINK_AGE_SECONDS


def test_t_cacv_02_attenuation_order_violation_index_regress() -> None:
    """A chain whose ``attenuation_index`` regresses (or stalls)
    surfaces as :class:`AttenuationOrderViolationError` with the
    offending positions carried structurally.
    """
    base = _NOW - timedelta(minutes=30)
    bad_chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base,
            registered_by=_LOCAL_ISSUER,
        ),
        AttenuationLink(
            attenuation_index=5,
            policy_pointer=_LOCAL_POINTER_B,
            issued_at=base + timedelta(minutes=1),
            registered_by=_LOCAL_ISSUER,
        ),
        AttenuationLink(
            # Index regress: 5 -> 3.
            attenuation_index=3,
            policy_pointer=_PEER_POLICY_POINTER,
            issued_at=base + timedelta(minutes=2),
        ),
    )
    verifier = _build_verifier(
        peer_policies={
            (_ROUTE_ID, _PEER_POLICY_POINTER): _peer_policy(),
        },
    )
    with pytest.raises(AttenuationOrderViolationError) as excinfo:
        verifier.verify(
            entry=_entry(), attestation=_attestation(), chain=bad_chain
        )
    assert excinfo.value.link_position == 2
    assert excinfo.value.previous_index == 5
    assert excinfo.value.current_index == 3
    assert "strictly greater" in str(excinfo.value)


def test_t_cacv_03_attenuation_order_violation_issued_at_regress() -> None:
    """A chain whose ``attenuation_index`` is monotonic but whose
    ``issued_at`` regresses surfaces as
    :class:`AttenuationOrderViolationError` (weak-monotonicity is
    required on ``issued_at``).
    """
    base = _NOW - timedelta(minutes=30)
    bad_chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base + timedelta(minutes=10),
            registered_by=_LOCAL_ISSUER,
        ),
        AttenuationLink(
            attenuation_index=1,
            # issued_at regress: earlier than predecessor.
            policy_pointer=_LOCAL_POINTER_B,
            issued_at=base,
            registered_by=_LOCAL_ISSUER,
        ),
    )
    verifier = _build_verifier()
    with pytest.raises(AttenuationOrderViolationError) as excinfo:
        verifier.verify(
            entry=_entry(),
            attestation=_attestation(peer_pointer=None),
            chain=bad_chain,
        )
    assert excinfo.value.link_position == 1
    assert "weakly monotonically non-decreasing" in str(excinfo.value)


def test_t_cacv_04_stale_link_age_exceeded() -> None:
    """A link older than ``max_link_age_seconds`` surfaces as
    :class:`StaleAttenuationReplayError` with
    ``cause="age_exceeded"``.
    """
    # max_link_age = 1 h (default). Make the first hop 3 h old.
    base = _NOW - timedelta(hours=3)
    bad_chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base,
            expires_at=_NOW + timedelta(hours=2),  # future expiry
            registered_by=_LOCAL_ISSUER,
        ),
    )
    verifier = _build_verifier()
    with pytest.raises(StaleAttenuationReplayError) as excinfo:
        verifier.verify(
            entry=_entry(),
            attestation=_attestation(peer_pointer=None),
            chain=bad_chain,
        )
    assert excinfo.value.cause == "age_exceeded"
    assert excinfo.value.link_position == 0
    assert excinfo.value.max_age_seconds == DEFAULT_MAX_LINK_AGE_SECONDS


def test_t_cacv_05_stale_link_expires_at_past() -> None:
    """A link whose ``expires_at`` is at or before ``now`` surfaces
    as :class:`StaleAttenuationReplayError` with
    ``cause="expired"`` (even if age is within ceiling).
    """
    base = _NOW - timedelta(minutes=10)
    bad_chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base,
            # Expires 1 minute before now.
            expires_at=_NOW - timedelta(minutes=1),
            registered_by=_LOCAL_ISSUER,
        ),
    )
    verifier = _build_verifier()
    with pytest.raises(StaleAttenuationReplayError) as excinfo:
        verifier.verify(
            entry=_entry(),
            attestation=_attestation(peer_pointer=None),
            chain=bad_chain,
        )
    assert excinfo.value.cause == "expired"
    assert excinfo.value.link_position == 0


def test_t_cacv_06_cross_org_boundary_pointer_not_in_either_surface() -> None:
    """A link whose ``policy_pointer`` is neither local nor the
    attested peer pointer surfaces as
    :class:`CrossOrgBoundaryViolationError` with the offending
    pointer carried structurally.
    """
    base = _NOW - timedelta(minutes=10)
    bad_chain = (
        AttenuationLink(
            attenuation_index=0,
            # Not a local pointer (no ``::``) and not the attested
            # peer pointer either.
            policy_pointer=(
                "https://attacker.example/.well-known/graft-policy#x"
            ),
            issued_at=base,
            expires_at=_NOW + timedelta(hours=1),
        ),
    )
    verifier = _build_verifier(
        peer_policies={
            (_ROUTE_ID, _PEER_POLICY_POINTER): _peer_policy(),
        },
    )
    with pytest.raises(CrossOrgBoundaryViolationError) as excinfo:
        verifier.verify(
            entry=_entry(), attestation=_attestation(), chain=bad_chain
        )
    assert excinfo.value.link_position == 0
    assert (
        excinfo.value.offending_pointer
        == "https://attacker.example/.well-known/graft-policy#x"
    )
    assert excinfo.value.attested_peer_pointer == _PEER_POLICY_POINTER


def test_t_cacv_07_cross_org_boundary_peer_resolver_returns_none() -> None:
    """A link whose ``policy_pointer`` matches the attested peer
    pointer but the peer resolver returns ``None`` (i.e. the
    pointer was rotated away on the peer side, or the peer
    rejects the lookup) surfaces as
    :class:`CrossOrgBoundaryViolationError`.
    """
    base = _NOW - timedelta(minutes=10)
    chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_PEER_POLICY_POINTER,
            issued_at=base,
            expires_at=_NOW + timedelta(hours=1),
        ),
    )
    # Peer resolver with EMPTY policies dict -> resolve returns
    # None for every lookup.
    verifier = _build_verifier(peer_policies={})
    with pytest.raises(CrossOrgBoundaryViolationError) as excinfo:
        verifier.verify(
            entry=_entry(), attestation=_attestation(), chain=chain
        )
    assert "not found at peer" in str(excinfo.value)
    assert excinfo.value.offending_pointer == _PEER_POLICY_POINTER


def test_t_cacv_08_revoked_link_denial() -> None:
    """A chain whose hop resolves to a revoked policy (Sprint-6
    Tag-1 revocation precedence) surfaces as
    :class:`AttenuationLinkRevokedError`.

    Scenario: the local policy was revoked in the past relative to
    the link's ``issued_at``; the link could not legitimately have
    been minted under that policy.
    """
    # Local policy revoked an hour BEFORE the link is minted.
    revocation_instant = _NOW - timedelta(hours=2)
    revoked_local_policy = _local_policy(revoked_at=revocation_instant)
    registry = _local_registry_with_policies(revoked_local_policy)

    # Link minted 30 min ago, after revocation.
    base = _NOW - timedelta(minutes=30)
    chain = (
        AttenuationLink(
            attenuation_index=0,
            policy_pointer=_LOCAL_POINTER_A,
            issued_at=base,
            expires_at=_NOW + timedelta(hours=1),
            registered_by=_LOCAL_ISSUER,
        ),
    )
    verifier = _build_verifier(registry=registry)
    with pytest.raises(AttenuationLinkRevokedError) as excinfo:
        verifier.verify(
            entry=_entry(),
            attestation=_attestation(peer_pointer=None),
            chain=chain,
        )
    assert excinfo.value.link_position == 0
    assert excinfo.value.revoked_at == revocation_instant
    assert excinfo.value.revocation_reason == "test-revocation"


def test_t_cacv_09_idempotent_re_verify_byte_equal_chain_hash() -> None:
    """Verifying the same (entry, attestation, chain) twice at
    different wall-clock instants yields byte-equal
    ``chain_hash`` values (the hash is deterministic over the
    chain payload, independent of ``verified_at``).
    """
    chain = _three_hop_chain()
    peer_policies = {(_ROUTE_ID, _PEER_POLICY_POINTER): _peer_policy()}

    # Verifier 1 at _NOW.
    v1 = _build_verifier(peer_policies=peer_policies, clock=_fixed_clock(_NOW))
    r1 = v1.verify(entry=_entry(), attestation=_attestation(), chain=chain)

    # Verifier 2 at _NOW + 15 min (still within link freshness).
    later = _NOW + timedelta(minutes=15)
    v2 = _build_verifier(peer_policies=peer_policies, clock=_fixed_clock(later))
    r2 = v2.verify(entry=_entry(), attestation=_attestation(), chain=chain)

    # The hash is stable; the verification timestamp differs.
    assert r1.chain_hash == r2.chain_hash
    assert r1.verified_at == _NOW
    assert r2.verified_at == later
    assert r1.attestation_route_id == r2.attestation_route_id
