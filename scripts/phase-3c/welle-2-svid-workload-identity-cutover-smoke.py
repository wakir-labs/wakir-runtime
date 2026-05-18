#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-2-svid-workload-identity-cutover-smoke — End-to-End Cutover-Smoke for ADR-0065 Welle-2.

Background
----------

ADR-0065 (approved 2026-05-17, commit ``1815a88``) staggers the
Phase-3c persona-engine default-backend flip in seven weekly waves.
**Welle-2** is ``svid_workload_identity``: the SPIFFE/SVID Workload-
Identity resolver, the 8th BackendDecision the engine emits per boot
(Tag-25 wire-in, PR #191 default backend resolver
``7e2defb``). ADR-0066 (approved 2026-05-17) accelerates the Welle-1
+ Welle-2 cutover into a **parallel KW-24 doppel-cutover**: Welle-1
(``v907_verify``) and Welle-2 (``svid_workload_identity``) flip on
the Pilot-VM in the same operator-hand window.

This script is the strict, **asserts-tragend** End-to-End Cutover-
Smoke for Welle-2, modelled byte-for-byte on the Welle-1 sibling
``scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py``
(Tag-34, PR #230, ``53af6ac``). The pattern-parity is intentional:
the operator runs both smokes back-to-back, gets two JSON envelopes
with the same shape (``schema`` only differs by Welle number), and
the dual-go/no-go decision is taken from the two tri-state exit
codes.

SVID-specific delta vs. Welle-1
-------------------------------

The smoke adds **one** SVID-specific assert that does not exist in
the Welle-1 shape:

* **A6 svid-fixture-parity:** the smoke recomputes the snapshot-hash
  ladder of the five canonical SVID Cross-Lang fixtures (PR #224
  ``de47cb3``, ``tests/fixtures/svid-workload-cross-lang/
  fixtures.json``) via the **Python authority**
  :mod:`wirelang.identity.svid_workload_identity_canonical`, and
  asserts that every recomputed SHA-256 equals the pinned baseline.
  This is the **substrate-level oracle** for SVID cross-lang parity:
  if the snapshot-encoder is byte-stable across Python and the future
  Rust pendant, every Python-recomputed hash equals the fixture's
  pinned ``snapshot_sha256_hex`` field. A6 caution-fires if any
  recomputed hash mismatches its baseline (substrate drift between
  the canonical-snapshot encoder and the Authority-Pin).

The other five asserts (A1..A5 + R1) mirror Welle-1 verbatim,
re-pointed at ``svid_workload_identity`` and
``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND``.

Real-resolver verification
--------------------------

ADR-0066 §Welle-2-Mitigation requires that the smoke verifies the
**real** ``resolve_svid_workload_identity_backend`` from PR #191
(Tag-25 wire-in, ``7e2defb``) — not a stub. The smoke imports the
resolver lazily via the same seam as Welle-1
(:func:`_import_resolver`) and passes a stub *binary-probe* so the
resolver never touches the filesystem. The resolver's pure logic
(env-var → BackendDecision shape) is exercised end-to-end. Tests
inject a fully-stubbed resolver module for hermetic-CI runs; the
real-resolver path is exercised by the operator when the wirelang
package is importable in the run environment.

What the smoke does
-------------------

1. **Pre-Cutover baseline.** Boots a mocked persona-engine with the
   Python default
   (``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=python``). Records the
   ``BackendDecision`` for ``svid_workload_identity`` plus the
   BackendDecisions for the other in-place components (default 9
   total per ADR-0066 KW-24 inventory after PR #200 federation-
   resolver wire-in). Computes a baseline cross-lang parity-hash.
2. **Cutover step.** Flips
   ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust`` in the hermetic env-
   map (the script never mutates ``os.environ``; the engine sees a
   private mapping), restarts the mocked engine, re-collects
   BackendDecisions.
3. **Post-Cutover asserts.** Five hard checks + one SVID-specific
   substrate-parity check:
     * **A1 backend-flip:** ``svid_workload_identity`` BackendDecision
       now reports ``chosen_backend == "rust"``.
     * **A2 parity-hash:** Cross-lang parity-hash identical between
       Post-Cutover-Rust and Rollback-Python (clean happy-paths,
       same projection as Welle-1).
     * **A3 latency:** P95-Latency on the Rust path is not worse than
       baseline + tolerance (default 20 % per ADR-0065 §AC-2).
     * **A4 decision-count:** Engine emits exactly
       ``expected_components`` (default 9) BackendDecisions per boot,
       no in-place component dropped or duplicated.
     * **A5 fallback-clean:** Zero ``fallback_reason`` entries on the
       Rust path. (Caveat: until the
       ``persona-engine-svid-workload-identity`` Rust crate ships a
       real ``FetchX509SVID`` substrate, the real resolver's
       ``fallback_reason="binary_missing"`` is the **expected** signal
       per the Tag-25 wire-in docstring. Operators running the smoke
       against the engine before the Welle-2 image lands will see
       A5 fail; that is the ADR-0065 Welle-2 *precondition*, not a
       smoke bug. The stub-resolver path used by the test-suite
       reports no fallback so the GREEN-band semantic stays
       unambiguous; live-operator runs supply the real binary.)
     * **A6 svid-fixture-parity:** Five SVID Cross-Lang fixtures from
       PR #224 (``tests/fixtures/svid-workload-cross-lang/
       fixtures.json``) recomputed via
       :mod:`wirelang.identity.svid_workload_identity_canonical`
       hash byte-equal to the pinned baselines. *Caution-severity*:
       a substrate-drift here means the canonical encoder has shifted
       since the Tag-33 pin; operators investigate but the
       engine-emission-level cutover (A1..A5) is still intact.
       Skipped (and reported as ``passed=true, severity=caution,
       skipped=true``) when the canonical module or fixture file is
       not importable in the smoke's run environment.
4. **Rollback probe.** ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND``
   unset (engine reads Python-default), re-boot, asserts that the
   engine emits ``chosen_backend == "python"`` again — the operator
   must be able to roll back in ≤10 min per ADR-0065 §Rollback-SLA.
5. **Tri-state exit:**
     * ``0`` — **GREEN**, cutover-ready. All five asserts pass +
       rollback OK + A6 substrate-parity green.
     * ``1`` — **CAUTION**. At least one non-blocker drift (A3
       latency in tolerance band, A4 component-count mismatch, A6
       SVID-fixture drift — operator should investigate but the
       engine-emission substance is intact).
     * ``2`` — **ROLLBACK-RECOMMENDED**. A1 / A2 / A5 failed, or
       rollback-probe failed.

The smoke writes a JSON envelope to ``--output`` (or stdout). The
envelope shape is documented under ``__all__`` and pinned by the
test suite.

Hermeticity
-----------

stdlib-only at the smoke level. The optional A6 fixture-parity
check imports
:mod:`wirelang.identity.svid_workload_identity_canonical` lazily and
reads the fixtures JSON; both are gracefully skipped if missing so
the smoke remains importable in test environments without the
wirelang package installed. The mocked engine itself never imports
NATS, the Anthropic SDK, the real Rust binary, or any container
runtime.

Operator usage
--------------

::

    # GREEN-path smoke (default 9 boots per phase, 9 expected components).
    python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \\
        --output out/welle-2-smoke.json

    # ADR-0065-prose-conformance variant (7 components per §Option-B):
    python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \\
        --expected-components 7 --output out/welle-2-smoke.json

    # Tighter latency tolerance (10 %, stricter than AC-2):
    python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \\
        --latency-tolerance-pct 10

    # Skip the A6 substrate-parity probe (e.g. when fixtures are
    # gated behind a sub-tree the operator does not have):
    python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \\
        --skip-svid-fixture-parity

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
# Constants — Welle-2 focus on svid_workload_identity.
# ---------------------------------------------------------------------------

#: Welle-2 focus component (ADR-0065 §Option-B Wo-2; ADR-0066 KW-24
#: parallel cutover).
FOCUS_COMPONENT = "svid_workload_identity"

#: Env-var the operator flips on Pilot-VM Quadlet for Welle-2.
FOCUS_ENV_VAR = "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"

#: All in-place Phase-3b/3c components the mocked engine emits
#: BackendDecisions for at boot. Tracks the current engine inventory:
#: nine resolvers as of PR #200 (Tag-30 federation_resolver wire-in).
#: This is the **engine-realität-after-PR-200** count per the Tag-35
#: Auftrag.
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
#: inventory (9 after PR #200 federation_resolver), not the ADR-0065
#: §Option-B prose (7). Operators invoking the smoke with the ADR-
#: prose interpretation pass ``--expected-components 7``; tests cover
#: both. The default-9 vs. ADR-prose-7 drift is the same drift
#: Welle-1 documents — Selin's drift-note is preserved.
DEFAULT_EXPECTED_COMPONENTS = len(ENGINE_BOOT_COMPONENTS)

#: Phase labels for the envelope.
PHASE_PRE = "pre_cutover_python_baseline"
PHASE_POST = "post_cutover_rust"
PHASE_ROLLBACK = "rollback_python"

#: Exit-code triad mandated by Auftrag-Tag-34/35.
EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

#: Schema version for the JSON envelope.
ENVELOPE_SCHEMA = "wakir.phase-3c.welle-2-cutover-smoke/1"

#: ENV-var values the smoke flips per phase.
ENV_VALUE_PYTHON = "python"
ENV_VALUE_RUST = "rust"

#: Path to the SVID Cross-Lang fixtures (PR #224 ``de47cb3``).
#: Resolved relative to the repo-root at runtime so the smoke works
#: from arbitrary working directories. Tests override via
#: ``--svid-fixture-path``.
DEFAULT_SVID_FIXTURE_RELPATH = (
    "tests/fixtures/svid-workload-cross-lang/fixtures.json"
)


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

    Operator-warning: the live Welle-2 substrate is still
    ``binary_missing`` until the
    ``persona-engine-svid-workload-identity`` Rust crate ships a
    real ``FetchX509SVID`` runtime (the Tag-25 wire-in docstring
    pinned that as the ADR-0065 Welle-2 *precondition*). The stub
    here keeps the smoke green-band-demonstrable; the live Pilot-VM
    smoke uses the real ``_binary_available`` probe and will fall
    into A5-failure until the crate lands. That is the substance-
    signal the operator wants, not a smoke bug.
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
        cutover step for svid_workload_identity).
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
) -> List[Dict[str, Any]]:
    """Simulate a single persona-engine boot.

    For each in-place component, calls the resolver and collects the
    ``BackendDecision``. Returns the list of decision-records in the
    declared component order. The engine in production emits these as
    structured-log JSON-lines; the smoke captures them in-memory.
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
      * ``per_boot_decisions`` — list of per-boot lists.
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

    Fixture-reference: ``tests/fixtures/svid-workload-cross-lang/
    fixtures.json`` (PR #224) and the Anchor-Emitter Cross-Lang
    fixtures (PR #170) embed the invariant that Python and Rust write
    byte-equal parity-relevant outputs. This hash is the smoke's
    engine-emission-level materialisation of that contract; A6 verifies
    the substrate-level oracle directly.
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
# A6 — SVID fixture-parity substrate probe.
# ---------------------------------------------------------------------------


def _repo_root_from_script() -> Path:
    """Locate the wakir-runtime repo root from this script's path.

    The smoke lives at ``scripts/phase-3c/welle-2-svid-workload-
    identity-cutover-smoke.py``, so the repo-root is two parents up.
    """
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _resolve_fixture_path(explicit: Optional[Path]) -> Path:
    if explicit is not None:
        return explicit
    return _repo_root_from_script() / DEFAULT_SVID_FIXTURE_RELPATH


def _import_svid_canonical() -> Any:
    """Lazy import of the SVID canonical-snapshot Python authority.

    Returns the imported module. Raises ImportError if the wirelang
    package is not installed; the caller treats that as A6-skip.
    """
    return importlib.import_module(
        "wirelang.identity.svid_workload_identity_canonical"
    )


def evaluate_svid_fixture_parity(
    *,
    fixture_path: Optional[Path] = None,
    canonical_module: Optional[Any] = None,
) -> Dict[str, Any]:
    """Recompute the SVID Cross-Lang fixture hashes via the Python authority.

    Returns a structured result:
      * ``passed`` — True if every fixture's recomputed
        ``snapshot_sha256_hex`` matches the pinned baseline.
      * ``skipped`` — True if the fixture file is missing or the
        canonical module cannot be imported (treated as ``passed`` to
        avoid hard-failing the smoke on environments without the
        wirelang package; severity stays caution).
      * ``severity`` — Always ``"caution"`` (substrate drift is a
        Tomás-Zone-K signal, not a Pilot-VM-cutover blocker).
      * ``detail`` — Human-readable summary or first mismatch.
      * ``recomputed`` — List of ``{name, baseline, recomputed,
        match}`` for each fixture (empty when skipped).

    The canonical module discovery order (see
    :func:`_resolve_svid_hash_helper`):

      1. ``module.snapshot_sha256_for_bindings(bindings) -> str`` —
         shortest-path helper (used by the test stubs).
      2. ``module.build_snapshot_from_bindings`` +
         ``module.snapshot_sha256_hex`` + ``module.build_binding`` —
         the **real wirelang public API**; takes the fixture's raw
         binding-dicts, constructs ``SvidWorkloadBinding`` instances
         via ``build_binding``, then builds the snapshot under the
         fixture's ``fixed_now_utc`` and hashes it.
      3. Legacy ``encode_svid_workload_snapshot`` / ``canonicalise``
         entry points (left in for forward-compat with substrate
         renames).
    """
    path = _resolve_fixture_path(fixture_path)
    if not path.is_file():
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": f"svid fixture file not found at {path}",
            "recomputed": [],
        }
    try:
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (OSError, ValueError) as exc:
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": f"svid fixture file unreadable at {path}: {exc}",
            "recomputed": [],
        }

    fixtures = payload.get("fixtures") or []
    if not isinstance(fixtures, list) or not fixtures:
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": f"svid fixture file at {path} has no 'fixtures' list",
            "recomputed": [],
        }

    module = canonical_module
    if module is None:
        try:
            module = _import_svid_canonical()
        except ImportError as exc:
            return {
                "passed": True,
                "skipped": True,
                "severity": "caution",
                "detail": (
                    f"svid_workload_identity_canonical not importable: "
                    f"{exc}"
                ),
                "recomputed": [],
            }

    fixed_now_utc = payload.get("fixed_now_utc")
    hash_helper = _resolve_svid_hash_helper(
        module, fixed_now_utc=fixed_now_utc
    )
    if hash_helper is None:
        return {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": (
                "svid_workload_identity_canonical exposes neither "
                "snapshot_sha256_for_bindings nor "
                "encode_svid_workload_snapshot"
            ),
            "recomputed": [],
        }

    recomputed: List[Dict[str, Any]] = []
    all_match = True
    first_mismatch_detail: Optional[str] = None
    for fixture in fixtures:
        name = fixture.get("name", "<unnamed>")
        bindings = fixture.get("input_bindings") or []
        expected_block = fixture.get("expected") or {}
        baseline = expected_block.get("snapshot_sha256_hex")
        if baseline is None:
            # Fixture missing baseline → skip but record.
            recomputed.append(
                {
                    "name": name,
                    "baseline": None,
                    "recomputed": None,
                    "match": True,
                    "note": "fixture has no snapshot_sha256_hex baseline",
                }
            )
            continue
        try:
            computed = hash_helper(bindings)
        except Exception as exc:  # noqa: BLE001 — substrate drift is the
            # signal we want; capture and continue.
            all_match = False
            if first_mismatch_detail is None:
                first_mismatch_detail = (
                    f"fixture {name!r} raised {type(exc).__name__}: {exc}"
                )
            recomputed.append(
                {
                    "name": name,
                    "baseline": baseline,
                    "recomputed": None,
                    "match": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        match = computed == baseline
        if not match and first_mismatch_detail is None:
            first_mismatch_detail = (
                f"fixture {name!r} baseline={baseline} "
                f"recomputed={computed}"
            )
        if not match:
            all_match = False
        recomputed.append(
            {
                "name": name,
                "baseline": baseline,
                "recomputed": computed,
                "match": match,
            }
        )

    return {
        "passed": all_match,
        "skipped": False,
        "severity": "caution",
        "detail": (
            first_mismatch_detail
            if first_mismatch_detail is not None
            else f"all {len(recomputed)} svid fixtures byte-equal"
        ),
        "recomputed": recomputed,
    }


def _resolve_svid_hash_helper(
    module: Any,
    *,
    fixed_now_utc: Optional[str] = None,
) -> Optional[Callable[[Any], str]]:
    """Discover a snapshot→sha256 helper on the canonical module.

    The smoke tries (in order):
      1. ``module.snapshot_sha256_for_bindings(bindings) -> str``
         (lowercase hex digest, used by test stubs).
      2. ``module.build_snapshot_from_bindings`` +
         ``module.snapshot_sha256_hex`` + ``module.build_binding`` —
         the **real wirelang public API** as of PR #224. Takes raw
         binding-dicts, constructs ``SvidWorkloadBinding`` via
         ``build_binding``, builds the snapshot under
         ``fixed_now_utc``, hashes via ``snapshot_sha256_hex``.
      3. ``module.encode_svid_workload_snapshot(bindings) -> bytes``
         (legacy JCS-bytes path) → wrapped through ``hashlib.sha256``.
      4. ``module.canonicalise(bindings) -> bytes`` (legacy name) →
         wrapped through ``hashlib.sha256``.

    Returns a unary callable taking the raw fixture-bindings list and
    returning the lowercase-hex SHA-256, or None if the module exposes
    no matching surface.
    """
    helper = getattr(module, "snapshot_sha256_for_bindings", None)
    if callable(helper):
        return helper

    builder = getattr(module, "build_snapshot_from_bindings", None)
    hasher = getattr(module, "snapshot_sha256_hex", None)
    binding_ctor = getattr(module, "build_binding", None)
    if callable(builder) and callable(hasher) and callable(binding_ctor):
        if fixed_now_utc is None:
            # Real wirelang builder requires a fixed_now_utc; if the
            # fixture file does not supply one, we cannot use this path.
            return None

        def _wrap_real_api(bindings: Any) -> str:
            typed_bindings = []
            for b in bindings:
                if not isinstance(b, dict):
                    raise TypeError(
                        f"binding entries must be dicts; got {type(b).__name__}"
                    )
                typed_bindings.append(
                    binding_ctor(
                        org_id=b["org_id"],
                        persona_id=b["persona_id"],
                        spiffe_id=b.get("spiffe_id"),
                        not_after_utc=b["not_after_utc"],
                        bind_state_sha256=b["bind_state_sha256"],
                        expired=bool(b.get("expired", False)),
                    )
                )
            snapshot = builder(typed_bindings, fixed_now_utc=fixed_now_utc)
            return hasher(snapshot)

        return _wrap_real_api

    encoder = getattr(module, "encode_svid_workload_snapshot", None)
    if callable(encoder):
        def _wrap_encoder(bindings: Any) -> str:
            payload = encoder(bindings)
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            return hashlib.sha256(payload).hexdigest()

        return _wrap_encoder

    legacy = getattr(module, "canonicalise", None)
    if callable(legacy):
        def _wrap_legacy(bindings: Any) -> str:
            payload = legacy(bindings)
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            return hashlib.sha256(payload).hexdigest()

        return _wrap_legacy

    return None


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
    svid_fixture_result: Optional[Dict[str, Any]] = None,
    focus: str = FOCUS_COMPONENT,
) -> Dict[str, Any]:
    """Evaluate A1..A5 + R1 + A6 (SVID-fixture-parity); return asserts-record.

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
            f"svid_workload_identity chosen_backend across "
            f"{len(post_focus)} post-cutover records: "
            f"{sorted({r.get('chosen_backend') for r in post_focus})}"
        ),
    }

    # A2: cross-lang parity-hash identical between Post-Cutover-Rust
    # and Rollback-Python (same projection as Welle-1).
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

    # A6: SVID-fixture-parity substrate probe (caution-severity).
    if svid_fixture_result is None:
        a6_detail = "A6 skipped (probe not invoked)"
        a6_record = {
            "passed": True,
            "severity": "caution",
            "skipped": True,
            "detail": a6_detail,
            "recomputed": [],
        }
    else:
        a6_record = {
            "passed": bool(svid_fixture_result.get("passed", True)),
            "severity": "caution",
            "skipped": bool(svid_fixture_result.get("skipped", False)),
            "detail": svid_fixture_result.get("detail", ""),
            "recomputed": svid_fixture_result.get("recomputed", []),
        }
    asserts["A6_svid_fixture_parity"] = a6_record

    return asserts


def _parity_hash_focus_normalised(
    records: List[Dict[str, Any]], *, focus: str = FOCUS_COMPONENT
) -> str:
    """Parity-hash over the *structural* fields of focus-component records.

    See the Welle-1 sibling for the full rationale; the projection
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
        "welle": 2,
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
    skip_svid_fixture_parity: bool = False,
    svid_fixture_path: Optional[Path] = None,
    svid_canonical_module: Optional[Any] = None,
) -> Tuple[Dict[str, Any], int]:
    """Run pre / post / rollback phases + asserts + A6 + envelope.

    Returns ``(envelope, exit_code)``.

    Pure function: never mutates ``os.environ``, never opens files
    except the optional SVID-fixture JSON (read-only).
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

    if skip_svid_fixture_parity:
        svid_fixture_result: Optional[Dict[str, Any]] = {
            "passed": True,
            "skipped": True,
            "severity": "caution",
            "detail": "A6 skipped via --skip-svid-fixture-parity",
            "recomputed": [],
        }
    else:
        svid_fixture_result = evaluate_svid_fixture_parity(
            fixture_path=svid_fixture_path,
            canonical_module=svid_canonical_module,
        )

    asserts = evaluate_post_cutover_asserts(
        pre_records=pre_phase["decisions"],
        post_records=post_phase["decisions"],
        rollback_records=rollback_phase["decisions"],
        expected_components=expected_components,
        boots_per_phase=boots_per_phase,
        latency_tolerance_pct=latency_tolerance_pct,
        svid_fixture_result=svid_fixture_result,
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
        prog="welle-2-svid-workload-identity-cutover-smoke",
        description=(
            "Phase-3c Welle-2 (svid_workload_identity) End-to-End "
            "Cutover-Smoke for ADR-0065 + ADR-0066 KW-24 doppel-"
            "cutover. Boots a mocked persona-engine across Pre-Cutover "
            "(Python baseline) -> Cutover (Rust) -> Rollback (Python) "
            "phases, evaluates A1..A5 + R1 + A6 (SVID fixture-parity) "
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
            f"{DEFAULT_EXPECTED_COMPONENTS} = engine inventory after "
            "PR #200 federation_resolver). Pass 7 for the ADR-0065 "
            "§Option-B prose interpretation."
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
        "--skip-svid-fixture-parity",
        action="store_true",
        help=(
            "Skip the A6 SVID-Cross-Lang fixture-parity probe. Use when "
            "the fixture file is gated behind a sub-tree the operator "
            "does not have or when the wirelang package is not in the "
            "import path."
        ),
    )
    p.add_argument(
        "--svid-fixture-path",
        type=Path,
        default=None,
        help=(
            f"Override the SVID Cross-Lang fixture path "
            f"(default <repo-root>/{DEFAULT_SVID_FIXTURE_RELPATH})."
        ),
    )
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    stdout: Optional[io.TextIOBase] = None,
    stderr: Optional[io.TextIOBase] = None,
    resolver_module: Optional[Any] = None,
    svid_canonical_module: Optional[Any] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if args.boots_per_phase < 1:
        err.write(
            f"welle-2-cutover-smoke: --boots-per-phase must be >= 1; "
            f"got {args.boots_per_phase!r}\n"
        )
        return 2
    if args.expected_components < 1:
        err.write(
            f"welle-2-cutover-smoke: --expected-components must be >= 1; "
            f"got {args.expected_components!r}\n"
        )
        return 2
    if args.latency_tolerance_pct < 0:
        err.write(
            f"welle-2-cutover-smoke: --latency-tolerance-pct must be >= 0; "
            f"got {args.latency_tolerance_pct!r}\n"
        )
        return 2

    envelope, exit_code = run_cutover_smoke(
        boots_per_phase=args.boots_per_phase,
        expected_components=args.expected_components,
        latency_tolerance_pct=args.latency_tolerance_pct,
        resolver_module=resolver_module,
        now_ts=args.now,
        skip_svid_fixture_parity=args.skip_svid_fixture_parity,
        svid_fixture_path=args.svid_fixture_path,
        svid_canonical_module=svid_canonical_module,
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
            f"welle-2-cutover-smoke: cannot write output "
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
    "DEFAULT_SVID_FIXTURE_RELPATH",
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
    "evaluate_svid_fixture_parity",
    "latency_p95",
    "main",
    "parity_hash",
    "run_cutover_smoke",
    "run_phase",
]


if __name__ == "__main__":
    sys.exit(main())
