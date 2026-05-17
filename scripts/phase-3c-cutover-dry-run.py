#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""phase-3c-cutover-dry-run — local Cutover simulator for ADR-0065 Welle-1.

Background
----------

ADR-0065 (approved 2026-05-17) formalises Phase-3c — the staged
per-component flip of the persona-engine default backend from
``python`` to ``rust`` (Option B, one component per week,
Welle-1 starts with ``v907_verify``).

Before the operator flips the production default for a given
component, ADR-0065 §Verifikations-Plan demands a Monday-morning
``Pilot-VM-Acceptance-Lane-Run`` (Live-Smoke) gated by Bridge-Audit-
Writer consistency. That live run is **Operator-Hand-territory**;
this script is the **local dry-run substrate** that lets Selin,
Reza, and Tomás rehearse the cutover *without* touching the
Pilot-VM, NATS, the Anthropic API, or any production side-effect.

What the dry-run does
---------------------

For a single Phase-3c component (default ``v907_verify``):

1. Sets ``WAKIR_<COMPONENT>_BACKEND=rust`` in a hermetic env-map
   (the script never mutates ``os.environ``; the engine sees a
   private mapping).
2. Spawns a mocked persona-boot sequence — ``N`` simulated boots
   (default 12, configurable via ``--boots``), each one calling the
   real :mod:`wirelang.persona_engine.rust_backend_switch` resolver
   for the requested component, with a stub binary-probe so the
   Rust subprocess is **never invoked**.
3. Collects every :class:`BackendDecision` record into an in-memory
   list (no JSONL written, no NATS published).
4. Computes a feasibility envelope: per-backend counts, latency
   percentiles (avg/p50/p95/p99 microseconds), fallback rate, and
   a single ``cutover_feasibility_score`` in ``[0.0, 1.0]``.
5. Writes the envelope as a JSON object to stdout (or to
   ``--output``).

When the dry-run is told to consult the real binary (``--probe-real``),
the binary-probe is :func:`wirelang.persona_engine.rust_backend_switch._binary_available`
and the envelope's ``dry_run`` field is ``"blocked"`` with an explicit
``error`` message when the Rust binary is missing or not executable.

This is the substrate that ADR-0065 §Verifikations-Plan Mo-Tag
``Cutover-Welle-PR`` review consumes — operators can run the
dry-run from any sandbox (host or claude-dev toolbox), inspect the
JSON, and only proceed to the live Pilot-VM smoke when feasibility
is GREEN.

Cutover feasibility score
-------------------------

The score is a single deterministic number in ``[0.0, 1.0]`` that
collapses three sub-signals:

  * **Backend purity** (weight 0.5) — fraction of boots whose
    ``chosen_backend`` matches the requested Rust variant. Anything
    less than 1.0 means at least one boot fell back to Python; the
    score declines linearly.
  * **Latency budget** (weight 0.3) — 1.0 if the p95 resolution
    latency is below the per-component budget threshold (default
    50_000 microseconds = 50 ms; configurable). Above the threshold
    the score drops linearly to 0.0 at 4× the threshold.
  * **Fallback rate** (weight 0.2) — ``1.0 - fallback_rate``. A
    fallback record is one whose ``fallback_reason`` is a non-null
    string (binary missing, not executable, explicit-python).

Score values:

  * ``>= 0.95`` — **GREEN**, ready for ADR-0065 §Mo Live-Smoke.
  * ``>= 0.80`` — **AMBER**, investigate latency tail / occasional
    fallback before proceeding.
  * ``< 0.80`` — **RED**, do not proceed; raise to Tomás Matrix-Lead.

The score is operator-facing copy, not a hard CI gate. The real
ADR-0065 acceptance criteria (AC-1..AC-5) are still measured
against live Pilot-VM evidence, not this dry-run.

Hermeticity
-----------

The script is stdlib-only, never imports NATS clients or the
Anthropic SDK, and the default binary-probe is a stub that returns
"available" without consulting the filesystem. ``--probe-real`` is
opt-in for operators who want the dry-run to also check that the
binary is actually deployed at ``WAKIR_RUST_<COMPONENT>_BIN``.

Exit codes
----------

* ``0`` — dry-run completed and produced a JSON envelope (regardless
  of feasibility colour — operator reads the JSON to decide).
* ``2`` — unknown component (CLI argument validation).
* ``3`` — output path is not writable.

License: Apache-2.0 (parity with sibling cutover/observability scripts).
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Component catalogue — mirrors ADR-0065 §Option-B-Reihenfolge and the
# seven production-default switches in
# wirelang/persona_engine/rust_backend_switch.py.
# ---------------------------------------------------------------------------

#: The seven Phase-3c components in cutover order. ADR-0065 §Option-B
#: enumerates the seven candidates with operator-facing long-form
#: names; the in-repo rust_backend_switch resolvers use the short
#: ``domain`` strings (``recovery``, ``fsm``, ``anchor_emitter``,
#: ``bridge_diff``). The dry-run script accepts both spellings via
#: :func:`validate_component` so that the Welle-1..7 cutover-PRs can
#: invoke it with ADR-0065 vocabulary, while the resolver bridge maps
#: to the short ``domain`` form internally.
#:
#: Naming-drift note (2026-05-17, Selin, updated Tag-25):
#: ADR-0065 §Option-B mentions ``svid_workload_identity`` and
#: ``bridge_audit_writer`` as components #2 and #3 of the cutover
#: order. The in-repo backend-switch substrate (PRs #131..#172) did
#: not initially expose dedicated resolver functions under those names
#: — the closest in-repo analogues remain ``bridge_diff`` (Tag-20
#: PR #175) and ``anchor_emitter`` (Tag-23 PR #170/#175, which writes
#: the WAT-anchor envelope and is the "writer" half of the bridge-
#: audit substrate). The Tag-25 Mini-Welle (ADR-0065 Welle-2 pre-
#: condition) added the ``svid_workload_identity`` resolver to the
#: switch substrate; the dry-run now lists it as the eighth component
#: at the ADR-0065-mandated Welle-2 position so the cutover-aggregator
#: no longer flags it as ``no-resolver``. Welle-2 production-default
#: flip remains gated on the Rust ``persona-engine-svid-workload-
#: identity`` crate shipping a callable binary; until then the
#: ``--probe-real`` mode reports the binary as missing and the
#: aggregator status reads ``ready-pending-binary``.
PHASE_3C_COMPONENTS: Tuple[str, ...] = (
    "v907_verify",
    "svid_workload_identity",
    "bridge_diff",
    "anchor_emitter",
    "state_backing",
    "fsm",
    "subscribe_loop",
    "recovery",
)

#: Operator-facing ADR-0065 long-form aliases. :func:`validate_component`
#: accepts either spelling and normalises to the in-repo short form.
PHASE_3C_COMPONENT_ALIASES: Dict[str, str] = {
    "lifecycle_state_machine": "fsm",
    "recovery_workflow": "recovery",
    "bridge_audit_writer": "anchor_emitter",
    # ADR-0065 §Option-B mentions svid_workload_identity directly; the
    # in-repo short form matches one-to-one with the Tag-25 resolver,
    # so no alias mapping is needed (the canonical form is itself).
}

#: Map each Phase-3c component name to the in-repo ``BackendDecision.domain``
#: value used by the rust_backend_switch resolvers. Both keys and values
#: are in the in-repo short form; ADR-0065 long-form names get aliased
#: in :func:`validate_component` before this map is consulted.
COMPONENT_TO_DOMAIN: Dict[str, str] = {
    "v907_verify": "v907_verify",
    "svid_workload_identity": "svid_workload_identity",
    "bridge_diff": "bridge_diff",
    "anchor_emitter": "anchor_emitter",
    "state_backing": "state_backing",
    "fsm": "fsm",
    "subscribe_loop": "subscribe_loop",
    "recovery": "recovery",
}

#: Map each Phase-3c component to the requested-backend value the
#: env-var must carry to opt into Rust. Most are simply ``"rust"``;
#: ``state_backing`` accepts ``rust_inmemory`` or ``rust_natskv`` —
#: the dry-run defaults to ``rust_inmemory`` since the script must
#: never talk to NATS.
COMPONENT_TO_RUST_VALUE: Dict[str, str] = {
    "v907_verify": "rust",
    "svid_workload_identity": "rust",
    "bridge_diff": "rust",
    "anchor_emitter": "rust",
    "state_backing": "rust_inmemory",
    "fsm": "rust",
    "subscribe_loop": "rust",
    "recovery": "rust",
}

#: Map each Phase-3c component to the env-var the operator flips.
#: Mirrors the constants in rust_backend_switch.py (kept locally so
#: this script stays import-light — only the resolver is imported
#: lazily when actually running a dry-run).
COMPONENT_TO_ENV: Dict[str, str] = {
    "v907_verify": "WAKIR_V907_VERIFY_BACKEND",
    "svid_workload_identity": "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    "bridge_diff": "WAKIR_BRIDGE_DIFF_BACKEND",
    "anchor_emitter": "WAKIR_ANCHOR_EMITTER_BACKEND",
    "state_backing": "WAKIR_STATE_BACKING_BACKEND",
    "fsm": "WAKIR_FSM_BACKEND",
    "subscribe_loop": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
    "recovery": "WAKIR_RECOVERY_BACKEND",
}

#: Default number of mocked boots per dry-run. Twelve is the Phase-3b
#: per-component live-smoke boot-count baseline (see ADR-0065 §Verif.-
#: Plan Mo); the dry-run mirrors that cadence so latency percentiles
#: have a non-trivial sample.
DEFAULT_BOOTS = 12

#: Default per-component p95-latency budget for the dry-run, in
#: microseconds. The number is generous (50 ms) — the resolver does
#: no real work (the binary-probe is stubbed), so production latencies
#: will be far lower. The dry-run scoring uses this budget as a sanity
#: ceiling, not a tight bound.
DEFAULT_P95_LATENCY_BUDGET_US = 50_000

#: Feasibility-score band thresholds — operator-facing copy.
SCORE_BAND_GREEN = 0.95
SCORE_BAND_AMBER = 0.80


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnknownComponentError(ValueError):
    """Raised when ``--component`` is not in :data:`PHASE_3C_COMPONENTS`."""


class DryRunBlockedError(RuntimeError):
    """Raised internally when --probe-real finds the binary missing.

    The script catches it and renders ``dry_run=blocked`` into the
    JSON envelope rather than letting the error propagate.
    """


# ---------------------------------------------------------------------------
# Resolver-import seam.
# ---------------------------------------------------------------------------


def _import_resolver() -> Any:
    """Lazy import of :mod:`wirelang.persona_engine.rust_backend_switch`.

    Kept lazy so that test environments without the wirelang package
    can still import this module for unit-testing the pure functions
    (component normalisation, scoring, JSON envelope shape) below.

    Returns the imported module object. Test code injects a stub via
    the :func:`run_dry_run` ``resolver_module`` keyword argument.
    """
    return importlib.import_module(
        "wirelang.persona_engine.rust_backend_switch"
    )


# ---------------------------------------------------------------------------
# Stub binary-probe — never touches the filesystem.
# ---------------------------------------------------------------------------


def _stub_probe_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
    """Pretend the Rust binary is present and executable.

    The dry-run uses this by default — the substance-question is
    "what does the resolver decide given the env-var", not "is the
    binary actually on disk". Operators who want the latter check
    pass ``--probe-real``.
    """
    return True, None


def _stub_probe_missing(_bin_path: str) -> Tuple[bool, Optional[str]]:
    """Pretend the Rust binary is absent.

    Used by tests that need to exercise the fallback-path branch of
    the resolver. Not wired to the CLI.
    """
    return False, "binary_missing"


# ---------------------------------------------------------------------------
# Component validation + env-map construction.
# ---------------------------------------------------------------------------


def validate_component(name: str) -> str:
    """Return the in-repo short name; raise on unknown / mismapped.

    Acceptance:
      * In-repo short forms (``v907_verify``, ``fsm``, ``recovery``,
        ``anchor_emitter``, ``bridge_diff``, ``subscribe_loop``,
        ``state_backing``) pass through unchanged.
      * ADR-0065 long-form aliases (``lifecycle_state_machine``,
        ``recovery_workflow``, ``bridge_audit_writer``) get mapped
        to their short forms via :data:`PHASE_3C_COMPONENT_ALIASES`.
      * Empty / whitespace / ``None`` raise with the full enumeration.
      * ``svid_workload_identity`` (ADR-0065 §Option-B but no in-repo
        resolver) raises with an explicit "not yet implemented" hint.
    """
    if name is None:
        raise UnknownComponentError(
            "component name is None; expected one of "
            f"{sorted(PHASE_3C_COMPONENTS)} (or aliases "
            f"{sorted(PHASE_3C_COMPONENT_ALIASES)})"
        )
    normalised = name.strip().lower()
    if not normalised:
        raise UnknownComponentError(
            "component name is empty; expected one of "
            f"{sorted(PHASE_3C_COMPONENTS)} (or aliases "
            f"{sorted(PHASE_3C_COMPONENT_ALIASES)})"
        )
    if normalised in PHASE_3C_COMPONENT_ALIASES:
        normalised = PHASE_3C_COMPONENT_ALIASES[normalised]
    if normalised not in PHASE_3C_COMPONENTS:
        raise UnknownComponentError(
            f"unknown component {name!r}; expected one of "
            f"{sorted(PHASE_3C_COMPONENTS)} (or aliases "
            f"{sorted(PHASE_3C_COMPONENT_ALIASES)})"
        )
    return normalised


def build_cutover_env(
    component: str,
    *,
    base_env: Optional[Mapping[str, str]] = None,
    state_backing_variant: str = "rust_inmemory",
) -> Dict[str, str]:
    """Return a hermetic env-map that flips the requested component to Rust.

    The returned dict is a *copy* of ``base_env`` (defaulting to an
    empty dict when not provided — the dry-run does NOT inherit the
    operator's environment, which could contain unrelated Phase-3b
    flags that would skew the boot decisions). The component's
    env-var is set to the appropriate Rust value; all other Phase-3c
    components' env-vars are explicitly set to ``"python"`` so the
    boot path is deterministic.

    Parameters
    ----------
    component
        Already-validated component name.
    base_env
        Optional starting env-map (typically empty; operators who
        want to layer custom values pass a dict here).
    state_backing_variant
        Override for the ``state_backing`` component's rust variant.
        Default ``rust_inmemory`` (hermetic). ``rust_natskv``
        documents the production posture but the dry-run still does
        not invoke NATS — the resolver only decides which value to
        emit on the decision record.
    """
    env: Dict[str, str] = dict(base_env or {})
    for comp, env_var in COMPONENT_TO_ENV.items():
        env[env_var] = "python"
    target_env_var = COMPONENT_TO_ENV[component]
    if component == "state_backing":
        if state_backing_variant not in ("rust_inmemory", "rust_natskv"):
            raise ValueError(
                f"state_backing_variant must be 'rust_inmemory' or "
                f"'rust_natskv'; got {state_backing_variant!r}"
            )
        env[target_env_var] = state_backing_variant
    else:
        env[target_env_var] = COMPONENT_TO_RUST_VALUE[component]
    return env


# ---------------------------------------------------------------------------
# Mocked boot-sequence runner.
# ---------------------------------------------------------------------------


def _resolve_for_component(
    component: str,
    *,
    env: Mapping[str, str],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
) -> Any:
    """Call the right resolver function for the given component.

    Returns the resolver's ``BackendDecision`` object (the second
    element of the resolver's ``(backend, decision)`` tuple).

    The resolver-module accessor pattern lets test code inject a
    stub module without the full ``wirelang`` import-chain.
    """
    # The resolver functions in rust_backend_switch.py live under
    # consistent names — resolve_<domain>_backend. Map via the same
    # COMPONENT_TO_DOMAIN bridge used for env-var construction.
    domain = COMPONENT_TO_DOMAIN[component]
    fn_name = f"resolve_{domain}_backend"
    resolver_fn = getattr(resolver_module, fn_name, None)
    if resolver_fn is None:
        raise AttributeError(
            f"resolver module is missing function {fn_name!r} "
            f"(component={component!r})"
        )
    _backend, decision = resolver_fn(
        env=env,
        log_sink=None,
        binary_probe=binary_probe,
    )
    return decision


def run_boot_sequence(
    component: str,
    *,
    boots: int,
    env: Mapping[str, str],
    resolver_module: Optional[Any] = None,
    binary_probe: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
) -> List[Dict[str, Any]]:
    """Run ``boots`` mocked persona-boots and return the decision records.

    Each iteration calls the real resolver for ``component`` with the
    hermetic env-map. The records are returned in chronological order
    so the aggregator can apply a sliding-window-style aggregation if
    needed (the current dry-run scoring uses the full set).

    Parameters
    ----------
    component
        Already-validated component name.
    boots
        Number of mocked boots; must be >= 1.
    env
        Hermetic env-map from :func:`build_cutover_env`.
    resolver_module
        Test seam; default :func:`_import_resolver` result.
    binary_probe
        Test seam; default :func:`_stub_probe_available`.
    """
    if boots < 1:
        raise ValueError(f"boots must be >= 1; got {boots!r}")
    module = resolver_module if resolver_module is not None else _import_resolver()
    probe = binary_probe if binary_probe is not None else _stub_probe_available
    records: List[Dict[str, Any]] = []
    for _ in range(boots):
        decision = _resolve_for_component(
            component,
            env=env,
            resolver_module=module,
            binary_probe=probe,
        )
        # Decision objects from rust_backend_switch are frozen
        # dataclasses; asdict normalises to a plain dict so the
        # rest of the dry-run is dict-only.
        records.append(asdict(decision))
    return records


# ---------------------------------------------------------------------------
# Latency-percentile + feasibility scoring.
# ---------------------------------------------------------------------------


def _nearest_rank_percentile(values: List[int], percentile: float) -> int:
    """Nearest-rank percentile of an integer sample.

    Mirrors the same semantics used by ``backend-decision-observability``
    so the dry-run envelope and the production aggregator agree.
    Returns 0 when the sample is empty.
    """
    if not values:
        return 0
    if percentile <= 0:
        return int(min(values))
    if percentile >= 100:
        return int(max(values))
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return int(ordered[rank - 1])


def latency_envelope(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Return ``{avg, p50, p95, p99, count}`` over ``resolution_latency_us``.

    Records with missing / non-int latency are dropped from the
    percentile calculation; ``count`` reflects the surviving sample.
    """
    latencies: List[int] = []
    for rec in records:
        raw = rec.get("resolution_latency_us")
        if isinstance(raw, bool):
            # bool is a subclass of int in Python; explicit guard.
            continue
        if isinstance(raw, int):
            latencies.append(raw)
    count = len(latencies)
    if count == 0:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "count": 0}
    avg = int(round(sum(latencies) / count))
    return {
        "avg": avg,
        "p50": _nearest_rank_percentile(latencies, 50.0),
        "p95": _nearest_rank_percentile(latencies, 95.0),
        "p99": _nearest_rank_percentile(latencies, 99.0),
        "count": count,
    }


def _backend_purity(
    records: List[Dict[str, Any]], *, requested: str
) -> float:
    """Fraction of boots whose ``chosen_backend`` matched ``requested``."""
    if not records:
        return 0.0
    matches = sum(
        1 for r in records if r.get("chosen_backend") == requested
    )
    return matches / len(records)


def _latency_score(p95_us: int, *, budget_us: int) -> float:
    """Linear score: 1.0 at ``p95 <= budget``; 0.0 at ``p95 >= 4*budget``."""
    if budget_us <= 0:
        return 1.0
    if p95_us <= budget_us:
        return 1.0
    ceiling = 4 * budget_us
    if p95_us >= ceiling:
        return 0.0
    # Linear interpolation between budget and 4*budget.
    span = ceiling - budget_us
    return max(0.0, 1.0 - (p95_us - budget_us) / span)


def _fallback_rate(records: List[Dict[str, Any]]) -> float:
    """Fraction of records whose ``fallback_reason`` is non-null."""
    if not records:
        return 0.0
    fallbacks = sum(
        1
        for r in records
        if r.get("fallback_reason") is not None
        and r.get("fallback_reason") != ""
    )
    return fallbacks / len(records)


def compute_feasibility_score(
    records: List[Dict[str, Any]],
    *,
    requested_backend: str,
    p95_latency_budget_us: int,
) -> Dict[str, Any]:
    """Return the feasibility envelope: score, band, and sub-components.

    Score:
        0.5 * backend_purity + 0.3 * latency_score + 0.2 * (1 - fallback_rate)

    All sub-components are clamped to [0.0, 1.0]; the final score is
    a deterministic function of the records and the budget.
    """
    purity = _backend_purity(records, requested=requested_backend)
    fallback = _fallback_rate(records)
    latency_envelope_dict = latency_envelope(records)
    p95 = latency_envelope_dict["p95"]
    latency = _latency_score(p95, budget_us=p95_latency_budget_us)
    fallback_score = 1.0 - fallback

    score = 0.5 * purity + 0.3 * latency + 0.2 * fallback_score
    # Clamp defensively — floating-point arithmetic on perfect inputs
    # can produce 1.0000000002.
    score = max(0.0, min(1.0, score))

    if score >= SCORE_BAND_GREEN:
        band = "GREEN"
    elif score >= SCORE_BAND_AMBER:
        band = "AMBER"
    else:
        band = "RED"

    return {
        "cutover_feasibility_score": round(score, 4),
        "band": band,
        "subscores": {
            "backend_purity": round(purity, 4),
            "latency_score": round(latency, 4),
            "fallback_score": round(fallback_score, 4),
        },
        "weights": {
            "backend_purity": 0.5,
            "latency_score": 0.3,
            "fallback_score": 0.2,
        },
        "p95_latency_budget_us": p95_latency_budget_us,
    }


# ---------------------------------------------------------------------------
# Envelope construction.
# ---------------------------------------------------------------------------


def build_envelope(
    *,
    component: str,
    boots: int,
    requested_backend: str,
    env_var: str,
    records: List[Dict[str, Any]],
    p95_latency_budget_us: int,
    probe_mode: str,
    dry_run_state: str = "completed",
    error: Optional[str] = None,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the full JSON-output envelope.

    The envelope is operator-facing and stable per this module's
    ``__all__`` contract; the Welle-1 cutover PR (Reza) will read
    fields directly to populate the Mo-status-report.

    Fields
    ------
    schema
        Constant ``"wakir.phase-3c.dry-run/1"`` — versioned for future
        evolution.
    timestamp_utc
        POSIX-epoch seconds (integer) at which the envelope was
        rendered. Hermetic tests pass ``now_ts`` explicitly.
    component
        Validated Phase-3c component name.
    env_var
        Env-var the operator must flip on Pilot-VM.
    requested_backend
        Value the env-var carries during the dry-run.
    boots
        Number of mocked boots executed.
    probe_mode
        ``"stub"`` or ``"real"`` — which binary-probe ran.
    dry_run
        ``"completed"`` or ``"blocked"``.
    decisions
        Full list of decision records, in chronological order.
    latency
        Result of :func:`latency_envelope`.
    feasibility
        Result of :func:`compute_feasibility_score` (omitted when
        ``dry_run == "blocked"``).
    chosen_backend_counts
        ``{chosen_backend -> int}`` aggregate of the decisions.
    fallback_reason_counts
        ``{reason -> int}`` aggregate (``None``/missing → ``"null"``).
    error
        Present and non-empty only when ``dry_run == "blocked"``.
    """
    timestamp = int(now_ts if now_ts is not None else time.time())

    chosen_counts: Dict[str, int] = {}
    fallback_counts: Dict[str, int] = {}
    for rec in records:
        chosen = rec.get("chosen_backend") or "unknown"
        chosen_counts[chosen] = chosen_counts.get(chosen, 0) + 1
        reason = rec.get("fallback_reason")
        key = "null" if reason is None or reason == "" else str(reason)
        fallback_counts[key] = fallback_counts.get(key, 0) + 1

    envelope: Dict[str, Any] = {
        "schema": "wakir.phase-3c.dry-run/1",
        "timestamp_utc": timestamp,
        "component": component,
        "env_var": env_var,
        "requested_backend": requested_backend,
        "boots": boots,
        "probe_mode": probe_mode,
        "dry_run": dry_run_state,
        "decisions": records,
        "latency": latency_envelope(records),
        "chosen_backend_counts": chosen_counts,
        "fallback_reason_counts": fallback_counts,
    }

    if dry_run_state == "completed":
        envelope["feasibility"] = compute_feasibility_score(
            records,
            requested_backend=requested_backend,
            p95_latency_budget_us=p95_latency_budget_us,
        )
    else:
        # Blocked envelopes still surface the budget so operators
        # know what was being targeted.
        envelope["feasibility"] = {
            "cutover_feasibility_score": 0.0,
            "band": "BLOCKED",
            "p95_latency_budget_us": p95_latency_budget_us,
        }
        envelope["error"] = error or "binary_missing"

    return envelope


# ---------------------------------------------------------------------------
# Top-level dry-run orchestrator.
# ---------------------------------------------------------------------------


def run_dry_run(
    *,
    component: str,
    boots: int = DEFAULT_BOOTS,
    p95_latency_budget_us: int = DEFAULT_P95_LATENCY_BUDGET_US,
    probe_real: bool = False,
    base_env: Optional[Mapping[str, str]] = None,
    state_backing_variant: str = "rust_inmemory",
    resolver_module: Optional[Any] = None,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Single-component dry-run end-to-end. Returns the JSON envelope.

    On a probe-real path where the binary turns out to be missing,
    the function returns an envelope with ``dry_run="blocked"`` and
    ``error="binary_missing"`` — it does NOT raise.

    Parameters mirror :func:`build_cutover_env` and
    :func:`run_boot_sequence`.
    """
    component = validate_component(component)
    env = build_cutover_env(
        component,
        base_env=base_env,
        state_backing_variant=state_backing_variant,
    )
    env_var = COMPONENT_TO_ENV[component]
    requested = env[env_var]

    module = resolver_module if resolver_module is not None else _import_resolver()

    if probe_real:
        # Consult the real resolver's binary-availability check before
        # spending boot-iterations. This is the seam that produces
        # dry_run=blocked when the binary is missing.
        bin_path_fn = getattr(module, f"_resolve_{COMPONENT_TO_DOMAIN[component]}_bin", None)
        probe_fn = getattr(module, "_binary_available", None)
        if bin_path_fn is None or probe_fn is None:
            return build_envelope(
                component=component,
                boots=boots,
                requested_backend=requested,
                env_var=env_var,
                records=[],
                p95_latency_budget_us=p95_latency_budget_us,
                probe_mode="real",
                dry_run_state="blocked",
                error=(
                    "resolver module missing binary-probe seam "
                    "(_binary_available or _resolve_<domain>_bin)"
                ),
                now_ts=now_ts,
            )
        bin_path = bin_path_fn(env)
        available, reason = probe_fn(bin_path)
        if not available:
            return build_envelope(
                component=component,
                boots=boots,
                requested_backend=requested,
                env_var=env_var,
                records=[],
                p95_latency_budget_us=p95_latency_budget_us,
                probe_mode="real",
                dry_run_state="blocked",
                error=(
                    f"rust binary unavailable at {bin_path!r}: "
                    f"{reason or 'unknown_reason'}"
                ),
                now_ts=now_ts,
            )
        probe: Callable[[str], Tuple[bool, Optional[str]]] = probe_fn
        probe_mode = "real"
    else:
        probe = _stub_probe_available
        probe_mode = "stub"

    records = run_boot_sequence(
        component,
        boots=boots,
        env=env,
        resolver_module=module,
        binary_probe=probe,
    )

    return build_envelope(
        component=component,
        boots=boots,
        requested_backend=requested,
        env_var=env_var,
        records=records,
        p95_latency_budget_us=p95_latency_budget_us,
        probe_mode=probe_mode,
        dry_run_state="completed",
        now_ts=now_ts,
    )


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-3c-cutover-dry-run",
        description=(
            "Phase-3c per-component Cutover dry-run (ADR-0065, Welle-1 "
            "v907_verify). Simulates a mocked persona-boot sequence "
            "with WAKIR_<COMPONENT>_BACKEND=rust set, collects "
            "BackendDecision records, and reports a feasibility "
            "envelope as JSON. Never invokes the real Rust binary, "
            "NATS, or the Anthropic API. License: Apache-2.0."
        ),
    )
    p.add_argument(
        "--component",
        type=str,
        default="v907_verify",
        help=(
            "Phase-3c component to dry-run. Default: v907_verify "
            "(Welle-1). One of: "
            f"{', '.join(sorted(PHASE_3C_COMPONENTS))}."
        ),
    )
    p.add_argument(
        "--boots",
        type=int,
        default=DEFAULT_BOOTS,
        help=(
            f"Number of mocked boots (default {DEFAULT_BOOTS}). "
            "Mirrors the Phase-3b live-smoke boot-count baseline."
        ),
    )
    p.add_argument(
        "--p95-latency-budget-us",
        type=int,
        default=DEFAULT_P95_LATENCY_BUDGET_US,
        help=(
            "P95-latency budget in microseconds for the latency "
            f"sub-score. Default {DEFAULT_P95_LATENCY_BUDGET_US} "
            "(= 50 ms, sanity ceiling, not tight bound)."
        ),
    )
    p.add_argument(
        "--probe-real",
        action="store_true",
        help=(
            "Consult the real binary-probe instead of the stub. When "
            "the Rust binary is missing or not executable, the envelope "
            "is rendered with dry_run=blocked and an error message."
        ),
    )
    p.add_argument(
        "--state-backing-variant",
        type=str,
        choices=("rust_inmemory", "rust_natskv"),
        default="rust_inmemory",
        help=(
            "Which rust variant to test for the state_backing "
            "component (ignored for other components). Default "
            "rust_inmemory (hermetic; rust_natskv documents the "
            "production posture but still never talks to NATS in "
            "dry-run mode)."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output file path. Default: write JSON envelope "
            "to stdout."
        ),
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help=(
            "Override the timestamp_utc field for hermetic tests. "
            "Production runs leave this unset and use time.time()."
        ),
    )
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    stdout: Optional[io.TextIOBase] = None,
    stderr: Optional[io.TextIOBase] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    try:
        component = validate_component(args.component)
    except UnknownComponentError as exc:
        err.write(f"phase-3c-cutover-dry-run: {exc}\n")
        return 2

    if args.boots < 1:
        err.write(
            f"phase-3c-cutover-dry-run: --boots must be >= 1; "
            f"got {args.boots!r}\n"
        )
        return 2

    envelope = run_dry_run(
        component=component,
        boots=args.boots,
        p95_latency_budget_us=args.p95_latency_budget_us,
        probe_real=args.probe_real,
        state_backing_variant=args.state_backing_variant,
        now_ts=args.now,
    )

    rendered = json.dumps(envelope, sort_keys=True, indent=2) + "\n"

    if args.output is None:
        out.write(rendered)
        return 0

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        err.write(
            f"phase-3c-cutover-dry-run: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        return 3
    return 0


__all__ = [
    "COMPONENT_TO_DOMAIN",
    "COMPONENT_TO_ENV",
    "COMPONENT_TO_RUST_VALUE",
    "DEFAULT_BOOTS",
    "DEFAULT_P95_LATENCY_BUDGET_US",
    "DryRunBlockedError",
    "PHASE_3C_COMPONENTS",
    "PHASE_3C_COMPONENT_ALIASES",
    "SCORE_BAND_AMBER",
    "SCORE_BAND_GREEN",
    "UnknownComponentError",
    "build_argparser",
    "build_cutover_env",
    "build_envelope",
    "compute_feasibility_score",
    "latency_envelope",
    "main",
    "run_boot_sequence",
    "run_dry_run",
    "validate_component",
]


if __name__ == "__main__":
    sys.exit(main())
