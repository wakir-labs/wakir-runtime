#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3-Final-Bilanz-Generator (Tag-43, Noa SRE).

Context
-------

The Phase-3 Marathon (KW-21..KW-27, ~2026-05-12 .. ~2026-06-29) drives
seven cutover-Wellen (W1 v907-verify .. W7 lifecycle-recovery) from
Python-default to Rust-default. Tag-38..Tag-42 produced live
observability scaffolding:

  * Tag-38 ci-aggregator-Failure-Rate-Tracker (Noa #251)
  * Tag-40 Marathon-Live-Dashboard + alerts (Noa #257)
  * Tag-40 Marathon-Aggregat-Tracker (Selin #261) -> state file
    ``state/phase-3-marathon-state.json``
  * Tag-41 Live-Stream-Aggregator (Noa)
  * Tag-42 Probe-Observability (Noa)
  * Per-Welle Henrik-Sign-Off ``state/welle-N-sign-off.json``
  * Phase-3-COMPLETE-Marker ``state/phase-3-complete-marker.json``
    (Tomas Tag-42 #258)

This generator stitches the streams into a single end-of-Marathon
bilanz. It is invoked manually via CLI **and** auto-triggered by the
workflow hook that watches the Phase-3-COMPLETE-Marker
(``workflows/phase-3-complete-marker-watcher.yml`` calls
``--auto-after-complete-marker``; if the marker JSON has
``status == "COMPLETE"`` the generator writes the bilanz, otherwise
exits 0 quietly so the hook is idempotent).

Output is two artefacts, both deterministic and reproducible from the
same inputs:

  * ``reports/phase-3-marathon-bilanz.md`` -- ~500..800 lines of
    operator-readable Markdown.
  * ``reports/phase-3-marathon-bilanz.json`` -- machine-readable
    rollup, suitable for ingestion by Henrik (Internal Audit) and
    by the Phase-4 pre-substanz-plan generator.

Sandbox boundary
----------------

The generator is **stdlib-only** and does no network I/O. Every input
path is explicit (``--marathon-state``, ``--aggregator-history``,
``--backend-decision-snapshots``, ``--drift-histograms``,
``--sign-off-glob``, ``--complete-marker``) and every file is read
once. The default paths point at the canonical ``state/`` and
``reports/`` directories under the repo root; the hermetic test suite
overrides them with fixtures.

Hermetic split
--------------

Everything above the ``# --- I/O boundary ---`` marker is
pure-function and exercised by
``tests/observability/test_phase_3_final_bilanz_generator.py``. The
I/O layer reads JSON from disk and writes the two output files;
everything else operates on parsed dictionaries.

Anchors
-------

  * ADR-0065 (Phase-3c Cutover Plan, approved 2026-05-17 ~18:10 CEST)
  * ADR-0066 (Phase-3c 4W-Beschleunigung, approved 2026-05-17)
  * ADR-0068 (ci-aggregator single Required-Status-Check, approved
    2026-05-18)
  * Noa Tag-38 PR (aggregator-failure-rate-tracker)
  * Noa Tag-40 PR (marathon dashboard + alerts)
  * Selin Tag-40 PR #261 (marathon-aggregat-tracker)
  * Tomas Tag-42 PR #258 (phase-3-complete-marker spec)

-- Noa
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import statistics
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Stdlib-only by design. Do not import third-party packages.

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

WELLE_ORDER: Tuple[str, ...] = (
    "welle-1-v907-verify",
    "welle-2-svid-workload-identity",
    "welle-3-bridge-audit-writer",
    "welle-4-state-backing",
    "welle-5-lifecycle-state-machine",
    "welle-6-subscribe-loop",
    "welle-7-recovery-workflow",
)

WELLE_SHORT: Dict[str, str] = {
    "welle-1-v907-verify": "W1 v907-verify",
    "welle-2-svid-workload-identity": "W2 svid-workload-identity",
    "welle-3-bridge-audit-writer": "W3 bridge-audit-writer",
    "welle-4-state-backing": "W4 state-backing",
    "welle-5-lifecycle-state-machine": "W5 lifecycle-state-machine",
    "welle-6-subscribe-loop": "W6 subscribe-loop",
    "welle-7-recovery-workflow": "W7 recovery-workflow",
}

LATENCY_BUDGET_MS: Dict[str, int] = {
    # Per-welle p95 cutover-decision-latency budget (ms). Sourced from
    # ADR-0065 §SLO-Targets. The generator flags any welle whose
    # observed p95 exceeds the budget by >=10 %.
    "welle-1-v907-verify": 1500,
    "welle-2-svid-workload-identity": 2000,
    "welle-3-bridge-audit-writer": 2500,
    "welle-4-state-backing": 3000,
    "welle-5-lifecycle-state-machine": 3500,
    "welle-6-subscribe-loop": 2500,
    "welle-7-recovery-workflow": 3000,
}

DRIFT_BUDGET_PCT: float = 0.5  # max drift backend-decision % per ADR-0065.

BILANZ_SCHEMA_VERSION: str = "1.0.0"


# --------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 (seconds, Z-suffix).

    Wrapped so hermetic tests can monkeypatch via ``--now-iso``.
    """
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Return percentile ``pct`` (0..100) of ``values``.

    Returns ``None`` for empty input. Uses the inclusive linear
    interpolation defined by ``statistics.quantiles`` for n>=2; for n=1
    returns the single value; for n==0 returns ``None``. Stdlib-only.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    if not (0.0 <= pct <= 100.0):
        raise ValueError(f"pct must be in [0, 100], got {pct}")
    sorted_v = sorted(float(v) for v in values)
    if pct == 0.0:
        return sorted_v[0]
    if pct == 100.0:
        return sorted_v[-1]
    # Linear interpolation, inclusive method (matches numpy default).
    rank = pct / 100.0 * (len(sorted_v) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_v) - 1)
    frac = rank - lo
    return sorted_v[lo] * (1.0 - frac) + sorted_v[hi] * frac


def fmt_ms(value: Optional[float]) -> str:
    """Format a millisecond value for the Markdown report."""
    if value is None:
        return "n/a"
    if value < 1.0:
        return f"{value:.3f} ms"
    if value < 100.0:
        return f"{value:.1f} ms"
    return f"{value:.0f} ms"


def fmt_pct(value: Optional[float]) -> str:
    """Format a fraction (0..1) as a percentage with two decimals."""
    if value is None:
        return "n/a"
    return f"{value * 100.0:.2f} %"


def latency_status(welle_id: str, p95_ms: Optional[float]) -> str:
    """Return ``"OK"``, ``"WARN"`` or ``"BREACH"`` for an observed p95.

    The latency is compared to the per-welle budget from
    ``LATENCY_BUDGET_MS``. WARN is ``p95 > 0.9 * budget``; BREACH is
    ``p95 > 1.1 * budget``. Missing data is ``"NO_DATA"``.
    """
    if p95_ms is None:
        return "NO_DATA"
    budget = LATENCY_BUDGET_MS.get(welle_id)
    if budget is None:
        return "NO_BUDGET"
    if p95_ms > budget * 1.1:
        return "BREACH"
    if p95_ms > budget * 0.9:
        return "WARN"
    return "OK"


def drift_status(observed_pct: Optional[float]) -> str:
    """Drift status against ``DRIFT_BUDGET_PCT``."""
    if observed_pct is None:
        return "NO_DATA"
    if observed_pct > DRIFT_BUDGET_PCT:
        return "BREACH"
    if observed_pct > DRIFT_BUDGET_PCT * 0.8:
        return "WARN"
    return "OK"


# --------------------------------------------------------------------
# Data shaping
# --------------------------------------------------------------------


def normalize_marathon_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract per-welle counts + global counts from marathon-state.

    Expected input (Selin #261 schema, simplified):

        {
          "schema_version": "1.0.0",
          "updated_at": "2026-06-29T11:00:00Z",
          "wellen": {
            "welle-1-v907-verify": {
              "cutover_runs_total": 4123,
              "cutover_runs_rust": 3987,
              "cutover_runs_python_fallback": 136,
              "decision_latency_ms_samples": [120, 230, ...],
              "last_sample_at": "..."
            },
            ...
          }
        }

    The generator is tolerant of missing keys -- a welle that has
    not yet started yields zero counts but no exception.
    """
    out: Dict[str, Any] = {
        "schema_version": state.get("schema_version", "unknown"),
        "updated_at": state.get("updated_at", "unknown"),
        "wellen": {},
    }
    wellen = state.get("wellen") or {}
    for wid in WELLE_ORDER:
        w = wellen.get(wid) or {}
        total = int(w.get("cutover_runs_total", 0))
        rust = int(w.get("cutover_runs_rust", 0))
        py = int(w.get("cutover_runs_python_fallback", 0))
        samples = [float(x) for x in (w.get("decision_latency_ms_samples") or [])]
        out["wellen"][wid] = {
            "cutover_runs_total": total,
            "cutover_runs_rust": rust,
            "cutover_runs_python_fallback": py,
            "rust_share": (rust / total) if total > 0 else None,
            "decision_latency_ms_p50": percentile(samples, 50.0),
            "decision_latency_ms_p95": percentile(samples, 95.0),
            "decision_latency_ms_p99": percentile(samples, 99.0),
            "decision_latency_ms_n": len(samples),
            "last_sample_at": w.get("last_sample_at", "unknown"),
        }
    return out


def normalize_aggregator_history(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll up ci-aggregator failure-rate history into a single bilanz.

    Expected entry shape (Noa #251 schema):

        {
          "run_id": "123456789",
          "started_at": "2026-05-20T11:00:00Z",
          "conclusion": "success" | "failure",
          "wait_loop_seconds": 1234,
          "sub_workflow_failures": ["wirelang suite production", ...]
        }
    """
    total = len(history)
    successes = sum(1 for e in history if e.get("conclusion") == "success")
    failures = sum(1 for e in history if e.get("conclusion") == "failure")
    wait_samples = [
        float(e.get("wait_loop_seconds", 0.0))
        for e in history
        if isinstance(e.get("wait_loop_seconds"), (int, float))
    ]
    failure_buckets: Dict[str, int] = {}
    for e in history:
        for sw in e.get("sub_workflow_failures") or []:
            failure_buckets[sw] = failure_buckets.get(sw, 0) + 1
    return {
        "runs_total": total,
        "runs_success": successes,
        "runs_failure": failures,
        "failure_rate": (failures / total) if total > 0 else None,
        "wait_loop_p50_s": percentile(wait_samples, 50.0),
        "wait_loop_p95_s": percentile(wait_samples, 95.0),
        "wait_loop_p99_s": percentile(wait_samples, 99.0),
        "sub_workflow_failure_buckets": failure_buckets,
    }


def normalize_backend_decision_snapshots(
    snapshots: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Per-welle backend-decision snapshot rollups.

    Input keyed by welle-id, value is a list of snapshot dicts with
    ``rust_decisions``, ``python_decisions`` and ``timestamp``.
    """
    out: Dict[str, Any] = {}
    for wid in WELLE_ORDER:
        snaps = snapshots.get(wid) or []
        rust_total = sum(int(s.get("rust_decisions", 0)) for s in snaps)
        py_total = sum(int(s.get("python_decisions", 0)) for s in snaps)
        total = rust_total + py_total
        out[wid] = {
            "snapshots_n": len(snaps),
            "rust_decisions_total": rust_total,
            "python_decisions_total": py_total,
            "rust_share": (rust_total / total) if total > 0 else None,
            "first_snapshot_at": snaps[0].get("timestamp") if snaps else None,
            "last_snapshot_at": snaps[-1].get("timestamp") if snaps else None,
        }
    return out


def normalize_drift_histograms(histograms: Dict[str, Any]) -> Dict[str, Any]:
    """Roll up cross-welle drift histograms.

    The drift histogram per welle is the % of cutover-decisions where
    aggregator-verdict and legacy-verdict disagreed. Input shape:

        {
          "welle-1-v907-verify": {
            "drift_pct_samples": [0.02, 0.01, ...],
            "bucket_count": 7
          },
          ...
        }
    """
    out: Dict[str, Any] = {}
    for wid in WELLE_ORDER:
        h = histograms.get(wid) or {}
        samples = [float(x) for x in (h.get("drift_pct_samples") or [])]
        out[wid] = {
            "drift_pct_samples_n": len(samples),
            "drift_pct_p50": percentile(samples, 50.0),
            "drift_pct_p95": percentile(samples, 95.0),
            "drift_pct_max": max(samples) if samples else None,
            "drift_status": drift_status(max(samples) if samples else None),
            "bucket_count": int(h.get("bucket_count", 0)),
        }
    return out


def normalize_sign_offs(sign_offs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Index Henrik per-welle sign-off files by welle-id.

    Expected per-file shape:

        {
          "welle_id": "welle-3-bridge-audit-writer",
          "signed_off_at": "2026-06-05T15:30:00Z",
          "signed_off_by": "henrik",
          "audit_findings": ["..."],
          "exception_count": 0,
          "audit_ok": true
        }
    """
    by_welle: Dict[str, Dict[str, Any]] = {}
    for s in sign_offs:
        wid = s.get("welle_id")
        if not isinstance(wid, str):
            continue
        by_welle[wid] = {
            "signed_off_at": s.get("signed_off_at"),
            "signed_off_by": s.get("signed_off_by"),
            "audit_findings": list(s.get("audit_findings") or []),
            "exception_count": int(s.get("exception_count", 0)),
            "audit_ok": bool(s.get("audit_ok", False)),
        }
    aggregate_audit_ok = all(
        by_welle.get(wid, {}).get("audit_ok") is True for wid in WELLE_ORDER
    )
    total_findings = sum(
        len(by_welle.get(wid, {}).get("audit_findings") or []) for wid in WELLE_ORDER
    )
    total_exceptions = sum(
        int(by_welle.get(wid, {}).get("exception_count", 0)) for wid in WELLE_ORDER
    )
    return {
        "by_welle": by_welle,
        "aggregate_audit_ok": aggregate_audit_ok,
        "total_findings": total_findings,
        "total_exceptions": total_exceptions,
        "missing_sign_offs": [w for w in WELLE_ORDER if w not in by_welle],
    }


def validate_complete_marker(marker: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate the Phase-3-COMPLETE-Marker.

    Expected shape:

        {
          "schema_version": "1.0.0",
          "status": "COMPLETE",
          "completed_at": "2026-06-29T23:59:00Z",
          "wellen_complete": 7,
          "approver": "tomas",
          "evidence_refs": [...]
        }
    """
    if marker is None:
        return {
            "present": False,
            "status": None,
            "is_complete": False,
            "validation_errors": ["marker_file_missing"],
        }
    errors: List[str] = []
    status = marker.get("status")
    if status != "COMPLETE":
        errors.append(f"status_not_complete:{status!r}")
    wellen_complete = marker.get("wellen_complete")
    if wellen_complete != 7:
        errors.append(f"wellen_complete_expected_7_got_{wellen_complete!r}")
    if not marker.get("completed_at"):
        errors.append("completed_at_missing")
    if not marker.get("approver"):
        errors.append("approver_missing")
    return {
        "present": True,
        "status": status,
        "is_complete": status == "COMPLETE" and not errors,
        "completed_at": marker.get("completed_at"),
        "wellen_complete": wellen_complete,
        "approver": marker.get("approver"),
        "evidence_refs": list(marker.get("evidence_refs") or []),
        "validation_errors": errors,
    }


# --------------------------------------------------------------------
# Bilanz assembly
# --------------------------------------------------------------------


def assemble_bilanz(
    *,
    marathon_state: Dict[str, Any],
    aggregator_history: List[Dict[str, Any]],
    backend_snapshots: Dict[str, List[Dict[str, Any]]],
    drift_histograms: Dict[str, Any],
    sign_offs: List[Dict[str, Any]],
    complete_marker: Optional[Dict[str, Any]],
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the full machine-readable bilanz dict."""
    ms = normalize_marathon_state(marathon_state)
    ag = normalize_aggregator_history(aggregator_history)
    bs = normalize_backend_decision_snapshots(backend_snapshots)
    dh = normalize_drift_histograms(drift_histograms)
    so = normalize_sign_offs(sign_offs)
    cm = validate_complete_marker(complete_marker)

    per_welle: Dict[str, Any] = {}
    for wid in WELLE_ORDER:
        marathon_w = ms["wellen"][wid]
        decision_p95 = marathon_w["decision_latency_ms_p95"]
        per_welle[wid] = {
            "short": WELLE_SHORT[wid],
            "marathon": marathon_w,
            "backend_snapshots": bs[wid],
            "drift": dh[wid],
            "sign_off": so["by_welle"].get(wid),
            "latency_status": latency_status(wid, decision_p95),
            "latency_budget_ms": LATENCY_BUDGET_MS[wid],
        }

    # Cross-welle coupling: pairwise drift correlation is overkill;
    # instead compute a one-line "max drift across wellen" + how many
    # wellen are inside the 0.5 % drift budget.
    drift_status_counts = {"OK": 0, "WARN": 0, "BREACH": 0, "NO_DATA": 0}
    for wid in WELLE_ORDER:
        drift_status_counts[dh[wid]["drift_status"]] += 1

    latency_status_counts = {"OK": 0, "WARN": 0, "BREACH": 0, "NO_DATA": 0, "NO_BUDGET": 0}
    for wid in WELLE_ORDER:
        st = per_welle[wid]["latency_status"]
        latency_status_counts[st] = latency_status_counts.get(st, 0) + 1

    executive: Dict[str, Any] = {
        "wellen_total": len(WELLE_ORDER),
        "wellen_with_sign_off": len(WELLE_ORDER) - len(so["missing_sign_offs"]),
        "marathon_last_update": ms["updated_at"],
        "aggregator_runs_total": ag["runs_total"],
        "aggregator_failure_rate": ag["failure_rate"],
        "drift_status_counts": drift_status_counts,
        "latency_status_counts": latency_status_counts,
        "complete_marker_is_complete": cm["is_complete"],
        "audit_aggregate_ok": so["aggregate_audit_ok"],
    }

    # Phase-4 follow-up items: derived from the bilanz, not hard-coded.
    followups: List[str] = []
    for wid in WELLE_ORDER:
        st = per_welle[wid]["latency_status"]
        if st in ("BREACH", "WARN"):
            followups.append(
                f"{WELLE_SHORT[wid]}: latency p95 {st} -- carry into "
                f"Phase-4 pre-substanz tuning"
            )
        d_st = dh[wid]["drift_status"]
        if d_st in ("BREACH", "WARN"):
            followups.append(
                f"{WELLE_SHORT[wid]}: drift {d_st} -- investigate before "
                f"Phase-4 Python-fallback removal"
            )
        sign = so["by_welle"].get(wid)
        if sign and (sign.get("exception_count") or 0) > 0:
            followups.append(
                f"{WELLE_SHORT[wid]}: {sign['exception_count']} audit "
                f"exception(s) -- Henrik to track into Phase-4"
            )
    if so["missing_sign_offs"]:
        for wid in so["missing_sign_offs"]:
            followups.append(
                f"{WELLE_SHORT[wid]}: Henrik sign-off MISSING -- blocker "
                f"for Phase-3-COMPLETE acceptance"
            )
    if not cm["is_complete"]:
        followups.append(
            "Phase-3-COMPLETE-marker not valid -- "
            + ", ".join(cm["validation_errors"] or ["unknown"])
        )
    if not followups:
        followups.append(
            "No outstanding follow-ups detected -- Phase-4 may proceed with "
            "the standard pre-substanz aufstellung."
        )

    return {
        "schema_version": BILANZ_SCHEMA_VERSION,
        "generated_at": generated_at or utc_now_iso(),
        "executive_summary": executive,
        "per_welle": per_welle,
        "aggregator_history_rollup": ag,
        "complete_marker_validation": cm,
        "audit_aggregate": {
            "by_welle": so["by_welle"],
            "aggregate_audit_ok": so["aggregate_audit_ok"],
            "total_findings": so["total_findings"],
            "total_exceptions": so["total_exceptions"],
            "missing_sign_offs": so["missing_sign_offs"],
        },
        "phase_4_followups": followups,
    }


# --------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------


def render_markdown(bilanz: Dict[str, Any]) -> str:
    """Render the bilanz dict into a long-form Markdown report.

    The output targets 500..800 lines so that the operator can read
    the entire bilanz top-to-bottom without paging. Sections follow
    the order in the task brief:

      1. Header / metadata
      2. Executive summary
      3. Per-welle mini-bilanz (7 sections)
      4. Cross-welle coupling
      5. Henrik audit aggregate
      6. Phase-3-COMPLETE-marker validation
      7. Phase-4 follow-up items
      8. Footer / source-of-truth list
    """
    lines: List[str] = []
    exe = bilanz["executive_summary"]
    cm = bilanz["complete_marker_validation"]

    lines.append("# Phase-3 Marathon Final Bilanz")
    lines.append("")
    lines.append(
        f"Generated at **{bilanz['generated_at']}** by "
        "`scripts/observability/phase-3-final-bilanz-generator.py`."
    )
    lines.append("")
    lines.append(
        f"Schema version: `{bilanz['schema_version']}`. "
        "This document is a snapshot; re-run the generator to refresh."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Executive summary ----
    lines.append("## 1. Executive Summary")
    lines.append("")
    lines.append(
        f"- Wellen total: **{exe['wellen_total']}** "
        f"(W1..W7 Rust-default cutover)"
    )
    lines.append(
        f"- Wellen with Henrik sign-off: "
        f"**{exe['wellen_with_sign_off']} / {exe['wellen_total']}**"
    )
    lines.append(
        f"- Marathon-Aggregat-Tracker last update: "
        f"`{exe['marathon_last_update']}`"
    )
    lines.append(
        f"- ci-aggregator runs total: **{exe['aggregator_runs_total']}**, "
        f"failure-rate **{fmt_pct(exe['aggregator_failure_rate'])}**"
    )
    lines.append("")
    lines.append("### Drift status across wellen")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for st in ("OK", "WARN", "BREACH", "NO_DATA"):
        lines.append(f"| {st} | {exe['drift_status_counts'][st]} |")
    lines.append("")
    lines.append("### Latency status across wellen")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for st in ("OK", "WARN", "BREACH", "NO_DATA", "NO_BUDGET"):
        lines.append(f"| {st} | {exe['latency_status_counts'].get(st, 0)} |")
    lines.append("")
    lines.append(
        f"**Phase-3-COMPLETE marker valid:** "
        f"{'YES' if exe['complete_marker_is_complete'] else 'NO'}"
    )
    lines.append("")
    lines.append(
        f"**Aggregate audit OK:** "
        f"{'YES' if exe['audit_aggregate_ok'] else 'NO'}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Per-welle mini-bilanz ----
    lines.append("## 2. Per-Welle Mini-Bilanz")
    lines.append("")
    for idx, wid in enumerate(WELLE_ORDER, start=1):
        w = bilanz["per_welle"][wid]
        marathon = w["marathon"]
        snap = w["backend_snapshots"]
        drift = w["drift"]
        sign = w["sign_off"]
        lines.append(f"### 2.{idx} {w['short']}")
        lines.append("")
        lines.append("**Substanz-Anker:**")
        lines.append("")
        lines.append(f"- Welle-ID: `{wid}`")
        lines.append(
            f"- Cutover-runs total: {marathon['cutover_runs_total']}"
        )
        lines.append(
            f"- Rust decisions: {marathon['cutover_runs_rust']} "
            f"({fmt_pct(marathon['rust_share'])})"
        )
        lines.append(
            f"- Python-fallback decisions: "
            f"{marathon['cutover_runs_python_fallback']}"
        )
        lines.append(
            f"- Last sample at: `{marathon['last_sample_at']}`"
        )
        lines.append("")
        lines.append("**Decision-Latency (ms):**")
        lines.append("")
        lines.append("| Quantile | Value |")
        lines.append("|---|---|")
        lines.append(
            f"| p50 | {fmt_ms(marathon['decision_latency_ms_p50'])} |"
        )
        lines.append(
            f"| p95 | {fmt_ms(marathon['decision_latency_ms_p95'])} |"
        )
        lines.append(
            f"| p99 | {fmt_ms(marathon['decision_latency_ms_p99'])} |"
        )
        lines.append(
            f"| samples n | {marathon['decision_latency_ms_n']} |"
        )
        lines.append(
            f"| budget p95 | {w['latency_budget_ms']} ms |"
        )
        lines.append(
            f"| **status** | **{w['latency_status']}** |"
        )
        lines.append("")
        lines.append("**BackendDecision-Snapshots:**")
        lines.append("")
        lines.append(f"- Snapshots collected: {snap['snapshots_n']}")
        lines.append(
            f"- Rust decisions total: {snap['rust_decisions_total']}, "
            f"Python: {snap['python_decisions_total']}"
        )
        lines.append(f"- Rust share: {fmt_pct(snap['rust_share'])}")
        if snap["first_snapshot_at"]:
            lines.append(
                f"- First snapshot: `{snap['first_snapshot_at']}`, "
                f"last: `{snap['last_snapshot_at']}`"
            )
        lines.append("")
        lines.append("**Drift-Histogram:**")
        lines.append("")
        lines.append(f"- Samples: {drift['drift_pct_samples_n']}")
        lines.append(f"- Buckets: {drift['bucket_count']}")
        lines.append(
            f"- p50 drift %: "
            f"{drift['drift_pct_p50'] if drift['drift_pct_p50'] is not None else 'n/a'}"
        )
        lines.append(
            f"- p95 drift %: "
            f"{drift['drift_pct_p95'] if drift['drift_pct_p95'] is not None else 'n/a'}"
        )
        lines.append(
            f"- max drift %: "
            f"{drift['drift_pct_max'] if drift['drift_pct_max'] is not None else 'n/a'}"
        )
        lines.append(f"- **drift status:** **{drift['drift_status']}**")
        lines.append("")
        lines.append("**Henrik Sign-Off:**")
        lines.append("")
        if sign is None:
            lines.append("- _NO SIGN-OFF FILED YET_")
        else:
            lines.append(
                f"- Signed off at: `{sign.get('signed_off_at')}` "
                f"by **{sign.get('signed_off_by')}**"
            )
            lines.append(
                f"- Audit OK: "
                f"{'YES' if sign.get('audit_ok') else 'NO'}"
            )
            lines.append(
                f"- Exception count: {sign.get('exception_count', 0)}"
            )
            findings = sign.get("audit_findings") or []
            if findings:
                lines.append("- Audit findings:")
                for f in findings:
                    lines.append(f"  - {f}")
            else:
                lines.append("- Audit findings: _none_")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ---- Cross-welle coupling ----
    lines.append("## 3. Cross-Welle Coupling Bilanz")
    lines.append("")
    lines.append(
        "Cross-welle coupling is observed via the drift histograms in "
        "section 2 and via the aggregator failure buckets below. The "
        "two coupling questions the operator must answer:"
    )
    lines.append("")
    lines.append(
        "1. **Does any welle's drift correlate with another welle's "
        "drift?** -- inspect the per-welle drift status; if two or more "
        "wellen are BREACH simultaneously the cause is likely systemic "
        "(NATS / SPIFFE / wirelang) rather than welle-local."
    )
    lines.append("")
    lines.append(
        "2. **Does the ci-aggregator wait-loop correlate with a "
        "specific sub-workflow regression?** -- the failure-bucket "
        "table below indicates which sub-workflows accumulated the "
        "most failures across the Marathon window."
    )
    lines.append("")
    ag = bilanz["aggregator_history_rollup"]
    lines.append("### ci-aggregator wait-loop latency")
    lines.append("")
    lines.append("| Quantile | Seconds |")
    lines.append("|---|---|")
    lines.append(
        f"| p50 | "
        f"{ag['wait_loop_p50_s'] if ag['wait_loop_p50_s'] is not None else 'n/a'} |"
    )
    lines.append(
        f"| p95 | "
        f"{ag['wait_loop_p95_s'] if ag['wait_loop_p95_s'] is not None else 'n/a'} |"
    )
    lines.append(
        f"| p99 | "
        f"{ag['wait_loop_p99_s'] if ag['wait_loop_p99_s'] is not None else 'n/a'} |"
    )
    lines.append("")
    lines.append("### Sub-workflow failure buckets")
    lines.append("")
    buckets = ag["sub_workflow_failure_buckets"]
    if buckets:
        lines.append("| Sub-workflow | Failure count |")
        lines.append("|---|---|")
        for sw, cnt in sorted(buckets.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {sw} | {cnt} |")
    else:
        lines.append("_No sub-workflow failures recorded._")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Henrik audit aggregate ----
    lines.append("## 4. Henrik Audit Aggregate")
    lines.append("")
    aud = bilanz["audit_aggregate"]
    lines.append(
        f"- Aggregate audit OK: "
        f"**{'YES' if aud['aggregate_audit_ok'] else 'NO'}**"
    )
    lines.append(f"- Total findings across wellen: {aud['total_findings']}")
    lines.append(
        f"- Total exception count across wellen: {aud['total_exceptions']}"
    )
    if aud["missing_sign_offs"]:
        lines.append("- **Missing sign-offs:**")
        for w in aud["missing_sign_offs"]:
            lines.append(f"  - {WELLE_SHORT[w]} (`{w}`)")
    else:
        lines.append("- All seven wellen carry Henrik sign-off.")
    lines.append("")
    lines.append("### Per-welle sign-off table")
    lines.append("")
    lines.append("| Welle | Signed off at | By | OK | Exceptions | Findings |")
    lines.append("|---|---|---|---|---|---|")
    for wid in WELLE_ORDER:
        s = aud["by_welle"].get(wid)
        if s is None:
            lines.append(
                f"| {WELLE_SHORT[wid]} | _MISSING_ | _MISSING_ | "
                "_MISSING_ | _MISSING_ | _MISSING_ |"
            )
        else:
            findings_n = len(s.get("audit_findings") or [])
            lines.append(
                f"| {WELLE_SHORT[wid]} | `{s.get('signed_off_at')}` | "
                f"{s.get('signed_off_by')} | "
                f"{'YES' if s.get('audit_ok') else 'NO'} | "
                f"{s.get('exception_count', 0)} | "
                f"{findings_n} |"
            )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- COMPLETE marker validation ----
    lines.append("## 5. Phase-3-COMPLETE-Marker Validation")
    lines.append("")
    if not cm["present"]:
        lines.append(
            "**Marker file is missing.** Without the marker file, the "
            "Phase-3 Marathon is not complete and Phase-4 must not start."
        )
    else:
        lines.append(f"- Status: `{cm.get('status')}`")
        lines.append(f"- Completed at: `{cm.get('completed_at')}`")
        lines.append(f"- Wellen complete: {cm.get('wellen_complete')}")
        lines.append(f"- Approver: `{cm.get('approver')}`")
        lines.append(f"- Is complete: **{'YES' if cm['is_complete'] else 'NO'}**")
        refs = cm.get("evidence_refs") or []
        if refs:
            lines.append("- Evidence refs:")
            for r in refs:
                lines.append(f"  - `{r}`")
        if cm.get("validation_errors"):
            lines.append("- **Validation errors:**")
            for e in cm["validation_errors"]:
                lines.append(f"  - `{e}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Phase-4 follow-up items ----
    lines.append("## 6. Phase-4 Follow-up Items")
    lines.append("")
    lines.append(
        "The following items must be carried into the Phase-4 "
        "pre-substanz aufstellung. Items are derived from this bilanz "
        "and not hand-edited; re-run the generator to update."
    )
    lines.append("")
    for item in bilanz["phase_4_followups"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Footer ----
    lines.append("## 7. Source-of-Truth Inputs")
    lines.append("")
    lines.append(
        "The bilanz aggregates the following observability streams. "
        "Each path is the canonical input; the hermetic test suite "
        "overrides them with fixtures."
    )
    lines.append("")
    lines.append("- `state/phase-3-marathon-state.json` (Selin #261)")
    lines.append("- `state/aggregator-failure-rate-history.json` (Noa #251)")
    lines.append(
        "- `state/backend-decision-snapshots/<welle-id>.json` (per-welle)"
    )
    lines.append(
        "- `state/cross-welle-drift-histograms.json` (Noa Tag-41)"
    )
    lines.append(
        "- `state/welle-N-sign-off.json` (Henrik, one per welle)"
    )
    lines.append(
        "- `state/phase-3-complete-marker.json` (Tomas #258)"
    )
    lines.append("")
    lines.append(
        "Runbook: `docs/observability/phase-3-final-bilanz-generator-runbook.md`."
    )
    lines.append("")
    lines.append("-- Noa")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------
# I/O boundary
# --------------------------------------------------------------------

# Everything above this marker is pure-function and hermetic-test
# target. Everything below performs disk I/O and CLI parsing.


def _load_json(path: str) -> Any:
    """Load JSON, raising a descriptive error on failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in {path}: {exc}") from exc


def _load_json_optional(path: str) -> Optional[Any]:
    """Load JSON, returning ``None`` if file is missing."""
    if not os.path.exists(path):
        return None
    return _load_json(path)


def _load_sign_offs(glob_pattern: str) -> List[Dict[str, Any]]:
    """Load all sign-off JSON files matching ``glob_pattern``."""
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(glob_pattern)):
        try:
            data = _load_json(path)
        except FileNotFoundError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _load_backend_snapshots(dir_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load per-welle backend-decision snapshot files from a directory."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    if not os.path.isdir(dir_path):
        return out
    for wid in WELLE_ORDER:
        path = os.path.join(dir_path, f"{wid}.json")
        if not os.path.exists(path):
            out[wid] = []
            continue
        try:
            data = _load_json(path)
        except FileNotFoundError:
            out[wid] = []
            continue
        if isinstance(data, list):
            out[wid] = [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict) and "snapshots" in data:
            sn = data.get("snapshots") or []
            out[wid] = [d for d in sn if isinstance(d, dict)]
        else:
            out[wid] = []
    return out


def _check_auto_trigger(marker_path: str) -> bool:
    """Return True if the COMPLETE-marker file is present and signals COMPLETE.

    Used by the workflow-hook auto-trigger to decide whether to write
    the bilanz or to exit quietly.
    """
    if not os.path.exists(marker_path):
        return False
    try:
        data = _load_json(marker_path)
    except (FileNotFoundError, RuntimeError):
        return False
    return isinstance(data, dict) and data.get("status") == "COMPLETE"


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="phase-3-final-bilanz-generator",
        description=(
            "Generate the Phase-3 Marathon Final Bilanz "
            "(Markdown + JSON) from all observability inputs."
        ),
    )
    parser.add_argument(
        "--marathon-state",
        default="state/phase-3-marathon-state.json",
        help="Path to Marathon-Aggregat-Tracker state JSON (Selin #261).",
    )
    parser.add_argument(
        "--aggregator-history",
        default="state/aggregator-failure-rate-history.json",
        help="Path to ci-aggregator failure-rate history JSON (Noa #251).",
    )
    parser.add_argument(
        "--backend-snapshots-dir",
        default="state/backend-decision-snapshots",
        help="Directory with per-welle BackendDecision snapshot JSONs.",
    )
    parser.add_argument(
        "--drift-histograms",
        default="state/cross-welle-drift-histograms.json",
        help="Path to cross-welle drift histogram JSON.",
    )
    parser.add_argument(
        "--sign-off-glob",
        default="state/welle-*-sign-off.json",
        help="Glob pattern for Henrik per-welle sign-off JSON files.",
    )
    parser.add_argument(
        "--complete-marker",
        default="state/phase-3-complete-marker.json",
        help="Path to Phase-3-COMPLETE-marker JSON (Tomas #258).",
    )
    parser.add_argument(
        "--output-md",
        default="reports/phase-3-marathon-bilanz.md",
        help="Output Markdown report path.",
    )
    parser.add_argument(
        "--output-json",
        default="reports/phase-3-marathon-bilanz.json",
        help="Output JSON rollup path.",
    )
    parser.add_argument(
        "--now-iso",
        default=None,
        help="Override generated_at timestamp (UTC ISO-8601). Test-only.",
    )
    parser.add_argument(
        "--auto-after-complete-marker",
        action="store_true",
        help=(
            "Auto-trigger mode: if the COMPLETE-marker is not present "
            "or not COMPLETE, exit 0 silently. Used by the workflow hook."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero if the bilanz reports any BREACH (latency, "
            "drift, audit, or marker validation)."
        ),
    )
    return parser.parse_args(argv)


def _detect_breach(bilanz: Dict[str, Any]) -> List[str]:
    """Return a list of BREACH descriptors, empty if none."""
    breaches: List[str] = []
    counts = bilanz["executive_summary"]
    if counts["latency_status_counts"].get("BREACH", 0) > 0:
        breaches.append(
            f"latency BREACH on {counts['latency_status_counts']['BREACH']} welle(s)"
        )
    if counts["drift_status_counts"].get("BREACH", 0) > 0:
        breaches.append(
            f"drift BREACH on {counts['drift_status_counts']['BREACH']} welle(s)"
        )
    if not counts["audit_aggregate_ok"]:
        breaches.append("audit aggregate not OK")
    if not counts["complete_marker_is_complete"]:
        breaches.append("complete-marker not valid")
    return breaches


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    if args.auto_after_complete_marker:
        if not _check_auto_trigger(args.complete_marker):
            # Hook ran prematurely; exit silently.
            return 0

    try:
        marathon_state = _load_json(args.marathon_state)
    except FileNotFoundError:
        print(
            f"ERROR: marathon-state file missing: {args.marathon_state}",
            file=sys.stderr,
        )
        return 2

    try:
        aggregator_history = _load_json(args.aggregator_history)
    except FileNotFoundError:
        aggregator_history = []
    if not isinstance(aggregator_history, list):
        aggregator_history = []

    backend_snapshots = _load_backend_snapshots(args.backend_snapshots_dir)
    drift_histograms = _load_json_optional(args.drift_histograms) or {}
    sign_offs = _load_sign_offs(args.sign_off_glob)
    complete_marker = _load_json_optional(args.complete_marker)

    bilanz = assemble_bilanz(
        marathon_state=marathon_state,
        aggregator_history=aggregator_history,
        backend_snapshots=backend_snapshots,
        drift_histograms=drift_histograms,
        sign_offs=sign_offs,
        complete_marker=complete_marker,
        generated_at=args.now_iso,
    )

    md = render_markdown(bilanz)

    os.makedirs(os.path.dirname(args.output_md) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_md, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(args.output_json, "w", encoding="utf-8") as fh:
        json.dump(bilanz, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(
        f"Phase-3 Final Bilanz written:\n  {args.output_md}\n  {args.output_json}",
        file=sys.stderr,
    )

    if args.strict:
        breaches = _detect_breach(bilanz)
        if breaches:
            print(
                "STRICT mode: BREACH detected -- "
                + "; ".join(breaches),
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
