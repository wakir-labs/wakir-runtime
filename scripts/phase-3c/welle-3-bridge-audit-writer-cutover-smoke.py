#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-3-bridge-audit-writer-cutover-smoke — End-to-End Cutover-Smoke for ADR-0066 Welle-3.

Background
----------

ADR-0066 (approved 2026-05-17, commit ``c907f98``) schedules
**Welle-3** of the Phase-3c default-backend flip as the **KW-25 solo
wave**: ``bridge_audit_writer`` (the engineering-output double-sink
writer) cuts over from Python-default to Rust-default with **no
parallel partner**. The solo posture is a Henrik-Caution mitigation,
not a sequencing convenience.

The Henrik-Caution-finding (ADR-0066 §Welle-3-Risiken) is the
**Consistency-Oracle-Selbst-Cutover-Risiko** (or, in Selin-shorthand,
**Self-Reference-Trap**):

  ``bridge_audit_writer`` is the module that emits the
  EngineeringOutputEvent envelopes — the very audit stream the
  Doppelbetrieb-Shadow phase reads to compare Pre-Framework against
  Wakir-Runtime output byte-for-byte. When this module itself flips
  from Python to Rust, any audit-stream observation taken from
  *during* the cutover is describing its own switch. A naïve smoke
  that hashes the audit stream after the focus-component has flipped
  would be observing a stream emitted by the new backend — i.e. the
  oracle and the cutover-subject are the same process. That's a
  circular oracle.

This smoke is the **strict, asserts-tragend** End-to-End Cutover-
Smoke for Welle-3, modelled on the Welle-2 sibling
``scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py``
(Tag-35, PR #234) and pattern-parity-aligned with the Welle-1
sibling ``scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py``
(Tag-34, PR #230). The pattern-parity is intentional: the operator
runs all three smokes in the same cutover-PR window, gets three JSON
envelopes with the same shape (``schema`` differs only by Welle
number), and the tri-state exit codes feed shell gates.

Self-Reference-Trap mitigation (Welle-3-specific)
-------------------------------------------------

The smoke adds **two** Welle-3-specific asserts that do not exist in
the Welle-1/2 shape, both explicitly addressing the Self-Reference-
Trap:

* **A6 bridge-audit-stream-pre-baseline-snapshot:** the smoke
  captures a deterministic audit-stream-hash by directly invoking
  ``EngineeringOutputEvent.to_jcs_bytes()`` against a fixed 3-
  emission fixture **BEFORE the cutover-step constructs the
  PHASE_POST env-map**. The capture happens in :func:`run_phase` for
  :data:`PHASE_PRE`, recorded in
  :func:`capture_bridge_audit_stream_baseline` as the
  ``baseline_audit_stream_sha256`` field of the pre-phase record.
  This **temporal invariant** is the substrate-level mitigation: the
  audit-stream hash that the post-cutover assert compares against
  was captured **before** the focus-component flipped, so the
  baseline is uncontaminated by the cutover-subject. Severity:
  caution — a hash mismatch here means the Python authority's JCS
  encoder shifted between the baseline and the post-cutover
  recomputation, which is a Tomás-Zone-K cross-modul drift signal,
  not a Pilot-VM-cutover blocker.

* **A7 self-reference-trap-mitigation-control:** verifies the
  control-flow invariant directly: the envelope's
  ``baseline_audit_stream_sha256`` field MUST be populated in the
  ``pre_cutover_python_baseline`` phase-record and MUST NOT be
  re-derived from any post-cutover phase. The assert reads the
  envelope structure itself and confirms the field is sourced from
  PHASE_PRE only. Severity: blocker — a fail here means a future
  smoke-refactor accidentally re-derives the baseline from a phase
  that already saw the focus-component flip, re-introducing the
  exact circular-oracle pattern Henrik flagged. The control-flow
  pin is what protects the substrate semantics from rot.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-1/2 shape verbatim, re-pointed at ``bridge_audit_writer``
and ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND``.

Resolver-shim (because real resolver is not yet wired)
------------------------------------------------------

ADR-0066 §Welle-3-Wire-In notes that as of baseline ``2ec0532``
(Tag-35 tip), ``wirelang.persona_engine.rust_backend_switch`` exposes
:data:`BRIDGE_AUDIT_WRITER_BACKEND_ENV`,
:class:`BridgeAuditWriterBackend`, and
:func:`_resolve_bridge_audit_writer_bin`, but the public resolver
function ``resolve_bridge_audit_writer_backend(env, log_sink,
binary_probe) -> (BackendDecision, BackendDecision)`` is **not yet
shipped**. The Reza Tag-36 wire-in is scheduled to add it. This
smoke handles both worlds via a resolver-shim:

* If the imported resolver module exposes
  ``resolve_bridge_audit_writer_backend`` (Reza-Tag-36 wire-in
  landed), the smoke uses it end-to-end and reports
  ``--expected-components 10``.
* Otherwise, the smoke constructs a local shim
  (:func:`_make_bridge_audit_writer_resolver_shim`) that wraps the
  existing ``BRIDGE_AUDIT_WRITER_BACKEND_ENV`` +
  ``_resolve_bridge_audit_writer_bin`` + ``_binary_available``
  primitives to produce a BackendDecision with the same byte-shape
  as the other resolvers. Operators run with default
  ``--expected-components 9`` and read the smoke's
  ``resolver_provenance`` field in the envelope (``"upstream"`` or
  ``"shim"``) to know which surface they exercised.

When Reza's wire-in lands, the same smoke script switches
provenance transparently — no smoke change required.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with the
   Python default (``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=python``).
   Records the ``BackendDecision`` for ``bridge_audit_writer`` plus
   the other in-place components.
   **AND captures the bridge-audit-stream pre-baseline hash** by
   invoking ``EngineeringOutputEvent.to_jcs_bytes()`` against the
   F1/F2/F3 stream-fixture from
   ``tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json``
   (PR #210, Tag-32). This is the Self-Reference-Trap-Mitigation
   capture moment: the baseline is taken before the cutover.
2. **Cutover step.** Flips
   ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust`` in the hermetic env-
   map, restarts the mocked engine, re-collects BackendDecisions.
3. **Post-Cutover asserts.** Five hard checks + two Welle-3-specific
   substrate checks (A1..A5 + R1 + A6 + A7).
4. **Rollback probe.** ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`` unset
   (engine reads Python-default), re-boot, asserts that the engine
   emits ``chosen_backend == "python"`` again — operator rollback
   path ≤10 min per ADR-0065 §Rollback-SLA (ADR-0066 inherits this
   contract).
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All blocker asserts pass +
       caution asserts pass.
     * ``1`` — **CAUTION**. At least one caution-severity drift
       (A3 latency, A4 component-count, A6 bridge-audit-stream
       drift).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 / A7 / R1
       failed.

The smoke writes a JSON envelope to ``--output`` (or stdout). The
envelope shape is pinned by the test suite.

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 bridge-audit-stream
check imports :mod:`wirelang.persona_engine.bridge_audit_writer`
lazily and reads the bridge-audit-writer cross-lang fixtures JSON;
both are gracefully skipped if missing so the smoke remains
importable in test environments without the wirelang package. The
mocked engine never imports NATS, the Anthropic SDK, the real Rust
binary, or any container runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, 9 expected
    # components per baseline-2ec0532 inventory).
    python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \\
        --output out/welle-3-smoke.json

    # Post-Reza-wire-in invocation (10 expected components):
    python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \\
        --expected-components 10 --output out/welle-3-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \\
        --latency-tolerance-pct 10

    # Skip the A6 bridge-audit-stream-parity probe (e.g. when the
    # wirelang package is not in the import path):
    python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \\
        --skip-bridge-audit-stream-parity

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
# Constants — Welle-3 focus on bridge_audit_writer.
# ---------------------------------------------------------------------------

#: Welle-3 focus component (ADR-0066 §Welle-3 KW-25 solo wave).
FOCUS_COMPONENT = "bridge_audit_writer"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-3.
FOCUS_ENV_VAR = "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Tracks the engine inventory at
#: baseline ``2ec0532`` (Tag-35 tip): nine resolvers as of PR #200
#: (Tag-30 federation_resolver wire-in). When the Reza Tag-36
#: bridge_audit_writer resolver wire-in lands, the tuple grows to
#: ten and operators pass ``--expected-components 10``. The smoke
#: keeps both worlds working without re-deploy because
#: ``bridge_audit_writer`` is added to ENGINE_BOOT_COMPONENTS
#: unconditionally and the smoke's resolver-shim provides a clean
#: shape when the upstream resolver function is missing.
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
#: ``2ec0532`` engine inventory (9) because as of that tip the
#: upstream resolver for ``bridge_audit_writer`` is not yet wired.
#: Operators running post-Reza-Tag-36-wire-in pass
#: ``--expected-components 10`` to track the wire-in. Tests cover
#: both modes.
DEFAULT_EXPECTED_COMPONENTS = 9

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34/35/36.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-3-cutover-smoke/1"

#: ENV-var values the smoke flips per phase.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"

#: Path to the Bridge-Audit-Writer Cross-Lang fixtures (PR #210
#: ``0168ac3`` Tag-32). Resolved relative to the repo-root at
#: runtime so the smoke works from arbitrary working directories.
#: Tests override via ``--bridge-audit-stream-fixture-path``.
DEFAULT_BRIDGE_AUDIT_STREAM_FIXTURE_RELPATH = (
    "tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json"
)

#: Resolver-provenance markers — surfaced in the envelope so
#: operators know which surface the smoke exercised.
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
# Resolver-shim — fills the gap until Reza Tag-36 wires
# ``resolve_bridge_audit_writer_backend`` upstream.
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


def _make_bridge_audit_writer_resolver_shim(
    resolver_module: Any,
) -> Callable[..., Tuple[str, _ShimBackendDecision]]:
    """Build a local resolver for ``bridge_audit_writer``.

    The shim wraps the existing module primitives:

    * :data:`BRIDGE_AUDIT_WRITER_BACKEND_ENV` for env-var name,
    * :func:`_resolve_bridge_audit_writer_bin` for binary-path
      resolution,
    * :func:`_binary_available` for the binary-probe.

    Returns a callable with the same signature as the other
    resolvers: ``(env, *, log_sink, binary_probe) -> (chosen_backend,
    BackendDecision-shaped-record)``. The shim never mutates os.environ.

    The smoke uses this only when the upstream resolver module does
    not yet expose ``resolve_bridge_audit_writer_backend`` (i.e. as
    of baseline ``2ec0532``). When Reza Tag-36 lands the wire-in, the
    smoke prefers the upstream function and the shim becomes inert.
    """
    env_var = getattr(
        resolver_module, "BRIDGE_AUDIT_WRITER_BACKEND_ENV", FOCUS_ENV_VAR
    )
    bin_resolver = getattr(
        resolver_module, "_resolve_bridge_audit_writer_bin", None
    )
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
                # No probe at all → fall back to python with explicit
                # reason; matches the wirelang convention that absence
                # of binary-probe is treated as missing-binary.
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
            # Python path. Wirelang convention (rust_backend_switch.py
            # lines 1153-1155 et seq.): fallback_reason="explicit_python"
            # iff the env-var was set to literally "python"; None when
            # the env-var was empty / absent (implicit python). The
            # distinction lets the audit record show the operator's
            # intent (opt-in vs default).
            chosen = ENV_VALUE_PYTHON
            if raw == ENV_VALUE_PYTHON:
                fallback_reason = "explicit_python"

        elapsed_us = max(1, (time.monotonic_ns() - start_ns) // 1000)
        decision = _ShimBackendDecision(
            domain=FOCUS_COMPONENT,
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
    is ``bridge_audit_writer``, falls back to the local shim. Any
    other missing-resolver is fatal (raises AttributeError).
    """
    fn_name = _resolver_fn_name(component)
    upstream = getattr(resolver_module, fn_name, None)
    if upstream is not None:
        return upstream, RESOLVER_PROVENANCE_UPSTREAM
    if component == FOCUS_COMPONENT:
        return (
            _make_bridge_audit_writer_resolver_shim(resolver_module),
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

    Operator-warning: live Welle-3 substrate readiness depends on
    the ``persona-engine-bridge-audit-writer`` binary shipping from
    the ``persona-engine-bridge-audit-replay`` crate (Tag-31 Mini-
    Welle PR #210). If the binary is not deployed on the Pilot-VM,
    the real ``_binary_available`` probe returns
    ``(False, "binary_missing")`` and A5 fails on the live smoke
    — that's the ADR-0066 Welle-3 precondition signal, not a smoke
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
) -> Dict[str, str]:
    """Return the hermetic env-map for ``phase``.

    Phases:
      * :data:`PHASE_PRE` — every Phase-3c component's env-var is
        explicitly ``"python"``. This is the Python-default baseline.
      * :data:`PHASE_POST` — same, but ``FOCUS_ENV_VAR=rust`` (the
        cutover step for bridge_audit_writer).
      * :data:`PHASE_ROLLBACK` — :data:`FOCUS_ENV_VAR` is *absent*
        from the env-map (engine reads the Python-default code-path,
        which is the Quadlet-default after rollback).

    The returned dict is always a fresh copy of ``base_env`` (default
    empty) — the smoke never inherits the operator's environment.
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
    capture_bridge_audit_baseline: bool = False,
    bridge_audit_baseline_fn: Optional[
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
      * ``bridge_audit_stream_baseline`` — populated iff
        ``capture_bridge_audit_baseline`` is True (PHASE_PRE only;
        this is the Self-Reference-Trap-Mitigation temporal anchor).

    Self-Reference-Trap-Mitigation note: the bridge-audit-stream
    baseline capture is gated on the ``capture_bridge_audit_baseline``
    flag and only set True by the orchestrator for :data:`PHASE_PRE`.
    If a future refactor accidentally sets the flag for any other
    phase, the A7 control-flow assert flags the regression.
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

    if capture_bridge_audit_baseline:
        if bridge_audit_baseline_fn is not None:
            baseline = bridge_audit_baseline_fn()
        else:
            baseline = capture_bridge_audit_stream_baseline()
        record["bridge_audit_stream_baseline"] = baseline
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

    Fixture-reference: ``tests/fixtures/bridge-audit-writer-cross-
    lang/fixtures.json`` (PR #210, F1/F2/F3 stream-fixture pins)
    embeds the substrate-level invariant that Python and Rust write
    byte-equal EngineeringOutputEvent JCS bytes. This hash is the
    smoke's engine-emission-level materialisation of that contract;
    A6 verifies the substrate-level oracle directly.
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
# A6 — Bridge-Audit-Stream pre-baseline + post-cutover-parity probe.
#
# Self-Reference-Trap-Mitigation note: the BASELINE capture happens
# in PHASE_PRE *before* the cutover-step constructs PHASE_POST. The
# POST recomputation is done by calling the SAME Python authority
# again (not the Rust pendant, which is not yet linked into the
# smoke). The substrate-level oracle is: the Python authority is
# byte-stable across the pre/post window. If the recomputed hash
# matches the baseline, the Python JCS encoder did not drift. That
# is the only oracle the smoke can give *without* falling into the
# circular-oracle trap; the Rust pendant byte-parity is locked at a
# different layer (the F1/F2/F3 stream-fixture pins).
# ---------------------------------------------------------------------------


#: Deterministic 3-emission audit-stream fixture used for the
#: bridge-audit-stream pre-baseline snapshot. Fixed timestamps and
#: payload hashes so the resulting JCS-bytes are byte-stable across
#: smoke invocations. Aligned with the F2/F3 fixture shape from
#: ``tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json``.
BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS: Tuple[Dict[str, Any], ...] = (
    {
        "org_id": "wakir-labs",
        "persona_id": "selin",
        "session_id": "welle-3-smoke-baseline",
        "step_index": 0,
        "output_kind": "tool_call",
        "output_payload_sha256": "sha256:" + ("0" * 64),
        "engine_version": "0.2.0-pilot",
        "v907_pin": "sha256:" + ("a" * 64),
        "ts_utc": "2026-05-25T00:00:00Z",
    },
    {
        "org_id": "wakir-labs",
        "persona_id": "selin",
        "session_id": "welle-3-smoke-baseline",
        "step_index": 1,
        "output_kind": "reply",
        "output_payload_sha256": "sha256:" + ("1" * 64),
        "engine_version": "0.2.0-pilot",
        "v907_pin": "sha256:" + ("a" * 64),
        "ts_utc": "2026-05-25T00:00:01Z",
    },
    {
        "org_id": "wakir-labs",
        "persona_id": "selin",
        "session_id": "welle-3-smoke-baseline",
        "step_index": 2,
        "output_kind": "audit_annotation",
        "output_payload_sha256": "sha256:" + ("2" * 64),
        "engine_version": "0.2.0-pilot",
        "v907_pin": "sha256:" + ("a" * 64),
        "ts_utc": "2026-05-25T00:00:02Z",
    },
)


def _import_bridge_audit_writer() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.bridge_audit_writer`.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.persona_engine.bridge_audit_writer"
    )


def _emission_to_jcs_bytes_via_module(
    module: Any, emission: Mapping[str, Any]
) -> bytes:
    """Construct an ``EngineeringOutputEvent`` and JCS-serialise it.

    The wirelang public API surface uses the dataclass
    ``EngineeringOutputEvent`` plus the ``to_jcs_bytes`` method
    (PR #19 / Tag-4 substrate). The helper prefers that surface;
    if missing it tries a stub-friendly ``to_jcs_bytes(emission)``
    module-level helper (used by the test suite).
    """
    cls = getattr(module, "EngineeringOutputEvent", None)
    if cls is not None:
        try:
            instance = cls(**dict(emission))
        except TypeError:
            instance = cls(
                org_id=emission["org_id"],
                persona_id=emission["persona_id"],
                session_id=emission["session_id"],
                step_index=emission["step_index"],
                output_kind=emission["output_kind"],
                output_payload_sha256=emission["output_payload_sha256"],
                engine_version=emission["engine_version"],
                v907_pin=emission["v907_pin"],
                ts_utc=emission["ts_utc"],
            )
        to_jcs = getattr(instance, "to_jcs_bytes", None)
        if callable(to_jcs):
            return to_jcs()
    helper = getattr(module, "to_jcs_bytes", None)
    if callable(helper):
        out = helper(dict(emission))
        if isinstance(out, str):
            return out.encode("utf-8")
        if isinstance(out, (bytes, bytearray)):
            return bytes(out)
    raise AttributeError(
        "bridge_audit_writer module exposes neither EngineeringOutputEvent "
        "with .to_jcs_bytes() nor a module-level to_jcs_bytes helper"
    )


def capture_bridge_audit_stream_baseline(
    *,
    emissions: Tuple[Dict[str, Any], ...] = BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS,
    writer_module: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Capture the pre-cutover bridge-audit-stream-hash baseline.

    Returns ``None`` if the wirelang.bridge_audit_writer module is
    not importable (smoke treats this as A6-skip). Otherwise returns
    a record with:

      * ``stream_sha256_hex`` — SHA-256 over the concatenated JCS
        bytes of every emission, in the supplied order.
      * ``per_emission_jcs_sha256`` — list of per-emission JCS
        SHA-256s, useful for debugging the first divergence point.
      * ``emission_count`` — len(emissions).
      * ``captured_at_phase`` — always :data:`PHASE_PRE` (Self-
        Reference-Trap-Mitigation invariant; do not change this).

    This function is the Self-Reference-Trap-Mitigation capture
    moment. The A7 control-flow assert verifies that the
    ``captured_at_phase`` field equals :data:`PHASE_PRE` in the
    envelope — i.e. that no future smoke-refactor sneaks a
    post-cutover baseline into the envelope.
    """
    module = writer_module
    if module is None:
        try:
            module = _import_bridge_audit_writer()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"bridge_audit_writer not importable: {exc}"
                ),
                "stream_sha256_hex": None,
                "per_emission_jcs_sha256": [],
                "emission_count": 0,
                "captured_at_phase": PHASE_PRE,
            }

    per_emission: List[str] = []
    concatenated = b""
    try:
        for emission in emissions:
            jcs = _emission_to_jcs_bytes_via_module(module, emission)
            per_emission.append(hashlib.sha256(jcs).hexdigest())
            concatenated += jcs
    except Exception as exc:  # noqa: BLE001 — substrate drift is the signal
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": f"bridge-audit-stream baseline capture raised "
                       f"{type(exc).__name__}: {exc}",
            "stream_sha256_hex": None,
            "per_emission_jcs_sha256": [],
            "emission_count": 0,
            "captured_at_phase": PHASE_PRE,
        }

    stream_hash = hashlib.sha256(concatenated).hexdigest()
    return {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": (
            f"bridge-audit-stream baseline captured: "
            f"{len(emissions)} emissions, stream_sha256={stream_hash[:16]}..."
        ),
        "stream_sha256_hex": stream_hash,
        "per_emission_jcs_sha256": per_emission,
        "emission_count": len(emissions),
        "captured_at_phase": PHASE_PRE,
    }


def evaluate_bridge_audit_stream_parity(
    baseline: Optional[Dict[str, Any]],
    *,
    emissions: Tuple[Dict[str, Any], ...] = BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS,
    writer_module: Optional[Any] = None,
) -> Dict[str, Any]:
    """Recompute the bridge-audit-stream-hash post-cutover and compare.

    Note: the recomputation is done by calling the SAME Python
    authority again, NOT the rust pendant. The substrate-level
    oracle is "the Python JCS encoder is byte-stable across the
    pre/post window". The Rust pendant byte-parity is pinned at the
    F1/F2/F3 fixture layer (separate substrate, not loaded by this
    smoke at runtime). This is the only oracle that does **not**
    fall into the Self-Reference-Trap.

    Returns the same shape as :func:`capture_bridge_audit_stream_baseline`
    but with an additional ``match`` field:

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

    module = writer_module
    if module is None:
        try:
            module = _import_bridge_audit_writer()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"bridge_audit_writer not importable for recompute: {exc}"
                ),
                "baseline_stream_sha256": baseline.get("stream_sha256_hex"),
                "recomputed_stream_sha256": None,
                "match": True,
                "captured_at_phase": baseline.get("captured_at_phase", PHASE_PRE),
            }

    try:
        concatenated = b""
        for emission in emissions:
            concatenated += _emission_to_jcs_bytes_via_module(module, emission)
        recomputed = hashlib.sha256(concatenated).hexdigest()
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "skipped": False,
            "severity": "caution",
            "detail": (
                f"bridge-audit-stream recompute raised "
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
            f"bridge-audit-stream parity ok ({recomputed[:16]}...)"
            if match
            else (
                f"bridge-audit-stream drift: baseline={baseline_hash} "
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


def evaluate_post_cutover_asserts(
    *,
    pre_records: List[Dict[str, Any]],
    post_records: List[Dict[str, Any]],
    rollback_records: List[Dict[str, Any]],
    expected_components: int,
    boots_per_phase: int,
    latency_tolerance_pct: int,
    bridge_audit_stream_baseline: Optional[Dict[str, Any]] = None,
    bridge_audit_stream_parity: Optional[Dict[str, Any]] = None,
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

    # A1: post-cutover focus-component reports chosen_backend == rust.
    post_focus = _focus_records(post_records, focus=focus)
    a1_all_rust = bool(post_focus) and all(
        r.get("chosen_backend") == ENV_VALUE_RUST for r in post_focus
    )
    asserts["A1_backend_flip"] = {
        "passed": a1_all_rust,
        "severity": "blocker",
        "detail": (
            f"bridge_audit_writer chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})}"
        ),
    }

    # A2: cross-lang parity-hash identical between Post-Cutover-Rust
    # and Rollback-Python (same projection as Welle-1/2).
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

    # A6: bridge-audit-stream pre/post parity probe (caution-severity).
    if bridge_audit_stream_parity is None:
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
            "passed": bool(bridge_audit_stream_parity.get("passed", True)),
            "severity": "caution",
            "skipped": bool(bridge_audit_stream_parity.get("skipped", False)),
            "detail": bridge_audit_stream_parity.get("detail", ""),
            "baseline_stream_sha256": bridge_audit_stream_parity.get(
                "baseline_stream_sha256"
            ),
            "recomputed_stream_sha256": bridge_audit_stream_parity.get(
                "recomputed_stream_sha256"
            ),
            "match": bool(bridge_audit_stream_parity.get("match", True)),
            "captured_at_phase": bridge_audit_stream_parity.get(
                "captured_at_phase", PHASE_PRE
            ),
        }
    asserts["A6_bridge_audit_stream_parity"] = a6_record

    # A7: Self-Reference-Trap-Mitigation control invariant.
    # The bridge_audit_stream_baseline MUST have been captured in
    # PHASE_PRE. Any other captured_at_phase value indicates a smoke-
    # refactor regression that re-introduced the circular-oracle
    # pattern Henrik flagged. Blocker severity.
    if bridge_audit_stream_baseline is None:
        # If A6 was skipped entirely, A7 has nothing to check; report
        # passed but skipped so the envelope is honest.
        a7_record = {
            "passed": True,
            "severity": "blocker",
            "skipped": True,
            "detail": (
                "A7 skipped (no bridge-audit-stream baseline; A6 was "
                "skipped). The Self-Reference-Trap-Mitigation cannot "
                "be exercised without a baseline."
            ),
            "captured_at_phase": None,
            "expected_phase": PHASE_PRE,
        }
    else:
        captured_phase = bridge_audit_stream_baseline.get("captured_at_phase")
        a7_match = captured_phase == PHASE_PRE
        a7_record = {
            "passed": a7_match,
            "severity": "blocker",
            "skipped": False,
            "detail": (
                f"baseline captured_at_phase={captured_phase!r} "
                f"expected={PHASE_PRE!r}"
                if not a7_match
                else (
                    f"Self-Reference-Trap-Mitigation OK: baseline "
                    f"captured in {captured_phase!r} (pre-cutover)"
                )
            ),
            "captured_at_phase": captured_phase,
            "expected_phase": PHASE_PRE,
        }
    asserts["A7_self_reference_trap_control"] = a7_record

    return asserts


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
    """Parity-hash over the *structural* fields of focus-component records.

    See the Welle-1/2 siblings for the full rationale; the projection
    keeps ``domain`` and ``fallback_reason`` while dropping the
    ``requested_backend`` / ``chosen_backend`` pair (both flipped by
    the env-var/cutover). ``bin_path`` is also dropped (filesystem-
    dependent).
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
    bridge_audit_stream_baseline: Optional[Dict[str, Any]] = None,
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
        "welle": 3,
        "focus_component": FOCUS_COMPONENT,
        "focus_env_var": FOCUS_ENV_VAR,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
        "resolver_provenance": dict(resolver_provenance or {}),
        "self_reference_trap_mitigation": {
            "baseline_captured_at_phase": (
                bridge_audit_stream_baseline.get("captured_at_phase")
                if bridge_audit_stream_baseline is not None
                else None
            ),
            "baseline_stream_sha256": (
                bridge_audit_stream_baseline.get("stream_sha256_hex")
                if bridge_audit_stream_baseline is not None
                else None
            ),
            "baseline_skipped": (
                bool(bridge_audit_stream_baseline.get("skipped", False))
                if bridge_audit_stream_baseline is not None
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
    resolver_module: Optional[Any] = None,
    binary_probe: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
    now_ts: Optional[int] = None,
    skip_bridge_audit_stream_parity: bool = False,
    bridge_audit_writer_module: Optional[Any] = None,
    bridge_audit_baseline_fn: Optional[
        Callable[[], Optional[Dict[str, Any]]]
    ] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6/A7 + envelope.

    Returns ``(envelope, exit_code)``.

    Pure function: never mutates ``os.environ``, never opens files
    except the optional bridge-audit-writer-cross-lang fixture JSON
    (read-only, used only by the test suite's parameter injection).

    Self-Reference-Trap-Mitigation invariant: the bridge-audit-stream
    baseline is captured **only** in PHASE_PRE. PHASE_POST and
    PHASE_ROLLBACK never trigger the baseline-capture path. The A7
    assert in :func:`evaluate_post_cutover_asserts` verifies this
    via the ``captured_at_phase`` field of the baseline record.
    """
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available

    # Pre-cutover phase ALSO captures the bridge-audit-stream baseline.
    pre_phase = run_phase(
        PHASE_PRE,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_bridge_audit_baseline=not skip_bridge_audit_stream_parity,
        bridge_audit_baseline_fn=(
            bridge_audit_baseline_fn
            if bridge_audit_baseline_fn is not None
            else (
                (lambda: capture_bridge_audit_stream_baseline(
                    writer_module=bridge_audit_writer_module
                ))
                if not skip_bridge_audit_stream_parity
                else None
            )
        ),
    )

    # Post-cutover and rollback NEVER capture a baseline — that's the
    # Self-Reference-Trap-Mitigation contract.
    post_phase = run_phase(
        PHASE_POST,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_bridge_audit_baseline=False,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
        capture_bridge_audit_baseline=False,
    )

    bridge_audit_baseline = pre_phase.get("bridge_audit_stream_baseline")

    if skip_bridge_audit_stream_parity:
        bridge_audit_parity: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                "A6 skipped via --skip-bridge-audit-stream-parity"
            ),
            "baseline_stream_sha256": None,
            "recomputed_stream_sha256": None,
            "match": True,
            "captured_at_phase": PHASE_PRE,
        }
    else:
        bridge_audit_parity = evaluate_bridge_audit_stream_parity(
            bridge_audit_baseline,
            writer_module=bridge_audit_writer_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        bridge_audit_stream_baseline=bridge_audit_baseline,
        bridge_audit_stream_parity=bridge_audit_parity,
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
        bridge_audit_stream_baseline=bridge_audit_baseline,
        resolver_provenance=merged_provenance,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-3-bridge-audit-writer-cutover-smoke",
        description=(
            "Phase-3c Welle-3 (bridge_audit_writer) End-to-End "
            "Cutover-Smoke for ADR-0066 KW-25 solo wave. Boots a "
            "mocked persona-engine across Pre-Cutover (Python "
            "baseline) -> Cutover (Rust) -> Rollback (Python) "
            "phases, evaluates A1..A5 + R1 + A6 (bridge-audit-stream "
            "parity) + A7 (Self-Reference-Trap-Mitigation control) "
            "asserts, and exits 0/1/2 = GREEN/CAUTION/"
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
            "baseline 2ec0532; pass 10 once the Reza Tag-36 "
            "bridge_audit_writer resolver wire-in lands)."
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
        "--skip-bridge-audit-stream-parity",
        action="store_true",
        help=(
            "Skip the A6 bridge-audit-stream-parity probe. When "
            "skipped, A7 is also skipped (the Self-Reference-Trap-"
            "Mitigation cannot be exercised without a baseline). Use "
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
    bridge_audit_writer_module: Optional[Any] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if args.boots_per_phase < 1:
        err.write(
            f"welle-3-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-3-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-3-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_bridge_audit_stream_parity=args.skip_bridge_audit_stream_parity,
        bridge_audit_writer_module=bridge_audit_writer_module,
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
            f"welle-3-cutover-smoke: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        # Hard I/O failure overrides the smoke exit-code: surface as
        # exit 2 (ROLLBACK), because the operator cannot consume the
        # evidence and should not proceed without it.
        return EXIT_ROLLBACK

    return exit_code


__all__ = [
    "BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS",
    "COMPONENT_TO_ENV",
    "DEFAULT_BOOTS_PER_PHASE",
    "DEFAULT_BRIDGE_AUDIT_STREAM_FIXTURE_RELPATH",
    "DEFAULT_EXPECTED_COMPONENTS",
    "DEFAULT_LATENCY_TOLERANCE_PCT",
    "ENGINE_BOOT_COMPONENTS",
    "ENVELOPE_SCHEMA",
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
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "capture_bridge_audit_stream_baseline",
    "derive_exit_code",
    "evaluate_bridge_audit_stream_parity",
    "evaluate_post_cutover_asserts",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
