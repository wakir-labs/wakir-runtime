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

Phase-2 Sprint-7 Tag-4 adds the **Capability-Attenuation-Chain-
Verifier** sub-module (``capability_attenuation_chain_verifier.py``)
— a passive defence-in-depth layer that verifies cross-org
capability-attenuation chains against three replay-class attacks
(attenuation-order-violation, stale-attenuation-replay,
cross-org-boundary-violation). Consumes
:attr:`MultiOrgRouteAttestation.peer_capability_policy_pointer` and
the Sprint-6 Tag-1
:class:`~wirelang.schemas.registered_by_capability.CapabilityPolicyRegistry`.

Phase-2 Sprint-7 Tag-5 adds the **UnrevokeAuditMarker cross-org
export-surface** sub-module
(``unrevoke_audit_marker_cross_org_export.py``) — the
Pseudonymisierung-Pattern-per-ADR-0031-D4 boundary between the
Sprint-6 Tag-9 :class:`UnrevokeAuditMarker` (internal audit-trail
artefact) and any cross-org publication. The exporter strips raw
operator narrative, categorises the operator gesture via a
pluggable :class:`UnrevokeReasonClassifier`, and produces a
route-scoped BLAKE2b-256 ``marker_id`` suitable for WAT-Audit-
Federation-Annex leaf-anchoring.

Phase-2 Sprint-7 Tag-6 adds the **multi-org-attestation live-tail
replicator** sub-module
(``multi_org_attestation_live_tail_replicator.py``) — the
continuous-stream composition layer on top of the Sprint-7 Tag-2
``bootstrap_multi_org_attestation_target_from_source`` one-shot
bootstrap. Together the two surfaces form the full cross-bucket
replication suite for the ``wakir-multi-org-attestations`` bucket
(pattern-mirror on the Sprint-6 Tag-6 capability-policy
cross-bucket replicator).

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
- :class:`wirelang.federation.capability_attenuation_chain_verifier.CapabilityAttenuationChainVerifier`
- :class:`wirelang.federation.capability_attenuation_chain_verifier.AttenuationLink`
- :class:`wirelang.federation.capability_attenuation_chain_verifier.VerifiedAttenuationChain`
- :class:`wirelang.federation.capability_attenuation_chain_verifier.ResolvedAttenuationLink`
- :class:`wirelang.federation.unrevoke_audit_marker_cross_org_export.UnrevokeAuditMarkerCrossOrgExporter`
- :class:`wirelang.federation.unrevoke_audit_marker_cross_org_export.ExportedUnrevokeAuditMarker`
- :class:`wirelang.federation.unrevoke_audit_marker_cross_org_export.UnrevokeReasonClass`
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
from .capability_attenuation_chain_verifier import (  # noqa: F401
    CHAIN_VERIFICATION_SCHEMA,
    DEFAULT_MAX_LINK_AGE_SECONDS,
    AttenuationChainShapeError,
    AttenuationLink,
    AttenuationLinkRevokedError,
    AttenuationOrderViolationError,
    CapabilityAttenuationChainError,
    CapabilityAttenuationChainVerifier,
    CrossOrgBoundaryViolationError,
    PeerCapabilityPolicyResolver,
    ResolvedAttenuationLink,
    StaleAttenuationReplayError,
    VerifiedAttenuationChain,
)
from .unrevoke_audit_marker_cross_org_export import (  # noqa: F401
    DEFAULT_CLASSIFIER,
    EXPORT_SCHEMA,
    ExportedUnrevokeAuditMarker,
    RawNarrativeLeakError,
    UnrevokeAuditMarkerCrossOrgExportError,
    UnrevokeAuditMarkerCrossOrgExporter,
    UnrevokeAuditMarkerShapeError,
    UnrevokeReasonClass,
    UnrevokeReasonClassifier,
)
from .multi_org_attestation_live_tail_replicator import (  # noqa: F401
    MultiOrgAttestationReplicator,
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
    "CHAIN_VERIFICATION_SCHEMA",
    "DEFAULT_MAX_LINK_AGE_SECONDS",
    "AttenuationChainShapeError",
    "AttenuationLink",
    "AttenuationLinkRevokedError",
    "AttenuationOrderViolationError",
    "CapabilityAttenuationChainError",
    "CapabilityAttenuationChainVerifier",
    "CrossOrgBoundaryViolationError",
    "PeerCapabilityPolicyResolver",
    "ResolvedAttenuationLink",
    "StaleAttenuationReplayError",
    "VerifiedAttenuationChain",
    "DEFAULT_CLASSIFIER",
    "EXPORT_SCHEMA",
    "ExportedUnrevokeAuditMarker",
    "RawNarrativeLeakError",
    "UnrevokeAuditMarkerCrossOrgExportError",
    "UnrevokeAuditMarkerCrossOrgExporter",
    "UnrevokeAuditMarkerShapeError",
    "UnrevokeReasonClass",
    "UnrevokeReasonClassifier",
    "MultiOrgAttestationReplicator",
]
