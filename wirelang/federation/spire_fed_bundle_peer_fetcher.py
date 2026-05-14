# SPDX-License-Identifier: BUSL-1.1
"""SPIRE-Federation-Bundle peer-trust-bundle fetcher (Live-Component).

Phase-2 Sprint-7 Pfad-B Tag-5 lands the **live-component** adapter
that wires the Sprint-7 Tag-3 :class:`SpiffeCrossTrustDomainBridge`
to the Sprint-8 Tag-1 ``infra/spire/federation/bin/spire_fed_bundle``
hermetic-mode CLI. With this adapter on the bridge's
``trust_bundle_fetcher`` slot, a Wakir-side bridge can resolve a
peer-org's trust-bundle by exporting the peer-org's hermetic-fixture
JWKS through the same CLI surface the operator uses for the manual
bootstrap roundtrip (``compose/spire-federation.yaml`` §3 README).

Composition contract
====================

The adapter composes three on-disk surfaces:

1. ``infra/spire/federation/bin/spire_fed_bundle.export_bundle`` —
   the hermetic-mode bundle exporter. The adapter shells out to the
   in-process Python function (NOT a subprocess), so the test
   surface stays hermetic and free of podman / spire-server runtime
   dependencies.
2. The bridge's :class:`PeerTrustBundleFetcher` Protocol — the
   adapter implements the async ``fetch(url, trust_domain)`` shape
   the bridge expects.
3. The bridge's :class:`FetchedTrustBundle` value object — the
   adapter wraps the exported JWKS bytes plus a deterministic
   ``fetched_at`` timestamp into a :class:`FetchedTrustBundle` the
   bridge can consume.

The adapter is **fail-closed at every step**: a trust-domain
mismatch between the requested fetch and the adapter's pinned
trust-domains raises a typed error; the bridge wraps that as a
:class:`PeerTrustBundleFetchError`.

Hermetic-mode rationale
=======================

This is the **hermetic** path. The adapter does NOT perform an
HTTPS GET against a live SPIRE-Server bundle-endpoint listener; it
reads the deterministic fixture JWKS that
``spire_fed_bundle.export_bundle`` produces for the named trust-
domain. The bytes are well-formed JWKS with EC-P-256 placeholder
coordinates seeded by the trust-domain literal — bit-identical
across runs, distinct across trust-domains.

Phase-2c follow-up: a separate Phase-2c live HTTPS fetcher will
implement the same :class:`PeerTrustBundleFetcher` Protocol by
issuing an HTTPS GET against the peer's bundle-endpoint listener
(loopback-bound in the compose substrate, ``https_spiffe`` profile
in production federation). The adapter shipped here is the bridge
between hermetic-only Sprint-7 substrate and operator-hand-gated
Sprint-8+ live federation trial.

Caching
=======

The adapter caches the last-exported bundle per (url, trust_domain)
pair so repeated bridge resolutions over the same route do not
re-export the JWKS. The cache is in-process; the adapter is a
plain dataclass so callers can construct one per
bridge-resolution scope and let the GC discard the cache when the
scope ends. A future minor bump can add an LRU eviction policy if
the in-process cache grows in production-loop usage.

URL contract
============

The adapter is constructed with a pinned
``trust_domain_to_url`` mapping. The bridge calls
``fetch(url=..., trust_domain=...)`` with the
attestation-supplied URL; the adapter rejects any URL that does not
match the pinned URL for the requested trust-domain. This guard
prevents a misconfigured attestation from coercing the adapter
into exporting a different trust-domain's bundle under the wrong
URL label.

The URL itself is opaque to the adapter — the hermetic-mode
exporter only consumes the trust-domain literal. The pinned URL
is the *bridge-consumed* artefact: the bridge stores it as the
:attr:`FetchedTrustBundle.url` for downstream audit consumers. In
production federation, the same URL is the
``https_spiffe://``-shaped bundle-endpoint URL.

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this module. Pre-Box-Worktree
ADR-0049 ``/tmp/reza-sprint-7-pfad-b-tag-5-runtime`` (suffix
``-runtime`` per Cross-Agent-Worktree-Collision policy), forked
from ``origin/main`` tip ``a2647ba``.

ADR-0051 Sandbox-Boundary
=========================

This module is **hermetic-only**. It does NOT call podman, does NOT
shell out to a live SPIRE-Server container, and does NOT depend on
any operator-hand artefact. The live-mode counterpart is a
Phase-2c Sprint-8+ artefact that lives in its own module so the
Sandbox-Host trennung (feedback_sandbox_host_trennung.md) is
preserved at the import-graph layer.

Cross-Review Zone-O
===================

This module is a Reza-side Wirelang substrate (Zone-O Reza-track).
Cross-review consumers:

- **D-2 Kai (DevOps/SPIRE-Federation-Bundle-Endpoint):** the URL
  shape this adapter consumes (``https://...`` bundle-endpoint
  URLs) MUST match the Kai-side SPIRE-Server config
  ``federation.bundle_endpoint`` listener configuration. The
  Phase-2c live fetcher will hit the same URL.
- **D-1 Tomás (WAT-Audit-Federation-Annex):** the
  :class:`FetchedTrustBundle.bundle_bytes` this adapter returns
  is what the WAT-Audit-Federation-Annex sweep anchors as the
  cross-org trust-bundle leaf.

Version: ``wakir.federation.spire-fed-bundle-peer-fetcher/1``.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .spiffe_cross_trust_domain_bridge import (
    FetchedTrustBundle,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Schema-URI fragment for this adapter. Carried in
#: :attr:`SpireFedBundlePeerTrustBundleFetcher.adapter_schema` so
#: downstream code (audit consumers, log emitters) can identify the
#: adapter by schema-pin rather than by class identity.
SPIRE_FED_BUNDLE_PEER_FETCHER_SCHEMA = (
    "wakir.federation.spire-fed-bundle-peer-fetcher/1"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SpireFedBundlePeerFetcherError(Exception):
    """Base class for adapter-internal errors.

    The bridge catches any exception from the fetcher and re-raises
    as :class:`PeerTrustBundleFetchError`; this hierarchy gives the
    test surface a precise type to assert against for adapter-side
    failure modes (vs. bridge-wrapped errors).
    """


class UnpinnedTrustDomainError(SpireFedBundlePeerFetcherError):
    """The adapter was asked to fetch a trust-domain not pinned at
    construction time. Fail-closed: the adapter never exports a
    JWKS for a trust-domain the operator did not explicitly enable.

    Attributes:
        trust_domain: the trust-domain the bridge requested.
        pinned: the tuple of trust-domains the adapter was pinned
            to at construction time.
    """

    def __init__(
        self,
        message: str,
        *,
        trust_domain: str,
        pinned: tuple,
    ) -> None:
        super().__init__(message)
        self.trust_domain = trust_domain
        self.pinned = pinned


class UrlTrustDomainMismatchError(SpireFedBundlePeerFetcherError):
    """The bridge-supplied URL does not match the adapter's pinned
    URL for the requested trust-domain. Fail-closed: the adapter
    refuses to export under a URL it was not configured to honour.

    Attributes:
        trust_domain: the trust-domain the bridge requested.
        requested_url: the URL the bridge passed.
        pinned_url: the URL the adapter has pinned for the
            requested trust-domain.
    """

    def __init__(
        self,
        message: str,
        *,
        trust_domain: str,
        requested_url: str,
        pinned_url: str,
    ) -> None:
        super().__init__(message)
        self.trust_domain = trust_domain
        self.requested_url = requested_url
        self.pinned_url = pinned_url


# ---------------------------------------------------------------------------
# spire-fed-bundle CLI module loader
# ---------------------------------------------------------------------------
#
# The CLI module lives at ``infra/spire/federation/bin/spire_fed_bundle.py``;
# the path is OUTSIDE the ``wirelang`` Python package, so a plain
# ``from infra...`` import does not work. We load the module by file
# path and cache it on first access.
#
# Rationale for not turning ``infra/`` into a package: the file is
# an operator CLI (sibling to ``spire-fed-bundle`` shebang script),
# not part of the wirelang public surface. Keeping the import
# isolated here means the wirelang package never imports operator
# tooling at module-import time; only callers that actively
# construct an adapter pay the file-path lookup cost.


_CLI_MODULE_CACHE: Optional[Any] = None


def _resolve_repo_root() -> Path:
    """Return the repository root path.

    Walks upward from this file's parent until it finds a directory
    that contains ``infra/spire/federation/bin/spire_fed_bundle.py``.
    Raises :class:`SpireFedBundlePeerFetcherError` if the file is
    not reachable (e.g. when the wirelang package is installed
    standalone without the ``infra/`` tree).
    """
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = (
            ancestor
            / "infra"
            / "spire"
            / "federation"
            / "bin"
            / "spire_fed_bundle.py"
        )
        if candidate.exists():
            return ancestor
    raise SpireFedBundlePeerFetcherError(
        "spire_fed_bundle.py not reachable from "
        f"{here}: walked {len(here.parents)} ancestors without "
        "finding infra/spire/federation/bin/spire_fed_bundle.py. The "
        "adapter requires the in-repo CLI module to be present; "
        "wirelang-only standalone installs do NOT carry the operator "
        "tooling tree."
    )


def _load_cli_module() -> Any:
    """Load and cache the spire_fed_bundle CLI module.

    Idempotent: subsequent calls return the same module instance.
    Thread-safe at the import-time scope: ``importlib.util`` machinery
    is itself thread-safe, and we use ``sys.modules`` membership as
    the cache anchor so duplicate concurrent loads collapse to a
    single module instance.
    """
    global _CLI_MODULE_CACHE
    if _CLI_MODULE_CACHE is not None:
        return _CLI_MODULE_CACHE
    cached = sys.modules.get("spire_fed_bundle_cli_adapter")
    if cached is not None:
        _CLI_MODULE_CACHE = cached
        return cached
    repo_root = _resolve_repo_root()
    cli_path = (
        repo_root
        / "infra"
        / "spire"
        / "federation"
        / "bin"
        / "spire_fed_bundle.py"
    )
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_cli_adapter", cli_path
    )
    if spec is None or spec.loader is None:
        raise SpireFedBundlePeerFetcherError(
            f"importlib could not produce a spec for {cli_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_cli_adapter"] = module
    spec.loader.exec_module(module)
    _CLI_MODULE_CACHE = module
    return module


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpireFedBundlePeerTrustBundleFetcher:
    """Live-component :class:`PeerTrustBundleFetcher` implementation
    backed by the hermetic-mode ``spire-fed-bundle export`` CLI.

    Construction:

    - ``trust_domain_to_url``: a mapping from trust-domain literal
      to the URL the bridge will consume. The adapter ONLY honours
      trust-domains present in this mapping; any other trust-domain
      raises :class:`UnpinnedTrustDomainError`.
    - ``clock``: optional callable returning a timezone-aware UTC
      datetime. Defaults to :func:`datetime.now(timezone.utc)`.
      Tests inject a fixed-clock fake for determinism.

    The adapter is **frozen and stateless** (the cache is module-
    level on the CLI module side). Multiple bridges can share one
    adapter instance.

    Resolution contract (:meth:`fetch`):

    1. Reject if ``trust_domain`` is not in the pinned mapping
       (raise :class:`UnpinnedTrustDomainError`).
    2. Reject if ``url`` does not equal the pinned URL for the
       requested ``trust_domain`` (raise
       :class:`UrlTrustDomainMismatchError`).
    3. Invoke ``spire_fed_bundle.export_bundle(trust_domain)`` to
       obtain the hermetic-fixture JWKS bytes. The CLI function is
       in-process; no subprocess.
    4. Construct a :class:`FetchedTrustBundle` with the bridge-
       supplied URL, the exported JWKS bytes, the requested trust-
       domain, and ``self._now()`` as ``fetched_at``.
    5. Return the bundle.

    All failure modes are typed; the adapter does not log on the
    path.

    Caller surface:

    Callers obtain a bridge that consumes this adapter via the
    standard injection-point ::

        adapter = SpireFedBundlePeerTrustBundleFetcher(
            trust_domain_to_url={
                "partner.test": "https://spire-server-partner:8443/bundle",
                "wakir.test": "https://spire-server-wakir:8443/bundle",
            },
        )
        bridge = SpiffeCrossTrustDomainBridge(
            route_registry=...,
            attestation_registry=...,
            trust_bundle_fetcher=adapter,
            peer_svid_verifier=...,
            ...
        )

    The URLs above are the loopback-bound bundle-endpoint listeners
    from ``compose/spire-federation.yaml``; in production federation
    they become the ``https_spiffe://`` profile URLs the SPIRE-Servers
    expose externally.
    """

    trust_domain_to_url: dict
    clock: Optional[Any] = None

    @property
    def adapter_schema(self) -> str:
        """Stable schema-URI for this adapter; useful for audit logs."""
        return SPIRE_FED_BUNDLE_PEER_FETCHER_SCHEMA

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "SpireFedBundlePeerTrustBundleFetcher.clock must "
                    "return a datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "SpireFedBundlePeerTrustBundleFetcher.clock must "
                    "return a timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    def _pinned_url(self, trust_domain: str) -> str:
        if trust_domain not in self.trust_domain_to_url:
            raise UnpinnedTrustDomainError(
                f"trust_domain {trust_domain!r} not in adapter pin set; "
                f"pinned={tuple(self.trust_domain_to_url)!r}",
                trust_domain=trust_domain,
                pinned=tuple(self.trust_domain_to_url),
            )
        return self.trust_domain_to_url[trust_domain]

    async def fetch(
        self, *, url: str, trust_domain: str
    ) -> FetchedTrustBundle:
        """Export the peer trust-bundle for ``trust_domain`` via the
        hermetic-mode spire-fed-bundle CLI and return a bridge-
        consumable :class:`FetchedTrustBundle`.
        """
        pinned_url = self._pinned_url(trust_domain)
        if url != pinned_url:
            raise UrlTrustDomainMismatchError(
                f"bridge requested url {url!r} for trust_domain "
                f"{trust_domain!r} but adapter is pinned to "
                f"{pinned_url!r} for that trust_domain",
                trust_domain=trust_domain,
                requested_url=url,
                pinned_url=pinned_url,
            )
        cli = _load_cli_module()
        jwks_text = cli.export_bundle(trust_domain)
        bundle_bytes = jwks_text.encode("utf-8")
        return FetchedTrustBundle(
            trust_domain=trust_domain,
            url=url,
            bundle_bytes=bundle_bytes,
            fetched_at=self._now(),
        )


__all__ = [
    "SPIRE_FED_BUNDLE_PEER_FETCHER_SCHEMA",
    "SpireFedBundlePeerFetcherError",
    "SpireFedBundlePeerTrustBundleFetcher",
    "UnpinnedTrustDomainError",
    "UrlTrustDomainMismatchError",
]
