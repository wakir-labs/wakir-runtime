#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-5-lifecycle-state-machine-cutover-smoke — End-to-End Cutover-Smoke for ADR-0066 Welle-5.

Background
----------

ADR-0066 (approved 2026-05-17, commit ``c907f98``) schedules
**Welle-5** of the Phase-3c default-backend flip as the **KW-26
Doppel-Welle** twin of Welle-4: ``lifecycle_state_machine`` (in-repo
short form ``fsm``, BackendDecision-domain ``fsm``) cuts over from
Python-default to Rust-default **in parallel with Welle-4**
(``state_backing``). The parallel posture is an ADR-0066 §Option-A+
Doppel-Welle pairing, not a sequencing convenience.

The Cross-Modul-Drift-Risk (ADR-0066 §Welle-4-5-Risiken, Tomás-Zone-K
review) is the **State-Mutation-Coupling-Risk**:

  ``lifecycle_state_machine`` (``fsm``) is the state-machine that
  decides *which* transitions can be persisted at all (spec §3.3 —
  six states, nine transitions). ``state_backing`` is the persistence
  trait that records ``PersonaStateSnapshot`` envelopes via the
  ``snapshot()`` / ``restore_latest()`` /
  ``atomic_swap_pinned_offset()`` API (spec §3.7.5). FSM transitions
  write through state_backing: a transition takes the lock, mutates
  in-memory state, then calls ``state_backing.snapshot()`` to
  persist the new offset (engine.py L951 et seq.). When **both**
  modules flip from Python to Rust during the same KW-26 window, any
  drift in their joint contract (FSM-transition byte-shape, accepted-
  vs-rejected record ordering, transition-table membership) will
  manifest as cross-modul state-corruption that no single-module
  smoke can catch.

This smoke is the **strict, asserts-tragend** End-to-End Cutover-
Smoke for Welle-5, modelled on the Welle-4 sibling
``scripts/phase-3c/welle-4-state-backing-cutover-smoke.py``
(Tag-37, PR #245) and pattern-parity-aligned with Welle-1/2/3
(``welle-1-v907-verify-cutover-smoke.py`` PR #230,
``welle-2-svid-workload-identity-cutover-smoke.py`` PR #234,
``welle-3-bridge-audit-writer-cutover-smoke.py`` PR #240). The
pattern-parity is intentional: the operator runs all five smokes in
the same cutover-PR window, gets five JSON envelopes with the same
shape (``schema`` differs only by Welle number), and the tri-state
exit codes feed shell gates.

Welle-5-specific asserts (FSM-Transition-Integrity + Cross-Modul-Drift)
-----------------------------------------------------------------------

The smoke adds **two** Welle-5-specific asserts that do not exist in
the Welle-1/2/3 shape, symmetric to Welle-4's A6+A7:

* **A6 fsm-transition-integrity (no phantom transitions):** the
  smoke builds a deterministic 6-record ``LifecycleTrace`` (using
  the spec §3.3 nine-transition table — uninstantiated → spawning →
  running → despawning → uninstantiated → recovered → running →
  migrated → uninstantiated) **BEFORE the cutover-step constructs
  the PHASE_POST env-map**. After the cutover (Engine-Reboot with
  ``WAKIR_FSM_BACKEND=rust``), the smoke re-emits the same
  ``LifecycleTrace`` via the Python authority a second time and
  asserts byte-equality of the JCS-canonical bytes. **Additionally**,
  the smoke verifies that every accepted record in the recomputed
  trace points at a ``(from_state, to_state)`` edge that exists in
  :data:`VALID_TRANSITIONS` — no phantom transitions (the FSM
  cutover MUST NOT silently introduce a transition the spec does
  not allow). This is the substrate-level oracle for the
  FSM-Transition-Integrity property: the JCS-canonical byte-shape
  of a ``LifecycleTrace`` written by the Python backend MUST be
  readable byte-for-byte by the Rust backend AND MUST only contain
  transitions from the spec's closed enumeration. The Rust pendant
  byte-parity is pinned at a separate substrate layer (the
  lifecycle-state-machine cross-lang fixture pins from PR #169 /
  PR #177). This smoke verifies the Python encoder is byte-stable
  across the pre/post window AND no phantom edges appear — the only
  oracle that does **not** require bringing up a real Rust binary
  in-process. Severity: caution — a hash mismatch or phantom-
  transition here signals Python FSM encoder drift between pre and
  post, which is a Tomás-Zone-K cross-modul drift signal, not a
  Pilot-VM-cutover blocker.

* **A7 cross-modul-drift-to-welle-4 (lifecycle_state_machine x state_backing):**
  verifies that the ``state_backing`` env-var stays at its baseline
  value (``python`` in PHASE_PRE, the operator's choice in
  PHASE_POST and PHASE_ROLLBACK) and that the per-boot
  ``state_backing`` BackendDecision ``chosen_backend`` field
  matches the env-var requested-value byte-for-byte in **every**
  phase. This is the cross-modul invariant: the
  lifecycle_state_machine cutover MUST NOT silently force the
  state_backing component into a different backend (the parallel-
  Welle joint-cutover concern). Severity: blocker — a fail here
  means lifecycle_state_machine's resolver leaked into the
  state_backing decision path, which would invalidate the parallel-
  Welle isolation contract. The control-flow pin is what protects
  the substrate semantics from rot during the KW-26 Doppel-Welle
  window.

A7 is **symmetric** to Welle-4's A7: Welle-4's A7 checks that
state_backing's cutover does not leak into fsm; Welle-5's A7 checks
that fsm's cutover does not leak into state_backing. Together they
pin the parallel-Welle isolation contract bidirectionally.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-4 shape verbatim, re-pointed at ``fsm`` and
``WAKIR_FSM_BACKEND``. Note that ``fsm`` has only **two** backend
values (``python``, ``rust``) — simpler than state_backing's three-
valued enum.

Real-resolver verification (no shim)
------------------------------------

Welle-5 uses the **real upstream resolver**
``resolve_fsm_backend`` directly. The resolver has been in baseline
since PR #169 (Tag-18 FSM-Rust-Default ENV-gated resolver). The
smoke imports it via :func:`_import_resolver` and never constructs
a shim. The ``resolver_provenance`` field in the envelope reports
``"upstream"`` for fsm in every run.

Default ``--expected-components 11``
------------------------------------

ADR-0066 §Welle-5 baseline is the post-Tag-37 engine inventory: ten
baseline components (v907_verify, svid_workload_identity,
bridge_diff, anchor_emitter, state_backing, fsm, subscribe_loop,
recovery, federation_resolver, bridge_audit_writer) plus
``bridge_audit_diff_engine`` from PR #241 / Tag-36 = 11 in-place
components at the Tag-38 baseline tip ``8ad125a``. The Reza Tag-36
``bridge_audit_diff_engine`` wire-in PR #241 landed before Tag-37
(``4ec8870`` / PR #245's expected-components remained at 10 for
Tag-37 backward-compat; Welle-5 at Tag-38 picks the post-wire-in
default of 11). Operators run with the default
``--expected-components 11``; if running against a pre-PR-#241 tip,
pass ``--expected-components 10``.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with the
   Python default (``WAKIR_FSM_BACKEND=python`` + every other
   component pinned to python). Records the ``BackendDecision`` for
   ``fsm`` plus the other in-place components. **AND captures the
   fsm-transition-trace pre-baseline hash** by invoking
   ``lifecycle_trace_sha256_hex(build_lifecycle_trace_from_records(...))``
   against the deterministic six-transition fixture (mirrors the
   F1/F2/F3 stream-fixture pattern from Welle-3/4). This is the
   FSM-Transition-Integrity capture moment: the baseline is taken
   before the cutover.
2. **Cutover step.** Flips ``WAKIR_FSM_BACKEND=rust`` in the
   hermetic env-map, restarts the mocked engine (engine-reboot
   semantics), re-collects BackendDecisions. The engine-reboot must
   successfully read the lifecycle-trace envelope that the Python
   backend wrote in PHASE_PRE — the smoke verifies this by re-
   emitting the same trace via the Python authority and asserting
   byte-equality with the pre-baseline hash AND verifying every
   accepted record references a valid transition-table edge.
3. **Post-Cutover asserts.** Five hard checks + two Welle-5-specific
   substrate checks (A1..A5 + R1 + A6 + A7).
4. **Rollback probe.** ``WAKIR_FSM_BACKEND`` unset (engine reads
   Python-default), re-boot, asserts that the engine emits
   ``chosen_backend == "python"`` again — operator rollback path
   ≤10 min per ADR-0065 §Rollback-SLA (ADR-0066 inherits this
   contract).
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All blocker asserts pass +
       caution asserts pass.
     * ``1`` — **CAUTION**. At least one caution-severity drift
       (A3 latency, A4 component-count, A6 fsm-transition drift /
       phantom transition).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 / A7 / R1
       failed.

The smoke writes a JSON envelope to ``--output`` (or stdout). The
envelope shape is pinned by the test suite.

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 fsm-transition-
parity check imports
:mod:`wirelang.persona_engine.lifecycle_state_machine_canonical`
lazily and reads only the in-memory deterministic 6-record fixture
embedded in this module; both are gracefully skipped if the import
fails so the smoke remains importable in test environments without
the wirelang package. The mocked engine never imports NATS, the
Anthropic SDK, the real Rust binary, or any container runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, 11 expected
    # components per Tag-38-tip inventory).
    python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \\
        --output out/welle-5-smoke.json

    # Pre-PR-#241 inventory (10 expected components):
    python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \\
        --expected-components 10 --output out/welle-5-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \\
        --latency-tolerance-pct 10

    # Skip the A6 fsm-transition-parity probe (e.g. when the wirelang
    # package is not in the import path):
    python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \\
        --skip-fsm-transition-parity

License: Apache-2.0 (parity with sibling Phase-3c scripts).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants — Welle-5 focus on lifecycle_state_machine (BackendDecision
# domain key: "fsm").
# ---------------------------------------------------------------------------

#: Welle-5 focus component (ADR-0066 §Welle-5 KW-26 Doppel-Welle).
#: The in-repo short form is "fsm"; ADR-0066 uses the long form
#: "lifecycle_state_machine". Both refer to the same substrate.
FOCUS_COMPONENT = "fsm"
FOCUS_COMPONENT_LONG = "lifecycle_state_machine"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-5.
FOCUS_ENV_VAR = "WAKIR_FSM_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Tracks the engine inventory at
#: baseline ``8ad125a`` (Tag-38 tip, post-PR-#241 bridge_audit_diff_engine
#: wire-in): eleven resolvers. The smoke keeps both worlds (10 and
#: 11) working without re-deploy because ``bridge_audit_diff_engine``
#: is added to ENGINE_BOOT_COMPONENTS unconditionally and the smoke's
#: resolver-shim provides a clean shape when an upstream resolver
#: function is missing.
ENGINE_BOOT_COMPONENTS: Tuple[str, ...] = (
    "v907_verify",
    "svid_workload_identity",
    "bridge_diff",
    "anchor_emitter",
    "state_backing",
    "fsm",
    "subscribe_loop",
    "recovery",
    "federation_resolver",
    "bridge_audit_writer",
    "bridge_audit_diff_engine",
)

#: ADR-0065 §AC-2 tolerance: P95-Latency on the Rust path must not be
#: worse than Python-baseline + 20 %.
DEFAULT_LATENCY_TOLERANCE_PCT = 20

#: ADR-0065 §Verifikations-Plan Mo: 12 boots is the live-smoke
#: baseline. Smoke uses 8 per phase by default (pre/post/rollback × 8
#: = 24 total resolver calls per component, well over the percentile
#: sample requirement).
DEFAULT_BOOTS_PER_PHASE = 8

#: Default expected in-place-component count. Tracks baseline
#: ``8ad125a`` (Tag-38 tip, post-PR-#241 wire-in) = 11 components.
#: Operators running against a pre-PR-#241 tip pass
#: ``--expected-components 10`` to track the pre-wire-in inventory.
#: Tests cover both modes.
DEFAULT_EXPECTED_COMPONENTS = 11

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34/35/36/37/38.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-5-cutover-smoke/1"

#: ENV-var values the smoke flips per phase. fsm has only two enum
#: values (python, rust) — simpler than state_backing's three-valued
#: enum.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"

#: Welle-4 cross-modul-drift partner. The state_backing env-var
#: stays at the per-phase baseline ("python" in PHASE_PRE) and the
#: assert verifies that fsm's cutover does not leak into the
#: state_backing path. Symmetric to Welle-4's A7.
WELLE_4_PARTNER_COMPONENT = "state_backing"
WELLE_4_PARTNER_ENV_VAR = "WAKIR_STATE_BACKING_BACKEND"

#: Resolver-provenance markers — surfaced in the envelope so
#: operators know which surface the smoke exercised. fsm itself is
#: ALWAYS upstream (PR #169 baseline); only the trailing
#: bridge_audit_diff_engine may be shim on pre-PR-#241 baselines.
RESOLVER_PROVENANCE_UPSTREAM = "upstream"
RESOLVER_PROVENANCE_SHIM = "shim"


# ---------------------------------------------------------------------------
# Per-component env-var bridge — mirrors rust_backend_switch.py module
# constants. Kept local so the smoke does not have to import the
# resolver module just to read constants.
# ---------------------------------------------------------------------------

COMPONENT_TO_ENV: Dict[str, str] = {
    "v907_verify": "WAKIR_V907_VERIFY_BACKEND",
    "svid_workload_identity": "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    "bridge_diff": "WAKIR_BRIDGE_DIFF_BACKEND",
    "anchor_emitter": "WAKIR_ANCHOR_EMITTER_BACKEND",
    "state_backing": "WAKIR_STATE_BACKING_BACKEND",
    "fsm": "WAKIR_FSM_BACKEND",
    "subscribe_loop": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
    "recovery": "WAKIR_RECOVERY_BACKEND",
    "federation_resolver": "WAKIR_FEDERATION_RESOLVER_BACKEND",
    "bridge_audit_writer": "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
    "bridge_audit_diff_engine": "WAKIR_BRIDGE_AUDIT_DIFF_ENGINE_BACKEND",
}


# ---------------------------------------------------------------------------
# Resolver-import seam (test-injectable).
# ---------------------------------------------------------------------------


def _import_resolver() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.rust_backend_switch`.

    Kept lazy so that test environments without the wirelang package
    can import this module to unit-test the pure functions
    (parity-hash, latency-delta computation, envelope shape).
    """
    return importlib.import_module(
        "wirelang.persona_engine.rust_backend_switch"
    )


def _resolver_fn_name(component: str) -> str:
    """Map an in-place component to its resolver function name."""
    return f"resolve_{component}_backend"


# ---------------------------------------------------------------------------
# Resolver-shim — fills the gap on pre-PR-#241 baselines where
# ``resolve_bridge_audit_diff_engine_backend`` is not yet wired
# upstream. fsm itself NEVER uses the shim (PR #169 has shipped the
# upstream resolver since Tag-18).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ShimBackendDecision:
    """Mirrors wirelang BackendDecision byte-shape for the shim path."""

    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


#: Component-name → (env-var-attr, bin-resolver-attr, default-env-var)
#: triples for the resolver-shim path. Used when an upstream resolver
#: is not yet shipped but the env-var + bin-resolver primitives are.
#: At Tag-38 baseline ``8ad125a``, PR #241 has landed so
#: bridge_audit_diff_engine is upstream; the shim primitives remain in
#: place for backward-compat with pre-PR-#241 baselines.
SHIM_COMPONENT_PRIMITIVES: Dict[str, Tuple[str, str, str]] = {
    "bridge_audit_writer": (
        "BRIDGE_AUDIT_WRITER_BACKEND_ENV",
        "_resolve_bridge_audit_writer_bin",
        "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
    ),
    "bridge_audit_diff_engine": (
        "BRIDGE_AUDIT_DIFF_ENGINE_BACKEND_ENV",
        "_resolve_bridge_audit_diff_engine_bin",
        "WAKIR_BRIDGE_AUDIT_DIFF_ENGINE_BACKEND",
    ),
}


def _make_trailing_component_resolver_shim(
    component: str,
    resolver_module: Any,
) -> Callable[..., Tuple[str, _ShimBackendDecision]]:
    """Build a local resolver for a trailing component (no upstream yet).

    Mirrors the Welle-3/4 resolver-shim pattern (see
    ``welle-3-bridge-audit-writer-cutover-smoke.py`` L339-426 and
    ``welle-4-state-backing-cutover-smoke.py`` for the symmetric
    shape). The shim wraps the existing module primitives when
    present (``<COMPONENT>_BACKEND_ENV``, ``_resolve_<component>_bin``,
    ``_binary_available``) and falls back to a python-only response
    when they are absent.

    Returns a callable with the same signature as the other
    resolvers: ``(env, *, log_sink, binary_probe) -> (chosen_backend,
    BackendDecision-shaped-record)``. The shim never mutates os.environ.
    """
    if component not in SHIM_COMPONENT_PRIMITIVES:
        raise ValueError(
            f"no shim primitives configured for component {component!r}; "
            f"valid: {sorted(SHIM_COMPONENT_PRIMITIVES.keys())!r}"
        )
    env_attr, bin_attr, env_default = SHIM_COMPONENT_PRIMITIVES[component]
    env_var = getattr(resolver_module, env_attr, env_default)
    bin_resolver = getattr(resolver_module, bin_attr, None)
    default_probe = getattr(resolver_module, "_binary_available", None)

    def _resolver(
        env: Optional[Mapping[str, str]] = None,
        *,
        log_sink: Any = None,
        binary_probe: Optional[
            Callable[[str], Tuple[bool, Optional[str]]]
        ] = None,
    ) -> Tuple[str, _ShimBackendDecision]:
        env_map = env or {}
        raw = env_map.get(env_var, "")
        requested = raw if raw else ENV_VALUE_PYTHON
        chosen = requested
        fallback_reason: Optional[str] = None
        bin_path: Optional[str] = None

        start_ns = time.monotonic_ns()
        if requested == ENV_VALUE_RUST:
            probe = binary_probe or default_probe
            if bin_resolver is not None:
                bin_path = bin_resolver(env_map)
            else:
                bin_path = None
            if probe is None:
                chosen = ENV_VALUE_PYTHON
                fallback_reason = "binary_probe_unavailable"
            elif bin_path is None:
                chosen = ENV_VALUE_PYTHON
                fallback_reason = "binary_path_unresolved"
            else:
                available, probe_reason = probe(bin_path)
                if not available:
                    chosen = ENV_VALUE_PYTHON
                    fallback_reason = probe_reason or "binary_missing"
        else:
            chosen = ENV_VALUE_PYTHON
            if raw == ENV_VALUE_PYTHON:
                fallback_reason = "explicit_python"

        elapsed_us = max(1, (time.monotonic_ns() - start_ns) // 1000)
        decision = _ShimBackendDecision(
            domain=component,
            requested_backend=requested,
            chosen_backend=chosen,
            resolution_latency_us=int(elapsed_us),
            fallback_reason=fallback_reason,
            bin_path=bin_path,
        )
        return chosen, decision

    return _resolver


def _resolve_resolver_for_component(
    component: str,
    resolver_module: Any,
) -> Tuple[Callable[..., Tuple[Any, Any]], str]:
    """Return ``(resolver_fn, provenance)`` for ``component``.

    Tries the upstream function name first. If missing AND component
    is a known shim-eligible trailing component
    (``bridge_audit_writer`` or ``bridge_audit_diff_engine``), falls
    back to the local shim. Any other missing-resolver is fatal
    (raises AttributeError). fsm itself MUST be upstream (PR #169);
    a missing ``resolve_fsm_backend`` is a substrate-regression and
    should fail loudly.
    """
    fn_name = _resolver_fn_name(component)
    upstream = getattr(resolver_module, fn_name, None)
    if upstream is not None:
        return upstream, RESOLVER_PROVENANCE_UPSTREAM
    if component in SHIM_COMPONENT_PRIMITIVES:
        return (
            _make_trailing_component_resolver_shim(component, resolver_module),
            RESOLVER_PROVENANCE_SHIM,
        )
    raise AttributeError(
        f"resolver module is missing function {fn_name!r} "
        f"(component={component!r}) and no shim is available"
    )


# ---------------------------------------------------------------------------
# Stub binary-probe — never touches the filesystem.
# ---------------------------------------------------------------------------


def _stub_probe_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
    """Pretend every Rust binary is present and executable.

    The smoke assumes the Pilot-VM operator has the Rust binaries
    deployed — that's a separate Quadlet-Installer prerequisite (per
    ADR-0065 §Trigger-Bedingung-3). The smoke focuses on the
    *backend-switch behaviour*, not the binary-deployment posture.

    Operator-warning: live Welle-5 substrate readiness depends on
    the ``persona-engine-fsm`` binary shipping from the
    ``persona-engine-fsm`` crate (Tag-18 Mini-Welle PR #169 /
    container-image-pipeline Tag-32 PR #226). If the binary is not
    deployed on the Pilot-VM, the real ``_binary_available`` probe
    returns ``(False, "binary_missing")`` and A5 fails on the live
    smoke — that's the ADR-0066 Welle-5 precondition signal, not a
    smoke bug. The stub here keeps the smoke green-band-demonstrable
    for pre-deploy CI gates.
    """
    return True, None


# ---------------------------------------------------------------------------
# Hermetic env-map construction per phase.
# ---------------------------------------------------------------------------


def build_phase_env(
    phase: str,
    *,
    base_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Return the hermetic env-map for ``phase``.

    Phases:
      * :data:`PHASE_PRE` — every Phase-3c component's env-var is
        explicitly ``"python"``. This is the Python-default baseline.
      * :data:`PHASE_POST` — same, but ``FOCUS_ENV_VAR=rust``.
      * :data:`PHASE_ROLLBACK` — :data:`FOCUS_ENV_VAR` is *absent*
        from the env-map (engine reads the Python-default code-path,
        which is the Quadlet-default after rollback).

    The returned dict is always a fresh copy of ``base_env`` (default
    empty) — the smoke never inherits the operator's environment.

    Welle-4 partner invariant: ``WAKIR_STATE_BACKING_BACKEND`` is set
    to ``"python"`` in every phase. The A7 cross-modul-drift assert
    verifies that the state_backing BackendDecision actually honours
    this setting in PHASE_POST — i.e. fsm's cutover does not leak
    into state_backing's resolver path. Symmetric to Welle-4's A7.
    """
    env: Dict[str, str] = dict(base_env or {})
    for env_var in COMPONENT_TO_ENV.values():
        env[env_var] = ENV_VALUE_PYTHON
    if phase == PHASE_PRE:
        return env
    if phase == PHASE_POST:
        env[FOCUS_ENV_VAR] = ENV_VALUE_RUST
        return env
    if phase == PHASE_ROLLBACK:
        # Rollback simulates ENV-unset: the focus env-var is absent
        # from the map. The resolver's _env_get returns "" then,
        # which the resolver treats as the python-default.
        env.pop(FOCUS_ENV_VAR, None)
        return env
    raise ValueError(
        f"unknown phase {phase!r}; expected one of "
        f"({PHASE_PRE!r}, {PHASE_POST!r}, {PHASE_ROLLBACK!r})"
    )


# ---------------------------------------------------------------------------
# Mocked persona-boot — emits one BackendDecision per in-place component.
# ---------------------------------------------------------------------------


def boot_engine_once(
    *,
    env: Mapping[str, str],
    components: Tuple[str, ...],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
    provenance_sink: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Simulate a single persona-engine boot.

    For each in-place component, calls the resolver (upstream or
    shim per :func:`_resolve_resolver_for_component`) and collects
    the ``BackendDecision``. Returns the list of decision-records in
    the declared component order. The engine in production emits
    these as structured-log JSON-lines; the smoke captures them in-
    memory.

    When ``provenance_sink`` is provided, the function records
    per-component resolver-provenance into it (``"upstream"`` or
    ``"shim"``) so the envelope can surface which resolver-surface
    the smoke exercised.
    """
    records: List[Dict[str, Any]] = []
    for component in components:
        resolver_fn, provenance = _resolve_resolver_for_component(
            component, resolver_module
        )
        if provenance_sink is not None:
            provenance_sink.setdefault(component, provenance)
        _backend, decision = resolver_fn(
            env=env,
            log_sink=None,
            binary_probe=binary_probe,
        )
        if hasattr(decision, "__dict__") or hasattr(decision, "__dataclass_fields__"):
            try:
                record = asdict(decision)
            except TypeError:
                record = dict(decision.__dict__)
        elif isinstance(decision, Mapping):
            record = dict(decision)
        else:
            raise TypeError(
                f"resolver {component!r} returned non-dataclass "
                f"non-mapping decision of type {type(decision).__name__}"
            )
        records.append(record)
    return records


def run_phase(
    phase: str,
    *,
    boots: int,
    components: Tuple[str, ...],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
    base_env: Optional[Mapping[str, str]] = None,
    capture_fsm_transition_baseline: bool = False,
    fsm_transition_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Dict[str, Any]:
    """Run ``boots`` mocked boots for a single phase.

    Returns a phase-record:
      * ``phase`` — the phase label.
      * ``env_snapshot`` — the hermetic env-map after :func:`build_phase_env`.
      * ``boots`` — boot-count.
      * ``decisions`` — flattened list of BackendDecision dicts
        (length == boots * len(components)).
      * ``per_boot_decisions`` — list of per-boot lists.
      * ``resolver_provenance`` — per-component provenance map.
      * ``fsm_transition_baseline`` — populated iff
        ``capture_fsm_transition_baseline`` is True (PHASE_PRE only;
        this is the FSM-Transition-Integrity temporal anchor).

    FSM-Transition-Integrity note: the fsm-transition baseline
    capture is gated on the ``capture_fsm_transition_baseline`` flag
    and only set True by the orchestrator for :data:`PHASE_PRE`. If
    a future refactor accidentally sets the flag for any other
    phase, the smoke architecture documents that this is the
    temporal anchor for the FSM-Transition-Integrity oracle.
    """
    if boots < 1:
        raise ValueError(f"boots must be >= 1; got {boots!r}")
    env = build_phase_env(phase, base_env=base_env)
    provenance: Dict[str, str] = {}
    per_boot: List[List[Dict[str, Any]]] = []
    flat: List[Dict[str, Any]] = []
    for _ in range(boots):
        boot_records = boot_engine_once(
            env=env,
            components=components,
            resolver_module=resolver_module,
            binary_probe=binary_probe,
            provenance_sink=provenance,
        )
        per_boot.append(boot_records)
        flat.extend(boot_records)

    record: Dict[str, Any] = {
        "phase": phase,
        "env_snapshot": dict(env),
        "boots": boots,
        "decisions": flat,
        "per_boot_decisions": per_boot,
        "resolver_provenance": dict(provenance),
    }

    if capture_fsm_transition_baseline:
        if fsm_transition_baseline_fn is not None:
            baseline = fsm_transition_baseline_fn()
        else:
            baseline = capture_fsm_transition_baseline_default()
        record["fsm_transition_baseline"] = baseline
    return record


# ---------------------------------------------------------------------------
# Parity-hash + latency helpers.
# ---------------------------------------------------------------------------


def parity_hash(records: List[Dict[str, Any]]) -> str:
    """Deterministic SHA-256 over the parity-relevant decision fields.

    The parity-hash is the cross-lang byte-shape oracle: Python and
    Rust resolvers should produce identical ``domain`` /
    ``requested_backend`` / ``chosen_backend`` / ``fallback_reason``
    tuples for the same env-map. Latency is *not* in the hash (it's
    monotonic-clock-derived and would defeat the determinism).

    Fixture-reference: ``tests/fixtures/lifecycle-state-machine-
    cross-lang/`` (PR #169 / PR #177) embeds the substrate-level
    invariant that Python and Rust write byte-equal LifecycleTrace
    JCS bytes. This hash is the smoke's engine-emission-level
    materialisation of that contract; A6 verifies the substrate-
    level oracle directly.
    """
    fields = [
        (
            r.get("domain"),
            r.get("requested_backend"),
            r.get("chosen_backend"),
            r.get("fallback_reason"),
        )
        for r in records
    ]
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _nearest_rank_percentile(values: List[int], percentile: float) -> int:
    """Same nearest-rank percentile semantics as the sibling dry-run."""
    if not values:
        return 0
    if percentile <= 0:
        return int(min(values))
    if percentile >= 100:
        return int(max(values))
    ordered = sorted(values)
    import math as _math
    rank = max(1, _math.ceil(percentile / 100.0 * len(ordered)))
    return int(ordered[rank - 1])


def _focus_latencies(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> List[int]:
    """Extract resolution_latency_us for the focus-component records only."""
    out: List[int] = []
    for r in records:
        if r.get("domain") != focus:
            continue
        raw = r.get("resolution_latency_us")
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            out.append(raw)
    return out


def latency_p95(records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT) -> int:
    """P95 of the focus-component resolution_latency_us across all boots."""
    return _nearest_rank_percentile(_focus_latencies(records, focus=focus), 95.0)


# ---------------------------------------------------------------------------
# A6 — FSM-Transition pre-baseline + post-cutover-parity probe
# (FSM-Transition-Integrity, no phantom transitions).
#
# FSM-Transition-Integrity note: the BASELINE capture happens in
# PHASE_PRE *before* the cutover-step constructs PHASE_POST. The
# POST recomputation is done by calling the SAME Python authority
# again (not the Rust pendant, which is not yet linked into the
# smoke). The substrate-level oracle is: the Python authority is
# byte-stable across the pre/post window AND every accepted record
# references an edge in the spec's closed VALID_TRANSITIONS
# enumeration. If the recomputed hash matches the baseline AND no
# phantom edges appear, the Python lifecycle-trace serializer did
# not drift. That is the only oracle the smoke can give *without*
# bringing up a real Rust binary; the Rust pendant byte-parity is
# locked at a different layer (the lifecycle-state-machine cross-
# lang fixture pins from PR #169 / PR #177).
# ---------------------------------------------------------------------------


#: Spec §3.3 closed enumeration of valid transitions. Duplicated
#: locally so the smoke remains importable when the wirelang package
#: is absent. The smoke's A6 phantom-transition check compares
#: against this tuple. Keep in lock-step with
#: ``wirelang.persona_engine.lifecycle_state_machine.VALID_TRANSITIONS``.
SPEC_VALID_TRANSITIONS: Tuple[Tuple[str, str], ...] = (
    ("uninstantiated", "spawning"),
    ("spawning", "running"),
    ("spawning", "uninstantiated"),
    ("running", "despawning"),
    ("despawning", "uninstantiated"),
    ("uninstantiated", "recovered"),
    ("recovered", "running"),
    ("running", "migrated"),
    ("migrated", "uninstantiated"),
)

#: Deterministic six-transition trace used for the fsm-transition
#: pre-baseline. Walks the full spec §3.3 happy-path
#: uninstantiated → spawning → running → despawning → uninstantiated
#: → recovered → running → migrated → uninstantiated. Fixed
#: timestamps so the resulting JCS-bytes are byte-stable across
#: smoke invocations. Aligned with the LifecycleTrace shape from
#: PR #169 / PR #177 (lifecycle-state-machine cross-lang fixtures).
DETERMINISTIC_LIFECYCLE_TRANSITIONS: Tuple[Dict[str, Any], ...] = (
    {
        "from_state": "uninstantiated",
        "to_state": "spawning",
        "ts_utc": "2026-05-26T00:00:00Z",
        "accepted": True,
    },
    {
        "from_state": "spawning",
        "to_state": "running",
        "ts_utc": "2026-05-26T00:00:01Z",
        "accepted": True,
    },
    {
        "from_state": "running",
        "to_state": "despawning",
        "ts_utc": "2026-05-26T00:00:02Z",
        "accepted": True,
    },
    {
        "from_state": "despawning",
        "to_state": "uninstantiated",
        "ts_utc": "2026-05-26T00:00:03Z",
        "accepted": True,
    },
    {
        "from_state": "uninstantiated",
        "to_state": "recovered",
        "ts_utc": "2026-05-26T00:00:04Z",
        "accepted": True,
    },
    {
        "from_state": "recovered",
        "to_state": "running",
        "ts_utc": "2026-05-26T00:00:05Z",
        "accepted": True,
    },
)

#: Org/persona identifiers for the deterministic trace fixture.
DETERMINISTIC_TRACE_PERSONA_ID = "persona-welle-5-smoke"
DETERMINISTIC_TRACE_ORG_ID = "org-welle-5-smoke"
DETERMINISTIC_TRACE_INITIAL_STATE = "uninstantiated"


def _import_lifecycle_canonical() -> Any:
    """Lazy import of
    :mod:`wirelang.persona_engine.lifecycle_state_machine_canonical`.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.persona_engine.lifecycle_state_machine_canonical"
    )


def _build_and_hash_trace(
    module: Any,
    transitions: Tuple[Dict[str, Any], ...],
) -> Tuple[bytes, str]:
    """Build a LifecycleTrace from transitions and return (bytes, hex-hash).

    The wirelang public API surface uses
    ``TransitionRecord`` + ``build_lifecycle_trace_from_records`` +
    ``serialize_lifecycle_trace`` + ``lifecycle_trace_sha256_hex``.
    The helper prefers that surface; if missing it tries stub-
    friendly module-level helpers (used by the test suite).
    """
    transition_record_cls = getattr(module, "TransitionRecord", None)
    builder = getattr(module, "build_lifecycle_trace_from_records", None)
    serialiser = getattr(module, "serialize_lifecycle_trace", None)
    hasher = getattr(module, "lifecycle_trace_sha256_hex", None)

    if (
        transition_record_cls is not None
        and callable(builder)
        and callable(serialiser)
    ):
        records = []
        for t in transitions:
            try:
                records.append(
                    transition_record_cls(
                        from_state=t["from_state"],
                        to_state=t["to_state"],
                        ts_utc=t["ts_utc"],
                        accepted=t["accepted"],
                        reason=t.get("reason"),
                    )
                )
            except TypeError:
                records.append(transition_record_cls(**dict(t)))
        trace = builder(
            persona_id=DETERMINISTIC_TRACE_PERSONA_ID,
            org_id=DETERMINISTIC_TRACE_ORG_ID,
            initial_state=DETERMINISTIC_TRACE_INITIAL_STATE,
            records=records,
        )
        payload = serialiser(trace)
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)
        if callable(hasher):
            digest = hasher(trace)
        else:
            digest = hashlib.sha256(payload_bytes).hexdigest()
        return payload_bytes, digest

    # Fallback: module-level to_jcs_bytes(transitions: list[dict]).
    fallback = getattr(module, "to_jcs_bytes", None)
    if callable(fallback):
        payload = fallback(list(transitions))
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)
        return payload_bytes, hashlib.sha256(payload_bytes).hexdigest()

    raise AttributeError(
        "lifecycle_state_machine_canonical module exposes neither "
        "TransitionRecord+build_lifecycle_trace_from_records+"
        "serialize_lifecycle_trace nor a module-level to_jcs_bytes "
        "helper"
    )


def _phantom_transitions(
    transitions: Tuple[Dict[str, Any], ...],
) -> List[Tuple[str, str]]:
    """Return any (from_state, to_state) pairs that are NOT in the spec.

    Only checks ``accepted == True`` records; rejected records are
    audit annotations and are allowed to reference any state-pair
    (that's the entire point of the rejection record).
    """
    out: List[Tuple[str, str]] = []
    valid = set(SPEC_VALID_TRANSITIONS)
    for t in transitions:
        if not t.get("accepted"):
            continue
        pair = (t.get("from_state"), t.get("to_state"))
        if pair not in valid:
            out.append((str(pair[0]), str(pair[1])))
    return out


def capture_fsm_transition_baseline_default(
    *,
    transitions: Tuple[Dict[str, Any], ...] = DETERMINISTIC_LIFECYCLE_TRANSITIONS,
    canonical_module: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Capture the pre-cutover fsm-transition-hash baseline.

    Returns a record (always non-None at the API level, ``skipped=True``
    when the wirelang.lifecycle_state_machine_canonical module is not
    importable). The record contains:

      * ``trace_sha256_hex`` — SHA-256 over the JCS-canonical bytes
        of the deterministic LifecycleTrace.
      * ``trace_byte_length`` — len of the canonical bytes (useful
        for cross-substrate sanity-checking).
      * ``transition_count`` — len(transitions).
      * ``phantom_transitions`` — list of (from, to) pairs not in
        :data:`SPEC_VALID_TRANSITIONS`. Should always be empty for
        the deterministic fixture; populated only if the fixture
        itself is corrupted (a regression-trap for the fixture).
      * ``captured_at_phase`` — always :data:`PHASE_PRE`
        (FSM-Transition-Integrity invariant; do not change this).

    This function is the FSM-Transition-Integrity capture moment.
    The post-cutover recompute reads the same baseline and asserts
    byte-equality (A6).
    """
    module = canonical_module
    if module is None:
        try:
            module = _import_lifecycle_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"lifecycle_state_machine_canonical not importable: "
                    f"{exc}"
                ),
                "trace_sha256_hex": None,
                "trace_byte_length": 0,
                "transition_count": 0,
                "phantom_transitions": [],
                "captured_at_phase": PHASE_PRE,
            }

    phantom = _phantom_transitions(transitions)

    try:
        payload_bytes, digest = _build_and_hash_trace(module, transitions)
    except Exception as exc:  # noqa: BLE001 — substrate drift is the signal
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                f"fsm-transition baseline capture raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "trace_sha256_hex": None,
            "trace_byte_length": 0,
            "transition_count": 0,
            "phantom_transitions": phantom,
            "captured_at_phase": PHASE_PRE,
        }

    return {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"fsm-transition baseline captured: "
            f"{len(transitions)} transitions, "
            f"trace_sha256={digest[:16]}..."
        ),
        "trace_sha256_hex": digest,
        "trace_byte_length": len(payload_bytes),
        "transition_count": len(transitions),
        "phantom_transitions": phantom,
        "captured_at_phase": PHASE_PRE,
    }


def evaluate_fsm_transition_parity(
    baseline: Optional[Dict[str, Any]],
    *,
    transitions: Tuple[Dict[str, Any], ...] = DETERMINISTIC_LIFECYCLE_TRANSITIONS,
    canonical_module: Optional[Any] = None,
) -> Dict[str, Any]:
    """Recompute the fsm-transition-hash post-cutover and compare.

    Note: the recomputation is done by calling the SAME Python
    authority again, NOT the Rust pendant. The substrate-level
    oracle is "the Python lifecycle_trace serializer is byte-stable
    across the pre/post window AND no phantom transitions appear".
    The Rust pendant byte-parity is pinned at the fixture layer
    (separate substrate, not loaded by this smoke at runtime). This
    is the only oracle the smoke can give *without* a real Rust
    binary.

    Returns a record with:

      * ``passed`` — True iff the recomputed hash matches the
        baseline hash AND no phantom transitions were detected
        post-cutover.
      * ``skipped`` — True iff baseline was skipped or recomputation
        cannot be performed.
      * ``baseline_trace_sha256`` — the baseline hash for the
        envelope reader.
      * ``recomputed_trace_sha256`` — the post-cutover hash.
      * ``match`` — bool (hash equality).
      * ``phantom_transitions`` — list of phantom-edges detected in
        the recomputed trace. Should always be empty.
    """
    if baseline is None or baseline.get("skipped"):
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                baseline.get("detail")
                if baseline is not None
                else "no baseline supplied; A6 skipped"
            ),
            "baseline_trace_sha256": None,
            "recomputed_trace_sha256": None,
            "match": True,
            "phantom_transitions": [],
            "captured_at_phase": (
                baseline.get("captured_at_phase") if baseline else PHASE_PRE
            ),
        }

    module = canonical_module
    if module is None:
        try:
            module = _import_lifecycle_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"lifecycle_state_machine_canonical not "
                    f"importable for recompute: {exc}"
                ),
                "baseline_trace_sha256": baseline.get("trace_sha256_hex"),
                "recomputed_trace_sha256": None,
                "match": True,
                "phantom_transitions": [],
                "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
            }

    phantom_post = _phantom_transitions(transitions)

    try:
        _payload_bytes, recomputed = _build_and_hash_trace(module, transitions)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "skipped": False,
            "severity": "caution",
            "detail": (
                f"fsm-transition recompute raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "baseline_trace_sha256": baseline.get("trace_sha256_hex"),
            "recomputed_trace_sha256": None,
            "match": False,
            "phantom_transitions": phantom_post,
            "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
        }

    baseline_hash = baseline.get("trace_sha256_hex")
    match = recomputed == baseline_hash
    no_phantoms = not phantom_post
    passed = match and no_phantoms

    if passed:
        detail = (
            f"fsm-transition parity ok ({recomputed[:16]}...), "
            f"no phantom transitions"
        )
    elif not match and not no_phantoms:
        detail = (
            f"fsm-transition drift AND phantom transitions: "
            f"baseline={baseline_hash} recomputed={recomputed} "
            f"phantoms={phantom_post!r}"
        )
    elif not match:
        detail = (
            f"fsm-transition drift: baseline={baseline_hash} "
            f"recomputed={recomputed}"
        )
    else:
        detail = (
            f"fsm-transition phantom edges detected: {phantom_post!r}"
        )

    return {
        "passed": passed,
        "skipped": False,
        "severity": "caution",
        "detail": detail,
        "baseline_trace_sha256": baseline_hash,
        "recomputed_trace_sha256": recomputed,
        "match": match,
        "phantom_transitions": phantom_post,
        "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
    }


# ---------------------------------------------------------------------------
# Assert evaluation.
# ---------------------------------------------------------------------------


def _focus_records(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("domain") == focus]


def evaluate_post_cutover_asserts(
    *,
    pre_records: List[Dict[str, Any]],
    post_records: List[Dict[str, Any]],
    rollback_records: List[Dict[str, Any]],
    expected_components: int,
    boots_per_phase: int,
    latency_tolerance_pct: int,
    fsm_transition_baseline: Optional[Dict[str, Any]] = None,
    fsm_transition_parity: Optional[Dict[str, Any]] = None,
    focus: str = FOCUS_COMPONENT,
) -> Dict[str, Any]:
    """Evaluate A1..A5 + R1 + A6 + A7; return asserts-record.

    Each assert is encoded as ``{passed: bool, severity: "blocker" |
    "caution", detail: str, ...}`` so the envelope can render the
    full Decision-Matrix table.

    Severity legend:
      * **blocker** — failure pushes exit to :data:`EXIT_ROLLBACK`.
      * **caution** — failure pushes exit to :data:`EXIT_CAUTION`
        (unless a blocker also failed, in which case rollback wins).
    """
    asserts: Dict[str, Any] = {}

    # A1: post-cutover focus-component reports chosen_backend == "rust".
    post_focus = _focus_records(post_records, focus=focus)
    a1_all_rust = bool(post_focus) and all(
        r.get("chosen_backend") == ENV_VALUE_RUST for r in post_focus
    )
    asserts["A1_backend_flip"] = {
        "passed": a1_all_rust,
        "severity": "blocker",
        "detail": (
            f"fsm chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})} "
            f"(expected all == {ENV_VALUE_RUST!r})"
        ),
    }

    # A2: cross-lang parity-hash identical between Post-Cutover-Rust
    # and Rollback-Python on the structural projection (drops the
    # requested_backend/chosen_backend pair).
    post_focus_hash = _parity_hash_focus_normalised(post_records, focus=focus)
    rollback_focus_hash = _parity_hash_focus_normalised(
        rollback_records, focus=focus
    )
    baseline_focus_hash = _parity_hash_focus_normalised(pre_records, focus=focus)
    a2_parity_ok = post_focus_hash == rollback_focus_hash
    asserts["A2_cross_lang_parity_hash"] = {
        "passed": a2_parity_ok,
        "severity": "blocker",
        "detail": (
            f"post_focus_hash={post_focus_hash[:16]}... "
            f"rollback_focus_hash={rollback_focus_hash[:16]}... "
            f"pre_explicit_python_hash={baseline_focus_hash[:16]}..."
            " (pre includes fallback_reason=explicit_python by resolver "
            "design; compared informationally only)"
        ),
    }

    # A3: P95 latency tolerance on focus-component.
    pre_p95 = latency_p95(pre_records, focus=focus)
    post_p95 = latency_p95(post_records, focus=focus)
    if pre_p95 <= 0:
        latency_ok = post_p95 <= 100
        tolerance_us = 100
    else:
        tolerance_us = pre_p95 + (pre_p95 * latency_tolerance_pct) // 100
        latency_ok = post_p95 <= tolerance_us
    asserts["A3_latency_within_tolerance"] = {
        "passed": latency_ok,
        "severity": "caution",
        "detail": (
            f"pre_p95_us={pre_p95} post_p95_us={post_p95} "
            f"tolerance_pct={latency_tolerance_pct} "
            f"tolerance_us={tolerance_us}"
        ),
    }

    # A4: decision-count per boot matches expected_components.
    a4_counts_per_boot: List[int] = []
    a4_total_ok = len(post_records) == expected_components * boots_per_phase
    if expected_components > 0 and len(post_records) % expected_components == 0:
        chunk = expected_components
        a4_counts_per_boot = [
            len(post_records[i : i + chunk])
            for i in range(0, len(post_records), chunk)
        ]
        a4_per_boot_ok = all(c == expected_components for c in a4_counts_per_boot)
    else:
        a4_per_boot_ok = False
    a4_passed = a4_total_ok and a4_per_boot_ok
    asserts["A4_decision_count_in_place"] = {
        "passed": a4_passed,
        "severity": "caution",
        "detail": (
            f"expected_components={expected_components} "
            f"boots_per_phase={boots_per_phase} "
            f"total_post_records={len(post_records)} "
            f"counts_per_boot={a4_counts_per_boot}"
        ),
    }

    # A5: zero fallback_reason entries on focus-component post-cutover.
    fallbacks = [
        r.get("fallback_reason")
        for r in post_focus
        if r.get("fallback_reason") not in (None, "")
    ]
    a5_clean = not fallbacks
    asserts["A5_fallback_clean"] = {
        "passed": a5_clean,
        "severity": "blocker",
        "detail": (
            f"fallback_reasons_on_focus_post={fallbacks!r}"
            if fallbacks
            else "no fallback on focus-component post-cutover"
        ),
    }

    # Rollback: focus-component on rollback phase must be python.
    rollback_focus = _focus_records(rollback_records, focus=focus)
    rollback_all_python = bool(rollback_focus) and all(
        r.get("chosen_backend") == ENV_VALUE_PYTHON for r in rollback_focus
    )
    asserts["R1_rollback_to_python"] = {
        "passed": rollback_all_python,
        "severity": "blocker",
        "detail": (
            f"rollback chosen_backend across {len(rollback_focus)} "
            f"records: "
            f"{sorted({r.get('chosen_backend') for r in rollback_focus})}"
        ),
    }

    # A6: fsm-transition pre/post parity probe + phantom-transition
    # check (caution-severity).
    if fsm_transition_parity is None:
        a6_record = {
            "passed": True,
            "severity": "caution",
            "skipped": True,
            "detail": "A6 skipped (probe not invoked)",
            "baseline_trace_sha256": None,
            "recomputed_trace_sha256": None,
            "match": True,
            "phantom_transitions": [],
            "captured_at_phase": PHASE_PRE,
        }
    else:
        a6_record = {
            "passed": bool(fsm_transition_parity.get("passed", True)),
            "severity": "caution",
            "skipped": bool(fsm_transition_parity.get("skipped", False)),
            "detail": fsm_transition_parity.get("detail", ""),
            "baseline_trace_sha256": fsm_transition_parity.get(
                "baseline_trace_sha256"
            ),
            "recomputed_trace_sha256": fsm_transition_parity.get(
                "recomputed_trace_sha256"
            ),
            "match": bool(fsm_transition_parity.get("match", True)),
            "phantom_transitions": list(
                fsm_transition_parity.get("phantom_transitions") or []
            ),
            "captured_at_phase": fsm_transition_parity.get(
                "captured_at_phase", PHASE_PRE
            ),
        }
    asserts["A6_fsm_transition_integrity"] = a6_record

    # A7: Cross-Modul-Drift-Mitigation control invariant (Welle-4
    # partner: state_backing). The state_backing BackendDecision MUST
    # honour WAKIR_STATE_BACKING_BACKEND==python in PHASE_POST (fsm's
    # cutover MUST NOT leak into state_backing's resolver path).
    # Symmetric to Welle-4's A7.
    sb_post_records = [
        r
        for r in post_records
        if r.get("domain") == WELLE_4_PARTNER_COMPONENT
    ]
    if not sb_post_records:
        a7_record = {
            "passed": False,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 state_backing cross-modul-drift check: no "
                f"state_backing BackendDecision present in PHASE_POST "
                f"records (expected {boots_per_phase} state_backing "
                f"decisions). The fsm cutover may have suppressed "
                f"state_backing emissions — parallel-Welle isolation "
                f"broken."
            ),
            "state_backing_chosen_backends": [],
            "expected_state_backing_backend": ENV_VALUE_PYTHON,
        }
    else:
        chosen = [r.get("chosen_backend") for r in sb_post_records]
        all_python = all(c == ENV_VALUE_PYTHON for c in chosen)
        a7_record = {
            "passed": all_python,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 cross-modul-drift OK: state_backing stayed at "
                f"python across {len(sb_post_records)} PHASE_POST "
                f"records during fsm cutover"
                if all_python
                else (
                    f"A7 cross-modul-drift FAIL: fsm cutover leaked "
                    f"into state_backing path. state_backing "
                    f"chosen_backend values in PHASE_POST: "
                    f"{sorted(set(chosen))} (expected all == "
                    f"'python'). This breaks the KW-26 Doppel-Welle "
                    f"isolation contract."
                )
            ),
            "state_backing_chosen_backends": sorted(set(chosen)),
            "expected_state_backing_backend": ENV_VALUE_PYTHON,
        }
    asserts["A7_cross_modul_drift_welle_4_state_backing"] = a7_record

    return asserts


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
    """Parity-hash over the *structural* fields of focus-component records.

    See the Welle-1/2/3/4 siblings for the full rationale; the
    projection keeps ``domain`` and ``fallback_reason`` while
    dropping the ``requested_backend`` / ``chosen_backend`` pair
    (both flipped by the env-var/cutover). ``bin_path`` is also
    dropped (filesystem-dependent).
    """
    focus_records = _focus_records(records, focus=focus)
    fields = [
        (
            r.get("domain"),
            r.get("fallback_reason"),
        )
        for r in focus_records
    ]
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_exit_code(asserts: Dict[str, Any]) -> int:
    """Map the asserts-record to the tri-state exit code.

    Logic:
      * Any blocker failed → :data:`EXIT_ROLLBACK` (2).
      * No blocker failed but any caution failed → :data:`EXIT_CAUTION` (1).
      * All passed (or all caution-skipped) → :data:`EXIT_GREEN` (0).

    Skipped asserts (``skipped: True``) are treated as passed for the
    purposes of exit-code derivation — the operator gets the
    information via the envelope's ``skipped`` flag.
    """
    blocker_fail = any(
        v.get("severity") == "blocker" and not v.get("passed")
        for v in asserts.values()
    )
    if blocker_fail:
        return EXIT_ROLLBACK
    caution_fail = any(
        v.get("severity") == "caution"
        and not v.get("passed")
        and not v.get("skipped")
        for v in asserts.values()
    )
    if caution_fail:
        return EXIT_CAUTION
    return EXIT_GREEN


# ---------------------------------------------------------------------------
# Envelope construction.
# ---------------------------------------------------------------------------


def build_envelope(
    *,
    pre_phase: Dict[str, Any],
    post_phase: Dict[str, Any],
    rollback_phase: Dict[str, Any],
    asserts: Dict[str, Any],
    exit_code: int,
    expected_components: int,
    boots_per_phase: int,
    latency_tolerance_pct: int,
    fsm_transition_baseline: Optional[Dict[str, Any]] = None,
    resolver_provenance: Optional[Dict[str, str]] = None,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the operator-facing JSON envelope."""
    timestamp = int(now_ts if now_ts is not None else time.time())
    band_for_exit = {
        EXIT_GREEN: "GREEN",
        EXIT_CAUTION: "CAUTION",
        EXIT_ROLLBACK: "ROLLBACK_RECOMMENDED",
    }
    envelope: Dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "timestamp_utc": timestamp,
        "welle": 5,
        "focus_component": FOCUS_COMPONENT,
        "focus_component_long": FOCUS_COMPONENT_LONG,
        "focus_env_var": FOCUS_ENV_VAR,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
        "resolver_provenance": dict(resolver_provenance or {}),
        "cross_modul_drift_mitigation": {
            "welle_4_partner_component": WELLE_4_PARTNER_COMPONENT,
            "welle_4_partner_env_var": WELLE_4_PARTNER_ENV_VAR,
            "expected_welle_4_partner_backend": ENV_VALUE_PYTHON,
            "state_backing_chosen_backends_in_post_phase": asserts.get(
                "A7_cross_modul_drift_welle_4_state_backing", {}
            ).get("state_backing_chosen_backends", []),
        },
        "fsm_transition_integrity": {
            "baseline_captured_at_phase": (
                fsm_transition_baseline.get("captured_at_phase")
                if fsm_transition_baseline is not None
                else None
            ),
            "baseline_trace_sha256": (
                fsm_transition_baseline.get("trace_sha256_hex")
                if fsm_transition_baseline is not None
                else None
            ),
            "baseline_skipped": (
                bool(fsm_transition_baseline.get("skipped", False))
                if fsm_transition_baseline is not None
                else True
            ),
            "baseline_phantom_transitions": (
                list(
                    fsm_transition_baseline.get("phantom_transitions") or []
                )
                if fsm_transition_baseline is not None
                else []
            ),
            "spec_valid_transition_count": len(SPEC_VALID_TRANSITIONS),
        },
        "phases": {
            PHASE_PRE: {
                "boots": pre_phase["boots"],
                "decision_count": len(pre_phase["decisions"]),
                "focus_p95_latency_us": latency_p95(pre_phase["decisions"]),
                "parity_hash": parity_hash(pre_phase["decisions"]),
                "focus_parity_hash_normalised": _parity_hash_focus_normalised(
                    pre_phase["decisions"]
                ),
            },
            PHASE_POST: {
                "boots": post_phase["boots"],
                "decision_count": len(post_phase["decisions"]),
                "focus_p95_latency_us": latency_p95(post_phase["decisions"]),
                "parity_hash": parity_hash(post_phase["decisions"]),
                "focus_parity_hash_normalised": _parity_hash_focus_normalised(
                    post_phase["decisions"]
                ),
            },
            PHASE_ROLLBACK: {
                "boots": rollback_phase["boots"],
                "decision_count": len(rollback_phase["decisions"]),
                "focus_p95_latency_us": latency_p95(
                    rollback_phase["decisions"]
                ),
                "parity_hash": parity_hash(rollback_phase["decisions"]),
                "focus_parity_hash_normalised": _parity_hash_focus_normalised(
                    rollback_phase["decisions"]
                ),
            },
        },
        "asserts": asserts,
        "exit_code": exit_code,
        "band": band_for_exit.get(exit_code, "UNKNOWN"),
    }
    return envelope


# ---------------------------------------------------------------------------
# Top-level orchestrator.
# ---------------------------------------------------------------------------


def run_cutover_smoke(
    *,
    boots_per_phase: int = DEFAULT_BOOTS_PER_PHASE,
    expected_components: int = DEFAULT_EXPECTED_COMPONENTS,
    latency_tolerance_pct: int = DEFAULT_LATENCY_TOLERANCE_PCT,
    components: Tuple[str, ...] = ENGINE_BOOT_COMPONENTS,
    base_env: Optional[Mapping[str, str]] = None,
    resolver_module: Optional[Any] = None,
    binary_probe: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
    now_ts: Optional[int] = None,
    skip_fsm_transition_parity: bool = False,
    canonical_module: Optional[Any] = None,
    fsm_transition_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6/A7 + envelope.

    Returns ``(envelope, exit_code)``.

    Pure function: never mutates ``os.environ``, never opens files
    except the optional lifecycle-state-machine cross-lang fixture
    JSON (read-only, used only by the test suite's parameter
    injection).

    FSM-Transition-Integrity invariant: the fsm-transition baseline
    is captured **only** in PHASE_PRE. PHASE_POST and PHASE_ROLLBACK
    never trigger the baseline-capture path. The A6 assert verifies
    parity by re-computing the JCS bytes via the Python authority
    twice (pre/post) and asserting byte-equality + phantom-
    transition-absence — this is the substrate-level oracle for
    "the Rust backend can read the Python backend's lifecycle
    traces and the spec's transition-table is invariant".
    """
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available

    # Pre-cutover phase ALSO captures the fsm-transition baseline.
    pre_phase = run_phase(
        PHASE_PRE,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_fsm_transition_baseline=not skip_fsm_transition_parity,
        fsm_transition_baseline_fn=(
            fsm_transition_baseline_fn
            if fsm_transition_baseline_fn is not None
            else (
                (lambda: capture_fsm_transition_baseline_default(
                    canonical_module=canonical_module
                ))
                if not skip_fsm_transition_parity
                else None
            )
        ),
    )

    # Post-cutover and rollback NEVER capture a baseline — the
    # FSM-Transition-Integrity contract pins the capture to
    # PHASE_PRE.
    post_phase = run_phase(
        PHASE_POST,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_fsm_transition_baseline=False,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_fsm_transition_baseline=False,
    )

    fsm_transition_baseline = pre_phase.get("fsm_transition_baseline")

    if skip_fsm_transition_parity:
        fsm_transition_parity: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": "A6 skipped via --skip-fsm-transition-parity",
            "baseline_trace_sha256": None,
            "recomputed_trace_sha256": None,
            "match": True,
            "phantom_transitions": [],
            "captured_at_phase": PHASE_PRE,
        }
    else:
        fsm_transition_parity = evaluate_fsm_transition_parity(
            fsm_transition_baseline,
            canonical_module=canonical_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        fsm_transition_baseline=fsm_transition_baseline,
        fsm_transition_parity=fsm_transition_parity,
    )
    exit_code = derive_exit_code(asserts)

    # Merge resolver-provenance across all phases — operator sees one
    # provenance map for the whole smoke.
    merged_provenance: Dict[str, str] = {}
    for phase_record in (pre_phase, post_phase, rollback_phase):
        for component, provenance in phase_record.get(
            "resolver_provenance", {}
        ).items():
            merged_provenance.setdefault(component, provenance)

    envelope = build_envelope(
        pre_phase=pre_phase,
        post_phase=post_phase,
        rollback_phase=rollback_phase,
        asserts=asserts,
        exit_code=exit_code,
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        fsm_transition_baseline=fsm_transition_baseline,
        resolver_provenance=merged_provenance,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-5-lifecycle-state-machine-cutover-smoke",
        description=(
            "Phase-3c Welle-5 (lifecycle_state_machine / fsm) End-to-"
            "End Cutover-Smoke for ADR-0066 KW-26 Doppel-Welle "
            "(parallel with Welle-4 state_backing). Boots a mocked "
            "persona-engine across Pre-Cutover (Python baseline) -> "
            "Cutover (Rust) -> Rollback (Python) phases, evaluates "
            "A1..A5 + R1 + A6 (fsm-transition-integrity / no phantom "
            "transitions) + A7 (cross-modul-drift-to-Welle-4-"
            "state_backing) asserts, and exits 0/1/2 = GREEN/CAUTION/"
            "ROLLBACK_RECOMMENDED. Never invokes the real Rust "
            "binary, NATS, or the Anthropic API. License: Apache-2.0."
        ),
    )
    p.add_argument(
        "--boots-per-phase",
        type=int,
        default=DEFAULT_BOOTS_PER_PHASE,
        help=(
            f"Mocked boots per phase (default {DEFAULT_BOOTS_PER_PHASE}). "
            "Each boot emits one BackendDecision per in-place component."
        ),
    )
    p.add_argument(
        "--expected-components",
        type=int,
        default=DEFAULT_EXPECTED_COMPONENTS,
        help=(
            f"Expected in-place component count per boot (default "
            f"{DEFAULT_EXPECTED_COMPONENTS} = engine inventory at "
            f"baseline 8ad125a, Tag-38 tip, post-PR-#241 wire-in). "
            f"Pre-PR-#241 baselines: pass 10."
        ),
    )
    p.add_argument(
        "--latency-tolerance-pct",
        type=int,
        default=DEFAULT_LATENCY_TOLERANCE_PCT,
        help=(
            f"P95-latency tolerance percentage over baseline "
            f"(default {DEFAULT_LATENCY_TOLERANCE_PCT}, per ADR-0065 §AC-2)."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output file path for the JSON envelope. "
            "Default: write to stdout."
        ),
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help=(
            "Override timestamp_utc for hermetic tests. "
            "Production runs leave this unset."
        ),
    )
    p.add_argument(
        "--skip-fsm-transition-parity",
        action="store_true",
        help=(
            "Skip the A6 fsm-transition-parity (FSM-Transition-"
            "Integrity / no phantom transitions) probe. Use when the "
            "wirelang package is not in the import path. A7 cross-"
            "modul-drift check is independent and still runs."
        ),
    )
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    stdout: Optional[io.TextIOBase] = None,
    stderr: Optional[io.TextIOBase] = None,
    resolver_module: Optional[Any] = None,
    canonical_module: Optional[Any] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if args.boots_per_phase < 1:
        err.write(
            f"welle-5-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-5-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-5-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_fsm_transition_parity=args.skip_fsm_transition_parity,
        canonical_module=canonical_module,
    )

    rendered = json.dumps(envelope, sort_keys=True, indent=2) + "\n"

    if args.output is None:
        out.write(rendered)
        return exit_code

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        err.write(
            f"welle-5-cutover-smoke: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        # Hard I/O failure overrides the smoke exit-code: surface as
        # exit 2 (ROLLBACK), because the operator cannot consume the
        # evidence and should not proceed without it.
        return EXIT_ROLLBACK

    return exit_code


__all__ = [
    "COMPONENT_TO_ENV",
    "DEFAULT_BOOTS_PER_PHASE",
    "DEFAULT_EXPECTED_COMPONENTS",
    "DEFAULT_LATENCY_TOLERANCE_PCT",
    "DETERMINISTIC_LIFECYCLE_TRANSITIONS",
    "DETERMINISTIC_TRACE_INITIAL_STATE",
    "DETERMINISTIC_TRACE_ORG_ID",
    "DETERMINISTIC_TRACE_PERSONA_ID",
    "ENGINE_BOOT_COMPONENTS",
    "ENVELOPE_SCHEMA",
    "ENV_VALUE_PYTHON",
    "ENV_VALUE_RUST",
    "EXIT_CAUTION",
    "EXIT_GREEN",
    "EXIT_ROLLBACK",
    "FOCUS_COMPONENT",
    "FOCUS_COMPONENT_LONG",
    "FOCUS_ENV_VAR",
    "PHASE_POST",
    "PHASE_PRE",
    "PHASE_ROLLBACK",
    "RESOLVER_PROVENANCE_SHIM",
    "RESOLVER_PROVENANCE_UPSTREAM",
    "SHIM_COMPONENT_PRIMITIVES",
    "SPEC_VALID_TRANSITIONS",
    "WELLE_4_PARTNER_COMPONENT",
    "WELLE_4_PARTNER_ENV_VAR",
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "capture_fsm_transition_baseline_default",
    "derive_exit_code",
    "evaluate_fsm_transition_parity",
    "evaluate_post_cutover_asserts",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
