# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Skizze-internal constants for the SPIFFE/SPIRE Z-A JWT-SVID
# Container-Identity-Skizze (Phase-2 Sprint-4 Tag-6).
#
# This module is **Skizze-Validations-Substanz**. It does not
# implement a SPIRE client, an attestor, or a NATS-JWT-Auth adapter.
# It defines the format constants proposed in
# ``docs/spiffe-z-a-jwt-svid-skizze.md`` §3.1, §3.2, §2 (Trust-Domain)
# and §4.1 (Workload-API socket path) as testable Python constants.
#
# Purpose: when the Cross-Review Zone A consensus later overrides one
# of these proposals (different trust-domain format, different
# persona-hash path-component length, different socket path), the
# hermetic tests in ``tests/orchestrator/test_spiffe_z_a_skizze.py``
# break visibly and force a co-edit. This is the same drift-detection
# discipline the dual-anchor parity tests use for the orchestrator-vs-
# Wirelang bucket-config mirror.
#
# Cross-Review-Zone-A Status (Tag-6 authoring stamp):
# - Konsens not yet recorded; Aisha-protocol pending.
# - All constants here are *proposals*, not decisions.
#
# Reference: docs/spiffe-z-a-jwt-svid-skizze.md (Tag-6).
"""SPIFFE Z-A skizze format constants (Phase-2 Sprint-4 Tag-6)."""

from __future__ import annotations

import re
from typing import Final


# ---------------------------------------------------------------------
# §2 — Trust-Domain proposal
# ---------------------------------------------------------------------

#: Phase-2 single-node trust-domain proposal (Skizze §2).
TRUST_DOMAIN_PHASE_2: Final[str] = "wakir.local"

#: Phase-3a federation-ready trust-domain template (Skizze §2 row 3a).
#: ``{org_id}`` is substituted at SPIRE-server-config render time.
TRUST_DOMAIN_PHASE_3A_TEMPLATE: Final[str] = "{org_id}.wakir.dev"


# ---------------------------------------------------------------------
# §3.1 — Persona-Container SPIFFE-ID pattern
# ---------------------------------------------------------------------

#: Length of the persona-hash component embedded into the SPIFFE-ID
#: path. Skizze §3.1 proposal: 12 lower-case hex chars (48 bits).
#: Final length is a Z-A decision-slot.
PERSONA_HASH_SHORT_LEN: Final[int] = 12

#: Regex for the persona-container SPIFFE-ID path-only form
#: (trust-domain stripped). Matches ``/agent/<persona-slug>/<persona-hash-12>``.
#:
#: - ``<persona-slug>``: lower-case ASCII letters, 2..16 chars
#:   (per ADR-0032 klar-slug pattern: ``mira``, ``tomas``, ``reza``,
#:   ``kai``, ``aisha``, etc.).
#: - ``<persona-hash-12>``: exactly ``PERSONA_HASH_SHORT_LEN`` lower-case
#:   hex chars.
PERSONA_ID_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^/agent/(?P<slug>[a-z]{2,16})/(?P<hash>[0-9a-f]{12})$"
)

#: Full-form SPIFFE-ID regex (trust-domain + path). Used to validate
#: a rendered SPIFFE-ID string end-to-end.
PERSONA_ID_FULL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^spiffe://(?P<trust>[a-z0-9.\-]+)/agent/"
    r"(?P<slug>[a-z]{2,16})/(?P<hash>[0-9a-f]{12})$"
)


# ---------------------------------------------------------------------
# §3.2 — Substrate-service SPIFFE-ID pattern
# ---------------------------------------------------------------------

#: Regex for the substrate-service SPIFFE-ID path-only form.
#: Matches ``/service/<service-name>``.
#:
#: - ``<service-name>``: lower-case ASCII letters, digits, hyphens,
#:   2..32 chars (e.g. ``nats``, ``orchestrator``, ``spire-server``,
#:   ``health-check-cron``).
SERVICE_ID_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^/service/(?P<name>[a-z][a-z0-9\-]{1,31})$"
)

#: Known Phase-2 substrate service names (Skizze §3.2 table).
KNOWN_PHASE_2_SERVICES: Final[frozenset[str]] = frozenset(
    {
        "nats",
        "orchestrator",
        "spire-server",
        "health-check-cron",
    }
)


# ---------------------------------------------------------------------
# §4.1 — Workload-API socket path
# ---------------------------------------------------------------------

#: Phase-2 default Workload-API Unix-socket path inside a persona
#: container (Skizze §4.1 diagram).
WORKLOAD_API_SOCKET_PATH_PHASE_2: Final[str] = "/run/spire/sockets/agent.sock"

#: Environment variable name that may override the socket path at
#: runtime (Phase-3a federation deployments may relocate the socket
#: for multi-tenancy isolation).
WORKLOAD_API_SOCKET_ENV_VAR: Final[str] = "SPIFFE_ENDPOINT_SOCKET"


# ---------------------------------------------------------------------
# §4.3 — JWT-SVID claims (proposal)
# ---------------------------------------------------------------------

#: Default JWT-SVID time-to-live for Phase-2 (15 minutes; SPIRE-default,
#: boring-tech-bias). The SPIRE-server-config in §5 binds this to
#: ``default_jwt_svid_ttl = "15m"``.
JWT_SVID_TTL_SECONDS_PHASE_2: Final[int] = 15 * 60

#: NATS audience the SVID is requested for in Phase-2 (single-node).
NATS_JWT_AUDIENCE_PHASE_2: Final[str] = "nats://wakir.local"
