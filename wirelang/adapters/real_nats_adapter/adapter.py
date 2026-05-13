# SPDX-License-Identifier: BUSL-1.1
"""Real NATS adapter implementation: Protocol, Mock, Live.

See ``wirelang/adapters/real_nats_adapter/__init__.py`` for the
substantive narrative. This module carries the type-pin contracts,
the deterministic in-process mock, and the live nats-py-backed
adapter with SPIRE-fallback-policy.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Default endpoints + env contracts
# ---------------------------------------------------------------------------

_DEFAULT_NATS_URL = "nats://localhost:4222"
_NATS_URL_ENV = "WIRELANG_NATS_URL"
_SPIRE_AGENT_SOCKET_ENV = "SPIRE_AGENT_SOCKET"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class NatsAdapterError(Exception):
    """Base for all wirelang-side NATS-adapter errors.

    Persona-container code SHOULD NOT see ``nats-py``-internal
    exception types. The adapter maps upstream errors onto this
    surface so the consumer has a stable error contract.
    """


class NatsAdapterUnavailable(NatsAdapterError):
    """The NATS server endpoint is not reachable.

    Typical causes: NATS server not running, wrong URL, network
    partition. Consumers SHOULD treat as transient and either retry
    with backoff or fall back to a degraded mode.
    """


class NatsAdapterAuthenticationError(NatsAdapterError):
    """The NATS server rejected the authentication credentials.

    Typical causes: JWT-SVID expired, audience-mismatch, server-side
    auth-policy mismatch. Distinct from :class:`NatsAdapterUnavailable`:
    the server answered but rejected the credentials.
    """


# ---------------------------------------------------------------------------
# Status surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NatsAdapterStatus:
    """Adapter-status snapshot.

    Surfaces the runtime configuration so the persona-container can
    audit which mode the adapter is in. Used by tests and by the
    orchestrator's adapter-selection codepath.

    Fields:

    - ``adapter_kind``: ``"mock"`` or ``"live"``.
    - ``connected``: ``True`` iff the adapter holds an open NATS
      connection. For the mock, always ``True`` after construction.
    - ``server_url``: the NATS URL the live adapter is bound to (or
      ``None`` for the mock).
    - ``auth_mode``: ``"live-spiffe"`` (SPIRE-Workload-API-backed
      JWT-SVID), ``"mock-jwt"`` (mock JWT-Auth, operator-acceptable
      for development), or ``"no-auth"`` (no credentials sent —
      only valid against a permissive dev-NATS-server).
    - ``live_mode_marker``: set to ``"sprint-8-tag-1-real-adapter-mirror"``
      on the live adapter; absent on the mock. Audit-trace marker.
    """

    adapter_kind: str
    connected: bool
    server_url: Optional[str]
    auth_mode: str
    live_mode_marker: Optional[str] = None


# ---------------------------------------------------------------------------
# Reachability probe (hermetic)
# ---------------------------------------------------------------------------


def is_nats_reachable(
    url: Optional[str] = None,
    *,
    timeout_seconds: float = 0.5,
) -> bool:
    """Best-effort TCP-probe of the NATS-server endpoint.

    Used by test skip-with-marker logic and by the live-adapter's
    pre-connect gate. Does NOT speak the NATS protocol — only opens
    a TCP socket to the host/port and closes it immediately. Hermetic
    (no NATS handshake, no auth, no subject traffic).

    Parameters:

    - ``url``: NATS URL like ``"nats://localhost:4222"``. ``None``
      reads ``WIRELANG_NATS_URL`` from the environment, falling back
      to the default ``"nats://localhost:4222"``.
    - ``timeout_seconds``: socket-connect timeout. Short by design;
      the probe is meant to be fast-fail in the unreachable case.

    Returns:

    - ``True`` if the TCP connect succeeds.
    - ``False`` on any error (refused, timeout, DNS-fail, etc.).
    """

    if url is None:
        url = os.environ.get(_NATS_URL_ENV, _DEFAULT_NATS_URL)

    host, port = _parse_nats_url(url)
    if host is None or port is None:
        return False

    try:
        with socket.create_connection(
            (host, port), timeout=timeout_seconds
        ):
            return True
    except (OSError, socket.timeout):
        return False


def _parse_nats_url(url: str) -> tuple[Optional[str], Optional[int]]:
    """Parse ``nats://host:port`` into ``(host, port)``.

    Tolerant of malformed input: returns ``(None, None)`` on parse
    failure rather than raising. The reachability probe uses this
    to fast-fail on a misconfigured URL.
    """

    if not isinstance(url, str):
        return (None, None)
    prefix = "nats://"
    if not url.startswith(prefix):
        return (None, None)
    rest = url[len(prefix):]
    if ":" not in rest:
        return (None, None)
    host, _, port_str = rest.rpartition(":")
    try:
        port = int(port_str)
    except ValueError:
        return (None, None)
    return (host, port)


# ---------------------------------------------------------------------------
# Adapter Protocol surface
# ---------------------------------------------------------------------------


class NatsConnectionAdapter(Protocol):
    """Wirelang-side NATS-connection surface.

    Concurrency: implementations MUST be safe for concurrent use
    from multiple asyncio tasks.

    Lifecycle: ``connect`` opens the connection (Live) or marks the
    adapter ready (Mock). ``close`` releases resources. The
    Protocol does NOT mandate async-context-manager protocol;
    concrete implementations may add it.

    Error semantics: all method failures raise :class:`NatsAdapterError`
    or a subclass. Persona-container code MUST NOT need to import
    from ``nats-py`` to catch errors.
    """

    async def connect(self) -> None:
        """Establish the NATS connection / mark adapter ready.

        Raises:

        - :class:`NatsAdapterUnavailable` — endpoint not reachable.
        - :class:`NatsAdapterAuthenticationError` — auth rejected.
        - :class:`NatsAdapterError` — generic catch-all.
        """
        ...

    async def close(self) -> None:
        """Release the NATS connection. Idempotent.

        After ``close``, the adapter is unusable; the consumer must
        construct a fresh instance to reconnect.
        """
        ...

    async def publish(self, subject: str, payload: bytes) -> None:
        """Publish a single message on ``subject`` with ``payload``.

        Raises:

        - :class:`NatsAdapterUnavailable` — connection lost.
        - :class:`NatsAdapterError` — generic catch-all.
        """
        ...

    def status(self) -> NatsAdapterStatus:
        """Snapshot the current adapter status.

        Synchronous; safe to call before / during / after ``connect``.
        """
        ...


# ---------------------------------------------------------------------------
# Mock implementation (hermetic, deterministic)
# ---------------------------------------------------------------------------


@dataclass
class MockNatsConnectionAdapter:
    """Hermetic in-process mock for :class:`NatsConnectionAdapter`.

    Deterministic: same construction args + same call sequence
    produces byte-identical observable state. No network, no clock,
    no random. Mirror-pattern on
    :class:`wirelang.adapters.spiffe_workload_api.MockSpiffeWorkloadApiAdapter`.

    Construction:

    - ``server_url`` (Optional[str]): cosmetic; surfaces in
      :meth:`status` as ``server_url``. Defaults to ``None``.
    - ``auth_mode`` (str): ``"mock-jwt"`` (default) / ``"no-auth"``.
      Persona-container code MUST treat ``"no-auth"`` as a
      development-only mode; production deployments configure
      ``"live-spiffe"`` via :class:`RealNatsConnectionAdapter`.

    Behaviour:

    - :meth:`connect` flips ``self.connected`` to ``True``.
      Idempotent; second call is a no-op.
    - :meth:`publish` records ``(subject, payload)`` in
      ``self.published`` (list, append-only) when connected. Raises
      :class:`NatsAdapterUnavailable` when not connected. Hermetic
      message-bus.
    - :meth:`close` flips ``self.connected`` back to ``False``.
    - :meth:`status` surfaces a :class:`NatsAdapterStatus` snapshot
      with ``adapter_kind="mock"``.

    Concurrency: instance state is plain Python; concurrent
    ``publish`` calls from multiple asyncio tasks append to the same
    list. For test purposes this is deterministic enough; if a test
    needs strict ordering it MUST serialise its publish calls.
    """

    server_url: Optional[str] = None
    auth_mode: str = "mock-jwt"
    connected: bool = False
    published: list = field(default_factory=list)

    async def connect(self) -> None:
        # Idempotent; flipping from True to True is a no-op.
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def publish(self, subject: str, payload: bytes) -> None:
        if not self.connected:
            raise NatsAdapterUnavailable(
                "MockNatsConnectionAdapter: publish before connect — "
                "call .connect() first"
            )
        if not isinstance(subject, str) or not subject:
            raise NatsAdapterError(
                "MockNatsConnectionAdapter: subject must be non-empty str"
            )
        if not isinstance(payload, (bytes, bytearray)):
            raise NatsAdapterError(
                "MockNatsConnectionAdapter: payload must be bytes"
            )
        self.published.append((subject, bytes(payload)))

    def status(self) -> NatsAdapterStatus:
        return NatsAdapterStatus(
            adapter_kind="mock",
            connected=self.connected,
            server_url=self.server_url,
            auth_mode=self.auth_mode,
            live_mode_marker=None,
        )


# ---------------------------------------------------------------------------
# Live implementation (nats-py-backed, SPIRE-fallback-policy)
# ---------------------------------------------------------------------------


class RealNatsConnectionAdapter:
    """Live :class:`NatsConnectionAdapter` backed by ``nats-py``.

    **Live-mode marker:** ``"sprint-8-tag-1-real-adapter-mirror"``.

    Sandbox-Boundary: localhost:4222 ist Operator-Hand-Fedora-Host.
    Der Persona-Container darf NICHT annehmen, dass NATS verfügbar
    ist. Tests gegen diesen Adapter MÜSSEN den Skip-with-Marker-Pfad
    respektieren (siehe :func:`is_nats_reachable`).

    SPIRE-Fallback-Policy
    ---------------------

    Der Konstruktor liest ``SPIRE_AGENT_SOCKET`` aus der Umgebung:

    - Wenn nicht gesetzt ODER explizit ``"none"`` ODER leer:
      Fallback auf ``auth_mode="mock-jwt"`` (Operator-side
      acceptable for development; siehe Sprint-7-Closeout-Stempel
      M-2 "SPIRE-Live als Operator-Hand-blockiert akzeptiert").
    - Wenn auf eine URI gesetzt (z.B.
      ``unix:///tmp/spire-agent/public/api.sock``):
      Markiert ``auth_mode="live-spiffe"`` — die tatsächliche
      Workload-API-Anbindung läuft über
      :mod:`wirelang.adapters.real_spiffe_workload_api`
      (Sprint-7+ / Phase-2c, Konstruktor-Gate WAKIR_SPIRE_LIVE=1).
      Wenn die SPIRE-Workload-API beim ``connect`` nicht erreichbar
      ist, raised :class:`NatsAdapterAuthenticationError` —
      Live-SPIFFE wurde explizit angefordert aber kann nicht
      erfüllt werden.

    Konstruktor-Parameter:

    - ``server_url`` (Optional[str]): NATS URL. ``None`` liest
      ``WIRELANG_NATS_URL`` aus der Umgebung, default
      ``"nats://localhost:4222"``.
    - ``connect_timeout_seconds`` (float): Timeout für den
      ``nats-py``-Connect-Aufruf. Default 2.0s.

    Lifecycle:

    - :meth:`connect` öffnet die Live-Verbindung (oder raised
      :class:`NatsAdapterUnavailable` wenn die Reachability-Probe
      fehlschlägt; vermeidet einen vollen ``nats-py``-Connect-Round-
      trip wenn der Endpunkt offensichtlich tot ist).
    - :meth:`publish` delegiert an ``nats-py``-Client mit
      Exception-Mapping auf :class:`NatsAdapterError`-Hierarchie.
    - :meth:`close` schliesst die Verbindung idempotent.

    Cross-Trust-Domain-Bridge-Anbindung
    ------------------------------------

    Der Adapter ist als Substrat-Layer für Sprint-7 Tag-3
    :mod:`wirelang.federation` SpiffeCrossTrustDomainBridge gedacht.
    Wenn ``auth_mode="live-spiffe"``, MUSS der Konsument die
    SPIFFE-ID des Workloads aus
    :mod:`wirelang.adapters.real_spiffe_workload_api` ableiten und
    als ``user_jwt_cb`` an ``nats-py`` ``Client.connect`` weitergeben.
    Dieser Adapter implementiert das Coupling NICHT direkt
    (Operator-Hand-blockiert); er liefert nur das Surface-Pin.

    Concurrency: instance state hält den ``nats-py``-Client;
    concurrent ``publish`` calls sind safe (nats-py-Client ist
    asyncio-aware).
    """

    LIVE_MODE_MARKER = "sprint-8-tag-1-real-adapter-mirror"

    def __init__(
        self,
        server_url: Optional[str] = None,
        *,
        connect_timeout_seconds: float = 2.0,
    ) -> None:
        if server_url is None:
            server_url = os.environ.get(_NATS_URL_ENV, _DEFAULT_NATS_URL)
        self._server_url = server_url
        self._connect_timeout = connect_timeout_seconds
        self._client = None  # nats-py Client instance, lazy-init on connect()
        self._connected = False
        self._auth_mode = self._resolve_auth_mode()

    @staticmethod
    def _resolve_auth_mode() -> str:
        """Map ``SPIRE_AGENT_SOCKET`` to an ``auth_mode`` label."""

        socket_value = os.environ.get(_SPIRE_AGENT_SOCKET_ENV, "")
        normalised = socket_value.strip().lower()
        if normalised in ("", "none"):
            return "mock-jwt"
        return "live-spiffe"

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    async def connect(self) -> None:
        """Open the live NATS connection.

        Two-stage gate:

        1. Reachability-probe (TCP connect, fast-fail). If the probe
           fails, raises :class:`NatsAdapterUnavailable` BEFORE
           involving ``nats-py``. This keeps the failure mode clean
           in the sandbox where localhost:4222 is unreachable.
        2. ``nats-py`` Client.connect with the configured timeout.

        For ``auth_mode="live-spiffe"``, the SPIFFE-Workload-API
        anbindung is currently Operator-Hand-blocked — raised
        :class:`NatsAdapterAuthenticationError` because the
        live-SPIFFE path requires Kai's DevOps-Track SPIRE-server
        bootstrap (Phase-2c+ Operator-Hand). Operator-side bypass
        via ``SPIRE_AGENT_SOCKET=none`` to fall back to ``mock-jwt``.
        """

        if not is_nats_reachable(self._server_url, timeout_seconds=0.5):
            raise NatsAdapterUnavailable(
                f"RealNatsConnectionAdapter: TCP probe of "
                f"{self._server_url!r} failed — NATS server not "
                f"reachable. Sandbox: localhost:4222 ist "
                f"Operator-Hand-Fedora-Host."
            )

        if self._auth_mode == "live-spiffe":
            raise NatsAdapterAuthenticationError(
                "RealNatsConnectionAdapter: auth_mode=live-spiffe is "
                "Operator-Hand-blocked (Sprint-7-Closeout-Stempel M-2: "
                "SPIRE-Live Phase-2.3+ pending Kai-DevOps-Track). "
                "Set SPIRE_AGENT_SOCKET=none to fall back to mock-jwt."
            )

        # Lazy-import nats-py to keep test-suite hermetic when nats-py
        # is not installed in the persona-container (the test runner
        # then exercises the skip-with-marker path via
        # ``is_nats_reachable``).
        try:
            from nats.aio.client import Client as NatsClient
        except ImportError as exc:
            raise NatsAdapterUnavailable(
                f"RealNatsConnectionAdapter: nats-py not installed "
                f"({exc}). Install ``nats-py`` or use "
                f"MockNatsConnectionAdapter."
            ) from exc

        client = NatsClient()
        try:
            await client.connect(
                servers=[self._server_url],
                connect_timeout=self._connect_timeout,
            )
        except Exception as exc:
            # Map nats-py upstream errors onto our hierarchy. We
            # cannot ``isinstance`` against nats-py-internal types
            # without importing them eagerly, so we string-match the
            # canonical names. Conservative: any error during connect
            # is mapped to NatsAdapterUnavailable unless it carries
            # an auth-keyword.
            err_msg = str(exc).lower()
            if "auth" in err_msg or "permission" in err_msg:
                raise NatsAdapterAuthenticationError(
                    f"RealNatsConnectionAdapter: NATS auth rejected — "
                    f"{exc}"
                ) from exc
            raise NatsAdapterUnavailable(
                f"RealNatsConnectionAdapter: NATS connect failed — "
                f"{exc}"
            ) from exc

        self._client = client
        self._connected = True

    async def close(self) -> None:
        """Close the live NATS connection. Idempotent."""

        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                # Best-effort close; suppress upstream errors so
                # callers can rely on close-idempotency.
                pass
        self._client = None
        self._connected = False

    async def publish(self, subject: str, payload: bytes) -> None:
        """Publish on a live NATS connection.

        Errors map onto :class:`NatsAdapterError` per the contract.
        """

        if not self._connected or self._client is None:
            raise NatsAdapterUnavailable(
                "RealNatsConnectionAdapter: publish before connect — "
                "call .connect() first"
            )
        if not isinstance(subject, str) or not subject:
            raise NatsAdapterError(
                "RealNatsConnectionAdapter: subject must be non-empty str"
            )
        if not isinstance(payload, (bytes, bytearray)):
            raise NatsAdapterError(
                "RealNatsConnectionAdapter: payload must be bytes"
            )
        try:
            await self._client.publish(subject, bytes(payload))
        except Exception as exc:
            raise NatsAdapterError(
                f"RealNatsConnectionAdapter: publish failed — {exc}"
            ) from exc

    def status(self) -> NatsAdapterStatus:
        return NatsAdapterStatus(
            adapter_kind="live",
            connected=self._connected,
            server_url=self._server_url,
            auth_mode=self._auth_mode,
            live_mode_marker=self.LIVE_MODE_MARKER,
        )
