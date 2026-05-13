# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for the Cross-Org Capability-Attenuation-Chain-Verifier.

Sprint-8 Tag-2 (Reza, 2026-05-13). Tests the three-detector
hardening module
:mod:`wirelang.federation.cross_org_attenuation_verifier` that
composes on top of the Sprint-2 Tag-5 N3 chain walker.

Test inventory (T-CO-01..T-CO-09; all deterministic):

- T-CO-01: argument-shape gate — non-ChainVerdict / naive-datetime rejected.
- T-CO-02: happy-path — 2-hop chain, no revocations, caveat-aligned,
  within boundary cap; verifier returns CrossOrgVerdict.
- T-CO-03: Detector 1 — bridge revoked AFTER mint is harmless
  (no replay risk).
- T-CO-04: Detector 1 — bridge revoked BEFORE mint with a later
  re-verification raises BridgeRevocationReplayError on the
  specific hop.
- T-CO-05: Detector 2 — verifier expects a caveat the issuer did
  not delegate -> CrossOrgCaveatMismatchError.
- T-CO-06: Detector 2 — verifier subset of issuer chain -> accept;
  empty verifier expectation -> accept.
- T-CO-07: Detector 3 — chain length exceeds cross_org_max_hops
  -> CrossOrgChainLengthLimitError.
- T-CO-08: Determinism — repeated verify() calls with identical
  inputs yield byte-identical accept verdicts / identical error
  types and messages.
- T-CO-09: Detector ordering invariant — when multiple detectors
  could fire, Detector 3 (chain-length) fires first, then
  Detector 1 (bridge-revocation), then Detector 2 (caveat-mismatch).
  This pinning prevents silent re-ordering across refactors.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wirelang.federation.cross_org_attenuation_verifier import (
    CROSS_ORG_MAX_HOPS_DEFAULT,
    BridgeRevocationMarker,
    BridgeRevocationReplayError,
    CaveatExpectation,
    CrossOrgArgumentError,
    CrossOrgAttenuationVerifier,
    CrossOrgCaveatMismatchError,
    CrossOrgChainLengthLimitError,
    CrossOrgVerdict,
    verify_cross_org_attenuation,
)
from wirelang.federation.n3_chain_walker import (
    ChainHopVerdict,
    ChainVerdict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FTD_CTX = "did:web:wakir.dev:ftd:v1"
_FTD_HOP_A = "did:web:processor-a.dev:ftd:v1"
_FTD_HOP_B = "did:web:partner-b.dev:ftd:v1"
_FTD_HOP_C = "did:web:partner-c.dev:ftd:v1"
_FTD_TARGET = "did:web:end-org.dev:ftd:v1"

_MINTED_AT = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
_REVOKED_BEFORE_MINT = datetime(2026, 5, 7, 6, 0, 0, tzinfo=timezone.utc)
_REVOKED_AFTER_MINT = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)


def _make_n3_verdict(hop_pairs: list, *, target: str = None) -> ChainVerdict:
    """Build a ChainVerdict directly from (source, target) hop pairs.

    Mirrors the N3 walker's accept-path verdict shape without
    actually running the walker; this isolates the Cross-Org
    verifier tests from N3-internal state and lets us craft
    arbitrary boundary topologies.
    """
    hops = []
    anchors = []
    for idx, (src, tgt) in enumerate(hop_pairs):
        anchor = f"wat-manifest-co-test-h{idx}"
        hops.append(
            ChainHopVerdict(
                hop_index=idx,
                source_ftd_id=src,
                target_ftd_id=tgt,
                route_id=f"{src}-|->{tgt}",
                wat_anchor_manifest_id=anchor,
            )
        )
        anchors.append(anchor)
    if target is None:
        target = hop_pairs[-1][1] if hop_pairs else _FTD_CTX
    return ChainVerdict(
        target_ftd_id=target,
        hops=tuple(hops),
        wat_anchor_chain=tuple(anchors),
    )


# ---------------------------------------------------------------------------
# T-CO-01 argument-shape gate
# ---------------------------------------------------------------------------


def test_t_co_01_argument_shape_gate():
    verifier = CrossOrgAttenuationVerifier()

    # n3_verdict must be a ChainVerdict.
    with pytest.raises(CrossOrgArgumentError):
        verifier.verify(
            n3_verdict="not-a-verdict",
            minted_at=_MINTED_AT,
        )

    # minted_at must be a datetime.
    verdict = _make_n3_verdict([(_FTD_CTX, _FTD_HOP_A)])
    with pytest.raises(CrossOrgArgumentError):
        verifier.verify(
            n3_verdict=verdict,
            minted_at="2026-05-07T12:00:00Z",
        )

    # minted_at must be tz-aware.
    naive = datetime(2026, 5, 7, 12, 0, 0)
    with pytest.raises(CrossOrgArgumentError):
        verifier.verify(
            n3_verdict=verdict,
            minted_at=naive,
        )

    # cross_org_max_hops must be non-negative int.
    with pytest.raises(CrossOrgArgumentError):
        CrossOrgAttenuationVerifier(cross_org_max_hops=-1)
    with pytest.raises(CrossOrgArgumentError):
        CrossOrgAttenuationVerifier(cross_org_max_hops="three")


# ---------------------------------------------------------------------------
# T-CO-02 happy-path
# ---------------------------------------------------------------------------


def test_t_co_02_happy_path_two_hop():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict(
        [
            (_FTD_CTX, _FTD_HOP_A),
            (_FTD_HOP_A, _FTD_TARGET),
        ]
    )

    issuer_caveats = [
        CaveatExpectation("peer_org", (_FTD_HOP_A,)),
        CaveatExpectation("treasury_path", ("hot",)),
    ]
    verifier_caveats = [
        CaveatExpectation("treasury_path", ("hot",)),
    ]

    out = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        issuer_caveat_chain=issuer_caveats,
        verifier_expected_caveats=verifier_caveats,
    )
    assert isinstance(out, CrossOrgVerdict)
    assert out.boundary_count == 2
    assert out.wat_anchor_chain == (
        "wat-manifest-co-test-h0",
        "wat-manifest-co-test-h1",
    )
    # The full N3 verdict is surfaced unchanged.
    assert out.n3_verdict is n3_verdict


# ---------------------------------------------------------------------------
# T-CO-03 Detector 1 — bridge revoked AFTER mint is harmless
# ---------------------------------------------------------------------------


def test_t_co_03_detector_1_bridge_revoked_after_mint_accepted():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict([(_FTD_CTX, _FTD_HOP_A)])

    marker = BridgeRevocationMarker(
        source_ftd_id=_FTD_CTX,
        target_ftd_id=_FTD_HOP_A,
        revoked_at=_REVOKED_AFTER_MINT,
    )
    # Bridge revoked AFTER the token was minted — the token's mint
    # event predates the revocation, so the bridge was active at
    # mint time. This is NOT a replay; it's a token that was
    # legitimately minted before the bridge retired.
    out = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        bridge_revocations=[marker],
    )
    assert isinstance(out, CrossOrgVerdict)


# ---------------------------------------------------------------------------
# T-CO-04 Detector 1 — bridge revoked BEFORE mint -> replay rejected
# ---------------------------------------------------------------------------


def test_t_co_04_detector_1_bridge_revoked_before_mint_rejected():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict(
        [
            (_FTD_CTX, _FTD_HOP_A),
            (_FTD_HOP_A, _FTD_TARGET),
        ]
    )

    # The bridge HOP-A -> TARGET was revoked BEFORE the token's
    # claimed mint time. A token presenting this chain at
    # verification time is a replay/forgery: the chain it claims
    # was active at mint was already broken.
    marker = BridgeRevocationMarker(
        source_ftd_id=_FTD_HOP_A,
        target_ftd_id=_FTD_TARGET,
        revoked_at=_REVOKED_BEFORE_MINT,
    )
    with pytest.raises(BridgeRevocationReplayError) as excinfo:
        verifier.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            bridge_revocations=[marker],
        )
    # The error message MUST reference the offending hop's pair
    # for forensic-trail completeness.
    assert _FTD_HOP_A in str(excinfo.value)
    assert _FTD_TARGET in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-CO-05 Detector 2 — caveat mismatch
# ---------------------------------------------------------------------------


def test_t_co_05_detector_2_caveat_mismatch_rejected():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict([(_FTD_CTX, _FTD_HOP_A)])

    # Org-A delegated only the (peer_org, FTD_HOP_A) caveat.
    issuer_caveats = [
        CaveatExpectation("peer_org", (_FTD_HOP_A,)),
    ]
    # Org-B expects a privilege Org-A did NOT delegate.
    verifier_caveats = [
        CaveatExpectation("treasury_unrestricted", ()),
    ]

    with pytest.raises(CrossOrgCaveatMismatchError) as excinfo:
        verifier.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=verifier_caveats,
        )
    assert "treasury_unrestricted" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-CO-06 Detector 2 — subset and empty cases accept
# ---------------------------------------------------------------------------


def test_t_co_06_detector_2_subset_and_empty_accepted():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict([(_FTD_CTX, _FTD_HOP_A)])

    # Subset: verifier expects only one of three issuer-delegated caveats.
    issuer_caveats = [
        CaveatExpectation("peer_org", (_FTD_HOP_A,)),
        CaveatExpectation("treasury_path", ("hot",)),
        CaveatExpectation("rate_limit_per_hour", (100,)),
    ]
    verifier_caveats = [
        CaveatExpectation("treasury_path", ("hot",)),
    ]
    out = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        issuer_caveat_chain=issuer_caveats,
        verifier_expected_caveats=verifier_caveats,
    )
    assert isinstance(out, CrossOrgVerdict)

    # Empty verifier expectation: no caveat-mismatch possible.
    out2 = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        issuer_caveat_chain=issuer_caveats,
        verifier_expected_caveats=[],
    )
    assert isinstance(out2, CrossOrgVerdict)


# ---------------------------------------------------------------------------
# T-CO-07 Detector 3 — chain length limit
# ---------------------------------------------------------------------------


def test_t_co_07_detector_3_chain_length_limit_rejected():
    # Default cap is 3. Build a 4-hop chain and expect rejection.
    verifier = CrossOrgAttenuationVerifier()
    assert verifier.cross_org_max_hops == CROSS_ORG_MAX_HOPS_DEFAULT == 3

    n3_verdict = _make_n3_verdict(
        [
            (_FTD_CTX, _FTD_HOP_A),
            (_FTD_HOP_A, _FTD_HOP_B),
            (_FTD_HOP_B, _FTD_HOP_C),
            (_FTD_HOP_C, _FTD_TARGET),
        ]
    )
    with pytest.raises(CrossOrgChainLengthLimitError) as excinfo:
        verifier.verify(n3_verdict, minted_at=_MINTED_AT)
    assert "4" in str(excinfo.value)
    assert "3" in str(excinfo.value)

    # Operator raises the cap with paired Z3 OTS-anchor policy:
    # the same chain accepts.
    operator_verifier = CrossOrgAttenuationVerifier(cross_org_max_hops=4)
    out = operator_verifier.verify(n3_verdict, minted_at=_MINTED_AT)
    assert isinstance(out, CrossOrgVerdict)
    assert out.boundary_count == 4


# ---------------------------------------------------------------------------
# T-CO-08 Determinism
# ---------------------------------------------------------------------------


def test_t_co_08_determinism():
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict(
        [
            (_FTD_CTX, _FTD_HOP_A),
            (_FTD_HOP_A, _FTD_TARGET),
        ]
    )

    issuer_caveats = [
        CaveatExpectation("peer_org", (_FTD_HOP_A,)),
        CaveatExpectation("treasury_path", ("hot",)),
    ]
    verifier_caveats = [CaveatExpectation("treasury_path", ("hot",))]
    marker = BridgeRevocationMarker(
        source_ftd_id=_FTD_CTX,
        target_ftd_id=_FTD_HOP_A,
        revoked_at=_REVOKED_AFTER_MINT,
    )

    out_a = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        bridge_revocations=[marker],
        issuer_caveat_chain=issuer_caveats,
        verifier_expected_caveats=verifier_caveats,
    )
    out_b = verifier.verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        bridge_revocations=[marker],
        issuer_caveat_chain=issuer_caveats,
        verifier_expected_caveats=verifier_caveats,
    )
    # Two verdicts MUST be equal under dataclass-equality.
    assert out_a == out_b
    assert out_a.boundary_count == out_b.boundary_count == 2
    assert out_a.wat_anchor_chain == out_b.wat_anchor_chain

    # Error path determinism: identical inputs that fail MUST yield
    # the same error TYPE and message.
    bad_verifier_caveats = [CaveatExpectation("forbidden_predicate", ())]
    with pytest.raises(CrossOrgCaveatMismatchError) as excinfo_a:
        verifier.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=bad_verifier_caveats,
        )
    with pytest.raises(CrossOrgCaveatMismatchError) as excinfo_b:
        verifier.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=bad_verifier_caveats,
        )
    assert str(excinfo_a.value) == str(excinfo_b.value)


# ---------------------------------------------------------------------------
# T-CO-09 Detector ordering invariant
# ---------------------------------------------------------------------------


def test_t_co_09_detector_ordering_invariant():
    """When multiple detectors could fire, the FIRST one (per the
    pinned order 3 -> 1 -> 2) fires.

    Construct inputs that simultaneously trigger Detectors 1, 2, AND 3:
    - chain length 5 (exceeds default cap 3) -> Detector 3
    - bridge revoked before mint -> Detector 1
    - verifier expects an undelegated caveat -> Detector 2

    The expected verdict: Detector 3 (CrossOrgChainLengthLimitError)
    wins because it is run first.
    """
    verifier = CrossOrgAttenuationVerifier()
    n3_verdict = _make_n3_verdict(
        [
            (_FTD_CTX, _FTD_HOP_A),
            (_FTD_HOP_A, _FTD_HOP_B),
            (_FTD_HOP_B, _FTD_HOP_C),
            (_FTD_HOP_C, _FTD_TARGET),
            (_FTD_TARGET, "did:web:far-org.dev:ftd:v1"),
        ]
    )
    marker = BridgeRevocationMarker(
        source_ftd_id=_FTD_CTX,
        target_ftd_id=_FTD_HOP_A,
        revoked_at=_REVOKED_BEFORE_MINT,
    )
    issuer_caveats = [CaveatExpectation("peer_org", (_FTD_HOP_A,))]
    bad_verifier_caveats = [CaveatExpectation("forbidden", ())]

    with pytest.raises(CrossOrgChainLengthLimitError):
        verifier.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            bridge_revocations=[marker],
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=bad_verifier_caveats,
        )

    # Now relax the chain-length cap and observe Detector 1 fires
    # next (revocation before caveat-mismatch).
    relaxed = CrossOrgAttenuationVerifier(cross_org_max_hops=10)
    with pytest.raises(BridgeRevocationReplayError):
        relaxed.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            bridge_revocations=[marker],
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=bad_verifier_caveats,
        )

    # Finally remove the revocation marker; Detector 2 (caveat) fires.
    with pytest.raises(CrossOrgCaveatMismatchError):
        relaxed.verify(
            n3_verdict,
            minted_at=_MINTED_AT,
            bridge_revocations=[],
            issuer_caveat_chain=issuer_caveats,
            verifier_expected_caveats=bad_verifier_caveats,
        )


# ---------------------------------------------------------------------------
# T-CO-aux convenience-fn parity
# ---------------------------------------------------------------------------


def test_t_co_aux_convenience_fn_parity():
    """The :func:`verify_cross_org_attenuation` convenience wrapper
    MUST produce an identical verdict to the class-form verifier."""
    n3_verdict = _make_n3_verdict([(_FTD_CTX, _FTD_HOP_A)])
    issuer = [CaveatExpectation("peer_org", (_FTD_HOP_A,))]
    expected = [CaveatExpectation("peer_org", (_FTD_HOP_A,))]

    class_form_verdict = CrossOrgAttenuationVerifier().verify(
        n3_verdict,
        minted_at=_MINTED_AT,
        issuer_caveat_chain=issuer,
        verifier_expected_caveats=expected,
    )
    fn_form_verdict = verify_cross_org_attenuation(
        n3_verdict,
        minted_at=_MINTED_AT,
        issuer_caveat_chain=issuer,
        verifier_expected_caveats=expected,
    )
    assert class_form_verdict == fn_form_verdict
