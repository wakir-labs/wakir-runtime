# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""SPIFFE Workload-API SVID fetch (Zone-L, spec §3.7.4 R3).

Engine-side caller for the SPIRE Workload-API socket bind-mounted
into the persona-container at ``/run/spire/agent-sockets/api.sock``
(Quadlet ``Volume=wakir-spire-agent-sockets.volume:...``).

Posture
-------

The Workload-API protocol is gRPC-over-Unix-socket
(``SPIFFE_X509_SVID`` service). A full async grpc-go-style binding
is **deferred to Sprint-Pengine-9** (it requires the ``grpcio`` +
``protobuf`` wheel set, ~80MB of native code). For ``0.2.0-pilot``
this module provides:

1. **Socket-presence probe.** Detect whether the bind-mounted socket
   path exists and is connectable (``socket.connect()`` with a small
   timeout). This is sufficient to gate the engine startup on the
   SPIRE-Agent sidecar reaching ``ready``; the actual SVID fetch is
   the v0.3.0-pilot surface.
2. **SVID-cache structured-log envelope.** When (later) a fetched
   SVID lands, the engine writes an audit annotation with the
   SPIFFE-ID, the certificate-not-after timestamp, and a bind-state
   hash. The envelope shape is fixed here so the wirelang.federation
   bridge (Reza-domain) can consume it.

Zone-L cross-review
-------------------

Reza is Identity-Substrate owner. The socket-path constant
``DEFAULT_WORKLOAD_API_SOCKET_PATH`` mirrors the SPIRE-Agent
Quadlet output; the SPIFFE-ID expectation
``spiffe://wakir.example/persona/<persona_id>`` is the operational
default (Sprint-9 Tag-5 substrate). Zone-L touch is the constant
inventory below; Sprint-Pengine-9 adds the grpc binding.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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

    This is the v0.2.0-pilot SVID-substrate gate. Full SVID-fetch
    over gRPC lands on the Sprint-Pengine-9 axis (requires grpcio
    wheel).
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
