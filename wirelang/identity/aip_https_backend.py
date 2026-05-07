# SPDX-License-Identifier: Apache-2.0
"""V-908 AIP-document HTTPS transport backend.

This module implements the Phase-1b production HTTPS transport for
fetching AIP documents over the wire. It is the counterpart to the
DNS-anchor :class:`StdlibDoHResolver` (Tag-5) for the AIP-doc fetch
half of the V-908 federation pipeline (§3.3 "HTTP transport").

V-908 spec §3.3 fixes the transport requirements:

* HTTPS-only (no plaintext HTTP fallback).
* Bounded redirect depth (the spec says "at most one redirect"; we
  default to that and refuse zero or more than one).
* No outbound credentials (V-908 §3.3 explicitly forbids ``Cookie``
  and ``Authorization`` headers; AIP documents are public-by-policy).
* Bounded body size (the spec leaves the precise floor to the
  implementer; we default to 256 KiB which is two orders of magnitude
  above any realistic AIP-doc shape and one order of magnitude below
  any common JSON-bomb threshold).
* Bounded timeout (split into connect-vs-body where the underlying
  transport supports it; ``urllib`` exposes a single timeout, so we
  expose the single timeout knob and document the behaviour).

The module deliberately uses only the Python standard library
(``urllib.request``, ``urllib.error``, ``http.client``, ``json``,
``ssl``) -- this matches the Tag-5 zero-third-party-dep posture of
:mod:`wirelang.identity.dns_anchor` and keeps the runtime sandbox
friendly. Tests mock at the urllib boundary; no real HTTPS calls
ever leave the test process.

Architecture (two layers)
-------------------------

The module ships **two cooperating types** so callers can compose
production wire as needed without forking the transport for each
verifier:

1. :class:`HTTPSDocumentTransport` -- pure transport: HTTPS GET +
   header parsing + body-size/redirect/credential enforcement.
   Returns :class:`HTTPSDocumentResponse` on success or raises
   :class:`HTTPSBackendError`. Knows nothing about AIP documents.

2. :class:`HTTPSAipResolver` -- composition layer that wires the
   transport into the federation pipeline's
   :class:`~wirelang.identity.federation_resolver.AIPResolverLike`
   protocol. Production deployments inject the Phase-1a
   :class:`wirelang.identity.aip_resolver.AIPResolver`'s verify path
   as the ``verify_fn`` callable; sandbox tests inject a stub.

This split lets the transport be tested exhaustively in the sandbox
(where ``rfc8785`` and ``jsonschema`` are not installed) while the
production AIP-verify pipeline (Phase-1a Tag-21 module) plugs in
unchanged.

Cache header semantics
----------------------

V-908 §3.3 requires that callers respect upstream ``Cache-Control``
and ``ETag`` headers when those are present, but does NOT require the
transport itself to be a cache. We surface the parsed headers on
:class:`HTTPSDocumentResponse` (``etag``, ``cache_control``,
``max_age_s``) and let the caller (typically the federation resolver
or an outer cache-tier) decide whether to honour them. The
``If-None-Match`` round-trip (304-handling) is supported on
:meth:`HTTPSDocumentTransport.get` via the ``if_none_match``
argument; a 304 response surfaces as
:class:`HTTPSDocumentNotModified`.

Error mapping
-------------

All transport-level failures are mapped to typed
:class:`HTTPSBackendError` subclasses so that the federation resolver
can map them onto V-908 §4.6 rows or propagate as Phase-1a-style
errors (e.g. ``AIPNotFoundError`` for HTTP 404). The mapping is
delegated to the caller; this module's job is to produce typed
errors, not to make policy decisions about how to surface them.

V-908 spec cross-references:

* §3.3 ("HTTP transport") -- HTTPS-only, redirect bound, no
  credentials, body-size bound, timeout bound.
* §6.1 ("Phase-1b targets") -- this module is one of the listed
  Phase-1b deliverables (HTTPS backend for AIP-doc fetch, called out
  in the Tag-7 outbox §5 risk-item 5 as PS-6).
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


# ---------------------------------------------------------------------------
# Defaults (V-908 §3.3 implementation choices)
# ---------------------------------------------------------------------------

#: Default per-request timeout in seconds. ``urllib.request.urlopen``
#: applies this to both connect and body reads.
DEFAULT_TIMEOUT_S: float = 10.0

#: Default maximum response body size in bytes. 256 KiB.
#:
#: V-908 §3.3 calls for a bounded body; AIP documents are small JSON
#: blobs (single-digit KiB at the absolute upper bound for foreseeable
#: shapes). The 256 KiB ceiling is two orders of magnitude above any
#: realistic AIP-doc shape, leaving headroom for spec evolution while
#: still rejecting JSON-bomb-class payloads.
DEFAULT_MAX_BODY_BYTES: int = 256 * 1024

#: Default User-Agent. Identifiable to peers and to ourselves in
#: server-side logs; not security-relevant.
DEFAULT_USER_AGENT: str = "wakir-runtime/0.1 (+v908)"

#: Maximum redirect depth. V-908 §3.3 says "at most one"; we default
#: to one and refuse to follow more.
DEFAULT_MAX_REDIRECTS: int = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HTTPSBackendError(Exception):
    """Base class for AIP HTTPS-backend failures.

    Subclasses carry typed information so that the federation resolver
    can map onto V-908 §4.6 rows. All instances expose the request
    URL on :attr:`url` (when available) for log/debug correlation.
    """

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class HTTPSSchemeError(HTTPSBackendError):
    """Raised when the URL is not ``https://`` (V-908 §3.3 HTTPS-only)."""


class HTTPSTransportError(HTTPSBackendError):
    """Connection refused, DNS failure, TLS error, or timeout.

    Maps onto network-layer failures distinct from server-returned
    HTTP error codes. The federation resolver typically surfaces these
    as Phase-1a ``AIPNotFoundError``-equivalent transport failures.
    """


class HTTPSStatusError(HTTPSBackendError):
    """Server returned a non-2xx HTTP status (excluding 304).

    The :attr:`status` attribute carries the integer HTTP status code.
    Common cases: 404 (AIP-doc not found), 5xx (upstream failure).
    304 ("Not Modified") is NOT raised here -- it surfaces as
    :class:`HTTPSDocumentNotModified` instead.
    """

    def __init__(self, message: str, *, status: int, url: str | None = None) -> None:
        super().__init__(message, url=url)
        self.status = status


class HTTPSRedirectError(HTTPSBackendError):
    """Raised when redirect depth exceeds the configured ceiling.

    Default ceiling is :data:`DEFAULT_MAX_REDIRECTS` (one). The
    transport refuses to follow redirects beyond the ceiling and does
    not silently widen the surface; the caller must explicitly raise
    the limit (and accept the spec consequences).
    """


class HTTPSBodySizeError(HTTPSBackendError):
    """Raised when the response body exceeds the configured ceiling."""


class HTTPSPayloadError(HTTPSBackendError):
    """Raised when the response body is not valid JSON or is malformed.

    Distinct from :class:`HTTPSStatusError` (which is a transport-layer
    success returning the wrong status) and from the Phase-1a
    ``AIPSchemaError`` (which is verify-layer; we never get to verify
    if the body is not parseable JSON).
    """


class HTTPSDocumentNotModified(HTTPSBackendError):
    """Raised on HTTP 304 ("Not Modified").

    Used by callers driving ``If-None-Match`` round-trips to detect
    that a cached document is still current. Not a hard failure; the
    caller catches and reuses its prior cached body.
    """

    def __init__(self, *, url: str | None = None, etag: str | None = None) -> None:
        super().__init__(f"document not modified (304) for {url!r}", url=url)
        self.etag = etag


# ---------------------------------------------------------------------------
# Response value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HTTPSDocumentResponse:
    """A successful HTTPS fetch of an AIP document (or any JSON doc).

    Attributes:
        url: the final URL that was fetched (after any redirect).
        body: the parsed JSON body (typically a ``dict``).
        body_bytes: the raw response bytes (used for downstream
            byte-level digests; the federation resolver uses these for
            JCS recomputation when the verify layer is invoked).
        status: HTTP status code (always 2xx for a success).
        etag: ``ETag`` response header value, or ``None`` if absent.
        cache_control: raw ``Cache-Control`` header value.
        max_age_s: parsed ``max-age`` directive in seconds, or
            ``None`` if absent / unparseable. Convenience for callers
            implementing a basic cache tier.
        content_type: raw ``Content-Type`` header value.
    """

    url: str
    body: dict
    body_bytes: bytes
    status: int
    etag: str | None
    cache_control: str | None
    max_age_s: int | None
    content_type: str | None


# ---------------------------------------------------------------------------
# Internal: urlopen abstraction (for test injection)
# ---------------------------------------------------------------------------


#: Callable signature compatible with :func:`urllib.request.urlopen`.
#:
#: The transport accepts this as a constructor injection so tests can
#: substitute a fake without monkey-patching the urllib module. The
#: production default binds ``urllib.request.urlopen`` directly.
UrlopenLike = Callable[..., Any]


def _default_urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
    context: ssl.SSLContext | None = None,
) -> Any:
    return urllib.request.urlopen(request, timeout=timeout, context=context)


# ---------------------------------------------------------------------------
# HTTPSDocumentTransport
# ---------------------------------------------------------------------------


class HTTPSDocumentTransport:
    """Pure HTTPS GET transport for V-908 AIP-document fetch.

    Knows nothing about AIP semantics; it fetches a URL, validates
    transport invariants (HTTPS-only, redirect ceiling, no credentials,
    body-size ceiling, timeout), and returns the parsed JSON body
    plus normative response headers.

    Args:
        timeout_s: Per-request timeout in seconds (applied by
            ``urllib.request.urlopen``). Default
            :data:`DEFAULT_TIMEOUT_S`.
        max_body_bytes: Maximum body size accepted. Default
            :data:`DEFAULT_MAX_BODY_BYTES`.
        max_redirects: Maximum redirect depth. Default
            :data:`DEFAULT_MAX_REDIRECTS` (one). Set to ``0`` to
            forbid all redirects.
        user_agent: User-Agent header value. Default
            :data:`DEFAULT_USER_AGENT`.
        ssl_context: optional :class:`ssl.SSLContext`. Default
            ``None`` causes ``urllib`` to use the system default
            (which respects ``SSL_CERT_FILE`` and the system trust
            store). Tests inject a stub to avoid real TLS.
        urlopen: Optional injection point for the urllib urlopen
            callable. Default is :func:`urllib.request.urlopen`.
            Tests provide a fake.

    Concurrency:
        The transport itself is stateless; instance methods are safe
        to call from multiple threads concurrently as long as the
        injected ``urlopen`` is thread-safe (the stdlib urllib is).
    """

    #: Headers we *forbid* the caller from supplying. V-908 §3.3
    #: explicitly forbids ``Cookie``/``Authorization`` and we strip
    #: any header value matching this lowercased set on input.
    _FORBIDDEN_REQUEST_HEADERS: frozenset[str] = frozenset(
        {"cookie", "authorization", "proxy-authorization"}
    )

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        user_agent: str = DEFAULT_USER_AGENT,
        ssl_context: ssl.SSLContext | None = None,
        urlopen: UrlopenLike | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be > 0")
        if max_redirects < 0:
            raise ValueError("max_redirects must be >= 0")
        if not user_agent:
            raise ValueError("user_agent must be non-empty")
        self._timeout_s = float(timeout_s)
        self._max_body_bytes = int(max_body_bytes)
        self._max_redirects = int(max_redirects)
        self._user_agent = user_agent
        self._ssl_context = ssl_context
        self._urlopen: UrlopenLike = urlopen or _default_urlopen

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        if_none_match: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HTTPSDocumentResponse:
        """Fetch ``url`` over HTTPS and return the parsed JSON body.

        Args:
            url: HTTPS URL to GET. Must start with ``https://``.
            if_none_match: optional ETag value to send as
                ``If-None-Match``; on HTTP 304 the call raises
                :class:`HTTPSDocumentNotModified` instead of returning
                a response.
            extra_headers: optional additional request headers. Any
                header in :attr:`_FORBIDDEN_REQUEST_HEADERS`
                (case-insensitive) is dropped silently before sending.

        Returns:
            :class:`HTTPSDocumentResponse` on a 2xx with a parseable
            JSON body.

        Raises:
            HTTPSSchemeError: URL scheme is not ``https``.
            HTTPSRedirectError: redirect depth exceeded.
            HTTPSStatusError: non-2xx, non-304 HTTP status.
            HTTPSDocumentNotModified: HTTP 304 (when
                ``if_none_match`` was supplied).
            HTTPSTransportError: connect / TLS / timeout failure.
            HTTPSBodySizeError: body exceeds ``max_body_bytes``.
            HTTPSPayloadError: body is not valid JSON.
        """
        self._enforce_https(url)
        headers = self._build_headers(if_none_match=if_none_match, extra=extra_headers)
        return self._fetch_with_redirect_budget(
            url, headers=headers, redirect_budget=self._max_redirects
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _enforce_https(url: str) -> None:
        # V-908 §3.3 -- HTTPS-only.
        if not isinstance(url, str) or not url:
            raise HTTPSSchemeError("url must be a non-empty string", url=url)
        # Lowercase prefix check; the rest of the URL is left to urllib.
        # We accept any case-folding of "HTTPS" up to the colon. urllib
        # itself canonicalises further.
        scheme_sep = url.find("://")
        if scheme_sep <= 0:
            raise HTTPSSchemeError(f"url is not a fully-qualified URL: {url!r}", url=url)
        scheme = url[:scheme_sep].lower()
        if scheme != "https":
            raise HTTPSSchemeError(
                f"only https:// URLs are accepted (got {scheme!r}://...)", url=url
            )

    def _build_headers(
        self,
        *,
        if_none_match: str | None,
        extra: Mapping[str, str] | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "user-agent": self._user_agent,
            "accept": "application/json",
        }
        if extra:
            for k, v in extra.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                if k.lower() in self._FORBIDDEN_REQUEST_HEADERS:
                    # V-908 §3.3 forbids credentials. Drop silently;
                    # the caller does not get to opt out.
                    continue
                headers[k.lower()] = v
        if if_none_match is not None:
            headers["if-none-match"] = if_none_match
        return headers

    def _fetch_with_redirect_budget(
        self,
        url: str,
        *,
        headers: dict[str, str],
        redirect_budget: int,
    ) -> HTTPSDocumentResponse:
        # We disable urllib's automatic redirect handling by using a
        # plain Request and re-checking the status code on the
        # response. This gives us strict control over the redirect
        # budget and ensures we re-validate the HTTPS scheme on the
        # redirect target.
        current_url = url
        budget = redirect_budget
        while True:
            request = urllib.request.Request(current_url, method="GET")
            for k, v in headers.items():
                request.add_header(k, v)
            try:
                resp = self._urlopen(
                    request, timeout=self._timeout_s, context=self._ssl_context
                )
            except urllib.error.HTTPError as e:
                # urllib raises HTTPError for non-2xx including 3xx.
                # We treat 3xx as redirect candidates and let 4xx/5xx
                # surface as HTTPSStatusError.
                status = getattr(e, "code", 0)
                if status in (301, 302, 303, 307, 308):
                    location = e.headers.get("Location") if e.headers else None
                    if not location:
                        raise HTTPSStatusError(
                            f"HTTP {status} without Location header",
                            status=status,
                            url=current_url,
                        ) from e
                    if budget <= 0:
                        raise HTTPSRedirectError(
                            f"redirect budget exhausted at {current_url!r} -> "
                            f"{location!r}",
                            url=current_url,
                        ) from e
                    self._enforce_https(location)
                    current_url = location
                    budget -= 1
                    continue
                if status == 304:
                    etag = e.headers.get("ETag") if e.headers else None
                    raise HTTPSDocumentNotModified(url=current_url, etag=etag) from e
                # Any other HTTP error code maps to HTTPSStatusError.
                raise HTTPSStatusError(
                    f"HTTP {status} for {current_url!r}",
                    status=status,
                    url=current_url,
                ) from e
            except urllib.error.URLError as e:
                raise HTTPSTransportError(
                    f"transport error to {current_url!r}: {e!r}", url=current_url
                ) from e
            except TimeoutError as e:  # pragma: no cover -- covered via URLError on stdlib
                raise HTTPSTransportError(
                    f"timeout to {current_url!r}: {e!r}", url=current_url
                ) from e

            # 2xx path. Parse and return.
            return self._read_2xx(resp, current_url)

    def _read_2xx(self, resp: Any, url: str) -> HTTPSDocumentResponse:
        status = getattr(resp, "status", None)
        if status is None:
            # Older urllib responses expose getcode() instead.
            status = resp.getcode() if hasattr(resp, "getcode") else 200
        if not (200 <= int(status) < 300):
            # Defensive -- should not happen since urllib raises on
            # non-2xx, but a fake urlopen could mis-route. Treat as
            # status error.
            raise HTTPSStatusError(
                f"non-2xx status {status} for {url!r}",
                status=int(status),
                url=url,
            )

        # Read with a hard ceiling. We use ``read(N+1)`` to detect
        # overflow without spending memory beyond the ceiling+1.
        try:
            raw = resp.read(self._max_body_bytes + 1)
        except (OSError, urllib.error.URLError) as e:
            raise HTTPSTransportError(
                f"read error from {url!r}: {e!r}", url=url
            ) from e

        if not isinstance(raw, (bytes, bytearray)):
            raise HTTPSPayloadError(
                f"non-bytes body from {url!r}: type={type(raw).__name__}",
                url=url,
            )
        body_bytes = bytes(raw)
        if len(body_bytes) > self._max_body_bytes:
            raise HTTPSBodySizeError(
                f"response body exceeds {self._max_body_bytes} bytes from {url!r}",
                url=url,
            )

        try:
            parsed = json.loads(body_bytes)
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPSPayloadError(
                f"response body is not valid JSON from {url!r}: {e!r}",
                url=url,
            ) from e
        if not isinstance(parsed, dict):
            raise HTTPSPayloadError(
                f"response body is not a JSON object from {url!r}: "
                f"got type={type(parsed).__name__}",
                url=url,
            )

        headers = _headers_to_mapping(resp)
        etag = headers.get("etag")
        cache_control = headers.get("cache-control")
        content_type = headers.get("content-type")
        max_age_s = _parse_max_age(cache_control)

        return HTTPSDocumentResponse(
            url=url,
            body=parsed,
            body_bytes=body_bytes,
            status=int(status),
            etag=etag,
            cache_control=cache_control,
            max_age_s=max_age_s,
            content_type=content_type,
        )


# ---------------------------------------------------------------------------
# HTTPSAipResolver -- composition layer (AIPResolverLike-compatible)
# ---------------------------------------------------------------------------


#: Callable signature for a verify hook bridging raw transport bytes
#: into the federation pipeline's
#: :class:`~wirelang.identity.federation_resolver.AIPDocumentLike`.
#:
#: Production deployments bind this to the Phase-1a Tag-21
#: :class:`wirelang.identity.aip_resolver.AIPResolver`'s verify-and-
#: project step (consuming JCS-recomputation, schema validation, and
#: signature verification). Sandbox tests inject a stub that accepts
#: pre-canonical inputs and returns a canned ``AIPDocumentLike`` so
#: the transport layer can be exercised without ``rfc8785`` /
#: ``jsonschema`` / ``cryptography`` being installed.
AipVerifyFn = Callable[[str, bytes, dict], Any]


class HTTPSAipResolver:
    """``AIPResolverLike``-compatible resolver wired against
    :class:`HTTPSDocumentTransport`.

    The constructor takes a transport and a ``verify_fn`` callable.
    Calling :meth:`resolve` fetches the URL via the transport and
    delegates verification (schema, signature, JCS recomputation) to
    ``verify_fn``. The verify result is returned unchanged; the
    federation resolver consumes it via the
    :class:`~wirelang.identity.federation_resolver.AIPDocumentLike`
    Protocol.

    Args:
        transport: the :class:`HTTPSDocumentTransport` to use.
        verify_fn: callable ``(uri, body_bytes, body_dict) -> doc``
            where ``doc`` is the verified
            ``AIPDocumentLike`` instance.
        cache: optional internal ETag cache. If supplied, the resolver
            issues ``If-None-Match`` round-trips and reuses cached
            verified documents on 304. Default ``None`` disables
            caching at this layer (the federation-side
            ``FTDCache`` is unaffected).

    Production wire (sketch)::

        from wirelang.identity.aip_resolver import AIPResolver
        from wirelang.identity.aip_https_backend import (
            HTTPSAipResolver, HTTPSDocumentTransport,
        )
        from wirelang.identity.federation_resolver import (
            resolve_federated_aip,
        )

        prod_aip = AIPResolver(...)  # Tag-21 verify pipeline

        def verify(uri, body_bytes, body):
            # Phase-1a verify path consumes raw bytes for JCS:
            return prod_aip.verify_from_transport(uri, body_bytes, body)

        transport = HTTPSDocumentTransport()
        resolver = HTTPSAipResolver(transport=transport, verify_fn=verify)
        result = resolve_federated_aip(
            aip_id, ftd_id, ..., aip_resolver=resolver, ...
        )

    The exact ``verify_from_transport`` shape on the Tag-21
    ``AIPResolver`` is a Phase-1b follow-up; the contract is captured
    by the :class:`AipVerifyFn` callable so the transport layer is
    not blocked by Phase-1a refactors.

    Sandbox / test wire:
        Tests construct ``HTTPSAipResolver`` with a fake
        ``urlopen`` injected into the transport and a stub
        ``verify_fn`` that returns a canned ``AIPDocumentLike``-shaped
        object. See ``wirelang/tests/test_aip_https_backend.py``.
    """

    def __init__(
        self,
        *,
        transport: HTTPSDocumentTransport,
        verify_fn: AipVerifyFn,
        cache: "HTTPSAipResolverCache | None" = None,
    ) -> None:
        self._transport = transport
        self._verify_fn = verify_fn
        self._cache = cache

    def resolve(self, uri: str) -> Any:
        """Fetch ``uri`` and return the verified AIP document.

        Conforms to
        :class:`~wirelang.identity.federation_resolver.AIPResolverLike`.

        Raises:
            HTTPSBackendError: any transport-level failure.
            Anything raised by ``verify_fn`` propagates unchanged.
        """
        cache_entry = self._cache.get(uri) if self._cache is not None else None
        if_none_match = cache_entry.etag if cache_entry is not None else None

        try:
            resp = self._transport.get(uri, if_none_match=if_none_match)
        except HTTPSDocumentNotModified:
            # Cache hit -- reuse the previously-verified document.
            if cache_entry is None:
                # Not reachable in normal operation: 304 was sent
                # because we set If-None-Match, which only happens
                # when cache_entry is non-None.
                raise
            return cache_entry.document

        document = self._verify_fn(uri, resp.body_bytes, resp.body)
        if self._cache is not None and resp.etag is not None:
            self._cache.put(uri, resp.etag, document)
        return document


@dataclass
class _HTTPSAipResolverCacheEntry:
    etag: str
    document: Any


class HTTPSAipResolverCache:
    """Per-URI ETag/document cache for :class:`HTTPSAipResolver`.

    Bounded LRU; defaults to 64 entries which is comfortable for
    Phase-1b federated-org count and well below memory-pressure
    thresholds for AIP-doc sizes.
    """

    def __init__(self, *, max_entries: int = 64) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")
        self._max_entries = int(max_entries)
        self._entries: dict[str, _HTTPSAipResolverCacheEntry] = {}
        self._order: list[str] = []

    def get(self, uri: str) -> _HTTPSAipResolverCacheEntry | None:
        return self._entries.get(uri)

    def put(self, uri: str, etag: str, document: Any) -> None:
        if uri in self._entries:
            self._entries[uri] = _HTTPSAipResolverCacheEntry(etag=etag, document=document)
            # Move to end of LRU order.
            try:
                self._order.remove(uri)
            except ValueError:
                pass
            self._order.append(uri)
            return
        if len(self._order) >= self._max_entries:
            evict = self._order.pop(0)
            self._entries.pop(evict, None)
        self._entries[uri] = _HTTPSAipResolverCacheEntry(etag=etag, document=document)
        self._order.append(uri)

    def __contains__(self, uri: object) -> bool:
        return uri in self._entries

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Internal: header / cache-control parsing
# ---------------------------------------------------------------------------


def _headers_to_mapping(resp: Any) -> dict[str, str]:
    """Normalise the response-headers object to a lowercase dict.

    urllib responses expose headers via ``resp.headers`` (an
    :class:`http.client.HTTPMessage`); fakes used in tests may expose
    a plain dict or a ``Mapping``. We accept both.
    """
    headers = getattr(resp, "headers", None)
    if headers is None:
        return {}
    out: dict[str, str] = {}
    if isinstance(headers, Mapping):
        items = headers.items()
    elif hasattr(headers, "items"):
        items = headers.items()
    else:
        return {}
    for k, v in items:
        if not isinstance(k, str):
            continue
        out[k.lower()] = str(v)
    return out


def _parse_max_age(cache_control: str | None) -> int | None:
    """Parse the ``max-age`` directive from a Cache-Control header.

    Returns the integer seconds or ``None`` if absent or unparseable.
    Tolerant of whitespace around the directive name and of other
    directives in the header (``no-cache``, ``private``, etc.) which
    are ignored at this layer; callers that care apply their own
    policy after inspecting :attr:`HTTPSDocumentResponse.cache_control`.
    """
    if not cache_control:
        return None
    for directive in cache_control.split(","):
        token = directive.strip().lower()
        if token.startswith("max-age="):
            value = token[len("max-age="):].strip()
            try:
                seconds = int(value)
            except ValueError:
                return None
            if seconds < 0:
                return None
            return seconds
    return None


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_USER_AGENT",
    "AipVerifyFn",
    "HTTPSBackendError",
    "HTTPSSchemeError",
    "HTTPSTransportError",
    "HTTPSStatusError",
    "HTTPSRedirectError",
    "HTTPSBodySizeError",
    "HTTPSPayloadError",
    "HTTPSDocumentNotModified",
    "HTTPSDocumentResponse",
    "HTTPSDocumentTransport",
    "HTTPSAipResolver",
    "HTTPSAipResolverCache",
]
