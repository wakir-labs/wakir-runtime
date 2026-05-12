# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# NATS-JWT-Auth `user_jwt_cb` callback skizze (Phase-2 Sprint-6 Tag-10).
#
# This module is **Skizze-Validations-Substanz**. It does not start a
# NATS connection, does not call SPIRE Workload-API, and does not link
# in real `nats-py`/`spiffe` imports. It defines:
#
# - A typed contract for a JWT-SVID cache surface a wirelang-side
#   adapter is expected to expose (path-by-name reference to
#   ``wirelang/adapters/spiffe_workload_api.py`` :class:`JwtSvidCache`-
#   shape; the Tag-10 substrate does NOT import the wirelang adapter).
# - A :func:`make_user_jwt_cb` factory that builds the synchronous
#   callable signature ``nats-py`` invokes at every CONNECT-frame build
#   (verified `nats/aio/client.py` Z. 1666-1668).
# - Refresh-on-Reconnect semantics: the callback always reads the
#   current SVID from the cache; it does NOT cache locally and does
#   NOT issue Workload-API fetches itself. The wirelang-side adapter
#   is expected to keep the cache fresh via a background
#   ``WatchJWTSVIDs`` stream (Phase-2.3 Operator-Hand bring-up).
# - Error semantics: if the cache yields no current SVID (cold-start
#   race or stream-stall), the callback raises
#   :class:`NatsJwtCallbackCacheEmpty` — caller (persona-container
#   boot path) MUST gate the NATS-connect call on cache-hot status.
#
# Cross-references (path-by-name; no imports):
# - ``wirelang/adapters/spiffe_workload_api.py`` (Reza Sprint-6 Tag-5,
#   commit ``9c94517``) — provides :class:`JwtSvid`, :class:`Mock-
#   SpiffeWorkloadApiAdapter`, error-hierarchy. Tag-10 references the
#   surface by name; tests use a Tag-10-local :class:`InMemorySvidCache`
#   stub so the skizze module remains importable without the wirelang
#   adapter substrate landing in the same branch.
# - ``docs/spiffe-z-a-jwt-svid-skizze.md`` §4.2-Punkt-7 + §6 §3 — the
#   refresh-on-reconnect client-side-callback pattern (Reza-Ack-Slot-4
#   correction; NOT a NATS-server feature).
# - ``scripts/spiffe_skizze_constants.py`` — re-used for
#   ``NATS_JWT_AUDIENCE_PHASE_2`` audience constant.
# - ``.venv/lib/python3.14/site-packages/nats/aio/client.py`` Z. 110
#   (JWTCallback typedef), Z. 317 (field), Z. 370 (connect-signature),
#   Z. 1666-1668 (CONNECT-frame-build invocation).
#
# Reference: docs/nats-jwt-auth-phase-2-4.md (Tag-10).
"""NATS-JWT-Auth `user_jwt_cb` callback skizze (Phase-2 Sprint-6 Tag-10).

The :func:`make_user_jwt_cb` factory builds the synchronous zero-arg
callable ``nats-py`` invokes inside the CONNECT-frame builder. The
callable returns the encoded JWT token as ``bytes`` matching the
``JWTCallback = Callable[[], Union[bytearray, bytes]]`` upstream
typedef.

Phase: hermetic skizze; persona-container wire-up lands in Phase-2.4
post-Operator-Hand bring-up (see ``docs/nats-jwt-auth-phase-2-4.md``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol


# ---------------------------------------------------------------------
# Surface contract — JwtSvidCache (wirelang-side; Tag-10 stub)
# ---------------------------------------------------------------------


class JwtSvidCacheView(Protocol):
    """Read-only view of the current cached JWT-SVID.

    The wirelang-side ``spiffe_workload_api`` adapter is expected to
    expose this surface via a ``JwtSvidCache`` object that:

    - Holds the most-recently observed JWT-SVID from a background
      ``WatchJWTSVIDs`` stream against the SPIRE Workload-API.
    - Is updated by the adapter (not by this callback).
    - Returns ``None`` when no SVID has been observed yet (cold-start
      window before the first stream push).

    Tag-10 substrate references this surface by name; the wirelang
    adapter at ``wirelang/adapters/spiffe_workload_api.py`` lands the
    concrete cache type in Sprint-6+ (Reza-track). Tag-10 tests use
    :class:`InMemorySvidCache` (below) as a hermetic local stub.

    Contract:

    - ``current_token`` returns the **encoded JWT-SVID bytes** (UTF-8
      bytes of the compact JWS form). ``None`` means "no current SVID".
    - ``current_expires_at`` returns the ``exp`` claim as a
      timezone-aware UTC datetime, or ``None`` when no SVID is cached.
    - ``current_spiffe_id`` returns the SPIFFE-ID URI of the cached
      SVID, or ``None``. Used for logging / drift-detection only;
      ``nats-py`` does not consume it.
    """

    def current_token(self) -> Optional[bytes]:
        ...

    def current_expires_at(self) -> Optional[datetime]:
        ...

    def current_spiffe_id(self) -> Optional[str]:
        ...


# ---------------------------------------------------------------------
# Local hermetic cache stub (Tag-10 tests only)
# ---------------------------------------------------------------------


class InMemorySvidCache:
    """Hermetic in-process :class:`JwtSvidCacheView` implementation.

    Tag-10 substrate uses this for tests; production persona-container
    code consumes the wirelang-side ``JwtSvidCache`` (path-by-name).

    Construction:

    - ``token``: the initial cached token bytes (or ``None`` for cold).
    - ``expires_at``: the initial ``exp`` (or ``None``).
    - ``spiffe_id``: the initial cached SPIFFE-ID (or ``None``).

    Mutation: tests call :meth:`set` to simulate a fresh push from
    the background ``WatchJWTSVIDs`` stream; :meth:`clear` simulates a
    stream stall.

    Note: this is intentionally minimal — no locking, no async, no
    expiry-driven eviction. The wirelang-side production cache adds
    those concerns.
    """

    def __init__(
        self,
        *,
        token: Optional[bytes] = None,
        expires_at: Optional[datetime] = None,
        spiffe_id: Optional[str] = None,
    ) -> None:
        self._token = token
        self._expires_at = expires_at
        self._spiffe_id = spiffe_id

    def current_token(self) -> Optional[bytes]:
        return self._token

    def current_expires_at(self) -> Optional[datetime]:
        return self._expires_at

    def current_spiffe_id(self) -> Optional[str]:
        return self._spiffe_id

    def set(
        self,
        *,
        token: bytes,
        expires_at: datetime,
        spiffe_id: str,
    ) -> None:
        if not isinstance(token, (bytes, bytearray)):
            raise TypeError("token must be bytes/bytearray")
        if not isinstance(expires_at, datetime):
            raise TypeError("expires_at must be a datetime")
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if not isinstance(spiffe_id, str) or not spiffe_id:
            raise ValueError("spiffe_id must be a non-empty string")
        self._token = bytes(token)
        self._expires_at = expires_at
        self._spiffe_id = spiffe_id

    def clear(self) -> None:
        self._token = None
        self._expires_at = None
        self._spiffe_id = None


# ---------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------


class NatsJwtCallbackError(Exception):
    """Base class for Tag-10 callback errors."""


class NatsJwtCallbackCacheEmpty(NatsJwtCallbackError):
    """The cache yielded no current SVID at CONNECT-frame-build time.

    Persona-container boot path MUST gate the ``nats.connect()`` call
    on cache-hot status (the wirelang adapter exposes a "wait for first
    SVID" surface; Tag-10 substrate does not). Raising at CONNECT-frame-
    build aborts the connect attempt cleanly inside the ``nats-py``
    state-machine.
    """


class NatsJwtCallbackSvidExpired(NatsJwtCallbackError):
    """The cached SVID is past its ``exp`` claim at callback-invocation.

    The wirelang-side background ``WatchJWTSVIDs`` stream is expected to
    refresh well before ``exp`` (SPIRE default: push at ``exp - 5min``).
    If this error fires, the refresh path stalled — Operator-Hand
    diagnostics (Phase-2.6 Trust-Bundle-Rotation-Runbook slot).

    By default :func:`make_user_jwt_cb` does NOT enforce the
    expires-at check (the NATS-server validates ``exp`` server-side
    anyway). Tests can set ``enforce_exp=True`` to surface stalls
    client-side at CONNECT-time.
    """


# ---------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------


def make_user_jwt_cb(
    cache: JwtSvidCacheView,
    *,
    enforce_exp: bool = False,
    now: Optional[Callable[[], datetime]] = None,
) -> Callable[[], bytes]:
    """Build the synchronous zero-arg callable ``nats-py`` invokes.

    Returns a callable matching the ``nats-py`` typedef
    ``JWTCallback = Callable[[], Union[bytearray, bytes]]`` (`nats/aio/
    client.py` Z. 110). ``nats-py`` invokes the returned callable at
    every CONNECT-frame build (Z. 1666-1668) — that includes initial
    connect AND reconnect-after-network-glitch.

    Parameters:

    - ``cache``: the JWT-SVID cache surface. Tag-10 hermetic tests pass
      :class:`InMemorySvidCache`; production persona-container code
      passes the wirelang-side ``JwtSvidCache`` (path-by-name).
    - ``enforce_exp``: when ``True``, the callback raises
      :class:`NatsJwtCallbackSvidExpired` if the cached SVID's ``exp``
      claim is past ``now``. Default ``False`` (NATS-server validates
      ``exp`` server-side).
    - ``now``: clock injection for tests. ``None`` (default) reads
      ``datetime.now(timezone.utc)`` at each invocation.

    Returns: zero-arg callable returning ``bytes``.

    Raises (at invocation time):

    - :class:`NatsJwtCallbackCacheEmpty` if cache yields no SVID.
    - :class:`NatsJwtCallbackSvidExpired` if ``enforce_exp=True`` and
      the cached SVID is past expiry.

    Refresh-on-Reconnect semantics: the callable reads the **current**
    cache state at each call. Between connect attempts, the wirelang-
    side background stream is expected to have refreshed the cache.
    ``nats-py`` does NOT re-use a stale token across reconnects (it
    re-invokes the callback) — verified `nats/aio/client.py` Z.
    1666-1668.
    """

    def _now() -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        return now()

    def _user_jwt_cb() -> bytes:
        token = cache.current_token()
        if token is None:
            raise NatsJwtCallbackCacheEmpty(
                "JwtSvidCache is empty at CONNECT-frame-build time; "
                "persona-container boot path must gate nats.connect() "
                "on cache-hot status (see "
                "wirelang/adapters/spiffe_workload_api.py JwtSvidCache "
                "wait-for-first-SVID surface)."
            )
        if enforce_exp:
            exp = cache.current_expires_at()
            if exp is not None and _now() >= exp:
                raise NatsJwtCallbackSvidExpired(
                    f"Cached SVID expired at {exp.isoformat()} "
                    f"(now={_now().isoformat()}); background "
                    f"WatchJWTSVIDs stream appears stalled. See "
                    f"Phase-2.6 Trust-Bundle-Rotation-Runbook slot."
                )
        return bytes(token)

    return _user_jwt_cb


# ---------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------

__all__ = [
    "InMemorySvidCache",
    "JwtSvidCacheView",
    "NatsJwtCallbackCacheEmpty",
    "NatsJwtCallbackError",
    "NatsJwtCallbackSvidExpired",
    "make_user_jwt_cb",
]
