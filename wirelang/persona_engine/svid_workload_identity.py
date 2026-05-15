# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""SPIFFE Workload-API SVID fetch (Zone-L, spec §3.7.4 R3).

Engine-side caller for the SPIRE Workload-API socket bind-mounted
into the persona-container at ``/run/spire/agent-sockets/api.sock``
(Quadlet ``Volume=wakir-spire-agent-sockets.volume:...``).

Sprint-Pengine-9 OI-PEFR-2 surface
----------------------------------

The v0.2.0-pilot binding shipped only a **socket-presence probe**:
``connect()``-on-UDS, no protocol exchange. Sprint-Pengine-9 adds
the full Workload-API SVID-fetch via grpcio:

1. **Socket-presence probe** (preserved). :func:`probe_workload_api_socket`
   keeps its v0.2.0-pilot semantics for the boot-gate path; the
   engine probe runs before the gRPC fetch to fail fast on a
   missing SPIRE-Agent.
2. **Full SVID-fetch** (new). :class:`WorkloadApiClient` opens a
   gRPC unix-socket channel to the SPIRE-Agent and calls the
   ``SpiffeWorkloadAPI.FetchX509SVID`` RPC. The stream-first
   response is consumed for the leaf certificate; the engine
   logs the SPIFFE-ID (Subject URI), the SAN list, the certificate
   not-after timestamp, and a bind-state hash as an audit
   annotation.

The implementation is **factory-injectable** for hermetic tests:
:class:`WorkloadApiClient` accepts a ``channel_factory`` and a
``stub_factory`` so the test suite can drive the fetch flow with a
fake gRPC channel that replays canned SVID bytes.

Zone-L cross-review
-------------------

Reza (Identity-Substrate) owns the SPIFFE-ID template + the
certificate-not-after semantics. The protobuf surface
(:mod:`wirelang.persona_engine._workload_api_pb2_minimal`)
mirrors the SPIFFE Workload-API v0.4 proto fields the engine
actually consumes — full proto reflection is not required for the
narrow read-only fetch path.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants (Zone-L cross-review surface).
# ---------------------------------------------------------------------------

#: Default Workload-API Unix socket path inside the persona-container.
#: Matches the Quadlet ``Volume=wakir-spire-agent-sockets.volume:
#: /run/spire/agent-sockets:ro,Z,U`` line.
DEFAULT_WORKLOAD_API_SOCKET_PATH = "/run/spire/agent-sockets/api.sock"

#: Expected SPIFFE-ID template for a persona-engine workload.
#: ``{org_id}`` and ``{persona_id}`` are filled in by the engine from
#: the WAKIR_ORG_ID + WAKIR_PERSONA_ID env vars.
SPIFFE_ID_TEMPLATE = "spiffe://wakir.{org_id}/persona/{persona_id}"

#: SPIFFE_ENDPOINT_SOCKET env-var key (parity with the SPIRE-SDK
#: convention used by ``go-spiffe`` and ``spire-agent``).
SPIFFE_ENDPOINT_SOCKET_ENV = "SPIFFE_ENDPOINT_SOCKET"

#: SPIFFE Workload-API RPC service + method names. These are
#: protocol-stable since SPIRE 1.x and form the Zone-L contract.
WORKLOAD_API_SERVICE = "SpiffeWorkloadAPI"
WORKLOAD_API_METHOD_FETCH_X509_SVID = "FetchX509SVID"

#: Required gRPC metadata header — the SPIRE-Agent rejects requests
#: that do not carry it (defence-in-depth against accidental cross-
#: process channel reuse).
WORKLOAD_API_SECURITY_HEADER = ("workload.spiffe.io", "true")

#: Soft cap on the SVID-fetch round-trip. The engine emits a WARN
#: audit annotation if the fetch exceeds this; the hard timeout is
#: the caller-supplied ``fetch_timeout_sec`` argument.
SVID_FETCH_SOFT_CAP_SEC: float = 2.0


class SvidFetchError(RuntimeError):
    """Raised when the workload-API socket is unreachable or returns
    an error."""


@dataclass(frozen=True)
class SvidProbeResult:
    """Result of a socket-presence probe.

    - :attr:`socket_present`: True iff the Unix socket file exists.
    - :attr:`socket_connectable`: True iff ``connect()`` returns
      without raising within the probe timeout.
    - :attr:`expected_spiffe_id`: the SPIFFE-ID the engine **expects**
      to be issued for this workload (template-resolved).
    - :attr:`probed_at_utc`: RFC 3339 UTC timestamp of the probe.
    """

    socket_present: bool
    socket_connectable: bool
    expected_spiffe_id: str
    probed_at_utc: str


@dataclass(frozen=True)
class SvidFetchResult:
    """Result of a full SVID-fetch over the Workload-API.

    - :attr:`spiffe_id`: SPIFFE-ID extracted from the leaf certificate
      SubjectAltName (URI form).
    - :attr:`san_uris`: All SAN URIs in the leaf cert (defence-in-depth
      against accidental multi-identity SVIDs).
    - :attr:`not_after_utc`: Leaf certificate notAfter timestamp
      (RFC 3339 UTC).
    - :attr:`bind_state_sha256`: SHA-256 of the leaf-cert DER bytes;
      cheap fingerprint for cross-correlation across audit annotations.
    - :attr:`trust_domain`: The SPIFFE trust domain of the issued ID.
    - :attr:`matches_expected`: True iff :attr:`spiffe_id` equals the
      template-resolved expected SPIFFE-ID for ``(org_id, persona_id)``.
    - :attr:`fetched_at_utc`: RFC 3339 UTC timestamp of the fetch.
    - :attr:`fetch_elapsed_sec`: monotonic round-trip elapsed seconds.
    - :attr:`soft_cap_exceeded`: True iff fetch elapsed exceeded
      :data:`SVID_FETCH_SOFT_CAP_SEC`.
    """

    spiffe_id: str
    san_uris: Tuple[str, ...]
    not_after_utc: str
    bind_state_sha256: str
    trust_domain: str
    matches_expected: bool
    fetched_at_utc: str
    fetch_elapsed_sec: float
    soft_cap_exceeded: bool


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_socket_path(env: Optional[dict] = None) -> str:
    """Resolve the workload-API socket path from env or default.

    The env var SPIFFE_ENDPOINT_SOCKET is a URI of the form
    ``unix:///path/to/sock``; we strip the ``unix://`` prefix.
    """
    if env is None:
        env = dict(os.environ)
    raw = env.get(SPIFFE_ENDPOINT_SOCKET_ENV)
    if not raw:
        return DEFAULT_WORKLOAD_API_SOCKET_PATH
    if raw.startswith("unix://"):
        return raw[len("unix://"):]
    return raw


def expected_spiffe_id_for(org_id: str, persona_id: str) -> str:
    """Resolve the SPIFFE-ID template for ``(org_id, persona_id)``."""
    return SPIFFE_ID_TEMPLATE.format(org_id=org_id, persona_id=persona_id)


def probe_workload_api_socket(
    org_id: str,
    persona_id: str,
    *,
    socket_path: Optional[str] = None,
    timeout_sec: float = 1.0,
) -> SvidProbeResult:
    """Probe the workload-API socket presence and connectability.

    Sprint-Pengine-9: still the boot-gate path. Engine boot runs this
    probe to fail fast on a missing SPIRE-Agent before attempting the
    gRPC SVID fetch.
    """
    path = socket_path or resolve_socket_path()
    p = Path(path)
    present = p.exists()
    connectable = False
    if present:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout_sec)
            s.connect(path)
            connectable = True
            s.close()
        except OSError:
            connectable = False
    return SvidProbeResult(
        socket_present=present,
        socket_connectable=connectable,
        expected_spiffe_id=expected_spiffe_id_for(org_id, persona_id),
        probed_at_utc=_utc_now_rfc3339(),
    )


# ---------------------------------------------------------------------------
# Sprint-Pengine-9 OI-PEFR-2 — full SVID-fetch over gRPC.
# ---------------------------------------------------------------------------


def _parse_leaf_certificate(der_bytes: bytes) -> Tuple[List[str], str, str]:
    """Parse a leaf X.509 certificate (DER form). Returns
    ``(san_uris, not_after_utc, trust_domain)``.

    Uses ``cryptography`` (a top-level wakir-runtime dep). If
    cryptography is unavailable the function raises ImportError up to
    the caller (the engine catches and falls back to socket-probe-only
    mode).
    """
    from cryptography import x509  # type: ignore[import-not-found]
    from cryptography.hazmat.primitives import serialization  # noqa: F401
    from cryptography.x509.oid import ExtensionOID

    cert = x509.load_der_x509_certificate(der_bytes)
    # SubjectAltName -> URI list.
    san_uris: List[str] = []
    try:
        san_ext = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        for uri in san_ext.value.get_values_for_type(x509.UniformResourceIdentifier):
            san_uris.append(uri)
    except x509.ExtensionNotFound:
        san_uris = []
    # notAfter -> RFC 3339 UTC.
    not_after = cert.not_valid_after_utc
    not_after_utc = not_after.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Trust domain — first SAN URI's host part.
    trust_domain = ""
    for uri in san_uris:
        if uri.startswith("spiffe://"):
            tail = uri[len("spiffe://"):]
            slash = tail.find("/")
            trust_domain = tail if slash < 0 else tail[:slash]
            break
    return san_uris, not_after_utc, trust_domain


class WorkloadApiClient:
    """Engine-side SPIFFE Workload-API gRPC client (OI-PEFR-2).

    Async-first. The constructor takes a ``socket_path`` (the
    bind-mounted UDS) and optional factory hooks for hermetic tests:

    - ``channel_factory(socket_path) -> aio.Channel``
    - ``stub_factory(channel) -> StubLike`` where ``StubLike`` exposes
      ``FetchX509SVID(request, metadata=...) -> AsyncIterator[reply]``
      and each reply carries ``svids`` (list) with ``x509_svid`` bytes
      (leaf DER) and ``spiffe_id`` (string).

    Hermetic-test posture: tests pass a stub channel + stub stub; no
    grpcio import happens. Production builds use grpcio.aio +
    a generated ``SpiffeWorkloadAPIStub`` from ``workload.proto``.
    For Sprint-Pengine-9 we ship a *minimal* protobuf surface
    (see ``_workload_api_pb2_minimal.py``) that mirrors the v0.4
    SPIRE proto fields we consume. A future Sprint-Pengine-10
    swap-in of the auto-generated ``workload_pb2`` is a drop-in:
    the field names align byte-for-byte.
    """

    def __init__(
        self,
        socket_path: str,
        *,
        fetch_timeout_sec: float = 5.0,
        channel_factory: Optional[Callable[[str], Any]] = None,
        stub_factory: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._socket_path = socket_path
        self._fetch_timeout_sec = fetch_timeout_sec
        self._channel_factory = channel_factory
        self._stub_factory = stub_factory
        self._channel: Any = None
        self._stub: Any = None

    async def __aenter__(self) -> "WorkloadApiClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._channel is not None:
            return
        if self._channel_factory is not None:
            self._channel = self._channel_factory(self._socket_path)
        else:
            try:
                import grpc  # type: ignore[import-not-found]
                from grpc import aio as grpc_aio  # type: ignore[import-not-found]
            except ImportError as exc:
                raise SvidFetchError(
                    "grpcio wheel missing; cannot construct "
                    "WorkloadApiClient. Engine will fence to socket-"
                    "probe-only mode. Remediation: rebuild the wakir-"
                    "persona-engine image with the persona-engine-"
                    "runtime pyproject extra (adds grpcio>=1.62)."
                ) from exc
            self._channel = grpc_aio.insecure_channel(
                f"unix://{self._socket_path}"
            )
        if self._stub_factory is not None:
            self._stub = self._stub_factory(self._channel)
        else:
            from . import _workload_api_pb2_minimal as wpb  # type: ignore

            self._stub = wpb.SpiffeWorkloadAPIStub(self._channel)

    async def close(self) -> None:
        if self._channel is None:
            return
        try:
            close = getattr(self._channel, "close", None)
            if close is not None:
                res = close()
                if asyncio.iscoroutine(res):
                    await res
        finally:
            self._channel = None
            self._stub = None

    async def fetch_x509_svid(
        self,
        *,
        org_id: str,
        persona_id: str,
    ) -> SvidFetchResult:
        """Run the FetchX509SVID RPC and return a structured result.

        The Workload-API ``FetchX509SVID`` is a server-streaming RPC
        that emits one reply per identity refresh; we consume the
        FIRST reply (the initial issuance), close the stream, and
        return.
        """
        if self._stub is None:
            raise SvidFetchError(
                "WorkloadApiClient not connected; call connect() first"
            )
        from . import _workload_api_pb2_minimal as wpb  # type: ignore

        start = time.monotonic()
        metadata = [WORKLOAD_API_SECURITY_HEADER]
        stream = self._stub.FetchX509SVID(
            wpb.X509SVIDRequest(),
            metadata=metadata,
        )
        first_reply = await asyncio.wait_for(
            _consume_first(stream),
            timeout=self._fetch_timeout_sec,
        )
        elapsed = time.monotonic() - start
        if first_reply is None or not getattr(first_reply, "svids", None):
            raise SvidFetchError(
                "FetchX509SVID stream produced no SVID in first reply"
            )
        svid0 = first_reply.svids[0]
        leaf_der = bytes(getattr(svid0, "x509_svid", b""))
        if not leaf_der:
            raise SvidFetchError("first SVID has empty x509_svid bytes")
        spiffe_id = str(getattr(svid0, "spiffe_id", ""))
        san_uris, not_after_utc, trust_domain = _parse_leaf_certificate(leaf_der)
        bind_state = "sha256:" + hashlib.sha256(leaf_der).hexdigest()
        expected = expected_spiffe_id_for(org_id, persona_id)
        return SvidFetchResult(
            spiffe_id=spiffe_id,
            san_uris=tuple(san_uris),
            not_after_utc=not_after_utc,
            bind_state_sha256=bind_state,
            trust_domain=trust_domain,
            matches_expected=(spiffe_id == expected),
            fetched_at_utc=_utc_now_rfc3339(),
            fetch_elapsed_sec=elapsed,
            soft_cap_exceeded=elapsed > SVID_FETCH_SOFT_CAP_SEC,
        )


async def _consume_first(stream: Any) -> Any:
    """Pull the first reply from a server-streaming gRPC call.

    Works against both grpc.aio (async-iterator) and hermetic stubs
    that expose ``__aiter__``.
    """
    if hasattr(stream, "__aiter__"):
        async for reply in stream:
            return reply
        return None
    # Some stubs expose .read() (parity with grpc.aio.StreamUnaryCall).
    if hasattr(stream, "read"):
        return await stream.read()
    raise SvidFetchError("stream object exposes neither __aiter__ nor read()")


async def fetch_workload_svid(
    org_id: str,
    persona_id: str,
    *,
    socket_path: Optional[str] = None,
    fetch_timeout_sec: float = 5.0,
    channel_factory: Optional[Callable[[str], Any]] = None,
    stub_factory: Optional[Callable[[Any], Any]] = None,
) -> SvidFetchResult:
    """Convenience helper: open client, fetch one SVID, close client."""
    path = socket_path or resolve_socket_path()
    async with WorkloadApiClient(
        socket_path=path,
        fetch_timeout_sec=fetch_timeout_sec,
        channel_factory=channel_factory,
        stub_factory=stub_factory,
    ) as client:
        return await client.fetch_x509_svid(
            org_id=org_id,
            persona_id=persona_id,
        )
