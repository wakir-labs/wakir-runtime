# SPDX-License-Identifier: Apache-2.0
"""Real SPIFFE Workload API adapter — wirelang-side surface mirror stub.

Phase: Phase-2 Sprint-6 Tag-7 (Adapter-Slot-2 mirror stub).
Status: surface-level Protocol-adoption stub WITHOUT functional
``spiffe``-PyPI-backed implementation. The actual upstream-backed
implementation is gated on:

1. Operator-side environment flag ``WAKIR_SPIRE_LIVE=1`` (see
   "Gating" below). The adapter constructor refuses instantiation
   when the flag is absent so a misconfigured persona-container
   cannot accidentally hit a live SPIRE agent during unit tests.
2. Kai's DevOps-track SPIRE-server / SPIRE-agent / NATS-JWT
   ``user_jwt_cb`` integration landing at Phase-2c (Sprint-6 Tag-7+
   or later — see ``wirelang/specs/identity-substrate.md`` §5.7 for
   the wirelang-side surface and Kai's runbook for the operator-side
   topology).
3. Upstream ``spiffe`` PyPI package being installed in the
   persona-container environment. The adapter does NOT depend on
   ``spiffe`` at import time (lazy import inside the constructor)
   so the wirelang test suite stays hermetic — a worktree without
   ``spiffe`` installed can still import this module and run the
   non-live tests.

Purpose
=======

Sprint-6 Tag-4..5 introduced the :class:`SpiffeWorkloadApiAdapter`
Protocol surface and the deterministic in-process
:class:`MockSpiffeWorkloadApiAdapter`. This Tag-7 mirror stub adds
the **second adapter slot** that will eventually carry the
upstream-``spiffe``-PyPI-backed implementation, paired with Kai's
SPIRE-sidecar work at Phase-2c+ (Sprint-7 or later).

The stub deliberately:

- Adopts the Tag-4 Protocol surface verbatim
  (``fetch_jwt_svid`` / ``fetch_x509_svid``) so a downstream type
  checker can verify protocol-conformance.
- Carries the same four-class error hierarchy
  (``SpiffeAdapterError`` / ``SpiffeAdapterUnavailable`` /
  ``SpiffeAdapterAttestationFailed`` / ``SpiffeAdapterAudienceRejected``)
  via re-export from :mod:`wirelang.adapters.spiffe_workload_api`.
- Refuses to dispatch real Workload-API calls in this Tag-7 box —
  all method bodies raise :class:`NotImplementedError` with a clear
  "Tag-7+ / Phase-2c" marker pointing at the implementation slot
  and the cross-reference to Kai's track.
- Carries explicit ``TODO(reza-tag-7-plus)`` markers at every site
  where the real upstream call will land, so the implementation
  slot is searchable and audit-able from grep alone.

Gating
======

The constructor refuses instantiation unless the environment
variable ``WAKIR_SPIRE_LIVE`` is set to ``"1"``. This is a
defence-in-depth measure: even after the implementation lands at
Phase-2c, a misconfigured persona-container that does NOT have a
SPIRE agent available will get a clean import-time error rather
than a runtime ``ConnectionRefusedError`` on the first
``fetch_jwt_svid`` call. The gate is implemented via
``os.environ.get("WAKIR_SPIRE_LIVE")`` — no ``dotenv``-style file
loading, no implicit defaults; explicit-or-refused.

Tests that wish to exercise the real-adapter Protocol-conformance
path WITHOUT a live SPIRE agent can set the flag and rely on the
``NotImplementedError`` raise to confirm the adapter is wired
correctly into the orchestrator's adapter-selection codepath.

TODO list (cross-reference to Kai's SPIRE-sidecar track)
========================================================

- **TODO(reza-tag-7-plus)** — Wire ``fetch_jwt_svid(audience)`` to
  the upstream ``spiffe.workload_api.WorkloadApiClient.fetch_jwt_svid()``
  call. The upstream method returns a
  ``spiffe.svid.jwt_svid.JwtSvid`` value object; this adapter MUST
  translate it into the wirelang-owned :class:`JwtSvid` shape (NOT
  re-export the upstream type). Per
  ``wirelang/specs/identity-substrate.md`` §5.5, persona-container
  code MUST NOT depend on upstream value-object types.

- **TODO(reza-tag-7-plus)** — Wire ``fetch_x509_svid()`` to the
  upstream ``WorkloadApiClient.fetch_x509_svid()`` call. The
  X509-SVID path is Phase-2c+ surface (the Tag-4 stub already has
  the value-object shape, but the mock at Tag-5 leaves it
  ``NotImplementedError``).

- **TODO(reza-tag-7-plus)** — Map upstream exceptions
  (``spiffe.errors.X509SvidError``, ``WorkloadApiError``,
  socket-level ``ConnectionRefusedError``, etc.) onto the four
  wirelang error-classes per the Z-A-Ack 2026-05-11 §7
  containment contract.

- **TODO(reza-tag-7-plus)** — Inject the workload-socket path
  through the constructor (default-pinned to the SPIRE-agent
  convention ``/tmp/spire-agent/public/api.sock`` but
  operator-overridable for Kai's containerised topology).

- **TODO(kai-cross-reference)** — The wirelang-side adapter
  expects Kai's SPIRE-sidecar to expose the Workload-API socket at
  the path supplied via the constructor. See Kai's
  Phase-2.3+ runbook for the sidecar topology and the
  workload-attestation policy that maps the persona-container's
  Kubernetes / podman attributes onto a SPIFFE-ID.

- **TODO(reza-tag-7-plus)** — Add a Phase-2c
  ``test_real_spiffe_workload_api_adapter.py`` test module that
  exercises the gate-flag refusal path (``WAKIR_SPIRE_LIVE`` not
  set ⇒ ``RuntimeError`` on construction) and the
  ``NotImplementedError`` raise on each method when the gate IS
  set but the upstream library is absent.

- **TODO(reza-tag-7-plus)** — Coordinate the audience-validation
  semantics with Kai. The Tag-4 mock raises
  :class:`SpiffeAdapterAudienceRejected` when the operator
  configures ``permitted_audiences``; the real adapter MUST mirror
  this contract by validating the returned JWT-SVID's ``aud``
  claim against the requested audience before returning.

Cross-references
================

- ``wirelang/specs/identity-substrate.md`` §5.5 — adapter-layer
  indirection constraint.
- ``wirelang/specs/identity-substrate.md`` §5.7 — implementation
  cross-references (wirelang-side stub, Kai DevOps-track owner-items,
  Phase-3 wirelang-roadmap slots).
- Z-A-Ack 2026-05-11 §3 — PyPI-package-name correction (``spiffe``,
  NOT ``py-spiffe``).
- Z-A-Ack 2026-05-11 §7 — adapter-layer agreement; upstream
  breaking changes are Z-A re-consensus triggers.
- :mod:`wirelang.adapters.spiffe_workload_api` — Tag-4 Protocol
  surface and Tag-5 mock implementation that this stub mirrors.
- Kai's Phase-2.3+ SPIRE-sidecar runbook (operator-side topology).
"""

from __future__ import annotations

import os
from typing import Optional

from wirelang.adapters.spiffe_workload_api import (
    JwtSvid,
    SpiffeAdapterAttestationFailed,
    SpiffeAdapterAudienceRejected,
    SpiffeAdapterError,
    SpiffeAdapterUnavailable,
    SpiffeWorkloadApiAdapter,
    X509Svid,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


WAKIR_SPIRE_LIVE_ENV = "WAKIR_SPIRE_LIVE"
"""Environment variable that gates real-adapter instantiation.

The constructor refuses instantiation unless this variable is set
to the literal string ``"1"``. Any other value (including
``"true"``, ``"yes"``, empty string, or absence) keeps the gate
closed.
"""

DEFAULT_WORKLOAD_API_SOCKET = "/tmp/spire-agent/public/api.sock"
"""Default Workload-API socket path (SPIRE-agent convention).

Operators with a containerised SPIRE-sidecar topology (Kai's
Phase-2.3+ track) MUST override this through the constructor.
"""


# ---------------------------------------------------------------------------
# Real adapter (Tag-7 stub; functional impl deferred to Phase-2c)
# ---------------------------------------------------------------------------


class RealSpiffeWorkloadApiAdapter:
    """Real upstream-``spiffe``-PyPI-backed SPIFFE Workload API adapter.

    Phase-2 Sprint-6 Tag-7 — mirror-stub for the Tag-4 Protocol
    surface. Functional implementation deferred to Phase-2c (paired
    with Kai's SPIRE-sidecar work). The constructor refuses
    instantiation unless ``WAKIR_SPIRE_LIVE=1`` is set in the
    process environment; method bodies raise
    :class:`NotImplementedError` with a Tag-7+ marker.

    Type-conforming to :class:`SpiffeWorkloadApiAdapter` Protocol
    (verified at import time via the static-type check below;
    runtime ``isinstance`` against ``Protocol`` is NOT supported by
    Python before 3.12 without ``runtime_checkable`` — the explicit
    method signatures here suffice for static checkers).

    Parameters
    ----------

    workload_socket_path:
        Filesystem path to the SPIRE-agent's Workload-API socket.
        Defaults to :data:`DEFAULT_WORKLOAD_API_SOCKET`. Operators
        with a containerised topology MUST override.

    Raises
    ------

    RuntimeError:
        If ``WAKIR_SPIRE_LIVE`` is not set to ``"1"`` in the
        environment. The error message includes a clear pointer to
        the environment-flag contract.
    """

    def __init__(
        self,
        *,
        workload_socket_path: str = DEFAULT_WORKLOAD_API_SOCKET,
    ) -> None:
        gate_value = os.environ.get(WAKIR_SPIRE_LIVE_ENV)
        if gate_value != "1":
            raise RuntimeError(
                f"{type(self).__name__} construction refused: "
                f"environment variable {WAKIR_SPIRE_LIVE_ENV!r} is "
                f"not set to '1' (current value: {gate_value!r}). "
                f"Set {WAKIR_SPIRE_LIVE_ENV}=1 to opt in to the "
                f"real Workload-API path; this gate is defence-in-"
                f"depth so a misconfigured persona-container cannot "
                f"accidentally hit a live SPIRE agent during unit "
                f"tests. See "
                f"wirelang/adapters/real_spiffe_workload_api.py "
                f"module docstring for the full contract."
            )
        self._workload_socket_path = workload_socket_path
        # TODO(reza-tag-7-plus): lazy-import the upstream ``spiffe``
        # PyPI package here and construct a
        # ``spiffe.workload_api.WorkloadApiClient`` instance bound
        # to ``self._workload_socket_path``. Keep the import inside
        # ``__init__`` so the wirelang test suite stays hermetic
        # (importable without ``spiffe`` installed) and so a
        # ``ModuleNotFoundError`` surfaces at construction time
        # (clear failure) rather than on the first method call
        # (confusing failure).
        self._client = None  # placeholder for upstream client handle.

    @property
    def workload_socket_path(self) -> str:
        """Read-only accessor for the configured Workload-API socket."""
        return self._workload_socket_path

    async def fetch_jwt_svid(
        self,
        audience: str,
        *,
        extra_audiences: Optional[tuple[str, ...]] = None,
        spiffe_id: Optional[str] = None,
    ) -> JwtSvid:
        """Fetch a JWT-SVID for the given audience.

        Sprint-6 Tag-7 stub: raises :class:`NotImplementedError`.
        Implementation deferred to Phase-2c paired with Kai's
        SPIRE-sidecar integration.

        TODO(reza-tag-7-plus): wire the upstream
        ``WorkloadApiClient.fetch_jwt_svid(audience, ...)`` call;
        translate the returned ``spiffe.svid.jwt_svid.JwtSvid`` into
        the wirelang-owned :class:`JwtSvid` shape; map upstream
        exceptions onto the four wirelang error-classes per the
        Z-A-Ack 2026-05-11 §7 containment contract.
        """
        raise NotImplementedError(
            "RealSpiffeWorkloadApiAdapter.fetch_jwt_svid is not yet "
            "implemented. Phase-2c surface; paired with Kai's "
            "SPIRE-sidecar work at Sprint-6 Tag-7+ / Phase-2c. See "
            "wirelang/adapters/real_spiffe_workload_api.py module "
            "docstring TODO list and "
            "wirelang/specs/identity-substrate.md §5.7."
        )

    async def fetch_x509_svid(
        self,
        *,
        spiffe_id: Optional[str] = None,
    ) -> X509Svid:
        """Fetch an X509-SVID.

        Sprint-6 Tag-7 stub: raises :class:`NotImplementedError`.
        Implementation deferred to Phase-2c.

        TODO(reza-tag-7-plus): wire the upstream
        ``WorkloadApiClient.fetch_x509_svid(...)`` call; translate
        the returned upstream X509-SVID into the wirelang-owned
        :class:`X509Svid` shape.
        """
        raise NotImplementedError(
            "RealSpiffeWorkloadApiAdapter.fetch_x509_svid is not yet "
            "implemented. Phase-2c surface; paired with Kai's "
            "SPIRE-sidecar work."
        )

    async def close(self) -> None:
        """Release the upstream Workload-API client.

        Sprint-6 Tag-7 stub: no-op (no underlying client to release).

        TODO(reza-tag-7-plus): call the upstream client's
        ``close()`` / ``__aexit__`` path here so persona-container
        lifecycle code can manage adapter resources deterministically.
        """
        # No-op until the upstream client is wired in.
        return None


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = [
    "DEFAULT_WORKLOAD_API_SOCKET",
    "RealSpiffeWorkloadApiAdapter",
    "WAKIR_SPIRE_LIVE_ENV",
]


# ---------------------------------------------------------------------------
# Static Protocol-conformance check (compile-time, no runtime cost)
# ---------------------------------------------------------------------------

# This assignment is type-checked by mypy / pyright at static analysis
# time: it asserts that RealSpiffeWorkloadApiAdapter conforms to the
# SpiffeWorkloadApiAdapter Protocol surface. The runtime behaviour is a
# no-op (assignment to a private name). If a future refactor renames or
# removes a Protocol method, mypy will flag this line.

_RealSpiffeWorkloadApiAdapter_protocol_conformance_check: type[
    SpiffeWorkloadApiAdapter
] = RealSpiffeWorkloadApiAdapter  # type: ignore[assignment]
