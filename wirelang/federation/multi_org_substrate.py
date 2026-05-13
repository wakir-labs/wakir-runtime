# SPDX-License-Identifier: BUSL-1.1
"""Multi-Org Federation Substrate (Phase-3 preparation).

Phase-2 Sprint-7 Tag-1 lands the **substrate** for multi-org
federation as an additive composition over the Sprint-3 Tag-6
``wakir-federation-routes`` NATS-KV bucket and the Phase-1b
:class:`wirelang.federation.n2_evaluator.RouteRegistryEntry`
dataclass.

This module is **substrate-only**: it does not perform live
cross-trust-domain attestation, it does not fetch trust bundles,
and it does not emit DID documents. Those surfaces are gated on
Mira-Eskalations-Punkt E1 (ADR-0031) and Sprint-8+ live federation
trial. What this module *does* ship in Sprint-7 Tag-1:

1.  A **frozen** :class:`MultiOrgRouteAttestation` dataclass that
    pairs an existing :class:`RouteRegistryEntry` with
    cross-trust-domain attestation fields (peer trust-domain,
    peer audit-anchor DID, optional peer trust-bundle URL).
    Existing single-org entries remain byte-equal at the wire
    layer — the attestation is a *side-table* keyed by
    ``route_id``, never a mutation of the original entry.
2.  An :class:`InMemoryMultiOrgAttestationRegistry` reference
    implementation (mirrors the Phase-1b
    :class:`InMemoryRouteRegistry` shape) that the Sprint-7 Tag-2
    NATS-KV backend will replace 1:1.
3.  A **mock-bridge-route resolution** path
    (:func:`resolve_mock_bridge_route`) that lets Sprint-7
    iterate the cross-trust-domain composition without
    needing a live SPIRE bundle endpoint or a live did:web
    fetch. Mock-bridge-routes are explicitly tagged
    (``is_mock=True``) so no caller can confuse them with a
    real federation attestation.

ADR-0031-Substrate-Voraussetzungs-Mapping (S-1..S-4 from Tag-10
skizze §3) maps as follows:

- **S-1 Cross-Org-Identity-Resolution**: covered by
  :attr:`MultiOrgRouteAttestation.peer_audit_anchor_did`
  (substrate-only; live did:web fetch is Sprint-7 Tag-2+).
- **S-2 Cross-Org-Audit-Federation**: covered by
  :attr:`MultiOrgRouteAttestation.peer_wat_anchor_manifest_id`
  (substrate-only; Tomás-side WAT-Audit-Federation-Annex
  consumes this field via D-1 cross-review).
- **S-3 Cross-Org-Capability-Token-Federation**: covered by
  :attr:`MultiOrgRouteAttestation.peer_capability_policy_pointer`
  (substrate-only; cross-org Biscuit-attenuation evaluation is
  Sprint-7 Tag-4+).
- **S-4 Cross-Trust-Domain-SPIFFE-Bridge**: covered by
  :attr:`MultiOrgRouteAttestation.peer_trust_domain` and
  :attr:`MultiOrgRouteAttestation.peer_trust_bundle_url`
  (substrate-only; live SpiffeCrossTrustDomainBridge component
  is Sprint-7 Tag-3+ paired with Kai SPIRE-Federation-Bundle-
  Endpoint cross-review D-2).

Cross-review zones touched:

- **D-1 (Reza × Tomás, WAT-Audit-Federation-Annex-Substrate)** —
  ``peer_wat_anchor_manifest_id`` is the Tomás-side WAT-anchor-
  resolution surface; Sprint-7-Tag-1 substrate-skizze defines
  the field shape, Tomás-side WAT-anchor-consumer is D-1 trigger.
- **D-2 (Reza × Kai, SPIFFE-Cross-Trust-Domain-Bridge-Substrate)** —
  ``peer_trust_domain`` and ``peer_trust_bundle_url`` are the
  Kai-side SPIRE-Federation-Bundle-Endpoint-Configuration
  surface; live bridge is Tag-3+ D-2 trigger.
- **D-3 (Reza × Selin, NLnet-Antrag-Konsistenz)** —
  the *substrate* tier of multi-org federation as described in
  this module is what the NLnet-Antrag vision-block (V-908)
  should reference; live federation trial remains a separate
  comms item.
- **D-4 (Reza × Aisha, Cross-Review-Moderation)** —
  Zone-D consensus-marker for Sprint-7-Pfad-B-Eröffnung is
  Aisha-side; this module's existence is the substantive anchor
  Aisha will protocol against.

ADR-0050 Tool-Surface-Stempel applies at module-level: this
file was authored using Read, Edit, Write, Bash (kein Agent-Tool,
WebFetch only for the §4.x A2A-Spec befund memo, not for this
file).

Mira-Eskalations-Punkt E1 status: the A2A-Spec §4.x befund memo
(``reza/outbox/2026-05-12-a2a-spec-§4-x-befund-fuer-mira.md``)
classifies the constraint as **unkritisch** — A2A §4.x neither
mandates nor forbids DID-document emission. The substrate in
this module is therefore not gated on E1; the live federation
trial (Sprint-8+) remains Mira-Hand approval-pending.

Version: ``wakir.federation.multi-org-attestation/1``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .n2_evaluator import RouteRegistryEntry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema-URI fragment for the multi-org attestation envelope. Used
#: by the Sprint-7 Tag-2 NATS-KV backend (forthcoming) to tag
#: persisted attestation records. Phase-1b convention: ``wakir.``
#: namespace prefix, kebab-case noun, integer version suffix.
ATTESTATION_VALUE_SCHEMA = "wakir.federation.multi-org-attestation/1"


#: Reserved prefix for mock-bridge-route identifiers. Sprint-7
#: iterates the cross-trust-domain composition with mock entries
#: while the live SPIRE-Federation-Bundle-Endpoint surface is
#: being prepared (Kai D-2). Mock entries MUST carry this prefix
#: in their ``route_id`` so a misconfigured production deployment
#: cannot accidentally treat a mock as live.
MOCK_BRIDGE_ROUTE_ID_PREFIX = "mock-bridge://"


# SPIFFE trust-domain regex per SPIFFE ID spec. The trust-domain
# component is the lowercase ASCII host portion of a SPIFFE ID
# (no path, no userinfo, no port). We accept the conservative
# subset used by SPIRE deployments: lowercase letters, digits,
# dots, hyphens. Length cap mirrors DNS labels (253 chars).
_TRUST_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


# did:web is the ADR-0031 D4 default for cross-org identity
# anchoring. We accept the canonical did:web grammar conservatively:
# ``did:web:`` followed by a percent-encoded host (with optional
# port and path), where each segment after the host uses ``:`` as
# the path separator per the did:web spec.
_DID_WEB_RE = re.compile(
    r"^did:web:[A-Za-z0-9._%-]+(:[A-Za-z0-9._%-]+)*$"
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MultiOrgSubstrateError(Exception):
    """Base class for multi-org federation substrate errors."""


class MultiOrgAttestationValidationError(MultiOrgSubstrateError):
    """Raised when a :class:`MultiOrgRouteAttestation` is constructed
    with field values that fail the shape/grammar contract.
    """


class MultiOrgAttestationConflictError(MultiOrgSubstrateError):
    """Raised when a registry rejects an attestation because it
    conflicts with an existing record (e.g. same ``route_id`` but
    different ``peer_trust_domain``).
    """


class UnknownBridgeRouteError(MultiOrgSubstrateError):
    """Raised by :func:`resolve_mock_bridge_route` when the
    requested ``route_id`` does not exist in the registry.
    """


# ---------------------------------------------------------------------------
# MultiOrgRouteAttestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiOrgRouteAttestation:
    """Cross-trust-domain attestation paired with an existing route.

    The attestation is a *side-table* keyed by :attr:`route_id`. The
    underlying :class:`RouteRegistryEntry` is not mutated — existing
    single-org entries remain byte-equal at the KV layer. A route
    *may* have at most one attestation; a route *may* have zero
    attestations (meaning it is single-org / Wakir-internal).

    Attributes:
        route_id: the ``route_id`` of an existing
            :class:`RouteRegistryEntry`. The substrate does not
            verify that the entry exists at construction time; that
            check is the responsibility of the registry layer.
        peer_trust_domain: the SPIFFE trust-domain identifier of
            the peer org (host portion of a SPIFFE ID, no scheme,
            no path). Example: ``"partner-a.example"``. Used by the
            Sprint-7 Tag-3+ SpiffeCrossTrustDomainBridge component
            (Kai D-2). MUST match :data:`_TRUST_DOMAIN_RE`.
        peer_audit_anchor_did: the peer org's audit-anchor DID
            (ADR-0031 D4 default: ``did:web``). Used by the
            Sprint-7 Tag-2+ live did:web resolution path. MUST
            match :data:`_DID_WEB_RE` for ``did:web``; other DID
            methods MAY be added in additive minor bumps.
        peer_wat_anchor_manifest_id: optional peer-side WAT
            manifest id. Used by the Tomás-side WAT-Audit-
            Federation-Annex (D-1) to cross-anchor merkle leaves
            into both org-trails. ``None`` means the peer does not
            (yet) expose WAT anchoring.
        peer_trust_bundle_url: optional HTTPS URL of the peer
            SPIFFE trust-bundle (JWK Set). ``None`` means the
            bundle is to be discovered out-of-band (e.g. operator-
            preprovisioned). Live bundle fetch is Sprint-7 Tag-3+.
        peer_capability_policy_pointer: optional JSON-Pointer or
            URI fragment referencing the peer's capability-policy
            attenuation policy (Biscuit public-key set / Datalog
            vocabulary pin). ``None`` means the peer's capability-
            token chains are not validated cross-org in this
            attestation. Sprint-7 Tag-4+.
        is_mock: ``True`` for mock-bridge-route attestations used
            during Sprint-7 substrate iteration before the live
            SPIRE federation endpoint is online. Mock attestations
            MUST carry a ``route_id`` starting with
            :data:`MOCK_BRIDGE_ROUTE_ID_PREFIX`. Live attestations
            MUST set ``is_mock=False`` and MUST NOT carry the mock
            prefix.

    Wire envelope (forthcoming Sprint-7 Tag-2 backend):

        {"schema": "wakir.federation.multi-org-attestation/1",
         "route_id": <str>,
         "peer_trust_domain": <str>,
         "peer_audit_anchor_did": <str>,
         "peer_wat_anchor_manifest_id": <str|null>,
         "peer_trust_bundle_url": <str|null>,
         "peer_capability_policy_pointer": <str|null>,
         "is_mock": <bool>}

    JCS canonicalisation (RFC 8785) is implicit via
    ``json.dumps(payload, sort_keys=True, separators=(",", ":"))``
    consistent with the Sprint-3 Tag-6 route-registry-entry
    envelope. The same byte-reproducibility contract applies.
    """

    route_id: str
    peer_trust_domain: str
    peer_audit_anchor_did: str
    peer_wat_anchor_manifest_id: Optional[str] = None
    peer_trust_bundle_url: Optional[str] = None
    peer_capability_policy_pointer: Optional[str] = None
    is_mock: bool = False

    def __post_init__(self) -> None:  # noqa: D401 - validator
        if not isinstance(self.route_id, str) or not self.route_id:
            raise MultiOrgAttestationValidationError(
                "route_id must be a non-empty string"
            )
        if not isinstance(self.peer_trust_domain, str):
            raise MultiOrgAttestationValidationError(
                "peer_trust_domain must be a string"
            )
        if not _TRUST_DOMAIN_RE.match(self.peer_trust_domain):
            raise MultiOrgAttestationValidationError(
                f"peer_trust_domain {self.peer_trust_domain!r} "
                f"does not match SPIFFE trust-domain grammar"
            )
        if not isinstance(self.peer_audit_anchor_did, str):
            raise MultiOrgAttestationValidationError(
                "peer_audit_anchor_did must be a string"
            )
        if not _DID_WEB_RE.match(self.peer_audit_anchor_did):
            raise MultiOrgAttestationValidationError(
                f"peer_audit_anchor_did {self.peer_audit_anchor_did!r} "
                f"is not a recognised did:web identifier "
                f"(other DID methods MAY be added in a future minor "
                f"bump)"
            )
        if self.peer_wat_anchor_manifest_id is not None and not isinstance(
            self.peer_wat_anchor_manifest_id, str
        ):
            raise MultiOrgAttestationValidationError(
                "peer_wat_anchor_manifest_id must be a string or None"
            )
        if self.peer_trust_bundle_url is not None and not isinstance(
            self.peer_trust_bundle_url, str
        ):
            raise MultiOrgAttestationValidationError(
                "peer_trust_bundle_url must be a string or None"
            )
        if self.peer_trust_bundle_url is not None and not (
            self.peer_trust_bundle_url.startswith("https://")
        ):
            raise MultiOrgAttestationValidationError(
                "peer_trust_bundle_url must be an https:// URL"
            )
        if self.peer_capability_policy_pointer is not None and not isinstance(
            self.peer_capability_policy_pointer, str
        ):
            raise MultiOrgAttestationValidationError(
                "peer_capability_policy_pointer must be a string or None"
            )
        if not isinstance(self.is_mock, bool):
            raise MultiOrgAttestationValidationError(
                "is_mock must be a bool"
            )
        # Mock-prefix consistency check: both directions enforced so
        # neither a real route can sneak in via the mock path nor a
        # mock route be miscoded as live.
        has_mock_prefix = self.route_id.startswith(
            MOCK_BRIDGE_ROUTE_ID_PREFIX
        )
        if self.is_mock and not has_mock_prefix:
            raise MultiOrgAttestationValidationError(
                f"is_mock=True requires route_id to start with "
                f"{MOCK_BRIDGE_ROUTE_ID_PREFIX!r}; got {self.route_id!r}"
            )
        if not self.is_mock and has_mock_prefix:
            raise MultiOrgAttestationValidationError(
                f"is_mock=False forbids the {MOCK_BRIDGE_ROUTE_ID_PREFIX!r} "
                f"prefix; got {self.route_id!r}"
            )


# ---------------------------------------------------------------------------
# InMemoryMultiOrgAttestationRegistry
# ---------------------------------------------------------------------------


@dataclass
class InMemoryMultiOrgAttestationRegistry:
    """Phase-3-preparation reference attestation registry.

    Mirrors the Phase-1b :class:`InMemoryRouteRegistry` shape: a
    plain dataclass holding a dict keyed by ``route_id``. The
    Sprint-7 Tag-2 NATS-KV backend will replace this 1:1 with the
    same surface (``add`` / ``lookup`` / ``snapshot`` / ``watch``).

    The registry enforces *at most one attestation per route_id*.
    A second ``add()`` with the same ``route_id`` raises
    :class:`MultiOrgAttestationConflictError` unless the second
    attestation is byte-equal to the first (idempotent re-add is
    allowed, mirroring the Sprint-5 LWW + Tag-3 watch-stream
    idempotency contract).
    """

    attestations: dict

    def __init__(self, attestations: Optional[dict] = None) -> None:
        self.attestations = dict(attestations) if attestations else {}

    def add(self, attestation: MultiOrgRouteAttestation) -> None:
        """Insert a new attestation. Idempotent re-adds (byte-equal)
        are silently accepted; non-equal updates raise
        :class:`MultiOrgAttestationConflictError`.

        Update semantics (replacing an existing attestation with a
        non-equal one) are deliberately not supported by the
        in-memory reference; the Sprint-7 Tag-2 NATS-KV backend
        will expose ``put_with_revision`` for CAS-protected
        updates, matching the Sprint-3 Tag-3 schema-registry
        pattern.
        """
        if not isinstance(attestation, MultiOrgRouteAttestation):
            raise TypeError(
                "attestation must be a MultiOrgRouteAttestation"
            )
        existing = self.attestations.get(attestation.route_id)
        if existing is not None and existing != attestation:
            raise MultiOrgAttestationConflictError(
                f"attestation already registered for "
                f"route_id={attestation.route_id!r} with different "
                f"fields; use put_with_revision once the Tag-2 "
                f"backend lands"
            )
        self.attestations[attestation.route_id] = attestation

    def lookup(
        self, route_id: str
    ) -> Optional[MultiOrgRouteAttestation]:
        """Return the attestation for ``route_id``, or ``None`` if
        no attestation has been registered. A ``None`` return
        means the route is single-org / Wakir-internal.
        """
        if not isinstance(route_id, str):
            return None
        return self.attestations.get(route_id)


# ---------------------------------------------------------------------------
# Mock-bridge-route resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MockBridgeResolution:
    """Result of :func:`resolve_mock_bridge_route`.

    Pairs the underlying :class:`RouteRegistryEntry` with the
    :class:`MultiOrgRouteAttestation`. The Sprint-7 Tag-3+ live
    bridge component (SpiffeCrossTrustDomainBridge) will return
    a structurally analogous result; the live path will also
    yield a validated SPIFFE trust-bundle and resolved DID
    document, which the mock path omits by design.
    """

    entry: RouteRegistryEntry
    attestation: MultiOrgRouteAttestation


def resolve_mock_bridge_route(
    route_id: str,
    *,
    route_registry,
    attestation_registry: InMemoryMultiOrgAttestationRegistry,
) -> MockBridgeResolution:
    """Resolve a mock-bridge route to its (entry, attestation) pair.

    This is the Sprint-7 substrate-iteration entry-point that lets
    callers exercise the multi-org composition (entry + attestation)
    without a live SPIRE bundle endpoint or a live did:web fetch.

    Contract:

    - ``route_id`` MUST start with
      :data:`MOCK_BRIDGE_ROUTE_ID_PREFIX` (enforces caller intent;
      the live bridge is a separate function).
    - ``route_registry`` MUST be a :class:`RouteRegistry` (Protocol)
      that returns a :class:`RouteRegistryEntry` for the
      ``route_id`` (or ``None``, in which case
      :class:`UnknownBridgeRouteError` is raised).
    - ``attestation_registry`` MUST hold a
      :class:`MultiOrgRouteAttestation` for the ``route_id`` with
      ``is_mock=True`` (otherwise
      :class:`UnknownBridgeRouteError` is raised).

    Failure modes (fail-closed per V-908 §6 conservative-safe-
    default convention):

    - unknown route_id           -> :class:`UnknownBridgeRouteError`
    - missing attestation        -> :class:`UnknownBridgeRouteError`
    - attestation not mock       -> :class:`UnknownBridgeRouteError`
    - bad prefix on route_id     -> :class:`UnknownBridgeRouteError`
    """
    if not isinstance(route_id, str):
        raise UnknownBridgeRouteError(
            f"route_id must be a string; got {type(route_id).__name__}"
        )
    if not route_id.startswith(MOCK_BRIDGE_ROUTE_ID_PREFIX):
        raise UnknownBridgeRouteError(
            f"route_id {route_id!r} does not carry the "
            f"{MOCK_BRIDGE_ROUTE_ID_PREFIX!r} prefix"
        )
    entry = route_registry.lookup(route_id)
    if entry is None:
        raise UnknownBridgeRouteError(
            f"route_id {route_id!r} not in route registry"
        )
    attestation = attestation_registry.lookup(route_id)
    if attestation is None:
        raise UnknownBridgeRouteError(
            f"route_id {route_id!r} has no multi-org attestation"
        )
    if not attestation.is_mock:
        raise UnknownBridgeRouteError(
            f"route_id {route_id!r} attestation is not a mock; "
            f"use the live bridge once Tag-3+ lands"
        )
    return MockBridgeResolution(entry=entry, attestation=attestation)


__all__ = [
    "ATTESTATION_VALUE_SCHEMA",
    "MOCK_BRIDGE_ROUTE_ID_PREFIX",
    "MultiOrgSubstrateError",
    "MultiOrgAttestationValidationError",
    "MultiOrgAttestationConflictError",
    "UnknownBridgeRouteError",
    "MultiOrgRouteAttestation",
    "InMemoryMultiOrgAttestationRegistry",
    "MockBridgeResolution",
    "resolve_mock_bridge_route",
]
