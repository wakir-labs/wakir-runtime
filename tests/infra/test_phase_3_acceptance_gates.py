# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3-Validation Acceptance-Gate skeleton (Sprint-Phase-3-Validation-
Test-Suite-Skeleton-MINI).

Anchors
-------

- ADR-0058 §"Phase 3 — Validation (Wochen 5-6)" and §"Phase 4 Cutover-
  Entscheidung" — the production-promotion lifecycle and the four-axis
  stress-test-drill matrix.
- ADR-0063 §"Phase 3 — Rust-Engine-Cutover" — the 15/15 Cross-Lang-Parität
  acceptance criterion for the Rust-engine cutover (Python ⇆ Rust
  byte-identical envelope parity on the canonical replay-tape vector
  set).
- ``docs/quality-gates/phase-3-production.md`` (Amara, PR #80) — the
  five Phase-3-Acceptance-Gates QA enforces before Aufsichtsrat-
  approval of cutover.
- ``docs/quality-gates/phase-3-production-trigger-checklist.md``
  (Amara, this PR) — the 10-item pre-trigger checklist that gates
  the Sprint-Phase-3-Validation-Test-Suite spawn.
- Sprint-Phase-2-Gates-Mini (Amara, PR #80) + Sprint-Phase-2-Gates-
  Recovery-Mock-Mini (Amara, PR #127) — the Phase-2 acceptance
  reference these skeletons inherit from.

Scope
-----

ONE skeleton-test per Phase-3-Acceptance-Gate as named in the
Sprint-Phase-3-Validation-Test-Suite-Skeleton-MINI brief, plus one
aggregator that walks all five back-to-back. All tests are
**skip-by-default** via the ``phase_3_skeleton`` marker — they fire
only when ``WAKIR_PHASE_3_SKELETON=1`` is set in the environment,
which is the opt-in switch the Phase-3-trigger sprint (~KW 27) will
flip to validate the full skeleton before Aufsichtsrat-decision.

The skeletons here are **hermetic placeholder oracles**: each one
captures the *contract surface* the live-acceptance gate will assert,
using deterministic in-memory mocks. The Phase-3-trigger sprint will
either (a) replace the mock-substrate with the real
wakir.persona_engine.rust_bridge / OTS / hash-chain hooks, or (b) keep
the mock-substrate as the hermetic-side check and add Operator-Hand
live-VM drills as the complementary lane (see
``feedback_live_bringup_sandbox_gap.md``).

Skip-by-default rationale
-------------------------

Phase-3 is ~KW 27 — six weeks out by stable schedule. Running the
skeletons green-by-construction in CI today would (i) waste signal
(the assertions are placeholder-shaped, not production-binding), and
(ii) risk false-positive confidence ("Phase-3 gates pass" without the
underlying substrate). Skip-by-default keeps the skeletons compilable
and import-correct (so refactors of the diff-engine, audit-writer,
etc. surface here as ImportErrors at collect-time) without claiming
green-light status on Phase-3 itself. The opt-in env-var matches the
``WAT_NETWORK_TESTS=1`` convention used elsewhere in ``tests/wat/``.

Gate naming
-----------

The brief's gate labels map onto the Amara-spec Phase-3-Acceptance-
Gates (``docs/quality-gates/phase-3-production.md`` §1) as follows:

* **Gate-3-1 Rust-Engine-Cutover-Acceptance (15/15)** ⇔ ADR-0063
  Phase-3 §"Cutover" — Python ⇆ Rust byte-identical envelope parity
  on 15 canonical replay-tape inputs. The 15/15 verdict is a
  hard-gate (any single failing vector blocks promotion).
* **Gate-3-2 Rollback-Drill ≤ 15min** ⇔ phase-3-production.md §3.2
  (Rollback-runbook drill cleared, measured rollback-time ≤ 15min
  against a Pilot-VM in the 30 days preceding cutover).
* **Gate-3-3 OTS-End-to-End-Latency p99** ⇔ phase-3-production.md
  §3.3 (V-907 / OTS audit-trail end-to-end, with an end-to-end-
  latency SLO on the publish → OTS-anchor-attest closure path).
* **Gate-3-4 28d-no-regression** ⇔ phase-3-production.md §3.5 (no
  regressions vs. Phase-2 baseline for first 28 days post-cutover —
  output-quality + substrate-stability).
* **Gate-3-5 Cross-Phase-Invarianten Hash-Chain** ⇔ phase-3-production
  .md §5 (cross-phase invariants — the no-regret-test-evidence rule
  and the V-907 pin-attest-mandatory invariant, encoded as a
  hash-chain over the per-phase quality-gate manifests so any
  retroactive edit surfaces as a chain-break).

Sandbox boundary
----------------

Hermetic-only. No podman, no NATS, no live VM, no OTS-calendar I/O
(see ``feedback_sandbox_host_trennung.md``). The live-VM-acceptance
gate, the real rollback drill, and the real OTS-anchor-cycle remain
Operator-Hand-lane responsibilities. These skeletons are the
test-time *oracle* the live drills compare against.

Vermutungs-Kennzeichnung (P2)
-----------------------------

The exact thresholds below (OTS end-to-end p99 = 60s, rollback budget
= 15min, 28-day-window) are sourced from ``phase-3-production.md`` §3
and ADR-0058. They are production-target placeholders pending Noa-
design-review (gate §5.3 in ``phase-2-doppelbetrieb.md``). The
skeleton uses them as *assertion-shape* anchors, not as Aufsichtsrat-
binding numbers.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
from dataclasses import dataclass, field
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Skip-by-default gate.
# ---------------------------------------------------------------------------

# All tests in this module carry the ``phase_3_skeleton`` marker so CI
# selectors can target / exclude the skeleton in isolation, AND a
# module-level skipif on the opt-in env-var. The two together give us:
#  - module-level fast-skip in default CI (skipif fires at collect-time);
#  - marker-based selection for the Phase-3-trigger sprint
#    (`pytest -m phase_3_skeleton tests/infra/test_phase_3_acceptance_gates.py`).
PHASE_3_OPT_IN = os.environ.get("WAKIR_PHASE_3_SKELETON") == "1"

pytestmark = [
    pytest.mark.phase_3_skeleton,
    pytest.mark.skipif(
        not PHASE_3_OPT_IN,
        reason=(
            "Phase-3-skeleton skip-by-default — opt in with "
            "WAKIR_PHASE_3_SKELETON=1 (Phase-3-trigger sprint ~KW 27 "
            "flips this gate)."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Shared constants — sourced from phase-3-production.md §3.
# ---------------------------------------------------------------------------

# ADR-0063 Phase-3 cutover criterion: 15/15 byte-identical envelope
# parity over the canonical replay-tape vector set.
RUST_CUTOVER_REQUIRED_PARITY = 15
RUST_CUTOVER_TOTAL_VECTORS = 15

# phase-3-production.md §3.2 — rollback runbook drill budget.
ROLLBACK_BUDGET_SECONDS = 15 * 60  # 15 minutes.

# phase-3-production.md §3.3 — OTS audit-trail end-to-end latency.
# Placeholder pending Noa-design-review (see P2 note above).
OTS_END_TO_END_LATENCY_P99_S = 60.0

# phase-3-production.md §3.5 — 28-day post-cutover stability window
# and the Phase-2 baseline functional-equivalence threshold.
POST_CUTOVER_STABILITY_WINDOW_DAYS = 28
PHASE_2_BASELINE_FUNCTIONAL_EQUIVALENCE = 0.95

# phase-3-production.md §5 — cross-phase invariants are encoded as a
# hash-chain over the per-phase quality-gate manifest digests.
PHASE_MANIFEST_DIGEST_PREFIX = "sha256:"


# ---------------------------------------------------------------------------
# Gate-3-1: Rust-Engine-Cutover-Acceptance (15/15 Cross-Lang-Parität).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayTapeVector:
    """One canonical replay-tape input for the Python ⇆ Rust parity check.

    The vector-id mirrors the planned ADR-0063 replay-tape naming
    (`rt-001` … `rt-015`); the payload is opaque bytes carried through
    both implementations end-to-end. The Phase-3-trigger sprint will
    replace the placeholder payloads with the canonical replay-tape
    corpus that Reza + Selin have agreed-upon as the Cross-Lang
    acceptance set.
    """

    vector_id: str
    payload: bytes
    expected_envelope_sha256: str


def _placeholder_replay_tape_corpus() -> list[ReplayTapeVector]:
    """Build a 15-element placeholder corpus.

    Each vector carries a deterministic payload and the sha256 of that
    payload as the expected-envelope-hash. The Phase-3-trigger sprint
    will replace this with the real replay-tape corpus + the real
    envelope-hash oracle (derived from the canonical Python engine).
    """
    out: list[ReplayTapeVector] = []
    for i in range(RUST_CUTOVER_TOTAL_VECTORS):
        payload = f"rt-{i:03d}-payload".encode("utf-8")
        out.append(
            ReplayTapeVector(
                vector_id=f"rt-{i:03d}",
                payload=payload,
                expected_envelope_sha256=PHASE_MANIFEST_DIGEST_PREFIX
                + hashlib.sha256(payload).hexdigest(),
            )
        )
    return out


def _mock_python_engine(vector: ReplayTapeVector) -> str:
    """Mock-python-engine — returns the expected envelope-hash by
    construction. Placeholder for the real Python persona-engine
    invocation the Phase-3-trigger sprint will wire up."""
    return vector.expected_envelope_sha256


def _mock_rust_engine(vector: ReplayTapeVector) -> str:
    """Mock-rust-engine — returns the same envelope-hash as the mock-
    python-engine (parity-by-construction). Placeholder for the real
    wakir.persona_engine.rust_bridge invocation."""
    return vector.expected_envelope_sha256


def test_gate_3_1_rust_engine_cutover_acceptance_15_of_15():
    """ADR-0063 Phase-3 cutover gate: Python ⇆ Rust envelope-hash parity
    on all 15 canonical replay-tape vectors.

    Hermetic placeholder. The Phase-3-trigger sprint will replace
    ``_mock_python_engine`` / ``_mock_rust_engine`` with real engine
    invocations against the canonical corpus and flip ``parity_required``
    to the production-binding 15.
    """
    corpus = _placeholder_replay_tape_corpus()
    assert len(corpus) == RUST_CUTOVER_TOTAL_VECTORS, (
        f"replay-tape corpus must contain exactly "
        f"{RUST_CUTOVER_TOTAL_VECTORS} vectors; got {len(corpus)}"
    )

    parity_count = 0
    failing_vectors: list[str] = []
    for vector in corpus:
        py_hash = _mock_python_engine(vector)
        rs_hash = _mock_rust_engine(vector)
        if py_hash == rs_hash == vector.expected_envelope_sha256:
            parity_count += 1
        else:
            failing_vectors.append(vector.vector_id)

    assert parity_count == RUST_CUTOVER_REQUIRED_PARITY, (
        f"Rust-engine cutover requires {RUST_CUTOVER_REQUIRED_PARITY}/"
        f"{RUST_CUTOVER_TOTAL_VECTORS} parity; got {parity_count} with "
        f"failing vectors {failing_vectors}"
    )

    # Failure-mode anchor: a single drifting Rust output MUST fail the
    # gate. We construct the failure case in-line to verify the
    # assertion-shape (not just the happy path).
    def _drifting_rust_engine(vector: ReplayTapeVector) -> str:
        if vector.vector_id == "rt-007":
            return PHASE_MANIFEST_DIGEST_PREFIX + ("f" * 64)
        return vector.expected_envelope_sha256

    drift_parity = sum(
        1
        for v in corpus
        if _mock_python_engine(v) == _drifting_rust_engine(v)
    )
    assert drift_parity < RUST_CUTOVER_REQUIRED_PARITY, (
        "gate must reject any replay-tape vector with Python ⇆ Rust "
        f"envelope-hash drift (got drift_parity={drift_parity})"
    )


# ---------------------------------------------------------------------------
# Gate-3-2: Rollback-Drill ≤ 15min.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RollbackDrillRecord:
    """One execution of the Phase-2 → Phase-3 emergency-rollback runbook.

    The drill-record mirrors the runbook-drill report Noa + Aisha sign
    off on (phase-3-production.md §3.2). The hermetic mock encodes the
    *shape* of the record; the Phase-3-trigger sprint replaces this
    with the actual signed-off report load.
    """

    drill_id: str
    ts_utc: str
    elapsed_seconds: float
    operator: str
    moderator: str
    outcome: str  # "pass" | "fail"


def _mock_recent_rollback_drill() -> RollbackDrillRecord:
    """A hermetic mock of a recent rollback drill — within budget."""
    return RollbackDrillRecord(
        drill_id="rollback-drill-2026-W26-001",
        ts_utc="2026-06-30T10:00:00Z",
        elapsed_seconds=11.5 * 60,
        operator="noa",
        moderator="aisha",
        outcome="pass",
    )


def test_gate_3_2_rollback_drill_under_15min():
    """phase-3-production.md §3.2: rollback-drill ≤ 15min, within 30
    days preceding cutover.

    Hermetic placeholder for the runbook-drill-report ingest. The
    Phase-3-trigger sprint will replace ``_mock_recent_rollback_drill``
    with a loader that reads the signed-off drill-record from the
    governance-artefacts path.
    """
    drill = _mock_recent_rollback_drill()

    assert drill.outcome == "pass", (
        f"rollback-drill outcome must be 'pass'; got {drill.outcome!r}"
    )
    assert drill.elapsed_seconds <= ROLLBACK_BUDGET_SECONDS, (
        f"rollback-drill elapsed {drill.elapsed_seconds:.1f}s exceeds "
        f"§3.2 budget {ROLLBACK_BUDGET_SECONDS}s"
    )

    # Sign-off invariant: both operator (Noa) and moderator (Aisha)
    # MUST be present for the drill-record to count.
    assert drill.operator, "rollback-drill requires a named operator"
    assert drill.moderator, "rollback-drill requires a named moderator"

    # Failure-mode anchor: a drill that exceeds the 15min budget must
    # be rejected even if outcome=="pass". The runbook explicitly
    # distinguishes "completed eventually" from "completed in budget".
    over_budget = RollbackDrillRecord(
        drill_id="rollback-drill-overrun",
        ts_utc="2026-06-15T08:00:00Z",
        elapsed_seconds=18 * 60,
        operator="noa",
        moderator="aisha",
        outcome="pass",
    )
    assert over_budget.elapsed_seconds > ROLLBACK_BUDGET_SECONDS, (
        "gate must reject rollback drills that exceed the 15min budget"
    )


# ---------------------------------------------------------------------------
# Gate-3-3: OTS-End-to-End-Latency p99.
# ---------------------------------------------------------------------------


def _mock_ots_end_to_end_latency_histogram() -> list[float]:
    """Return a 200-sample latency histogram (seconds) for the publish →
    OTS-anchor-attest end-to-end path.

    The distribution is modelled on the Bitcoin-confirmation-bounded
    case: most attestations complete in a single block-cycle (~10-30s
    in normal conditions), with a tail bounded by the OTS-calendar
    multi-calendar-failover retry budget.
    """
    samples: list[float] = []
    # 95% of samples in [10, 35] seconds (normal Bitcoin block-cycle).
    samples.extend(10.0 + (i * 0.13) for i in range(190))
    # 5% of samples in [40, 58] seconds (calendar-failover retry path).
    samples.extend(40.0 + (i * 2.0) for i in range(10))
    return samples


def _p99(samples: list[float]) -> float:
    """Compute p99 from a sample window via inclusive-quantile rank.

    Mirrors the helper in ``test_phase_2_acceptance_gates.py`` —
    kept local to keep the skeleton self-contained.
    """
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, int(round(0.99 * (len(ordered) - 1))))
    return ordered[idx]


def test_gate_3_3_ots_end_to_end_latency_p99():
    """phase-3-production.md §3.3: V-907 / OTS audit-trail end-to-end
    latency p99 ≤ ``OTS_END_TO_END_LATENCY_P99_S``.

    Hermetic placeholder. The Phase-3-trigger sprint will replace the
    mock-histogram with a loader that reads the OTS reconciliation-
    report's latency-rollup column.
    """
    samples = _mock_ots_end_to_end_latency_histogram()
    assert len(samples) == 200

    p99 = _p99(samples)
    assert p99 <= OTS_END_TO_END_LATENCY_P99_S, (
        f"OTS end-to-end p99 {p99:.2f}s exceeds §3.3 SLO "
        f"{OTS_END_TO_END_LATENCY_P99_S}s"
    )

    # Sanity: median is well under p99 (right-skewed Bitcoin-block
    # distribution).
    median = statistics.median(samples)
    assert median < p99, (
        f"distribution must be right-skewed (median {median:.2f}s < "
        f"p99 {p99:.2f}s)"
    )

    # Failure-mode anchor: an injected 120s excursion (e.g. both OTS
    # calendars down) MUST push p99 over SLO.
    bad_samples = samples + [120.0] * 5
    bad_p99 = _p99(bad_samples)
    assert bad_p99 > OTS_END_TO_END_LATENCY_P99_S, (
        f"injected 120s excursion must drive p99 ({bad_p99:.2f}s) over "
        f"§3.3 SLO {OTS_END_TO_END_LATENCY_P99_S}s"
    )


# ---------------------------------------------------------------------------
# Gate-3-4: 28d-no-regression.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyStabilityRecord:
    """One day's rollup of the post-cutover stability metrics.

    Mirrors the daily-aggregate row the post-cutover 28-day stability
    report (phase-3-production.md §3.5 + Henrik Audit-Punkt J) emits:
    functional-equivalence score vs. Phase-2 baseline, plus any SLO
    excursion count.
    """

    day_index: int
    functional_equivalence_score: float
    slo_excursion_count: int


def _mock_post_cutover_28_day_window() -> list[DailyStabilityRecord]:
    """Build a 28-element placeholder daily-rollup window.

    All days clear the §3.5 thresholds by construction. The Phase-3-
    trigger sprint replaces this with a loader that reads the actual
    weekly Doppelbetrieb-rollup + Noa SLO-rollup over the post-cutover
    28-day window.
    """
    return [
        DailyStabilityRecord(
            day_index=d,
            functional_equivalence_score=0.97 + (d % 3) * 0.005,
            slo_excursion_count=0,
        )
        for d in range(POST_CUTOVER_STABILITY_WINDOW_DAYS)
    ]


def test_gate_3_4_28d_no_regression():
    """phase-3-production.md §3.5: no regressions vs. Phase-2 baseline
    for first 28 days post-cutover.

    Hermetic placeholder. Two contract surfaces:
      1. Every day in the 28-day window has functional-equivalence
         ≥ 0.95 vs. Phase-2 baseline.
      2. Zero SLO excursions over the 28-day window.
    """
    window = _mock_post_cutover_28_day_window()
    assert len(window) == POST_CUTOVER_STABILITY_WINDOW_DAYS, (
        f"stability window must be exactly "
        f"{POST_CUTOVER_STABILITY_WINDOW_DAYS} days; got {len(window)}"
    )

    # Contract 1: every day clears the Phase-2 baseline.
    failing_days = [
        d
        for d in window
        if d.functional_equivalence_score
        < PHASE_2_BASELINE_FUNCTIONAL_EQUIVALENCE
    ]
    assert not failing_days, (
        f"days below Phase-2 baseline "
        f"({PHASE_2_BASELINE_FUNCTIONAL_EQUIVALENCE}): "
        f"{[d.day_index for d in failing_days]}"
    )

    # Contract 2: zero SLO excursions.
    total_excursions = sum(d.slo_excursion_count for d in window)
    assert total_excursions == 0, (
        f"zero-SLO-excursion invariant broken: {total_excursions} "
        f"excursions in 28-day window"
    )

    # Failure-mode anchor: a single day at 0.90 functional-equivalence
    # MUST fail the gate (the §3.5 contract is not a mean-over-window
    # threshold, it is a per-day floor).
    regressed_window = list(window)
    regressed_window[10] = DailyStabilityRecord(
        day_index=10,
        functional_equivalence_score=0.90,
        slo_excursion_count=0,
    )
    failing_after_inject = [
        d
        for d in regressed_window
        if d.functional_equivalence_score
        < PHASE_2_BASELINE_FUNCTIONAL_EQUIVALENCE
    ]
    assert failing_after_inject, (
        "gate must reject any day below the 0.95 baseline, even if "
        "the window-mean clears threshold"
    )


# ---------------------------------------------------------------------------
# Gate-3-5: Cross-Phase-Invarianten Hash-Chain.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseManifestRecord:
    """One phase's quality-gate-manifest digest entry in the hash-chain.

    The hash-chain encodes phase-3-production.md §5's cross-phase
    invariants: each phase's quality-gate manifest is digested, and
    each manifest digest is chained to the previous via
    ``next_digest = sha256(prev_digest || curr_manifest_digest)``.
    Any retroactive edit to a Phase-1b or Phase-2 manifest surfaces
    here as a chain-break.
    """

    phase_label: str  # "phase-1b" | "phase-2" | "phase-3"
    manifest_digest: str
    chain_digest: str


def _digest(text: str) -> str:
    return PHASE_MANIFEST_DIGEST_PREFIX + hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def _mock_phase_manifest_chain() -> list[PhaseManifestRecord]:
    """Build a 3-element placeholder phase-manifest chain.

    Each entry's chain_digest is computed via the chaining rule above.
    The Phase-3-trigger sprint will replace ``_digest`` calls with
    actual manifest-file content digests.
    """
    phase_1b_manifest = _digest("phase-1b-pilot.md@frozen-2026-05-09")
    phase_2_manifest = _digest("phase-2-doppelbetrieb.md@frozen-2026-05-16")
    phase_3_manifest = _digest("phase-3-production.md@draft-2026-05-16")

    # Genesis: chain_digest_0 = sha256(phase_1b_manifest).
    chain_1b = _digest(phase_1b_manifest)
    chain_2 = _digest(chain_1b + phase_2_manifest)
    chain_3 = _digest(chain_2 + phase_3_manifest)

    return [
        PhaseManifestRecord(
            phase_label="phase-1b",
            manifest_digest=phase_1b_manifest,
            chain_digest=chain_1b,
        ),
        PhaseManifestRecord(
            phase_label="phase-2",
            manifest_digest=phase_2_manifest,
            chain_digest=chain_2,
        ),
        PhaseManifestRecord(
            phase_label="phase-3",
            manifest_digest=phase_3_manifest,
            chain_digest=chain_3,
        ),
    ]


def _verify_chain(chain: list[PhaseManifestRecord]) -> bool:
    """Recompute the chain digests and check link-integrity.

    Returns True iff every chain_digest matches the recomputed value.
    Encodes the verifier the Phase-3-trigger sprint will harden into
    the Henrik-Audit-Sample ingest path.
    """
    if not chain:
        return True
    expected_prev = _digest(chain[0].manifest_digest)
    if chain[0].chain_digest != expected_prev:
        return False
    for prev, curr in zip(chain, chain[1:]):
        expected = _digest(prev.chain_digest + curr.manifest_digest)
        if curr.chain_digest != expected:
            return False
    return True


def test_gate_3_5_cross_phase_invariants_hash_chain():
    """phase-3-production.md §5: cross-phase invariants encoded as a
    hash-chain over per-phase quality-gate manifests.

    The chain must:
      1. Cover all three phases (phase-1b, phase-2, phase-3) in order.
      2. Be link-consistent (each chain_digest matches the chaining
         rule applied to the previous link).
      3. Detect retroactive edits to any prior phase's manifest.
    """
    chain = _mock_phase_manifest_chain()

    # Contract 1: ordered three-phase coverage.
    assert [r.phase_label for r in chain] == [
        "phase-1b",
        "phase-2",
        "phase-3",
    ], (
        "hash-chain must cover phase-1b, phase-2, phase-3 in that "
        f"order; got {[r.phase_label for r in chain]}"
    )

    # Contract 2: link integrity.
    assert _verify_chain(chain), (
        "phase-manifest hash-chain failed link-integrity verification"
    )

    # Contract 3: retroactive-edit detection. Mutating the Phase-1b
    # manifest digest MUST break the chain even if Phase-2 / Phase-3
    # chain digests are left untouched.
    tampered = list(chain)
    tampered[0] = PhaseManifestRecord(
        phase_label="phase-1b",
        manifest_digest=_digest("phase-1b-pilot.md@TAMPERED"),
        chain_digest=tampered[0].chain_digest,
    )
    assert not _verify_chain(tampered), (
        "gate must detect retroactive edits to prior-phase manifests "
        "even when the chain_digest field is left at its old value"
    )


# ---------------------------------------------------------------------------
# Aggregator: all five Phase-3 gates back-to-back.
# ---------------------------------------------------------------------------


def test_gate_aggregator_phase_3_validation_all_green():
    """Aggregate verdict: all five Phase-3-Acceptance-Gates green over a
    single hermetic mock-run.

    Mirrors the Phase-2-aggregator pattern in
    ``test_phase_2_acceptance_gates.py``: surfaces cross-gate
    interactions (e.g. a hash-chain break on Gate-3-5 SHOULD NOT
    silently flip the Rust-parity verdict on Gate-3-1) and emits a
    JSON-serialisable verdict-map for Henrik's Audit-Sample ingest
    (phase-3-production.md §4 Audit-Punkt J + K).
    """
    verdicts: dict[str, bool] = {}

    # Gate-3-1: Rust-engine cutover parity.
    corpus = _placeholder_replay_tape_corpus()
    parity = sum(
        1
        for v in corpus
        if _mock_python_engine(v) == _mock_rust_engine(v)
    )
    verdicts["gate-3-1-rust-parity"] = parity == RUST_CUTOVER_REQUIRED_PARITY

    # Gate-3-2: Rollback-drill in-budget.
    drill = _mock_recent_rollback_drill()
    verdicts["gate-3-2-rollback-15min"] = (
        drill.outcome == "pass"
        and drill.elapsed_seconds <= ROLLBACK_BUDGET_SECONDS
    )

    # Gate-3-3: OTS end-to-end p99 under SLO.
    samples = _mock_ots_end_to_end_latency_histogram()
    verdicts["gate-3-3-ots-p99"] = _p99(samples) <= OTS_END_TO_END_LATENCY_P99_S

    # Gate-3-4: 28-day no-regression.
    window = _mock_post_cutover_28_day_window()
    verdicts["gate-3-4-28d-no-regression"] = (
        all(
            d.functional_equivalence_score
            >= PHASE_2_BASELINE_FUNCTIONAL_EQUIVALENCE
            for d in window
        )
        and sum(d.slo_excursion_count for d in window) == 0
    )

    # Gate-3-5: Cross-phase invariants hash-chain.
    chain = _mock_phase_manifest_chain()
    verdicts["gate-3-5-hash-chain"] = _verify_chain(chain)

    # All five gates MUST be green for Phase-3 promotion.
    assert all(verdicts.values()), (
        f"aggregator verdict: not all Phase-3 gates green {verdicts}"
    )
    assert set(verdicts.keys()) == {
        "gate-3-1-rust-parity",
        "gate-3-2-rollback-15min",
        "gate-3-3-ots-p99",
        "gate-3-4-28d-no-regression",
        "gate-3-5-hash-chain",
    }, "aggregator must touch all five Phase-3 gates"

    # Cross-gate non-interference invariant: a hash-chain break on
    # Gate-3-5 MUST NOT silently flip the Rust-parity verdict on
    # Gate-3-1 (the verdicts are computed from independent substrates;
    # this assertion documents that the independence is structural,
    # not coincidental).
    assert verdicts["gate-3-1-rust-parity"] is True
    assert verdicts["gate-3-5-hash-chain"] is True

    # Audit-friendly rollup: deterministic JSON-serialisable verdict-
    # map for Henrik Audit-Punkt J + K ingest.
    rollup = json.dumps(verdicts, sort_keys=True)
    assert "gate-3-1-rust-parity" in rollup
    assert rollup == json.dumps(verdicts, sort_keys=True), (
        "rollup serialisation must be deterministic"
    )
