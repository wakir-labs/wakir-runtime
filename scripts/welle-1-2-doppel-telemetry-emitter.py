#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""welle-1-2-doppel-telemetry-emitter — Tag-32 Mini-Welle Day-0 telemetry.

Background
----------

ADR-0066 (2026-05-17) collapsed the seven Phase-3c cutover welles into
a four-week schedule. KW 24 runs the **first doppel-welle pair**:

  * **Welle-1** — ``v907_verify``      (ENV ``WAKIR_V907_VERIFY_BACKEND``)
  * **Welle-2** — ``svid_workload_identity``
                  (ENV ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND``)

Dry-Run on Monday, full Cutover on Wednesday. Day-0 observability is
the operator-acceptance-call substrate the cutover lead will watch
during both windows.

This emitter is the Tag-32 Day-0 Observability deliverable, analogous
to the Tag-31 Welle-3 high-frequency telemetry emitter
(``welle-3-telemetry-emitter.py``). The Welle-3 emitter solves
Henrik's circular-oracle risk for the solo KW-25 cutover. The
Welle-1+2 doppel emitter solves the related but distinct **doppel-
welle correlation risk**: when two welles cut over in the same week,
a regression that affects both modules can hide inside the aggregate
counters surfaced by Tag-30's general welle-status emitter. The
doppel emitter mitigates this by emitting **per-welle** high-frequency
telemetry side by side, plus an explicit **combined health-score**
that turns red the moment either welle drifts.

What the doppel emitter adds on top of Tag-30's baseline
---------------------------------------------------------

1. **Per-welle high-frequency consistency score** (10s default,
   ``--tick-interval-seconds``) computed independently over Welle-1
   (``v907_verify``) and Welle-2 (``svid_workload_identity``)
   sliding-window BackendDecisions. Substrate for dashboard panels
   ``Welle-1 Self-Score`` and ``Welle-2 Self-Score``.

2. **Per-welle independent oracle**: Phase-2 cross-modul stress test
   result, loaded from a single Phase-2-stress JSON that may carry
   per-welle ``per_welle`` entries (preferred) or — for backward
   compatibility — a root-level cross-modul status that is applied to
   both welles. Substrate for the per-welle oracle panels.

3. **Per-welle divergence red-flag**: per-welle |self - oracle| >
   threshold (default 0.5pp) raises that welle's red-flag. Each welle
   is independent; a green Welle-1 next to a red Welle-2 must surface
   as such on the dashboard.

4. **Aggregated combined health-score** (the ADR-0066 doppel-welle-
   week deliverable): a single 0..100 score that combines both
   welles. Definition: ``min(welle_1_self_score, welle_2_self_score)``
   when both are defined; ``None`` otherwise. Mirrors the operator
   intuition that the doppel-week is only as healthy as its weaker
   welle. The combined health-score also turns red if **either**
   welle's red-flag is set.

Posture
-------

Stdlib-only. No cosign / podman / systemctl / NATS / network. Reads
two on-disk inputs (BackendDecision JSONL + optional Phase-2-stress
JSON + optional lifecycle override), emits one JSON snapshot and an
optional Prometheus textfile-collector output.

The 10s tick matches Welle-3; the operator-acceptance call needs the
same near-real-time cadence regardless of which welle pair is mid-
cutover. Both welles share the same emitter invocation so a single
systemd timer drives the whole doppel-week.

Welle fix-set
-------------

* **Welle numbers:** ``1`` and ``2``
* **Domain mapping:**
  * ``1`` -> ``v907_verify``           (ENV ``WAKIR_V907_VERIFY_BACKEND``)
  * ``2`` -> ``svid_workload_identity`` (ENV ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND``)
* **ADR-0066 cap:** ``DOPPEL_WELLE_CAP = 2``. KW 24 honors the cap by
  design (exactly 2 welles aktiv). The emitter surfaces per-welle
  aktiv-state booleans so the dashboard can show inadvertent solo
  drift (one welle stuck) or cap-violation (a third welle leaking in).

ENV contract
------------

The emitter uses the same ENV keys as the Tag-30 / Tag-31 emitters
plus per-welle Phase-2-stress paths for resolution priority CLI > ENV:

  * ``--decisions-jsonl PATH`` CLI flag
  * ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV (shared)
  * ``WAKIR_BACKEND_DECISION_JSONL`` ENV (fallback)

  * ``--phase2-stress-json PATH`` CLI flag (one file, per-welle entries)
  * ``WAKIR_PHASE_2_STRESS_OUTPUT`` ENV

  * ``--lifecycle-json PATH`` CLI flag
  * ``WAKIR_PHASE_3C_WELLE_LIFECYCLE`` ENV

Outputs
-------

Two files (both optional via CLI):

* ``--out PATH``           -> JSON snapshot (doppel telemetry payload)
* ``--prom-textfile PATH`` -> Prometheus node-exporter textfile

Prometheus metric names (all gauges; per-welle metrics carry
``welle="1"|"2"`` and ``domain="v907_verify"|"svid_workload_identity"``
labels). The combined health-score carries ``pair="1+2"``:

Per-welle (emitted twice — one row per welle):

  * ``persona_engine_doppel_welle_consistency_score``
  * ``persona_engine_doppel_welle_stress_oracle_score``
  * ``persona_engine_doppel_welle_divergence_pct``
  * ``persona_engine_doppel_welle_divergence_red_flag``
  * ``persona_engine_doppel_welle_window_python_count``
  * ``persona_engine_doppel_welle_window_rust_count``
  * ``persona_engine_doppel_welle_window_fallback_count``
  * ``persona_engine_doppel_welle_window_seconds``
  * ``persona_engine_doppel_welle_tick_interval_seconds``
  * ``persona_engine_doppel_welle_divergence_threshold_pct``
  * ``persona_engine_doppel_welle_aktiv``

Combined (emitted once with ``pair="1+2"``):

  * ``persona_engine_doppel_welle_combined_health_score``
  * ``persona_engine_doppel_welle_combined_red_flag``
  * ``persona_engine_doppel_welle_pair_aktiv_count``

Exit codes
----------

* ``0`` — snapshot built, no per-welle or combined red-flag.
* ``1`` — snapshot built, **any** red-flag set (operator
   investigation required; doppel-week rollback decision attaches to
   the **specific** welle that fired the flag).
* ``2`` — input error (malformed JSON / unreadable file / bad CLI).
"""

from __future__ import annotations

import argparse
import enum
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants (single-source-of-truth for the Welle-1+2 fix-set)
# ---------------------------------------------------------------------------


SCHEMA_ID = "wakir.persona-engine.welle-1-2-doppel-telemetry.v1"

# Welle -> (domain, env-var) fix-set. Ordered so the dashboard panels
# render Welle-1 first, then Welle-2.
WELLE_FIX_SET: Tuple[Tuple[int, str, str], ...] = (
    (1, "v907_verify", "WAKIR_V907_VERIFY_BACKEND"),
    (2, "svid_workload_identity", "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"),
)

# ADR-0066 doppel-welle cap (informational; Tag-30's emitter enforces
# the cap). Surfaced here for the pair-aktiv-count panel.
DOPPEL_WELLE_CAP = 2

# 10s tick — operator-acceptance call needs near-real-time cadence.
DEFAULT_TICK_INTERVAL_SECONDS = 10

# 5-minute sliding window over BackendDecisions per welle.
DEFAULT_WINDOW_SECONDS = 300

# 0.5pp divergence -> rollback trigger (Henrik's tolerance band).
DEFAULT_DIVERGENCE_THRESHOLD_PCT = 0.5

# ENV var keys (importable for test surface)
ENV_PHASE_3C_OBS_BASELINE_PATH = "WAKIR_PHASE_3C_OBS_BASELINE_PATH"
ENV_BACKEND_DECISION_JSONL = "WAKIR_BACKEND_DECISION_JSONL"
ENV_PHASE_2_STRESS_OUTPUT = "WAKIR_PHASE_2_STRESS_OUTPUT"
ENV_PHASE_3C_WELLE_LIFECYCLE = "WAKIR_PHASE_3C_WELLE_LIFECYCLE"

# Pair label rendered on the combined-health-score Prometheus metrics.
PAIR_LABEL = "1+2"


class WelleState(enum.Enum):
    """Welle-1/2 lifecycle states (mirror Tag-30 vocabulary)."""

    PRE_CUTOVER = "pre_cutover"
    IN_CUTOVER = "in_cutover"
    POST_CUTOVER = "post_cutover"
    ROLLBACK_ACTIVE = "rollback_active"
    WELLE_COMPLETE = "welle_complete"


class StressOracleStatus(enum.Enum):
    """Phase-2-stress-test oracle status (mirrors Tag-30 cross-modul
    drift tri-state for dashboard consistency)."""

    GREEN = "green"
    RED = "red"
    YELLOW = "yellow"


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
    """Phase-2 cross-modul stress-test oracle payload (per welle)."""

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
class WelleTelemetry:
    """Single-welle telemetry block (Welle-1 or Welle-2)."""

    welle: int
    domain: str
    env_var: str
    welle_state: WelleState
    welle_aktiv: bool
    window_counts: WindowCounts
    consistency_score_pct: Optional[float]
    stress_oracle: StressOracle
    divergence_pct: Optional[float]
    divergence_red_flag: bool
    red_flag_reason: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "welle": self.welle,
            "domain": self.domain,
            "env_var": self.env_var,
            "welle_state": self.welle_state.value,
            "welle_aktiv": self.welle_aktiv,
            "window_counts": {
                "python_count": self.window_counts.python_count,
                "rust_count": self.window_counts.rust_count,
                "fallback_count": self.window_counts.fallback_count,
                "total": self.window_counts.total,
            },
            "consistency_score_pct": self.consistency_score_pct,
            "stress_oracle": self.stress_oracle.to_json(),
            "divergence_pct": self.divergence_pct,
            "divergence_red_flag": self.divergence_red_flag,
            "red_flag_reason": self.red_flag_reason,
        }


@dataclass(frozen=True)
class DoppelTelemetrySnapshot:
    """Full Welle-1+2 doppel telemetry snapshot."""

    schema_id: str
    generated_at: str
    pair_label: str
    window_seconds: int
    tick_interval_seconds: int
    divergence_threshold_pct: float
    welles: Tuple[WelleTelemetry, WelleTelemetry]
    combined_health_score_pct: Optional[float]
    combined_red_flag: bool
    combined_red_flag_reason: str
    pair_aktiv_count: int

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "generated_at": self.generated_at,
            "pair_label": self.pair_label,
            "window_seconds": self.window_seconds,
            "tick_interval_seconds": self.tick_interval_seconds,
            "divergence_threshold_pct": self.divergence_threshold_pct,
            "welles": [w.to_json() for w in self.welles],
            "combined_health_score_pct": self.combined_health_score_pct,
            "combined_red_flag": self.combined_red_flag,
            "combined_red_flag_reason": self.combined_red_flag_reason,
            "pair_aktiv_count": self.pair_aktiv_count,
            "doppel_welle_cap": DOPPEL_WELLE_CAP,
        }


# ---------------------------------------------------------------------------
# Path resolution (CLI > ENV > None) — shared shape with Tag-30 / Tag-31
# ---------------------------------------------------------------------------


def _resolve_path(
    cli_value: Optional[str], env_keys: List[str]
) -> Optional[Path]:
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
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# BackendDecision JSONL ingestion (one welle at a time)
# ---------------------------------------------------------------------------


def ingest_window_for_domain(
    path: Optional[Path],
    *,
    domain: str,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> Tuple[WindowCounts, int]:
    """Aggregate BackendDecisions for ``domain`` inside the sliding window.

    Returns ``(window_counts, parse_errors)``. Mirrors the Welle-3
    emitter's ``ingest_window`` but is parameterised by ``domain`` so
    one decision-log scan can score either welle.
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
                if rec.get("domain") != domain:
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
    """rust_count / total * 100. Returns None on no traffic."""

    total = counts.total
    if total == 0:
        return None
    return round((counts.rust_count / total) * 100.0, 4)


# ---------------------------------------------------------------------------
# Phase-2 cross-modul stress-test oracle (per welle)
# ---------------------------------------------------------------------------


def _coerce_score(score_raw: Any) -> Optional[float]:
    if score_raw is None:
        return None
    if isinstance(score_raw, bool):
        return None
    if isinstance(score_raw, (int, float)):
        s = float(score_raw)
        if math.isnan(s) or math.isinf(s):
            return None
        return s
    return None


def _oracle_from_entry(entry: Dict[str, Any]) -> StressOracle:
    """Build a StressOracle from one per-welle entry dict."""

    status_raw = entry.get("cross_modul_stress_status")
    score_pct = _coerce_score(entry.get("cross_modul_stress_score_pct"))

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


def load_stress_oracles(
    path: Optional[Path],
) -> Dict[int, StressOracle]:
    """Load per-welle Phase-2 cross-modul stress-test oracles.

    Schema (preferred, per-welle):

        {
          "per_welle": {
            "1": {"cross_modul_stress_status": "pass",
                  "cross_modul_stress_score_pct": 99.7},
            "2": {"cross_modul_stress_status": "pass",
                  "cross_modul_stress_score_pct": 98.4}
          }
        }

    Schema (legacy / single-status fallback, applied to both welles):

        {
          "cross_modul_stress_status": "pass",
          "cross_modul_stress_score_pct": 99.0
        }

    Returns a dict keyed by welle number ``{1: StressOracle, 2: StressOracle}``.
    Missing welles default to YELLOW with a diagnostic reason. The
    legacy fallback is the same status/score copied into both welle
    slots so the dashboard never goes blank on an old Phase-2 output.
    """

    welles = [w for w, _, _ in WELLE_FIX_SET]

    if path is None:
        reason = "phase-2-stress-output-not-configured"
        return {
            w: StressOracle(StressOracleStatus.YELLOW, None, reason)
            for w in welles
        }
    if not path.is_file():
        reason = "phase-2-stress-file-not-found"
        return {
            w: StressOracle(StressOracleStatus.YELLOW, None, reason)
            for w in welles
        }
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        reason = "phase-2-stress-parse-error"
        return {
            w: StressOracle(StressOracleStatus.YELLOW, None, reason)
            for w in welles
        }
    if not isinstance(obj, dict):
        reason = "phase-2-stress-root-not-object"
        return {
            w: StressOracle(StressOracleStatus.YELLOW, None, reason)
            for w in welles
        }

    per_welle = obj.get("per_welle")
    if isinstance(per_welle, dict):
        result: Dict[int, StressOracle] = {}
        for w in welles:
            entry = per_welle.get(str(w))
            if entry is None:
                entry = per_welle.get(w)
            if isinstance(entry, dict):
                result[w] = _oracle_from_entry(entry)
            else:
                result[w] = StressOracle(
                    StressOracleStatus.YELLOW,
                    None,
                    "phase-2-stress-welle-entry-missing",
                )
        return result

    # Legacy fallback: root-level cross_modul_* fields applied to both welles.
    legacy = _oracle_from_entry(obj)
    return {w: legacy for w in welles}


# ---------------------------------------------------------------------------
# Lifecycle (operator-hand state machine for Welle-1 and Welle-2)
# ---------------------------------------------------------------------------


def load_welle_lifecycle(
    path: Optional[Path],
) -> Dict[int, WelleState]:
    """Resolve per-welle lifecycle states from the operator-hand override.

    The override file is a flat ``{"<welle>": "<state>"}`` dict. We
    read keys ``"1"`` and ``"2"`` (or int 1/2). Missing welles default
    to PRE_CUTOVER. Malformed file degrades safely (both PRE_CUTOVER)
    rather than throwing.
    """

    welles = [w for w, _, _ in WELLE_FIX_SET]
    default = {w: WelleState.PRE_CUTOVER for w in welles}

    if path is None or not path.is_file():
        return default
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return default
    if not isinstance(obj, dict):
        return default

    valid = {s.value for s in WelleState}
    out: Dict[int, WelleState] = {}
    for w in welles:
        raw = obj.get(str(w))
        if raw is None:
            raw = obj.get(w)
        if isinstance(raw, str) and raw in valid:
            out[w] = WelleState(raw)
        else:
            out[w] = WelleState.PRE_CUTOVER
    return out


# ---------------------------------------------------------------------------
# Per-welle telemetry builder
# ---------------------------------------------------------------------------


def _build_welle_telemetry(
    *,
    welle: int,
    domain: str,
    env_var: str,
    decisions_path: Optional[Path],
    state: WelleState,
    oracle: StressOracle,
    window_seconds: int,
    divergence_threshold_pct: float,
    now: datetime,
) -> WelleTelemetry:
    counts, _parse_errors = ingest_window_for_domain(
        decisions_path,
        domain=domain,
        window_seconds=window_seconds,
        now=now,
    )
    consistency = compute_consistency_score_pct(counts)
    welle_aktiv = state in (
        WelleState.IN_CUTOVER,
        WelleState.ROLLBACK_ACTIVE,
    )

    divergence_pct: Optional[float]
    red_flag = False
    red_flag_reason: str

    if consistency is None:
        divergence_pct = None
        red_flag_reason = "consistency-score-no-traffic-in-window"
    elif oracle.score_pct is None:
        divergence_pct = None
        red_flag_reason = "stress-oracle-score-missing"
    else:
        divergence_pct = round(abs(consistency - oracle.score_pct), 4)
        if divergence_pct > divergence_threshold_pct:
            red_flag = True
            red_flag_reason = (
                f"divergence-{divergence_pct:.4f}pct-exceeds-"
                f"threshold-{divergence_threshold_pct:.4f}pct"
            )
        else:
            red_flag_reason = "ok"

    # Stress-oracle hard-fail overrides numeric divergence — same rule
    # as the Welle-3 emitter (Henrik's independent-oracle directive).
    if oracle.status == StressOracleStatus.RED and not red_flag:
        red_flag = True
        red_flag_reason = "stress-oracle-status-fail"

    return WelleTelemetry(
        welle=welle,
        domain=domain,
        env_var=env_var,
        welle_state=state,
        welle_aktiv=welle_aktiv,
        window_counts=counts,
        consistency_score_pct=consistency,
        stress_oracle=oracle,
        divergence_pct=divergence_pct,
        divergence_red_flag=red_flag,
        red_flag_reason=red_flag_reason,
    )


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
) -> DoppelTelemetrySnapshot:
    """Build a single Welle-1+2 doppel-telemetry snapshot."""

    if now is None:
        now = _now_utc()

    oracles = load_stress_oracles(phase2_stress_path)
    states = load_welle_lifecycle(lifecycle_path)

    welle_telemetries: List[WelleTelemetry] = []
    for welle, domain, env_var in WELLE_FIX_SET:
        wt = _build_welle_telemetry(
            welle=welle,
            domain=domain,
            env_var=env_var,
            decisions_path=decisions_path,
            state=states[welle],
            oracle=oracles[welle],
            window_seconds=window_seconds,
            divergence_threshold_pct=divergence_threshold_pct,
            now=now,
        )
        welle_telemetries.append(wt)

    # Combined health-score: min of the two self-scores when both are
    # defined; None when either is None.
    scores = [w.consistency_score_pct for w in welle_telemetries]
    if all(s is not None for s in scores):
        combined_health_score_pct: Optional[float] = round(
            min(s for s in scores if s is not None), 4
        )
    else:
        combined_health_score_pct = None

    # Combined red-flag: any per-welle red-flag fires the combined flag.
    red_welles = [w for w in welle_telemetries if w.divergence_red_flag]
    if red_welles:
        combined_red_flag = True
        combined_red_flag_reason = (
            "welle-"
            + "+".join(str(w.welle) for w in red_welles)
            + "-red-flag"
        )
    else:
        combined_red_flag = False
        combined_red_flag_reason = "ok"

    pair_aktiv_count = sum(1 for w in welle_telemetries if w.welle_aktiv)

    return DoppelTelemetrySnapshot(
        schema_id=SCHEMA_ID,
        generated_at=now.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        pair_label=PAIR_LABEL,
        window_seconds=window_seconds,
        tick_interval_seconds=tick_interval_seconds,
        divergence_threshold_pct=divergence_threshold_pct,
        welles=(welle_telemetries[0], welle_telemetries[1]),
        combined_health_score_pct=combined_health_score_pct,
        combined_red_flag=combined_red_flag,
        combined_red_flag_reason=combined_red_flag_reason,
        pair_aktiv_count=pair_aktiv_count,
    )


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def _fmt_float(v: Optional[float]) -> str:
    if v is None:
        return "NaN"
    return f"{v:g}"


def _render_per_welle_metrics(
    snap: DoppelTelemetrySnapshot, wt: WelleTelemetry
) -> List[str]:
    lines: List[str] = []
    base_labels = f'welle="{wt.welle}",domain="{wt.domain}",pair="{snap.pair_label}"'

    lines.append(
        f'persona_engine_doppel_welle_consistency_score{{{base_labels}}} '
        f'{_fmt_float(wt.consistency_score_pct)}'
    )
    lines.append(
        f'persona_engine_doppel_welle_stress_oracle_score{{{base_labels},'
        f'status="{wt.stress_oracle.status.value}"}} '
        f'{_fmt_float(wt.stress_oracle.score_pct)}'
    )
    lines.append(
        f'persona_engine_doppel_welle_divergence_pct{{{base_labels}}} '
        f'{_fmt_float(wt.divergence_pct)}'
    )
    lines.append(
        f'persona_engine_doppel_welle_divergence_red_flag{{{base_labels},'
        f'reason="{wt.red_flag_reason}"}} '
        f'{1 if wt.divergence_red_flag else 0}'
    )
    lines.append(
        f'persona_engine_doppel_welle_window_python_count{{{base_labels}}} '
        f'{wt.window_counts.python_count}'
    )
    lines.append(
        f'persona_engine_doppel_welle_window_rust_count{{{base_labels}}} '
        f'{wt.window_counts.rust_count}'
    )
    lines.append(
        f'persona_engine_doppel_welle_window_fallback_count{{{base_labels}}} '
        f'{wt.window_counts.fallback_count}'
    )
    lines.append(
        f'persona_engine_doppel_welle_window_seconds{{{base_labels}}} '
        f'{snap.window_seconds}'
    )
    lines.append(
        f'persona_engine_doppel_welle_tick_interval_seconds{{{base_labels}}} '
        f'{snap.tick_interval_seconds}'
    )
    lines.append(
        f'persona_engine_doppel_welle_divergence_threshold_pct{{{base_labels}}} '
        f'{snap.divergence_threshold_pct:g}'
    )
    lines.append(
        f'persona_engine_doppel_welle_aktiv{{{base_labels},'
        f'state="{wt.welle_state.value}"}} '
        f'{1 if wt.welle_aktiv else 0}'
    )
    return lines


def render_prometheus_textfile(snapshot: DoppelTelemetrySnapshot) -> str:
    """Render the doppel snapshot as a Prometheus node-exporter textfile.

    Per-welle metrics are emitted twice (once per welle, with stable
    ``welle`` and ``domain`` labels). Combined metrics carry the
    ``pair="1+2"`` label. All gauges. None -> NaN per spec.
    """

    lines: List[str] = []

    # HELP / TYPE preamble — one block per metric name.
    helps: List[Tuple[str, str, str]] = [
        (
            "persona_engine_doppel_welle_consistency_score",
            "gauge",
            "Per-welle self-consistency score (rust_count/total*100) for the KW-24 Welle-1+2 doppel-cutover.",
        ),
        (
            "persona_engine_doppel_welle_stress_oracle_score",
            "gauge",
            "Per-welle Phase-2 cross-modul stress-test oracle score (percent).",
        ),
        (
            "persona_engine_doppel_welle_divergence_pct",
            "gauge",
            "Absolute |self - oracle| in percentage points, per welle.",
        ),
        (
            "persona_engine_doppel_welle_divergence_red_flag",
            "gauge",
            "1 iff per-welle divergence exceeds the configured threshold OR oracle status RED.",
        ),
        (
            "persona_engine_doppel_welle_window_python_count",
            "gauge",
            "Per-welle BackendDecision count in the sliding window where chosen_backend=python.",
        ),
        (
            "persona_engine_doppel_welle_window_rust_count",
            "gauge",
            "Per-welle BackendDecision count in the sliding window where chosen_backend=rust.",
        ),
        (
            "persona_engine_doppel_welle_window_fallback_count",
            "gauge",
            "Per-welle BackendDecision count in the sliding window where fallback_reason was set.",
        ),
        (
            "persona_engine_doppel_welle_window_seconds",
            "gauge",
            "Per-welle sliding-window length in seconds (mirror, for dashboard parity).",
        ),
        (
            "persona_engine_doppel_welle_tick_interval_seconds",
            "gauge",
            "Per-welle emitter tick interval (operator-cadence target).",
        ),
        (
            "persona_engine_doppel_welle_divergence_threshold_pct",
            "gauge",
            "Configured per-welle divergence threshold in percentage points.",
        ),
        (
            "persona_engine_doppel_welle_aktiv",
            "gauge",
            "1 iff a welle's lifecycle state is in_cutover or rollback_active.",
        ),
        (
            "persona_engine_doppel_welle_combined_health_score",
            "gauge",
            "Combined doppel-welle health-score: min(self-score over welles) when both defined.",
        ),
        (
            "persona_engine_doppel_welle_combined_red_flag",
            "gauge",
            "1 iff ANY per-welle red-flag fired during the doppel-week.",
        ),
        (
            "persona_engine_doppel_welle_pair_aktiv_count",
            "gauge",
            "Count of welles in the pair currently in_cutover or rollback_active.",
        ),
    ]
    for name, kind, help_text in helps:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")

    # Per-welle samples
    for wt in snapshot.welles:
        lines.extend(_render_per_welle_metrics(snapshot, wt))

    # Combined samples
    pair_labels = f'pair="{snapshot.pair_label}"'
    lines.append(
        f'persona_engine_doppel_welle_combined_health_score{{{pair_labels}}} '
        f'{_fmt_float(snapshot.combined_health_score_pct)}'
    )
    lines.append(
        f'persona_engine_doppel_welle_combined_red_flag{{{pair_labels},'
        f'reason="{snapshot.combined_red_flag_reason}"}} '
        f'{1 if snapshot.combined_red_flag else 0}'
    )
    lines.append(
        f'persona_engine_doppel_welle_pair_aktiv_count{{{pair_labels}}} '
        f'{snapshot.pair_aktiv_count}'
    )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="welle-1-2-doppel-telemetry-emitter",
        description=(
            "Emit Welle-1+2 (v907_verify + svid_workload_identity) doppel "
            "high-frequency telemetry for the KW-24 cutover week (ADR-0066 "
            "Day-0 Observability)."
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
        help="Tick interval (informational). Default 10s.",
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
        help="Per-welle red-flag threshold in percentage points. Default 0.5.",
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
            "welle-1-2-doppel-telemetry-emitter: tick-interval-seconds must be > 0",
            file=sys.stderr,
        )
        return 2
    if args.window_seconds <= 0:
        print(
            "welle-1-2-doppel-telemetry-emitter: window-seconds must be > 0",
            file=sys.stderr,
        )
        return 2
    if args.divergence_threshold_pct < 0:
        print(
            "welle-1-2-doppel-telemetry-emitter: divergence-threshold-pct must be >= 0",
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

    return 1 if snapshot.combined_red_flag else 0


if __name__ == "__main__":
    sys.exit(main())
