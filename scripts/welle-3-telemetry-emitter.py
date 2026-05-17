#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-3-telemetry-emitter — Tag-31 Mini-Welle high-frequency Welle-3 telemetry.

Background
----------

ADR-0066 (2026-05-17) collapsed the seven Phase-3c cutover welles into
a four-week schedule. KW 25 runs Welle-3 (``bridge_audit_writer``)
**solo** — no parallel partner. The reason is a structural risk
flagged by Henrik (Internal Audit) during the ADR-0066 review:

  **Consistency-Oracle-Selbst-Cutover-Risiko** — once the persona
  engine's Rust backend takes over ``bridge_audit_writer``, the very
  module that emits the BackendDecision audit envelopes is itself
  being swapped. Reading the consistency signal from the module that
  is mid-cutover is a circular oracle. A python-vs-rust split read
  back from ``bridge_audit_writer`` is the module describing its own
  switch — exactly the situation Henrik called out.

This emitter mitigates the risk by adding two substantive things on
top of the Tag-30 ``phase-3c-welle-status-emitter`` baseline:

  1. **High-frequency per-tick consistency score** (10s default,
     configurable via ``--tick-interval-seconds``) computed only over
     Welle-3 (``bridge_audit_writer``) decisions in a sliding window
     ending at "now". This is the substrate behind the dashboard's
     ``Bridge-Audit-Writer-Konsistenz-Score`` panel.

  2. **Independent oracle: Phase-2 cross-modul stress-test result**,
     loaded from a separate stress-test output JSON
     (``--phase2-stress-json``). The stress test stresses
     cross-modul-pinning **outside** the bridge_audit_writer code
     path — exactly the independence Henrik asked for. This is the
     substrate behind the dashboard's
     ``Phase-2-Cross-Modul-Stress-Test-Oracle`` panel.

  3. **Divergence alert:** the emitter compares the bridge_audit_writer
     self-score against the phase2-stress oracle and raises a
     ``divergence_red_flag`` boolean when the absolute delta exceeds
     the configurable threshold (default 0.5 percentage points,
     ``--divergence-threshold-pct``). Crossing the threshold is the
     ADR-0066 Welle-3 immediate-rollback trigger.

Posture
-------

Stdlib-only. No cosign / podman / systemctl / NATS / network. Reads
two on-disk inputs (BackendDecision JSONL + Phase-2-stress-test
output JSON), emits one JSON snapshot and an optional Prometheus
textfile-collector output.

The Welle-3-specific telemetry runs at higher cadence than the
Tag-30 emitter (10s vs. Tag-30's 1m default) so the operator on the
KW-25 cutover-acceptance call sees a near-real-time consistency
trend during the solo cutover window. Higher cadence is acceptable
because the on-disk inputs are append-only JSONL files; we slide a
window over them, we do not re-process every record.

Welle-3 fix-set
---------------

* **Welle:** ``3`` (the only welle this emitter scores)
* **Domain:** ``bridge_audit_writer``
* **ENV-VAR (production):** ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND``
* **ADR-0066 cap:** ``DOPPEL_WELLE_CAP = 2``; Welle-3 runs solo by
  design, so welle-aktiv-count must stay at exactly 1 during KW 25
  if the schedule is being honored. The emitter does **not** enforce
  the cap (that is Tag-30's job) — it surfaces the welle-3-aktiv
  boolean so the dashboard panel turns red on inadvertent
  parallelism.

ENV contract
------------

  1. ``--decisions-jsonl PATH`` CLI flag.
  2. ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV (shared with the
     Tag-30 emitter so a single operator-hand path drives both).
  3. ``WAKIR_BACKEND_DECISION_JSONL`` ENV.

For the Phase-2-stress-test oracle:

  1. ``--phase2-stress-json PATH`` CLI flag.
  2. ``WAKIR_PHASE_2_STRESS_OUTPUT`` ENV.

For the lifecycle override (operator-hand state machine, same file as
Tag-30):

  1. ``--lifecycle-json PATH`` CLI flag.
  2. ``WAKIR_PHASE_3C_WELLE_LIFECYCLE`` ENV.

Outputs
-------

Two files (both optional via CLI):

* ``--out PATH``           -> JSON snapshot (Welle-3 telemetry payload)
* ``--prom-textfile PATH`` -> Prometheus node-exporter textfile

Prometheus metric names (all gauges, all carrying ``welle="3"``
and ``domain="bridge_audit_writer"`` labels):

  * ``persona_engine_welle_3_consistency_score``
  * ``persona_engine_welle_3_stress_oracle_score``
  * ``persona_engine_welle_3_divergence_pct``
  * ``persona_engine_welle_3_divergence_red_flag``
  * ``persona_engine_welle_3_window_python_count``
  * ``persona_engine_welle_3_window_rust_count``
  * ``persona_engine_welle_3_window_fallback_count``
  * ``persona_engine_welle_3_window_seconds``
  * ``persona_engine_welle_3_tick_interval_seconds``
  * ``persona_engine_welle_3_divergence_threshold_pct``
  * ``persona_engine_welle_3_aktiv`` (1 iff lifecycle state is
     ``in_cutover`` or ``rollback_active``)

Exit codes
----------

* ``0`` — snapshot built, no red-flag.
* ``1`` — snapshot built, **divergence_red_flag set** (operator
   investigation required; the cutover team treats this as the
   ADR-0066 Mitigation-2 rollback trigger).
* ``2`` — input error (malformed JSON / unreadable file / bad CLI).
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import math
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants (single-source-of-truth for the Welle-3 fix-set)
# ---------------------------------------------------------------------------


SCHEMA_ID = "wakir.persona-engine.welle-3-telemetry.v1"

WELLE_NUMBER = 3
WELLE_DOMAIN = "bridge_audit_writer"
WELLE_ENV_VAR = "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"

# ADR-0066 doppel-welle cap (informational on this emitter; the
# Tag-30 emitter enforces the cap. Surfaced here only for the
# welle-3-aktiv panel.)
DOPPEL_WELLE_CAP = 2

# High-frequency tick — KW-25 operator-acceptance call needs a
# near-real-time consistency trend.
DEFAULT_TICK_INTERVAL_SECONDS = 10

# Sliding window over the BackendDecision JSONL. 5 minutes balances
# signal stability against the operator's preference for a fast-
# responding indicator during the cutover hour.
DEFAULT_WINDOW_SECONDS = 300

# Henrik's tolerance band: 0.5 percentage points of divergence
# between the bridge_audit_writer self-score and the phase-2 stress
# oracle is the ADR-0066 Mitigation-2 immediate-rollback trigger.
DEFAULT_DIVERGENCE_THRESHOLD_PCT = 0.5

# ENV var keys (importable for test surface)
ENV_PHASE_3C_OBS_BASELINE_PATH = "WAKIR_PHASE_3C_OBS_BASELINE_PATH"
ENV_BACKEND_DECISION_JSONL = "WAKIR_BACKEND_DECISION_JSONL"
ENV_PHASE_2_STRESS_OUTPUT = "WAKIR_PHASE_2_STRESS_OUTPUT"
ENV_PHASE_3C_WELLE_LIFECYCLE = "WAKIR_PHASE_3C_WELLE_LIFECYCLE"


class WelleState(enum.Enum):
    """Welle-3 lifecycle states (mirror Tag-30 vocabulary)."""

    PRE_CUTOVER = "pre_cutover"
    IN_CUTOVER = "in_cutover"
    POST_CUTOVER = "post_cutover"
    ROLLBACK_ACTIVE = "rollback_active"
    WELLE_COMPLETE = "welle_complete"


class StressOracleStatus(enum.Enum):
    """Phase-2-stress-test oracle status (mirrors Tag-30 cross-modul
    drift tri-state for dashboard consistency)."""

    GREEN = "green"   # stress test passed
    RED = "red"       # stress test failed
    YELLOW = "yellow"  # stress test skipped / missing / unparseable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowCounts:
    """Per-backend count of BackendDecisions inside the sliding window."""

    python_count: int = 0
    rust_count: int = 0
    fallback_count: int = 0

    @property
    def total(self) -> int:
        return self.python_count + self.rust_count + self.fallback_count


@dataclass(frozen=True)
class StressOracle:
    """Phase-2 cross-modul stress-test oracle payload."""

    status: StressOracleStatus
    score_pct: Optional[float]
    reason: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "score_pct": self.score_pct,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Welle3TelemetrySnapshot:
    """Single snapshot of Welle-3 telemetry."""

    schema_id: str
    generated_at: str
    welle: int
    domain: str
    env_var: str
    welle_state: WelleState
    welle_aktiv: bool
    window_seconds: int
    tick_interval_seconds: int
    window_counts: WindowCounts
    consistency_score_pct: Optional[float]
    stress_oracle: StressOracle
    divergence_pct: Optional[float]
    divergence_threshold_pct: float
    divergence_red_flag: bool
    red_flag_reason: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "generated_at": self.generated_at,
            "welle": self.welle,
            "domain": self.domain,
            "env_var": self.env_var,
            "welle_state": self.welle_state.value,
            "welle_aktiv": self.welle_aktiv,
            "window_seconds": self.window_seconds,
            "tick_interval_seconds": self.tick_interval_seconds,
            "window_counts": {
                "python_count": self.window_counts.python_count,
                "rust_count": self.window_counts.rust_count,
                "fallback_count": self.window_counts.fallback_count,
                "total": self.window_counts.total,
            },
            "consistency_score_pct": self.consistency_score_pct,
            "stress_oracle": self.stress_oracle.to_json(),
            "divergence_pct": self.divergence_pct,
            "divergence_threshold_pct": self.divergence_threshold_pct,
            "divergence_red_flag": self.divergence_red_flag,
            "red_flag_reason": self.red_flag_reason,
        }


# ---------------------------------------------------------------------------
# Path resolution (CLI > ENV > None)
# ---------------------------------------------------------------------------


def _resolve_path(
    cli_value: Optional[str], env_keys: List[str]
) -> Optional[Path]:
    """Resolve a path argument with CLI > ENV priority."""

    if cli_value:
        return Path(cli_value).expanduser()
    for key in env_keys:
        v = os.environ.get(key)
        if v:
            return Path(v).expanduser()
    return None


def resolve_decisions_jsonl_path(
    cli_value: Optional[str],
) -> Optional[Path]:
    return _resolve_path(
        cli_value,
        [ENV_PHASE_3C_OBS_BASELINE_PATH, ENV_BACKEND_DECISION_JSONL],
    )


def resolve_phase2_stress_path(
    cli_value: Optional[str],
) -> Optional[Path]:
    return _resolve_path(cli_value, [ENV_PHASE_2_STRESS_OUTPUT])


def resolve_lifecycle_path(
    cli_value: Optional[str],
) -> Optional[Path]:
    return _resolve_path(cli_value, [ENV_PHASE_3C_WELLE_LIFECYCLE])


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _parse_ts(ts: str) -> Optional[datetime]:
    """Parse the ``ts`` field from a BackendDecision record.

    Accepts ISO-8601 strings with a ``Z`` suffix (the persona-engine's
    canonical envelope). Returns None on parse failure; the emitter
    silently drops records with unparseable timestamps to keep the
    consistency signal robust against log-rotation artefacts.
    """

    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BackendDecision JSONL ingestion (sliding window over Welle-3 only)
# ---------------------------------------------------------------------------


def ingest_window(
    path: Optional[Path],
    *,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> Tuple[WindowCounts, int]:
    """Aggregate Welle-3 BackendDecisions inside the sliding window.

    Returns ``(window_counts, parse_errors)``. ``parse_errors`` is
    the count of JSONL lines that failed to parse — surfaced so the
    operator can tell apart "no Welle-3 traffic" from "decision log
    is corrupt". The function reads only Welle-3 records (the
    ``bridge_audit_writer`` domain); other welles' records are
    skipped silently.
    """

    if path is None or not path.is_file():
        return WindowCounts(), 0

    if now is None:
        now = _now_utc()
    window_start = now.timestamp() - max(window_seconds, 0)

    python_count = rust_count = fallback_count = 0
    parse_errors = 0

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    parse_errors += 1
                    continue
                if not isinstance(rec, dict):
                    parse_errors += 1
                    continue
                if rec.get("domain") != WELLE_DOMAIN:
                    continue
                ts = _parse_ts(rec.get("ts", ""))
                if ts is None:
                    parse_errors += 1
                    continue
                if ts.timestamp() < window_start:
                    continue
                chosen = rec.get("chosen_backend")
                fallback = rec.get("fallback_reason")
                if fallback:
                    fallback_count += 1
                    continue
                if chosen == "python":
                    python_count += 1
                elif chosen == "rust":
                    rust_count += 1
                else:
                    # unknown backend value — count as fallback for
                    # the consistency-score denominator
                    fallback_count += 1
    except OSError:
        return WindowCounts(), parse_errors

    return (
        WindowCounts(
            python_count=python_count,
            rust_count=rust_count,
            fallback_count=fallback_count,
        ),
        parse_errors,
    )


# ---------------------------------------------------------------------------
# Consistency score
# ---------------------------------------------------------------------------


def compute_consistency_score_pct(
    counts: WindowCounts,
) -> Optional[float]:
    """Compute the bridge_audit_writer self-consistency score.

    Definition: rust_count / total * 100 — i.e. the percentage of
    Welle-3 traffic that landed on the Rust backend without fallback.
    Returns ``None`` when there is no traffic in the window (the
    "no-signal" condition, distinct from "all fallback").
    """

    total = counts.total
    if total == 0:
        return None
    return round((counts.rust_count / total) * 100.0, 4)


# ---------------------------------------------------------------------------
# Phase-2 cross-modul stress-test oracle
# ---------------------------------------------------------------------------


def load_stress_oracle(path: Optional[Path]) -> StressOracle:
    """Load the Phase-2 cross-modul stress-test oracle.

    The Phase-2-Acceptance-Gate optional stress-test mode (ADR-0066
    Mitigation-2) emits a JSON file with two fields:

      * ``cross_modul_stress_status``: ``pass`` / ``fail`` /
        ``skipped``
      * ``cross_modul_stress_score_pct``: a 0..100 float carrying the
        stress-test's measured cross-modul-rust-rate. ``None`` /
        absent is allowed when the stress test was skipped.

    Mapping mirrors Tag-30 cross_modul_drift for dashboard parity:

      * ``pass``     -> GREEN
      * ``fail``     -> RED
      * ``skipped``  -> YELLOW
      * anything else / missing field / file missing -> YELLOW
    """

    if path is None:
        return StressOracle(
            StressOracleStatus.YELLOW,
            None,
            "phase-2-stress-output-not-configured",
        )
    if not path.is_file():
        return StressOracle(
            StressOracleStatus.YELLOW,
            None,
            "phase-2-stress-file-not-found",
        )
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return StressOracle(
            StressOracleStatus.YELLOW,
            None,
            "phase-2-stress-parse-error",
        )
    if not isinstance(obj, dict):
        return StressOracle(
            StressOracleStatus.YELLOW,
            None,
            "phase-2-stress-root-not-object",
        )

    status_raw = obj.get("cross_modul_stress_status")
    score_raw = obj.get("cross_modul_stress_score_pct")

    score_pct: Optional[float]
    if score_raw is None:
        score_pct = None
    elif isinstance(score_raw, (int, float)) and not isinstance(
        score_raw, bool
    ):
        score_pct = float(score_raw)
        if math.isnan(score_pct) or math.isinf(score_pct):
            score_pct = None
    else:
        score_pct = None

    if status_raw == "pass":
        return StressOracle(
            StressOracleStatus.GREEN,
            score_pct,
            "cross-modul-stress-pass",
        )
    if status_raw == "fail":
        return StressOracle(
            StressOracleStatus.RED,
            score_pct,
            "cross-modul-stress-fail",
        )
    if status_raw == "skipped":
        return StressOracle(
            StressOracleStatus.YELLOW,
            score_pct,
            "cross-modul-stress-skipped",
        )
    return StressOracle(
        StressOracleStatus.YELLOW,
        score_pct,
        "cross-modul-stress-status-missing-or-unknown",
    )


# ---------------------------------------------------------------------------
# Lifecycle (operator-hand state machine for Welle-3)
# ---------------------------------------------------------------------------


def load_welle_3_lifecycle(path: Optional[Path]) -> WelleState:
    """Resolve the Welle-3 lifecycle state from the operator-hand
    override JSON.

    The override format mirrors Tag-30's: a flat dict ``{"<welle>":
    "<state>"}`` where keys are stringified welle numbers and values
    are state-vocabulary strings. We read only the key ``"3"``;
    other welles are ignored here (Tag-30's emitter handles them).
    """

    if path is None or not path.is_file():
        return WelleState.PRE_CUTOVER
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        # Tag-30 raises on malformed lifecycle; here we degrade to
        # PRE_CUTOVER for safety. A malformed lifecycle should not
        # falsely advance Welle-3 to ``welle_complete``.
        return WelleState.PRE_CUTOVER
    if not isinstance(obj, dict):
        return WelleState.PRE_CUTOVER

    raw = obj.get("3")
    if raw is None:
        # Tag-30 uses int keys via cast; tolerate both shapes here.
        raw = obj.get(3)
    if raw is None:
        return WelleState.PRE_CUTOVER

    valid = {s.value for s in WelleState}
    if isinstance(raw, str) and raw in valid:
        return WelleState(raw)
    return WelleState.PRE_CUTOVER


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_snapshot(
    *,
    decisions_path: Optional[Path],
    phase2_stress_path: Optional[Path],
    lifecycle_path: Optional[Path],
    tick_interval_seconds: int = DEFAULT_TICK_INTERVAL_SECONDS,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    divergence_threshold_pct: float = DEFAULT_DIVERGENCE_THRESHOLD_PCT,
    now: Optional[datetime] = None,
) -> Welle3TelemetrySnapshot:
    """Build a single Welle-3 telemetry snapshot from on-disk inputs.

    Never invents numbers: when the BackendDecision window is empty
    the consistency score is None, when the stress oracle is missing
    the divergence is None. Red-flag fires only when **both** the
    self-score and the oracle score are concrete numbers and their
    absolute delta exceeds the configured threshold.
    """

    if now is None:
        now = _now_utc()

    counts, _parse_errors = ingest_window(
        decisions_path,
        window_seconds=window_seconds,
        now=now,
    )
    consistency = compute_consistency_score_pct(counts)
    oracle = load_stress_oracle(phase2_stress_path)
    state = load_welle_3_lifecycle(lifecycle_path)

    welle_aktiv = state in (
        WelleState.IN_CUTOVER,
        WelleState.ROLLBACK_ACTIVE,
    )

    # Divergence + red-flag logic
    divergence_pct: Optional[float]
    red_flag = False
    red_flag_reason = "ok"

    if consistency is None:
        divergence_pct = None
        red_flag_reason = "consistency-score-no-traffic-in-window"
    elif oracle.score_pct is None:
        divergence_pct = None
        red_flag_reason = "stress-oracle-score-missing"
    else:
        divergence_pct = round(
            abs(consistency - oracle.score_pct), 4
        )
        if divergence_pct > divergence_threshold_pct:
            red_flag = True
            red_flag_reason = (
                f"divergence-{divergence_pct:.4f}pct-exceeds-"
                f"threshold-{divergence_threshold_pct:.4f}pct"
            )
        else:
            red_flag_reason = "ok"

    # Hard red-flag override: stress oracle status RED is itself a
    # rollback trigger regardless of the numeric divergence (Henrik's
    # rule: "if the independent oracle says fail, do not wait for the
    # divergence math").
    if oracle.status == StressOracleStatus.RED and not red_flag:
        red_flag = True
        red_flag_reason = "stress-oracle-status-fail"

    return Welle3TelemetrySnapshot(
        schema_id=SCHEMA_ID,
        generated_at=now.replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        welle=WELLE_NUMBER,
        domain=WELLE_DOMAIN,
        env_var=WELLE_ENV_VAR,
        welle_state=state,
        welle_aktiv=welle_aktiv,
        window_seconds=window_seconds,
        tick_interval_seconds=tick_interval_seconds,
        window_counts=counts,
        consistency_score_pct=consistency,
        stress_oracle=oracle,
        divergence_pct=divergence_pct,
        divergence_threshold_pct=divergence_threshold_pct,
        divergence_red_flag=red_flag,
        red_flag_reason=red_flag_reason,
    )


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def render_prometheus_textfile(snapshot: Welle3TelemetrySnapshot) -> str:
    """Render the snapshot as a Prometheus node-exporter textfile.

    All gauges. All carry ``welle="3"`` and ``domain="bridge_audit_writer"``
    labels for stable PromQL filters from the dashboard. ``None``
    values are rendered as ``NaN`` per the Prometheus textfile spec.
    """

    def _fmt(v: Optional[float]) -> str:
        if v is None:
            return "NaN"
        return f"{v:g}"

    base_labels = f'welle="{WELLE_NUMBER}",domain="{WELLE_DOMAIN}"'
    lines: List[str] = []

    lines.append(
        "# HELP persona_engine_welle_3_consistency_score "
        "Welle-3 bridge_audit_writer self-consistency score (rust_count/total*100)."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_consistency_score gauge"
    )
    lines.append(
        f"persona_engine_welle_3_consistency_score{{{base_labels}}} "
        f"{_fmt(snapshot.consistency_score_pct)}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_stress_oracle_score "
        "Welle-3 Phase-2 cross-modul stress-test oracle score (percent)."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_stress_oracle_score gauge"
    )
    lines.append(
        f"persona_engine_welle_3_stress_oracle_score{{{base_labels},"
        f'status="{snapshot.stress_oracle.status.value}"}} '
        f"{_fmt(snapshot.stress_oracle.score_pct)}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_divergence_pct "
        "Absolute difference between Welle-3 self-score and stress oracle (percent)."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_divergence_pct gauge"
    )
    lines.append(
        f"persona_engine_welle_3_divergence_pct{{{base_labels}}} "
        f"{_fmt(snapshot.divergence_pct)}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_divergence_red_flag "
        "1 iff Welle-3 self-vs-oracle divergence exceeds the configured threshold."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_divergence_red_flag gauge"
    )
    lines.append(
        f"persona_engine_welle_3_divergence_red_flag{{{base_labels},"
        f'reason="{snapshot.red_flag_reason}"}} '
        f"{1 if snapshot.divergence_red_flag else 0}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_window_python_count "
        "Welle-3 BackendDecision count in the sliding window where chosen_backend=python."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_window_python_count gauge"
    )
    lines.append(
        f"persona_engine_welle_3_window_python_count{{{base_labels}}} "
        f"{snapshot.window_counts.python_count}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_window_rust_count "
        "Welle-3 BackendDecision count in the sliding window where chosen_backend=rust."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_window_rust_count gauge"
    )
    lines.append(
        f"persona_engine_welle_3_window_rust_count{{{base_labels}}} "
        f"{snapshot.window_counts.rust_count}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_window_fallback_count "
        "Welle-3 BackendDecision count in the sliding window where fallback_reason was set."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_window_fallback_count gauge"
    )
    lines.append(
        f"persona_engine_welle_3_window_fallback_count{{{base_labels}}} "
        f"{snapshot.window_counts.fallback_count}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_window_seconds "
        "Welle-3 sliding-window length in seconds."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_window_seconds gauge"
    )
    lines.append(
        f"persona_engine_welle_3_window_seconds{{{base_labels}}} "
        f"{snapshot.window_seconds}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_tick_interval_seconds "
        "Welle-3 emitter tick interval (operator-cadence target)."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_tick_interval_seconds gauge"
    )
    lines.append(
        f"persona_engine_welle_3_tick_interval_seconds{{{base_labels}}} "
        f"{snapshot.tick_interval_seconds}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_divergence_threshold_pct "
        "Configured divergence threshold in percentage points."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_divergence_threshold_pct gauge"
    )
    lines.append(
        f"persona_engine_welle_3_divergence_threshold_pct{{{base_labels}}} "
        f"{snapshot.divergence_threshold_pct:g}"
    )

    lines.append(
        "# HELP persona_engine_welle_3_aktiv "
        "1 iff Welle-3 lifecycle state is in_cutover or rollback_active."
    )
    lines.append(
        "# TYPE persona_engine_welle_3_aktiv gauge"
    )
    lines.append(
        f"persona_engine_welle_3_aktiv{{{base_labels},"
        f'state="{snapshot.welle_state.value}"}} '
        f"{1 if snapshot.welle_aktiv else 0}"
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-3-telemetry-emitter",
        description=(
            "Emit Welle-3 (bridge_audit_writer) high-frequency telemetry "
            "with Phase-2 cross-modul stress-test as independent oracle."
        ),
    )
    p.add_argument(
        "--decisions-jsonl",
        help="Path to BackendDecision JSONL (defaults to env-resolved).",
    )
    p.add_argument(
        "--phase2-stress-json",
        help="Path to Phase-2 cross-modul stress-test output JSON.",
    )
    p.add_argument(
        "--lifecycle-json",
        help="Path to operator-hand lifecycle override JSON.",
    )
    p.add_argument(
        "--tick-interval-seconds",
        type=int,
        default=DEFAULT_TICK_INTERVAL_SECONDS,
        help=(
            "Tick interval for the cadence panel (informational; the "
            "emitter is a one-shot run, the cadence is enforced by the "
            "caller's systemd timer or cron). Default 10s."
        ),
    )
    p.add_argument(
        "--window-seconds",
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help="Sliding-window length in seconds. Default 300 (5 minutes).",
    )
    p.add_argument(
        "--divergence-threshold-pct",
        type=float,
        default=DEFAULT_DIVERGENCE_THRESHOLD_PCT,
        help="Red-flag threshold in percentage points. Default 0.5.",
    )
    p.add_argument(
        "--out",
        help="Output path for the JSON snapshot (stdout if omitted).",
    )
    p.add_argument(
        "--prom-textfile",
        help="Output path for Prometheus textfile-collector format.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.tick_interval_seconds <= 0:
        print(
            "welle-3-telemetry-emitter: tick-interval-seconds must be > 0",
            file=sys.stderr,
        )
        return 2
    if args.window_seconds <= 0:
        print(
            "welle-3-telemetry-emitter: window-seconds must be > 0",
            file=sys.stderr,
        )
        return 2
    if args.divergence_threshold_pct < 0:
        print(
            "welle-3-telemetry-emitter: divergence-threshold-pct must be >= 0",
            file=sys.stderr,
        )
        return 2

    decisions_path = resolve_decisions_jsonl_path(args.decisions_jsonl)
    phase2_path = resolve_phase2_stress_path(args.phase2_stress_json)
    lifecycle_path = resolve_lifecycle_path(args.lifecycle_json)

    snapshot = build_snapshot(
        decisions_path=decisions_path,
        phase2_stress_path=phase2_path,
        lifecycle_path=lifecycle_path,
        tick_interval_seconds=args.tick_interval_seconds,
        window_seconds=args.window_seconds,
        divergence_threshold_pct=args.divergence_threshold_pct,
    )

    payload = json.dumps(snapshot.to_json(), indent=2, sort_keys=True)

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")

    if args.prom_textfile:
        prom_path = Path(args.prom_textfile).expanduser()
        prom_path.parent.mkdir(parents=True, exist_ok=True)
        prom_path.write_text(
            render_prometheus_textfile(snapshot), encoding="utf-8"
        )

    return 1 if snapshot.divergence_red_flag else 0


if __name__ == "__main__":
    sys.exit(main())
