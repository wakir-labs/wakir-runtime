# SPDX-License-Identifier: BUSL-1.1
"""SPIRE-Federation-Bundle live HTTPS peer-trust-bundle fetcher (Phase-2c).

Phase-2 Sprint-7 Pfad-B Tag-6 lands the **Phase-2c live HTTPS
counterpart** to the Sprint-7 Pfad-B Tag-5 hermetic-mode
:class:`SpireFedBundlePeerTrustBundleFetcher`. The live fetcher
implements the same :class:`PeerTrustBundleFetcher` Protocol so a
Wakir-side bridge can be wired to either implementation
interchangeably; the choice between hermetic (in-process fixture
JWKS) and live (HTTPS GET against a real SPIRE-Server bundle
endpoint listener) is an *operator concern*, not a bridge concern.

Composition contract
====================

The live fetcher composes three on-disk surfaces:

1. The Python stdlib ``urllib.request`` / ``ssl`` surface — boring-
   tech default, no new third-party dependency. The fetcher does
   NOT pull in ``httpx`` or ``requests``; both would add a wheel
   surface without buying anything for a fail-closed, single-shot
   HTTPS GET. ``urllib`` is part of every supported Python.
2. The bridge's :class:`PeerTrustBundleFetcher` Protocol — the
   adapter implements the async ``fetch(url, trust_domain)`` shape
   the bridge expects. The HTTPS GET runs inside
   :func:`asyncio.to_thread` so a bridge running in an asyncio task
   does not block its event loop on a slow peer.
3. The bridge's :class:`FetchedTrustBundle` value object — the
   adapter wraps the fetched JWKS bytes plus a deterministic
   ``fetched_at`` timestamp into a :class:`FetchedTrustBundle` the
   bridge can consume.

The adapter is **fail-closed at every step**:

- Trust-domain not in the pin set → :class:`UnpinnedTrustDomainError`
  (re-used from the Tag-5 hermetic module).
- Bridge-supplied URL ≠ pinned URL for the trust-domain →
  :class:`UrlTrustDomainMismatchError` (also re-used).
- Network / DNS / TCP failure → :class:`LiveBundleFetchError`
  with the underlying :class:`OSError` chained as ``cause``.
- HTTP non-2xx response → :class:`LiveBundleHttpStatusError`
  carrying the status code and the URL.
- Read timeout → :class:`LiveBundleTimeoutError` carrying the
  effective timeout and the URL.
- TLS handshake failure → :class:`LiveBundleTlsError` carrying the
  underlying :class:`ssl.SSLError` as ``cause``.
- Empty / oversized response body → :class:`LiveBundleFetchError`
  (size cap is constant ``MAX_BUNDLE_BYTES`` = 1 MiB; defence
  against an adversarial peer returning unbounded garbage).

The bridge catches any of the above (they all subclass
:class:`SpireFedBundleLiveFetcherError`) and re-wraps them as
:class:`PeerTrustBundleFetchError` with the original as ``cause`` —
the bridge's existing fail-closed contract is preserved.

URL contract — root-path resolution
====================================

The SPIRE-Server federation bundle endpoint serves the bundle at
the listener's **root path** (``"/"``); the upstream Go
implementation enforces this with an explicit ``if req.URL.Path !=
"/" { http.NotFound }`` guard
(`pkg/server/endpoints/bundle/server.go`). Therefore a URL of the
shape ``https://spire-server-<peer>:8443`` (with NO path suffix)
is the canonical pinned URL for the live fetcher. URLs with a
trailing slash (``https://...:8443/``) are equivalent; URLs with
any other suffix (``/bundle``, ``/spiffe/bundle``) will yield a
``404 Not Found`` from the SPIRE-Server and surface as
:class:`LiveBundleHttpStatusError` on the adapter side.

This decision closes the **Tag-5 Open-Item** (``2026-05-14
sprint-7-pfad-b-tag-5-federation-live-component.md`` cross-review
Zone-A D-2 Kai): the Tag-5 hermetic adapter's pinned-URL shape
included a ``/bundle`` suffix because the hermetic exporter is
opaque to URL — only the trust-domain literal feeds the JWKS
fixture. For the live fetcher the URL is **load-bearing** and
MUST be root-path. The Tag-5 hermetic adapter's URL-suffix
convention is therefore a *hermetic-mode convenience* and does NOT
constrain the live-mode pin set.

Phase-2c TLS posture
====================

The live fetcher accepts two TLS modes via the constructor:

1. ``verify_ca_bundle_path`` (production posture): path to a PEM
   file containing the trust-bundle CA certificates the SPIRE-
   Server uses for its bundle endpoint listener. The TLS handshake
   succeeds only if the server certificate chains to one of these
   CAs. This is the boring-default for any production federation.
2. ``insecure_tls`` (Phase-2c-pilot only): boolean. When ``True``,
   the fetcher disables certificate validation entirely. This is
   the **pilot-stand** posture documented in Mira's Sprint-7 Pfad-B
   Tag-6 inbox: the two pilot VMs (wakir-pilot 192.168.178.116 and
   wakir-orbit 192.168.178.191) currently run with self-signed
   SPIRE-Server certs and no shared CA-bootstrap path yet. The
   ``insecure_tls=True`` mode is gated by an explicit constructor
   argument so that no production caller can fall into it by
   accident (the default is ``False``, and the constructor raises
   on mode ambiguity — see :meth:`__post_init__`).

The two modes are **mutually exclusive**. Constructing the adapter
with both ``verify_ca_bundle_path`` AND ``insecure_tls=True``
raises :class:`ValueError` at construction time. Constructing with
neither also raises ``ValueError``; the operator MUST make the
posture choice explicit.

ADR-0051 Sandbox-Boundary
=========================

This module is **the** live-counterpart module. The
:mod:`wirelang.federation.spire_fed_bundle_peer_fetcher` Tag-5
hermetic module remains hermetic-only; *this* module is the
explicit boundary-crossing surface. Callers that opt into live
federation MUST import this module explicitly — the import-graph
signal is the architectural marker for the Sandbox-Host trennung
(``feedback_sandbox_host_trennung.md``).

The module is hermetic-testable: the test suite stands up a
stdlib :class:`http.server.ThreadingHTTPServer` on loopback (no
podman, no container, no SPIRE-Server), serves a canned JWKS body
on ``/``, and the live fetcher hits it. The boundary-crossing
artefact in production is the operator-hand TLS-CA-bootstrap, not
the test surface.

Cross-Review Zone-A (Kai)
=========================

The URL shape this fetcher consumes (``https://<peer-host>:8443``,
root path, no suffix) is the canonical SPIRE-Server federation
bundle endpoint URL form. Kai's
``infra/spire/federation/config/spire-server-{orbit,wakir}.conf``
``federation { bundle_endpoint { ... } }`` block configures the
listener at ``port = 8443`` on the SPIRE-Server's bind address; the
SPIRE-Server then serves the bundle at the listener's root path.
The two pilot VMs' mutual DNS (Mira-Hand 2026-05-15 04:53 CEST via
``/etc/hosts``) maps ``wakir-pilot`` and ``wakir-orbit`` to their
respective IPs so the URL is hostname-keyed, NOT IP-keyed.

Cross-Review Zone-Q (Amara, optional)
=====================================

The fail-closed-gate test inventory in
``test_spire_fed_bundle_live_https_fetcher.py`` follows the same
mutation-coverage method the federation suite uses elsewhere: each
error class has at least one positive test (a wire shape that
triggers it) and one negative test (a wire shape that bypasses it
but still surfaces a structurally distinct error class). The
Mutation-Coverage matrix is documented in the test docstring.

Version: ``wakir.federation.spire-fed-bundle-live-https-fetcher/1``.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .spiffe_cross_trust_domain_bridge import FetchedTrustBundle
from .spire_fed_bundle_peer_fetcher import (
    UnpinnedTrustDomainError,
    UrlTrustDomainMismatchError,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema-URI fragment for this live fetcher. Carried in
#: :attr:`LiveHttpsSpireFedBundleFetcher.adapter_schema` so downstream
#: audit consumers can disambiguate the hermetic Tag-5 surface from the
#: live Tag-6 surface by schema-pin rather than by class identity.
SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA = (
    "wakir.federation.spire-fed-bundle-live-https-fetcher/1"
)


#: Maximum bundle response size in bytes. SPIRE-Server bundle JWKS
#: payloads in practice are tens of KB at most; the 1-MiB cap is a
#: defence-in-depth ceiling against an adversarial peer returning
#: unbounded garbage (e.g. ``yes 'a' | head -c $((1<<32))``). Operator
#: callers needing a higher cap MUST construct a fetcher with an
#: explicit ``max_bundle_bytes`` override (the dataclass field).
MAX_BUNDLE_BYTES = 1 << 20  # 1 MiB


#: Default per-request socket timeout, in seconds. SPIRE-Servers on
#: the local network respond well under one second; the 10s default
#: is a generous ceiling that still trips before any reasonable
#: human-supervised CLI session loses interest.
DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SpireFedBundleLiveFetcherError(Exception):
    """Base class for live-fetcher errors.

    The bridge catches any exception from the fetcher and re-raises
    as :class:`PeerTrustBundleFetchError`; this hierarchy gives the
    test surface a precise type to assert against for live-fetcher-
    side failure modes (vs. bridge-wrapped errors).

    All concrete live-fetcher errors subclass this base. The Tag-5
    pin-set errors (:class:`UnpinnedTrustDomainError` and
    :class:`UrlTrustDomainMismatchError`) are re-used from the
    hermetic Tag-5 module — they parent
    :class:`SpireFedBundlePeerFetcherError` there, NOT this base.
    Callers that want to absorb every adapter-side error uniformly
    catch ``(SpireFedBundleLiveFetcherError,
    SpireFedBundlePeerFetcherError)``.
    """


class LiveBundleFetchError(SpireFedBundleLiveFetcherError):
    """A network-, DNS-, or TCP-level failure prevented the bundle
    fetch from completing.

    Attributes:
        url: the URL the fetcher attempted to retrieve.
        cause: the underlying :class:`OSError` / :class:`URLError` /
            :class:`socket.gaierror`, when available.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.cause = cause


class LiveBundleHttpStatusError(SpireFedBundleLiveFetcherError):
    """The HTTPS GET completed but the SPIRE-Server returned a
    non-2xx status code.

    Most common cause for a 404 is a URL-shape mismatch (the
    operator pinned a URL with a path suffix like ``/bundle`` or
    ``/spiffe/bundle`` but the SPIRE-Server bundle endpoint serves
    only the root path). 503/504 indicate the SPIRE-Server is
    starting up or under load; the operator runbook covers retry.

    Attributes:
        url: the URL the fetcher attempted to retrieve.
        status: the HTTP status code the server returned.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str,
        status: int,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class LiveBundleTimeoutError(SpireFedBundleLiveFetcherError):
    """The HTTPS GET did not complete within the configured timeout.

    Operationally distinct from :class:`LiveBundleFetchError`: the
    socket was reachable, the TLS handshake either started or
    completed, but the server did not send a full response body in
    time.

    Attributes:
        url: the URL the fetcher attempted to retrieve.
        timeout_seconds: the timeout that elapsed.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str,
        timeout_seconds: float,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.timeout_seconds = timeout_seconds


class LiveBundleTlsError(SpireFedBundleLiveFetcherError):
    """The TLS handshake against the SPIRE-Server bundle endpoint
    failed.

    Causes: the server certificate does not chain to the configured
    CA bundle, the hostname does not match the certificate's
    SAN/CN, the certificate is expired, the protocol/cipher offer
    does not overlap.

    Attributes:
        url: the URL the fetcher attempted to retrieve.
        cause: the underlying :class:`ssl.SSLError`.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.cause = cause


# ---------------------------------------------------------------------------
# Live adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveHttpsSpireFedBundleFetcher:
    """Live HTTPS :class:`PeerTrustBundleFetcher` implementation that
    fetches the peer SPIRE-Server federation bundle by issuing a
    single HTTPS GET against the pinned URL.

    Construction:

    - ``trust_domain_to_url``: mapping from trust-domain literal to
      the URL the bridge will consume. Same shape as the Tag-5
      hermetic adapter so an operator can swap one for the other
      via a single constructor call. URLs MUST resolve to the
      SPIRE-Server federation bundle endpoint root path (no path
      suffix); see module docstring "URL contract — root-path
      resolution".
    - ``verify_ca_bundle_path``: path to a PEM CA-bundle file. When
      set, TLS verification is enforced against this CA bundle.
      Mutually exclusive with ``insecure_tls=True``.
    - ``insecure_tls``: boolean. When ``True``, TLS verification is
      disabled entirely. Phase-2c pilot only — see module docstring
      "Phase-2c TLS posture". Mutually exclusive with
      ``verify_ca_bundle_path``.
    - ``timeout_seconds``: per-request socket timeout. Default
      :data:`DEFAULT_FETCH_TIMEOUT_SECONDS`.
    - ``max_bundle_bytes``: response size cap. Default
      :data:`MAX_BUNDLE_BYTES`.
    - ``clock``: optional callable returning a timezone-aware UTC
      datetime; tests inject a fixed clock for determinism.

    The adapter is **frozen and stateless**. Multiple bridges can
    share one adapter instance; concurrent ``fetch`` calls are safe
    (urllib opens a new socket per call).

    Resolution contract (:meth:`fetch`):

    1. Reject if ``trust_domain`` is not in the pinned mapping
       (raise :class:`UnpinnedTrustDomainError` — re-used from
       Tag-5).
    2. Reject if ``url`` does not equal the pinned URL for the
       requested ``trust_domain`` (raise
       :class:`UrlTrustDomainMismatchError` — re-used from Tag-5).
    3. Issue an HTTPS GET against the pinned URL inside
       :func:`asyncio.to_thread` (so the bridge's asyncio event
       loop is not blocked). The TLS posture is determined by
       ``verify_ca_bundle_path`` vs ``insecure_tls``.
    4. Map any transport failure to a typed live-fetcher error
       (see module-level error classes).
    5. On a 2xx response, read the body up to ``max_bundle_bytes``
       and construct a :class:`FetchedTrustBundle` with the
       requested trust-domain, the pinned URL, the body bytes, and
       ``self._now()`` as ``fetched_at``.
    6. Return the bundle.

    Caller surface ::

        adapter = LiveHttpsSpireFedBundleFetcher(
            trust_domain_to_url={
                "orbit.test": "https://wakir-orbit:8443",
                "wakir.test": "https://wakir-pilot:8443",
            },
            insecure_tls=True,  # Phase-2c pilot posture
        )
        bridge = SpiffeCrossTrustDomainBridge(
            route_registry=...,
            attestation_registry=...,
            trust_bundle_fetcher=adapter,
            peer_svid_verifier=...,
            ...
        )

    The URLs above are the canonical Phase-2c pilot URLs given the
    mutual DNS resolution Mira-Hand-set on both VMs (2026-05-15
    ~04:53 CEST).
    """

    trust_domain_to_url: dict
    verify_ca_bundle_path: Optional[str] = None
    insecure_tls: bool = False
    timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS
    max_bundle_bytes: int = MAX_BUNDLE_BYTES
    clock: Optional[Any] = None
    # The SSLContext is cached in a private field initialised in
    # __post_init__ so concurrent fetch calls share one context
    # (SSLContext is documented thread-safe).
    _ssl_context: ssl.SSLContext = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Posture-choice validation: exactly one TLS mode must be
        # selected at construction time. The default of both fields
        # is "neither set", which is intentionally invalid — the
        # operator MUST make the choice explicit.
        if self.verify_ca_bundle_path is not None and self.insecure_tls:
            raise ValueError(
                "LiveHttpsSpireFedBundleFetcher: "
                "verify_ca_bundle_path and insecure_tls=True are "
                "mutually exclusive. Choose exactly one TLS posture."
            )
        if self.verify_ca_bundle_path is None and not self.insecure_tls:
            raise ValueError(
                "LiveHttpsSpireFedBundleFetcher: "
                "no TLS posture configured. Set either "
                "verify_ca_bundle_path=<path-to-ca-pem> "
                "(production-posture) or insecure_tls=True "
                "(Phase-2c pilot-posture)."
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                "LiveHttpsSpireFedBundleFetcher: timeout_seconds "
                f"must be > 0, got {self.timeout_seconds}"
            )
        if self.max_bundle_bytes <= 0:
            raise ValueError(
                "LiveHttpsSpireFedBundleFetcher: max_bundle_bytes "
                f"must be > 0, got {self.max_bundle_bytes}"
            )
        # Construct the SSLContext. Note: object.__setattr__ is the
        # supported pattern for assigning to a frozen dataclass in
        # __post_init__; see Python data-class docs.
        if self.insecure_tls:
            ctx = ssl._create_unverified_context()
        else:
            ctx = ssl.create_default_context(
                cafile=self.verify_ca_bundle_path
            )
        object.__setattr__(self, "_ssl_context", ctx)

    @property
    def adapter_schema(self) -> str:
        """Stable schema-URI for this adapter; useful for audit logs."""
        return SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "LiveHttpsSpireFedBundleFetcher.clock must "
                    "return a datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "LiveHttpsSpireFedBundleFetcher.clock must "
                    "return a timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    def _pinned_url(self, trust_domain: str) -> str:
        if trust_domain not in self.trust_domain_to_url:
            raise UnpinnedTrustDomainError(
                f"trust_domain {trust_domain!r} not in live-fetcher "
                f"pin set; pinned="
                f"{tuple(self.trust_domain_to_url)!r}",
                trust_domain=trust_domain,
                pinned=tuple(self.trust_domain_to_url),
            )
        return self.trust_domain_to_url[trust_domain]

    def _do_https_get(self, url: str) -> bytes:
        """Blocking HTTPS GET. Called inside :func:`asyncio.to_thread`.

        Returns the response body bytes (capped at
        ``max_bundle_bytes``). Raises a typed live-fetcher error
        on any failure path.
        """
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(
                req,
                timeout=self.timeout_seconds,
                context=self._ssl_context,
            ) as resp:
                status = resp.getcode()
                if status is None or not (200 <= status < 300):
                    raise LiveBundleHttpStatusError(
                        f"live HTTPS GET {url!r} returned non-2xx "
                        f"status {status!r}",
                        url=url,
                        status=int(status) if status is not None else 0,
                    )
                # Read at most max_bundle_bytes + 1 so we can detect
                # an oversize body without buffering it whole.
                body = resp.read(self.max_bundle_bytes + 1)
                if len(body) == 0:
                    raise LiveBundleFetchError(
                        f"live HTTPS GET {url!r} returned an empty "
                        "response body",
                        url=url,
                    )
                if len(body) > self.max_bundle_bytes:
                    raise LiveBundleFetchError(
                        f"live HTTPS GET {url!r} response body "
                        f"exceeded max_bundle_bytes="
                        f"{self.max_bundle_bytes}; refusing to "
                        "buffer further",
                        url=url,
                    )
                return body
        except urllib.error.HTTPError as exc:
            # urlopen raises HTTPError for 4xx/5xx in some Python
            # versions; surface that as our typed status error
            # rather than as a generic fetch error.
            raise LiveBundleHttpStatusError(
                f"live HTTPS GET {url!r} returned HTTP "
                f"{exc.code} {exc.reason!r}",
                url=url,
                status=int(exc.code),
            ) from exc
        except ssl.SSLError as exc:
            raise LiveBundleTlsError(
                f"live HTTPS GET {url!r} TLS handshake failed: "
                f"{exc!s}",
                url=url,
                cause=exc,
            ) from exc
        except socket.timeout as exc:
            raise LiveBundleTimeoutError(
                f"live HTTPS GET {url!r} timed out after "
                f"{self.timeout_seconds}s",
                url=url,
                timeout_seconds=self.timeout_seconds,
            ) from exc
        except urllib.error.URLError as exc:
            # URLError wraps the underlying reason; if the reason is
            # an SSL or timeout, surface the more-specific type.
            inner = getattr(exc, "reason", None)
            if isinstance(inner, ssl.SSLError):
                raise LiveBundleTlsError(
                    f"live HTTPS GET {url!r} TLS handshake failed: "
                    f"{inner!s}",
                    url=url,
                    cause=inner,
                ) from exc
            if isinstance(inner, socket.timeout):
                raise LiveBundleTimeoutError(
                    f"live HTTPS GET {url!r} timed out after "
                    f"{self.timeout_seconds}s",
                    url=url,
                    timeout_seconds=self.timeout_seconds,
                ) from exc
            raise LiveBundleFetchError(
                f"live HTTPS GET {url!r} failed: {exc!s}",
                url=url,
                cause=exc,
            ) from exc
        except OSError as exc:
            raise LiveBundleFetchError(
                f"live HTTPS GET {url!r} socket/IO failure: "
                f"{exc!s}",
                url=url,
                cause=exc,
            ) from exc

    async def fetch(
        self, *, url: str, trust_domain: str
    ) -> FetchedTrustBundle:
        """Fetch the peer trust-bundle for ``trust_domain`` by issuing
        an HTTPS GET against the pinned URL and return a bridge-
        consumable :class:`FetchedTrustBundle`.

        The HTTPS GET runs in a thread executor so the calling
        asyncio event loop is not blocked. Concurrent ``fetch``
        calls each spawn their own urllib socket; the underlying
        :class:`ssl.SSLContext` is shared (it is thread-safe).
        """
        pinned_url = self._pinned_url(trust_domain)
        if url != pinned_url:
            raise UrlTrustDomainMismatchError(
                f"bridge requested url {url!r} for trust_domain "
                f"{trust_domain!r} but live-fetcher is pinned to "
                f"{pinned_url!r} for that trust_domain",
                trust_domain=trust_domain,
                requested_url=url,
                pinned_url=pinned_url,
            )
        body = await asyncio.to_thread(self._do_https_get, pinned_url)
        return FetchedTrustBundle(
            trust_domain=trust_domain,
            url=pinned_url,
            bundle_bytes=body,
            fetched_at=self._now(),
        )


__all__ = [
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "LiveBundleFetchError",
    "LiveBundleHttpStatusError",
    "LiveBundleTimeoutError",
    "LiveBundleTlsError",
    "LiveHttpsSpireFedBundleFetcher",
    "MAX_BUNDLE_BYTES",
    "SPIRE_FED_BUNDLE_LIVE_HTTPS_FETCHER_SCHEMA",
    "SpireFedBundleLiveFetcherError",
]
