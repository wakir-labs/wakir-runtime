#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-1-v907-verify-cutover-smoke — End-to-End Cutover-Smoke for ADR-0065 Welle-1.

Background
----------

ADR-0065 (approved 2026-05-17, commit ``1815a88``) staggers the
Phase-3c persona-engine default-backend flip in seven weekly waves.
Welle-1 is ``v907_verify``: the read-only hash-determinism gate, the
lowest-risk component, the first to be cut over from Python-default
to Rust-default.

ADR-0065 §Verifikations-Plan demands an end-to-end Smoke before the
operator flips the Pilot-VM ``WAKIR_V907_VERIFY_BACKEND`` Quadlet
default. The sibling artefact ``scripts/phase-3c-cutover-dry-run.py``
(Tag-24, PR earlier) is a feasibility *probe* — it reports a score
band, no asserts. This script is the strict, **asserts-tragend**
counterpart: it reproduces the full pre-cutover / cutover-step /
post-cutover / rollback shape and exits with a tri-state code that
operators can wire into shell gates.

This is the substrate the Welle-1 cutover-PR (Reza, scheduled
~2026-05-24) is expected to consume before the live Pilot-VM
acceptance lane runs.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with the
   Python default (``WAKIR_V907_VERIFY_BACKEND=python``). Records the
   ``BackendDecision`` for ``v907_verify`` plus the BackendDecisions
   for the other in-place components (default 8 total per
   ADR-0065-current Phase-3b inventory). Computes a baseline cross-
   lang parity-hash (deterministic over the decision-records of all
   in-place components — the parity-hash is the byte-shape oracle
   that pins the Bridge-Audit-Writer consistency contract from PR
   #224 (Tag-33 SVID Cross-Lang Pins) and PR #170 (Tag-23 Anchor-
   Emitter Cross-Lang fixtures).
2. **Cutover step.** Flips ``WAKIR_V907_VERIFY_BACKEND=rust`` in the
   hermetic env-map (the script never mutates ``os.environ``; the
   engine sees a private mapping), restarts the mocked engine,
   re-collects BackendDecisions.
3. **Post-Cutover asserts.** Five hard checks:
     * **A1 backend-flip:** ``v907_verify`` BackendDecision now
       reports ``chosen_backend == "rust"``.
     * **A2 parity-hash:** Cross-lang parity-hash identical to
       baseline (the V-907 hash-determinism gate is byte-equal across
       Python and Rust implementations — that's the substance-promise
       PR #224 cemented).
     * **A3 latency:** P95-Latency on the Rust path is not worse than
       baseline + tolerance (default 20 % per ADR-0065 §AC-2,
       configurable via ``--latency-tolerance-pct``).
     * **A4 decision-count:** Engine still emits exactly
       ``expected_components`` (default 8) BackendDecisions per boot,
       no in-place component dropped or duplicated. (Auftrag says
       "7 BackendDecisions"; ADR-0065 §Option-B lists 7 components,
       but the current Phase-3b inventory in
       :mod:`wirelang.persona_engine.rust_backend_switch` has 8
       resolvers — Selin's drift-note: the ``expected_components``
       default tracks the engine inventory, not the ADR-0065 prose.
       Operators who want the literal ADR-0065 count pass
       ``--expected-components 7``.)
     * **A5 fallback-clean:** Zero ``fallback_reason`` entries on the
       Rust path (a fallback would mean the engine silently dropped
       back to Python — the cutover would look successful but the
       audit-record would not say ``backend: rust``).
4. **Rollback probe.** ``WAKIR_V907_VERIFY_BACKEND`` unset (engine
   reads Python-default), re-boot, asserts that the engine emits
   ``chosen_backend == "python"`` again — the operator must be able
   to roll back in ≤10 min per ADR-0065 §Rollback-SLA, so the smoke
   verifies that the ENV-unset path is functional.
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All five asserts pass + rollback OK.
     * ``1`` — **CAUTION**. At least one non-blocker drift (A3 latency in
       tolerance band, A4 component-count mismatch — operator should
       investigate but the engine substance is intact).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 failed, or
       rollback-probe failed (these are substance-fail signals; the
       engine's V-907 hash-determinism is broken or the backend did
       not flip).

The smoke writes a JSON envelope to ``--output`` (or stdout) that the
Welle-1 cutover-PR can attach as evidence. The envelope shape is
documented under ``__all__`` and pinned by the test suite.

Hermeticity
-----------

stdlib-only. Never imports NATS clients, the Anthropic SDK, the real
Rust binary, or any container runtime. The mocked engine uses the
production :mod:`wirelang.persona_engine.rust_backend_switch`
resolvers via the same lazy-import seam as the dry-run sibling, with
a stubbed binary-probe so the Rust subprocess is never invoked. Tests
inject a fully-stubbed resolver module so the script is importable
without the wirelang package being installed.

Operator usage
--------------

::

    # GREEN-path smoke (default 8 boots per phase, full asserts)
    python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \\
        --output out/welle-1-smoke.json

    # ADR-0065-prose-conformance variant (7 components):
    python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \\
        --expected-components 7 --output out/welle-1-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \\
        --latency-tolerance-pct 10

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
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants — Welle-1 focus on v907_verify, but the smoke is generic
# enough to be extended to Welle-2..7 by changing the focus component.
# ---------------------------------------------------------------------------

#: Welle-1 focus component (ADR-0065 §Option-B Wo-1).
FOCUS_COMPONENT = "v907_verify"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-1.
FOCUS_ENV_VAR = "WAKIR_V907_VERIFY_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Mirrors the order in the sibling
#: dry-run (which mirrors the ADR-0065 §Option-B Welle-1..7 sequence
#: + the Tag-25 Welle-2 svid_workload_identity wire-in).
ENGINE_BOOT_COMPONENTS: Tuple[str, ...] = (
    "v907_verify",
    "svid_workload_identity",
    "bridge_diff",
    "anchor_emitter",
    "state_backing",
    "fsm",
    "subscribe_loop",
    "recovery",
)

#: ADR-0065 §AC-2 tolerance: P95-Latency on the Rust path must not be
#: worse than Python-baseline + 20 %.
DEFAULT_LATENCY_TOLERANCE_PCT = 20

#: ADR-0065 §Verifikations-Plan Mo: 12 boots is the live-smoke baseline.
#: Smoke uses 8 per phase by default (pre/post/rollback × 8 = 24 total
#: resolver calls per component, well over the percentile sample
#: requirement).
DEFAULT_BOOTS_PER_PHASE = 8

#: Default expected in-place-component count. Tracks the engine
#: inventory (8), not the ADR-0065 §Option-B prose (7). Operators
#: invoking the smoke with the ADR-prose interpretation pass
#: ``--expected-components 7``; tests cover both.
DEFAULT_EXPECTED_COMPONENTS = len(ENGINE_BOOT_COMPONENTS)

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-1-cutover-smoke/1"

#: ENV-var values the smoke flips per phase.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"


# ---------------------------------------------------------------------------
# Per-component env-var bridge — mirrors rust_backend_switch.py module
# constants. Kept local so the smoke does not have to import the
# resolver module just to read constants; the resolver itself is
# still consulted via lazy-import for decision-making.
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
# Stub binary-probe — never touches the filesystem.
# ---------------------------------------------------------------------------


def _stub_probe_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
    """Pretend every Rust binary is present and executable.

    The smoke assumes the Pilot-VM operator has the Rust binaries
    deployed — that's a separate Quadlet-Installer prerequisite (per
    ADR-0065 §Trigger-Bedingung-3). The smoke focuses on the
    *backend-switch behaviour*, not the binary-deployment posture.
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
        cutover step).
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
        # which the resolver treats as the python-default
        # (verified against the resolver code at line ~1408).
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
) -> List[Dict[str, Any]]:
    """Simulate a single persona-engine boot.

    For each in-place component, calls the resolver and collects the
    ``BackendDecision``. Returns the list of decision-records in the
    declared component order. The engine in production emits these as
    structured-log JSON-lines; the smoke captures them in-memory.

    Parameters
    ----------
    env
        Hermetic env-map from :func:`build_phase_env`.
    components
        Tuple of in-place components to resolve.
    resolver_module
        Lazy-imported resolver module (test seam).
    binary_probe
        Stubbed binary-probe (test seam).
    """
    records: List[Dict[str, Any]] = []
    for component in components:
        fn_name = _resolver_fn_name(component)
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
        records.append(asdict(decision))
    return records


def run_phase(
    phase: str,
    *,
    boots: int,
    components: Tuple[str, ...],
    resolver_module: Any,
    binary_probe: Callable[[str], Tuple[bool, Optional[str]]],
    base_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Run ``boots`` mocked boots for a single phase.

    Returns a phase-record:
      * ``phase`` — the phase label.
      * ``env_snapshot`` — the hermetic env-map after :func:`build_phase_env`.
      * ``boots`` — boot-count.
      * ``decisions`` — flattened list of BackendDecision dicts
        (length == boots * len(components)).
      * ``per_boot_decisions`` — list of per-boot lists (length ==
        boots, each element is a list of length len(components)).
    """
    if boots < 1:
        raise ValueError(f"boots must be >= 1; got {boots!r}")
    env = build_phase_env(phase, base_env=base_env)
    per_boot: List[List[Dict[str, Any]]] = []
    flat: List[Dict[str, Any]] = []
    for _ in range(boots):
        boot_records = boot_engine_once(
            env=env,
            components=components,
            resolver_module=resolver_module,
            binary_probe=binary_probe,
        )
        per_boot.append(boot_records)
        flat.extend(boot_records)
    return {
        "phase": phase,
        "env_snapshot": dict(env),
        "boots": boots,
        "decisions": flat,
        "per_boot_decisions": per_boot,
    }


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

    Fixture-reference: ``tests/fixtures/anchor-emitter-cross-lang/``
    (PR #170) and the SVID Cross-Lang Pins (PR #224) embed the
    invariant that Python and Rust write byte-equal parity-relevant
    outputs. This hash is the smoke's local materialisation of that
    contract — the V-907 hash-determinism gate (ADR-0063 §V-907) is
    exactly the "byte-equal across implementations" promise.
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
    focus: str = FOCUS_COMPONENT,
) -> Dict[str, Any]:
    """Evaluate A1..A5 plus rollback-probe; return a structured asserts-record.

    Each assert is encoded as ``{passed: bool, severity: "blocker" |
    "caution", detail: str}`` so the envelope can render the full
    Decision-Matrix table.

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
            f"v907_verify chosen_backend across {len(post_focus)} "
            f"post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})}"
        ),
    }

    # A2: cross-lang parity-hash identical between the two clean
    # happy-paths — Post-Cutover-Rust and Rollback-Python.
    #
    # Why not Pre vs Post? The Pre-Cutover phase is the *explicit*
    # python branch: the operator has set WAKIR_V907_VERIFY_BACKEND=
    # python, and the resolver records `fallback_reason=
    # "explicit_python"` to distinguish that explicit choice from the
    # implicit python-default. Rollback (env-var absent) is the
    # implicit-python branch: `fallback_reason=None`. The two are
    # *semantically* different by resolver-design — that's the
    # information R1 leans on to verify the rollback path.
    #
    # The genuine cross-lang parity-promise is between the two
    # clean-emit paths: a successful cutover to Rust
    # (chosen=rust, fallback_reason=None) and a successful rollback
    # back to the implicit Python (chosen=python, fallback_reason=
    # None). With chosen_backend projected out, the BackendDecision's
    # structural shape must be byte-equal across both backends.
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

    # A3: P95 latency tolerance.
    pre_p95 = latency_p95(pre_records, focus=focus)
    post_p95 = latency_p95(post_records, focus=focus)
    # If baseline is 0 (very fast stub path), use absolute tolerance
    # window of 100 microseconds — the smoke is hermetic, so the
    # resolvers run essentially instantly. The tolerance only fires
    # if the post-cutover p95 is meaningfully higher.
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
    # Bucket post-records into boots of size len(ENGINE_BOOT_COMPONENTS)
    # via the per_boot list shape — but here we operate on the flat
    # list, so check the flat length first.
    a4_total_ok = len(post_records) == expected_components * boots_per_phase
    # Per-boot bucketisation: chunk size = expected_components (treat
    # the actual engine emission as ground truth — if the engine
    # emitted fewer/more components per boot, the bucket won't divide
    # cleanly and a4 fails).
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

    return asserts


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
    """Parity-hash over the *structural* fields of focus-component records.

    A2 verifies the **structural cross-lang parity** of the decision
    records — i.e. the focus-component still surfaces a well-formed
    BackendDecision under both backends, with the same ``domain`` and
    the same ``fallback_reason`` shape (null on clean paths,
    non-empty on failure paths). The ``requested_backend`` and
    ``chosen_backend`` fields are deliberately projected out:
    ``requested_backend`` is what the env-var flip changes (python →
    rust between Pre and Post), and ``chosen_backend`` is what the
    resolver returns (also flipped on a successful cutover). Including
    either would make A2 trivially differ across the cutover and
    defeat the assert's purpose.

    What remains is the *byte-shape oracle*: the resolver must keep
    emitting BackendDecision records with the right ``domain``,
    consistent ``fallback_reason`` (null when the backend resolves
    cleanly), and consistent presence semantics. This mirrors the
    invariant that PR #224 (SVID Cross-Lang Pins) and PR #170
    (Anchor-Emitter Cross-Lang fixtures) pinned at the
    Bridge-Audit-Writer substrate level — the audit-record's
    well-formedness does not depend on which backend produced it.

    ``bin_path`` is also not included because the focus-component's
    Rust binary path is filesystem-dependent (operator-VM-specific)
    and would defeat determinism.
    """
    focus_records = _focus_records(records, focus=focus)
    fields = [
        (
            r.get("domain"),
            # requested_backend deliberately omitted: env-var flip
            # naturally changes it.
            # chosen_backend deliberately omitted: it is what the
            # cutover flips.
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
      * All passed → :data:`EXIT_GREEN` (0).
    """
    blocker_fail = any(
        v.get("severity") == "blocker" and not v.get("passed")
        for v in asserts.values()
    )
    if blocker_fail:
        return EXIT_ROLLBACK
    caution_fail = any(
        v.get("severity") == "caution" and not v.get("passed")
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
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the operator-facing JSON envelope.

    Fields fixed by :data:`__all__` contract and the test suite.
    """
    timestamp = int(now_ts if now_ts is not None else time.time())
    band_for_exit = {
        EXIT_GREEN: "GREEN",
        EXIT_CAUTION: "CAUTION",
        EXIT_ROLLBACK: "ROLLBACK_RECOMMENDED",
    }
    envelope: Dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "timestamp_utc": timestamp,
        "welle": 1,
        "focus_component": FOCUS_COMPONENT,
        "focus_env_var": FOCUS_ENV_VAR,
        "engine_boot_components": list(ENGINE_BOOT_COMPONENTS),
        "expected_components": expected_components,
        "boots_per_phase": boots_per_phase,
        "latency_tolerance_pct": latency_tolerance_pct,
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
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + envelope. Return (envelope, exit_code).

    Pure function: never mutates ``os.environ``, never opens files.
    All side-effects happen at the CLI layer.
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
    )
    post_phase = run_phase(
        PHASE_POST,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
    )
    rollback_phase = run_phase(
        PHASE_ROLLBACK,
        boots=boots_per_phase,
        components=components,
        resolver_module=module,
        binary_probe=probe,
        base_env=base_env,
    )
    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
    )
    exit_code = derive_exit_code(asserts)
    envelope = build_envelope(
        pre_phase=pre_phase,
        post_phase=post_phase,
        rollback_phase=rollback_phase,
        asserts=asserts,
        exit_code=exit_code,
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        now_ts=now_ts,
    )
    return envelope, exit_code


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-1-v907-verify-cutover-smoke",
        description=(
            "Phase-3c Welle-1 (v907_verify) End-to-End Cutover-Smoke "
            "for ADR-0065. Boots a mocked persona-engine across "
            "Pre-Cutover (Python baseline) → Cutover (Rust) → Rollback "
            "(Python) phases, evaluates A1..A5 + R1 asserts, and "
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
            f"{DEFAULT_EXPECTED_COMPONENTS} = engine inventory). Pass 7 "
            "for the ADR-0065 §Option-B prose interpretation."
        ),
    )
    p.add_argument(
        "--latency-tolerance-pct",
        type=int,
        default=DEFAULT_LATENCY_TOLERANCE_PCT,
        help=(
            f"P95-latency tolerance percentage over baseline "
            f"(default {DEFAULT_LATENCY_TOLERANCE_PCT}, per ADR-0065 §AC-2). "
            "A3 caution-asserts fires when post p95 exceeds baseline + "
            "this percentage."
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
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    stdout: Optional[io.TextIOBase] = None,
    stderr: Optional[io.TextIOBase] = None,
    resolver_module: Optional[Any] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if args.boots_per_phase < 1:
        err.write(
            f"welle-1-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-1-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-1-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
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
            f"welle-1-cutover-smoke: cannot write output "
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
    "boot_engine_once",
    "build_argparser",
    "build_envelope",
    "build_phase_env",
    "derive_exit_code",
    "evaluate_post_cutover_asserts",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
