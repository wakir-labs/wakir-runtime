#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Marathon-Final-Bilanz Aggregator -- Tag-50 (Tomas).

Purpose
-------

Phase-3 ran a seven-Welle cutover marathon (KW-21..KW-27). Five
engineering personas left observable footprints over the run:

* **Tomas** (matrix-lead) wrote ``state/phase-3-complete-marker.json``
  (Tag-42 #258), Welle-3..7 hot-spot probe envelopes (Tag-45 + Tag-48)
  and the cross-welle hot-spot rollup (Tag-49 #317).
* **Noa** (SRE) wrote the marathon-aggregat-tracker output
  ``state/aggregator-failure-rate-history.json`` (Tag-38 #251), the
  Phase-3 final-bilanz generator (Tag-43 #276) and the per-welle
  prom-textfile heatmap emitter (Tag-49 #315).
* **Amara** (QA) wrote the cross-welle E2E acceptance run reports and
  the Doppel-Welle E2E acceptance-suite extension (Tag-30 #199;
  Tag-38, Tag-39).
* **Selin** (Persona-Engine) wrote the marathon-state file
  ``state/phase-3-marathon-state.json`` (Tag-40 #261) and the bridge-
  audit-writer wire-in (Tag-48 #313).
* **Henrik** (Internal Audit) wrote the per-welle sign-off envelopes
  ``state/welle-N-sign-off.json`` (Welle-1..7) and the Phase-3-Schluss-
  Audit-Spec.

Tag-43 Noa's ``phase-3-final-bilanz-generator.py`` stitches the SRE
streams into the *full* end-of-Marathon-Bilanz once the COMPLETE-marker
is written. That generator is post-COMPLETE only.

This Tag-50 aggregator is a *thinner companion*: it walks the same
sources but is **dual-trigger** -- it runs daily during the marathon
window AND post-Welle-7-sign-off -- and renders a one-page
cross-persona snapshot. The snapshot answers

    "Where do the five personas stand right now?"

without waiting for the COMPLETE-marker. It is the daily AR/Mira-Hand
read-out for Phase-3 marathon close-out and the post-Welle-7 hand-off
bilanz to Internal-Audit / Aufsichtsrat.

Output (two artefacts, both deterministic from the same inputs):

  * ``reports/marathon-final-bilanz.md`` -- ~120..200 lines of
    operator-readable Markdown, suitable for direct paste into
    GITHUB_STEP_SUMMARY.
  * ``reports/marathon-final-bilanz.json`` -- machine-readable rollup
    for downstream tooling (Henrik audit-bundle import, Phase-4
    pre-substanz planner).

The Job-Summary is rendered by the workflow itself from the same
Markdown file; this script writes the file and exits.

Sandbox posture
---------------

stdlib-only. No subprocess. No network. No file-system writes outside
the configured ``--output-dir``. Every input path is explicit via CLI
flag; defaults assume a real ``state/`` and ``reports/`` directory at
the repo root. The hermetic test suite overrides every path with
fixtures.

Hermetic split
--------------

Everything above the ``# --- I/O boundary ---`` marker is pure-function
and tested in ``tests/ci/test_marathon_final_bilanz_aggregator.py``.
The I/O layer reads JSON and writes the two output files; everything
else operates on parsed dictionaries.

Verdict aggregation
-------------------

Per-persona slot status (one slot per persona):

* ``READY``        -- expected artefact present and well-formed.
* ``PARTIAL``      -- expected artefact present but missing some
                      fields (Phase-3 mid-marathon: some Wellen still
                      pending sign-off).
* ``PENDING``      -- expected artefact absent. Not loud-failure
                      during the marathon window; loud-failure post-
                      Welle-7-sign-off (``--mode=post-welle-7``).
* ``BROKEN``       -- artefact present but malformed (parse error,
                      schema mismatch). Always loud-failure.

Bilanz aggregate verdict (across the five persona slots):

* ``MARATHON_READY``    -- all five slots ``READY``, all seven
                          Welle-sign-offs present, COMPLETE-marker
                          present and status=COMPLETE.
* ``MARATHON_IN_FLIGHT`` -- one or more slots ``PARTIAL`` or
                          ``PENDING``, zero ``BROKEN``. Normal mid-
                          marathon state.
* ``MARATHON_BROKEN``    -- any ``BROKEN`` slot. Loud-failure.

In ``--mode=post-welle-7`` any ``PENDING`` slot also yields
``MARATHON_BROKEN`` since at that point every persona is expected to
have delivered.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

SCHEMA_VERSION = "1.0.0"

PERSONAS = ("tomas", "noa", "amara", "selin", "henrik")
WELLEN = (
    "welle-1-v907-verify",
    "welle-2-svid-workload-identity",
    "welle-3-bridge-audit-writer",
    "welle-4-state-backing",
    "welle-5-lifecycle-state-machine",
    "welle-6-subscribe-loop",
    "welle-7-recovery-workflow",
)

# --- pure-function layer ----------------------------------------------------


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    """Navigate nested dicts safely; return default on any miss."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        if k not in cur:
            return default
        cur = cur[k]
    return cur


def evaluate_tomas_slot(complete_marker: Any, cross_welle_envelope: Any) -> dict:
    """Tomas slot: COMPLETE-marker (Tag-42) + cross-welle envelope (Tag-49)."""
    findings: list[str] = []
    if complete_marker is None and cross_welle_envelope is None:
        return {
            "persona": "tomas",
            "status": "PENDING",
            "details": "neither COMPLETE-marker nor cross-welle envelope found",
            "findings": findings,
        }
    have_marker = complete_marker is not None
    have_env = cross_welle_envelope is not None
    marker_status = _safe_get(complete_marker, "status")
    wellen_complete = _safe_get(complete_marker, "wellen_complete", default=0)
    cross_verdict = _safe_get(cross_welle_envelope, "verdict")

    if have_marker:
        if marker_status not in ("COMPLETE", "IN_PROGRESS"):
            return {
                "persona": "tomas",
                "status": "BROKEN",
                "details": f"COMPLETE-marker status invalid: {marker_status!r}",
                "findings": findings,
            }
        if not isinstance(wellen_complete, int) or wellen_complete < 0:
            return {
                "persona": "tomas",
                "status": "BROKEN",
                "details": "wellen_complete missing or invalid",
                "findings": findings,
            }
    if have_env:
        if cross_verdict not in ("CLEAR", "CAUTION", "BLOCK"):
            return {
                "persona": "tomas",
                "status": "BROKEN",
                "details": f"cross-welle envelope verdict invalid: {cross_verdict!r}",
                "findings": findings,
            }
        findings.append(f"cross-welle verdict: {cross_verdict}")

    # READY: COMPLETE-marker with status COMPLETE AND cross-welle envelope.
    if have_marker and marker_status == "COMPLETE" and have_env:
        findings.append(f"wellen_complete: {wellen_complete}")
        return {
            "persona": "tomas",
            "status": "READY",
            "details": "COMPLETE-marker + cross-welle envelope present",
            "findings": findings,
        }
    # PARTIAL: at least one of marker/env present but not COMPLETE yet.
    if have_marker:
        findings.append(f"marker status: {marker_status}")
        findings.append(f"wellen_complete: {wellen_complete}")
    return {
        "persona": "tomas",
        "status": "PARTIAL",
        "details": "marker or envelope present but not yet COMPLETE",
        "findings": findings,
    }


def evaluate_noa_slot(aggregator_history: Any, drift_histograms: Any) -> dict:
    """Noa slot: aggregator-failure-rate history (Tag-38) + drift histograms."""
    findings: list[str] = []
    if aggregator_history is None and drift_histograms is None:
        return {
            "persona": "noa",
            "status": "PENDING",
            "details": "neither aggregator history nor drift histograms found",
            "findings": findings,
        }
    if aggregator_history is not None:
        if not isinstance(aggregator_history, list):
            return {
                "persona": "noa",
                "status": "BROKEN",
                "details": "aggregator-failure-rate-history not a list",
                "findings": findings,
            }
        runs = len(aggregator_history)
        failed = sum(
            1
            for r in aggregator_history
            if isinstance(r, dict) and r.get("conclusion") != "success"
        )
        findings.append(f"aggregator-runs: {runs}")
        findings.append(f"aggregator-failures: {failed}")
    if drift_histograms is not None:
        if not isinstance(drift_histograms, dict):
            return {
                "persona": "noa",
                "status": "BROKEN",
                "details": "drift-histograms not a dict",
                "findings": findings,
            }
        wellen_with_drift = len(drift_histograms)
        findings.append(f"wellen-with-drift-data: {wellen_with_drift}")
    have_both = aggregator_history is not None and drift_histograms is not None
    if have_both:
        return {
            "persona": "noa",
            "status": "READY",
            "details": "aggregator history + drift histograms present",
            "findings": findings,
        }
    return {
        "persona": "noa",
        "status": "PARTIAL",
        "details": "one of aggregator-history / drift-histograms missing",
        "findings": findings,
    }


def evaluate_amara_slot(marathon_state: Any) -> dict:
    """Amara slot: marathon-state coverage across wellen (E2E acceptance signal)."""
    findings: list[str] = []
    if marathon_state is None:
        return {
            "persona": "amara",
            "status": "PENDING",
            "details": "marathon-state.json not found",
            "findings": findings,
        }
    if not isinstance(marathon_state, dict):
        return {
            "persona": "amara",
            "status": "BROKEN",
            "details": "marathon-state not a dict",
            "findings": findings,
        }
    wellen = _safe_get(marathon_state, "wellen")
    if not isinstance(wellen, dict):
        return {
            "persona": "amara",
            "status": "BROKEN",
            "details": "marathon-state.wellen missing or not a dict",
            "findings": findings,
        }
    total_runs = 0
    covered_wellen = 0
    for welle_id in WELLEN:
        block = wellen.get(welle_id)
        if isinstance(block, dict):
            covered_wellen += 1
            t = block.get("cutover_runs_total")
            if isinstance(t, int):
                total_runs += t
    findings.append(f"wellen-covered: {covered_wellen}/{len(WELLEN)}")
    findings.append(f"total-cutover-runs: {total_runs}")
    if covered_wellen == len(WELLEN):
        return {
            "persona": "amara",
            "status": "READY",
            "details": "E2E coverage across all seven wellen present",
            "findings": findings,
        }
    return {
        "persona": "amara",
        "status": "PARTIAL",
        "details": f"E2E coverage partial ({covered_wellen}/{len(WELLEN)})",
        "findings": findings,
    }


def evaluate_selin_slot(marathon_state: Any) -> dict:
    """Selin slot: marathon-state Rust-vs-Python ratios (Persona-Engine cutover)."""
    findings: list[str] = []
    if marathon_state is None:
        return {
            "persona": "selin",
            "status": "PENDING",
            "details": "marathon-state.json not found",
            "findings": findings,
        }
    if not isinstance(marathon_state, dict):
        return {
            "persona": "selin",
            "status": "BROKEN",
            "details": "marathon-state not a dict",
            "findings": findings,
        }
    wellen = _safe_get(marathon_state, "wellen", default={})
    if not isinstance(wellen, dict):
        return {
            "persona": "selin",
            "status": "BROKEN",
            "details": "marathon-state.wellen missing or not a dict",
            "findings": findings,
        }
    rust_total = 0
    python_total = 0
    wellen_with_ratio = 0
    for welle_id in WELLEN:
        block = wellen.get(welle_id)
        if not isinstance(block, dict):
            continue
        rust = block.get("cutover_runs_rust")
        py = block.get("cutover_runs_python_fallback")
        if isinstance(rust, int) and isinstance(py, int):
            wellen_with_ratio += 1
            rust_total += rust
            python_total += py
    findings.append(f"wellen-with-rust-ratio: {wellen_with_ratio}/{len(WELLEN)}")
    if (rust_total + python_total) > 0:
        rust_pct = 100.0 * rust_total / (rust_total + python_total)
        findings.append(f"rust-default-share: {rust_pct:.2f}%")
    if wellen_with_ratio == len(WELLEN):
        return {
            "persona": "selin",
            "status": "READY",
            "details": "Rust-vs-Python ratios present for all seven wellen",
            "findings": findings,
        }
    return {
        "persona": "selin",
        "status": "PARTIAL",
        "details": f"ratios partial ({wellen_with_ratio}/{len(WELLEN)})",
        "findings": findings,
    }


def evaluate_henrik_slot(sign_offs: dict[str, Any]) -> dict:
    """Henrik slot: per-welle sign-off envelopes (Internal-Audit)."""
    findings: list[str] = []
    if not sign_offs:
        return {
            "persona": "henrik",
            "status": "PENDING",
            "details": "no welle-N-sign-off envelopes found",
            "findings": findings,
        }
    present: list[str] = []
    audit_ok_count = 0
    audit_red_count = 0
    for welle_id in WELLEN:
        env = sign_offs.get(welle_id)
        if env is None:
            continue
        present.append(welle_id)
        if not isinstance(env, dict):
            return {
                "persona": "henrik",
                "status": "BROKEN",
                "details": f"sign-off for {welle_id} not a dict",
                "findings": findings,
            }
        signed_by = env.get("signed_off_by")
        if signed_by != "henrik":
            return {
                "persona": "henrik",
                "status": "BROKEN",
                "details": (
                    f"sign-off for {welle_id} signed_off_by={signed_by!r}, "
                    "expected 'henrik'"
                ),
                "findings": findings,
            }
        audit_ok = env.get("audit_ok")
        if not isinstance(audit_ok, bool):
            return {
                "persona": "henrik",
                "status": "BROKEN",
                "details": f"sign-off for {welle_id} audit_ok not boolean",
                "findings": findings,
            }
        if audit_ok:
            audit_ok_count += 1
        else:
            audit_red_count += 1
    findings.append(f"sign-offs-present: {len(present)}/{len(WELLEN)}")
    findings.append(f"audit-ok-count: {audit_ok_count}")
    findings.append(f"audit-red-count: {audit_red_count}")
    if len(present) == len(WELLEN) and audit_red_count == 0:
        return {
            "persona": "henrik",
            "status": "READY",
            "details": "all seven sign-offs present, all audit_ok=true",
            "findings": findings,
        }
    if len(present) == len(WELLEN) and audit_red_count > 0:
        # Sign-offs complete but some red -- not BROKEN structurally,
        # but the marathon is not READY (Henrik recorded red findings).
        return {
            "persona": "henrik",
            "status": "PARTIAL",
            "details": f"all sign-offs present but {audit_red_count} red",
            "findings": findings,
        }
    return {
        "persona": "henrik",
        "status": "PARTIAL",
        "details": f"sign-offs partial ({len(present)}/{len(WELLEN)})",
        "findings": findings,
    }


def aggregate_bilanz(
    slots: list[dict],
    mode: str,
    sign_offs_count: int,
    marker_status: str | None,
) -> dict:
    """Compose the marathon-aggregate verdict from the five persona slots.

    Args:
        slots: list of five persona slot dicts.
        mode: 'daily' or 'post-welle-7'.
        sign_offs_count: number of welle-N-sign-off envelopes present.
        marker_status: COMPLETE-marker.status or None.
    Returns:
        dict with verdict + summary counts.
    """
    counts = {"READY": 0, "PARTIAL": 0, "PENDING": 0, "BROKEN": 0}
    for s in slots:
        st = s.get("status")
        if st in counts:
            counts[st] += 1
    have_broken = counts["BROKEN"] > 0
    have_pending = counts["PENDING"] > 0
    have_partial = counts["PARTIAL"] > 0
    all_ready = counts["READY"] == len(slots)

    if have_broken:
        verdict = "MARATHON_BROKEN"
    elif mode == "post-welle-7" and have_pending:
        # In post-welle-7 mode, every persona is expected to have
        # delivered. PENDING is loud-failure.
        verdict = "MARATHON_BROKEN"
    elif (
        all_ready
        and sign_offs_count == len(WELLEN)
        and marker_status == "COMPLETE"
    ):
        verdict = "MARATHON_READY"
    elif have_pending or have_partial:
        verdict = "MARATHON_IN_FLIGHT"
    else:
        # all_ready but COMPLETE-marker not yet COMPLETE: mid-marathon
        verdict = "MARATHON_IN_FLIGHT"

    return {
        "verdict": verdict,
        "slot_counts": counts,
        "sign_offs_present": sign_offs_count,
        "sign_offs_expected": len(WELLEN),
        "complete_marker_status": marker_status or "ABSENT",
    }


def render_markdown(envelope: dict) -> str:
    """Render a deterministic Markdown bilanz from the envelope."""
    lines: list[str] = []
    lines.append("# Phase-3 Marathon-Final-Bilanz")
    lines.append("")
    lines.append(f"- **Snapshot:** {envelope.get('snapshot_at', '<n/a>')}")
    lines.append(f"- **Mode:** {envelope.get('mode', '<n/a>')}")
    lines.append(f"- **Schema:** {envelope.get('schema_version', '<n/a>')}")
    lines.append("")
    lines.append("## Aggregate Verdict")
    lines.append("")
    agg = envelope.get("aggregate", {})
    lines.append(f"**Verdict:** `{agg.get('verdict', 'UNKNOWN')}`")
    lines.append("")
    counts = agg.get("slot_counts", {})
    lines.append(
        f"- Slots READY/PARTIAL/PENDING/BROKEN: "
        f"{counts.get('READY', 0)}/{counts.get('PARTIAL', 0)}/"
        f"{counts.get('PENDING', 0)}/{counts.get('BROKEN', 0)}"
    )
    lines.append(
        f"- Welle-Sign-offs: {agg.get('sign_offs_present', 0)}/"
        f"{agg.get('sign_offs_expected', 0)}"
    )
    lines.append(
        f"- COMPLETE-Marker: `{agg.get('complete_marker_status', 'ABSENT')}`"
    )
    lines.append("")
    lines.append("## Per-Persona Slots")
    lines.append("")
    lines.append("| Persona | Status | Details |")
    lines.append("|---------|--------|---------|")
    for slot in envelope.get("slots", []):
        persona = slot.get("persona", "?")
        status = slot.get("status", "?")
        details = (slot.get("details", "") or "").replace("|", "\\|")
        lines.append(f"| {persona} | `{status}` | {details} |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    for slot in envelope.get("slots", []):
        persona = slot.get("persona", "?")
        findings = slot.get("findings", [])
        if not findings:
            continue
        lines.append(f"### {persona}")
        lines.append("")
        for f in findings:
            lines.append(f"- {f}")
        lines.append("")
    lines.append("## Welle-Sign-Off Roster")
    lines.append("")
    lines.append("| Welle | Sign-Off | Audit-OK |")
    lines.append("|-------|----------|----------|")
    sign_off_roster = envelope.get("sign_off_roster", [])
    for entry in sign_off_roster:
        welle = entry.get("welle", "?")
        present = "present" if entry.get("present") else "absent"
        audit_ok = entry.get("audit_ok")
        ok_str = "n/a" if audit_ok is None else ("ok" if audit_ok else "red")
        lines.append(f"| {welle} | {present} | {ok_str} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_envelope(
    *,
    snapshot_at: str,
    mode: str,
    complete_marker: Any,
    cross_welle_envelope: Any,
    aggregator_history: Any,
    drift_histograms: Any,
    marathon_state: Any,
    sign_offs: dict[str, Any],
) -> dict:
    """Build the full bilanz envelope from parsed inputs."""
    slots = [
        evaluate_tomas_slot(complete_marker, cross_welle_envelope),
        evaluate_noa_slot(aggregator_history, drift_histograms),
        evaluate_amara_slot(marathon_state),
        evaluate_selin_slot(marathon_state),
        evaluate_henrik_slot(sign_offs),
    ]
    marker_status = _safe_get(complete_marker, "status")
    sign_offs_count = sum(1 for w in WELLEN if w in sign_offs)
    aggregate = aggregate_bilanz(slots, mode, sign_offs_count, marker_status)

    sign_off_roster = []
    for welle_id in WELLEN:
        env = sign_offs.get(welle_id)
        if env is None:
            sign_off_roster.append(
                {"welle": welle_id, "present": False, "audit_ok": None}
            )
        else:
            sign_off_roster.append(
                {
                    "welle": welle_id,
                    "present": True,
                    "audit_ok": env.get("audit_ok") if isinstance(env, dict) else None,
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_at": snapshot_at,
        "mode": mode,
        "aggregate": aggregate,
        "slots": slots,
        "sign_off_roster": sign_off_roster,
    }


# --- I/O boundary -----------------------------------------------------------


def _read_json(path: pathlib.Path) -> Any:
    """Read a JSON file; return None if missing, raise on parse error."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"FATAL: malformed JSON at {path}: {e}") from e


def _read_sign_offs(state_dir: pathlib.Path) -> dict[str, Any]:
    """Read all welle-N-sign-off.json files found in state_dir."""
    out: dict[str, Any] = {}
    for welle_id in WELLEN:
        # File naming: welle-N-sign-off.json (no slug suffix).
        # Slug extraction: welle-N from welle-N-slug -> "welle-N"
        # Then look for "welle-N-sign-off.json".
        parts = welle_id.split("-")
        if len(parts) >= 2 and parts[0] == "welle":
            short = f"{parts[0]}-{parts[1]}"  # e.g. "welle-3"
        else:
            short = welle_id
        candidate = state_dir / f"{short}-sign-off.json"
        if candidate.exists():
            out[welle_id] = _read_json(candidate)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Marathon-Final-Bilanz Aggregator (Tag-50 / Tomas)"
    )
    parser.add_argument(
        "--state-dir",
        default="state",
        help="State directory holding sign-off envelopes and marathon-state files.",
    )
    parser.add_argument(
        "--cross-welle-envelope",
        default="out/cross-welle-hot-spot-verdict.json",
        help="Tomas cross-welle hot-spot envelope (Tag-49).",
    )
    parser.add_argument(
        "--complete-marker",
        default=None,
        help="Path to phase-3-complete-marker.json (defaults to state-dir/...).",
    )
    parser.add_argument(
        "--marathon-state",
        default=None,
        help="Path to phase-3-marathon-state.json (defaults to state-dir/...).",
    )
    parser.add_argument(
        "--aggregator-history",
        default=None,
        help="Path to aggregator-failure-rate-history.json.",
    )
    parser.add_argument(
        "--drift-histograms",
        default=None,
        help="Path to cross-welle-drift-histograms.json.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Output directory for bilanz Markdown + JSON.",
    )
    parser.add_argument(
        "--snapshot-at",
        default=None,
        help="ISO timestamp for the snapshot field (UTC). Defaults to now.",
    )
    parser.add_argument(
        "--mode",
        choices=("daily", "post-welle-7"),
        default="daily",
        help="Aggregation mode: daily (during marathon) or post-welle-7 (final).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on MARATHON_BROKEN (default: always exit 0).",
    )
    parser.add_argument(
        "--print-stdout",
        action="store_true",
        help="Also print the JSON envelope to stdout.",
    )
    args = parser.parse_args(argv)

    state_dir = pathlib.Path(args.state_dir)
    output_dir = pathlib.Path(args.output_dir)

    complete_marker_path = pathlib.Path(
        args.complete_marker or (state_dir / "phase-3-complete-marker.json")
    )
    marathon_state_path = pathlib.Path(
        args.marathon_state or (state_dir / "phase-3-marathon-state.json")
    )
    aggregator_history_path = pathlib.Path(
        args.aggregator_history
        or (state_dir / "aggregator-failure-rate-history.json")
    )
    drift_histograms_path = pathlib.Path(
        args.drift_histograms or (state_dir / "cross-welle-drift-histograms.json")
    )
    cross_welle_envelope_path = pathlib.Path(args.cross_welle_envelope)

    complete_marker = _read_json(complete_marker_path)
    marathon_state = _read_json(marathon_state_path)
    aggregator_history = _read_json(aggregator_history_path)
    drift_histograms = _read_json(drift_histograms_path)
    cross_welle_envelope = _read_json(cross_welle_envelope_path)
    sign_offs = _read_sign_offs(state_dir)

    if args.snapshot_at:
        snapshot_at = args.snapshot_at
    else:
        import datetime
        snapshot_at = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    envelope = build_envelope(
        snapshot_at=snapshot_at,
        mode=args.mode,
        complete_marker=complete_marker,
        cross_welle_envelope=cross_welle_envelope,
        aggregator_history=aggregator_history,
        drift_histograms=drift_histograms,
        marathon_state=marathon_state,
        sign_offs=sign_offs,
    )
    markdown = render_markdown(envelope)

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "marathon-final-bilanz.md"
    json_path = output_dir / "marathon-final-bilanz.json"
    with md_path.open("w", encoding="utf-8") as f:
        f.write(markdown)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, sort_keys=True)
        f.write("\n")

    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))

    verdict = envelope["aggregate"]["verdict"]
    print(
        f"[marathon-final-bilanz] verdict={verdict} "
        f"md={md_path} json={json_path}",
        file=sys.stderr,
    )

    if args.strict and verdict == "MARATHON_BROKEN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
