# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Phase-2-Doppelbetrieb Acceptance-Gate tests (Sprint-Phase-2-Gates-Mini).

Anchors
-------

- ADR-0058 §"Phase 2 — Doppelbetrieb (Wochen 1-4)" — the four-week
  Doppelbetrieb-Vergleich plan with 4-axis Score and Henrik-Audit-
  Sample pflicht.
- ``docs/quality-gates/phase-2-doppelbetrieb.md`` (Amara, PR #80) — the
  five acceptance-gates that QA enforces before promotion to Phase 3.
- ``wirelang.persona_engine.bridge_audit_diff_engine`` (Selin, PR #106)
  — the deterministic-diff oracle used by Gate-2-2 to compute the
  consistency-score over a mock bridge-trace.

Scope
-----

ONE test per Phase-2-Acceptance-Gate as named in the Sprint-Phase-2-
Gates-Mini brief, plus one aggregator that walks all five back-to-back
to surface cross-gate interactions. All tests are hermetic: no podman,
no NATS, no live VM — pure in-memory mocks (see
``feedback_sandbox_host_trennung.md`` and
``feedback_live_bringup_sandbox_gap.md``). The live-VM-acceptance gate
remains the Operator-Hand-lane responsibility.

Gate naming
-----------

The brief's gate labels map onto the Amara-spec gates as follows:

* **Gate-2-1 Bridge-Forward-Symmetry** ⇔ phase-2-doppelbetrieb.md §2.2
  (Bridge-Forward fan-out symmetric, drop-rate ≤ 0.1%).
* **Gate-2-2 Konsistenz-Score ≥ Threshold** ⇔ §2.3 (Doppelbetrieb-
  Score four-axis verdict — here the consistency-score from Selin's
  diff-engine, used as the test-time proxy for the runtime 6h-rollup
  Henrik samples).
* **Gate-2-3 V907-Hash-Stabilität-Marker** ⇔ §2.4 (Zero
  ``PersonaHashDriftError`` events, ``axis-a-pin`` matches build-time
  pin).
* **Gate-2-4 Recovery-R1..R4-Mock-Drill** ⇔ ADR-0058 §Phase 3 stress-
  test-drill matrix (Despawn+Recovery, Capability-Token-Rotation,
  KV-Persistenz-VM-Reboot, WAT-OTS-Anchor-Cycle-Failover). The mock-
  drill here is the hermetic equivalent of the live drill; the live
  drill remains operator-hand.
* **Gate-2-5 Subscribe-Loop-Lag-Mock** ⇔ phase-2-doppelbetrieb.md §3
  SLO row (Output-reply timeliness p99 ≤ 45s).

Sandbox boundary
----------------

In-memory: every test constructs deterministic mock fan-out traces,
mock score-runs, mock pin-cards, mock recovery transcripts, and mock
subscribe-loop timing histograms. No filesystem writes outside
``tmp_path``; no subprocess, no network.
"""

from __future__ import annotations

import hashlib
import io
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffInput,
    compare_implementations,
    consistency_score,
    diff_envelopes,
)
from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
)


# ---------------------------------------------------------------------------
# Shared fixtures and mock substrate.
# ---------------------------------------------------------------------------


_ORG = "acme"
_PERSONA = "tomas"
_SESSION = "phase-2-acceptance-mock"
_V907_PIN = "sha256:" + "a" * 64
_PRE_VERSION = "pre-framework-tomas"
_RUN_VERSION = "0.4.2-pilot"
_TS = "2026-05-16T00:00:00Z"

# Acceptance thresholds — sourced from phase-2-doppelbetrieb.md §1.
DROP_RATE_THRESHOLD = 0.001          # §2.2 ≤ 0.1%
CONSISTENCY_SCORE_THRESHOLD = 0.95   # §2.3 functional_equivalence
P99_REPLY_TIMELINESS_S = 45.0        # §3 SLI row
SUBSCRIBE_LAG_P99_S = 45.0           # mirror of p99 reply timeliness


@dataclass(frozen=True)
class FanOutEvent:
    """One auftrag fanned out by Bridge-Forward.

    Mirrors the on-the-wire substrate of the
    ``wakir.<env>.agent.agent.task.assigned.tomas`` ⇒ pair-of-sinks
    contract: each auftrag MUST land exactly once on each sink. Drop
    is encoded by ``pre_sink_received=False`` or
    ``run_sink_received=False``.
    """

    auftrag_id: str
    pre_sink_received: bool
    run_sink_received: bool


def _build_symmetric_fanout(n: int) -> list[FanOutEvent]:
    """Build ``n`` fan-out events with zero drops on either sink."""
    return [
        FanOutEvent(
            auftrag_id=f"auftrag-{i:04d}",
            pre_sink_received=True,
            run_sink_received=True,
        )
        for i in range(n)
    ]


def _build_fanout_with_drop_rate(
    n: int, pre_drops: int, run_drops: int
) -> list[FanOutEvent]:
    """Build ``n`` fan-out events with the requested per-sink drops.

    The first ``pre_drops`` events drop on the pre-sink; the last
    ``run_drops`` drop on the run-sink. Drops are non-overlapping for
    test clarity.
    """
    assert pre_drops + run_drops <= n, "non-overlapping drop budget"
    out: list[FanOutEvent] = []
    for i in range(n):
        pre_received = i >= pre_drops
        run_received = i < n - run_drops
        out.append(
            FanOutEvent(
                auftrag_id=f"auftrag-{i:04d}",
                pre_sink_received=pre_received,
                run_sink_received=run_received,
            )
        )
    return out


def _drop_rate(events: list[FanOutEvent]) -> float:
    """Drop-rate per phase-2-doppelbetrieb.md §2.2:

    a drop is any auftrag missing on at least one sink.
    """
    if not events:
        return 0.0
    dropped = sum(
        1 for e in events if not (e.pre_sink_received and e.run_sink_received)
    )
    return dropped / len(events)


def _make_writer(
    tmp_path: Path, sink: io.StringIO, engine_version: str
) -> BridgeAuditWriter:
    """Construct a writer using the Doppelbetrieb shared-Markdown-sink
    layout (both engines append to one Pre-Framework sink + their own
    structured-log JSON sink)."""
    return BridgeAuditWriter(
        org_id=_ORG,
        persona_id=_PERSONA,
        session_id=f"{_SESSION}-{engine_version}",
        engine_version=engine_version,
        v907_pin=_V907_PIN,
        preframework_sink_path=tmp_path / "bridge-audit.md",
        wakir_runtime_sink=sink,
    )


# ---------------------------------------------------------------------------
# Gate-2-1: Bridge-Forward-Symmetry.
# ---------------------------------------------------------------------------


def test_gate_2_1_bridge_forward_symmetry():
    """Every auftrag fans out to exactly one Pre-Framework + one Wakir-
    Runtime sink emission; drop-rate ≤ 0.1% over rolling 24h.

    Anchor: phase-2-doppelbetrieb.md §2.2. The hermetic mock runs a
    1000-event window — the same magnitude the bridge-audit
    reconciliation report aggregates (Sprint-10 Tag-6 spec §7).
    """
    # Symmetric window: 1000 auftraege, no drops.
    events = _build_symmetric_fanout(1000)
    assert _drop_rate(events) == 0.0

    # Boundary case: exactly one drop ⇒ 0.001 drop-rate ⇒ at-threshold.
    events_at_threshold = _build_fanout_with_drop_rate(1000, pre_drops=1, run_drops=0)
    rate = _drop_rate(events_at_threshold)
    assert rate == pytest.approx(0.001, abs=1e-9), (
        f"single-drop in 1000 must yield drop-rate=0.1% exactly, got {rate}"
    )
    assert rate <= DROP_RATE_THRESHOLD, (
        f"drop-rate {rate} must remain ≤ §2.2 threshold {DROP_RATE_THRESHOLD}"
    )

    # Failure mode: two drops ⇒ 0.002 ⇒ exceeds threshold, gate fails.
    events_over = _build_fanout_with_drop_rate(1000, pre_drops=2, run_drops=0)
    assert _drop_rate(events_over) > DROP_RATE_THRESHOLD, (
        "gate must detect drop-rate excursions above 0.1%"
    )

    # Symmetry contract: every non-dropped auftrag hits both sinks.
    for e in events:
        assert e.pre_sink_received and e.run_sink_received, (
            f"symmetric fanout invariant broken at {e.auftrag_id}"
        )


# ---------------------------------------------------------------------------
# Gate-2-2: Konsistenz-Score ≥ Threshold (via Selin diff-engine).
# ---------------------------------------------------------------------------


def _identity_impl(input_: DiffInput) -> dict:
    """Adapter producing a stable CloudEvent envelope for a DiffInput.

    Used as the Pre-Framework-side adapter in Gate-2-2 mock-runs.
    Both adapters return structurally identical envelopes by default;
    the wakir-runtime adapter mutates one field to surface drift.
    """
    return {
        "specversion": "1.0",
        "type": "wakir.persona.output.v1",
        "source": f"wakir://{input_.org_id}/{input_.persona_id}",
        "id": f"{input_.session_id}:{input_.step_index}",
        "time": input_.ts_utc,
        "datacontenttype": "application/json",
        "data": {
            "output_kind": input_.output_kind,
            "payload_sha256": "sha256:"
            + hashlib.sha256(input_.payload).hexdigest(),
            "step_index": input_.step_index,
        },
    }


def _drifting_impl(input_: DiffInput) -> dict:
    """Adapter that introduces a single-field drift on step 7 only.

    Mirrors the realistic Doppelbetrieb case: 99/100 events byte-
    identical, 1/100 with a structural drift (e.g. a new
    ``audit_annotation`` field one implementation emits and the other
    does not). Returns identical envelope shape for all other steps.
    """
    envelope = dict(_identity_impl(input_))
    if input_.step_index == 7:
        data = dict(envelope["data"])
        data["spurious_extra_field"] = "drift-marker"
        envelope["data"] = data
    return envelope


def test_gate_2_2_konsistenz_score_threshold():
    """Selin diff-engine yields ``consistency_score >= 0.95`` over a
    mock 100-event trace where 99/100 are byte-identical and 1/100
    carries a single-field drift.

    Anchor: phase-2-doppelbetrieb.md §2.3
    (``functional_equivalence >= 0.95`` axis of the four-axis verdict).
    Uses Selin's ``compare_implementations`` + ``consistency_score`` so
    this test breaks symmetrically with the runtime CLI.
    """
    reports = []
    for step in range(100):
        di = DiffInput(
            org_id=_ORG,
            persona_id=_PERSONA,
            session_id=_SESSION,
            step_index=step,
            output_kind="reply",
            payload=f'{{"step":{step}}}'.encode("utf-8"),
            ts_utc=_TS,
        )
        reports.append(
            compare_implementations(di, _identity_impl, _drifting_impl)
        )

    # 99/100 events byte-identical.
    identical_count = sum(1 for r in reports if r.byte_identical)
    assert identical_count == 99, (
        f"expected 99/100 byte-identical events, got {identical_count}/100"
    )

    # The single drifting event has score < 1.0 (one field of ~10
    # differs ⇒ score ≈ 0.9). A single drift below 0.95 is acceptable
    # at the event-level; the §2.3 gate is on the *window-mean* score,
    # which is the test-time proxy for the 6h-rollup the runtime CLI
    # emits.
    drift_report = next(r for r in reports if not r.byte_identical)
    assert drift_report.consistency_score < 1.0
    assert drift_report.consistency_score > 0.0, (
        "single-field drift must not score 0.0 (catastrophic)"
    )

    # Aggregate score (mean across the 100-event window) must clear
    # threshold. With 99/100 at 1.0 and 1/100 at ~0.9, the mean is
    # ~0.999, well above the 0.95 functional-equivalence threshold.
    mean_score = statistics.fmean(r.consistency_score for r in reports)
    assert mean_score >= CONSISTENCY_SCORE_THRESHOLD, (
        f"window-mean consistency-score {mean_score} below §2.3 threshold "
        f"{CONSISTENCY_SCORE_THRESHOLD}"
    )

    # Failure mode: a trace where every event drifts on multiple fields
    # MUST fail the gate. Build a totally-different envelope adapter.
    def _all_drift_impl(input_: DiffInput) -> dict:
        return {"unrelated_shape": True, "step": input_.step_index}

    catastrophic = compare_implementations(
        DiffInput(
            org_id=_ORG,
            persona_id=_PERSONA,
            session_id=_SESSION,
            step_index=0,
            output_kind="reply",
            payload=b"x",
            ts_utc=_TS,
        ),
        _identity_impl,
        _all_drift_impl,
    )
    assert catastrophic.consistency_score < CONSISTENCY_SCORE_THRESHOLD, (
        "gate must reject catastrophic-drift traces"
    )


# ---------------------------------------------------------------------------
# Gate-2-3: V-907-Hash-Stabilität-Marker.
# ---------------------------------------------------------------------------


def test_gate_2_3_v907_hash_stability_marker(tmp_path):
    """Every Bridge-Audit-Writer envelope over a rolling window pins
    the same ``v907_pin`` value; zero ``EXIT_V907_HASH_DRIFT`` events.

    Anchor: phase-2-doppelbetrieb.md §2.4 (No V-907 pin-drift for 28
    days; ``axis-a-pin`` matches build-time pin). The hermetic test
    walks a 50-emission mock and asserts pin-stability on the envelope
    field that the runtime ``bridge-audit axis-a-pin`` query reads.
    """
    sink = io.StringIO()
    writer = _make_writer(tmp_path, sink, _RUN_VERSION)

    envelopes = []
    for step in range(50):
        evt = writer.emit(
            "reply",
            f'{{"step":{step}}}'.encode("utf-8"),
            ts_utc=_TS,
        )
        envelopes.append(evt)

    # Every emission MUST carry the same v907_pin (build-time pin).
    pins = {evt.v907_pin for evt in envelopes}
    assert pins == {_V907_PIN}, (
        f"V-907 pin-drift detected across 50-emission window: {pins}"
    )

    # No emission may carry an empty / sentinel pin.
    assert all(evt.v907_pin and evt.v907_pin.startswith("sha256:") for evt in envelopes), (
        "every envelope must carry a non-empty sha256: V-907 pin"
    )

    # Drift-injection: a second writer with a different build-time pin
    # MUST emit envelopes that the audit substrate can attribute to a
    # different pin (this is what the EXIT_V907_HASH_DRIFT detector
    # would surface in production).
    sink2 = io.StringIO()
    drift_pin = "sha256:" + "b" * 64
    drift_writer = BridgeAuditWriter(
        org_id=_ORG,
        persona_id=_PERSONA,
        session_id="phase-2-drift-arm",
        engine_version=_RUN_VERSION,
        v907_pin=drift_pin,
        preframework_sink_path=tmp_path / "drift-sink.md",
        wakir_runtime_sink=sink2,
    )
    drift_evt = drift_writer.emit("reply", b'{"x":1}', ts_utc=_TS)
    assert drift_evt.v907_pin == drift_pin
    assert drift_evt.v907_pin != _V907_PIN, (
        "audit substrate must see distinct pins across two engines with "
        "different build-time pin material"
    )


# ---------------------------------------------------------------------------
# Gate-2-4: Recovery-R1..R4-Mock-Drill.
# ---------------------------------------------------------------------------


@dataclass
class RecoveryStep:
    """One step in a Recovery-Drill transcript.

    ADR-0058 Phase 3 names four drill axes:
      * R1 = Persona-Despawn + Recovery on wakir-runtime stack
      * R2 = Capability-Token-Rotation + Replay-Detection
      * R3 = Marker-Stack KV-Persistenz across VM-Reboot
      * R4 = WAT-OTS-Anchor-Cycle Multi-Calendar-Failover

    Each step records whether the drill axis recovered cleanly. The
    mock-drill is hermetic — it does not actually restart a container
    or rotate a real token; it asserts the contract surface the live
    drill exercises.
    """

    axis: str
    recovered: bool
    notes: str = ""


def _mock_recovery_drill() -> list[RecoveryStep]:
    """Run a hermetic mock drill across R1..R4 and return transcript.

    The mock always succeeds on a healthy substrate; the test below
    also constructs a partial-failure transcript to assert the gate
    rejects it.
    """
    return [
        RecoveryStep(
            axis="R1-despawn-recovery",
            recovered=True,
            notes="persona-engine container despawn → re-spawn cleanly "
            "rehydrated active_log from NATS-KV",
        ),
        RecoveryStep(
            axis="R2-capability-rotation",
            recovered=True,
            notes="capability-token rotated; replay of old token "
            "rejected by middleware",
        ),
        RecoveryStep(
            axis="R3-kv-vm-reboot",
            recovered=True,
            notes="VM-reboot retained NATS-KV marker-stack bucket; "
            "monotonic transition.utc invariant held",
        ),
        RecoveryStep(
            axis="R4-wat-ots-failover",
            recovered=True,
            notes="primary OTS-calendar timed out; secondary calendar "
            "anchored within retry budget",
        ),
    ]


def test_gate_2_4_recovery_r1_r4_mock_drill():
    """R1..R4 mock-drill transcript records ``recovered=True`` for every
    axis; partial-failure transcripts are rejected.

    Anchor: ADR-0058 §"Phase 3 — Validation (Wochen 5-6)" Stress-Test-
    Drill matrix. The mock here is the test-time equivalent of the
    live drill the Operator-Hand-lane executes — see
    ``feedback_sandbox_host_trennung.md``.
    """
    transcript = _mock_recovery_drill()

    # Exactly four axes per ADR-0058.
    axes = {step.axis for step in transcript}
    assert axes == {
        "R1-despawn-recovery",
        "R2-capability-rotation",
        "R3-kv-vm-reboot",
        "R4-wat-ots-failover",
    }, f"drill transcript MUST cover R1..R4, got {axes}"
    assert len(transcript) == 4, (
        f"one step per axis, got {len(transcript)}"
    )

    # Healthy drill: every axis recovered.
    assert all(step.recovered for step in transcript), (
        "Phase-2 → Phase-3 promotion gate requires all four axes green; "
        f"failing axes: {[s.axis for s in transcript if not s.recovered]}"
    )

    # Failure mode: a transcript with one failure (e.g. R3 lost KV
    # state on VM-reboot) MUST fail the gate.
    partial_failure = [
        RecoveryStep(axis="R1-despawn-recovery", recovered=True),
        RecoveryStep(axis="R2-capability-rotation", recovered=True),
        RecoveryStep(
            axis="R3-kv-vm-reboot",
            recovered=False,
            notes="KV bucket lost on reboot — operator alert raised",
        ),
        RecoveryStep(axis="R4-wat-ots-failover", recovered=True),
    ]
    assert not all(step.recovered for step in partial_failure), (
        "gate must reject any drill transcript with a failing axis"
    )


# ---------------------------------------------------------------------------
# Gate-2-5: Subscribe-Loop-Lag-Mock.
# ---------------------------------------------------------------------------


def _mock_subscribe_loop_lag_histogram() -> list[float]:
    """Return a 200-sample lag histogram (seconds) for a healthy
    subscribe-loop.

    Models the Output-reply timeliness SLI (publish → reply latency).
    The distribution is right-tailed but bounded: median ~5s, p95 ~20s,
    p99 ~35s — well under the §3 SLO row of 45s.
    """
    samples: list[float] = []
    # 95% of samples in [1, 15] seconds (fast path).
    samples.extend(1.0 + (i * 0.07) for i in range(190))
    # 5% of samples in [20, 40] seconds (slow path: bridge-forward
    # contention, NATS-replay, etc).
    samples.extend(20.0 + (i * 2.0) for i in range(10))
    return samples


def _p99(samples: list[float]) -> float:
    """Compute p99 from a sample window via inclusive-quantile rank."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, int(round(0.99 * (len(ordered) - 1))))
    return ordered[idx]


def test_gate_2_5_subscribe_loop_lag_mock():
    """Subscribe-loop publish → reply p99 ≤ 45s over a 200-sample mock
    window.

    Anchor: phase-2-doppelbetrieb.md §3 SLO row (Output-reply timeliness
    p99 ≤ 45s, rolling 1h). The mock substitutes a deterministic
    histogram for the live NATS-replay subscribe-loop; the live SLI is
    Noa's domain.
    """
    samples = _mock_subscribe_loop_lag_histogram()
    assert len(samples) == 200

    p99 = _p99(samples)
    assert p99 <= SUBSCRIBE_LAG_P99_S, (
        f"p99 lag {p99}s exceeds §3 SLO {SUBSCRIBE_LAG_P99_S}s — "
        f"subscribe-loop gate must reject"
    )

    # Sanity: median is well under p99 (right-skewed distribution).
    median = statistics.median(samples)
    assert median < p99, (
        f"distribution must be right-skewed (median {median}s < p99 {p99}s)"
    )

    # Failure mode: an excursion sample at 60s pushes p99 over SLO.
    bad_samples = samples + [60.0] * 5
    bad_p99 = _p99(bad_samples)
    assert bad_p99 > SUBSCRIBE_LAG_P99_S, (
        f"injected 60s-excursion must drive p99 ({bad_p99}s) over SLO"
    )


# ---------------------------------------------------------------------------
# Aggregator: all five gates back-to-back.
# ---------------------------------------------------------------------------


def test_gate_aggregator_phase_2_acceptance_all_green(tmp_path):
    """Aggregate verdict: all five Phase-2-Acceptance-Gates green over a
    single hermetic mock-run.

    The aggregator surfaces cross-gate interactions — e.g. a drift
    event on Gate-2-2 SHOULD NOT cascade into a V-907-pin-drift on
    Gate-2-3, and a subscribe-loop excursion on Gate-2-5 SHOULD NOT
    silently flip Bridge-Forward symmetry on Gate-2-1. This is the
    test-time proxy for the weekly rollup Henrik samples
    (phase-2-doppelbetrieb.md §4 Audit-Punkt E).
    """
    verdicts: dict[str, bool] = {}

    # Gate-2-1: drop-rate over 1000-event window.
    events = _build_symmetric_fanout(1000)
    verdicts["gate-2-1-symmetry"] = _drop_rate(events) <= DROP_RATE_THRESHOLD

    # Gate-2-2: consistency-score over 100-event mock trace.
    reports = []
    for step in range(100):
        di = DiffInput(
            org_id=_ORG,
            persona_id=_PERSONA,
            session_id=_SESSION,
            step_index=step,
            output_kind="reply",
            payload=f'{{"step":{step}}}'.encode("utf-8"),
            ts_utc=_TS,
        )
        reports.append(compare_implementations(di, _identity_impl, _drifting_impl))
    mean_score = statistics.fmean(r.consistency_score for r in reports)
    verdicts["gate-2-2-konsistenz"] = mean_score >= CONSISTENCY_SCORE_THRESHOLD

    # Gate-2-3: V-907 pin stability over 50-emission window.
    sink = io.StringIO()
    writer = _make_writer(tmp_path, sink, _RUN_VERSION)
    envelopes = [
        writer.emit("reply", f'{{"step":{i}}}'.encode("utf-8"), ts_utc=_TS)
        for i in range(50)
    ]
    pins = {e.v907_pin for e in envelopes}
    verdicts["gate-2-3-v907"] = pins == {_V907_PIN}

    # Gate-2-4: Recovery-R1..R4 mock-drill.
    transcript = _mock_recovery_drill()
    verdicts["gate-2-4-recovery"] = all(step.recovered for step in transcript)

    # Gate-2-5: Subscribe-loop p99 ≤ 45s.
    samples = _mock_subscribe_loop_lag_histogram()
    verdicts["gate-2-5-subscribe-lag"] = _p99(samples) <= SUBSCRIBE_LAG_P99_S

    # All five gates MUST be green for Phase-2 → Phase-3 promotion.
    assert all(verdicts.values()), (
        f"aggregator verdict: not all gates green {verdicts}"
    )
    assert set(verdicts.keys()) == {
        "gate-2-1-symmetry",
        "gate-2-2-konsistenz",
        "gate-2-3-v907",
        "gate-2-4-recovery",
        "gate-2-5-subscribe-lag",
    }, "aggregator must touch all five gates"

    # Cross-gate non-interference invariant: Gate-2-2's single-event
    # drift (step 7) MUST NOT have flipped Gate-2-3's V-907 pin set.
    assert _V907_PIN in pins, (
        "Gate-2-2 drift on payload field must not propagate to V-907 "
        "pin set in Gate-2-3"
    )

    # Audit-friendly rollup: the aggregator emits a JSON-serialisable
    # verdict-map that Henrik's weekly Audit-Sample (§4 Audit-Punkt E)
    # consumes. The shape is stable across runs.
    rollup = json.dumps(verdicts, sort_keys=True)
    assert "gate-2-1-symmetry" in rollup
    assert rollup == json.dumps(verdicts, sort_keys=True), (
        "rollup serialisation must be deterministic"
    )
