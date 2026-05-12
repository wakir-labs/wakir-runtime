# SPDX-License-Identifier: Apache-2.0
"""V-908 Federation-Resolver pipeline (Phase-1b PS-5).

This module ties the Tag-6 FTD-verifier (``ftd_verifier``) together
with the Phase-1a AIP-document resolver (``aip_resolver``) into a
single end-to-end entry point for cross-org AIP-doc resolution::

    resolve_federated_aip(aip_did, ftd_did, *, ftd_resolver,
                          ftd_doc_jcs_bytes, aip_resolver, ...)
        -> FederatedResolveResult

The verifier composes the two layers per V-908 spec section 4.1
(steps 4-10). The FTD layer (steps 1-3) is delegated wholesale to
:func:`wirelang.identity.ftd_verifier.verify_ftd_document`; this
module wires its output (the windowed ``valid_issuer_keys``) into
the AIP-side pipeline as an explicit cross-check against the AIP
document's signing key.

Pipeline shape (V-908 section 4.1, Phase-1b):

1.  Token shape parse (caller-side; not implemented here).
2.  FTD lookup (caller passes the FTD ``id`` and pre-fetched body
    bytes; HTTPS transport is caller-side per V-908 section 3.3).
3.  FTD verify (delegated to ``ftd_verifier.verify_ftd_document``).
4.  **AIP fetch.** AIP-doc fetched via the caller-supplied
    :class:`AIPResolverLike` backend. The AIP URL host MUST equal
    the FTD ``domain`` field; mismatch raises
    :class:`FTDDomainMismatchError` (V-908 section 4.6 row).
5.  AIP schema-check (delegated to the resolver).
6.  AIP ``id`` consistency (delegated; Phase-1a phishing-guard).
7.  **AIP signature verify with FTD cross-check.** The AIP's
    signing key MUST be present in the FTD's
    ``valid_issuer_keys`` set with ``purpose == 'biscuit-root'``;
    mismatch raises :class:`FederatedIssuerKeyError`.
8.  JCS recompute (delegated).
9.  Optional caller pin (delegated).
10. Cache update + result return.

Layering / sandbox boundary
---------------------------

Phase-1a's reference :mod:`wirelang.identity.aip_resolver` module
hard-imports ``rfc8785`` and ``jsonschema``; both are absent in
the current sandbox build (Tag-2 / Tag-5 / Tag-6 capability stamp).
This federation resolver therefore declares an
:class:`AIPResolverLike` ``Protocol`` that any AIP-side resolver
(production or test stub) must satisfy. Production deployments
plug in :class:`wirelang.identity.aip_resolver.AIPResolver`
directly; the test suite supplies a small in-tree stub that
implements the same Protocol with pure-Python primitives.

This deliberately mirrors the Tag-6 strategy of "verify pipeline
hot path runs in pure Python so tests stay sandbox-grade" while
preserving the production-grade plug-in path. The Protocol
boundary is the only API contract between this module and the
AIP-side resolver implementation.

Phase-1b boundary
-----------------

Out of scope:

- HTTPS transport for FTD-doc and AIP-doc fetch (caller-side per
  V-908 section 3.3).
- Token-shape parse and Biscuit-chain verify (V-908 section 4.1
  step 1 and step 10; downstream of this module).
- WAT-leaf projection for federated tokens (V-908 section 5.1
  informative; Z3 cross-review with WAT-eng).
- Persona-hash chain cross-check (V-907 / item I-12 hook in the
  AIP resolver).
- Time-source bridge cross-check (V-908 section 4.4; item I-9).

References (URL-stamped 2026-05-07 by wirelang-eng, see V-908
spec §9):

- V-908 spec: ``wirelang/specs/wakir-v-908-federation-resolver-spec.md``
- AIP resolver: ``wirelang/identity/aip_resolver.py`` (Tag-21 stub)
- FTD verifier: ``wirelang/identity/ftd_verifier.py`` (Tag-6 PS-4)
- DNS anchor: ``wirelang/identity/dns_anchor.py`` (Tag-5)
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol, Tuple, runtime_checkable
from urllib.parse import urlsplit

from .ftd_verifier import (
    FTDCache,
    FTDVerifyError,
    ValidIssuerKey,
    VerifyResult as FTDVerifyResult,
    verify_ftd_document,
)


# ---------------------------------------------------------------------------
# Errors (V-908 section 4.6 federated rows)
# ---------------------------------------------------------------------------


class FederatedResolveError(Exception):
    """Base class for federated-resolve errors.

    Mirrors the ``AIPResolveError`` and ``FTDVerifyError`` Phase-1a /
    PS-4 conventions so callers can branch on the failure mode.
    """


class FTDDomainMismatchError(FederatedResolveError):
    """V-908 section 4.6 row.

    Raised when the AIP document URL host does not match the FTD
    document's ``domain`` field. This is the federation analog of
    Phase-1a's resolver-trusted URL-host policy: the FTD-doc's
    ``domain`` is the *only* host allowed to serve AIP docs that
    claim federation membership in this trust domain.
    """


class FederatedIssuerKeyError(FederatedResolveError):
    """V-908 section 4.1 step 7 cross-check failure.

    Raised when the AIP-doc's signing key is not present in the
    FTD-doc's ``valid_issuer_keys`` set (or the matched entry is
    not currently in its validity window with
    ``purpose == 'biscuit-root'``). The Phase-1a AIP-side
    signature verify itself succeeded; the failure is at the
    federation cross-check layer.
    """


# ---------------------------------------------------------------------------
# AIP-side Protocol (duck-typing boundary; sandbox-friendly)
# ---------------------------------------------------------------------------


@runtime_checkable
class AIPDocumentLike(Protocol):
    """Minimal shape that the federation pipeline reads from an
    AIP resolver result.

    The Phase-1a reference :class:`wirelang.identity.aip_resolver.AIPDocument`
    satisfies this Protocol by construction. A production resolver,
    a test stub, or a future extended document type may substitute
    so long as the four attributes below are present and
    semantically consistent with the V-908 layering.

    Attributes:
        id: AIP document id (URI). Used for the ``host`` extraction
            against the FTD ``domain``.
        body: full AIP document body. Used to derive the signing
            ``kid`` / ``public_key_hex`` for the FTD cross-check.
        jcs_sha256: SHA-256 of JCS(body without document_signature).
            Forwarded into the result for WAT-leaf consumers.
        biscuit_root_pubkey_hex: 64-hex Ed25519 root key the
            Phase-1a resolver derived during signature verify; this
            is the candidate that MUST appear in the FTD
            ``valid_issuer_keys`` set under the federated pipeline.
    """

    id: str
    body: dict
    jcs_sha256: str
    biscuit_root_pubkey_hex: str


@runtime_checkable
class AIPResolverLike(Protocol):
    """Minimal shape that the federation pipeline expects of an
    AIP-side resolver.

    Phase-1a's :class:`wirelang.identity.aip_resolver.AIPResolver`
    satisfies this Protocol. The pipeline relies on two
    behaviours:

    1. ``resolve(uri)`` returns a verified
       :class:`AIPDocumentLike` (Phase-1a verify-pipeline already
       executed: schema, signature, JCS, id-consistency).
    2. The resolver does NOT block the federation cross-check;
       i.e. the resolver's policy is "trust the local key
       resolution"; the federation layer is the one that adds the
       FTD cross-check on top.
    """

    def resolve(self, uri: str) -> AIPDocumentLike:
        """Return a verified AIP document, or raise."""
        ...


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FederatedResolveResult:
    """Outcome of a successful federated AIP resolution.

    Attributes:
        aip_id: the AIP document id (URI) that was resolved.
        ftd_id: the FTD document id consulted.
        aip_body: the verified AIP document body (defensive copy
            owned by the underlying resolver result).
        aip_jcs_sha256: SHA-256(JCS(aip_body without
            ``document_signature``)). Forwarded from the AIP
            resolver for WAT-leaf consumers.
        ftd_fingerprint_sha256: SHA-256(JCS(ftd_doc without
            ``document_signature``)). Forwarded from the FTD
            verifier for WAT-leaf consumers.
        biscuit_root_pubkey_hex: 64-hex Ed25519 key that signed
            the AIP document; verified to be present in the FTD's
            ``valid_issuer_keys`` set with
            ``purpose == 'biscuit-root'`` and current validity
            window.
        matched_issuer_kid: the FTD ``issuer_keys[].kid`` entry
            that matched the AIP signing key. Useful for audit and
            for Phase-2 ``peer_org`` predicate evaluation.
        verified_at: wall-clock UTC at the moment verification
            ran end-to-end.
    """

    aip_id: str
    ftd_id: str
    aip_body: dict
    aip_jcs_sha256: str
    ftd_fingerprint_sha256: str
    biscuit_root_pubkey_hex: str
    matched_issuer_kid: str
    verified_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _aip_url_host(aip_id: str) -> str:
    """Extract the host component the AIP document is served from.

    The Phase-1a fixtures and Tag-21 resolver use AIP ids of the
    shape ``aip:web:<host>/<persona-path>``; production extension
    will use ``https://<host>/...`` URIs once the HTTPS transport
    is wired (V-908 section 3.3, Phase-1b boundary).

    This helper accepts both shapes:

    - ``aip:web:host/path``                   -> ``host``
    - ``aip:web:host:port/path``              -> ``host:port``
    - ``https://host/path`` or ``http://...`` -> ``host`` (incl. port)

    Returns the lower-cased host string. Raises
    :class:`ValueError` if the id is structurally unparseable.
    """
    if not isinstance(aip_id, str) or not aip_id:
        raise ValueError("aip_id must be a non-empty string")

    if aip_id.startswith("https://") or aip_id.startswith("http://"):
        parts = urlsplit(aip_id)
        host = parts.hostname or ""
        # urlsplit lower-cases hostname already; include port if any
        if parts.port:
            host = f"{host}:{parts.port}"
        if not host:
            raise ValueError(f"aip_id has no host: {aip_id!r}")
        return host

    if aip_id.startswith("aip:web:"):
        rest = aip_id[len("aip:web:") :]
        # Slash separates host[:port] from the persona path.
        slash = rest.find("/")
        host = rest if slash == -1 else rest[:slash]
        if not host:
            raise ValueError(f"aip:web id has no host: {aip_id!r}")
        return host.lower()

    raise ValueError(f"aip_id scheme not supported by federation pipeline: {aip_id!r}")


def _match_issuer_key(
    biscuit_root_pubkey_hex: str,
    valid_issuer_keys: Tuple[ValidIssuerKey, ...],
) -> Optional[ValidIssuerKey]:
    """Linear scan of windowed issuer keys for a public-key match.

    The verifier already filtered ``valid_issuer_keys`` to the
    set whose validity window includes ``now`` (FTD pipeline
    step 6). We additionally require ``purpose == 'biscuit-root'``
    here per V-908 section 4.1 step 7.

    Returns the matching entry or ``None``.
    """
    target = biscuit_root_pubkey_hex.lower()
    for entry in valid_issuer_keys:
        if entry.purpose != "biscuit-root":
            continue
        if entry.public_key_hex.lower() == target:
            return entry
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_federated_aip(
    aip_id: str,
    ftd_id: str,
    *,
    ftd_resolver,  # TxtResolver from .dns_anchor
    ftd_doc_jcs_bytes: bytes,
    aip_resolver: AIPResolverLike,
    ftd_cache: Optional[FTDCache] = None,
    now: Optional[datetime] = None,
    dns_timeout_s: float = 3.0,
) -> FederatedResolveResult:
    """End-to-end federated AIP resolve (V-908 section 4.1 steps 4-10).

    This is the single public entry point for cross-org AIP
    resolution under a federation trust domain. It composes the
    Tag-6 FTD-verifier with the Phase-1a AIP-resolver and adds
    the V-908 federation-specific cross-checks
    (``FTDDomainMismatchError``, ``FederatedIssuerKeyError``).

    Args:
        aip_id: the AIP document id (URI) to resolve. Must claim
            membership in the FTD trust domain identified by
            ``ftd_id``.
        ftd_id: the federation trust document id (a ``did:web:...``
            string per V-908 section 3.1).
        ftd_resolver: a :class:`wirelang.identity.dns_anchor.TxtResolver`
            instance the FTD verifier uses to fetch the DNS anchor.
        ftd_doc_jcs_bytes: the JCS-canonical bytes of the FTD
            document body, pre-fetched by the caller per V-908
            section 3.3.
        aip_resolver: a Phase-1a-compatible
            :class:`AIPResolverLike` instance.
        ftd_cache: optional :class:`FTDCache` to reuse across
            calls. If ``None`` the verifier creates an internal
            scratch cache; reuse the cache across calls for
            production-grade behaviour.
        now: optional UTC wall-clock override (testing).
        dns_timeout_s: DNS-resolver timeout, forwarded to FTD verify.

    Returns:
        :class:`FederatedResolveResult` with the verified AIP
        body, the matched issuer key, and the byte-anchors
        (``aip_jcs_sha256``, ``ftd_fingerprint_sha256``) for
        WAT-leaf consumers.

    Raises:
        :class:`FTDVerifyError` (and subclasses) if the FTD layer
            fails. Forwarded unchanged.
        :class:`FTDDomainMismatchError` if the AIP id host does
            not match the FTD ``domain`` (V-908 section 4.6).
        :class:`FederatedIssuerKeyError` if the AIP signing key is
            not present in the FTD's ``valid_issuer_keys`` set with
            ``purpose == 'biscuit-root'``.
        any error raised by the AIP resolver (typically Phase-1a
            ``AIPSchemaError``, ``AIPSignatureError``,
            ``AIPHashMismatchError``, ``AIPNotFoundError``).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ----- Steps 1-3: FTD verify -------------------------------------
    # If the caller supplied a cache, consult it first; the verifier
    # itself does not consult the cache (its API takes pre-fetched
    # bytes and is therefore stateless w.r.t. cache hits).
    ftd_result: Optional[FTDVerifyResult] = None
    if ftd_cache is not None:
        ftd_result = ftd_cache.get(ftd_id)

    if ftd_result is None:
        ftd_result = verify_ftd_document(
            ftd_doc_jcs_bytes,
            ftd_id,
            resolver=ftd_resolver,
            now=now,
            dns_timeout_s=dns_timeout_s,
            cache=ftd_cache,  # verify_ftd_document handles put-on-success
        )

    # ----- Step 4: AIP fetch with FTD-domain enforcement -------------
    # Bind the AIP URL host to the FTD ``domain`` BEFORE we delegate
    # to the AIP resolver. This is the V-908 section 4.6 row that
    # Phase-1a does not enforce (because Phase-1a trusts the local
    # backend mapping). Phase-1b federation rejects any AIP id whose
    # host does not match the FTD domain even if the resolver would
    # otherwise serve it.
    try:
        aip_host = _aip_url_host(aip_id)
    except ValueError as exc:
        raise FTDDomainMismatchError(
            f"AIP id is not parseable as URL host: {exc}"
        ) from exc

    ftd_domain = ftd_result.ftd_doc.get("domain", "")
    if not isinstance(ftd_domain, str) or not ftd_domain:
        # FTD verifier already enforces shape, but defensive-double-check
        raise FTDDomainMismatchError(
            f"FTD document {ftd_id!r} has no domain field"
        )

    if aip_host.lower() != ftd_domain.lower():
        raise FTDDomainMismatchError(
            f"AIP host {aip_host!r} does not match FTD domain "
            f"{ftd_domain!r} for FTD {ftd_id!r}"
        )

    # ----- Steps 5, 6, 8, 9: delegate to AIP resolver ----------------
    # The Phase-1a resolver handles schema-check, id-consistency,
    # JCS recompute, and (if used) the optional caller pin.
    aip_doc = aip_resolver.resolve(aip_id)

    # ----- Step 7: AIP signature key cross-check vs FTD --------------
    # The Phase-1a resolver already verified the signature against
    # whatever ``biscuit_root_pubkey`` it derived from the AIP body.
    # Federation requires that this key is also present in the FTD's
    # current valid issuer set.
    matched = _match_issuer_key(
        aip_doc.biscuit_root_pubkey_hex,
        ftd_result.valid_issuer_keys,
    )
    if matched is None:
        raise FederatedIssuerKeyError(
            f"AIP signing key {aip_doc.biscuit_root_pubkey_hex!r} not "
            f"present in FTD {ftd_id!r} valid_issuer_keys set"
        )

    # ----- Step 10: cache update + return ----------------------------
    # FTD-cache update was already handled inside verify_ftd_document
    # when applicable; the AIP-side resolver owns its own cache.
    return FederatedResolveResult(
        aip_id=aip_doc.id,
        ftd_id=ftd_result.ftd_id,
        aip_body=copy.deepcopy(aip_doc.body),
        aip_jcs_sha256=aip_doc.jcs_sha256,
        ftd_fingerprint_sha256=ftd_result.fingerprint_sha256,
        biscuit_root_pubkey_hex=aip_doc.biscuit_root_pubkey_hex,
        matched_issuer_kid=matched.kid,
        verified_at=now,
    )


__all__ = [
    "AIPDocumentLike",
    "AIPResolverLike",
    "FederatedIssuerKeyError",
    "FederatedResolveError",
    "FederatedResolveResult",
    "FTDDomainMismatchError",
    "resolve_federated_aip",
]
