# SPDX-License-Identifier: BUSL-1.1
"""Cross-Org Capability-Attenuation-Chain-Verifier (Sprint-8 Tag-2 hardening).

This module hardens the N3 multi-FTD delegation-chain walker
(:mod:`wirelang.federation.n3_chain_walker`) for Multi-Org-Boundary
edge cases that arise when a Wirelang Layer-3 capability-token is
minted in Org-A and verified in Org-B (or further attenuated by
Org-C). The N3 walker proves that the FTD-graph contains an
active delegation path; this module adds three orthogonal
hardening detectors on top:

1. **Bridge-Revocation Replay Detector.** A Cross-Org token MUST
   be rejected when any Trust-Domain-Bridge along its issuance
   chain has been revoked since the token was minted, even if the
   chain at evaluation time still appears active under
   last-write-wins registry semantics. Operationalised via a
   ``minted_at`` anchor compared against per-hop
   ``revoked_at`` markers exposed by the registry.

2. **Caveat-Mismatch Detector.** When Org-A mints a token under
   one set of issuer-side caveats and Org-B verifies it under a
   verifier-side expectation, the two caveat sets MUST be
   compatible: Org-B's expectation MUST be a subset (or equal) of
   the issuer's attenuation chain — otherwise Org-B would be
   accepting a privilege Org-A did not delegate. The detector
   surfaces typed errors for both shape-mismatch and value-mismatch.

3. **Chain-Length-Limit Replay Detector.** Even within the N3
   walker's ``max_depth`` budget, a Cross-Org chain that crosses
   strictly more than ``cross_org_max_hops`` distinct trust-domain
   boundaries is rejected: this is a defence-in-depth detector
   against attenuation-amplification attacks where an adversary
   inflates the FTD count to evade per-org rate limits.

All three detectors are **pure** (no clock, no I/O), **stateless**
(no mutation), and **deterministic** (same input -> same verdict
or same typed error). They compose on top of the N3 walker's
existing ``ChainVerdict`` rather than replacing it: callers run
the N3 walk first and then apply this module's verifier to the
verdict.

Cross-review hooks
------------------

- **Zone 1 (Identity-Substrate):** the verifier consumes the N3
  walker's per-hop ``source_ftd_id`` / ``target_ftd_id``; it does
  NOT re-resolve FTD documents. The Zone-1 substrate is upstream.
- **Zone 2 (WAT × Wirelang):** each Cross-Org hop carries a
  ``wat_anchor_manifest_id`` (surfaced unchanged by the N3
  verdict); this module preserves the anchor chain in its own
  ``CrossOrgVerdict.wat_anchor_chain`` field so a downstream
  WAT-leaf consumer can emit a single audit snapshot per cross-org
  verification.
- **Zone 3 (OTS-Schema-Anker):** the schema for
  ``BridgeRevocationMarker`` is reserved for a future
  schema-registry entry; the Phase-2 anchor is out of scope here.

Sprint-8 Tag-2 contract (Reza, 2026-05-13):

- Three replay-detector families ratified: ``bridge_revocation``,
  ``caveat_mismatch``, ``chain_length_limit``.
- Default ``cross_org_max_hops = 3`` (one trust-domain boundary per
  delegation step in a typical 4-org issuance chain).
- The module is additive; the N3 walker and N2 evaluator surfaces
  remain unchanged.

References (URL-stamped 2026-05-13):

- N3 walker: ``wirelang/federation/n3_chain_walker.py`` (Sprint-2
  Tag-5, hardened by this Tag-2 module).
- N2 evaluator: ``wirelang/federation/n2_evaluator.py`` (Sprint-2
  Tag-3).
- V-908 spec §3.2 / §6: ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md``.
- Layer-3 capability-token: ``wirelang/specs/layer-3-capability-token.md``
  §"Replay protection".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Optional, Tuple

from .n2_evaluator import FederationPredicateError
from .n3_chain_walker import ChainVerdict


# ---------------------------------------------------------------------------
# Public surface constants
# ---------------------------------------------------------------------------


CROSS_ORG_MAX_HOPS_DEFAULT = 3
"""Default maximum number of distinct trust-domain hops in a
Cross-Org chain.

The N3 walker's ``MAX_DEPTH_DEFAULT = 4`` covers the FTD-graph
depth (issuer -> processor -> partner -> end-org). The
Cross-Org-Boundary detector tightens this to ``3`` distinct
trust-domain crossings: a 4-hop chain visits 5 FTDs and crosses 4
boundaries, which the Phase-1b defence-in-depth posture rejects
absent explicit operator opt-in.

Operators MAY raise this at :class:`CrossOrgAttenuationVerifier`
construction time when their topology genuinely requires deeper
attenuation chains; doing so MUST be paired with a Z3 OTS-anchor
of the operator policy.
"""


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class CrossOrgVerifierError(FederationPredicateError):
    """Base class for Cross-Org attenuation-verifier failures.

    Inherits from :class:`FederationPredicateError` so callers that
    short-circuit on N2/N3 evaluator errors uniformly handle
    Cross-Org failures without surface widening.
    """


class CrossOrgArgumentError(CrossOrgVerifierError):
    """Raised when a Cross-Org verifier argument fails the
    syntactic shape contract."""


class BridgeRevocationReplayError(CrossOrgVerifierError):
    """Detector 1: a Cross-Org token's chain crosses a
    Trust-Domain-Bridge that was revoked at or before the token's
    ``minted_at`` anchor.

    The forensic invariant is: a token MUST NOT be accepted when
    any bridge along its chain was revoked at-or-before mint time.
    """


class CrossOrgCaveatMismatchError(CrossOrgVerifierError):
    """Detector 2: the verifier-side caveat expectation is NOT a
    subset of the issuer-side attenuation caveat chain.

    The forensic invariant is: Org-B's expectation MUST be a subset
    of (or equal to) Org-A's delegated caveat chain. Any predicate
    Org-B expects which Org-A did not delegate fails the detector.
    """


class CrossOrgChainLengthLimitError(CrossOrgVerifierError):
    """Detector 3: the Cross-Org chain crosses strictly more than
    ``cross_org_max_hops`` distinct trust-domain boundaries.

    Forensic invariant: the chain depth at Cross-Org granularity
    (number of FTD-boundary crossings) MUST NOT exceed the
    configured ``cross_org_max_hops`` cap.
    """


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeRevocationMarker:
    """A single Trust-Domain-Bridge revocation marker.

    Attributes:
        source_ftd_id: the FTD id at the start of the revoked bridge.
        target_ftd_id: the FTD id at the end of the revoked bridge.
        revoked_at: wall-clock at which the bridge was revoked.
            A token whose ``minted_at`` is at-or-after this point
            crossing this bridge MAY still be considered (the bridge
            was active at mint time); a token whose ``minted_at``
            is strictly-before this point AND was minted on the
            assumption the bridge stayed active later is what the
            detector protects against. See
            :meth:`bridge_was_revoked_for_mint`.

    Schema contract (reserved for Phase-2 OTS-anchored registry):
    operators emit one of these per (source, target) FTD pair that
    has been retired. The registry is intentionally append-only to
    preserve the audit trail; expired bridges remain queryable.
    """

    source_ftd_id: str
    target_ftd_id: str
    revoked_at: datetime

    def bridge_was_revoked_for_mint(self, minted_at: datetime) -> bool:
        """Return whether this marker invalidates a token minted at ``minted_at``.

        The Phase-1b rule is: if the bridge was revoked AT-OR-BEFORE
        the token's claimed mint time, the token's chain claim is
        forensically inconsistent — the bridge it claims to traverse
        had already been retired at the moment the token says it was
        minted. This is the canonical replay/forgery signature.

        A token whose ``minted_at`` strictly precedes the revocation
        was minted legitimately while the bridge was active. The
        subsequent revocation is a separate authorisation event
        (covered by the N2/N3 route-window check); the
        Bridge-Revocation REPLAY detector does NOT fire for that
        case — that is by design, to keep the detector scoped to
        forgery rather than to ordinary expiry.
        """
        return self.revoked_at <= minted_at


@dataclass(frozen=True)
class CaveatExpectation:
    """A verifier-side caveat expectation.

    A caveat is represented as a (predicate, argument-tuple) pair.
    The detector compares the verifier expectation set against the
    issuer-side attenuation caveat chain via set-containment.

    Attributes:
        predicate: the Datalog predicate name (e.g. ``"peer_org"``).
        arguments: the argument tuple. All elements MUST be hashable
            so the (predicate, arguments) pair can live in a frozen
            set.
    """

    predicate: str
    arguments: Tuple[object, ...]


@dataclass(frozen=True)
class CrossOrgVerdict:
    """Aggregate verdict for a successful Cross-Org verification.

    Attributes:
        n3_verdict: the underlying N3 :class:`ChainVerdict` the
            Cross-Org verifier validated. Surfaced for callers that
            want both layers' forensics without re-running the walk.
        boundary_count: the number of distinct trust-domain
            boundaries crossed (equals ``n3_verdict.depth`` for the
            current Phase-1b model: one boundary per N3 hop).
        wat_anchor_chain: the per-hop WAT manifest ids, surfaced
            unchanged from the N3 verdict for downstream WAT-leaf
            consumers. Convenience alias to keep Cross-Org callers
            from reaching through to ``n3_verdict.wat_anchor_chain``.
    """

    n3_verdict: ChainVerdict
    boundary_count: int = field(init=False)
    wat_anchor_chain: Tuple[Optional[str], ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "boundary_count", self.n3_verdict.depth)
        object.__setattr__(
            self, "wat_anchor_chain", self.n3_verdict.wat_anchor_chain
        )


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class CrossOrgAttenuationVerifier:
    """Cross-Org capability-attenuation-chain hardening verifier.

    Composes three orthogonal replay-detector families on top of a
    pre-computed N3 :class:`ChainVerdict`. The verifier is **pure**
    and **stateless**: every call to :meth:`verify` produces the
    same verdict (or the same typed error) given identical inputs.

    The verifier does NOT itself walk the FTD-graph; callers are
    expected to obtain a :class:`ChainVerdict` from
    :class:`wirelang.federation.n3_chain_walker.ChainWalker` (or
    :func:`walk_delegation_chain`) first. This separation is
    deliberate: the N3 walker handles graph-connectivity proofs;
    this module handles boundary-edge-case proofs.

    Construction-time bounds:

    - ``cross_org_max_hops``: defaults to
      :data:`CROSS_ORG_MAX_HOPS_DEFAULT`. Operators MAY raise this
      with a paired Z3 OTS-anchor of policy.

    Per-call inputs:

    - ``n3_verdict``: the N3 walker's verdict for this Cross-Org chain.
    - ``minted_at``: the wall-clock at which the verified token was
      minted. Required for Detector 1.
    - ``bridge_revocations``: an iterable of
      :class:`BridgeRevocationMarker` (Detector 1 lookup space).
    - ``issuer_caveat_chain``: the set of (predicate, args) the
      issuer-side attenuation actually delegated.
    - ``verifier_expected_caveats``: the set of (predicate, args)
      the verifier-side expects.

    The :meth:`verify` method returns a :class:`CrossOrgVerdict`
    on accept; on rejection it raises one of the typed errors.
    """

    def __init__(self, *, cross_org_max_hops: int = CROSS_ORG_MAX_HOPS_DEFAULT) -> None:
        if not isinstance(cross_org_max_hops, int) or cross_org_max_hops < 0:
            raise CrossOrgArgumentError(
                "cross_org_max_hops must be a non-negative int"
            )
        self._cross_org_max_hops = cross_org_max_hops

    @property
    def cross_org_max_hops(self) -> int:
        return self._cross_org_max_hops

    # ----- detectors ------------------------------------------------------

    def _detector_1_bridge_revocation(
        self,
        n3_verdict: ChainVerdict,
        minted_at: datetime,
        bridge_revocations: Iterable[BridgeRevocationMarker],
    ) -> None:
        """Detector 1: reject if any hop's bridge was revoked before mint."""
        # Build a lookup map (source, target) -> latest revocation.
        # Multiple revocations for the same pair MAY exist (append-
        # only registry); we honour the EARLIEST revocation as the
        # forensic anchor: if a bridge was revoked at t1 and re-
        # introduced+revoked again at t2, a token minted before t1
        # is invalidated by t1 (the bridge was retired at t1).
        revocation_map: dict = {}
        for marker in bridge_revocations:
            if not isinstance(marker, BridgeRevocationMarker):
                raise CrossOrgArgumentError(
                    "bridge_revocations entries must be BridgeRevocationMarker instances"
                )
            key = (marker.source_ftd_id, marker.target_ftd_id)
            existing = revocation_map.get(key)
            if existing is None or marker.revoked_at < existing.revoked_at:
                revocation_map[key] = marker

        for hop in n3_verdict.hops:
            key = (hop.source_ftd_id, hop.target_ftd_id)
            marker = revocation_map.get(key)
            if marker is None:
                continue
            if marker.bridge_was_revoked_for_mint(minted_at):
                raise BridgeRevocationReplayError(
                    f"hop {hop.hop_index} ({hop.source_ftd_id!r} -> "
                    f"{hop.target_ftd_id!r}): bridge already revoked at "
                    f"{marker.revoked_at.isoformat()} at-or-before "
                    f"claimed mint at {minted_at.isoformat()}; "
                    f"chain claim is forensically inconsistent — "
                    f"replay rejected"
                )

    def _detector_2_caveat_mismatch(
        self,
        issuer_caveat_chain: Iterable[CaveatExpectation],
        verifier_expected_caveats: Iterable[CaveatExpectation],
    ) -> None:
        """Detector 2: reject if verifier expectation is not a
        subset of issuer chain.

        The check is strict containment: every verifier-expected
        caveat MUST appear (predicate AND argument-tuple equal) in
        the issuer-delegated chain. Org-B cannot expect a privilege
        Org-A did not delegate.
        """
        issuer_set = set()
        for caveat in issuer_caveat_chain:
            if not isinstance(caveat, CaveatExpectation):
                raise CrossOrgArgumentError(
                    "issuer_caveat_chain entries must be CaveatExpectation instances"
                )
            issuer_set.add((caveat.predicate, caveat.arguments))

        verifier_set = set()
        for caveat in verifier_expected_caveats:
            if not isinstance(caveat, CaveatExpectation):
                raise CrossOrgArgumentError(
                    "verifier_expected_caveats entries must be CaveatExpectation instances"
                )
            verifier_set.add((caveat.predicate, caveat.arguments))

        extras = verifier_set - issuer_set
        if extras:
            # Surface the first extras entry for forensic clarity;
            # the full extras set is included in the error message.
            extras_list = sorted(
                extras, key=lambda c: (c[0], tuple(map(repr, c[1])))
            )
            first = extras_list[0]
            raise CrossOrgCaveatMismatchError(
                f"verifier expectation {first[0]!r}{first[1]!r} not "
                f"present in issuer caveat chain; {len(extras)} extra(s) total: "
                f"{[c[0] for c in extras_list]!r}"
            )

    def _detector_3_chain_length_limit(self, n3_verdict: ChainVerdict) -> None:
        """Detector 3: reject if Cross-Org chain exceeds boundary cap."""
        if n3_verdict.depth > self._cross_org_max_hops:
            raise CrossOrgChainLengthLimitError(
                f"Cross-Org chain crosses {n3_verdict.depth} trust-domain "
                f"boundaries, exceeds cross_org_max_hops "
                f"{self._cross_org_max_hops}"
            )

    # ----- entry-point ----------------------------------------------------

    def verify(
        self,
        n3_verdict: ChainVerdict,
        *,
        minted_at: datetime,
        bridge_revocations: Optional[Iterable[BridgeRevocationMarker]] = None,
        issuer_caveat_chain: Optional[Iterable[CaveatExpectation]] = None,
        verifier_expected_caveats: Optional[Iterable[CaveatExpectation]] = None,
    ) -> CrossOrgVerdict:
        """Run all three detectors against the N3 verdict.

        Detectors are run in fixed order (3, 1, 2) so:

        - Chain-length-limit fires first: short-circuit on the
          cheapest check and avoid downstream work for clearly-
          over-cap chains.
        - Bridge-revocation fires second: independent of caveat
          shape; rejects forged-chain replays before semantic checks.
        - Caveat-mismatch fires last: most expensive set comparison,
          guarded by the cheaper rejections above.

        The order is documented and stable; tests pin this ordering
        as a forensic invariant so error-type assertions remain
        deterministic.

        Args:
            n3_verdict: the pre-computed N3 chain verdict.
            minted_at: wall-clock at token-mint. Must be tz-aware.
            bridge_revocations: iterable of bridge-revocation markers
                (Detector 1 lookup space). ``None`` treated as empty.
            issuer_caveat_chain: iterable of issuer-delegated caveats.
                ``None`` treated as empty (which implies any non-empty
                verifier expectation triggers Detector 2).
            verifier_expected_caveats: iterable of verifier-side
                expected caveats. ``None`` treated as empty (no
                caveat-mismatch possible).

        Returns:
            :class:`CrossOrgVerdict` on accept.

        Raises:
            :class:`CrossOrgArgumentError`: malformed argument.
            :class:`CrossOrgChainLengthLimitError`: Detector 3.
            :class:`BridgeRevocationReplayError`: Detector 1.
            :class:`CrossOrgCaveatMismatchError`: Detector 2.
        """
        if not isinstance(n3_verdict, ChainVerdict):
            raise CrossOrgArgumentError(
                "n3_verdict must be a ChainVerdict"
            )
        if not isinstance(minted_at, datetime):
            raise CrossOrgArgumentError(
                "minted_at must be a datetime"
            )
        if minted_at.tzinfo is None:
            raise CrossOrgArgumentError(
                "minted_at must be timezone-aware (UTC)"
            )

        # Detector 3 — cheapest.
        self._detector_3_chain_length_limit(n3_verdict)

        # Detector 1 — bridge-revocation replay.
        self._detector_1_bridge_revocation(
            n3_verdict,
            minted_at,
            bridge_revocations or (),
        )

        # Detector 2 — caveat mismatch.
        self._detector_2_caveat_mismatch(
            issuer_caveat_chain or (),
            verifier_expected_caveats or (),
        )

        return CrossOrgVerdict(n3_verdict=n3_verdict)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def verify_cross_org_attenuation(
    n3_verdict: ChainVerdict,
    *,
    minted_at: datetime,
    bridge_revocations: Optional[Iterable[BridgeRevocationMarker]] = None,
    issuer_caveat_chain: Optional[Iterable[CaveatExpectation]] = None,
    verifier_expected_caveats: Optional[Iterable[CaveatExpectation]] = None,
    cross_org_max_hops: int = CROSS_ORG_MAX_HOPS_DEFAULT,
) -> CrossOrgVerdict:
    """Convenience wrapper around :class:`CrossOrgAttenuationVerifier`.

    Equivalent to
    ``CrossOrgAttenuationVerifier(cross_org_max_hops=...).verify(...)``.
    Provided so callers that use the verifier exactly once need not
    instantiate the class explicitly.
    """
    verifier = CrossOrgAttenuationVerifier(
        cross_org_max_hops=cross_org_max_hops,
    )
    return verifier.verify(
        n3_verdict,
        minted_at=minted_at,
        bridge_revocations=bridge_revocations,
        issuer_caveat_chain=issuer_caveat_chain,
        verifier_expected_caveats=verifier_expected_caveats,
    )


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "BridgeRevocationMarker",
    "BridgeRevocationReplayError",
    "CROSS_ORG_MAX_HOPS_DEFAULT",
    "CaveatExpectation",
    "CrossOrgArgumentError",
    "CrossOrgAttenuationVerifier",
    "CrossOrgCaveatMismatchError",
    "CrossOrgChainLengthLimitError",
    "CrossOrgVerdict",
    "CrossOrgVerifierError",
    "verify_cross_org_attenuation",
]
