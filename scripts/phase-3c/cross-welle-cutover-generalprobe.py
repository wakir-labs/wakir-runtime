#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""cross-welle-cutover-generalprobe — Phase-3c marathon dress-rehearsal.

Background
----------

ADR-0066 sequences the Phase-3c persona-engine default-backend
cutover across four calendar weeks:

* **KW-24** — Welle-1 ``v907_verify`` + Welle-2 ``svid_workload_identity``
  (parallel sub-sequence; both are low-risk read-side flips).
* **KW-25** — Welle-3 ``bridge_audit_writer`` (solo, write-side, the
  single highest-risk wave; gets a full week to settle).
* **KW-26** — Welle-4 ``state_backing`` + Welle-5
  ``lifecycle_state_machine`` (parallel sub-sequence).
* **KW-27** — Welle-6 ``subscribe_loop`` + Welle-7
  ``recovery_workflow`` (parallel sub-sequence; the closing pair).

The seven sibling per-welle smokes
(``scripts/phase-3c/welle-N-*-cutover-smoke.py``) each verify one
wave hermetically. They do **not** verify that the four-week
calendar holds together — that is, that one wave's cutover does
not leak state into the next, that A7 cross-modul-drift asserts
stay green across the full marathon, and that the operator-facing
Marathon-Verdict aggregates cleanly.

This script is the dress-rehearsal: it runs all seven welle-smokes
in ADR-0066-order, aggregates their tri-state exit codes and
A1..A7 asserts into a single Marathon-Verdict, and exits
``0/1/2 = GREEN/CAUTION/ROLLBACK_RECOMMENDED``. Cutover-Execution
KW-24 does not start without a GREEN generalprobe in CI.

What the generalprobe does
--------------------------

1. **Plan.** Build the sub-sequence plan from ADR-0066. Each
   sub-sequence has a calendar-week label, a list of welles, and
   a mode (``parallel`` for multi-welle weeks, ``solo`` for
   single-welle weeks).
2. **Dispatch.** For each sub-sequence, invoke the configured
   welle-N smokes. Parallel sub-sequences spawn one subprocess
   per welle and join. Solo sub-sequences run inline.
3. **Collect.** Each welle-smoke writes its JSON envelope to a
   per-welle output file under ``--out-dir`` (default
   ``out/cross-welle-generalprobe/<timestamp>/``). The
   generalprobe reads each envelope and pins:
     * ``welle`` (int) — must equal the expected wave id.
     * ``exit_code`` (int) — 0/1/2.
     * ``band`` (str) — GREEN/CAUTION/ROLLBACK_RECOMMENDED.
     * ``asserts`` (dict) — per-assert pass/fail/severity records.
4. **Aggregate.** Two aggregations:

   * **Marathon-Exit:** the worst tri-state exit code across all
     dispatched welles. ROLLBACK > CAUTION > GREEN.
   * **Cross-Welle-Drift-Aggregator:** all A1..A7 asserts from all
     dispatched welles are union'd into a single record. For each
     assert family, the aggregator reports ``{passed_in: [...],
     failed_in: [...], skipped_in: [...]}``. A *family* is the
     prefix before the welle-suffix (``A1_backend_flip``,
     ``A2_cross_lang_parity_hash``, ..., ``A7_<welle-specific>``).
     The Marathon-Drift-Verdict is computed family-by-family: if
     any blocker-severity assert failed in any welle, that family
     is RED; if only caution-severity failed, AMBER; else GREEN.
5. **Emit.** A single Marathon-Envelope is written to ``--output``
   (or stdout) with the full plan, per-welle envelopes (by
   reference path), the Marathon-Exit, and the
   Cross-Welle-Drift-Aggregator. The envelope shape is pinned by
   the test suite under ``tests/phase_3c/test_cross_welle_generalprobe.py``.

CLI surface
-----------

::

    # Full marathon (all 7 welles, GREEN if all pass)
    python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \\
        --out-dir out/generalprobe/

    # Plan-only — print the ADR-0066 sequence, do not invoke smokes
    python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --dry-run

    # Partial run: only KW-24 + KW-25 (welles 1..3)
    python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --up-to-welle 3

    # Resume mid-marathon: only welles 4..7 (KW-26 + KW-27)
    python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --from-welle 4

    # Pass smoke arguments through (e.g. tighten latency band)
    python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \\
        --smoke-arg --boots-per-phase=2

Hermeticity
-----------

stdlib-only. The orchestrator spawns each welle-smoke as a
subprocess via :mod:`subprocess`. PYTHONPATH is set to the
repo-root so the smokes can import ``wirelang.persona_engine.
rust_backend_switch``. No NATS, no Rust binary, no Anthropic SDK
is invoked; the smokes themselves are hermetic by construction.

The orchestrator never mutates ``os.environ``: each subprocess
gets a freshly-built env-map. Tests inject a ``smoke_runner``
seam so the test suite can simulate welle envelopes without
spawning real subprocesses.

License: Apache-2.0 (parity with sibling Phase-3c scripts).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)


# ---------------------------------------------------------------------------
# Constants — pinned by the test suite.
# ---------------------------------------------------------------------------


EXIT_GREEN = 0
EXIT_CAUTION = 1
EXIT_ROLLBACK = 2

ENVELOPE_SCHEMA = "wakir.phase-3c.cross-welle-generalprobe/1"

BAND_GREEN = "GREEN"
BAND_CAUTION = "CAUTION"
BAND_ROLLBACK = "ROLLBACK_RECOMMENDED"
BAND_UNKNOWN = "UNKNOWN"

BAND_FOR_EXIT: Mapping[int, str] = {
    EXIT_GREEN: BAND_GREEN,
    EXIT_CAUTION: BAND_CAUTION,
    EXIT_ROLLBACK: BAND_ROLLBACK,
}

# Drift-family verdict bands (orthogonal to per-welle tri-state).
DRIFT_FAMILY_GREEN = "GREEN"
DRIFT_FAMILY_AMBER = "AMBER"
DRIFT_FAMILY_RED = "RED"


# ADR-0066 calendar plan. Order is load-bearing: KW-24 must run
# before KW-25 must run before KW-26 must run before KW-27.
@dataclass(frozen=True)
class SubSequence:
    """One ADR-0066 calendar-week sub-sequence."""

    kw_label: str
    welles: Tuple[int, ...]
    mode: str  # "parallel" or "solo"


PLAN: Tuple[SubSequence, ...] = (
    SubSequence(kw_label="KW-24", welles=(1, 2), mode="parallel"),
    SubSequence(kw_label="KW-25", welles=(3,), mode="solo"),
    SubSequence(kw_label="KW-26", welles=(4, 5), mode="parallel"),
    SubSequence(kw_label="KW-27", welles=(6, 7), mode="parallel"),
)


# Welle-N → smoke-script-path (relative to repo-root).
WELLE_SMOKE_PATHS: Mapping[int, str] = {
    1: "scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py",
    2: "scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py",
    3: "scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py",
    4: "scripts/phase-3c/welle-4-state-backing-cutover-smoke.py",
    5: "scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py",
    6: "scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py",
    7: "scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py",
}

# Welle-N → focus-component label (for the drift-aggregator
# detail-rendering). Kept in this module so the orchestrator
# does not need to import the sibling smokes.
WELLE_FOCUS_COMPONENT: Mapping[int, str] = {
    1: "v907_verify",
    2: "svid_workload_identity",
    3: "bridge_audit_writer",
    4: "state_backing",
    5: "lifecycle_state_machine",
    6: "subscribe_loop",
    7: "recovery_workflow",
}


# All assert-family prefixes the aggregator recognises. Per the
# per-welle smoke audit (Reza Tag-40 walk-through):
#   - A1..A5 are shared across all 7 welles.
#   - A6 is welle-specific (welle-1 has none; welles 2..7 each
#     have their own A6 family).
#   - A7 is the cross-modul-drift assert; introduced in welle-3,
#     present on welles 3..7.
#   - R1 (rollback) is shared across all 7 welles.
ASSERT_FAMILIES_SHARED: Tuple[str, ...] = (
    "A1_backend_flip",
    "A2_cross_lang_parity_hash",
    "A3_latency_within_tolerance",
    "A4_decision_count_in_place",
    "A5_fallback_clean",
    "R1_rollback_to_python",
)


# ---------------------------------------------------------------------------
# Plan-derivation helpers.
# ---------------------------------------------------------------------------


def filter_plan(
    plan: Sequence[SubSequence],
    *,
    from_welle: int = 1,
    up_to_welle: int = 7,
) -> List[SubSequence]:
    """Return the sub-sequences whose welles fall in [from_welle, up_to_welle].

    A sub-sequence is included if *any* of its welles is in range.
    Welles outside the range are filtered out within each sub-sequence;
    if a sub-sequence has no remaining welles, it is dropped.
    """
    if from_welle < 1 or up_to_welle > 7 or from_welle > up_to_welle:
        raise ValueError(
            f"invalid welle range: from={from_welle} up_to={up_to_welle} "
            f"(must satisfy 1 <= from <= up_to <= 7)"
        )
    out: List[SubSequence] = []
    for sub in plan:
        keep = tuple(w for w in sub.welles if from_welle <= w <= up_to_welle)
        if not keep:
            continue
        # Preserve mode unless the filter degrades a parallel
        # sub-sequence to a single welle.
        mode = sub.mode if len(keep) > 1 else "solo"
        out.append(SubSequence(kw_label=sub.kw_label, welles=keep, mode=mode))
    return out


def expected_assert_families(welles: Sequence[int]) -> List[str]:
    """Return the union of expected assert-family keys for `welles`.

    Used by the aggregator to know which families to report. Order
    is stable: shared families first, then A6/A7 in welle-id order.
    """
    families: List[str] = list(ASSERT_FAMILIES_SHARED)
    for w in sorted(welles):
        a6_key = _family_a6_for_welle(w)
        if a6_key is not None and a6_key not in families:
            families.append(a6_key)
        a7_key = _family_a7_for_welle(w)
        if a7_key is not None and a7_key not in families:
            families.append(a7_key)
    return families


def _family_a6_for_welle(welle: int) -> Optional[str]:
    """Return the A6 family-key for `welle`, or None if absent."""
    # welle-1 has no A6 (it is the read-only flip and only carries
    # A1..A5 + R1). Welles 2..7 each pin their own A6 family.
    if welle == 1:
        return None
    return {
        2: "A6_svid_fixture_parity",
        3: "A6_bridge_audit_stream_parity",
        4: "A6_cross_backend_read_compatibility",
        5: "A6_fsm_transition_integrity",
        6: "A6_subscribe_loop_lag_stability",
        7: "A6_recovery_r1_r4_drill",
    }.get(welle)


def _family_a7_for_welle(welle: int) -> Optional[str]:
    """Return the A7 family-key for `welle`, or None if absent.

    The per-welle smoke audit pinned (Tag-40 walk-through, captured
    from the live envelopes of all seven welle-smokes):

      * Welles 1+2 have no A7 (leading wave-pair, no earlier wave
        to drift against).
      * Welle-3 has ``A7_self_reference_trap_control`` (solo wave,
        no pair, so the A7 is a self-reference sentinel).
      * Welles 4..7 have a *pair-specific* A7 key naming the other
        moduln they verify drift against:

          - welle-4 → ``A7_cross_modul_drift_welle_5_fsm``
          - welle-5 → ``A7_cross_modul_drift_welle_4_state_backing``
          - welle-6 → ``A7_cross_modul_drift_welle_7_recovery``
          - welle-7 → ``A7_cross_modul_drift_welle_6_subscribe_loop``

    The aggregator surfaces these as separate families (one per
    pair-direction) so the operator can read drift symmetry from
    the Marathon-Envelope. Each pair-direction is independent: a
    welle-4 → welle-5 fail and a welle-5 → welle-4 pass tell two
    different stories about which side of the parallel pair leaked
    state.
    """
    if welle < 3:
        return None
    return {
        3: "A7_self_reference_trap_control",
        4: "A7_cross_modul_drift_welle_5_fsm",
        5: "A7_cross_modul_drift_welle_4_state_backing",
        6: "A7_cross_modul_drift_welle_7_recovery",
        7: "A7_cross_modul_drift_welle_6_subscribe_loop",
    }.get(welle)


# ---------------------------------------------------------------------------
# Smoke-runner seam.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmokeResult:
    """Result of invoking one welle-smoke."""

    welle: int
    exit_code: int
    band: str
    envelope: Dict[str, Any]
    envelope_path: Optional[Path]
    stderr_tail: str  # last ~16 lines for diagnostics


SmokeRunner = Callable[[int, Path, Sequence[str], Mapping[str, str]], SmokeResult]


def default_smoke_runner(
    welle: int,
    output_path: Path,
    extra_args: Sequence[str],
    env: Mapping[str, str],
) -> SmokeResult:
    """Spawn the welle-N smoke as a subprocess and parse its envelope.

    Hermeticity contract:
      * Never mutates the caller's environment.
      * Sets PYTHONPATH to the repo-root so the smoke can import
        ``wirelang.persona_engine.rust_backend_switch`` from the
        same checkout.
      * Reads the JSON envelope from `output_path` (the smoke is
        invoked with ``--output``).
    """
    smoke_rel = WELLE_SMOKE_PATHS[welle]
    repo_root = _repo_root_from_env(env)
    smoke_path = repo_root / smoke_rel
    if not smoke_path.is_file():
        return SmokeResult(
            welle=welle,
            exit_code=EXIT_ROLLBACK,
            band=BAND_ROLLBACK,
            envelope={
                "schema": "wakir.phase-3c.cross-welle-generalprobe.synthetic/1",
                "welle": welle,
                "band": BAND_ROLLBACK,
                "exit_code": EXIT_ROLLBACK,
                "asserts": {},
                "error": f"smoke script not found at {smoke_path}",
            },
            envelope_path=None,
            stderr_tail=f"smoke script not found at {smoke_path}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(smoke_path),
        "--output",
        str(output_path),
        *list(extra_args),
    ]
    proc = subprocess.run(
        cmd,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    exit_code = proc.returncode
    stderr_tail = "\n".join(proc.stderr.splitlines()[-16:])

    envelope: Dict[str, Any]
    if output_path.is_file():
        try:
            envelope = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            envelope = {
                "schema": "wakir.phase-3c.cross-welle-generalprobe.synthetic/1",
                "welle": welle,
                "band": BAND_ROLLBACK,
                "exit_code": EXIT_ROLLBACK,
                "asserts": {},
                "error": f"envelope JSON decode error: {exc}",
            }
            exit_code = EXIT_ROLLBACK
    else:
        envelope = {
            "schema": "wakir.phase-3c.cross-welle-generalprobe.synthetic/1",
            "welle": welle,
            "band": BAND_ROLLBACK,
            "exit_code": EXIT_ROLLBACK,
            "asserts": {},
            "error": "smoke produced no output envelope",
        }
        exit_code = EXIT_ROLLBACK

    band = envelope.get("band") or BAND_FOR_EXIT.get(exit_code, BAND_UNKNOWN)
    return SmokeResult(
        welle=welle,
        exit_code=exit_code,
        band=band,
        envelope=envelope,
        envelope_path=output_path if output_path.is_file() else None,
        stderr_tail=stderr_tail,
    )


def _repo_root_from_env(env: Mapping[str, str]) -> Path:
    """Return the repo-root path the runner uses for PYTHONPATH/smoke-paths."""
    val = env.get("WAKIR_GENERALPROBE_REPO_ROOT")
    if val:
        return Path(val)
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Aggregation logic.
# ---------------------------------------------------------------------------


def aggregate_exit(results: Sequence[SmokeResult]) -> int:
    """Marathon-Exit = worst per-welle exit code (ROLLBACK > CAUTION > GREEN)."""
    if not results:
        return EXIT_GREEN
    worst = EXIT_GREEN
    for r in results:
        if r.exit_code == EXIT_ROLLBACK:
            return EXIT_ROLLBACK
        if r.exit_code == EXIT_CAUTION:
            worst = EXIT_CAUTION
    return worst


def aggregate_drift(
    results: Sequence[SmokeResult],
    *,
    families: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build the Cross-Welle-Drift-Aggregator record.

    For each assert family, record:
      * ``passed_in`` — list of welle ids where the assert passed.
      * ``failed_in`` — list of welle ids where the assert failed
        (with per-welle severity for blocker/caution disambiguation).
      * ``skipped_in`` — list of welle ids where the family is not
        applicable (e.g. A6 on welle-1, A7 on welles 1+2).
      * ``family_verdict`` — RED / AMBER / GREEN per the rules:

        - RED if any blocker-severity assert failed.
        - AMBER if at least one caution failed but no blocker did.
        - GREEN if all dispatched welles passed (or family is N/A).
    """
    welles_dispatched = sorted({r.welle for r in results})
    if families is None:
        families = expected_assert_families(welles_dispatched)

    drift: Dict[str, Any] = {
        "families": {},
        "welles_dispatched": welles_dispatched,
    }
    overall_verdict = DRIFT_FAMILY_GREEN
    for fam in families:
        passed_in: List[int] = []
        failed_in: List[Dict[str, Any]] = []
        skipped_in: List[int] = []

        for r in sorted(results, key=lambda x: x.welle):
            applicable = _is_family_applicable(fam, r.welle)
            if not applicable:
                skipped_in.append(r.welle)
                continue
            asserts = r.envelope.get("asserts") or {}
            record = asserts.get(fam)
            if record is None:
                # Family expected for this welle but absent — treat
                # as a failed-record with synthesized blocker severity
                # so the operator notices a contract drift.
                failed_in.append(
                    {
                        "welle": r.welle,
                        "severity": "blocker",
                        "detail": "assert family expected but missing from envelope",
                    }
                )
                continue
            if record.get("passed"):
                passed_in.append(r.welle)
            else:
                failed_in.append(
                    {
                        "welle": r.welle,
                        "severity": record.get("severity", "caution"),
                        "detail": record.get("detail", ""),
                    }
                )

        family_verdict = DRIFT_FAMILY_GREEN
        if any(f.get("severity") == "blocker" for f in failed_in):
            family_verdict = DRIFT_FAMILY_RED
        elif failed_in:
            family_verdict = DRIFT_FAMILY_AMBER

        drift["families"][fam] = {
            "passed_in": passed_in,
            "failed_in": failed_in,
            "skipped_in": skipped_in,
            "family_verdict": family_verdict,
        }
        overall_verdict = _worst_family_verdict(overall_verdict, family_verdict)

    drift["overall_drift_verdict"] = overall_verdict
    return drift


def _is_family_applicable(family: str, welle: int) -> bool:
    """Is `family` expected to appear in welle-N's envelope?"""
    if family in ASSERT_FAMILIES_SHARED:
        return True
    if family == _family_a6_for_welle(welle):
        return True
    if family == _family_a7_for_welle(welle):
        return True
    return False


def _worst_family_verdict(current: str, candidate: str) -> str:
    """Combine two family-verdicts; RED beats AMBER beats GREEN."""
    rank = {DRIFT_FAMILY_GREEN: 0, DRIFT_FAMILY_AMBER: 1, DRIFT_FAMILY_RED: 2}
    return current if rank[current] >= rank[candidate] else candidate


# ---------------------------------------------------------------------------
# Marathon-Envelope construction.
# ---------------------------------------------------------------------------


def build_marathon_envelope(
    *,
    plan: Sequence[SubSequence],
    results: Sequence[SmokeResult],
    marathon_exit: int,
    drift: Dict[str, Any],
    now_ts: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Build the operator-facing Marathon-Envelope JSON."""
    timestamp = int(now_ts if now_ts is not None else time.time())
    envelope: Dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "timestamp_utc": timestamp,
        "dry_run": dry_run,
        "plan": [
            {
                "kw_label": sub.kw_label,
                "welles": list(sub.welles),
                "mode": sub.mode,
            }
            for sub in plan
        ],
        "welle_results": [
            {
                "welle": r.welle,
                "focus_component": WELLE_FOCUS_COMPONENT.get(r.welle, "?"),
                "exit_code": r.exit_code,
                "band": r.band,
                "envelope_path": str(r.envelope_path) if r.envelope_path else None,
                "asserts_summary": _summarise_asserts(r.envelope.get("asserts") or {}),
                "error": r.envelope.get("error"),
            }
            for r in sorted(results, key=lambda x: x.welle)
        ],
        "marathon_exit_code": marathon_exit,
        "marathon_band": BAND_FOR_EXIT.get(marathon_exit, BAND_UNKNOWN),
        "cross_welle_drift": drift,
    }
    return envelope


def _summarise_asserts(asserts: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact per-welle assert summary for the marathon envelope."""
    passed = sorted(k for k, v in asserts.items() if v.get("passed"))
    failed = sorted(k for k, v in asserts.items() if not v.get("passed"))
    return {
        "total": len(asserts),
        "passed": passed,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Orchestrator entry-point.
# ---------------------------------------------------------------------------


def run_generalprobe(
    *,
    from_welle: int = 1,
    up_to_welle: int = 7,
    out_dir: Optional[Path] = None,
    smoke_args: Sequence[str] = (),
    parallel: bool = True,
    smoke_runner: Optional[SmokeRunner] = None,
    env: Optional[Mapping[str, str]] = None,
    now_ts: Optional[int] = None,
    dry_run: bool = False,
) -> Tuple[Dict[str, Any], int]:
    """Top-level orchestrator. Returns (marathon_envelope, exit_code).

    The seam parameters (``smoke_runner``, ``env``, ``now_ts``) keep
    the orchestrator hermetically testable: the test suite injects a
    deterministic ``smoke_runner`` that returns canned SmokeResults
    without spawning real subprocesses.
    """
    plan = filter_plan(PLAN, from_welle=from_welle, up_to_welle=up_to_welle)

    if dry_run:
        envelope = build_marathon_envelope(
            plan=plan,
            results=(),
            marathon_exit=EXIT_GREEN,
            drift={"families": {}, "welles_dispatched": [], "overall_drift_verdict": DRIFT_FAMILY_GREEN},
            now_ts=now_ts,
            dry_run=True,
        )
        return envelope, EXIT_GREEN

    runner = smoke_runner if smoke_runner is not None else default_smoke_runner
    base_env = _build_base_env(env)
    out_dir_resolved = out_dir if out_dir is not None else _default_out_dir(
        base_env, now_ts=now_ts
    )

    all_results: List[SmokeResult] = []
    for sub in plan:
        results = _dispatch_sub_sequence(
            sub,
            runner=runner,
            out_dir=out_dir_resolved,
            smoke_args=smoke_args,
            env=base_env,
            parallel=parallel,
        )
        all_results.extend(results)
        # Short-circuit on ROLLBACK: an earlier wave's blocker fail
        # makes the next wave's evidence operator-irrelevant for the
        # cutover-go/no-go gate. Continuing would just waste time.
        if any(r.exit_code == EXIT_ROLLBACK for r in results):
            break

    marathon_exit = aggregate_exit(all_results)
    drift = aggregate_drift(all_results)
    envelope = build_marathon_envelope(
        plan=plan,
        results=all_results,
        marathon_exit=marathon_exit,
        drift=drift,
        now_ts=now_ts,
        dry_run=False,
    )
    return envelope, marathon_exit


def _dispatch_sub_sequence(
    sub: SubSequence,
    *,
    runner: SmokeRunner,
    out_dir: Path,
    smoke_args: Sequence[str],
    env: Mapping[str, str],
    parallel: bool,
) -> List[SmokeResult]:
    """Dispatch the welles of one sub-sequence. Parallel if `mode==parallel`."""
    welles = list(sub.welles)
    if not welles:
        return []
    if sub.mode == "parallel" and parallel and len(welles) > 1:
        with ThreadPoolExecutor(max_workers=len(welles)) as ex:
            futures: Dict[Future, int] = {}
            for w in welles:
                out_path = out_dir / f"welle-{w}-envelope.json"
                fut = ex.submit(runner, w, out_path, smoke_args, env)
                futures[fut] = w
            results: List[SmokeResult] = []
            for fut in futures:
                results.append(fut.result())
        # Preserve welle order in the output regardless of completion order.
        return sorted(results, key=lambda r: r.welle)
    # Solo or forced-sequential.
    results = []
    for w in welles:
        out_path = out_dir / f"welle-{w}-envelope.json"
        results.append(runner(w, out_path, smoke_args, env))
    return results


def _build_base_env(env: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """Build the env-map handed to each smoke subprocess."""
    source = dict(env) if env is not None else dict(os.environ)
    repo_root = _repo_root_from_env(source)
    # Prepend repo-root to PYTHONPATH so the smoke can import
    # wirelang.persona_engine.rust_backend_switch from the same
    # checkout.
    py_path = source.get("PYTHONPATH", "")
    repo_str = str(repo_root)
    if repo_str not in py_path.split(os.pathsep):
        source["PYTHONPATH"] = (
            f"{repo_str}{os.pathsep}{py_path}" if py_path else repo_str
        )
    return source


def _default_out_dir(env: Mapping[str, str], *, now_ts: Optional[int]) -> Path:
    """Default per-run output directory under out/cross-welle-generalprobe/."""
    repo_root = _repo_root_from_env(env)
    ts = int(now_ts if now_ts is not None else time.time())
    return repo_root / "out" / "cross-welle-generalprobe" / str(ts)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cross-welle-cutover-generalprobe",
        description=(
            "Phase-3c marathon dress-rehearsal. Runs all seven "
            "Welle-N cutover-smokes in ADR-0066 calendar order "
            "(KW-24..KW-27), aggregates exit codes + A1..A7 asserts "
            "into a Marathon-Verdict, and exits "
            "0/1/2 = GREEN/CAUTION/ROLLBACK_RECOMMENDED. Never "
            "invokes the real Rust binary, NATS, or the Anthropic "
            "API. License: Apache-2.0."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the ADR-0066 sub-sequence plan without invoking "
            "any welle-smoke. Exits 0."
        ),
    )
    p.add_argument(
        "--from-welle",
        type=int,
        default=1,
        help="First welle to run (1..7, default 1).",
    )
    p.add_argument(
        "--up-to-welle",
        type=int,
        default=7,
        help="Last welle to run (1..7, default 7).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "Directory for per-welle envelope JSON files. "
            "Default: out/cross-welle-generalprobe/<unix-ts>/."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output file for the Marathon-Envelope. "
            "Default: write to stdout."
        ),
    )
    p.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        dest="smoke_args",
        metavar="ARG",
        help=(
            "Extra argument passed to every welle-smoke subprocess. "
            "Repeatable. Example: --smoke-arg --boots-per-phase=2"
        ),
    )
    p.add_argument(
        "--sequential",
        action="store_true",
        help=(
            "Force sequential welle execution even within parallel "
            "sub-sequences. Useful for debugging stderr interleave."
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
    smoke_runner: Optional[SmokeRunner] = None,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_argparser().parse_args(argv)

    if not (1 <= args.from_welle <= 7):
        err.write(
            f"cross-welle-generalprobe: --from-welle must be in [1,7]; "
            f"got {args.from_welle!r}\n"
        )
        return EXIT_ROLLBACK
    if not (1 <= args.up_to_welle <= 7):
        err.write(
            f"cross-welle-generalprobe: --up-to-welle must be in [1,7]; "
            f"got {args.up_to_welle!r}\n"
        )
        return EXIT_ROLLBACK
    if args.from_welle > args.up_to_welle:
        err.write(
            f"cross-welle-generalprobe: --from-welle ({args.from_welle}) "
            f"must be <= --up-to-welle ({args.up_to_welle})\n"
        )
        return EXIT_ROLLBACK

    envelope, exit_code = run_generalprobe(
        from_welle=args.from_welle,
        up_to_welle=args.up_to_welle,
        out_dir=args.out_dir,
        smoke_args=tuple(args.smoke_args),
        parallel=not args.sequential,
        smoke_runner=smoke_runner,
        env=env,
        now_ts=args.now,
        dry_run=args.dry_run,
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
            f"cross-welle-generalprobe: cannot write output "
            f"{args.output!r}: {exc}\n"
        )
        return EXIT_ROLLBACK

    return exit_code


__all__ = [
    "ASSERT_FAMILIES_SHARED",
    "BAND_CAUTION",
    "BAND_FOR_EXIT",
    "BAND_GREEN",
    "BAND_ROLLBACK",
    "BAND_UNKNOWN",
    "DRIFT_FAMILY_AMBER",
    "DRIFT_FAMILY_GREEN",
    "DRIFT_FAMILY_RED",
    "ENVELOPE_SCHEMA",
    "EXIT_CAUTION",
    "EXIT_GREEN",
    "EXIT_ROLLBACK",
    "PLAN",
    "SmokeResult",
    "SubSequence",
    "WELLE_FOCUS_COMPONENT",
    "WELLE_SMOKE_PATHS",
    "aggregate_drift",
    "aggregate_exit",
    "build_argparser",
    "build_marathon_envelope",
    "default_smoke_runner",
    "expected_assert_families",
    "filter_plan",
    "main",
    "run_generalprobe",
]


if __name__ == "__main__":
    sys.exit(main())
