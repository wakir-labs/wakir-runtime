#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""phase-3c-welle-status-emitter — Tag-30 Mini-Welle per-welle live status.

Background
----------

ADR-0066 (2026-05-17) accelerated the Phase-3c cutover sequence from
7 weeks to 4 weeks by allowing pairs of welles to run in parallel
(Welle-1+2 KW 24, Welle-3 solo KW 25, Welle-4+5 KW 26, Welle-6+7
KW 27). The trigger-gate aggregator
(``scripts/phase-3c-trigger-gate-aggregator.py``) gives operators a
pre-flight readiness check; the observability baseline tracker
(``scripts/phase-3c-observability-baseline-tracker.py``) reports the
multi-day burn-up of BackendDecision evidence. Neither of those
answers the question an operator actually has during the cutover
week:

  * **Where is each welle right now?** — pre-cutover (gates not all
    green), in-cutover (cutover-day live, Phase-2-Acceptance-Gate
    actively scoring), post-cutover (cutover-day done, soak window
    open), rollback-active (a welle has tripped its rollback gate),
    or welle-complete (soak passed, welle closed).
  * **How many welles are active concurrently?** — ADR-0066 caps this
    at two for doppel-welle weeks; a third concurrent welle is an
    immediate red.
  * **What is the per-welle python-vs-rust BackendDecision split?**
    — the substantive fitness signal that says the welle's Rust
    binary is actually carrying the production path.
  * **Where is the cross-modul drift signal?** — for doppel-welle
    weeks (4+5, 6+7), a Cross-Modul-Pin failure trips the rollback
    gate. The dashboard needs a single panel that turns red when
    *any* doppel-welle pair shows pin-drift.

This emitter is the substrate behind the
``dashboards/persona-engine-phase-3c-welle-status.json`` Grafana
dashboard. It produces a single JSON snapshot per invocation:

  * **Per-welle state:** one of ``pre_cutover``, ``in_cutover``,
    ``post_cutover``, ``rollback_active``, ``welle_complete``.
  * **Per-welle BackendDecision split:** python_count, rust_count,
    fallback_count, python_rate, rust_rate, fallback_rate.
  * **Per-welle latency comparison:** p50 / p95 / p99 for python
    vs. rust (from the optional ``resolution_latency_us`` field on
    BackendDecision records).
  * **Marathon-progress gauge:** count of ``welle_complete`` welles
    divided by 7 (the ADR-0065 welle inventory).
  * **Welle-aktiv counter:** count of welles currently in
    ``in_cutover`` OR ``rollback_active``. Capped expectation = 2 for
    doppel-welle weeks; the dashboard surfaces a red panel when the
    counter exceeds the cap.
  * **Cross-Modul-Drift indicator:** boolean from the optional
    Phase-2-Acceptance-Gate output (``cross_modul_pin_status`` field
    or its absence). Red when fail, green when pass, yellow when
    Phase-2-Acceptance-Gate output is missing.

Posture
-------

Stdlib-only. No cosign / podman / systemctl / NATS invocation. No
network. Reads two on-disk inputs (BackendDecision JSONL +
Phase-2-Acceptance-Gate JSON), emits one JSON snapshot. The Grafana
dashboard scrapes either a Prometheus Pushgateway (live deployment)
or a static file under ``$PWD/var/phase-3c-welle-status.json``
(workstation / dry-run).

The seven welles are pinned to a static inventory matching
ADR-0065 §Empfehlung as overridden by ADR-0066 §Welle-Sequenz:

  1. v907_verify          (KW 24, parallel with welle-2)
  2. svid_workload_identity (KW 24, parallel with welle-1)
  3. bridge_audit_writer   (KW 25, solo)
  4. state_backing         (KW 26, parallel with welle-5)
  5. lifecycle_state_machine (KW 26, parallel with welle-4)
  6. subscribe_loop        (KW 27, parallel with welle-7)
  7. recovery_workflow     (KW 27, parallel with welle-6)

The mapping between welle-number and BackendDecision ``domain``
field is fixed in :data:`WELLE_DOMAIN_MAP` below. Adding an eighth
welle requires editing the map (and ADR-0065 / ADR-0066).

ENV contract
------------

Same JSONL-path resolution as the Tag-25 baseline tracker:

  1. ``--decisions-jsonl PATH`` CLI flag.
  2. ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV (shared with the
     Tag-24 Gate-4 aggregator).
  3. ``WAKIR_BACKEND_DECISION_JSONL`` ENV.

For the Phase-2-Acceptance-Gate signal:

  1. ``--phase2-acceptance-json PATH`` CLI flag.
  2. ``WAKIR_PHASE_2_ACCEPTANCE_OUTPUT`` ENV.

For the welle-lifecycle override file (operator-hand state-machine):

  1. ``--lifecycle-json PATH`` CLI flag.
  2. ``WAKIR_PHASE_3C_WELLE_LIFECYCLE`` ENV.

The lifecycle file is a small JSON map ``{<welle-num>: <state>}``
that the operator writes by hand at the start of each cutover-day
(``in_cutover``), at the end of the cutover-day
(``post_cutover``), when a rollback is triggered
(``rollback_active``), and when the soak passes
(``welle_complete``). When the file is absent, every welle defaults
to ``pre_cutover``. The dashboard does NOT auto-advance the lifecycle
— that stays operator-hand per the sandbox-host-trennung discipline
(``feedback_sandbox_host_trennung.md``).

Usage
-----

::

    # Stdout JSON, exit-code reflects status.
    python scripts/phase-3c-welle-status-emitter.py

    # Write the snapshot to a file (workstation pattern).
    python scripts/phase-3c-welle-status-emitter.py \
        --out var/phase-3c-welle-status.json

    # Operator-hand override for the lifecycle map.
    python scripts/phase-3c-welle-status-emitter.py \
        --lifecycle-json /var/lib/wakir/phase-3c-welle-lifecycle.json

Exit-code semantics
-------------------

  * ``0`` — emitter ran cleanly; per-welle states + counters
    computed. Snapshot validity is the dashboard's call.
  * ``1`` — at least one welle reported ``rollback_active``, OR the
    welle-aktiv counter exceeded the doppel-welle cap of 2.
  * ``2`` — input-file resolution failed (no path for the JSONL),
    OR an invalid lifecycle state appeared in the override file.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import re
import sys
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants — welle inventory + ENV names
# ---------------------------------------------------------------------------


SCHEMA_ID = "wakir.phase-3c.welle-status-emitter/1"


#: Maximum welles that may be ``in_cutover`` OR ``rollback_active``
#: concurrently per ADR-0066 §Welle-Parallelitaet. Bridge-Audit
#: (Welle-3) bleibt solo; alle anderen Wochen erlauben 2 parallel.
DOPPEL_WELLE_CAP = 2


#: Total welles in the ADR-0065 cutover sequence (used for the
#: marathon-progress gauge denominator).
WELLE_TOTAL = 7


#: Pinned welle inventory. The ``domain`` field must match the
#: BackendDecision ``domain`` value the persona-engine emits for
#: that component. Adding an eighth welle requires editing this map.
WELLE_DOMAIN_MAP: Dict[int, Dict[str, str]] = {
    1: {
        "domain": "v907_verify",
        "kw": "KW 24",
        "pair": "welle-2",
    },
    2: {
        "domain": "svid_workload_identity",
        "kw": "KW 24",
        "pair": "welle-1",
    },
    3: {
        "domain": "bridge_audit_writer",
        "kw": "KW 25",
        "pair": "solo",
    },
    4: {
        "domain": "state_backing",
        "kw": "KW 26",
        "pair": "welle-5",
    },
    5: {
        "domain": "lifecycle_state_machine",
        "kw": "KW 26",
        "pair": "welle-4",
    },
    6: {
        "domain": "subscribe_loop",
        "kw": "KW 27",
        "pair": "welle-7",
    },
    7: {
        "domain": "recovery_workflow",
        "kw": "KW 27",
        "pair": "welle-6",
    },
}


ENV_PHASE_3C_OBS_BASELINE_PATH = "WAKIR_PHASE_3C_OBS_BASELINE_PATH"
ENV_BACKEND_DECISION_JSONL = "WAKIR_BACKEND_DECISION_JSONL"
ENV_PHASE_2_ACCEPTANCE_OUTPUT = "WAKIR_PHASE_2_ACCEPTANCE_OUTPUT"
ENV_PHASE_3C_WELLE_LIFECYCLE = "WAKIR_PHASE_3C_WELLE_LIFECYCLE"


BACKEND_DECISION_MSG = "backend-decision"

_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# ---------------------------------------------------------------------------
# Lifecycle state enum
# ---------------------------------------------------------------------------


class WelleState(str, enum.Enum):
    """Per-welle lifecycle state. String-enum for JSON round-trip."""

    PRE_CUTOVER = "pre_cutover"
    IN_CUTOVER = "in_cutover"
    POST_CUTOVER = "post_cutover"
    ROLLBACK_ACTIVE = "rollback_active"
    WELLE_COMPLETE = "welle_complete"


#: States that count toward the welle-aktiv counter (the cap).
ACTIVE_STATES = frozenset(
    {WelleState.IN_CUTOVER, WelleState.ROLLBACK_ACTIVE}
)


#: States that count as "done" for the marathon-progress gauge.
COMPLETE_STATES = frozenset({WelleState.WELLE_COMPLETE})


class CrossModulDriftStatus(str, enum.Enum):
    """Tri-state cross-modul-drift indicator."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# ---------------------------------------------------------------------------
# Result-types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LatencyStats:
    """Backend-comparison latency stats. All values microseconds.

    ``count`` may be 0 (no records for this backend/welle); percentiles
    are then None. The emitter never invents a latency value.
    """

    count: int
    p50_us: Optional[float]
    p95_us: Optional[float]
    p99_us: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "p50_us": self.p50_us,
            "p95_us": self.p95_us,
            "p99_us": self.p99_us,
        }


@dataclasses.dataclass(frozen=True)
class WelleStatus:
    """Per-welle snapshot row."""

    welle: int
    domain: str
    kw: str
    pair: str
    state: WelleState
    python_count: int
    rust_count: int
    other_count: int
    fallback_count: int
    total_decisions: int
    python_latency: LatencyStats
    rust_latency: LatencyStats

    @property
    def python_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.python_count / self.total_decisions

    @property
    def rust_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.rust_count / self.total_decisions

    @property
    def fallback_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.fallback_count / self.total_decisions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "welle": self.welle,
            "domain": self.domain,
            "kw": self.kw,
            "pair": self.pair,
            "state": self.state.value,
            "python_count": self.python_count,
            "rust_count": self.rust_count,
            "other_count": self.other_count,
            "fallback_count": self.fallback_count,
            "total_decisions": self.total_decisions,
            "python_rate": round(self.python_rate, 6),
            "rust_rate": round(self.rust_rate, 6),
            "fallback_rate": round(self.fallback_rate, 6),
            "python_latency": self.python_latency.to_dict(),
            "rust_latency": self.rust_latency.to_dict(),
        }


@dataclasses.dataclass(frozen=True)
class WelleStatusSnapshot:
    """Top-level emitter snapshot."""

    schema: str
    decisions_jsonl_path: Optional[str]
    phase2_acceptance_path: Optional[str]
    lifecycle_path: Optional[str]
    welles: List[WelleStatus]
    marathon_progress_pct: float
    welle_aktiv_count: int
    doppel_welle_cap: int
    cap_exceeded: bool
    cross_modul_drift: CrossModulDriftStatus
    cross_modul_reason: str
    exit_code: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "decisions_jsonl_path": self.decisions_jsonl_path,
            "phase2_acceptance_path": self.phase2_acceptance_path,
            "lifecycle_path": self.lifecycle_path,
            "welles": [w.to_dict() for w in self.welles],
            "marathon_progress_pct": round(self.marathon_progress_pct, 4),
            "welle_aktiv_count": self.welle_aktiv_count,
            "doppel_welle_cap": self.doppel_welle_cap,
            "cap_exceeded": self.cap_exceeded,
            "cross_modul_drift": self.cross_modul_drift.value,
            "cross_modul_reason": self.cross_modul_reason,
            "exit_code": self.exit_code,
        }


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_decisions_jsonl_path(
    cli_path: Optional[str],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Resolve the BackendDecision JSONL path.

    Priority order matches the Tag-25 baseline tracker.
    """

    env_map = env if env is not None else os.environ
    if cli_path and cli_path.strip():
        return Path(cli_path.strip())
    for key in (
        ENV_PHASE_3C_OBS_BASELINE_PATH,
        ENV_BACKEND_DECISION_JSONL,
    ):
        val = env_map.get(key)
        if isinstance(val, str) and val.strip():
            return Path(val.strip())
    return None


def resolve_phase2_acceptance_path(
    cli_path: Optional[str],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Resolve the Phase-2-Acceptance-Gate output JSON path."""

    env_map = env if env is not None else os.environ
    if cli_path and cli_path.strip():
        return Path(cli_path.strip())
    val = env_map.get(ENV_PHASE_2_ACCEPTANCE_OUTPUT)
    if isinstance(val, str) and val.strip():
        return Path(val.strip())
    return None


def resolve_lifecycle_path(
    cli_path: Optional[str],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Resolve the welle-lifecycle override JSON path."""

    env_map = env if env is not None else os.environ
    if cli_path and cli_path.strip():
        return Path(cli_path.strip())
    val = env_map.get(ENV_PHASE_3C_WELLE_LIFECYCLE)
    if isinstance(val, str) and val.strip():
        return Path(val.strip())
    return None


# ---------------------------------------------------------------------------
# JSONL ingestion (BackendDecision)
# ---------------------------------------------------------------------------


def _is_backend_decision_record(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    msg = obj.get("msg")
    if msg is None:
        return True
    return msg == BACKEND_DECISION_MSG


def _normalise_backend(value: Any) -> str:
    if value is None or not isinstance(value, str):
        return "backend_unknown"
    stripped = value.strip().lower()
    return stripped if stripped else "backend_unknown"


def _backend_family(chosen: str) -> str:
    if chosen == "python":
        return "python"
    if chosen.startswith("rust"):
        return "rust"
    return "other"


def _has_fallback(record: Mapping[str, Any]) -> bool:
    reason = record.get("fallback_reason")
    return isinstance(reason, str) and bool(reason.strip())


def _extract_latency_us(record: Mapping[str, Any]) -> Optional[float]:
    val = record.get("resolution_latency_us")
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)) and val >= 0:
        return float(val)
    return None


@dataclasses.dataclass
class _WelleAccumulator:
    """Mutable in-flight per-welle state during JSONL ingestion."""

    python_count: int = 0
    rust_count: int = 0
    other_count: int = 0
    fallback_count: int = 0
    python_latencies: List[float] = dataclasses.field(default_factory=list)
    rust_latencies: List[float] = dataclasses.field(default_factory=list)

    @property
    def total(self) -> int:
        return self.python_count + self.rust_count + self.other_count


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Compute the ``pct`` percentile of ``values`` (0 < pct <= 100).

    Stdlib-only nearest-rank percentile. Returns None for empty list.
    """

    if not values:
        return None
    if pct <= 0 or pct > 100:
        raise ValueError(f"percentile out of range: {pct}")
    s = sorted(values)
    # Nearest-rank: index = ceil(pct/100 * N) - 1, clamped to [0, N-1].
    n = len(s)
    rank = int((pct / 100.0) * n)
    if rank == 0:
        rank = 1
    if rank > n:
        rank = n
    return s[rank - 1]


def _build_latency_stats(values: List[float]) -> LatencyStats:
    if not values:
        return LatencyStats(count=0, p50_us=None, p95_us=None, p99_us=None)
    return LatencyStats(
        count=len(values),
        p50_us=median(values),
        p95_us=_percentile(values, 95.0),
        p99_us=_percentile(values, 99.0),
    )


def ingest_decisions(
    path: Optional[Path],
) -> Tuple[Dict[str, _WelleAccumulator], int]:
    """Ingest the BackendDecision JSONL into per-domain accumulators.

    Returns a ``(by_domain, parse_errors)`` tuple. ``by_domain`` is
    keyed by the persona-engine ``domain`` field. Unknown domains
    are still tallied so the dashboard's "uncategorised welle" count
    panel surfaces drift.
    """

    by_domain: Dict[str, _WelleAccumulator] = {}
    parse_errors = 0

    if path is None or not path.is_file():
        return by_domain, parse_errors

    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                parse_errors += 1
                continue
            if not _is_backend_decision_record(obj):
                parse_errors += 1
                continue
            domain = obj.get("domain")
            if not isinstance(domain, str) or not domain.strip():
                parse_errors += 1
                continue
            acc = by_domain.setdefault(domain.strip(), _WelleAccumulator())
            chosen = _normalise_backend(obj.get("chosen_backend"))
            family = _backend_family(chosen)
            if family == "python":
                acc.python_count += 1
            elif family == "rust":
                acc.rust_count += 1
            else:
                acc.other_count += 1
            if _has_fallback(obj):
                acc.fallback_count += 1
            lat = _extract_latency_us(obj)
            if lat is not None:
                if family == "python":
                    acc.python_latencies.append(lat)
                elif family == "rust":
                    acc.rust_latencies.append(lat)

    return by_domain, parse_errors


# ---------------------------------------------------------------------------
# Lifecycle override ingestion
# ---------------------------------------------------------------------------


def load_lifecycle(path: Optional[Path]) -> Dict[int, WelleState]:
    """Load the welle-lifecycle override JSON.

    Schema: ``{ "1": "in_cutover", "2": "pre_cutover", ... }``. Keys
    may be ints or strings. Missing welles default to PRE_CUTOVER.

    Raises ValueError on:
      * non-object root
      * unknown welle number (outside 1..WELLE_TOTAL)
      * unknown lifecycle state string

    Returns the override map ONLY (no defaulting); the caller merges
    with the welle inventory.
    """

    if path is None or not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        raise ValueError(f"lifecycle JSON parse failure: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"lifecycle JSON root must be an object, got {type(raw).__name__}"
        )

    out: Dict[int, WelleState] = {}
    valid_states = {s.value for s in WelleState}

    for k, v in raw.items():
        try:
            welle_num = int(k)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"lifecycle JSON key not int-coercible: {k!r}"
            ) from exc
        if welle_num < 1 or welle_num > WELLE_TOTAL:
            raise ValueError(
                f"lifecycle JSON welle out of range 1..{WELLE_TOTAL}: {welle_num}"
            )
        if not isinstance(v, str) or v not in valid_states:
            raise ValueError(
                f"lifecycle JSON welle={welle_num} state invalid: {v!r}"
            )
        out[welle_num] = WelleState(v)

    return out


# ---------------------------------------------------------------------------
# Phase-2-Acceptance-Gate ingestion
# ---------------------------------------------------------------------------


def load_cross_modul_drift(
    path: Optional[Path],
) -> Tuple[CrossModulDriftStatus, str]:
    """Inspect the Phase-2-Acceptance-Gate output for cross-modul-drift.

    The Phase-2-Acceptance-Gate (PR #178 + ADR-0066 Mitigation-1)
    emits a JSON file with a ``cross_modul_pin_status`` field whose
    value is one of ``pass`` / ``fail`` / ``skipped``. The mapping:

      * ``pass``    -> GREEN
      * ``fail``    -> RED
      * ``skipped`` -> YELLOW
      * anything else / missing field / file missing -> YELLOW

    Yellow is the conservative default: an absent file is a
    "no-signal" condition, not a green stamp. This matches the
    Gate-4 yellow-tolerance discipline in the
    ``phase-3c-welle-1-validation.yml`` workflow.
    """

    if path is None:
        return (CrossModulDriftStatus.YELLOW, "phase-2-acceptance-output-not-configured")
    if not path.is_file():
        return (CrossModulDriftStatus.YELLOW, "phase-2-acceptance-file-not-found")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return (CrossModulDriftStatus.YELLOW, "phase-2-acceptance-parse-error")
    if not isinstance(obj, dict):
        return (CrossModulDriftStatus.YELLOW, "phase-2-acceptance-root-not-object")
    status = obj.get("cross_modul_pin_status")
    if status == "pass":
        return (CrossModulDriftStatus.GREEN, "cross-modul-pin-pass")
    if status == "fail":
        return (CrossModulDriftStatus.RED, "cross-modul-pin-fail")
    if status == "skipped":
        return (CrossModulDriftStatus.YELLOW, "cross-modul-pin-skipped")
    return (CrossModulDriftStatus.YELLOW, "cross-modul-pin-status-missing-or-unknown")


# ---------------------------------------------------------------------------
# Public API: build_snapshot
# ---------------------------------------------------------------------------


def build_snapshot(
    *,
    decisions_path: Optional[Path],
    phase2_path: Optional[Path],
    lifecycle_path: Optional[Path],
) -> WelleStatusSnapshot:
    """Build a single WelleStatusSnapshot from on-disk inputs.

    Per the docstring contract: never invents latency values, never
    auto-advances the lifecycle, never silently drops malformed
    JSONL records (they go into the parse-errors count via
    :func:`ingest_decisions`).
    """

    by_domain, _parse_errors = ingest_decisions(decisions_path)
    lifecycle_override = load_lifecycle(lifecycle_path)
    drift, drift_reason = load_cross_modul_drift(phase2_path)

    welles: List[WelleStatus] = []
    for welle_num in sorted(WELLE_DOMAIN_MAP.keys()):
        meta = WELLE_DOMAIN_MAP[welle_num]
        domain = meta["domain"]
        acc = by_domain.get(domain, _WelleAccumulator())
        state = lifecycle_override.get(welle_num, WelleState.PRE_CUTOVER)
        welles.append(
            WelleStatus(
                welle=welle_num,
                domain=domain,
                kw=meta["kw"],
                pair=meta["pair"],
                state=state,
                python_count=acc.python_count,
                rust_count=acc.rust_count,
                other_count=acc.other_count,
                fallback_count=acc.fallback_count,
                total_decisions=acc.total,
                python_latency=_build_latency_stats(acc.python_latencies),
                rust_latency=_build_latency_stats(acc.rust_latencies),
            )
        )

    welle_aktiv_count = sum(
        1 for w in welles if w.state in ACTIVE_STATES
    )
    welle_complete_count = sum(
        1 for w in welles if w.state in COMPLETE_STATES
    )
    marathon_progress_pct = (
        100.0 * welle_complete_count / WELLE_TOTAL
        if WELLE_TOTAL > 0
        else 0.0
    )
    cap_exceeded = welle_aktiv_count > DOPPEL_WELLE_CAP
    rollback_active_any = any(
        w.state == WelleState.ROLLBACK_ACTIVE for w in welles
    )

    if cap_exceeded or rollback_active_any:
        exit_code = 1
    else:
        exit_code = 0

    return WelleStatusSnapshot(
        schema=SCHEMA_ID,
        decisions_jsonl_path=str(decisions_path) if decisions_path else None,
        phase2_acceptance_path=str(phase2_path) if phase2_path else None,
        lifecycle_path=str(lifecycle_path) if lifecycle_path else None,
        welles=welles,
        marathon_progress_pct=marathon_progress_pct,
        welle_aktiv_count=welle_aktiv_count,
        doppel_welle_cap=DOPPEL_WELLE_CAP,
        cap_exceeded=cap_exceeded,
        cross_modul_drift=drift,
        cross_modul_reason=drift_reason,
        exit_code=exit_code,
    )


# ---------------------------------------------------------------------------
# Prometheus textfile emit
# ---------------------------------------------------------------------------


def render_prometheus_textfile(snapshot: WelleStatusSnapshot) -> str:
    """Render the snapshot as Prometheus textfile-collector format.

    The output is suitable for either the node-exporter textfile
    collector or for direct ``curl --data-binary`` upload to a
    Prometheus Pushgateway. Schema-version stable: metric names
    listed below MUST remain stable for the Grafana dashboard to
    keep working.

    Emitted metric families:

      * ``persona_engine_phase_3c_welle_state{welle, domain, state}``
        — 1.0 for the current state of each welle, 0.0 for other
        states (long-form). Lets the dashboard panel select on
        ``state="in_cutover"`` etc.
      * ``persona_engine_phase_3c_welle_decisions_total{welle, domain, backend}``
        — counter-style gauge (NOT a real counter; the JSONL is
        rewritten, not appended-to with monotonic reset semantics).
      * ``persona_engine_phase_3c_welle_fallback_total{welle, domain}``
      * ``persona_engine_phase_3c_welle_latency_us{welle, domain, backend, quantile}``
      * ``persona_engine_phase_3c_marathon_progress_pct``
      * ``persona_engine_phase_3c_welle_aktiv_count``
      * ``persona_engine_phase_3c_doppel_welle_cap``
      * ``persona_engine_phase_3c_cap_exceeded``
      * ``persona_engine_phase_3c_cross_modul_drift{status}``
    """

    lines: List[str] = []

    lines.append(
        "# HELP persona_engine_phase_3c_welle_state Per-welle current "
        "lifecycle state (long-form one-hot)."
    )
    lines.append("# TYPE persona_engine_phase_3c_welle_state gauge")
    for w in snapshot.welles:
        for s in WelleState:
            v = 1.0 if w.state == s else 0.0
            lines.append(
                f'persona_engine_phase_3c_welle_state{{welle="{w.welle}",'
                f'domain="{w.domain}",state="{s.value}"}} {v}'
            )

    lines.append(
        "# HELP persona_engine_phase_3c_welle_decisions_total Per-welle "
        "BackendDecision counts by backend family."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_welle_decisions_total gauge"
    )
    for w in snapshot.welles:
        for backend, count in (
            ("python", w.python_count),
            ("rust", w.rust_count),
            ("other", w.other_count),
        ):
            lines.append(
                f'persona_engine_phase_3c_welle_decisions_total{{welle="{w.welle}",'
                f'domain="{w.domain}",backend="{backend}"}} {count}'
            )

    lines.append(
        "# HELP persona_engine_phase_3c_welle_fallback_total Per-welle "
        "fallback-record count."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_welle_fallback_total gauge"
    )
    for w in snapshot.welles:
        lines.append(
            f'persona_engine_phase_3c_welle_fallback_total{{welle="{w.welle}",'
            f'domain="{w.domain}"}} {w.fallback_count}'
        )

    lines.append(
        "# HELP persona_engine_phase_3c_welle_latency_us Per-welle "
        "resolution-latency percentiles in microseconds."
    )
    lines.append("# TYPE persona_engine_phase_3c_welle_latency_us gauge")
    for w in snapshot.welles:
        for backend, stats in (
            ("python", w.python_latency),
            ("rust", w.rust_latency),
        ):
            for qname, qval in (
                ("0.5", stats.p50_us),
                ("0.95", stats.p95_us),
                ("0.99", stats.p99_us),
            ):
                if qval is None:
                    continue
                lines.append(
                    f'persona_engine_phase_3c_welle_latency_us{{welle="{w.welle}",'
                    f'domain="{w.domain}",backend="{backend}",'
                    f'quantile="{qname}"}} {qval}'
                )

    lines.append(
        "# HELP persona_engine_phase_3c_marathon_progress_pct Percent of "
        "welles in welle_complete state, 0..100."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_marathon_progress_pct gauge"
    )
    lines.append(
        f"persona_engine_phase_3c_marathon_progress_pct "
        f"{snapshot.marathon_progress_pct}"
    )

    lines.append(
        "# HELP persona_engine_phase_3c_welle_aktiv_count Welles currently "
        "in_cutover or rollback_active."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_welle_aktiv_count gauge"
    )
    lines.append(
        f"persona_engine_phase_3c_welle_aktiv_count "
        f"{snapshot.welle_aktiv_count}"
    )

    lines.append(
        "# HELP persona_engine_phase_3c_doppel_welle_cap ADR-0066 cap on "
        "concurrent active welles."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_doppel_welle_cap gauge"
    )
    lines.append(
        f"persona_engine_phase_3c_doppel_welle_cap "
        f"{snapshot.doppel_welle_cap}"
    )

    lines.append(
        "# HELP persona_engine_phase_3c_cap_exceeded 1.0 when welle_aktiv_count > "
        "doppel_welle_cap, else 0.0."
    )
    lines.append("# TYPE persona_engine_phase_3c_cap_exceeded gauge")
    lines.append(
        f"persona_engine_phase_3c_cap_exceeded "
        f"{1.0 if snapshot.cap_exceeded else 0.0}"
    )

    lines.append(
        "# HELP persona_engine_phase_3c_cross_modul_drift Cross-modul-pin "
        "tri-state (one-hot over green|yellow|red)."
    )
    lines.append(
        "# TYPE persona_engine_phase_3c_cross_modul_drift gauge"
    )
    for s in CrossModulDriftStatus:
        v = 1.0 if snapshot.cross_modul_drift == s else 0.0
        lines.append(
            f'persona_engine_phase_3c_cross_modul_drift{{status="{s.value}"}} {v}'
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-3c-welle-status-emitter",
        description=(
            "Phase-3c per-welle live-status emitter for the Grafana "
            "welle-status dashboard."
        ),
    )
    p.add_argument(
        "--decisions-jsonl",
        type=str,
        default=None,
        help=(
            "Path to the BackendDecision JSONL. Falls back to "
            f"${ENV_PHASE_3C_OBS_BASELINE_PATH} then "
            f"${ENV_BACKEND_DECISION_JSONL}."
        ),
    )
    p.add_argument(
        "--phase2-acceptance-json",
        type=str,
        default=None,
        help=(
            "Path to the Phase-2-Acceptance-Gate output JSON. Falls "
            f"back to ${ENV_PHASE_2_ACCEPTANCE_OUTPUT}."
        ),
    )
    p.add_argument(
        "--lifecycle-json",
        type=str,
        default=None,
        help=(
            "Path to the welle-lifecycle override JSON. Falls back "
            f"to ${ENV_PHASE_3C_WELLE_LIFECYCLE}."
        ),
    )
    p.add_argument(
        "--out",
        type=str,
        default=None,
        help=(
            "Write the JSON snapshot to this path (in addition to "
            "stdout). Used by the workstation/dry-run pattern."
        ),
    )
    p.add_argument(
        "--prom-textfile",
        type=str,
        default=None,
        help=(
            "Write a Prometheus textfile-collector rendering to this "
            "path. Used by the live deployment to feed the Grafana "
            "dashboard."
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    decisions_path = resolve_decisions_jsonl_path(args.decisions_jsonl)
    phase2_path = resolve_phase2_acceptance_path(args.phase2_acceptance_json)
    lifecycle_path = resolve_lifecycle_path(args.lifecycle_json)

    if decisions_path is None:
        print(
            "phase-3c-welle-status-emitter: no decisions-jsonl path "
            "configured (CLI flag, $WAKIR_PHASE_3C_OBS_BASELINE_PATH, "
            "or $WAKIR_BACKEND_DECISION_JSONL).",
            file=sys.stderr,
        )
        return 2

    try:
        snapshot = build_snapshot(
            decisions_path=decisions_path,
            phase2_path=phase2_path,
            lifecycle_path=lifecycle_path,
        )
    except ValueError as exc:
        print(
            f"phase-3c-welle-status-emitter: lifecycle override invalid: {exc}",
            file=sys.stderr,
        )
        return 2

    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=True)
    print(payload)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")

    if args.prom_textfile:
        prom_path = Path(args.prom_textfile)
        prom_path.parent.mkdir(parents=True, exist_ok=True)
        prom_path.write_text(
            render_prometheus_textfile(snapshot), encoding="utf-8"
        )

    return snapshot.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
