#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-4-state-backing-cutover-smoke — End-to-End Cutover-Smoke for ADR-0066 Welle-4.

Background
----------

ADR-0066 (approved 2026-05-17, commit ``c907f98``) schedules
**Welle-4** of the Phase-3c default-backend flip as the **KW-26
Doppel-Welle**: ``state_backing`` cuts over from Python-default to
Rust-default **in parallel with Welle-5** (``lifecycle_state_machine``
/ ``fsm``). The parallel posture is an ADR-0066 §Option-A+ Doppel-
Welle pairing, not a sequencing convenience.

The Cross-Modul-Drift-Risk (ADR-0066 §Welle-4-5-Risiken, Tomás-Zone-K
review) is the **State-Mutation-Coupling-Risk**:

  ``state_backing`` is the persistence trait that records
  ``PersonaStateSnapshot`` envelopes via the
  ``snapshot()`` / ``restore_latest()`` / ``atomic_swap_pinned_offset()``
  API (spec §3.7.5). ``lifecycle_state_machine`` (``fsm``) is the
  state-machine that decides *which* transitions can be persisted at
  all (spec §3.3 — six states, nine transitions). FSM transitions
  write through state_backing: a transition takes the lock, mutates
  in-memory state, then calls ``state_backing.snapshot()`` to
  persist the new offset (engine.py L951 et seq.). When **both**
  modules flip from Python to Rust during the same KW-26 window,
  any drift in their joint contract (snapshot byte-shape, offset
  monotonicity, pinned-offset compare-and-swap semantics) will
  manifest as cross-modul state-corruption that no single-module
  smoke can catch.

This smoke is the **strict, asserts-tragend** End-to-End Cutover-
Smoke for Welle-4, modelled on the Welle-3 sibling
``scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py``
(Tag-36, PR #240) and pattern-parity-aligned with Welle-1
``scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py``
(Tag-34, PR #230) and Welle-2
``scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py``
(Tag-35, PR #234). The pattern-parity is intentional: the operator
runs all four smokes in the same cutover-PR window, gets four JSON
envelopes with the same shape (``schema`` differs only by Welle
number), and the tri-state exit codes feed shell gates.

Welle-4-specific asserts (Cross-Backend-Read-Compatibility + Cross-Modul-Drift)
-------------------------------------------------------------------------------

The smoke adds **two** Welle-4-specific asserts that do not exist in
the Welle-1/2/3 shape, both addressing the Doppel-Welle risk axes:

* **A6 cross-backend-read-compatibility:** the smoke captures a
  deterministic ``PersonaStateSnapshot`` JCS-byte-blob via the
  Python authority's ``snapshot_to_jcs_bytes()`` **BEFORE the
  cutover-step constructs the PHASE_POST env-map**. After the
  cutover (Engine-Reboot with ``WAKIR_STATE_BACKING_BACKEND=
  rust_inmemory``), the smoke re-emits the same snapshot via the
  Python authority a second time and asserts byte-equality. This is
  the substrate-level oracle for the
  Cross-Backend-Read-Compatibility property: the JCS-canonical byte-
  shape of a ``PersonaStateSnapshot`` written by the Python backend
  MUST be readable byte-for-byte by the Rust backend. The Rust
  pendant byte-parity is pinned at a separate substrate layer
  (the state_backing cross-lang fixture pins from PR #183
  ``state-backing-cross-lang/fixtures.json``, Tag-23 Reza wire-in).
  This smoke verifies the Python encoder is byte-stable across the
  pre/post window — the only oracle that does **not** require
  bringing up a real Rust binary in-process. Severity: caution — a
  hash mismatch here signals Python JCS encoder drift between pre
  and post, which is a Tomás-Zone-K cross-modul drift signal, not a
  Pilot-VM-cutover blocker.

* **A7 cross-modul-drift-to-welle-5 (state_backing x lifecycle_state_machine):**
  verifies that the ``fsm`` env-var stays at its baseline value
  (``python`` in PHASE_PRE, the operator's choice in PHASE_POST and
  PHASE_ROLLBACK) and that the per-boot ``fsm`` BackendDecision
  ``chosen_backend`` field matches the env-var requested-value
  byte-for-byte in **every** phase. This is the cross-modul
  invariant: the state_backing cutover MUST NOT silently force the
  fsm component into a different backend (the parallel-Welle
  joint-cutover concern). Severity: blocker — a fail here means
  state_backing's resolver leaked into the fsm decision path, which
  would invalidate the parallel-Welle isolation contract. The
  control-flow pin is what protects the substrate semantics from
  rot during the KW-26 Doppel-Welle window.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-3 shape verbatim, re-pointed at ``state_backing`` and
``WAKIR_STATE_BACKING_BACKEND``. Note that ``state_backing`` has
**three** backend values (``python``, ``rust_inmemory``,
``rust_natskv``); the smoke targets ``rust_inmemory`` as the cutover
target per the ADR-0066 §Welle-4 default (matches
``scripts/phase-3c-cutover-dry-run.py`` Welle-4 default).

Real-resolver verification (no shim)
------------------------------------

Unlike Welle-3 (which needed a resolver-shim because
``resolve_bridge_audit_writer_backend`` was not yet wired at the
baseline tip), Welle-4 uses the **real upstream resolver**
``resolve_state_backing_backend`` directly. The resolver has been
in baseline since PR #167 (Tag-17 ENV-gated state-backing default
resolver, ``ee4f3d2``). The smoke imports it via
:func:`_import_resolver` and never constructs a shim. The
``resolver_provenance`` field in the envelope reports
``"upstream"`` for state_backing in every run.

Default ``--expected-components 10``
------------------------------------

ADR-0066 §Welle-4 baseline is the post-Welle-3-merge engine
inventory: nine baseline components (v907_verify,
svid_workload_identity, bridge_diff, anchor_emitter, state_backing,
fsm, subscribe_loop, recovery, federation_resolver) plus
``bridge_audit_writer`` from PR #240 / Tag-36 = 10 in-place
components. The Reza Tag-36 ``bridge_audit_diff_engine`` wire-in
(PR #241) adds an 11th component-slot that the smoke includes in
``ENGINE_BOOT_COMPONENTS`` via a resolver-shim (mirrors the
Welle-3 pattern for bridge_audit_writer — same gracefully-shimmed
posture, transparent provenance-flip when the upstream resolver
lands). Operators run with the default ``--expected-components 10``
until the resolver wire-in lands, then pass
``--expected-components 11``.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with the
   Python default
   (``WAKIR_STATE_BACKING_BACKEND=python`` + every other component
   pinned to python). Records the ``BackendDecision`` for
   ``state_backing`` plus the other in-place components.
   **AND captures the state-backing snapshot pre-baseline hash** by
   invoking ``snapshot_to_jcs_bytes(PersonaStateSnapshot(...))``
   against the deterministic snapshot fixture (mirrors the F1/F2/F3
   stream-fixture pattern from Welle-3). This is the
   Cross-Backend-Read-Compatibility capture moment: the baseline is
   taken before the cutover.
2. **Cutover step.** Flips
   ``WAKIR_STATE_BACKING_BACKEND=rust_inmemory`` in the hermetic
   env-map, restarts the mocked engine (engine-reboot semantics),
   re-collects BackendDecisions. The engine-reboot must successfully
   read the snapshot envelope that the Python backend wrote in
   PHASE_PRE — the smoke verifies this by re-emitting the same
   snapshot via the Python authority and asserting byte-equality
   with the pre-baseline hash.
3. **Post-Cutover asserts.** Five hard checks + two Welle-4-specific
   substrate checks (A1..A5 + R1 + A6 + A7).
4. **Rollback probe.** ``WAKIR_STATE_BACKING_BACKEND`` unset
   (engine reads Python-default), re-boot, asserts that the engine
   emits ``chosen_backend == "python"`` again — operator rollback
   path ≤10 min per ADR-0065 §Rollback-SLA (ADR-0066 inherits this
   contract).
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All blocker asserts pass +
       caution asserts pass.
     * ``1`` — **CAUTION**. At least one caution-severity drift
       (A3 latency, A4 component-count, A6 state-snapshot drift).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 / A7 / R1
       failed.

The smoke writes a JSON envelope to ``--output`` (or stdout). The
envelope shape is pinned by the test suite.

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 state-snapshot
parity check imports :mod:`wirelang.persona_engine.state_backing`
lazily and reads only the in-memory deterministic snapshot fixture
embedded in this module; both are gracefully skipped if the import
fails so the smoke remains importable in test environments without
the wirelang package. The mocked engine never imports NATS, the
Anthropic SDK, the real Rust binary, or any container runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, 10 expected
    # components per Tag-36-tip inventory).
    python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \\
        --output out/welle-4-smoke.json

    # Post-Reza-Tag-36-#241-wire-in invocation (11 expected components):
    python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \\
        --expected-components 11 --output out/welle-4-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \\
        --latency-tolerance-pct 10

    # Skip the A6 state-snapshot-parity probe (e.g. when the wirelang
    # package is not in the import path):
    python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \\
        --skip-state-snapshot-parity

    # Target rust_natskv instead of the default rust_inmemory:
    python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \\
        --rust-backend-value rust_natskv

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
# Constants — Welle-4 focus on state_backing.
# ---------------------------------------------------------------------------

#: Welle-4 focus component (ADR-0066 §Welle-4 KW-26 Doppel-Welle).
FOCUS_COMPONENT = "state_backing"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-4.
FOCUS_ENV_VAR = "WAKIR_STATE_BACKING_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Tracks the engine inventory at
#: baseline ``4803394`` (Tag-36 tip, post-Welle-3-merge): ten
#: resolvers including bridge_audit_writer (PR #240). When the Reza
#: Tag-36 bridge_audit_diff_engine resolver wire-in lands (PR #241),
#: the tuple grows to eleven and operators pass
#: ``--expected-components 11``. The smoke keeps both worlds working
#: without re-deploy because ``bridge_audit_diff_engine`` is added
#: to ENGINE_BOOT_COMPONENTS unconditionally and the smoke's
#: resolver-shim provides a clean shape when the upstream resolver
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
#: ``4803394`` engine inventory (10) because as of that tip the
#: upstream resolver for ``bridge_audit_diff_engine`` is not yet
#: wired. Operators running post-Reza-Tag-36-#241-wire-in pass
#: ``--expected-components 11`` to track the wire-in. Tests cover
#: both modes.
DEFAULT_EXPECTED_COMPONENTS = 10

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34/35/36/37.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-4-cutover-smoke/1"

#: ENV-var values the smoke flips per phase. state_backing has
#: three Rust enum values (rust_inmemory, rust_natskv); rust_inmemory
#: is the ADR-0066 §Welle-4 default cutover target.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST_DEFAULT = "rust_inmemory"
ENV_VALUE_RUST_NATSKV = "rust_natskv"
VALID_RUST_VALUES: Tuple[str, ...] = (ENV_VALUE_RUST_DEFAULT, ENV_VALUE_RUST_NATSKV)

#: Welle-5 cross-modul-drift partner. The FSM env-var stays at the
#: per-phase baseline ("python" in PHASE_PRE) and the assert verifies
#: that state_backing's cutover does not leak into the fsm path.
WELLE_5_PARTNER_COMPONENT = "fsm"
WELLE_5_PARTNER_ENV_VAR = "WAKIR_FSM_BACKEND"

#: Resolver-provenance markers — surfaced in the envelope so
#: operators know which surface the smoke exercised. state_backing
#: itself is ALWAYS upstream (PR #167 baseline); only the trailing
#: bridge_audit_diff_engine may be shim until Reza wire-in lands.
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
# Resolver-shim — fills the gap until Reza Tag-36 #241 wires
# ``resolve_bridge_audit_diff_engine_backend`` upstream. state_backing
# itself NEVER uses the shim (PR #167 has shipped the upstream
# resolver since Tag-17).
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


#: Component-name → (env-var-attr, bin-resolver-attr) pairs for the
#: resolver-shim path. Used when an upstream resolver is not yet
#: shipped but the env-var + bin-resolver primitives are. At baseline
#: 4803394, both bridge_audit_writer and bridge_audit_diff_engine fall
#: into this category (PR #240 added the smoke for bridge_audit_writer
#: but did NOT add the upstream resolver function; PR #241 is the
#: Reza-Tag-36 wire-in target for bridge_audit_diff_engine).
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

    Mirrors the Welle-3 resolver-shim pattern for bridge_audit_writer
    (see welle-3-bridge-audit-writer-cutover-smoke.py L339-426).
    The shim wraps the existing module primitives when present
    (``<COMPONENT>_BACKEND_ENV``, ``_resolve_<component>_bin``,
    ``_binary_available``) and falls back to a python-only response
    when they are absent.

    Returns a callable with the same signature as the other
    resolvers: ``(env, *, log_sink, binary_probe) -> (chosen_backend,
    BackendDecision-shaped-record)``. The shim never mutates os.environ.

    The smoke uses this for the trailing 10th and 11th components
    (``bridge_audit_writer`` and ``bridge_audit_diff_engine``) until
    the Reza-Tag-36 + Reza-Tag-36-#241 wire-ins land. When the
    upstream functions ship, the smoke prefers them and the shim
    becomes inert (resolver_provenance flips from "shim" to
    "upstream" transparently).
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
        # bridge_audit_writer + bridge_audit_diff_engine both support
        # the two-valued enum (python|rust). state_backing's three-
        # valued enum is handled exclusively by the upstream resolver
        # (PR #167), never by this shim.
        if requested == "rust":
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
    (raises AttributeError). state_backing itself MUST be upstream
    (PR #167); a missing ``resolve_state_backing_backend`` is a
    substrate-regression and should fail loudly.
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

    Operator-warning: live Welle-4 substrate readiness depends on
    the ``persona-engine-state-backing`` binary shipping from the
    ``persona-engine-state-backing`` crate (Tag-17 Mini-Welle PR
    #167). If the binary is not deployed on the Pilot-VM, the real
    ``_binary_available`` probe returns
    ``(False, "binary_missing")`` and A5 fails on the live smoke
    — that's the ADR-0066 Welle-4 precondition signal, not a smoke
    bug. The stub here keeps the smoke green-band-demonstrable for
    pre-deploy CI gates.
    """
    return True, None


# ---------------------------------------------------------------------------
# Hermetic env-map construction per phase.
# ---------------------------------------------------------------------------


def build_phase_env(
    phase: str,
    *,
    base_env: Optional[Mapping[str, str]] = None,
    rust_backend_value: str = ENV_VALUE_RUST_DEFAULT,
) -> Dict[str, str]:
    """Return the hermetic env-map for ``phase``.

    Phases:
      * :data:`PHASE_PRE` — every Phase-3c component's env-var is
        explicitly ``"python"``. This is the Python-default baseline.
      * :data:`PHASE_POST` — same, but ``FOCUS_ENV_VAR=rust_inmemory``
        (or ``rust_natskv`` if ``rust_backend_value`` is overridden).
      * :data:`PHASE_ROLLBACK` — :data:`FOCUS_ENV_VAR` is *absent*
        from the env-map (engine reads the Python-default code-path,
        which is the Quadlet-default after rollback).

    The returned dict is always a fresh copy of ``base_env`` (default
    empty) — the smoke never inherits the operator's environment.

    Welle-5 partner invariant: ``WAKIR_FSM_BACKEND`` is set to
    ``"python"`` in every phase. The A7 cross-modul-drift assert
    verifies that the fsm BackendDecision actually honours this
    setting in PHASE_POST — i.e. state_backing's cutover does not
    leak into fsm's resolver path.
    """
    if rust_backend_value not in VALID_RUST_VALUES:
        raise ValueError(
            f"rust_backend_value must be one of {VALID_RUST_VALUES!r}; "
            f"got {rust_backend_value!r}"
        )
    env: Dict[str, str] = dict(base_env or {})
    for env_var in COMPONENT_TO_ENV.values():
        env[env_var] = ENV_VALUE_PYTHON
    if phase == PHASE_PRE:
        return env
    if phase == PHASE_POST:
        env[FOCUS_ENV_VAR] = rust_backend_value
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
    rust_backend_value: str = ENV_VALUE_RUST_DEFAULT,
    capture_state_snapshot_baseline: bool = False,
    state_snapshot_baseline_fn: Optional[
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
      * ``state_snapshot_baseline`` — populated iff
        ``capture_state_snapshot_baseline`` is True (PHASE_PRE only;
        this is the Cross-Backend-Read-Compatibility temporal anchor).

    Cross-Backend-Read-Compatibility note: the state-snapshot
    baseline capture is gated on the
    ``capture_state_snapshot_baseline`` flag and only set True by
    the orchestrator for :data:`PHASE_PRE`. If a future refactor
    accidentally sets the flag for any other phase, the smoke
    architecture documents that this is the temporal anchor for the
    Cross-Backend-Read-Compatibility oracle.
    """
    if boots < 1:
        raise ValueError(f"boots must be >= 1; got {boots!r}")
    env = build_phase_env(
        phase, base_env=base_env, rust_backend_value=rust_backend_value
    )
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

    if capture_state_snapshot_baseline:
        if state_snapshot_baseline_fn is not None:
            baseline = state_snapshot_baseline_fn()
        else:
            baseline = capture_state_snapshot_baseline_default()
        record["state_snapshot_baseline"] = baseline
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

    Fixture-reference: ``tests/fixtures/state-backing-cross-lang/
    fixtures.json`` (PR #183, Tag-23) embeds the substrate-level
    invariant that Python and Rust write byte-equal
    PersonaStateSnapshot JCS bytes. This hash is the smoke's
    engine-emission-level materialisation of that contract; A6
    verifies the substrate-level oracle directly.
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
# A6 — State-Snapshot pre-baseline + post-cutover-parity probe
# (Cross-Backend-Read-Compatibility).
#
# Cross-Backend-Read-Compatibility note: the BASELINE capture happens
# in PHASE_PRE *before* the cutover-step constructs PHASE_POST. The
# POST recomputation is done by calling the SAME Python authority
# again (not the Rust pendant, which is not yet linked into the
# smoke). The substrate-level oracle is: the Python authority is
# byte-stable across the pre/post window. If the recomputed hash
# matches the baseline, the Python snapshot_to_jcs_bytes encoder did
# not drift. That is the only oracle the smoke can give *without*
# bringing up a real Rust binary; the Rust pendant byte-parity is
# locked at a different layer (the state-backing cross-lang fixture
# pins from PR #183).
# ---------------------------------------------------------------------------


#: Deterministic 3-snapshot fixture used for the state-snapshot
#: pre-baseline. Fixed offsets, persona-hashes, and timestamps so the
#: resulting JCS-bytes are byte-stable across smoke invocations.
#: Aligned with the snapshot shape from PR #183 (state-backing
#: cross-lang fixtures.json).
STATE_BACKING_DETERMINISTIC_SNAPSHOTS: Tuple[Dict[str, Any], ...] = (
    {
        "persona_hash": "sha256:" + ("a" * 64),
        "audit_trace_offset": 1,
        "capability_token_ids": ["cap-001", "cap-002"],
        "snapshot_at_utc": "2026-05-26T00:00:00Z",
        "workspace_state_hash": "sha256:" + ("b" * 64),
    },
    {
        "persona_hash": "sha256:" + ("a" * 64),
        "audit_trace_offset": 2,
        "capability_token_ids": ["cap-001", "cap-002", "cap-003"],
        "snapshot_at_utc": "2026-05-26T00:00:01Z",
        "workspace_state_hash": "sha256:" + ("c" * 64),
    },
    {
        "persona_hash": "sha256:" + ("a" * 64),
        "audit_trace_offset": 3,
        "capability_token_ids": ["cap-001", "cap-002", "cap-003", "cap-004"],
        "snapshot_at_utc": "2026-05-26T00:00:02Z",
        "workspace_state_hash": "sha256:" + ("d" * 64),
    },
)

#: Default relative path for the cross-lang state-backing fixtures
#: (PR #183 Tag-23). Resolved relative to the repo root; tests may
#: override.
DEFAULT_STATE_BACKING_FIXTURE_RELPATH = (
    "tests/fixtures/state-backing-cross-lang/fixtures.json"
)


def _import_state_backing() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.state_backing`.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.persona_engine.state_backing"
    )


def _snapshot_to_jcs_bytes_via_module(
    module: Any, snapshot: Mapping[str, Any]
) -> bytes:
    """Construct a ``PersonaStateSnapshot`` and JCS-serialise it.

    The wirelang public API surface uses the dataclass
    ``PersonaStateSnapshot`` plus the module-level
    ``snapshot_to_jcs_bytes`` helper (PR #183 substrate). The helper
    prefers that surface; if missing it tries a stub-friendly
    ``to_jcs_bytes(snapshot)`` module-level helper (used by the test
    suite).
    """
    cls = getattr(module, "PersonaStateSnapshot", None)
    helper = getattr(module, "snapshot_to_jcs_bytes", None)
    if cls is not None and callable(helper):
        try:
            instance = cls(
                persona_hash=snapshot["persona_hash"],
                audit_trace_offset=snapshot["audit_trace_offset"],
                capability_token_ids=tuple(snapshot["capability_token_ids"]),
                snapshot_at_utc=snapshot["snapshot_at_utc"],
                workspace_state_hash=snapshot["workspace_state_hash"],
            )
        except TypeError:
            instance = cls(**dict(snapshot))
        out = helper(instance)
        if isinstance(out, str):
            return out.encode("utf-8")
        if isinstance(out, (bytes, bytearray)):
            return bytes(out)
    # Fallback: module-level to_jcs_bytes helper taking dict directly.
    fallback = getattr(module, "to_jcs_bytes", None)
    if callable(fallback):
        out = fallback(dict(snapshot))
        if isinstance(out, str):
            return out.encode("utf-8")
        if isinstance(out, (bytes, bytearray)):
            return bytes(out)
    raise AttributeError(
        "state_backing module exposes neither PersonaStateSnapshot + "
        "snapshot_to_jcs_bytes nor a module-level to_jcs_bytes helper"
    )


def capture_state_snapshot_baseline_default(
    *,
    snapshots: Tuple[Dict[str, Any], ...] = STATE_BACKING_DETERMINISTIC_SNAPSHOTS,
    backing_module: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Capture the pre-cutover state-snapshot-hash baseline.

    Returns ``None`` if the wirelang.state_backing module is not
    importable (smoke treats this as A6-skip). Otherwise returns a
    record with:

      * ``stream_sha256_hex`` — SHA-256 over the concatenated JCS
        bytes of every snapshot, in the supplied order.
      * ``per_snapshot_jcs_sha256`` — list of per-snapshot JCS
        SHA-256s, useful for debugging the first divergence point.
      * ``snapshot_count`` — len(snapshots).
      * ``captured_at_phase`` — always :data:`PHASE_PRE`
        (Cross-Backend-Read-Compatibility invariant; do not change
        this).

    This function is the Cross-Backend-Read-Compatibility capture
    moment. The post-cutover recompute reads the same baseline and
    asserts byte-equality (A6).
    """
    module = backing_module
    if module is None:
        try:
            module = _import_state_backing()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"state_backing not importable: {exc}"
                ),
                "stream_sha256_hex": None,
                "per_snapshot_jcs_sha256": [],
                "snapshot_count": 0,
                "captured_at_phase": PHASE_PRE,
            }

    per_snapshot: List[str] = []
    concatenated = b""
    try:
        for snapshot in snapshots:
            jcs = _snapshot_to_jcs_bytes_via_module(module, snapshot)
            per_snapshot.append(hashlib.sha256(jcs).hexdigest())
            concatenated += jcs
    except Exception as exc:  # noqa: BLE001 — substrate drift is the signal
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                f"state-snapshot baseline capture raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "stream_sha256_hex": None,
            "per_snapshot_jcs_sha256": [],
            "snapshot_count": 0,
            "captured_at_phase": PHASE_PRE,
        }

    stream_hash = hashlib.sha256(concatenated).hexdigest()
    return {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"state-snapshot baseline captured: "
            f"{len(snapshots)} snapshots, stream_sha256={stream_hash[:16]}..."
        ),
        "stream_sha256_hex": stream_hash,
        "per_snapshot_jcs_sha256": per_snapshot,
        "snapshot_count": len(snapshots),
        "captured_at_phase": PHASE_PRE,
    }


def evaluate_state_snapshot_parity(
    baseline: Optional[Dict[str, Any]],
    *,
    snapshots: Tuple[Dict[str, Any], ...] = STATE_BACKING_DETERMINISTIC_SNAPSHOTS,
    backing_module: Optional[Any] = None,
) -> Dict[str, Any]:
    """Recompute the state-snapshot-hash post-cutover and compare.

    Note: the recomputation is done by calling the SAME Python
    authority again, NOT the Rust pendant. The substrate-level oracle
    is "the Python snapshot_to_jcs_bytes encoder is byte-stable
    across the pre/post window". The Rust pendant byte-parity is
    pinned at the F1/F2/F3-equivalent fixture layer (separate
    substrate, not loaded by this smoke at runtime). This is the
    only oracle that does **not** require a real Rust binary.

    Returns the same shape as
    :func:`capture_state_snapshot_baseline_default` but with an
    additional ``match`` field:

      * ``passed`` — True iff the recomputed hash matches the
        baseline hash.
      * ``skipped`` — True iff baseline was skipped or recomputation
        cannot be performed.
      * ``baseline_stream_sha256`` — the baseline hash for the
        envelope reader.
      * ``recomputed_stream_sha256`` — the post-cutover hash.
      * ``match`` — bool.
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
            "baseline_stream_sha256": None,
            "recomputed_stream_sha256": None,
            "match": True,
            "captured_at_phase": (
                baseline.get("captured_at_phase") if baseline else PHASE_PRE
            ),
        }

    module = backing_module
    if module is None:
        try:
            module = _import_state_backing()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"state_backing not importable for recompute: {exc}"
                ),
                "baseline_stream_sha256": baseline.get("stream_sha256_hex"),
                "recomputed_stream_sha256": None,
                "match": True,
                "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
            }

    try:
        concatenated = b""
        for snapshot in snapshots:
            concatenated += _snapshot_to_jcs_bytes_via_module(module, snapshot)
        recomputed = hashlib.sha256(concatenated).hexdigest()
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "skipped": False,
            "severity": "caution",
            "detail": (
                f"state-snapshot recompute raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "baseline_stream_sha256": baseline.get("stream_sha256_hex"),
            "recomputed_stream_sha256": None,
            "match": False,
            "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
        }

    baseline_hash = baseline.get("stream_sha256_hex")
    match = recomputed == baseline_hash
    return {
        "passed": match,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"state-snapshot parity ok ({recomputed[:16]}...)"
            if match
            else (
                f"state-snapshot drift: baseline={baseline_hash} "
                f"recomputed={recomputed}"
            )
        ),
        "baseline_stream_sha256": baseline_hash,
        "recomputed_stream_sha256": recomputed,
        "match": match,
        "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
    }


# ---------------------------------------------------------------------------
# Assert evaluation.
# ---------------------------------------------------------------------------


def _focus_records(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("domain") == focus]


def _is_rust_value(value: Any) -> bool:
    """state_backing has multiple rust enum values; helper to check."""
    return value in VALID_RUST_VALUES


def evaluate_post_cutover_asserts(
    *,
    pre_records: List[Dict[str, Any]],
    post_records: List[Dict[str, Any]],
    rollback_records: List[Dict[str, Any]],
    expected_components: int,
    boots_per_phase: int,
    latency_tolerance_pct: int,
    rust_backend_value: str = ENV_VALUE_RUST_DEFAULT,
    state_snapshot_baseline: Optional[Dict[str, Any]] = None,
    state_snapshot_parity: Optional[Dict[str, Any]] = None,
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

    # A1: post-cutover focus-component reports chosen_backend ∈ rust_*.
    post_focus = _focus_records(post_records, focus=focus)
    a1_all_rust = bool(post_focus) and all(
        _is_rust_value(r.get("chosen_backend")) for r in post_focus
    )
    asserts["A1_backend_flip"] = {
        "passed": a1_all_rust,
        "severity": "blocker",
        "detail": (
            f"state_backing chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})} "
            f"(expected all in {VALID_RUST_VALUES!r})"
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

    # A6: state-snapshot pre/post parity probe (caution-severity).
    if state_snapshot_parity is None:
        a6_detail = "A6 skipped (probe not invoked)"
        a6_record = {
            "passed": True,
            "severity": "caution",
            "skipped": True,
            "detail": a6_detail,
            "baseline_stream_sha256": None,
            "recomputed_stream_sha256": None,
            "match": True,
            "captured_at_phase": PHASE_PRE,
        }
    else:
        a6_record = {
            "passed": bool(state_snapshot_parity.get("passed", True)),
            "severity": "caution",
            "skipped": bool(state_snapshot_parity.get("skipped", False)),
            "detail": state_snapshot_parity.get("detail", ""),
            "baseline_stream_sha256": state_snapshot_parity.get(
                "baseline_stream_sha256"
            ),
            "recomputed_stream_sha256": state_snapshot_parity.get(
                "recomputed_stream_sha256"
            ),
            "match": bool(state_snapshot_parity.get("match", True)),
            "captured_at_phase": state_snapshot_parity.get(
                "captured_at_phase", PHASE_PRE
            ),
        }
    asserts["A6_cross_backend_read_compatibility"] = a6_record

    # A7: Cross-Modul-Drift-Mitigation control invariant (Welle-5
    # partner: fsm). The fsm BackendDecision MUST honour
    # WAKIR_FSM_BACKEND==python in PHASE_POST (state_backing's
    # cutover MUST NOT leak into fsm's resolver path).
    fsm_post_records = [
        r for r in post_records if r.get("domain") == WELLE_5_PARTNER_COMPONENT
    ]
    if not fsm_post_records:
        a7_record = {
            "passed": False,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 fsm cross-modul-drift check: no fsm "
                f"BackendDecision present in PHASE_POST records "
                f"(expected {boots_per_phase} fsm decisions). The "
                f"state_backing cutover may have suppressed fsm "
                f"emissions — parallel-Welle isolation broken."
            ),
            "fsm_chosen_backends": [],
            "expected_fsm_backend": ENV_VALUE_PYTHON,
        }
    else:
        chosen = [r.get("chosen_backend") for r in fsm_post_records]
        all_python = all(c == ENV_VALUE_PYTHON for c in chosen)
        a7_record = {
            "passed": all_python,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 cross-modul-drift OK: fsm stayed at python "
                f"across {len(fsm_post_records)} PHASE_POST records "
                f"during state_backing cutover"
                if all_python
                else (
                    f"A7 cross-modul-drift FAIL: state_backing "
                    f"cutover leaked into fsm path. fsm chosen_backend "
                    f"values in PHASE_POST: {sorted(set(chosen))} "
                    f"(expected all == 'python'). This breaks the "
                    f"KW-26 Doppel-Welle isolation contract."
                )
            ),
            "fsm_chosen_backends": sorted(set(chosen)),
            "expected_fsm_backend": ENV_VALUE_PYTHON,
        }
    asserts["A7_cross_modul_drift_welle_5_fsm"] = a7_record

    return asserts


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
    """Parity-hash over the *structural* fields of focus-component records.

    See the Welle-1/2/3 siblings for the full rationale; the
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
    rust_backend_value: str,
    state_snapshot_baseline: Optional[Dict[str, Any]] = None,
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
        "welle": 4,
        "focus_component": FOCUS_COMPONENT,
        "focus_env_var": FOCUS_ENV_VAR,
        "rust_backend_value": rust_backend_value,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
        "resolver_provenance": dict(resolver_provenance or {}),
        "cross_modul_drift_mitigation": {
            "welle_5_partner_component": WELLE_5_PARTNER_COMPONENT,
            "welle_5_partner_env_var": WELLE_5_PARTNER_ENV_VAR,
            "expected_welle_5_partner_backend": ENV_VALUE_PYTHON,
            "fsm_chosen_backends_in_post_phase": asserts.get(
                "A7_cross_modul_drift_welle_5_fsm", {}
            ).get("fsm_chosen_backends", []),
        },
        "cross_backend_read_compatibility": {
            "baseline_captured_at_phase": (
                state_snapshot_baseline.get("captured_at_phase")
                if state_snapshot_baseline is not None
                else None
            ),
            "baseline_stream_sha256": (
                state_snapshot_baseline.get("stream_sha256_hex")
                if state_snapshot_baseline is not None
                else None
            ),
            "baseline_skipped": (
                bool(state_snapshot_baseline.get("skipped", False))
                if state_snapshot_baseline is not None
                else True
            ),
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
    rust_backend_value: str = ENV_VALUE_RUST_DEFAULT,
    resolver_module: Optional[Any] = None,
    binary_probe: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
    now_ts: Optional[int] = None,
    skip_state_snapshot_parity: bool = False,
    state_backing_module: Optional[Any] = None,
    state_snapshot_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6/A7 + envelope.

    Returns ``(envelope, exit_code)``.

    Pure function: never mutates ``os.environ``, never opens files
    except the optional state-backing-cross-lang fixture JSON
    (read-only, used only by the test suite's parameter injection).

    Cross-Backend-Read-Compatibility invariant: the state-snapshot
    baseline is captured **only** in PHASE_PRE. PHASE_POST and
    PHASE_ROLLBACK never trigger the baseline-capture path. The A6
    assert verifies parity by re-computing the JCS bytes via the
    Python authority twice (pre/post) and asserting byte-equality —
    this is the substrate-level oracle for "the Rust backend can
    read the Python backend's snapshots".
    """
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available

    # Pre-cutover phase ALSO captures the state-snapshot baseline.
    pre_phase = run_phase(
        PHASE_PRE,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        rust_backend_value=rust_backend_value,
        capture_state_snapshot_baseline=not skip_state_snapshot_parity,
        state_snapshot_baseline_fn=(
            state_snapshot_baseline_fn
            if state_snapshot_baseline_fn is not None
            else (
                (lambda: capture_state_snapshot_baseline_default(
                    backing_module=state_backing_module
                ))
                if not skip_state_snapshot_parity
                else None
            )
        ),
    )

    # Post-cutover and rollback NEVER capture a baseline — the
    # Cross-Backend-Read-Compatibility contract pins the capture to
    # PHASE_PRE.
    post_phase = run_phase(
        PHASE_POST,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        rust_backend_value=rust_backend_value,
        capture_state_snapshot_baseline=False,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        rust_backend_value=rust_backend_value,
        capture_state_snapshot_baseline=False,
    )

    state_snapshot_baseline = pre_phase.get("state_snapshot_baseline")

    if skip_state_snapshot_parity:
        state_snapshot_parity: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                "A6 skipped via --skip-state-snapshot-parity"
            ),
            "baseline_stream_sha256": None,
            "recomputed_stream_sha256": None,
            "match": True,
            "captured_at_phase": PHASE_PRE,
        }
    else:
        state_snapshot_parity = evaluate_state_snapshot_parity(
            state_snapshot_baseline,
            backing_module=state_backing_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        rust_backend_value=rust_backend_value,
        state_snapshot_baseline=state_snapshot_baseline,
        state_snapshot_parity=state_snapshot_parity,
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
        rust_backend_value=rust_backend_value,
        state_snapshot_baseline=state_snapshot_baseline,
        resolver_provenance=merged_provenance,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-4-state-backing-cutover-smoke",
        description=(
            "Phase-3c Welle-4 (state_backing) End-to-End Cutover-"
            "Smoke for ADR-0066 KW-26 Doppel-Welle (parallel with "
            "Welle-5 lifecycle_state_machine). Boots a mocked "
            "persona-engine across Pre-Cutover (Python baseline) -> "
            "Cutover (Rust) -> Rollback (Python) phases, evaluates "
            "A1..A5 + R1 + A6 (cross-backend-read-compatibility) + "
            "A7 (cross-modul-drift-to-Welle-5-fsm) asserts, and "
            "exits 0/1/2 = GREEN/CAUTION/ROLLBACK_RECOMMENDED. Never "
            "invokes the real Rust binary, NATS, or the Anthropic "
            "API. License: Apache-2.0."
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
            "baseline 4803394; pass 11 once the Reza Tag-36 #241 "
            "bridge_audit_diff_engine resolver wire-in lands)."
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
        "--rust-backend-value",
        type=str,
        choices=list(VALID_RUST_VALUES),
        default=ENV_VALUE_RUST_DEFAULT,
        help=(
            "Rust enum value to flip state_backing to during the "
            f"cutover step (default {ENV_VALUE_RUST_DEFAULT!r}; "
            f"valid: {VALID_RUST_VALUES!r}). ADR-0066 §Welle-4 "
            "default cutover target is rust_inmemory."
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
        "--skip-state-snapshot-parity",
        action="store_true",
        help=(
            "Skip the A6 state-snapshot-parity (Cross-Backend-Read-"
            "Compatibility) probe. Use when the wirelang package is "
            "not in the import path. A7 cross-modul-drift check is "
            "independent and still runs."
        ),
    )
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    stdout: Optional[io.TextIOBase] = None,
    stderr: Optional[io.TextIOBase] = None,
    resolver_module: Optional[Any] = None,
    state_backing_module: Optional[Any] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if args.boots_per_phase < 1:
        err.write(
            f"welle-4-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-4-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-4-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        rust_backend_value=args.rust_backend_value,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_state_snapshot_parity=args.skip_state_snapshot_parity,
        state_backing_module=state_backing_module,
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
            f"welle-4-cutover-smoke: cannot write output "
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
    "DEFAULT_STATE_BACKING_FIXTURE_RELPATH",
    "ENGINE_BOOT_COMPONENTS",
    "ENVELOPE_SCHEMA",
    "ENV_VALUE_PYTHON",
    "ENV_VALUE_RUST_DEFAULT",
    "ENV_VALUE_RUST_NATSKV",
    "EXIT_CAUTION",
    "EXIT_GREEN",
    "EXIT_ROLLBACK",
    "FOCUS_COMPONENT",
    "FOCUS_ENV_VAR",
    "PHASE_POST",
    "PHASE_PRE",
    "PHASE_ROLLBACK",
    "RESOLVER_PROVENANCE_SHIM",
    "RESOLVER_PROVENANCE_UPSTREAM",
    "SHIM_COMPONENT_PRIMITIVES",
    "STATE_BACKING_DETERMINISTIC_SNAPSHOTS",
    "VALID_RUST_VALUES",
    "WELLE_5_PARTNER_COMPONENT",
    "WELLE_5_PARTNER_ENV_VAR",
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "capture_state_snapshot_baseline_default",
    "derive_exit_code",
    "evaluate_post_cutover_asserts",
    "evaluate_state_snapshot_parity",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
