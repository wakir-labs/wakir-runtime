# SPDX-License-Identifier: Apache-2.0
"""Phase-2 Sprint-4 Tag-4 AIP-document transport-fetch.

This module is the Phase-2 follow-up to the Sprint-4 Tag-3
``kid_resolver`` boundary statement: "the resolver does NOT fetch
the AIP document over transport". Tag-4 plugs that gap with a thin
composition layer that:

1.  Maps an ``aip:web:host/path`` identifier to a canonical
    ``https://host/.well-known/aip/<path>.json`` URL (the Wakir
    convention; see ``wirelang/tests/test_layer_3_capability_token.py``
    ``aip_document_ref = "https://wakir.dev/.well-known/aip/<persona>.json"``
    for the reference shape).
2.  Fetches the body via the Phase-1b V-908 HTTPS-transport layer
    (``wirelang.identity.aip_https_backend.HTTPSDocumentTransport``).
3.  Optionally cross-checks the document against a Wakir-style DNS
    TXT anchor record at ``_wakir-aip.<host>`` (V-908 §3.4 federation
    pattern extended from FTD to AIP-document; same shape
    ``v=1; sha256=<64-hex>`` over ``SHA-256(JCS(body without
    document_signature))``).
4.  Returns the verified body alongside its JCS byte-anchor for
    direct hand-off to :func:`wirelang.identity.resolve_kid`.

Phase-2 Sprint-4 Tag-4 boundary
-------------------------------

This module deliberately does NOT:

* Validate the AIP document's ``document_signature`` slot. Establishing
  AIP-document signing-trust is the caller's responsibility — see
  :func:`wirelang.identity.verify_aip_signature`. The Tag-4 fetch
  layer is byte-orthogonal to the signing trust layer.
* Validate the AIP document against the JSON Schema. Schema-validation
  belongs to the Phase-1a ``aip_resolver`` (sandbox-restricted to
  ``rfc8785`` + ``jsonschema`` paths). Tag-4 returns the parsed body
  unchanged and lets the caller drive schema-validation.
* Mutate the schema-registry backend surface. ``NatsKvSchemaRegistry``
  is unchanged; no new method, no new envelope.
* Cache the result. The V-908 ``HTTPSAipResolverCache`` already exists
  in the HTTPS backend for the federation pipeline; Tag-4 is a stateless
  pure-composition layer. Production callers compose with the existing
  cache or roll a tier on top.

DNS-anchor cross-check semantics
---------------------------------

The cross-check is parameter-controlled via ``anchor_required``:

* ``anchor_required=False`` (default): if ``dns_resolver`` is ``None``
  the call short-circuits to a plain HTTPS fetch. If a resolver is
  supplied, the call still does a best-effort TXT lookup and includes
  the resulting anchor in :class:`AipFetchResult` (or ``None`` if the
  record is absent or malformed), but a missing/malformed anchor is
  NOT a hard failure.
* ``anchor_required=True``: a missing or malformed DNS TXT record at
  ``_wakir-aip.<host>`` raises
  :class:`AipDnsAnchorMismatchError`. A fingerprint mismatch between
  the anchor and the JCS digest of the fetched body also raises this
  error. Production hard-trust paths SHOULD set this.

The anchor name prefix ``_wakir-aip`` mirrors V-908 §3.4's
``_wakir-ftd`` pattern; the TXT-record shape is identical so we
reuse :func:`wirelang.identity.dns_anchor.parse_anchor` verbatim.

V-908 spec cross-references
---------------------------

* V-908 §3.3 (HTTPS transport) — fully delegated to the Tag-8
  ``HTTPSDocumentTransport`` (no new transport invariants here).
* V-908 §3.4 (DNS anchor) — extended in shape from FTD-doc to
  AIP-doc; the TXT-record format and trust-model are byte-identical.
* Schema-Registry spec §5.10 (Phase-2 Sprint-4 Tag-4 follow-up to
  §5.9 ``kid_resolver``) — documents the Tag-4 composition layer and
  the Tag-4 boundary statements (above).

Cross-Review-Zone-1 (Identity-Substrate) — non-touched
------------------------------------------------------

Tag-4 closes the Z-1-Sprint-4-Anhang follow-up slot
"AIP-document transport-fetch" without touching any of the four
Z-1-K-Sprint-4 consensus points:

* Z-1-K-Sprint-4-1 (kid-Resolver-Shape) — non-touched; Tag-3 closed it.
  Tag-4 feeds the resolver, does not modify its surface.
* Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) — non-touched; this module
  consumes ``aip_signing._jcs_canonicalize`` byte-identical (no new
  JCS path).
* Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) — non-touched; this layer
  is curve-agnostic (it fetches a document, not a key).
* Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) — non-touched;
  ``anchor_required`` is the Tag-4 hard-vs-soft toggle and is
  independent of the schema-registry-signing STRICT toggle.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from .aip_https_backend import (
    HTTPSBackendError,
    HTTPSDocumentResponse,
    HTTPSDocumentTransport,
)
from .dns_anchor import (
    DnsAnchor,
    DnsAnchorError,
    TxtResolver,
    fetch_anchor,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AipDocumentTransportError(Exception):
    """Base class for Tag-4 AIP-document transport-fetch failures.

    Subclasses distinguish parse-side errors (URL scheme) from
    cross-check errors (DNS-anchor mismatch). Transport-level failures
    propagate unchanged as :class:`HTTPSBackendError` subclasses; the
    Tag-4 layer does NOT wrap them so callers retain typed access to
    the V-908 §3.3 invariants.
    """


class AipUrlSchemeError(AipDocumentTransportError):
    """The ``aip_id`` is not a parseable AIP identifier.

    Tag-4 accepts two shapes:

    * ``aip:web:host[:port]/path`` (the Wakir-canonical form).
    * ``https://host[:port]/path`` (a pre-resolved HTTPS URL, returned
      as-is). ``http://`` is rejected — V-908 §3.3 is HTTPS-only.

    All other shapes raise this error.
    """


class AipDnsAnchorMismatchError(AipDocumentTransportError):
    """Raised when DNS-anchor cross-check fails.

    Carries the ``host`` and the offending ``aip_id`` plus, when
    available, the expected and observed fingerprint hex strings.
    The federation resolver in V-908 §4.1 step 3 raises a similar
    typed error on FTD-side anchor mismatches; this is the AIP-side
    analog for Phase-2 Tag-4.

    Raised when:

    * ``anchor_required=True`` and the TXT record is absent / malformed
      (the underlying :class:`DnsAnchorError` is wrapped).
    * The TXT record's fingerprint does not match
      ``SHA-256(JCS(body without document_signature))``.
    """

    def __init__(
        self,
        message: str,
        *,
        aip_id: str,
        host: str,
        expected: Optional[str] = None,
        observed: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.aip_id = aip_id
        self.host = host
        self.expected = expected
        self.observed = observed


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AipFetchResult:
    """The outcome of a successful Tag-4 AIP-document fetch.

    Attributes:
        aip_id: the input AIP identifier (``aip:web:...`` or pre-resolved
            ``https://...``).
        url: the canonical HTTPS URL that was fetched (after the
            aip:web → HTTPS mapping; for an https:// input the field
            equals ``aip_id``).
        host: the lower-cased host component (without scheme), used for
            the DNS-anchor lookup.
        aip_doc: the parsed AIP-document body (a ``dict``). Suitable for
            direct hand-off to :func:`wirelang.identity.resolve_kid`.
        body_bytes: raw HTTPS response bytes. Preserved for downstream
            JCS recomputation by signature-verify paths.
        jcs_sha256_hex: lower-case hex of
            ``SHA-256(JCS(body without document_signature))``. This is
            the canonical AIP-doc byte-anchor; identical in shape to
            the V-908 FTD-fingerprint convention.
        dns_anchor: the parsed DNS anchor, or ``None`` when the call
            was made with no resolver or when the resolver lookup
            failed in soft-mode (``anchor_required=False``).
        anchor_matched: ``True`` iff a DNS anchor was both present and
            its fingerprint equals ``jcs_sha256_hex``. Always ``False``
            when ``dns_anchor`` is ``None``.
    """

    aip_id: str
    url: str
    host: str
    aip_doc: dict
    body_bytes: bytes
    jcs_sha256_hex: str
    dns_anchor: Optional[DnsAnchor]
    anchor_matched: bool


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


#: The Wakir-canonical AIP-document path-prefix under the well-known
#: namespace. Per RFC 8615 the ``.well-known`` registry is the right
#: home for under-host identity documents; the Tag-4 ``aip`` subspace
#: is the Wakir convention (V-908 §3.4 sibling).
WELL_KNOWN_AIP_PREFIX: str = "/.well-known/aip/"

#: The Wakir DNS anchor prefix for AIP documents. Mirrors V-908 §3.4's
#: ``_wakir-ftd`` prefix (FTD-doc anchor) byte-for-byte in shape; only
#: the role-string differs (``-aip`` vs ``-ftd``). Same TXT-record
#: format ``v=1; sha256=<64-hex>``.
DNS_ANCHOR_PREFIX: str = "_wakir-aip."


# ---------------------------------------------------------------------------
# aip:web → HTTPS URL
# ---------------------------------------------------------------------------


def aip_web_to_https_url(aip_id: str) -> tuple[str, str]:
    """Translate an AIP identifier to a canonical HTTPS URL + host.

    The Wakir Phase-2 convention publishes AIP documents under
    ``https://<host>/.well-known/aip/<persona-path>.json``. For
    ``aip:web:host/path`` inputs this function performs the mapping;
    for pre-resolved ``https://...`` inputs it returns the URL
    unchanged (the host is parsed from the URL).

    Args:
        aip_id: an AIP identifier. Accepted shapes:

            * ``aip:web:host[:port]/persona-path``
            * ``aip:web:host[:port]`` (no path; ``index.json`` is implied)
            * ``https://host[:port]/...`` (pre-resolved)

    Returns:
        Tuple ``(url, host)`` where ``url`` is the canonical HTTPS URL
        and ``host`` is the lower-cased host[:port] string suitable for
        the DNS-anchor lookup.

    Raises:
        AipUrlSchemeError: the input is not a parseable AIP identifier.
    """
    if not isinstance(aip_id, str) or not aip_id:
        raise AipUrlSchemeError("aip_id must be a non-empty string")

    if aip_id.startswith("aip:web:"):
        rest = aip_id[len("aip:web:") :]
        if not rest:
            raise AipUrlSchemeError(f"aip:web id has no host: {aip_id!r}")
        slash = rest.find("/")
        if slash == -1:
            host = rest
            persona_path = "index"
        else:
            host = rest[:slash]
            persona_path = rest[slash + 1 :]
            if not persona_path:
                persona_path = "index"
        if not host:
            raise AipUrlSchemeError(f"aip:web id has empty host: {aip_id!r}")
        host_lc = host.lower()
        # Strip any trailing .json the caller may have written into the
        # persona-path; the well-known URL adds it back so the canonical
        # form is single-source.
        if persona_path.endswith(".json"):
            persona_path = persona_path[: -len(".json")]
        url = f"https://{host_lc}{WELL_KNOWN_AIP_PREFIX}{persona_path}.json"
        return url, host_lc

    if aip_id.startswith("https://"):
        # Pre-resolved URL: trust the caller's URL but parse out the
        # host for DNS-anchor lookup.
        # Minimal parse (avoid urlsplit dependency cycle / behaviour drift):
        rest = aip_id[len("https://") :]
        if not rest:
            raise AipUrlSchemeError(f"https URL has no host: {aip_id!r}")
        slash = rest.find("/")
        host = rest if slash == -1 else rest[:slash]
        if not host:
            raise AipUrlSchemeError(f"https URL has empty host: {aip_id!r}")
        return aip_id, host.lower()

    if aip_id.startswith("http://"):
        raise AipUrlSchemeError(
            f"plaintext http:// is forbidden (V-908 §3.3): {aip_id!r}"
        )

    raise AipUrlSchemeError(
        f"aip_id scheme not supported (expected aip:web: or https://): {aip_id!r}"
    )


# ---------------------------------------------------------------------------
# JCS-anchor recomputation
# ---------------------------------------------------------------------------


def _jcs_anchor_hex(aip_doc: dict) -> str:
    """Compute ``SHA-256(JCS(body without document_signature))`` hex.

    Identical in shape and byte-output to the V-908 FTD-fingerprint
    convention (V-908 §2.1). The ``document_signature`` slot is removed
    from a deep copy of the input so the caller's body is not mutated.

    The JCS canonicaliser is the resolver-indirected one used by
    :mod:`wirelang.identity.aip_signing`; we import it lazily to avoid
    a circular module dependency at import time and to keep the Tag-4
    module importable in the sandbox build (where ``rfc8785`` is
    absent — the pure-Python fallback is exercised instead).
    """
    # Lazy import: aip_signing imports a small graph; keeping the
    # dependency import-time-lazy avoids a chain where any consumer of
    # aip_document_transport_fetch pays the aip_signing import cost
    # whether or not they touch the anchor path.
    from .aip_signing import _jcs_canonicalize  # noqa: WPS437 -- internal-use OK

    body = copy.deepcopy(aip_doc)
    body.pop("document_signature", None)
    canonical = _jcs_canonicalize(body)
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_aip_document(
    aip_id: str,
    *,
    transport: HTTPSDocumentTransport,
    dns_resolver: Optional[TxtResolver] = None,
    anchor_required: bool = False,
    dns_timeout_s: float = 3.0,
) -> AipFetchResult:
    """Fetch and (optionally) DNS-anchor-cross-check an AIP document.

    This is the single public entry point for Phase-2 Sprint-4 Tag-4
    AIP-document transport-fetch. The function composes the V-908
    HTTPS-transport layer (Tag-8 ``HTTPSDocumentTransport``) with the
    V-908 DNS-anchor lookup (``dns_anchor.fetch_anchor``) and returns
    a typed :class:`AipFetchResult` ready for kid-resolver consumption.

    Args:
        aip_id: the AIP identifier. Either ``aip:web:host/path`` or a
            pre-resolved ``https://...`` URL. See
            :func:`aip_web_to_https_url` for the exact accepted shapes.
        transport: the V-908 HTTPS transport instance. Production
            callers construct it once and reuse it; tests inject a
            transport with a fake ``urlopen``.
        dns_resolver: optional :class:`TxtResolver` for the DNS-anchor
            cross-check. When ``None`` (default), no DNS lookup is
            attempted regardless of ``anchor_required``; supplying
            ``anchor_required=True`` with ``dns_resolver=None`` raises
            :class:`AipDnsAnchorMismatchError` immediately (the contract
            is unambiguous: if you require an anchor, you must wire a
            resolver).
        anchor_required: when ``True``, a missing / malformed / mismatching
            DNS anchor raises :class:`AipDnsAnchorMismatchError`. When
            ``False`` (default), the DNS lookup is best-effort and a
            soft-failure surfaces as ``dns_anchor=None`` and
            ``anchor_matched=False`` on the result. Production
            hard-trust paths SHOULD set this.
        dns_timeout_s: DNS-resolver timeout, forwarded to
            :func:`dns_anchor.fetch_anchor`. Default 3.0s.

    Returns:
        :class:`AipFetchResult` with the parsed body and JCS byte-anchor.

    Raises:
        AipUrlSchemeError: ``aip_id`` is not a parseable AIP identifier.
        AipDnsAnchorMismatchError: ``anchor_required=True`` and the
            anchor cross-check failed (absent, malformed, or fingerprint
            mismatch).
        HTTPSBackendError (or subclass): any V-908 §3.3 transport-level
            failure. Tag-4 does NOT wrap these; the caller retains
            typed access (e.g. ``HTTPSStatusError.status == 404``).
    """
    url, host = aip_web_to_https_url(aip_id)

    # ------------------------------------------------------------------
    # 1. HTTPS fetch (V-908 §3.3 delegated).
    # ------------------------------------------------------------------
    response: HTTPSDocumentResponse = transport.get(url)
    if not isinstance(response.body, dict):
        # The Tag-8 transport already parses JSON and raises
        # HTTPSPayloadError on a non-parseable body; we additionally
        # guard against a parseable-but-non-object body (e.g. a JSON
        # array at the root). AIP documents are objects per the
        # JSON-Schema; a non-object root is a structural protocol-layer
        # failure.
        raise HTTPSBackendError(
            f"AIP-document body must be a JSON object, got "
            f"{type(response.body).__name__}",
            url=url,
        )
    aip_doc: dict = response.body
    body_bytes: bytes = response.body_bytes

    # ------------------------------------------------------------------
    # 2. JCS byte-anchor (single source of truth for the fingerprint).
    # ------------------------------------------------------------------
    jcs_hex = _jcs_anchor_hex(aip_doc)

    # ------------------------------------------------------------------
    # 3. DNS-anchor cross-check (V-908 §3.4 pattern, AIP-doc variant).
    # ------------------------------------------------------------------
    dns_anchor_obj: Optional[DnsAnchor] = None
    anchor_matched = False

    if anchor_required and dns_resolver is None:
        # Defensive: the caller cannot require an anchor without a
        # resolver. Raise eagerly rather than silently down-grading.
        raise AipDnsAnchorMismatchError(
            "anchor_required=True but dns_resolver is None",
            aip_id=aip_id,
            host=host,
            expected=jcs_hex,
            observed=None,
        )

    if dns_resolver is not None:
        anchor_host = f"{DNS_ANCHOR_PREFIX}{host}"
        try:
            dns_anchor_obj = fetch_anchor(
                dns_resolver, anchor_host, timeout_s=dns_timeout_s
            )
        except DnsAnchorError as exc:
            if anchor_required:
                raise AipDnsAnchorMismatchError(
                    f"DNS anchor lookup failed at {anchor_host!r}: {exc}",
                    aip_id=aip_id,
                    host=host,
                    expected=jcs_hex,
                    observed=None,
                ) from exc
            # Soft mode: leave dns_anchor_obj as None and continue.
        else:
            # Compare fingerprint to the computed JCS-anchor hex.
            if dns_anchor_obj.fingerprint == jcs_hex:
                anchor_matched = True
            else:
                if anchor_required:
                    raise AipDnsAnchorMismatchError(
                        f"DNS anchor fingerprint mismatch at {anchor_host!r}",
                        aip_id=aip_id,
                        host=host,
                        expected=jcs_hex,
                        observed=dns_anchor_obj.fingerprint,
                    )
                # Soft mode: keep the parsed anchor on the result but
                # surface anchor_matched=False so the caller can decide.
                anchor_matched = False

    return AipFetchResult(
        aip_id=aip_id,
        url=url,
        host=host,
        aip_doc=aip_doc,
        body_bytes=body_bytes,
        jcs_sha256_hex=jcs_hex,
        dns_anchor=dns_anchor_obj,
        anchor_matched=anchor_matched,
    )


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "AipDocumentTransportError",
    "AipDnsAnchorMismatchError",
    "AipFetchResult",
    "AipUrlSchemeError",
    "DNS_ANCHOR_PREFIX",
    "WELL_KNOWN_AIP_PREFIX",
    "aip_web_to_https_url",
    "fetch_aip_document",
]
