#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cutover-Day-Live-Stream-Aggregator (Phase-3c, Tag-41, Noa SRE).

Context
-------

ADR-0066 (Phase-3c Cutover-Plan) schedules seven Cutover-Wellen across
KW-24..27 (Welle-1 v907_verify KW-24, Welle-2 svid_workload_identity
KW-24, Welle-3 bridge_audit_writer KW-25 solo, Welle-4 state_backing
KW-26, Welle-5 lifecycle_state_machine KW-26, Welle-6 subscribe_loop
KW-27, Welle-7 recovery_workflow KW-27). For each Welle the
persona-engine emits a stream of ``BackendDecision`` audit-events on
the NATS subject ``wakir.persona-engine.boot-decision-audit.*`` (see
``scripts/persona-engine/backend-decision-observability.py`` /
``dashboards/persona-engine-backend-decisions.json``).

During a Cutover-Tag-Morgen the operator needs three things that the
existing post-hoc Aggregator-Failure-Rate-Tracker (Tag-38 PR #251)
and Marathon-Dashboard (Tag-40 PR #260) do NOT produce:

  1. **Realtime per-Welle BackendDecision distribution.** Operator
     question: "is Welle-N's backend-switch ratio (production vs.
     shadow vs. fallback) holding steady, or is it drifting away
     from the pre-cutover baseline within the first 5/30/60 minutes?"
  2. **Realtime Cross-Welle-Drift.** When two Wellen run on the same
     day (Doppel-Welle KW-26: Welle-4 + Welle-5, ADR-0066 Mitigation-1),
     do their backend-switch distributions diverge in a way that
     would not show up in the per-Welle view? This is the A7-test
     (ADR-0066 §Mitigation-2-Cross-Welle-Coordination-Test) but
     ON-STREAM instead of as post-hoc batch.
  3. **Live-stream tail** for the operator's terminal at 06:30 CEST
     on Cutover-Tag-Morgen. The Grafana dashboard is the second-
     screen; the live stdout is the first-screen.

This aggregator is read-only against the BackendDecision stream:
either subscribe via ``nats sub`` (live, when SPIFFE-creds present)
or poll a fixture-jsonl-file (hermetic-test + dry-run).

Sandbox boundary
----------------

When invoked with ``--mode=fixture --fixture-stream <path>`` the
script reads newline-delimited JSON events from a file and feeds
them through the aggregation pipeline as if they had arrived
on-stream. This is the mode used by the hermetic test-suite
(``tests/observability/test_cutover_day_live_stream_aggregator.py``)
and by the Operator-Doku dry-run-rehearsal at the start of each
Cutover-Tag.

The ``--mode=nats`` path shells out to ``nats sub`` (the NATS-CLI;
see Kai's ADR-0020 Container-Orchestration NATS substrate) and
pipes one JSON event per line into the aggregation pipeline. We
deliberately do NOT take a hard dependency on the ``nats-py``
library: stdlib + the NATS-CLI is enough, keeps the SRE-side
hermetically testable, and avoids a Python-runtime version-pin
fight with Kai's container substrate.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-
function, hermetic-test target. The I/O wrappers (NATS-CLI subshell,
file-tail, signal handlers, Prometheus-textfile writer) are below.

Drift-threshold semantics
-------------------------

For each Welle-pair (Welle-A, Welle-B) running on the same day,
the aggregator computes the L1-distance between their normalised
backend-decision distributions over the active sliding window:

  drift(A, B) = 0.5 * sum_k |p_A(k) - p_B(k)|

where p_W(k) is the fraction of the last N decisions on Welle W
that ended in backend ``k`` (one of {"production", "shadow",
"fallback", "skipped"}). The 0.5 factor normalises the result to
[0, 1] (total-variation distance).

Bands (operator-tuned defaults):
  drift < 0.05  => GREEN
  0.05 <= drift < 0.15 => AMBER
  drift >= 0.15 => RED

A RED-crossing emits a Mira-Notify event on stdout (the Bash
wrapper picks it up via stdout tee and forwards to the operator's
notify queue) and increments the ``wakir_cutover_live_drift_red``
Prometheus gauge. AMBER and GREEN crossings are logged but not
notified (anti-alert-fatigue).

Anchors
-------

* ADR-0066 §Cutover-Plan (Phase-3c Welle-1..7).
* ADR-0066 §Mitigation-2-Cross-Welle-Coordination-Test (A7).
* PR #251 (Tag-38 aggregator-failure-rate-tracker) — pattern source.
* PR #260 (Tag-40 phase-3-marathon dashboard 71 panels) — extended.
* ``scripts/persona-engine/backend-decision-observability.py`` —
  upstream emit-points (Reza/persona-engine), schema source.

Author: Noa Bergstroem (SRE)
Tag: 41 (KW-22, Cutover-Tag-Morgen-Werkzeug)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from collections import deque, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Deque,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    TextIO,
    Tuple,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#
# The seven Phase-3c-Cutover-Wellen (ADR-0066 Cutover-Plan). Keep this
# list in lock-step with the welle-templating in
# ``dashboards/phase-3c-cross-welle-coordination.json`` and with
# ``dashboards/persona-engine-phase-3c-welle-status.json``. The
# hermetic test ``test_welle_inventory_matches_dashboard`` asserts the
# names below match a fixture extracted from the Grafana JSON.

WELLE_NAMES: Tuple[str, ...] = (
    "welle-1",
    "welle-2",
    "welle-3",
    "welle-4",
    "welle-5",
    "welle-6",
    "welle-7",
)

# Sliding-window sizes for realtime aggregation. Smaller windows than
# the post-hoc tracker (50/100/500) because at 06:30 CEST Cutover-Tag-
# Morgen the operator wants "the last 1 / 5 / 30 minutes" granularity,
# not "the last 50 / 100 / 500 events". Event-counts not minutes: a
# Welle that emits 10 decisions/second hits 600 in 1 minute; the
# operator-facing windows are decision-count based to keep them
# rate-independent.

WINDOW_SIZES: Tuple[int, ...] = (60, 300, 1800)

# BackendDecision outcomes the aggregator knows about. Source: Reza's
# ``backend-decision-observability.py`` event-emit schema. ``unknown``
# is the catch-all bucket for events with an outcome string we don't
# recognise (forward-compat for new backends added during Phase-3c).

BACKEND_OUTCOMES: Tuple[str, ...] = (
    "production",
    "shadow",
    "fallback",
    "skipped",
    "unknown",
)

# Drift-threshold bands (total-variation distance between two Welle-
# distributions). See module docstring for the operator-tuned defaults.

DRIFT_AMBER_THRESHOLD = 0.05
DRIFT_RED_THRESHOLD = 0.15

# Default NATS subject pattern. Wildcard ``*`` matches the per-Welle
# suffix; the wirelang frame's ``welle`` field is the discriminator.

DEFAULT_NATS_SUBJECT = "wakir.persona-engine.boot-decision-audit.*"

# Default Prometheus-textfile path (matches the node-exporter
# convention from Tag-38 aggregator-failure-rate-tracker.py).

DEFAULT_PROMETHEUS_TEXTFILE_PATH = (
    "/var/lib/prometheus/node-exporter/wakir_cutover_live_stream.prom"
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendDecisionEvent:
    """One BackendDecision audit-event from the NATS stream.

    Mirrors the on-wire schema emitted by
    ``scripts/persona-engine/backend-decision-observability.py``:

      {
        "welle": "welle-3",
        "outcome": "production",
        "latency_ms": 12.4,
        "head_sha": "abc123",
        "timestamp_unixtime": 1747740000.0
      }

    ``welle`` is the cutover-welle this decision belongs to (one of
    ``WELLE_NAMES``). ``outcome`` is one of ``BACKEND_OUTCOMES``;
    unrecognised values get re-bucketed as ``unknown`` in the rollup.
    ``latency_ms`` is the persona-engine's backend-decision wall-
    clock (NOT the wirelang frame round-trip latency).
    """

    welle: str
    outcome: str
    latency_ms: float
    head_sha: str
    timestamp_unixtime: float


@dataclass
class WelleWindow:
    """Sliding window of BackendDecision events for one Welle.

    Holds at most ``capacity`` events; evicting the oldest as new
    events arrive. The dict counters are derived state for fast
    distribution-readout without scanning the deque every emit.
    """

    welle: str
    capacity: int
    events: Deque[BackendDecisionEvent] = field(default_factory=deque)
    outcome_counts: Dict[str, int] = field(
        default_factory=lambda: {k: 0 for k in BACKEND_OUTCOMES}
    )
    latencies_ms: Deque[float] = field(default_factory=deque)

    def add(self, ev: BackendDecisionEvent) -> None:
        """Append event; evict oldest if at capacity."""
        bucket = ev.outcome if ev.outcome in self.outcome_counts else "unknown"
        if len(self.events) >= self.capacity:
            old = self.events.popleft()
            old_bucket = (
                old.outcome if old.outcome in self.outcome_counts else "unknown"
            )
            self.outcome_counts[old_bucket] = max(
                0, self.outcome_counts[old_bucket] - 1
            )
            if self.latencies_ms:
                self.latencies_ms.popleft()
        # Append normalised copy (so the counter and the deque agree
        # on the bucket name even when ev.outcome was an unknown
        # string).
        self.events.append(ev)
        self.outcome_counts[bucket] = self.outcome_counts.get(bucket, 0) + 1
        if ev.latency_ms >= 0:
            self.latencies_ms.append(float(ev.latency_ms))

    def sample_count(self) -> int:
        return len(self.events)

    def distribution(self) -> Dict[str, float]:
        """Normalised backend-outcome distribution over the window.

        Returns one entry per ``BACKEND_OUTCOMES`` bucket; sums to 1.0
        when the window is non-empty, all-zero when empty.
        """
        total = sum(self.outcome_counts.values())
        if total <= 0:
            return {k: 0.0 for k in BACKEND_OUTCOMES}
        return {k: self.outcome_counts.get(k, 0) / total for k in BACKEND_OUTCOMES}

    def latency_percentiles(self) -> Tuple[float, float, float]:
        """Return (p50, p95, p99) latency over the window."""
        if not self.latencies_ms:
            return (0.0, 0.0, 0.0)
        vals = list(self.latencies_ms)
        return (
            _percentile(vals, 50),
            _percentile(vals, 95),
            _percentile(vals, 99),
        )


@dataclass(frozen=True)
class DriftReading:
    """Total-variation drift between two Welle distributions.

    ``band`` is ``GREEN``, ``AMBER`` or ``RED`` per the
    operator-tuned thresholds at the top of the module.
    """

    welle_a: str
    welle_b: str
    drift: float
    band: str
    sample_count_a: int
    sample_count_b: int


@dataclass(frozen=True)
class DriftCrossing:
    """One band-boundary crossing event.

    Emitted when a Welle-pair's drift crosses a threshold (in either
    direction). The Bash wrapper greps for ``DRIFT_RED_CROSSING`` on
    stdout to forward to Mira-Notify.
    """

    welle_a: str
    welle_b: str
    previous_band: str
    current_band: str
    drift: float
    timestamp_unixtime: float


# ---------------------------------------------------------------------------
# Pure-function aggregator (hermetic test target)
# ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile, stdlib-only."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def parse_event_json(line: str) -> Optional[BackendDecisionEvent]:
    """Parse one stream-line into a BackendDecisionEvent.

    Pure function. Returns ``None`` on malformed input (missing
    required fields, JSON parse error). Tolerates extra fields:
    upstream schema-evolution must not break the aggregator.

    Required fields: ``welle``, ``outcome``. Optional with safe
    defaults: ``latency_ms`` (0.0), ``head_sha`` (""),
    ``timestamp_unixtime`` (0.0).
    """
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    welle = obj.get("welle")
    outcome = obj.get("outcome")
    if not welle or not outcome:
        return None
    try:
        latency = float(obj.get("latency_ms", 0.0) or 0.0)
    except (TypeError, ValueError):
        latency = 0.0
    try:
        ts = float(obj.get("timestamp_unixtime", 0.0) or 0.0)
    except (TypeError, ValueError):
        ts = 0.0
    return BackendDecisionEvent(
        welle=str(welle),
        outcome=str(outcome),
        latency_ms=latency,
        head_sha=str(obj.get("head_sha") or ""),
        timestamp_unixtime=ts,
    )


def classify_drift_band(drift: float) -> str:
    """Map a drift value to GREEN / AMBER / RED."""
    if drift >= DRIFT_RED_THRESHOLD:
        return "RED"
    if drift >= DRIFT_AMBER_THRESHOLD:
        return "AMBER"
    return "GREEN"


def compute_pairwise_drift(
    windows: Mapping[str, WelleWindow],
    *,
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
) -> List[DriftReading]:
    """Compute total-variation drift between Welle pairs.

    Pure function. ``pairs`` defaults to all C(N, 2) unordered
    pairs of Welle names present in ``windows``. The drift formula
    is the total-variation distance between the two normalised
    distributions (see module docstring).

    Pairs where one side has zero samples return drift=0.0 with
    band=GREEN (no data is not divergence). The hermetic test
    ``test_drift_zero_when_no_samples`` enforces this.
    """
    out: List[DriftReading] = []
    welle_list = sorted(windows.keys())
    if pairs is None:
        pairs = []
        for i, a in enumerate(welle_list):
            for b in welle_list[i + 1 :]:
                pairs.append((a, b))
    for a, b in pairs:
        wa = windows.get(a)
        wb = windows.get(b)
        if wa is None or wb is None:
            continue
        ca = wa.sample_count()
        cb = wb.sample_count()
        if ca == 0 or cb == 0:
            out.append(
                DriftReading(
                    welle_a=a,
                    welle_b=b,
                    drift=0.0,
                    band="GREEN",
                    sample_count_a=ca,
                    sample_count_b=cb,
                )
            )
            continue
        da = wa.distribution()
        db = wb.distribution()
        keys = set(da.keys()) | set(db.keys())
        drift = 0.5 * sum(abs(da.get(k, 0.0) - db.get(k, 0.0)) for k in keys)
        out.append(
            DriftReading(
                welle_a=a,
                welle_b=b,
                drift=drift,
                band=classify_drift_band(drift),
                sample_count_a=ca,
                sample_count_b=cb,
            )
        )
    return out


def detect_band_crossings(
    previous: Mapping[Tuple[str, str], str],
    current: Sequence[DriftReading],
    *,
    timestamp_unixtime: Optional[float] = None,
) -> List[DriftCrossing]:
    """Detect band-boundary crossings between two snapshots.

    Pure function. ``previous`` maps (welle_a, welle_b) to the
    band-string from the prior snapshot; ``current`` is the latest
    DriftReading list. A crossing is emitted whenever a pair's
    band differs from its previous band. First-seen pairs (no entry
    in ``previous``) are NOT emitted as crossings — they are
    initial-state, not transitions.
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    events: List[DriftCrossing] = []
    for r in current:
        key = (r.welle_a, r.welle_b)
        prev_band = previous.get(key)
        if prev_band is None:
            continue
        if prev_band != r.band:
            events.append(
                DriftCrossing(
                    welle_a=r.welle_a,
                    welle_b=r.welle_b,
                    previous_band=prev_band,
                    current_band=r.band,
                    drift=r.drift,
                    timestamp_unixtime=timestamp_unixtime,
                )
            )
    return events


def render_state_json(
    windows: Mapping[str, WelleWindow],
    drift_readings: Sequence[DriftReading],
    *,
    window_size: int,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render aggregator state as JSON for the operator stdout tail.

    Pure function. Schema mirrors the post-hoc JSON of the Tag-38
    tracker but with a realtime-tail layout (per-Welle distribution
    + per-pair drift + per-Welle latency percentiles).
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    out = {
        "schema_version": 1,
        "anchor": "ADR-0066 Phase-3c §Mitigation-2 (Cross-Welle on-stream)",
        "timestamp_unixtime": timestamp_unixtime,
        "window_size": window_size,
        "wellen": {},
        "drift": [],
        "summary": {
            "welle_count": len(windows),
            "drift_pair_count": len(drift_readings),
            "drift_red_count": sum(1 for r in drift_readings if r.band == "RED"),
            "drift_amber_count": sum(
                1 for r in drift_readings if r.band == "AMBER"
            ),
        },
    }
    for welle, w in sorted(windows.items()):
        p50, p95, p99 = w.latency_percentiles()
        out["wellen"][welle] = {
            "sample_count": w.sample_count(),
            "distribution": w.distribution(),
            "latency_p50_ms": p50,
            "latency_p95_ms": p95,
            "latency_p99_ms": p99,
        }
    for r in drift_readings:
        out["drift"].append(
            {
                "welle_a": r.welle_a,
                "welle_b": r.welle_b,
                "drift": r.drift,
                "band": r.band,
                "sample_count_a": r.sample_count_a,
                "sample_count_b": r.sample_count_b,
            }
        )
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def render_prometheus_textfile(
    windows: Mapping[str, WelleWindow],
    drift_readings: Sequence[DriftReading],
    *,
    window_size: int,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render aggregator state as a Prometheus textfile.

    Pure function. Gauges emitted:

      wakir_cutover_live_distribution{welle, outcome} (gauge, [0,1])
      wakir_cutover_live_sample_count{welle} (gauge)
      wakir_cutover_live_latency_ms{welle, pct} (gauge)
      wakir_cutover_live_drift{welle_a, welle_b} (gauge, [0,1])
      wakir_cutover_live_drift_red (gauge, count of RED pairs)
      wakir_cutover_live_drift_amber (gauge, count of AMBER pairs)
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    ts_ms = int(timestamp_unixtime * 1000)
    lines: List[str] = []
    lines.append(
        "# HELP wakir_cutover_live_distribution Per-Welle realtime "
        "backend-decision-outcome distribution (fraction in [0,1])."
    )
    lines.append("# TYPE wakir_cutover_live_distribution gauge")
    for welle, w in sorted(windows.items()):
        dist = w.distribution()
        for outcome in BACKEND_OUTCOMES:
            lines.append(
                f'wakir_cutover_live_distribution{{welle="{welle}",'
                f'outcome="{outcome}"}} {dist.get(outcome, 0.0):.6f} {ts_ms}'
            )
    lines.append("")
    lines.append(
        "# HELP wakir_cutover_live_sample_count Per-Welle realtime "
        "window sample count."
    )
    lines.append("# TYPE wakir_cutover_live_sample_count gauge")
    for welle, w in sorted(windows.items()):
        lines.append(
            f'wakir_cutover_live_sample_count{{welle="{welle}"}} '
            f"{w.sample_count()} {ts_ms}"
        )
    lines.append("")
    lines.append(
        "# HELP wakir_cutover_live_latency_ms Per-Welle realtime "
        "backend-decision latency percentiles (p50/p95/p99)."
    )
    lines.append("# TYPE wakir_cutover_live_latency_ms gauge")
    for welle, w in sorted(windows.items()):
        p50, p95, p99 = w.latency_percentiles()
        for pct_label, pct_value in (("p50", p50), ("p95", p95), ("p99", p99)):
            lines.append(
                f'wakir_cutover_live_latency_ms{{welle="{welle}",'
                f'pct="{pct_label}"}} {pct_value:.3f} {ts_ms}'
            )
    lines.append("")
    lines.append(
        "# HELP wakir_cutover_live_drift Per-Welle-pair total-variation "
        "drift between normalised backend-decision distributions."
    )
    lines.append("# TYPE wakir_cutover_live_drift gauge")
    for r in drift_readings:
        lines.append(
            f'wakir_cutover_live_drift{{welle_a="{r.welle_a}",'
            f'welle_b="{r.welle_b}"}} {r.drift:.6f} {ts_ms}'
        )
    lines.append("")
    red = sum(1 for r in drift_readings if r.band == "RED")
    amber = sum(1 for r in drift_readings if r.band == "AMBER")
    lines.append(
        "# HELP wakir_cutover_live_drift_red Count of Welle-pairs "
        "currently in the RED drift band."
    )
    lines.append("# TYPE wakir_cutover_live_drift_red gauge")
    lines.append(f"wakir_cutover_live_drift_red {red} {ts_ms}")
    lines.append("")
    lines.append(
        "# HELP wakir_cutover_live_drift_amber Count of Welle-pairs "
        "currently in the AMBER drift band."
    )
    lines.append("# TYPE wakir_cutover_live_drift_amber gauge")
    lines.append(f"wakir_cutover_live_drift_amber {amber} {ts_ms}")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_notify_line(crossing: DriftCrossing) -> str:
    """Render one band-crossing as an operator-grep-friendly line.

    The Bash wrapper greps for ``DRIFT_RED_CROSSING`` and
    ``DRIFT_AMBER_CROSSING`` prefixes on stdout to forward to the
    Mira-Notify queue.
    """
    tag = f"DRIFT_{crossing.current_band}_CROSSING"
    return (
        f"{tag} welle_a={crossing.welle_a} welle_b={crossing.welle_b} "
        f"drift={crossing.drift:.4f} previous_band={crossing.previous_band} "
        f"timestamp={crossing.timestamp_unixtime:.0f}"
    )


# ---------------------------------------------------------------------------
# Pipeline driver (pure-function ingestion loop)
# ---------------------------------------------------------------------------


@dataclass
class AggregatorState:
    """Mutable per-process aggregator state.

    Holds one WelleWindow per Welle and the previous-snapshot
    band-map for crossing detection. Constructed empty and grown
    on-demand: a Welle that never emits an event never gets a
    window (avoids cluttering the dashboard with empty rows for
    Wellen that aren't yet active in the cutover-plan).
    """

    window_size: int
    windows: Dict[str, WelleWindow] = field(default_factory=dict)
    previous_bands: Dict[Tuple[str, str], str] = field(default_factory=dict)

    def ingest(self, ev: BackendDecisionEvent) -> None:
        """Add one event to the matching Welle's sliding window."""
        if ev.welle not in self.windows:
            self.windows[ev.welle] = WelleWindow(
                welle=ev.welle, capacity=self.window_size
            )
        self.windows[ev.welle].add(ev)

    def snapshot(
        self, *, timestamp_unixtime: Optional[float] = None
    ) -> Tuple[List[DriftReading], List[DriftCrossing]]:
        """Compute drift readings + detect crossings vs. previous snapshot.

        Updates ``previous_bands`` to reflect the new readings, so the
        next call computes crossings against the just-emitted state.
        """
        readings = compute_pairwise_drift(self.windows)
        crossings = detect_band_crossings(
            self.previous_bands,
            readings,
            timestamp_unixtime=timestamp_unixtime,
        )
        self.previous_bands = {(r.welle_a, r.welle_b): r.band for r in readings}
        return readings, crossings


def run_pipeline(
    event_lines: Iterable[str],
    *,
    state: AggregatorState,
    emit_every: int = 50,
    json_sink: Optional[TextIO] = None,
    notify_sink: Optional[TextIO] = None,
    prometheus_path: Optional[Path] = None,
    time_fn=time.time,
) -> int:
    """Drive the aggregator over a line-iterator of stream events.

    Returns the count of events ingested. Side effects: writes
    ``emit_every``-batched snapshots to ``json_sink`` and per-crossing
    notify lines to ``notify_sink``; rewrites ``prometheus_path`` after
    each batch.

    Pure-function-mostly: the only impurity is the I/O sinks and the
    optional ``time_fn`` injection. The hermetic test exercises this
    function directly with StringIO sinks.
    """
    count = 0
    for line in event_lines:
        ev = parse_event_json(line)
        if ev is None:
            continue
        state.ingest(ev)
        count += 1
        if count % emit_every == 0:
            ts = time_fn()
            readings, crossings = state.snapshot(timestamp_unixtime=ts)
            if json_sink is not None:
                json_sink.write(
                    render_state_json(
                        state.windows,
                        readings,
                        window_size=state.window_size,
                        timestamp_unixtime=ts,
                    )
                )
                json_sink.flush()
            if notify_sink is not None:
                for c in crossings:
                    notify_sink.write(render_notify_line(c) + "\n")
                notify_sink.flush()
            if prometheus_path is not None:
                prometheus_path.write_text(
                    render_prometheus_textfile(
                        state.windows,
                        readings,
                        window_size=state.window_size,
                        timestamp_unixtime=ts,
                    ),
                    encoding="utf-8",
                )
    return count


def final_state_dump(
    state: AggregatorState, *, timestamp_unixtime: Optional[float] = None
) -> str:
    """Render a final-state JSON dump for clean shutdown.

    Called by the SIGINT handler in the Bash wrapper via a separate
    invocation. Pure function over the in-memory state.
    """
    readings, _ = state.snapshot(timestamp_unixtime=timestamp_unixtime)
    return render_state_json(
        state.windows,
        readings,
        window_size=state.window_size,
        timestamp_unixtime=timestamp_unixtime,
    )


# ---------------------------------------------------------------------------
# I/O boundary
# ---------------------------------------------------------------------------
# Everything below this marker shells out to ``nats``, opens files, or
# installs signal handlers. Not hermetically unit-tested; the
# fixture-mode entrypoint covers the integration path.
# ---------------------------------------------------------------------------


def fixture_line_iterator(fixture_path: Path) -> Iterator[str]:
    """Yield one stream-line per JSON-line in the fixture file."""
    with fixture_path.open("r", encoding="utf-8") as f:
        for line in f:
            yield line


def nats_subscribe_line_iterator(
    *, subject: str, nats_url: Optional[str] = None
) -> Iterator[str]:  # pragma: no cover - I/O wrapper, integration-tested
    """Yield stream lines from ``nats sub`` stdout.

    Shells out to the NATS-CLI. Requires the operator's SPIFFE
    workload-identity SVID to be mounted at the conventional path
    (see Kai's ADR-0020 NATS substrate). Does NOT take a hard
    dependency on the ``nats-py`` library.

    Loops until the subprocess exits. SIGINT in the parent kills the
    subshell via process-group.
    """
    cmd = ["nats", "sub", subject, "--raw"]
    if nats_url:
        cmd.extend(["-s", nats_url])
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            yield line
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()


def _install_sigint_handler(
    state: AggregatorState,
    final_dump_path: Optional[Path],
) -> None:  # pragma: no cover - signal handler
    """Install a SIGINT handler that dumps final state and exits."""

    def _handler(signum, frame):  # noqa: ARG001
        ts = time.time()
        dump = final_state_dump(state, timestamp_unixtime=ts)
        if final_dump_path:
            final_dump_path.write_text(dump, encoding="utf-8")
            print(
                f"[shutdown] final-state dump written to {final_dump_path}",
                file=sys.stderr,
            )
        else:
            sys.stderr.write("[shutdown] final-state:\n")
            sys.stderr.write(dump)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cutover-day-live-stream-aggregator",
        description=(
            "Realtime BackendDecision-Stream-Aggregator + Cross-Welle-"
            "Drift-Live-Indicator for Phase-3c Cutover-Tage KW-24..27 "
            "(Tag-41 Noa SRE). Subscribes to the NATS BackendDecision-"
            "stream (or polls a fixture-file in hermetic-test mode), "
            "rolls up per-Welle distributions over a sliding window, "
            "computes pairwise total-variation drift, emits JSON-stream "
            "+ Prometheus-textfile + Mira-Notify lines on RED-band "
            "crossings."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("fixture", "nats"),
        default="fixture",
        help="``fixture``: read --fixture-stream JSONL. ``nats``: shell out to nats sub.",
    )
    parser.add_argument(
        "--fixture-stream",
        type=Path,
        default=None,
        help="Path to JSONL fixture (mode=fixture only).",
    )
    parser.add_argument(
        "--nats-subject",
        type=str,
        default=DEFAULT_NATS_SUBJECT,
        help=f"NATS subject pattern. Default: {DEFAULT_NATS_SUBJECT}",
    )
    parser.add_argument(
        "--nats-url",
        type=str,
        default=None,
        help="NATS server URL (nats://...). If omitted, nats-CLI uses its default config.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=WINDOW_SIZES[1],
        choices=list(WINDOW_SIZES),
        help=(
            "Sliding window size in events. "
            f"Choices: {WINDOW_SIZES}. Default: {WINDOW_SIZES[1]}."
        ),
    )
    parser.add_argument(
        "--emit-every",
        type=int,
        default=50,
        help="Emit a snapshot every N events. Default 50.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Write JSON snapshots to this path (appends). Default: stdout.",
    )
    parser.add_argument(
        "--notify-output",
        type=Path,
        default=None,
        help="Write band-crossing notify lines to this path. Default: stderr.",
    )
    parser.add_argument(
        "--prometheus-output",
        type=Path,
        default=None,
        help=(
            "Path for Prometheus textfile. If omitted, skip Prometheus emit. "
            f"Conventional value: {DEFAULT_PROMETHEUS_TEXTFILE_PATH}"
        ),
    )
    parser.add_argument(
        "--final-dump-output",
        type=Path,
        default=None,
        help="On SIGINT/SIGTERM, write final-state JSON to this path.",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Stop after N events (0 = unbounded). Useful for rehearsal runs.",
    )
    args = parser.parse_args(argv)

    state = AggregatorState(window_size=args.window_size)

    # I/O sinks.
    json_sink: Optional[TextIO]
    if args.json_output:
        json_sink = args.json_output.open("a", encoding="utf-8")
    else:
        json_sink = sys.stdout
    notify_sink: Optional[TextIO]
    if args.notify_output:
        notify_sink = args.notify_output.open("a", encoding="utf-8")
    else:
        notify_sink = sys.stderr

    # Source of events.
    if args.mode == "fixture":
        if not args.fixture_stream:
            print(
                "ERROR: --fixture-stream required in mode=fixture.",
                file=sys.stderr,
            )
            return 2
        line_iter: Iterable[str] = fixture_line_iterator(args.fixture_stream)
    else:  # nats
        # Install signal handler only in long-running NATS mode.
        _install_sigint_handler(state, args.final_dump_output)
        line_iter = nats_subscribe_line_iterator(
            subject=args.nats_subject, nats_url=args.nats_url
        )

    # Bounded iteration if --max-events.
    if args.max_events > 0:
        def _bounded(it: Iterable[str], n: int) -> Iterator[str]:
            for i, x in enumerate(it):
                if i >= n:
                    return
                yield x

        line_iter = _bounded(line_iter, args.max_events)

    count = run_pipeline(
        line_iter,
        state=state,
        emit_every=args.emit_every,
        json_sink=json_sink,
        notify_sink=notify_sink,
        prometheus_path=args.prometheus_output,
    )

    # Final snapshot at clean end-of-stream (fixture-mode hits this).
    ts = time.time()
    final = final_state_dump(state, timestamp_unixtime=ts)
    if args.final_dump_output:
        args.final_dump_output.write_text(final, encoding="utf-8")
    else:
        if json_sink is not sys.stdout and json_sink is not None:
            json_sink.write(final)
            json_sink.flush()
        else:
            sys.stdout.write(final)

    print(
        f"[done] ingested {count} events across {len(state.windows)} Wellen.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
