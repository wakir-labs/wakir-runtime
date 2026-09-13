# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# This file is part of the Wakir Persona-Engine real-implementation
# module (image tag ``0.2.0-pilot``). Licensed
# under the Business Source License 1.1; see ../LICENSE-BSL.md for
# the canonical wirelang-package header. Change Date: four (4) years
# after first publication; Change License: Apache 2.0.
"""Wakir persona-engine real implementation.

This package is the **production** persona-engine implementation
that swaps in for the substrate-stub binary shipped at image tag
``0.1.0-pilot`` (the WAT side). The stub satisfies the
Quadlet CLI contract (``spawn`` / ``healthcheck`` / ``version``)
but emits no Engineering output; this package emits real output and
drives the six deferred surfaces from the stub's startup
roll-call:

1. NATS-KV state-pack persistence (``state_backing``).
2. SPIRE Workload-API SVID fetch (``svid_workload_identity``).
3. Spawn-session lifecycle state-machine (``lifecycle_state_machine``).
4. Persona canonical-form / V-907 pin-hash verification
   (``v907_verify``).
5. Recovery-workflow R1..R4 (``recovery_workflow``).
6. Doppelbetrieb-shadow output bridging (``bridge_audit_writer``).

Public API surface
------------------

- :class:`PersonaEngine`: the spawn-session orchestrator. Consumes
  the env-var contract documented in
  ``wirelang/specs/persona-engine-format-spec.md`` §"Env var
  contract" plus the bind-mounted persona-definition (axis-A) and
  the optional wakir-persona-v1 (axis-C) JSON document.
- :class:`LifecycleStateMachine`: spec §3.3 envelope; six states,
  nine valid transitions, invalid-transition errors raise.
- :func:`run_spawn`: subcommand entry point invoked by
  ``persona-engine spawn``.
- :func:`run_healthcheck`: subcommand entry point invoked by
  ``persona-engine healthcheck`` (Quadlet ``HealthCmd=`` line).
- :func:`run_version`: subcommand entry point invoked by
  ``persona-engine version``.

Spec anchor
-----------

``wirelang/specs/persona-engine-format-spec.md`` v1.3
(..).

Lazy-import discipline (parity with ``wirelang.persona``)
---------------------------------------------------------

This package follows the PEP-562 pattern:
no eager imports of ``nats-py`` or ``cryptography`` at top level.
Sub-modules that bind those wheels (``state_backing`` for
NATS-KV, ``svid_workload_identity`` for the SPIFFE Workload-API)
import the wheels at call time inside try/except shims so the
package itself stays importable on the constrained
``wakir-provisioner`` wheel set (parity with the
provisioner BUCKET_FAMILIES probe-pattern).
"""

from __future__ import annotations

from .__version__ import __version__  # canonical anchor

__all__ = [
    "__version__",
    "PersonaEngine",
    "AsyncPersonaEngine",
    "LifecycleStateMachine",
    "DrillScheduler",
    "MigrateVersionWorkflow",
    "run_spawn",
    "run_healthcheck",
    "run_version",
]


def __getattr__(name: str):  # PEP-562 lazy attribute access
    if name == "PersonaEngine":
        from .engine import PersonaEngine

        return PersonaEngine
    if name == "AsyncPersonaEngine":
        from .engine_async import AsyncPersonaEngine

        return AsyncPersonaEngine
    if name == "LifecycleStateMachine":
        from .lifecycle_state_machine import LifecycleStateMachine

        return LifecycleStateMachine
    if name == "DrillScheduler":
        from .drill_scheduler import DrillScheduler

        return DrillScheduler
    if name == "MigrateVersionWorkflow":
        from .migrate_version import MigrateVersionWorkflow

        return MigrateVersionWorkflow
    if name == "run_spawn":
        from .cli import run_spawn

        return run_spawn
    if name == "run_healthcheck":
        from .cli import run_healthcheck

        return run_healthcheck
    if name == "run_version":
        from .cli import run_version

        return run_version
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
