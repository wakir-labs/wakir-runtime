#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Regenerate the five Phase-3-Marathon-Bilanz fixture datasets.

The fixtures are produced from pure-Python builders so they are
deterministic and byte-stable. Manual edits to the JSON files in
``tests/fixtures/phase-3-marathon-bilanz/<dataset>/state/`` will be
overwritten by this script.

The hermetic test suite invokes ``_build_dataset`` directly and
compares against the on-disk fixtures via SHA-256 to enforce that
the on-disk artefacts match the builders bit-for-bit.

Run manually:

    python3 tests/fixtures/phase-3-marathon-bilanz/regenerate.py

-- Selin
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Sequence, Tuple

# Mirror the WELLE_ORDER and LATENCY_BUDGET_MS constants from
# ``scripts/observability/phase-3-final-bilanz-generator.py`` to avoid
# an import-by-hyphenated-path dance in this builder. The hermetic
# test suite asserts the constants match between the two files.

WELLE_ORDER: Tuple[str, ...] = (
    "welle-1-v907-verify",
    "welle-2-svid-workload-identity",
    "welle-3-bridge-audit-writer",
    "welle-4-state-backing",
    "welle-5-lifecycle-state-machine",
    "welle-6-subscribe-loop",
    "welle-7-recovery-workflow",
)

LATENCY_BUDGET_MS: Dict[str, int] = {
    "welle-1-v907-verify": 1500,
    "welle-2-svid-workload-identity": 2000,
    "welle-3-bridge-audit-writer": 2500,
    "welle-4-state-backing": 3000,
    "welle-5-lifecycle-state-machine": 3500,
    "welle-6-subscribe-loop": 2500,
    "welle-7-recovery-workflow": 3000,
}

FIXTURES_ROOT = pathlib.Path(__file__).resolve().parent


# --------------------------------------------------------------------
# Generic builders -- parameterised so each dataset can opt in/out.
# --------------------------------------------------------------------


def _marathon_state(
    *,
    rust_share_per_welle: Dict[str, float],
    latency_factor_per_welle: Dict[str, float],
    updated_at: str = "2026-06-29T11:00:00Z",
    cutover_runs_per_welle_base: int = 1000,
    excluded_wellen: Sequence[str] = (),
) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "updated_at": updated_at,
        "wellen": {},
    }
    for i, wid in enumerate(WELLE_ORDER, start=1):
        if wid in excluded_wellen:
            continue
        total = cutover_runs_per_welle_base * i
        rust_share = rust_share_per_welle.get(wid, 0.99)
        rust = int(round(total * rust_share))
        py = total - rust
        budget = LATENCY_BUDGET_MS[wid]
        peak = budget * latency_factor_per_welle.get(wid, 0.5)
        samples = [
            round(peak * 0.25, 3),
            round(peak * 0.5, 3),
            round(peak * 0.75, 3),
            round(peak, 3),
        ]
        # Deterministic per-welle timestamp.
        state["wellen"][wid] = {
            "cutover_runs_total": total,
            "cutover_runs_rust": rust,
            "cutover_runs_python_fallback": py,
            "decision_latency_ms_samples": samples,
            "last_sample_at": f"2026-06-2{i % 10}T12:00:00Z",
        }
    return state


def _aggregator_history(
    *,
    success_count: int = 18,
    failure_count: int = 2,
    failure_buckets: Sequence[str] = ("wirelang suite production",),
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # Deterministic ordering by sequence number.
    for n in range(success_count):
        out.append(
            {
                "run_id": f"run-success-{n + 1:04d}",
                "started_at": f"2026-05-{20 + (n % 7):02d}T11:{(n * 7) % 60:02d}:00Z",
                "conclusion": "success",
                "wait_loop_seconds": 600 + (n * 11) % 200,
                "sub_workflow_failures": [],
            }
        )
    for n in range(failure_count):
        out.append(
            {
                "run_id": f"run-failure-{n + 1:04d}",
                "started_at": f"2026-05-{22 + (n % 5):02d}T13:{(n * 13) % 60:02d}:00Z",
                "conclusion": "failure",
                "wait_loop_seconds": 1100 + (n * 17) % 300,
                "sub_workflow_failures": list(failure_buckets),
            }
        )
    return out


def _backend_snapshots(
    *,
    rust_per_welle: Dict[str, int],
    python_per_welle: Dict[str, int],
    excluded_wellen: Sequence[str] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for wid in WELLE_ORDER:
        if wid in excluded_wellen:
            out[wid] = []
            continue
        rust = rust_per_welle.get(wid, 250)
        py = python_per_welle.get(wid, 5)
        # Two deterministic snapshots per welle.
        out[wid] = [
            {
                "rust_decisions": rust // 2,
                "python_decisions": py // 2 + (py % 2),
                "timestamp": "2026-06-01T10:00:00Z",
            },
            {
                "rust_decisions": rust - rust // 2,
                "python_decisions": py // 2,
                "timestamp": "2026-06-15T10:00:00Z",
            },
        ]
    return out


def _drift_histograms(
    *,
    breach_wellen: Sequence[str] = (),
    excluded_wellen: Sequence[str] = (),
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for wid in WELLE_ORDER:
        if wid in excluded_wellen:
            continue
        if wid in breach_wellen:
            # Above 0.5 % budget.
            samples = [0.6, 0.7, 0.8, 0.65]
        else:
            samples = [0.05, 0.1, 0.15, 0.2]
        out[wid] = {"drift_pct_samples": samples, "bucket_count": 7}
    return out


def _sign_off(
    *,
    welle_id: str,
    audit_ok: bool = True,
    exception_count: int = 0,
    audit_findings: Sequence[str] = (),
    signed_off_at: str = "2026-06-15T10:00:00Z",
    signed_off_by: str = "henrik",
) -> Dict[str, Any]:
    return {
        "welle_id": welle_id,
        "signed_off_at": signed_off_at,
        "signed_off_by": signed_off_by,
        "audit_findings": list(audit_findings),
        "exception_count": exception_count,
        "audit_ok": audit_ok,
    }


def _complete_marker(
    *,
    status: str = "COMPLETE",
    wellen_complete: int = 7,
    completed_at: str = "2026-06-29T23:59:00Z",
    approver: str = "tomas",
    evidence_refs: Sequence[str] = (
        "state/welle-1-sign-off.json",
        "state/welle-2-sign-off.json",
        "state/welle-3-sign-off.json",
        "state/welle-4-sign-off.json",
        "state/welle-5-sign-off.json",
        "state/welle-6-sign-off.json",
        "state/welle-7-sign-off.json",
    ),
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": status,
        "completed_at": completed_at,
        "wellen_complete": wellen_complete,
        "approver": approver,
        "evidence_refs": list(evidence_refs),
    }


# --------------------------------------------------------------------
# Dataset builders
# --------------------------------------------------------------------


def build_happy_path() -> Dict[str, Any]:
    """All 7 wellen green, all sign-offs in, marker COMPLETE."""
    return {
        "marathon_state": _marathon_state(
            rust_share_per_welle={wid: 0.99 for wid in WELLE_ORDER},
            latency_factor_per_welle={wid: 0.5 for wid in WELLE_ORDER},
        ),
        "aggregator_history": _aggregator_history(
            success_count=18, failure_count=2
        ),
        "backend_snapshots": _backend_snapshots(
            rust_per_welle={wid: 250 + i * 10 for i, wid in enumerate(WELLE_ORDER)},
            python_per_welle={wid: 4 for wid in WELLE_ORDER},
        ),
        "drift_histograms": _drift_histograms(),
        "sign_offs": [_sign_off(welle_id=wid) for wid in WELLE_ORDER],
        "complete_marker": _complete_marker(),
    }


def build_rollback_path() -> Dict[str, Any]:
    """Welle-3 rolled back; W4..W7 blocked; no COMPLETE-Marker."""
    rolled = {
        "welle-3-bridge-audit-writer",
        "welle-4-state-backing",
        "welle-5-lifecycle-state-machine",
        "welle-6-subscribe-loop",
        "welle-7-recovery-workflow",
    }
    return {
        "marathon_state": _marathon_state(
            rust_share_per_welle={
                "welle-1-v907-verify": 0.99,
                "welle-2-svid-workload-identity": 0.99,
                # Welle-3 was rolled back -- the marathon tracker still
                # holds the pre-rollback numbers but Henrik audit will
                # mark audit_ok=false. W4..W7 never started.
                "welle-3-bridge-audit-writer": 0.4,
            },
            latency_factor_per_welle={wid: 0.5 for wid in WELLE_ORDER},
            excluded_wellen=("welle-4-state-backing",
                             "welle-5-lifecycle-state-machine",
                             "welle-6-subscribe-loop",
                             "welle-7-recovery-workflow"),
        ),
        "aggregator_history": _aggregator_history(
            success_count=12,
            failure_count=6,
            failure_buckets=(
                "wirelang suite production",
                "bridge-audit-writer cross-lang",
            ),
        ),
        "backend_snapshots": _backend_snapshots(
            rust_per_welle={
                "welle-1-v907-verify": 250,
                "welle-2-svid-workload-identity": 260,
                "welle-3-bridge-audit-writer": 80,
            },
            python_per_welle={
                "welle-1-v907-verify": 4,
                "welle-2-svid-workload-identity": 4,
                "welle-3-bridge-audit-writer": 120,
            },
            excluded_wellen=(
                "welle-4-state-backing",
                "welle-5-lifecycle-state-machine",
                "welle-6-subscribe-loop",
                "welle-7-recovery-workflow",
            ),
        ),
        "drift_histograms": _drift_histograms(
            breach_wellen=("welle-3-bridge-audit-writer",),
            excluded_wellen=(
                "welle-4-state-backing",
                "welle-5-lifecycle-state-machine",
                "welle-6-subscribe-loop",
                "welle-7-recovery-workflow",
            ),
        ),
        "sign_offs": [
            _sign_off(welle_id="welle-1-v907-verify"),
            _sign_off(welle_id="welle-2-svid-workload-identity"),
            _sign_off(
                welle_id="welle-3-bridge-audit-writer",
                audit_ok=False,
                exception_count=3,
                audit_findings=[
                    "drift > 0.5 % budget on bridge-audit-writer",
                    "Rust-decision share collapsed to 40 %",
                    "Rollback initiated 2026-06-08T14:00:00Z",
                ],
            ),
            # W4..W7: no sign-off (blocked by rollback).
        ],
        # No COMPLETE-marker: rollback path means Marathon-in-flight.
        "complete_marker": None,
    }


def build_welle_7_missing() -> Dict[str, Any]:
    """All 6 sign-offs green but Welle-7 pre-auditor absent."""
    return {
        "marathon_state": _marathon_state(
            rust_share_per_welle={wid: 0.99 for wid in WELLE_ORDER},
            latency_factor_per_welle={wid: 0.5 for wid in WELLE_ORDER},
        ),
        "aggregator_history": _aggregator_history(
            success_count=20, failure_count=2
        ),
        "backend_snapshots": _backend_snapshots(
            rust_per_welle={wid: 260 for wid in WELLE_ORDER},
            python_per_welle={wid: 4 for wid in WELLE_ORDER},
        ),
        "drift_histograms": _drift_histograms(),
        "sign_offs": [
            _sign_off(welle_id=wid)
            for wid in WELLE_ORDER
            if wid != "welle-7-recovery-workflow"
        ],
        # Complete marker exists but with wellen_complete=6, so validation
        # will flag wellen_complete_expected_7_got_6.
        "complete_marker": _complete_marker(wellen_complete=6),
    }


def build_cross_drift() -> Dict[str, Any]:
    """W4 + W5 simultaneously above drift budget => systemic-coupling."""
    return {
        "marathon_state": _marathon_state(
            rust_share_per_welle={wid: 0.99 for wid in WELLE_ORDER},
            latency_factor_per_welle={wid: 0.5 for wid in WELLE_ORDER},
        ),
        "aggregator_history": _aggregator_history(
            success_count=15,
            failure_count=5,
            failure_buckets=(
                "state-backing cross-lang",
                "lifecycle-state-machine cross-lang",
            ),
        ),
        "backend_snapshots": _backend_snapshots(
            rust_per_welle={wid: 260 for wid in WELLE_ORDER},
            python_per_welle={wid: 4 for wid in WELLE_ORDER},
        ),
        "drift_histograms": _drift_histograms(
            breach_wellen=(
                "welle-4-state-backing",
                "welle-5-lifecycle-state-machine",
            )
        ),
        "sign_offs": [
            _sign_off(
                welle_id=wid,
                audit_ok=(wid not in (
                    "welle-4-state-backing",
                    "welle-5-lifecycle-state-machine",
                )),
                exception_count=(
                    2
                    if wid in (
                        "welle-4-state-backing",
                        "welle-5-lifecycle-state-machine",
                    )
                    else 0
                ),
                audit_findings=(
                    ["drift > 0.5 % budget", "cross-welle correlation observed"]
                    if wid in (
                        "welle-4-state-backing",
                        "welle-5-lifecycle-state-machine",
                    )
                    else []
                ),
            )
            for wid in WELLE_ORDER
        ],
        # Complete-marker is COMPLETE but the bilanz will downgrade the
        # aggregate audit because two wellen carry exceptions.
        "complete_marker": _complete_marker(),
    }


def build_latency_excursion() -> Dict[str, Any]:
    """All verdicts GREEN but W3 + W5 p95 latency above budget."""
    # latency_factor > 1.1 triggers BREACH; cap below WARN for others.
    return {
        "marathon_state": _marathon_state(
            rust_share_per_welle={wid: 0.99 for wid in WELLE_ORDER},
            latency_factor_per_welle={
                "welle-1-v907-verify": 0.5,
                "welle-2-svid-workload-identity": 0.5,
                "welle-3-bridge-audit-writer": 1.2,
                "welle-4-state-backing": 0.5,
                "welle-5-lifecycle-state-machine": 1.3,
                "welle-6-subscribe-loop": 0.5,
                "welle-7-recovery-workflow": 0.5,
            },
        ),
        "aggregator_history": _aggregator_history(
            success_count=20, failure_count=0
        ),
        "backend_snapshots": _backend_snapshots(
            rust_per_welle={wid: 260 for wid in WELLE_ORDER},
            python_per_welle={wid: 4 for wid in WELLE_ORDER},
        ),
        "drift_histograms": _drift_histograms(),
        # All sign-offs green (latency does not gate Henrik audit).
        "sign_offs": [_sign_off(welle_id=wid) for wid in WELLE_ORDER],
        "complete_marker": _complete_marker(),
    }


DATASETS: Dict[str, Any] = {
    "happy-path": build_happy_path,
    "rollback-path": build_rollback_path,
    "welle-7-missing": build_welle_7_missing,
    "cross-drift": build_cross_drift,
    "latency-excursion": build_latency_excursion,
}


# --------------------------------------------------------------------
# Disk writer (byte-stable)
# --------------------------------------------------------------------


def _write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def write_dataset(name: str, dataset: Dict[str, Any], root: pathlib.Path) -> None:
    state = root / name / "state"
    state.mkdir(parents=True, exist_ok=True)
    snap_dir = state / "backend-decision-snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    _write_json(state / "phase-3-marathon-state.json", dataset["marathon_state"])
    _write_json(
        state / "aggregator-failure-rate-history.json",
        dataset["aggregator_history"],
    )
    _write_json(
        state / "cross-welle-drift-histograms.json",
        dataset["drift_histograms"],
    )
    for wid, snaps in dataset["backend_snapshots"].items():
        _write_json(snap_dir / f"{wid}.json", snaps)

    for s in dataset["sign_offs"]:
        wid = s["welle_id"]
        idx = WELLE_ORDER.index(wid) + 1
        _write_json(state / f"welle-{idx}-sign-off.json", s)

    if dataset["complete_marker"] is not None:
        _write_json(
            state / "phase-3-complete-marker.json", dataset["complete_marker"]
        )
    else:
        # Ensure no stale marker from a previous run is left behind.
        stale = state / "phase-3-complete-marker.json"
        if stale.exists():
            stale.unlink()


def main() -> int:
    for name, builder in DATASETS.items():
        write_dataset(name, builder(), FIXTURES_ROOT)
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
