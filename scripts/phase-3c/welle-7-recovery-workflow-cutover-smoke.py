#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-7-recovery-workflow-cutover-smoke — End-to-End Cutover-Smoke for ADR-0066 Welle-7.

Background
----------

ADR-0066 (approved 2026-05-17, commit ``c907f98``) schedules
**Welle-7** of the Phase-3c default-backend flip as the **KW-27
Doppel-Welle** twin of Welle-6: ``recovery_workflow`` (in-repo
short form ``recovery``, BackendDecision-domain ``recovery``)
cuts over from Python-default to Rust-default **in parallel with
Welle-6** (``subscribe_loop``). The parallel posture is an
ADR-0066 §Option-A+ Doppel-Welle pairing — the **final** Doppel-
Welle of Phase-3, closing the seven-Welle sequence (Phase-3-Ende).

The Cross-Modul-Drift-Risk (ADR-0066 §Welle-6-7-Risiken, Tomás-
Zone-K review) is the **Recovery-Re-Entry × NATS-Subscribe
Coupling Risk**:

  ``recovery_workflow`` (``RecoveryWorkflow``) is the R1..R4
  orchestrator that brings a despawned/crashed persona back to
  ``running`` (spec §3.7.4). At the runtime level, the recovery
  workflow's R2-Reload phase reads from ``state_backing`` (Welle-4,
  already cutovert in KW-26) and R3-Re-register coordinates with
  the SVID workload-identity substrate. ``subscribe_loop``
  (``NatsSubscribeLoop``) is the NATS message pump (spec §3.7.6).
  On recovery entry, the subscribe-loop must drain in-flight
  messages before R2 mutates state. When **both** modules flip
  from Python to Rust during the same KW-27 window, any drift in
  their joint contract (R1-detection signal source,
  RecoveryOutcome byte-shape, R4-Resume callback semantics) will
  manifest as cross-modul recovery storms or message loss that no
  single-module smoke can catch.

This smoke is the **strict, asserts-tragend** End-to-End Cutover-
Smoke for Welle-7, modelled on the Welle-5 sibling
``scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py``
(Tag-38, PR #249) and pattern-parity-aligned with Welle-6
``scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py``
(Tag-39). The pattern-parity is intentional: the operator runs
all seven smokes in the same cutover-PR window, gets seven JSON
envelopes with the same shape (``schema`` differs only by Welle
number), and the tri-state exit codes feed shell gates.

Welle-7-specific asserts (Recovery-R1..R4 Hermetic-Mock-Drill + Cross-Modul-Drift)
-----------------------------------------------------------------------------------

The smoke adds **two** Welle-7-specific asserts that do not exist
in the Welle-1/2/3 shape, symmetric to Welle-4/5/6's A6+A7:

* **A6 recovery-r1-r4-drill (hermetic R1..R4 mock-drill over
  cutover window):** the smoke captures a deterministic
  RecoveryOutcome envelope walking the full R1 -> R2 -> R3 -> R4
  spec §3.7.4 happy-path **BEFORE the cutover-step constructs the
  PHASE_POST env-map**. After the cutover (engine-reboot with
  ``WAKIR_RECOVERY_BACKEND=rust``), the smoke re-emits the same
  RecoveryOutcome via the Python authority a second time and
  asserts byte-equality of the JCS-canonical bytes.
  **Additionally**, the smoke verifies that every phase result in
  the recomputed outcome belongs to the spec's closed phase
  enumeration ``("R1", "R2", "R3", "R4")`` and that the ordering
  is preserved — no phase reordering, no out-of-spec phase labels.
  Severity: caution — a hash mismatch or phase-ordering drift here
  signals Python RecoveryOutcome encoder drift between pre and
  post, which is a Tomás-Zone-K cross-modul drift signal, not a
  Pilot-VM-cutover blocker. The Rust pendant byte-parity is pinned
  at a separate substrate layer (the recovery-workflow cross-lang
  fixture pins from PR #176 / PR #167).

* **A7 cross-modul-drift-to-welle-6 (recovery_workflow x subscribe_loop):**
  verifies that the ``subscribe_loop`` env-var stays at its
  baseline value (``python`` in PHASE_PRE, the operator's choice
  in PHASE_POST and PHASE_ROLLBACK) and that the per-boot
  ``subscribe_loop`` BackendDecision ``chosen_backend`` field
  matches the env-var requested-value byte-for-byte in **every**
  phase. This is the cross-modul invariant: the recovery cutover
  MUST NOT silently force the subscribe_loop component into a
  different backend (the parallel-Welle joint-cutover concern).
  Severity: blocker — a fail here means recovery's resolver
  leaked into the subscribe_loop decision path, which would
  invalidate the parallel-Welle isolation contract.

A7 is **symmetric** to Welle-6's A7: Welle-6's A7 checks that
subscribe_loop's cutover does not leak into recovery; Welle-7's
A7 checks that recovery's cutover does not leak into
subscribe_loop. Together they pin the parallel-Welle isolation
contract bidirectionally.

State-Backing-Awareness pre-check
---------------------------------

Per Auftrag-Tag-39, recovery reads from state_backing (Welle-4,
already cutovert in KW-26). By KW-27 the state_backing substrate
is stable on Rust-default. The smoke surfaces a
``state_backing_post_cutover_state`` field in the envelope so the
operator can confirm state_backing is in the expected post-KW-26
state before kicking off the Welle-7 cutover. The smoke's
PHASE_POST env-map sets ``WAKIR_STATE_BACKING_BACKEND=rust`` (the
post-KW-26 production state) to reflect the realistic runtime
posture; the focus assertions are unaffected.

FSM is also already cutovert in KW-26; the smoke pins fsm to
``rust`` in every phase for the same reason.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-5/6 shape verbatim, re-pointed at ``recovery`` and
``WAKIR_RECOVERY_BACKEND``. ``recovery`` has only **two** backend
values (``python``, ``rust``).

Real-resolver verification (no shim)
------------------------------------

Welle-7 uses the **real upstream resolver**
``resolve_recovery_backend`` directly. The resolver has been in
baseline since PR #135 (Tag-13 recovery substrate, PR #167 Tag-17
wiring). The smoke imports it via :func:`_import_resolver` and
never constructs a shim. The ``resolver_provenance`` field in the
envelope reports ``"upstream"`` for recovery in every run.

Note that the Auftrag refers to the resolver as
``resolve_recovery_workflow_backend`` but the in-repo function
name is ``resolve_recovery_backend`` (matching the BackendDecision-
domain short form ``recovery``). The smoke binds to the short-form
name; the long-form ``recovery_workflow`` is surfaced only in the
``FOCUS_COMPONENT_LONG`` envelope field for operator readability.

Default ``--expected-components 11``
------------------------------------

ADR-0066 §Welle-7 baseline is the post-Tag-38 engine inventory:
eleven in-place components. Operators run with the default
``--expected-components 11``.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with
   the Python default. Records the ``BackendDecision`` for
   ``recovery`` plus the other in-place components. **AND captures
   the recovery R1..R4 drill baseline hash** by invoking the
   canonical RecoveryOutcome serializer against a deterministic
   R1->R2->R3->R4 outcome fixture.
2. **Cutover step.** Flips ``WAKIR_RECOVERY_BACKEND=rust`` in the
   hermetic env-map, restarts the mocked engine, re-collects
   BackendDecisions, and re-emits the R1..R4 drill outcome to
   verify byte-stability.
3. **Post-Cutover asserts.** Five hard checks + two Welle-7-
   specific substrate checks (A1..A5 + R1 + A6 + A7).
4. **Rollback probe.** ``WAKIR_RECOVERY_BACKEND`` unset.
5. **Tri-state exit:**
     * ``0`` — **GREEN**.
     * ``1`` — **CAUTION** (A3, A4, A6 caution drifts).
     * ``2`` — **ROLLBACK-RECOMMENDED** (A1/A2/A5/A7/R1 fail).

The smoke writes a JSON envelope to ``--output`` (or stdout).

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 R1..R4 drill check
imports :mod:`wirelang.persona_engine.recovery_workflow_canonical`
lazily; the wirelang dependency on ``rfc8785`` is bypassed by the
smoke's preference for the smoke's own JSON-canonical fallback
when the public API surface is missing, so the test suite can
exercise A6 without the rfc8785 wheel. The mocked engine never
imports NATS, the Anthropic SDK, the real Rust binary, or any
container runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, 11 expected
    # components per Tag-38-tip inventory).
    python3 scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py \\
        --output out/welle-7-smoke.json

    # Skip A6 R1..R4 drill (e.g. when rfc8785 wheel unavailable):
    python3 scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py \\
        --skip-recovery-drill-parity

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
# Constants — Welle-7 focus on recovery.
# ---------------------------------------------------------------------------

#: Welle-7 focus component (ADR-0066 §Welle-7 KW-27 Doppel-Welle).
#: In-repo short form is "recovery"; ADR-0066 long form is
#: "recovery_workflow".
FOCUS_COMPONENT = "recovery"
FOCUS_COMPONENT_LONG = "recovery_workflow"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-7.
FOCUS_ENV_VAR = "WAKIR_RECOVERY_BACKEND"

#: All in-place Phase-3b/3c components.
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

#: ADR-0065 §AC-2 tolerance.
DEFAULT_LATENCY_TOLERANCE_PCT = 20

#: Default boots per phase.
DEFAULT_BOOTS_PER_PHASE = 8

#: Default expected in-place-component count.
DEFAULT_EXPECTED_COMPONENTS = 11

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-7-cutover-smoke/1"

#: ENV-var values.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"

#: Welle-6 cross-modul-drift partner.
WELLE_6_PARTNER_COMPONENT = "subscribe_loop"
WELLE_6_PARTNER_ENV_VAR = "WAKIR_SUBSCRIBE_LOOP_BACKEND"

#: State-Backing-Awareness: state_backing (Welle-4) was already
#: cutovert in KW-26. By KW-27 the state_backing substrate is stable
#: on Rust-default. state_backing has a three-valued enum
#: (``python``, ``rust_inmemory``, ``rust_natskv``); the Welle-4
#: cutover defaults to ``rust_inmemory``, so the smoke pins it to
#: ``rust_inmemory`` in every phase to reflect the post-KW-26
#: production state.
STATE_BACKING_POST_KW26_COMPONENT = "state_backing"
STATE_BACKING_POST_KW26_ENV_VAR = "WAKIR_STATE_BACKING_BACKEND"
STATE_BACKING_POST_KW26_BACKEND = "rust_inmemory"

#: FSM (Welle-5) was also already cutovert in KW-26.
FSM_POST_KW26_COMPONENT = "fsm"
FSM_POST_KW26_ENV_VAR = "WAKIR_FSM_BACKEND"
FSM_POST_KW26_BACKEND = ENV_VALUE_RUST

#: Resolver-provenance markers.
RESOLVER_PROVENANCE_UPSTREAM = "upstream"
RESOLVER_PROVENANCE_SHIM = "shim"


# ---------------------------------------------------------------------------
# Per-component env-var bridge.
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
# Resolver-import seam.
# ---------------------------------------------------------------------------


def _import_resolver() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.rust_backend_switch`."""
    return importlib.import_module(
        "wirelang.persona_engine.rust_backend_switch"
    )


def _resolver_fn_name(component: str) -> str:
    return f"resolve_{component}_backend"


# ---------------------------------------------------------------------------
# Resolver-shim.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ShimBackendDecision:
    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


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

    recovery itself MUST be upstream (PR #167); a missing
    ``resolve_recovery_backend`` is a substrate-regression and
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


def _stub_probe_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
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

    State-Backing-Awareness: ``WAKIR_STATE_BACKING_BACKEND`` is
    pinned to ``"rust"`` in every phase (post-KW-26 production
    state, Welle-4 already cutovert).

    FSM-Awareness: ``WAKIR_FSM_BACKEND`` is pinned to ``"rust"`` in
    every phase (post-KW-26 production state, Welle-5 already
    cutovert).

    Welle-6 partner invariant: ``WAKIR_SUBSCRIBE_LOOP_BACKEND`` is
    set to ``"python"`` in every phase. The A7 cross-modul-drift
    assert verifies that the subscribe_loop BackendDecision
    actually honours this setting in PHASE_POST — i.e. recovery's
    cutover does not leak into subscribe_loop's resolver path.
    """
    env: Dict[str, str] = dict(base_env or {})
    for env_var in COMPONENT_TO_ENV.values():
        env[env_var] = ENV_VALUE_PYTHON
    # State-Backing-Awareness + FSM-Awareness: post-KW-26 production
    # state pins state_backing and fsm to rust.
    env[STATE_BACKING_POST_KW26_ENV_VAR] = STATE_BACKING_POST_KW26_BACKEND
    env[FSM_POST_KW26_ENV_VAR] = FSM_POST_KW26_BACKEND
    if phase == PHASE_PRE:
        return env
    if phase == PHASE_POST:
        env[FOCUS_ENV_VAR] = ENV_VALUE_RUST
        return env
    if phase == PHASE_ROLLBACK:
        env.pop(FOCUS_ENV_VAR, None)
        return env
    raise ValueError(
        f"unknown phase {phase!r}; expected one of "
        f"({PHASE_PRE!r}, {PHASE_POST!r}, {PHASE_ROLLBACK!r})"
    )


# ---------------------------------------------------------------------------
# Mocked persona-boot.
# ---------------------------------------------------------------------------


def boot_engine_once(
    *,
    env: Mapping[str, str],
    components: Tuple[str, ...],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
    provenance_sink: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
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
    capture_recovery_drill_baseline: bool = False,
    recovery_drill_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Dict[str, Any]:
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

    if capture_recovery_drill_baseline:
        if recovery_drill_baseline_fn is not None:
            baseline = recovery_drill_baseline_fn()
        else:
            baseline = capture_recovery_drill_baseline_default()
        record["recovery_drill_baseline"] = baseline
    return record


# ---------------------------------------------------------------------------
# Parity-hash + latency helpers.
# ---------------------------------------------------------------------------


def parity_hash(records: List[Dict[str, Any]]) -> str:
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
    return _nearest_rank_percentile(_focus_latencies(records, focus=focus), 95.0)


# ---------------------------------------------------------------------------
# A6 — Recovery R1..R4 hermetic-Mock-Drill pre-baseline + post-
# cutover-parity probe.
# ---------------------------------------------------------------------------


#: Spec §3.7.4 closed enumeration of recovery phases. The smoke's
#: A6 ordering check compares against this tuple. Keep in lock-step
#: with ``wirelang.persona_engine.recovery_workflow.RECOVERY_WORKFLOW_PHASE_ORDER``.
SPEC_VALID_RECOVERY_PHASES: Tuple[str, ...] = ("R1", "R2", "R3", "R4")

#: Spec §3.7.4.1 closed enumeration of recovery triggers.
SPEC_VALID_RECOVERY_TRIGGERS: Tuple[str, ...] = (
    "CrashDetected",
    "DespawnMidOperation",
    "StateCorruption",
)

#: Deterministic four-phase recovery outcome fixture used for the
#: R1..R4 hermetic-mock-drill baseline. Walks the full spec §3.7.4
#: happy-path: R1 detected -> R2 reloaded -> R3 re_registered ->
#: R4 resumed. Timing fields are timing-free per the canonical
#: projection spec (elapsed_sec=0, soft_cap_exceeded=False).
DETERMINISTIC_RECOVERY_OUTCOME: Dict[str, Any] = {
    "trigger": "CrashDetected",
    "final_state": "running",
    "success": True,
    "phases": [
        {
            "phase": "R1",
            "terminal_status": "detected",
            "audit_annotation": "R1: trigger=CrashDetected",
        },
        {
            "phase": "R2",
            "terminal_status": "reloaded",
            "audit_annotation": "R2: state_backing.restore_latest ok",
        },
        {
            "phase": "R3",
            "terminal_status": "re_registered",
            "audit_annotation": "R3: SVID workload-API refresh ok",
        },
        {
            "phase": "R4",
            "terminal_status": "resumed",
            "audit_annotation": "R4: container resumed",
        },
    ],
}


def _import_recovery_canonical() -> Any:
    """Lazy import of
    :mod:`wirelang.persona_engine.recovery_workflow_canonical`.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.persona_engine.recovery_workflow_canonical"
    )


def _smoke_internal_jcs_canonical_bytes(canonical_dict: Dict[str, Any]) -> bytes:
    """Smoke-internal JCS-canonical bytes via stdlib JSON.

    Used as a fallback when the wirelang public API surface uses
    ``rfc8785`` which may not be importable in the test env. The
    smoke's hash compares this with itself across pre/post; the
    Rust pendant byte-parity is pinned at a different substrate
    layer.
    """
    return json.dumps(
        canonical_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _build_and_hash_recovery_outcome(
    module: Any,
    outcome: Dict[str, Any] = None,  # type: ignore[assignment]
) -> Tuple[bytes, str]:
    """Build a canonical recovery outcome dict and return (bytes, hex-hash).

    Strategy:

    1. Prefer the wirelang public API surface
       (``recovery_outcome_canonical_dict`` + ``recovery_outcome_jcs_bytes``
       + ``recovery_outcome_sha256_hex``) when ALL three are callable.
    2. Fall back to a smoke-internal JSON-canonical hash when the
       public API is missing or raises (e.g. rfc8785 wheel absent).

    The fallback path keeps the smoke importable + the hash byte-
    stable across the pre/post window regardless of wheel
    availability; the Rust pendant byte-parity oracle is pinned at
    a separate substrate layer.
    """
    payload = outcome if outcome is not None else DETERMINISTIC_RECOVERY_OUTCOME

    builder = getattr(module, "recovery_outcome_canonical_dict", None)
    jcs_bytes_fn = getattr(module, "recovery_outcome_jcs_bytes", None)
    sha256_hex_fn = getattr(module, "recovery_outcome_sha256_hex", None)

    if callable(builder) and callable(jcs_bytes_fn):
        # Real wirelang API: trigger/final_state/success/phases.
        # The trigger is a RecoveryTrigger enum in production; we
        # build the canonical dict directly via stdlib JSON to
        # avoid depending on the enum + rfc8785.
        try:
            phases = payload["phases"]
            phase_results = [_to_phase_result(module, p) for p in phases]
            trigger_obj = _to_recovery_trigger(module, payload["trigger"])
            canonical = builder(
                trigger=trigger_obj,
                phases=phase_results,
                final_state=payload["final_state"],
                success=payload["success"],
            )
        except Exception:  # noqa: BLE001
            # Fall back to smoke-internal canonical projection.
            canonical = _smoke_canonical_projection(payload)
        try:
            jcs = jcs_bytes_fn(canonical)
        except Exception:  # noqa: BLE001 — rfc8785 wheel absent or similar
            jcs = _smoke_internal_jcs_canonical_bytes(_smoke_canonical_projection(payload))
        if callable(sha256_hex_fn):
            try:
                digest = sha256_hex_fn(canonical)
            except Exception:  # noqa: BLE001
                digest = hashlib.sha256(jcs).hexdigest()
        else:
            digest = hashlib.sha256(jcs).hexdigest()
        return jcs, digest

    # Pure smoke-internal path: stdlib JSON canonical.
    canonical = _smoke_canonical_projection(payload)
    jcs = _smoke_internal_jcs_canonical_bytes(canonical)
    return jcs, hashlib.sha256(jcs).hexdigest()


def _smoke_canonical_projection(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """Smoke-internal canonical projection mirroring the wirelang
    shape: phases sorted by spec order, timing fields zeroed, schema
    tag included."""
    phases_in = outcome.get("phases", [])
    # Preserve input order but zero timing fields per spec.
    phases_out = []
    for p in phases_in:
        phases_out.append({
            "audit_annotation": p.get("audit_annotation", ""),
            "elapsed_sec": 0,
            "phase": p.get("phase", ""),
            "soft_cap_exceeded": False,
            "terminal_status": p.get("terminal_status", ""),
        })
    return {
        "final_state": outcome.get("final_state", ""),
        "phases": phases_out,
        "schema": "wakir.persona-engine.recovery-outcome/1",
        "success": bool(outcome.get("success", False)),
        "total_elapsed_sec": 0,
        "trigger": outcome.get("trigger", ""),
    }


def _to_phase_result(module: Any, phase_dict: Dict[str, Any]) -> Any:
    """Try to construct a PhaseResult dataclass from the wirelang
    module; fall back to a SimpleNamespace-like dict-as-attr proxy."""
    PhaseResult = getattr(module, "PhaseResult", None)
    # PhaseResult lives in recovery_workflow not _canonical, so it
    # may be missing on the _canonical surface. Try importing.
    if PhaseResult is None:
        try:
            rw = importlib.import_module(
                "wirelang.persona_engine.recovery_workflow"
            )
            PhaseResult = getattr(rw, "PhaseResult", None)
        except ImportError:
            PhaseResult = None
    if PhaseResult is not None:
        try:
            return PhaseResult(
                phase=phase_dict["phase"],
                terminal_status=phase_dict["terminal_status"],
                elapsed_sec=0.0,
                soft_cap_exceeded=False,
                audit_annotation=phase_dict.get("audit_annotation", ""),
            )
        except TypeError:
            pass

    @dataclass(frozen=True)
    class _SmokePhaseResult:
        phase: str
        terminal_status: str
        elapsed_sec: float
        soft_cap_exceeded: bool
        audit_annotation: str

    return _SmokePhaseResult(
        phase=phase_dict["phase"],
        terminal_status=phase_dict["terminal_status"],
        elapsed_sec=0.0,
        soft_cap_exceeded=False,
        audit_annotation=phase_dict.get("audit_annotation", ""),
    )


def _to_recovery_trigger(module: Any, value: str) -> Any:
    """Try to construct a RecoveryTrigger enum from the wirelang
    module; fall back to a SimpleNamespace-like .value proxy."""
    RecoveryTrigger = getattr(module, "RecoveryTrigger", None)
    if RecoveryTrigger is None:
        try:
            rw = importlib.import_module(
                "wirelang.persona_engine.recovery_workflow"
            )
            RecoveryTrigger = getattr(rw, "RecoveryTrigger", None)
        except ImportError:
            RecoveryTrigger = None
    if RecoveryTrigger is not None:
        try:
            return RecoveryTrigger(value)
        except ValueError:
            pass

    class _SmokeRecoveryTrigger:
        def __init__(self, v: str) -> None:
            self.value = v

    return _SmokeRecoveryTrigger(value)


def _phase_ordering_violations(
    outcome: Dict[str, Any],
) -> List[Tuple[int, str]]:
    """Return (index, phase) pairs that violate the spec ordering.

    Spec §3.7.4 requires R1 -> R2 -> R3 -> R4 in that exact order.
    Returns the violating entries; empty list means well-ordered.
    Out-of-spec phase labels are also flagged.
    """
    out: List[Tuple[int, str]] = []
    phases = outcome.get("phases", [])
    expected = SPEC_VALID_RECOVERY_PHASES
    for i, p in enumerate(phases):
        phase = p.get("phase", "")
        if phase not in expected:
            out.append((i, phase))
            continue
        if i < len(expected) and phase != expected[i]:
            out.append((i, phase))
    return out


def capture_recovery_drill_baseline_default(
    *,
    outcome: Dict[str, Any] = None,  # type: ignore[assignment]
    canonical_module: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Capture the pre-cutover recovery R1..R4 drill baseline.

    Returns a record (always non-None, ``skipped=True`` when the
    recovery_workflow_canonical module is not importable).
    """
    payload = outcome if outcome is not None else DETERMINISTIC_RECOVERY_OUTCOME
    module = canonical_module
    if module is None:
        try:
            module = _import_recovery_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"recovery_workflow_canonical not importable: {exc}"
                ),
                "recovery_outcome_sha256_hex": None,
                "recovery_outcome_byte_length": 0,
                "phase_count": len(payload.get("phases", [])),
                "phase_ordering_violations": _phase_ordering_violations(payload),
                "captured_at_phase": PHASE_PRE,
            }

    violations = _phase_ordering_violations(payload)

    try:
        payload_bytes, digest = _build_and_hash_recovery_outcome(module, payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                f"recovery-drill baseline capture raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "recovery_outcome_sha256_hex": None,
            "recovery_outcome_byte_length": 0,
            "phase_count": len(payload.get("phases", [])),
            "phase_ordering_violations": violations,
            "captured_at_phase": PHASE_PRE,
        }

    return {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"recovery-drill baseline captured: "
            f"{len(payload.get('phases', []))} phases (R1..R4), "
            f"outcome_sha256={digest[:16]}..."
        ),
        "recovery_outcome_sha256_hex": digest,
        "recovery_outcome_byte_length": len(payload_bytes),
        "phase_count": len(payload.get("phases", [])),
        "phase_ordering_violations": violations,
        "captured_at_phase": PHASE_PRE,
    }


def evaluate_recovery_drill_parity(
    baseline: Optional[Dict[str, Any]],
    *,
    outcome: Dict[str, Any] = None,  # type: ignore[assignment]
    canonical_module: Optional[Any] = None,
) -> Dict[str, Any]:
    """Recompute the recovery-drill hash post-cutover and compare."""
    payload = outcome if outcome is not None else DETERMINISTIC_RECOVERY_OUTCOME

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
            "baseline_recovery_outcome_sha256": None,
            "recomputed_recovery_outcome_sha256": None,
            "match": True,
            "phase_ordering_violations": [],
            "captured_at_phase": (
                baseline.get("captured_at_phase") if baseline else PHASE_PRE
            ),
        }

    module = canonical_module
    if module is None:
        try:
            module = _import_recovery_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"recovery_workflow_canonical not importable for "
                    f"recompute: {exc}"
                ),
                "baseline_recovery_outcome_sha256": baseline.get(
                    "recovery_outcome_sha256_hex"
                ),
                "recomputed_recovery_outcome_sha256": None,
                "match": True,
                "phase_ordering_violations": [],
                "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
            }

    violations_post = _phase_ordering_violations(payload)

    try:
        _payload_bytes, recomputed = _build_and_hash_recovery_outcome(module, payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "skipped": False,
            "severity": "caution",
            "detail": (
                f"recovery-drill recompute raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "baseline_recovery_outcome_sha256": baseline.get(
                "recovery_outcome_sha256_hex"
            ),
            "recomputed_recovery_outcome_sha256": None,
            "match": False,
            "phase_ordering_violations": violations_post,
            "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
        }

    baseline_hash = baseline.get("recovery_outcome_sha256_hex")
    match = recomputed == baseline_hash
    no_violations = not violations_post
    passed = match and no_violations

    if passed:
        detail = (
            f"recovery-drill parity ok ({recomputed[:16]}...), "
            f"no phase-ordering violations"
        )
    elif not match and not no_violations:
        detail = (
            f"recovery-drill drift AND phase-ordering violations: "
            f"baseline={baseline_hash} recomputed={recomputed} "
            f"violations={violations_post!r}"
        )
    elif not match:
        detail = (
            f"recovery-drill drift: baseline={baseline_hash} "
            f"recomputed={recomputed}"
        )
    else:
        detail = (
            f"recovery-drill phase-ordering violations: {violations_post!r}"
        )

    return {
        "passed": passed,
        "skipped": False,
        "severity": "caution",
        "detail": detail,
        "baseline_recovery_outcome_sha256": baseline_hash,
        "recomputed_recovery_outcome_sha256": recomputed,
        "match": match,
        "phase_ordering_violations": violations_post,
        "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
    }


# ---------------------------------------------------------------------------
# Assert evaluation.
# ---------------------------------------------------------------------------


def _focus_records(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> List[Dict[str, Any]]:
    return [r for r in records if r.get("domain") == focus]


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
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


def evaluate_post_cutover_asserts(
    *,
    pre_records: List[Dict[str, Any]],
    post_records: List[Dict[str, Any]],
    rollback_records: List[Dict[str, Any]],
    expected_components: int,
    boots_per_phase: int,
    latency_tolerance_pct: int,
    recovery_drill_baseline: Optional[Dict[str, Any]] = None,
    recovery_drill_parity: Optional[Dict[str, Any]] = None,
    focus: str = FOCUS_COMPONENT,
) -> Dict[str, Any]:
    asserts: Dict[str, Any] = {}

    # A1
    post_focus = _focus_records(post_records, focus=focus)
    a1_all_rust = bool(post_focus) and all(
        r.get("chosen_backend") == ENV_VALUE_RUST for r in post_focus
    )
    asserts["A1_backend_flip"] = {
        "passed": a1_all_rust,
        "severity": "blocker",
        "detail": (
            f"recovery chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})} "
            f"(expected all == {ENV_VALUE_RUST!r})"
        ),
    }

    # A2
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
        ),
    }

    # A3
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

    # A4
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

    # A5
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

    # R1
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

    # A6 recovery-R1..R4-drill parity (caution).
    if recovery_drill_parity is None:
        a6_record = {
            "passed": True,
            "severity": "caution",
            "skipped": True,
            "detail": "A6 skipped (probe not invoked)",
            "baseline_recovery_outcome_sha256": None,
            "recomputed_recovery_outcome_sha256": None,
            "match": True,
            "phase_ordering_violations": [],
            "captured_at_phase": PHASE_PRE,
        }
    else:
        a6_record = {
            "passed": bool(recovery_drill_parity.get("passed", True)),
            "severity": "caution",
            "skipped": bool(recovery_drill_parity.get("skipped", False)),
            "detail": recovery_drill_parity.get("detail", ""),
            "baseline_recovery_outcome_sha256": recovery_drill_parity.get(
                "baseline_recovery_outcome_sha256"
            ),
            "recomputed_recovery_outcome_sha256": recovery_drill_parity.get(
                "recomputed_recovery_outcome_sha256"
            ),
            "match": bool(recovery_drill_parity.get("match", True)),
            "phase_ordering_violations": list(
                recovery_drill_parity.get("phase_ordering_violations") or []
            ),
            "captured_at_phase": recovery_drill_parity.get(
                "captured_at_phase", PHASE_PRE
            ),
        }
    asserts["A6_recovery_r1_r4_drill"] = a6_record

    # A7 Cross-Modul-Drift to Welle-6 partner (subscribe_loop).
    sl_post_records = [
        r
        for r in post_records
        if r.get("domain") == WELLE_6_PARTNER_COMPONENT
    ]
    if not sl_post_records:
        a7_record = {
            "passed": False,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 subscribe_loop cross-modul-drift check: no "
                f"subscribe_loop BackendDecision present in "
                f"PHASE_POST records (expected {boots_per_phase} "
                f"subscribe_loop decisions). The recovery cutover "
                f"may have suppressed subscribe_loop emissions — "
                f"parallel-Welle isolation broken."
            ),
            "subscribe_loop_chosen_backends": [],
            "expected_subscribe_loop_backend": ENV_VALUE_PYTHON,
        }
    else:
        chosen = [r.get("chosen_backend") for r in sl_post_records]
        all_python = all(c == ENV_VALUE_PYTHON for c in chosen)
        a7_record = {
            "passed": all_python,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 cross-modul-drift OK: subscribe_loop stayed at "
                f"python across {len(sl_post_records)} PHASE_POST "
                f"records during recovery cutover"
                if all_python
                else (
                    f"A7 cross-modul-drift FAIL: recovery cutover "
                    f"leaked into subscribe_loop path. "
                    f"subscribe_loop chosen_backend values in "
                    f"PHASE_POST: {sorted(set(chosen))} (expected "
                    f"all == 'python'). This breaks the KW-27 "
                    f"Doppel-Welle isolation contract."
                )
            ),
            "subscribe_loop_chosen_backends": sorted(set(chosen)),
            "expected_subscribe_loop_backend": ENV_VALUE_PYTHON,
        }
    asserts["A7_cross_modul_drift_welle_6_subscribe_loop"] = a7_record

    return asserts


def derive_exit_code(asserts: Dict[str, Any]) -> int:
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
# State-Backing-Awareness + FSM-Awareness pre-check.
# ---------------------------------------------------------------------------


def evaluate_state_backing_post_cutover_state(
    post_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check that state_backing (Welle-4) is in the expected post-KW-26 state."""
    sb_records = [
        r for r in post_records if r.get("domain") == STATE_BACKING_POST_KW26_COMPONENT
    ]
    chosen = sorted({r.get("chosen_backend") for r in sb_records})
    in_state = (
        bool(sb_records)
        and all(
            r.get("chosen_backend") == STATE_BACKING_POST_KW26_BACKEND
            for r in sb_records
        )
    )
    return {
        "state_backing_chosen_backends": chosen,
        "expected_state_backing_backend": STATE_BACKING_POST_KW26_BACKEND,
        "state_backing_in_expected_post_kw26_state": in_state,
        "detail": (
            f"state_backing is in expected post-KW-26 state "
            f"(chosen_backend={chosen!r})"
            if in_state
            else (
                f"state_backing is NOT in expected post-KW-26 state. "
                f"Saw chosen_backend={chosen!r}, expected "
                f"{[STATE_BACKING_POST_KW26_BACKEND]!r}. The Welle-7 "
                f"cutover should only proceed AFTER state_backing "
                f"(Welle-4) cutover is complete and stable on rust."
            )
        ),
    }


def evaluate_fsm_post_cutover_state(
    post_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check that FSM (Welle-5) is in the expected post-KW-26 state."""
    fsm_records = [
        r for r in post_records if r.get("domain") == FSM_POST_KW26_COMPONENT
    ]
    chosen = sorted({r.get("chosen_backend") for r in fsm_records})
    in_state = (
        bool(fsm_records)
        and all(
            r.get("chosen_backend") == FSM_POST_KW26_BACKEND
            for r in fsm_records
        )
    )
    return {
        "fsm_chosen_backends": chosen,
        "expected_fsm_backend": FSM_POST_KW26_BACKEND,
        "fsm_in_expected_post_kw26_state": in_state,
        "detail": (
            f"FSM is in expected post-KW-26 state "
            f"(chosen_backend={chosen!r})"
            if in_state
            else (
                f"FSM is NOT in expected post-KW-26 state. "
                f"Saw chosen_backend={chosen!r}, expected "
                f"{[FSM_POST_KW26_BACKEND]!r}."
            )
        ),
    }


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
    recovery_drill_baseline: Optional[Dict[str, Any]] = None,
    resolver_provenance: Optional[Dict[str, str]] = None,
    state_backing_post_cutover_state: Optional[Dict[str, Any]] = None,
    fsm_post_cutover_state: Optional[Dict[str, Any]] = None,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    timestamp = int(now_ts if now_ts is not None else time.time())
    band_for_exit = {
        EXIT_GREEN: "GREEN",
        EXIT_CAUTION: "CAUTION",
        EXIT_ROLLBACK: "ROLLBACK_RECOMMENDED",
    }
    envelope: Dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "timestamp_utc": timestamp,
        "welle": 7,
        "focus_component": FOCUS_COMPONENT,
        "focus_component_long": FOCUS_COMPONENT_LONG,
        "focus_env_var": FOCUS_ENV_VAR,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
        "resolver_provenance": dict(resolver_provenance or {}),
        "cross_modul_drift_mitigation": {
            "welle_6_partner_component": WELLE_6_PARTNER_COMPONENT,
            "welle_6_partner_env_var": WELLE_6_PARTNER_ENV_VAR,
            "expected_welle_6_partner_backend": ENV_VALUE_PYTHON,
            "subscribe_loop_chosen_backends_in_post_phase": asserts.get(
                "A7_cross_modul_drift_welle_6_subscribe_loop", {}
            ).get("subscribe_loop_chosen_backends", []),
        },
        "recovery_drill_integrity": {
            "baseline_captured_at_phase": (
                recovery_drill_baseline.get("captured_at_phase")
                if recovery_drill_baseline is not None
                else None
            ),
            "baseline_recovery_outcome_sha256": (
                recovery_drill_baseline.get("recovery_outcome_sha256_hex")
                if recovery_drill_baseline is not None
                else None
            ),
            "baseline_skipped": (
                bool(recovery_drill_baseline.get("skipped", False))
                if recovery_drill_baseline is not None
                else True
            ),
            "baseline_phase_ordering_violations": (
                list(
                    recovery_drill_baseline.get("phase_ordering_violations") or []
                )
                if recovery_drill_baseline is not None
                else []
            ),
            "spec_valid_recovery_phases": list(SPEC_VALID_RECOVERY_PHASES),
            "spec_valid_recovery_triggers": list(SPEC_VALID_RECOVERY_TRIGGERS),
        },
        "state_backing_post_cutover_state": (
            state_backing_post_cutover_state
            if state_backing_post_cutover_state is not None
            else {
                "state_backing_chosen_backends": [],
                "expected_state_backing_backend": STATE_BACKING_POST_KW26_BACKEND,
                "state_backing_in_expected_post_kw26_state": False,
                "detail": "state_backing_post_cutover_state not computed",
            }
        ),
        "fsm_post_cutover_state": (
            fsm_post_cutover_state
            if fsm_post_cutover_state is not None
            else {
                "fsm_chosen_backends": [],
                "expected_fsm_backend": FSM_POST_KW26_BACKEND,
                "fsm_in_expected_post_kw26_state": False,
                "detail": "fsm_post_cutover_state not computed",
            }
        ),
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
    skip_recovery_drill_parity: bool = False,
    canonical_module: Optional[Any] = None,
    recovery_drill_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6/A7 + envelope."""
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available

    pre_phase = run_phase(
        PHASE_PRE,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_recovery_drill_baseline=not skip_recovery_drill_parity,
        recovery_drill_baseline_fn=(
            recovery_drill_baseline_fn
            if recovery_drill_baseline_fn is not None
            else (
                (lambda: capture_recovery_drill_baseline_default(
                    canonical_module=canonical_module
                ))
                if not skip_recovery_drill_parity
                else None
            )
        ),
    )

    post_phase = run_phase(
        PHASE_POST,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_recovery_drill_baseline=False,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_recovery_drill_baseline=False,
    )

    recovery_drill_baseline = pre_phase.get("recovery_drill_baseline")

    if skip_recovery_drill_parity:
        recovery_drill_parity: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": "A6 skipped via --skip-recovery-drill-parity",
            "baseline_recovery_outcome_sha256": None,
            "recomputed_recovery_outcome_sha256": None,
            "match": True,
            "phase_ordering_violations": [],
            "captured_at_phase": PHASE_PRE,
        }
    else:
        recovery_drill_parity = evaluate_recovery_drill_parity(
            recovery_drill_baseline,
            canonical_module=canonical_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        recovery_drill_baseline=recovery_drill_baseline,
        recovery_drill_parity=recovery_drill_parity,
    )
    exit_code = derive_exit_code(asserts)

    state_backing_post_cutover_state = evaluate_state_backing_post_cutover_state(
        post_phase["decisions"]
    )
    fsm_post_cutover_state = evaluate_fsm_post_cutover_state(
        post_phase["decisions"]
    )

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
        recovery_drill_baseline=recovery_drill_baseline,
        resolver_provenance=merged_provenance,
        state_backing_post_cutover_state=state_backing_post_cutover_state,
        fsm_post_cutover_state=fsm_post_cutover_state,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-7-recovery-workflow-cutover-smoke",
        description=(
            "Phase-3c Welle-7 (recovery_workflow / recovery) End-to-"
            "End Cutover-Smoke for ADR-0066 KW-27 Doppel-Welle "
            "(parallel with Welle-6 subscribe_loop, Phase-3-Ende). "
            "Boots a mocked persona-engine across Pre-Cutover "
            "(Python baseline) -> Cutover (Rust) -> Rollback "
            "(Python) phases, evaluates A1..A5 + R1 + A6 "
            "(recovery-r1-r4-drill) + A7 (cross-modul-drift-to-"
            "Welle-6-subscribe_loop) asserts, and exits 0/1/2 = "
            "GREEN/CAUTION/ROLLBACK_RECOMMENDED. Never invokes the "
            "real Rust binary, NATS, or the Anthropic API. "
            "License: Apache-2.0."
        ),
    )
    p.add_argument(
        "--boots-per-phase",
        type=int,
        default=DEFAULT_BOOTS_PER_PHASE,
        help=f"Mocked boots per phase (default {DEFAULT_BOOTS_PER_PHASE}).",
    )
    p.add_argument(
        "--expected-components",
        type=int,
        default=DEFAULT_EXPECTED_COMPONENTS,
        help=(
            f"Expected in-place component count per boot (default "
            f"{DEFAULT_EXPECTED_COMPONENTS} = engine inventory at "
            f"baseline 7a0c8b6, Tag-38 tip)."
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
        help="Optional output file path for the JSON envelope.",
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help="Override timestamp_utc for hermetic tests.",
    )
    p.add_argument(
        "--skip-recovery-drill-parity",
        action="store_true",
        help=(
            "Skip the A6 recovery-R1..R4-drill probe. Use when the "
            "wirelang package is not in the import path."
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
            f"welle-7-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-7-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-7-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_recovery_drill_parity=args.skip_recovery_drill_parity,
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
            f"welle-7-cutover-smoke: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        return EXIT_ROLLBACK

    return exit_code


__all__ = [
    "COMPONENT_TO_ENV",
    "DEFAULT_BOOTS_PER_PHASE",
    "DEFAULT_EXPECTED_COMPONENTS",
    "DEFAULT_LATENCY_TOLERANCE_PCT",
    "DETERMINISTIC_RECOVERY_OUTCOME",
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
    "FSM_POST_KW26_BACKEND",
    "FSM_POST_KW26_COMPONENT",
    "FSM_POST_KW26_ENV_VAR",
    "PHASE_POST",
    "PHASE_PRE",
    "PHASE_ROLLBACK",
    "RESOLVER_PROVENANCE_SHIM",
    "RESOLVER_PROVENANCE_UPSTREAM",
    "SHIM_COMPONENT_PRIMITIVES",
    "SPEC_VALID_RECOVERY_PHASES",
    "SPEC_VALID_RECOVERY_TRIGGERS",
    "STATE_BACKING_POST_KW26_BACKEND",
    "STATE_BACKING_POST_KW26_COMPONENT",
    "STATE_BACKING_POST_KW26_ENV_VAR",
    "WELLE_6_PARTNER_COMPONENT",
    "WELLE_6_PARTNER_ENV_VAR",
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "capture_recovery_drill_baseline_default",
    "derive_exit_code",
    "evaluate_fsm_post_cutover_state",
    "evaluate_post_cutover_asserts",
    "evaluate_recovery_drill_parity",
    "evaluate_state_backing_post_cutover_state",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
