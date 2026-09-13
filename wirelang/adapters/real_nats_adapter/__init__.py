# SPDX-License-Identifier: Apache-2.0
"""Real NATS adapter — wirelang-side surface mirror for Phase-2c.

Scope: RealAdapter mirror, paired with SpiffeCrossTrustDomainBridge
and MultiOrgAttestationNatsKvBackend.
Status: Live-NATS-Connection-fähig (best-effort lokal) mit
Mock-Mirror als deterministic Test-Pfad. Operator-Hand-SPIRE-Substrate
ist als blockiert akzeptiert — Fallback auf JWT-Auth-Mock wenn die
SPIRE-Workload-API nicht erreichbar ist
(``SPIRE_AGENT_SOCKET=none`` oder Workload-API-Endpoint-Fehler).

Purpose
=======

Das bisherige Wirelang-Substrate adressierte NATS-KV-Backends
(capability-policy, multi-org-attestation,
federation-route-registry) ausschliesslich gegen ein
Mock-Backend, das in-memory Bucket-State hält. Dieses Modul bildet
den **Slot-2 RealAdapter-Mirror** — die wirelang-Seite einer
echten NATS-Live-Connection — analog zum
:mod:`wirelang.adapters.real_spiffe_workload_api` Mirror-Stub.

Im Gegensatz zum SPIRE-Stub liefert dieses Modul eine **funktionale
Live-Adapter-Implementierung**, weil die nats-py-Lib in der
Persona-Container-Umgebung verfügbar ist und localhost:4222 ein
zumutbarer Operator-Hand-Endpunkt ist (vs. SPIRE-Workload-API, die
einen kompletten SPIRE-Server + Agent + Workload-Attestation-Policy
braucht).

Drei Substanz-Schichten:

1. :class:`NatsConnectionAdapter` Protocol-Surface — die wirelang-
   gehaltene stable Surface über ``nats-py`` ``Client``.
2. :class:`MockNatsConnectionAdapter` — deterministic in-process
   Mock, hermetic, no network. Pattern-Mirror auf
   :class:`MockSpiffeWorkloadApiAdapter`.
3. :class:`RealNatsConnectionAdapter` — Live-Adapter, lazy-import
   von ``nats.aio.client``, mit
   :class:`NatsAdapterUnavailable`-Mapping auf socket-level Errors.

Operator-Hand-SPIRE-Substrate-Block
====================================

Das SpiffeCrossTrustDomainBridge-Pattern erwartet
JWT-SVID-Auth gegenüber NATS via ``user_jwt_cb`` (DevOps track).
Die SPIRE-Workload-API-Erreichbarkeit ist Operator-Hand-Fedora-Host-
gated (Milestone M-2). Dieser Adapter folgt der
**SPIRE-Fallback-Policy**:

- Wenn ``SPIRE_AGENT_SOCKET`` als URI gesetzt ist UND erreichbar:
  Live-SPIFFE-JWT-Pfad (Phase-2c+, currently not implemented in
  this module — delegiert an :mod:`real_spiffe_workload_api`).
- Wenn ``SPIRE_AGENT_SOCKET=none`` ODER nicht gesetzt:
  Fallback auf JWT-Auth-Mock (operator-side acceptable for
  development; production NATS-Cluster wird per DevOps track
  später auf SPIRE-Live umgestellt).
- Status-Surface ``status()`` markiert den aktuellen Auth-Mode als
  ``"live-spiffe"`` / ``"mock-jwt"`` / ``"no-auth"``, sodass der
  Persona-Container den Mode auditieren kann.

Live-Connection-Gating
======================

Der Live-Adapter verbindet sich gegen ``WIRELANG_NATS_URL``
(Default ``nats://localhost:4222``). Wenn die NATS-Server nicht
erreichbar ist, raised :meth:`RealNatsConnectionAdapter.connect`
:class:`NatsAdapterUnavailable` — der Aufrufer kann darauf reagieren
(Skip-with-Marker im Test, Eskalation in Produktion).

**Sandbox-Boundary:** localhost:4222 ist Operator-Hand-Fedora-Host.
Der Persona-Container darf nicht annehmen, dass NATS verfügbar ist.
Tests gegen den Real-Adapter MÜSSEN den Skip-with-Marker-Pfad
respektieren (siehe :func:`is_nats_reachable`).

Public surface (re-exported from this ``__init__``):

- :class:`NatsConnectionAdapter`
- :class:`MockNatsConnectionAdapter`
- :class:`RealNatsConnectionAdapter`
- :class:`NatsAdapterError`
- :class:`NatsAdapterUnavailable`
- :class:`NatsAdapterAuthenticationError`
- :class:`NatsAdapterStatus`
- :func:`is_nats_reachable`
"""

from __future__ import annotations

from .adapter import (
    MockNatsConnectionAdapter,
    NatsAdapterAuthenticationError,
    NatsAdapterError,
    NatsAdapterStatus,
    NatsAdapterUnavailable,
    NatsConnectionAdapter,
    RealNatsConnectionAdapter,
    is_nats_reachable,
)

__all__ = [
    "MockNatsConnectionAdapter",
    "NatsAdapterAuthenticationError",
    "NatsAdapterError",
    "NatsAdapterStatus",
    "NatsAdapterUnavailable",
    "NatsConnectionAdapter",
    "RealNatsConnectionAdapter",
    "is_nats_reachable",
]
