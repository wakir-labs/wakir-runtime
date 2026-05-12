# SPDX-License-Identifier: Apache-2.0
"""Wakir Wirelang federation sub-package (V-908).

Phase-1b Sprint-2 Tag-3 introduces the live ``peer_org`` /
``federation_route`` Datalog-predicate evaluator. The federation
substrate proper (DNS-anchor resolver, FTD verifier, federation
resolver pipeline) lives in :mod:`wirelang.identity`; this
sub-package owns the *predicate-evaluator* layer that consumes
those primitives and exposes a deterministic accept/reject
verdict for Wirelang Layer-3 tokens that carry V-908 caveats.

Phase-2 Sprint-7 Tag-1 adds the **multi-org federation substrate**
sub-module (``multi_org_substrate.py``) as a Phase-3-preparation
layer composing additively over the Sprint-3 Tag-6
``wakir-federation-routes`` bucket. The substrate is mock-only at
Tag-1; live SPIRE bundle / did:web resolution lands Tag-3+.

Phase-2 Sprint-7 Tag-2 adds the **multi-org-attestation NATS-KV
backend** sub-module
(``multi_org_attestation_nats_kv_backend.py``) on the
``wakir-multi-org-attestations`` bucket: durable persistence,
CAS-pinned upsert, authority-gesture monotonic invariant,
watch-stream + live-snapshot, and cross-bucket replication.

Phase-2 Sprint-7 Tag-3 adds the **SPIFFE cross-trust-domain bridge**
sub-module (``spiffe_cross_trust_domain_bridge.py``) — the live
counterpart to the Tag-1 mock-bridge resolver. The bridge orchestrates
peer trust-bundle fetch (via a pluggable
:class:`PeerTrustBundleFetcher`), peer JWT-SVID verification (via a
pluggable :class:`PeerSvidVerifier`), bundle-freshness enforcement,
and optional local-workload SVID pairing. Hermetic by injection of
Protocol fakes; live HTTPS-fetch impl is Phase-2c.

Public surface:

- :class:`wirelang.federation.n2_evaluator.FederationContext`
- :class:`wirelang.federation.n2_evaluator.FederationEvaluator`
- :class:`wirelang.federation.n2_evaluator.RouteRegistry`
- :class:`wirelang.federation.n2_evaluator.RouteRegistryEntry`
- exception hierarchy: :class:`PeerOrgMismatchError`,
  :class:`FederationRouteUnknownError`,
  :class:`FederationRouteExpiredError`,
  :class:`FederationPredicateArgumentError`.
- :class:`wirelang.federation.multi_org_substrate.MultiOrgRouteAttestation`
- :class:`wirelang.federation.multi_org_substrate.InMemoryMultiOrgAttestationRegistry`
- :func:`wirelang.federation.multi_org_substrate.resolve_mock_bridge_route`
- :class:`wirelang.federation.multi_org_attestation_nats_kv_backend.NatsKvMultiOrgAttestationRegistry`
- :class:`wirelang.federation.multi_org_attestation_nats_kv_backend.LiveMultiOrgAttestationSnapshot`
- :func:`wirelang.federation.multi_org_attestation_nats_kv_backend.bootstrap_multi_org_attestation_target_from_source`
- :class:`wirelang.federation.spiffe_cross_trust_domain_bridge.SpiffeCrossTrustDomainBridge`
- :class:`wirelang.federation.spiffe_cross_trust_domain_bridge.LiveBridgeResolution`
- :class:`wirelang.federation.spiffe_cross_trust_domain_bridge.FetchedTrustBundle`
- :class:`wirelang.federation.spiffe_cross_trust_domain_bridge.VerifiedPeerSvid`
"""

from .spiffe_cross_trust_domain_bridge import (  # noqa: F401
    BRIDGE_RESOLUTION_SCHEMA,
    DEFAULT_BUNDLE_MAX_AGE_SECONDS,
    FetchedTrustBundle,
    LiveBridgeResolution,
    PeerSvidSignatureError,
    PeerSvidVerifier,
    PeerTrustBundleExpiredError,
    PeerTrustBundleFetchError,
    PeerTrustBundleFetcher,
    SpiffeCrossTrustDomainBridge,
    SpiffeCrossTrustDomainBridgeError,
    VerifiedPeerSvid,
)

__all__ = [
    "BRIDGE_RESOLUTION_SCHEMA",
    "DEFAULT_BUNDLE_MAX_AGE_SECONDS",
    "FetchedTrustBundle",
    "LiveBridgeResolution",
    "PeerSvidSignatureError",
    "PeerSvidVerifier",
    "PeerTrustBundleExpiredError",
    "PeerTrustBundleFetchError",
    "PeerTrustBundleFetcher",
    "SpiffeCrossTrustDomainBridge",
    "SpiffeCrossTrustDomainBridgeError",
    "VerifiedPeerSvid",
]
