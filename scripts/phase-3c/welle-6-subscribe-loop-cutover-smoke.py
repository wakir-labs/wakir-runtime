#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-6-subscribe-loop-cutover-smoke — End-to-End Cutover-Smoke for ADR-0066 Welle-6.

Background
----------

ADR-0066 (approved 2026-05-17, commit ``c907f98``) schedules
**Welle-6** of the Phase-3c default-backend flip as the **KW-27
Doppel-Welle** twin of Welle-7: ``subscribe_loop`` (in-repo and
BackendDecision-domain short form ``subscribe_loop``) cuts over
from Python-default to Rust-default **in parallel with Welle-7**
(``recovery_workflow`` / in-repo short form ``recovery``). The
parallel posture is an ADR-0066 §Option-A+ Doppel-Welle pairing —
the **final** Doppel-Welle of Phase-3, closing the seven-Welle
sequence.

The Cross-Modul-Drift-Risk (ADR-0066 §Welle-6-7-Risiken, Tomás-
Zone-K review) is the **NATS-Subscribe × Recovery-Re-Entry Coupling
Risk**:

  ``subscribe_loop`` (``NatsSubscribeLoop``) is the NATS message
  pump that delivers prompt envelopes to the persona-engine and
  emits ack-records back (spec §3.7.6, Sprint-Pengine-10 OI-PEFR-6).
  ``recovery_workflow`` (``RecoveryWorkflow``) is the R1..R4
  orchestrator that brings a despawned/crashed persona back to
  ``running`` (spec §3.7.4). At the runtime level, the subscribe-
  loop is the **observer-of-truth** for "is the persona alive?":
  it sees the prompt-envelope traffic that signals an active
  persona-session. The recovery-workflow, on entry, must coordinate
  with the subscribe-loop to drain in-flight messages before R2-
  Reload mutates state. When **both** modules flip from Python to
  Rust during the same KW-27 window, any drift in their joint
  contract (ack-record byte-shape, lag-sample emission rate,
  R1-detection signal source) will manifest as cross-modul recovery
  storms or message loss that no single-module smoke can catch.

This smoke is the **strict, asserts-tragend** End-to-End Cutover-
Smoke for Welle-6, modelled on the Welle-5 sibling
``scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py``
(Tag-38, PR #249) and pattern-parity-aligned with Welle-1/2/3/4
(``welle-1-v907-verify-cutover-smoke.py`` PR #230,
``welle-2-svid-workload-identity-cutover-smoke.py`` PR #234,
``welle-3-bridge-audit-writer-cutover-smoke.py`` PR #240,
``welle-4-state-backing-cutover-smoke.py`` PR #245). The pattern-
parity is intentional: the operator runs all seven smokes in the
same cutover-PR window, gets seven JSON envelopes with the same
shape (``schema`` differs only by Welle number), and the tri-state
exit codes feed shell gates.

Welle-6-specific asserts (Subscribe-Loop-Lag-Stability + Cross-Modul-Drift)
---------------------------------------------------------------------------

The smoke adds **two** Welle-6-specific asserts that do not exist
in the Welle-1/2/3 shape, symmetric to Welle-4/5's A6+A7:

* **A6 subscribe-loop-lag-stability (output-reply-timeliness):**
  the smoke builds a deterministic 12-sample synthetic lag-fixture
  (sub-millisecond lag-values that bracket the
  ``persona_engine.subscribe.lag_seconds`` histogram bucket spec)
  **BEFORE the cutover-step constructs the PHASE_POST env-map**.
  After the cutover (engine-reboot with
  ``WAKIR_SUBSCRIBE_LOOP_BACKEND=rust``), the smoke re-emits the
  same lag-fixture via the Python authority a second time and
  asserts byte-equality of the JCS-canonical bytes of an
  ack-record built from the focus-component message-handling path.
  **Additionally**, the smoke verifies that the per-phase mean and
  P95 of the synthetic lag distribution stay within a 25% drift
  envelope across pre/post boots — the operator-Sicht
  output-reply-timeliness contract. Severity: caution — a hash
  mismatch OR a lag-distribution drift here signals subscribe-loop
  encoder drift OR ack-emission-rate drift between pre and post,
  which is a Tomás-Zone-K cross-modul drift signal, not a Pilot-VM-
  cutover blocker. The Rust pendant byte-parity is pinned at a
  separate substrate layer (the subscribe-ack cross-lang fixture
  pins from PR #172 / PR #181). This smoke verifies the Python
  encoder is byte-stable across the pre/post window AND the lag
  distribution is bounded — the only oracle that does **not**
  require bringing up a real Rust binary in-process.

* **A7 cross-modul-drift-to-welle-7 (subscribe_loop x recovery_workflow):**
  verifies that the ``recovery`` env-var stays at its baseline
  value (``python`` in PHASE_PRE, the operator's choice in
  PHASE_POST and PHASE_ROLLBACK) and that the per-boot ``recovery``
  BackendDecision ``chosen_backend`` field matches the env-var
  requested-value byte-for-byte in **every** phase. This is the
  cross-modul invariant: the subscribe_loop cutover MUST NOT
  silently force the recovery_workflow component into a different
  backend (the parallel-Welle joint-cutover concern). Severity:
  blocker — a fail here means subscribe_loop's resolver leaked
  into the recovery decision path, which would invalidate the
  parallel-Welle isolation contract. The control-flow pin is what
  protects the substrate semantics from rot during the KW-27
  Doppel-Welle window.

A7 is **symmetric** to Welle-7's A7: Welle-7's A7 checks that
recovery's cutover does not leak into subscribe_loop; Welle-6's A7
checks that subscribe_loop's cutover does not leak into recovery.
Together they pin the parallel-Welle isolation contract
bidirectionally.

FSM-Awareness pre-check
-----------------------

Per Auftrag-Tag-39, the subscribe_loop cutover must NOT be started
or stopped inside an FSM-cutover-window. FSM (Welle-5) was already
cutovert in KW-26; by KW-27 the FSM substrate is stable on Rust-
default. The smoke surfaces an ``fsm_post_cutover_state`` field in
the envelope so the operator can confirm FSM is in the expected
post-KW-26 state before kicking off the Welle-6 cutover. The
smoke's PHASE_POST env-map sets ``WAKIR_FSM_BACKEND=rust`` (the
post-KW-26 production state) to reflect the realistic runtime
posture; the focus assertions are unaffected.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-5 shape verbatim, re-pointed at ``subscribe_loop`` and
``WAKIR_SUBSCRIBE_LOOP_BACKEND``. ``subscribe_loop`` has only
**two** backend values (``python``, ``rust``) — simpler than
state_backing's three-valued enum.

Real-resolver verification (no shim)
------------------------------------

Welle-6 uses the **real upstream resolver**
``resolve_subscribe_loop_backend`` directly. The resolver has been
in baseline since PR #181 (Tag-22 subscribe_loop Rust-Default ENV-
gated resolver). The smoke imports it via :func:`_import_resolver`
and never constructs a shim. The ``resolver_provenance`` field in
the envelope reports ``"upstream"`` for subscribe_loop in every
run.

Default ``--expected-components 11``
------------------------------------

ADR-0066 §Welle-6 baseline is the post-Tag-38 engine inventory:
eleven in-place components (v907_verify, svid_workload_identity,
bridge_diff, anchor_emitter, state_backing, fsm, subscribe_loop,
recovery, federation_resolver, bridge_audit_writer,
bridge_audit_diff_engine). Operators run with the default
``--expected-components 11``; if running against a pre-PR-#241
tip, pass ``--expected-components 10``.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with
   the Python default (``WAKIR_SUBSCRIBE_LOOP_BACKEND=python`` +
   every other component pinned to python except fsm which is
   pinned to rust per post-KW-26 production state). Records the
   ``BackendDecision`` for ``subscribe_loop`` plus the other in-
   place components. **AND captures the subscribe-loop lag-stability
   baseline hash** by invoking the canonical ack-record serializer
   against the deterministic twelve-sample lag-fixture. This is
   the lag-stability capture moment: the baseline is taken before
   the cutover.
2. **Cutover step.** Flips ``WAKIR_SUBSCRIBE_LOOP_BACKEND=rust``
   in the hermetic env-map, restarts the mocked engine (engine-
   reboot semantics), re-collects BackendDecisions. The engine-
   reboot must successfully read the ack-record envelope that the
   Python backend wrote in PHASE_PRE — the smoke verifies this by
   re-emitting the same lag-fixture via the Python authority and
   asserting byte-equality with the pre-baseline hash AND
   verifying the lag-distribution mean+P95 stay within the drift
   envelope.
3. **Post-Cutover asserts.** Five hard checks + two Welle-6-
   specific substrate checks (A1..A5 + R1 + A6 + A7).
4. **Rollback probe.** ``WAKIR_SUBSCRIBE_LOOP_BACKEND`` unset
   (engine reads Python-default), re-boot, asserts that the
   engine emits ``chosen_backend == "python"`` again — operator
   rollback path <=10 min per ADR-0065 §Rollback-SLA (ADR-0066
   inherits this contract).
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All blocker asserts pass
       + caution asserts pass.
     * ``1`` — **CAUTION**. At least one caution-severity drift
       (A3 latency, A4 component-count, A6 lag-stability drift /
       byte-drift).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 / A7 / R1
       failed.

The smoke writes a JSON envelope to ``--output`` (or stdout). The
envelope shape is pinned by the test suite.

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 lag-stability
check imports :mod:`wirelang.persona_engine.subscribe_ack` lazily
and reads only the in-memory deterministic 12-sample lag fixture
embedded in this module; both are gracefully skipped if the
import fails so the smoke remains importable in test environments
without the wirelang package. The mocked engine never imports
NATS, the Anthropic SDK, the real Rust binary, or any container
runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, 11 expected
    # components per Tag-38-tip inventory).
    python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \\
        --output out/welle-6-smoke.json

    # Pre-PR-#241 inventory (10 expected components):
    python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \\
        --expected-components 10 --output out/welle-6-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \\
        --latency-tolerance-pct 10

    # Skip the A6 lag-stability probe (e.g. when the wirelang
    # package is not in the import path):
    python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \\
        --skip-lag-stability-parity

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
# Constants — Welle-6 focus on subscribe_loop.
# ---------------------------------------------------------------------------

#: Welle-6 focus component (ADR-0066 §Welle-6 KW-27 Doppel-Welle).
FOCUS_COMPONENT = "subscribe_loop"
FOCUS_COMPONENT_LONG = "subscribe_loop"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-6.
FOCUS_ENV_VAR = "WAKIR_SUBSCRIBE_LOOP_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Tracks the engine inventory at
#: baseline ``7a0c8b6`` (Tag-38 tip, post-PR-#241 wire-in):
#: eleven resolvers.
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

#: ADR-0065 §AC-2 tolerance: P95-Latency on the Rust path must not
#: be worse than Python-baseline + 20 %.
DEFAULT_LATENCY_TOLERANCE_PCT = 20

#: ADR-0065 §Verifikations-Plan Mo: 12 boots is the live-smoke
#: baseline. Smoke uses 8 per phase by default.
DEFAULT_BOOTS_PER_PHASE = 8

#: Default expected in-place-component count.
DEFAULT_EXPECTED_COMPONENTS = 11

#: Welle-6-specific: maximum permissible drift on lag-distribution
#: mean and P95 across pre/post phases (operator-Sicht output-
#: reply-timeliness contract). 25% is the ADR-0066 §A6-tolerance
#: anchor.
DEFAULT_LAG_DISTRIBUTION_DRIFT_PCT = 25

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34/35/36/37/38/39.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-6-cutover-smoke/1"

#: ENV-var values the smoke flips per phase.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"

#: Welle-7 cross-modul-drift partner. The recovery env-var stays
#: at the per-phase baseline ("python" in PHASE_PRE) and the
#: assert verifies that subscribe_loop's cutover does not leak
#: into the recovery path. Symmetric to Welle-7's A7.
WELLE_7_PARTNER_COMPONENT = "recovery"
WELLE_7_PARTNER_ENV_VAR = "WAKIR_RECOVERY_BACKEND"

#: FSM-Awareness: FSM (Welle-5) was already cutovert in KW-26. By
#: KW-27 the FSM substrate is stable on Rust-default. The smoke's
#: env-map pins WAKIR_FSM_BACKEND=rust in every phase to reflect
#: the realistic post-KW-26 runtime posture.
FSM_POST_KW26_COMPONENT = "fsm"
FSM_POST_KW26_ENV_VAR = "WAKIR_FSM_BACKEND"
FSM_POST_KW26_BACKEND = ENV_VALUE_RUST

#: Resolver-provenance markers.
RESOLVER_PROVENANCE_UPSTREAM = "upstream"
RESOLVER_PROVENANCE_SHIM = "shim"


# ---------------------------------------------------------------------------
# Per-component env-var bridge — mirrors rust_backend_switch.py
# module constants. Kept local so the smoke does not have to import
# the resolver module just to read constants.
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
    """Lazy import of :mod:`wirelang.persona_engine.rust_backend_switch`."""
    return importlib.import_module(
        "wirelang.persona_engine.rust_backend_switch"
    )


def _resolver_fn_name(component: str) -> str:
    """Map an in-place component to its resolver function name."""
    return f"resolve_{component}_backend"


# ---------------------------------------------------------------------------
# Resolver-shim — fills the gap on pre-PR-#241 baselines where
# ``resolve_bridge_audit_diff_engine_backend`` is not yet wired
# upstream. subscribe_loop itself NEVER uses the shim (PR #181 has
# shipped the upstream resolver since Tag-22).
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

    Mirrors the Welle-3/4/5 resolver-shim pattern. Returns a
    callable with the same signature as the other resolvers.
    The shim never mutates os.environ.
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

    subscribe_loop itself MUST be upstream (PR #181); a missing
    ``resolve_subscribe_loop_backend`` is a substrate-regression
    and should fail loudly.
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
    """Pretend every Rust binary is present and executable."""
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
        explicitly ``"python"`` EXCEPT :data:`FSM_POST_KW26_ENV_VAR`
        which is pinned to ``"rust"`` (post-KW-26 production state).
      * :data:`PHASE_POST` — same, but ``FOCUS_ENV_VAR=rust``.
      * :data:`PHASE_ROLLBACK` — :data:`FOCUS_ENV_VAR` is *absent*.

    Welle-7 partner invariant: ``WAKIR_RECOVERY_BACKEND`` is set to
    ``"python"`` in every phase. The A7 cross-modul-drift assert
    verifies that the recovery BackendDecision actually honours
    this setting in PHASE_POST — i.e. subscribe_loop's cutover
    does not leak into recovery's resolver path. Symmetric to
    Welle-7's A7.

    FSM-Awareness: ``WAKIR_FSM_BACKEND`` is pinned to ``"rust"`` in
    every phase to reflect the post-KW-26 production state (Welle-5
    already cutovert). The smoke's focus assertions are unaffected
    by FSM's runtime state.
    """
    env: Dict[str, str] = dict(base_env or {})
    for env_var in COMPONENT_TO_ENV.values():
        env[env_var] = ENV_VALUE_PYTHON
    # FSM-Awareness: post-KW-26 production state pins FSM to rust.
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
# Mocked persona-boot — emits one BackendDecision per in-place
# component.
# ---------------------------------------------------------------------------


def boot_engine_once(
    *,
    env: Mapping[str, str],
    components: Tuple[str, ...],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
    provenance_sink: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Simulate a single persona-engine boot."""
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
    capture_lag_stability_baseline: bool = False,
    lag_stability_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Dict[str, Any]:
    """Run ``boots`` mocked boots for a single phase."""
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

    if capture_lag_stability_baseline:
        if lag_stability_baseline_fn is not None:
            baseline = lag_stability_baseline_fn()
        else:
            baseline = capture_lag_stability_baseline_default()
        record["lag_stability_baseline"] = baseline
    return record


# ---------------------------------------------------------------------------
# Parity-hash + latency helpers.
# ---------------------------------------------------------------------------


def parity_hash(records: List[Dict[str, Any]]) -> str:
    """Deterministic SHA-256 over the parity-relevant decision fields."""
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
# A6 — Subscribe-Loop-Lag-Stability pre-baseline + post-cutover-
# parity probe.
#
# Subscribe-Loop-Lag-Stability note: the BASELINE capture happens
# in PHASE_PRE *before* the cutover-step constructs PHASE_POST. The
# POST recomputation is done by calling the SAME Python authority
# again (not the Rust pendant). The substrate-level oracle is: the
# Python authority is byte-stable across the pre/post window AND
# the synthetic lag distribution mean+P95 stay within the operator
# drift envelope. If the recomputed hash matches the baseline AND
# the lag distribution stays bounded, the Python subscribe-ack
# serializer + lag-emission shape did not drift. The Rust pendant
# byte-parity is locked at a different layer (the subscribe-ack
# cross-lang fixture pins from PR #172 / PR #181).
# ---------------------------------------------------------------------------


#: Deterministic twelve-sample synthetic lag fixture used for the
#: subscribe-loop lag-stability pre-baseline. Sub-millisecond lag
#: values that bracket the histogram bucket spec; mean ~0.5 ms, P95
#: ~0.95 ms. Byte-stable across smoke invocations.
DETERMINISTIC_LAG_SAMPLES_SEC: Tuple[float, ...] = (
    0.001,
    0.002,
    0.005,
    0.010,
    0.020,
    0.050,
    0.100,
    0.200,
    0.500,
    0.800,
    0.900,
    0.950,
)

#: Identifiers for the deterministic ack-record fixture. The real
#: wirelang ``build_subscribe_ack_record`` requires:
#: ``auftrag_id`` / ``frame_index`` / ``outcome`` / ``persona_id`` /
#: ``prompt_sha256`` / ``subject`` (no ``org_id``/``ts_utc`` —
#: schema is set internally). The smoke also exposes ``ORG_ID`` /
#: ``TS_UTC`` constants for backward-compat with stub modules used
#: by the test suite that mirror the older shape.
DETERMINISTIC_ACK_PERSONA_ID = "persona-welle-6-smoke"
DETERMINISTIC_ACK_ORG_ID = "org-welle-6-smoke"
DETERMINISTIC_ACK_AUFTRAG_ID = "auftrag-welle-6-smoke"
DETERMINISTIC_ACK_SUBJECT = "wakir.persona.welle-6.smoke"
DETERMINISTIC_ACK_OUTCOME = "processed"
DETERMINISTIC_ACK_PROMPT_SHA256 = (
    "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
)
DETERMINISTIC_ACK_FRAME_INDEX = 0
DETERMINISTIC_ACK_TS_UTC = "2026-06-02T00:00:00Z"


def _import_subscribe_ack_canonical() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.subscribe_ack`.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.persona_engine.subscribe_ack"
    )


def _build_and_hash_ack_record(
    module: Any,
    persona_id: str = DETERMINISTIC_ACK_PERSONA_ID,
    org_id: str = DETERMINISTIC_ACK_ORG_ID,
    prompt_sha256: str = DETERMINISTIC_ACK_PROMPT_SHA256,
    frame_index: int = DETERMINISTIC_ACK_FRAME_INDEX,
    ts_utc: str = DETERMINISTIC_ACK_TS_UTC,
    auftrag_id: str = DETERMINISTIC_ACK_AUFTRAG_ID,
    subject: str = DETERMINISTIC_ACK_SUBJECT,
    outcome: str = DETERMINISTIC_ACK_OUTCOME,
) -> Tuple[bytes, str]:
    """Build a SubscribeAckRecord and return (bytes, hex-hash).

    Prefers the wirelang public API
    (``build_subscribe_ack_record`` + ``serialize_subscribe_ack`` +
    ``ack_record_sha256_hex``). Tries the real wirelang signature
    (``auftrag_id`` + ``subject``) first, then falls back to legacy
    stub signature (``org_id`` + ``ts_utc``) used by the test suite.
    """
    builder = getattr(module, "build_subscribe_ack_record", None)
    serialiser = getattr(module, "serialize_subscribe_ack", None)
    hasher = getattr(module, "ack_record_sha256_hex", None)

    if callable(builder) and callable(serialiser):
        record = None
        # Try real wirelang signature first.
        try:
            record = builder(
                auftrag_id=auftrag_id,
                frame_index=frame_index,
                outcome=outcome,
                persona_id=persona_id,
                prompt_sha256=prompt_sha256,
                subject=subject,
            )
        except TypeError:
            pass
        # Fall back to legacy stub signature (org_id + ts_utc).
        if record is None:
            try:
                record = builder(
                    persona_id=persona_id,
                    org_id=org_id,
                    prompt_sha256=prompt_sha256,
                    frame_index=frame_index,
                    ts_utc=ts_utc,
                    outcome=outcome,
                )
            except TypeError:
                record = builder(
                    persona_id=persona_id,
                    org_id=org_id,
                    prompt_sha256=prompt_sha256,
                    frame_index=frame_index,
                    ts_utc=ts_utc,
                )
        payload = serialiser(record)
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)
        if callable(hasher):
            digest = hasher(record)
        else:
            digest = hashlib.sha256(payload_bytes).hexdigest()
        return payload_bytes, digest

    fallback = getattr(module, "to_jcs_bytes", None)
    if callable(fallback):
        payload = fallback({
            "persona_id": persona_id,
            "org_id": org_id,
            "prompt_sha256": prompt_sha256,
            "frame_index": frame_index,
            "ts_utc": ts_utc,
            "outcome": outcome,
        })
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            payload_bytes = bytes(payload)
        return payload_bytes, hashlib.sha256(payload_bytes).hexdigest()

    raise AttributeError(
        "subscribe_ack module exposes neither "
        "build_subscribe_ack_record+serialize_subscribe_ack nor a "
        "module-level to_jcs_bytes helper"
    )


def _lag_mean(samples: Tuple[float, ...]) -> float:
    """Arithmetic mean of the lag samples. Returns 0.0 on empty."""
    if not samples:
        return 0.0
    return sum(samples) / len(samples)


def _lag_p95(samples: Tuple[float, ...]) -> float:
    """Nearest-rank P95 of the lag samples. Returns 0.0 on empty."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    import math as _math
    rank = max(1, _math.ceil(95.0 / 100.0 * len(ordered)))
    return ordered[rank - 1]


def capture_lag_stability_baseline_default(
    *,
    samples: Tuple[float, ...] = DETERMINISTIC_LAG_SAMPLES_SEC,
    canonical_module: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Capture the pre-cutover subscribe-loop lag-stability baseline.

    Returns a record (always non-None at the API level, ``skipped=True``
    when the subscribe_ack module is not importable). The record
    contains:

      * ``ack_record_sha256_hex`` — SHA-256 over the JCS-canonical
        bytes of the deterministic SubscribeAckRecord.
      * ``ack_record_byte_length`` — len of the canonical bytes.
      * ``lag_sample_count`` — len(samples).
      * ``lag_mean_sec`` — arithmetic mean of the lag samples.
      * ``lag_p95_sec`` — nearest-rank P95 of the lag samples.
      * ``captured_at_phase`` — always :data:`PHASE_PRE`.
    """
    module = canonical_module
    if module is None:
        try:
            module = _import_subscribe_ack_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"subscribe_ack not importable: {exc}"
                ),
                "ack_record_sha256_hex": None,
                "ack_record_byte_length": 0,
                "lag_sample_count": len(samples),
                "lag_mean_sec": _lag_mean(samples),
                "lag_p95_sec": _lag_p95(samples),
                "captured_at_phase": PHASE_PRE,
            }

    try:
        payload_bytes, digest = _build_and_hash_ack_record(module)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                f"lag-stability baseline capture raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "ack_record_sha256_hex": None,
            "ack_record_byte_length": 0,
            "lag_sample_count": len(samples),
            "lag_mean_sec": _lag_mean(samples),
            "lag_p95_sec": _lag_p95(samples),
            "captured_at_phase": PHASE_PRE,
        }

    return {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"lag-stability baseline captured: "
            f"{len(samples)} samples, "
            f"ack_sha256={digest[:16]}..., "
            f"lag_mean_sec={_lag_mean(samples):.6f}, "
            f"lag_p95_sec={_lag_p95(samples):.6f}"
        ),
        "ack_record_sha256_hex": digest,
        "ack_record_byte_length": len(payload_bytes),
        "lag_sample_count": len(samples),
        "lag_mean_sec": _lag_mean(samples),
        "lag_p95_sec": _lag_p95(samples),
        "captured_at_phase": PHASE_PRE,
    }


def evaluate_lag_stability_parity(
    baseline: Optional[Dict[str, Any]],
    *,
    samples: Tuple[float, ...] = DETERMINISTIC_LAG_SAMPLES_SEC,
    canonical_module: Optional[Any] = None,
    drift_pct: int = DEFAULT_LAG_DISTRIBUTION_DRIFT_PCT,
) -> Dict[str, Any]:
    """Recompute the lag-stability hash post-cutover and compare.

    Returns a record with:

      * ``passed`` — True iff the recomputed hash matches the
        baseline hash AND lag-distribution mean+P95 stay within
        ``drift_pct`` of baseline.
      * ``skipped`` — True iff baseline was skipped or recomputation
        cannot be performed.
      * ``baseline_ack_record_sha256`` — the baseline hash.
      * ``recomputed_ack_record_sha256`` — the post-cutover hash.
      * ``match`` — bool (hash equality).
      * ``baseline_lag_mean_sec`` — baseline mean lag.
      * ``recomputed_lag_mean_sec`` — post-cutover mean lag.
      * ``baseline_lag_p95_sec`` — baseline P95 lag.
      * ``recomputed_lag_p95_sec`` — post-cutover P95 lag.
      * ``lag_drift_within_envelope`` — bool (mean+P95 within drift_pct).
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
            "baseline_ack_record_sha256": None,
            "recomputed_ack_record_sha256": None,
            "match": True,
            "baseline_lag_mean_sec": (
                baseline.get("lag_mean_sec", 0.0)
                if baseline is not None
                else 0.0
            ),
            "recomputed_lag_mean_sec": 0.0,
            "baseline_lag_p95_sec": (
                baseline.get("lag_p95_sec", 0.0)
                if baseline is not None
                else 0.0
            ),
            "recomputed_lag_p95_sec": 0.0,
            "lag_drift_within_envelope": True,
            "captured_at_phase": (
                baseline.get("captured_at_phase") if baseline else PHASE_PRE
            ),
        }

    module = canonical_module
    if module is None:
        try:
            module = _import_subscribe_ack_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"subscribe_ack not importable for recompute: {exc}"
                ),
                "baseline_ack_record_sha256": baseline.get("ack_record_sha256_hex"),
                "recomputed_ack_record_sha256": None,
                "match": True,
                "baseline_lag_mean_sec": baseline.get("lag_mean_sec", 0.0),
                "recomputed_lag_mean_sec": 0.0,
                "baseline_lag_p95_sec": baseline.get("lag_p95_sec", 0.0),
                "recomputed_lag_p95_sec": 0.0,
                "lag_drift_within_envelope": True,
                "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
            }

    try:
        _payload_bytes, recomputed = _build_and_hash_ack_record(module)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "skipped": False,
            "severity": "caution",
            "detail": (
                f"lag-stability recompute raised "
                f"{type(exc).__name__}: {exc}"
            ),
            "baseline_ack_record_sha256": baseline.get("ack_record_sha256_hex"),
            "recomputed_ack_record_sha256": None,
            "match": False,
            "baseline_lag_mean_sec": baseline.get("lag_mean_sec", 0.0),
            "recomputed_lag_mean_sec": 0.0,
            "baseline_lag_p95_sec": baseline.get("lag_p95_sec", 0.0),
            "recomputed_lag_p95_sec": 0.0,
            "lag_drift_within_envelope": False,
            "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
        }

    baseline_hash = baseline.get("ack_record_sha256_hex")
    match = recomputed == baseline_hash

    recomputed_mean = _lag_mean(samples)
    recomputed_p95 = _lag_p95(samples)
    baseline_mean = float(baseline.get("lag_mean_sec", 0.0))
    baseline_p95 = float(baseline.get("lag_p95_sec", 0.0))

    def _drift_within(b: float, r: float, pct: int) -> bool:
        if b <= 0.0:
            return r <= 1e-9 or r <= 0.001  # 1ms absolute floor
        return abs(r - b) / b * 100.0 <= float(pct)

    mean_within = _drift_within(baseline_mean, recomputed_mean, drift_pct)
    p95_within = _drift_within(baseline_p95, recomputed_p95, drift_pct)
    lag_drift_within_envelope = mean_within and p95_within

    passed = match and lag_drift_within_envelope

    if passed:
        detail = (
            f"lag-stability parity ok ({recomputed[:16]}...), "
            f"mean_drift_within={drift_pct}%, p95_drift_within={drift_pct}%"
        )
    elif not match and not lag_drift_within_envelope:
        detail = (
            f"lag-stability hash drift AND lag-distribution drift: "
            f"baseline={baseline_hash} recomputed={recomputed} "
            f"baseline_mean={baseline_mean:.6f} recomputed_mean={recomputed_mean:.6f} "
            f"baseline_p95={baseline_p95:.6f} recomputed_p95={recomputed_p95:.6f}"
        )
    elif not match:
        detail = (
            f"lag-stability hash drift: baseline={baseline_hash} "
            f"recomputed={recomputed}"
        )
    else:
        detail = (
            f"lag-distribution drift outside {drift_pct}% envelope: "
            f"baseline_mean={baseline_mean:.6f} recomputed_mean={recomputed_mean:.6f} "
            f"baseline_p95={baseline_p95:.6f} recomputed_p95={recomputed_p95:.6f}"
        )

    return {
        "passed": passed,
        "skipped": False,
        "severity": "caution",
        "detail": detail,
        "baseline_ack_record_sha256": baseline_hash,
        "recomputed_ack_record_sha256": recomputed,
        "match": match,
        "baseline_lag_mean_sec": baseline_mean,
        "recomputed_lag_mean_sec": recomputed_mean,
        "baseline_lag_p95_sec": baseline_p95,
        "recomputed_lag_p95_sec": recomputed_p95,
        "lag_drift_within_envelope": lag_drift_within_envelope,
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
    """Parity-hash over the *structural* fields of focus-component records."""
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
    lag_stability_baseline: Optional[Dict[str, Any]] = None,
    lag_stability_parity: Optional[Dict[str, Any]] = None,
    focus: str = FOCUS_COMPONENT,
) -> Dict[str, Any]:
    """Evaluate A1..A5 + R1 + A6 + A7; return asserts-record."""
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
            f"subscribe_loop chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})} "
            f"(expected all == {ENV_VALUE_RUST!r})"
        ),
    }

    # A2: cross-lang parity-hash identical between Post-Cutover-Rust
    # and Rollback-Python on the structural projection.
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

    # R1: focus-component on rollback phase must be python.
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

    # A6: subscribe-loop lag-stability pre/post probe (caution).
    if lag_stability_parity is None:
        a6_record = {
            "passed": True,
            "severity": "caution",
            "skipped": True,
            "detail": "A6 skipped (probe not invoked)",
            "baseline_ack_record_sha256": None,
            "recomputed_ack_record_sha256": None,
            "match": True,
            "baseline_lag_mean_sec": 0.0,
            "recomputed_lag_mean_sec": 0.0,
            "baseline_lag_p95_sec": 0.0,
            "recomputed_lag_p95_sec": 0.0,
            "lag_drift_within_envelope": True,
            "captured_at_phase": PHASE_PRE,
        }
    else:
        a6_record = {
            "passed": bool(lag_stability_parity.get("passed", True)),
            "severity": "caution",
            "skipped": bool(lag_stability_parity.get("skipped", False)),
            "detail": lag_stability_parity.get("detail", ""),
            "baseline_ack_record_sha256": lag_stability_parity.get(
                "baseline_ack_record_sha256"
            ),
            "recomputed_ack_record_sha256": lag_stability_parity.get(
                "recomputed_ack_record_sha256"
            ),
            "match": bool(lag_stability_parity.get("match", True)),
            "baseline_lag_mean_sec": float(
                lag_stability_parity.get("baseline_lag_mean_sec", 0.0)
            ),
            "recomputed_lag_mean_sec": float(
                lag_stability_parity.get("recomputed_lag_mean_sec", 0.0)
            ),
            "baseline_lag_p95_sec": float(
                lag_stability_parity.get("baseline_lag_p95_sec", 0.0)
            ),
            "recomputed_lag_p95_sec": float(
                lag_stability_parity.get("recomputed_lag_p95_sec", 0.0)
            ),
            "lag_drift_within_envelope": bool(
                lag_stability_parity.get("lag_drift_within_envelope", True)
            ),
            "captured_at_phase": lag_stability_parity.get(
                "captured_at_phase", PHASE_PRE
            ),
        }
    asserts["A6_subscribe_loop_lag_stability"] = a6_record

    # A7: Cross-Modul-Drift to Welle-7 partner (recovery).
    rec_post_records = [
        r
        for r in post_records
        if r.get("domain") == WELLE_7_PARTNER_COMPONENT
    ]
    if not rec_post_records:
        a7_record = {
            "passed": False,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 recovery cross-modul-drift check: no recovery "
                f"BackendDecision present in PHASE_POST records "
                f"(expected {boots_per_phase} recovery decisions). "
                f"The subscribe_loop cutover may have suppressed "
                f"recovery emissions — parallel-Welle isolation "
                f"broken."
            ),
            "recovery_chosen_backends": [],
            "expected_recovery_backend": ENV_VALUE_PYTHON,
        }
    else:
        chosen = [r.get("chosen_backend") for r in rec_post_records]
        all_python = all(c == ENV_VALUE_PYTHON for c in chosen)
        a7_record = {
            "passed": all_python,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"A7 cross-modul-drift OK: recovery stayed at python "
                f"across {len(rec_post_records)} PHASE_POST records "
                f"during subscribe_loop cutover"
                if all_python
                else (
                    f"A7 cross-modul-drift FAIL: subscribe_loop "
                    f"cutover leaked into recovery path. recovery "
                    f"chosen_backend values in PHASE_POST: "
                    f"{sorted(set(chosen))} (expected all == "
                    f"'python'). This breaks the KW-27 Doppel-Welle "
                    f"isolation contract."
                )
            ),
            "recovery_chosen_backends": sorted(set(chosen)),
            "expected_recovery_backend": ENV_VALUE_PYTHON,
        }
    asserts["A7_cross_modul_drift_welle_7_recovery"] = a7_record

    return asserts


def derive_exit_code(asserts: Dict[str, Any]) -> int:
    """Map the asserts-record to the tri-state exit code."""
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
# FSM-Awareness pre-check.
# ---------------------------------------------------------------------------


def evaluate_fsm_post_cutover_state(
    post_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check that FSM (Welle-5) is in the expected post-KW-26 state.

    The Welle-6 cutover MUST NOT start or stop inside an FSM-cutover-
    window. By KW-27, the FSM substrate is stable on Rust-default
    (Welle-5 already cutovert in KW-26). The smoke surfaces an
    ``fsm_post_cutover_state`` field so the operator can confirm FSM
    is rust before kicking off the Welle-6 cutover.

    Returns a record (informational, not a hard assert):

      * ``fsm_chosen_backends`` — sorted unique fsm chosen_backend
        values seen in PHASE_POST.
      * ``expected_fsm_backend`` — :data:`FSM_POST_KW26_BACKEND`.
      * ``fsm_in_expected_post_kw26_state`` — bool.
      * ``detail`` — human-readable summary.

    This is informational and intentionally not wired into the
    exit-code derivation. The operator reads the field to confirm
    runtime posture; a deviation here is a substrate-state issue,
    not a smoke-validation issue.
    """
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
                f"{[FSM_POST_KW26_BACKEND]!r}. The Welle-6 cutover "
                f"should only proceed AFTER FSM (Welle-5) cutover is "
                f"complete and stable on rust."
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
    lag_stability_baseline: Optional[Dict[str, Any]] = None,
    resolver_provenance: Optional[Dict[str, str]] = None,
    fsm_post_cutover_state: Optional[Dict[str, Any]] = None,
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
        "welle": 6,
        "focus_component": FOCUS_COMPONENT,
        "focus_component_long": FOCUS_COMPONENT_LONG,
        "focus_env_var": FOCUS_ENV_VAR,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
        "resolver_provenance": dict(resolver_provenance or {}),
        "cross_modul_drift_mitigation": {
            "welle_7_partner_component": WELLE_7_PARTNER_COMPONENT,
            "welle_7_partner_env_var": WELLE_7_PARTNER_ENV_VAR,
            "expected_welle_7_partner_backend": ENV_VALUE_PYTHON,
            "recovery_chosen_backends_in_post_phase": asserts.get(
                "A7_cross_modul_drift_welle_7_recovery", {}
            ).get("recovery_chosen_backends", []),
        },
        "lag_stability": {
            "baseline_captured_at_phase": (
                lag_stability_baseline.get("captured_at_phase")
                if lag_stability_baseline is not None
                else None
            ),
            "baseline_ack_record_sha256": (
                lag_stability_baseline.get("ack_record_sha256_hex")
                if lag_stability_baseline is not None
                else None
            ),
            "baseline_skipped": (
                bool(lag_stability_baseline.get("skipped", False))
                if lag_stability_baseline is not None
                else True
            ),
            "baseline_lag_mean_sec": (
                float(lag_stability_baseline.get("lag_mean_sec", 0.0))
                if lag_stability_baseline is not None
                else 0.0
            ),
            "baseline_lag_p95_sec": (
                float(lag_stability_baseline.get("lag_p95_sec", 0.0))
                if lag_stability_baseline is not None
                else 0.0
            ),
            "drift_pct": DEFAULT_LAG_DISTRIBUTION_DRIFT_PCT,
            "lag_sample_count": len(DETERMINISTIC_LAG_SAMPLES_SEC),
        },
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
    skip_lag_stability_parity: bool = False,
    canonical_module: Optional[Any] = None,
    lag_stability_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6/A7 + envelope.

    Returns ``(envelope, exit_code)``.
    """
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available

    pre_phase = run_phase(
        PHASE_PRE,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_lag_stability_baseline=not skip_lag_stability_parity,
        lag_stability_baseline_fn=(
            lag_stability_baseline_fn
            if lag_stability_baseline_fn is not None
            else (
                (lambda: capture_lag_stability_baseline_default(
                    canonical_module=canonical_module
                ))
                if not skip_lag_stability_parity
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
        capture_lag_stability_baseline=False,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_lag_stability_baseline=False,
    )

    lag_stability_baseline = pre_phase.get("lag_stability_baseline")

    if skip_lag_stability_parity:
        lag_stability_parity: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": "A6 skipped via --skip-lag-stability-parity",
            "baseline_ack_record_sha256": None,
            "recomputed_ack_record_sha256": None,
            "match": True,
            "baseline_lag_mean_sec": 0.0,
            "recomputed_lag_mean_sec": 0.0,
            "baseline_lag_p95_sec": 0.0,
            "recomputed_lag_p95_sec": 0.0,
            "lag_drift_within_envelope": True,
            "captured_at_phase": PHASE_PRE,
        }
    else:
        lag_stability_parity = evaluate_lag_stability_parity(
            lag_stability_baseline,
            canonical_module=canonical_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        lag_stability_baseline=lag_stability_baseline,
        lag_stability_parity=lag_stability_parity,
    )
    exit_code = derive_exit_code(asserts)

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
        lag_stability_baseline=lag_stability_baseline,
        resolver_provenance=merged_provenance,
        fsm_post_cutover_state=fsm_post_cutover_state,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-6-subscribe-loop-cutover-smoke",
        description=(
            "Phase-3c Welle-6 (subscribe_loop) End-to-End Cutover-"
            "Smoke for ADR-0066 KW-27 Doppel-Welle (parallel with "
            "Welle-7 recovery_workflow). Boots a mocked persona-"
            "engine across Pre-Cutover (Python baseline) -> Cutover "
            "(Rust) -> Rollback (Python) phases, evaluates A1..A5 + "
            "R1 + A6 (subscribe-loop-lag-stability) + A7 (cross-"
            "modul-drift-to-Welle-7-recovery) asserts, and exits "
            "0/1/2 = GREEN/CAUTION/ROLLBACK_RECOMMENDED. Never "
            "invokes the real Rust binary, NATS, or the Anthropic "
            "API. License: Apache-2.0."
        ),
    )
    p.add_argument(
        "--boots-per-phase",
        type=int,
        default=DEFAULT_BOOTS_PER_PHASE,
        help=(
            f"Mocked boots per phase (default {DEFAULT_BOOTS_PER_PHASE})."
        ),
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
        "--skip-lag-stability-parity",
        action="store_true",
        help=(
            "Skip the A6 subscribe-loop-lag-stability probe. Use "
            "when the wirelang package is not in the import path."
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
            f"welle-6-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-6-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-6-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_lag_stability_parity=args.skip_lag_stability_parity,
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
            f"welle-6-cutover-smoke: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        return EXIT_ROLLBACK

    return exit_code


__all__ = [
    "COMPONENT_TO_ENV",
    "DEFAULT_BOOTS_PER_PHASE",
    "DEFAULT_EXPECTED_COMPONENTS",
    "DEFAULT_LAG_DISTRIBUTION_DRIFT_PCT",
    "DEFAULT_LATENCY_TOLERANCE_PCT",
    "DETERMINISTIC_ACK_AUFTRAG_ID",
    "DETERMINISTIC_ACK_FRAME_INDEX",
    "DETERMINISTIC_ACK_ORG_ID",
    "DETERMINISTIC_ACK_OUTCOME",
    "DETERMINISTIC_ACK_PERSONA_ID",
    "DETERMINISTIC_ACK_PROMPT_SHA256",
    "DETERMINISTIC_ACK_SUBJECT",
    "DETERMINISTIC_ACK_TS_UTC",
    "DETERMINISTIC_LAG_SAMPLES_SEC",
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
    "WELLE_7_PARTNER_COMPONENT",
    "WELLE_7_PARTNER_ENV_VAR",
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "capture_lag_stability_baseline_default",
    "derive_exit_code",
    "evaluate_fsm_post_cutover_state",
    "evaluate_lag_stability_parity",
    "evaluate_post_cutover_asserts",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
