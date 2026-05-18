#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-3 Hot-Spot probe aggregator (Tag-45).

Background
----------

Henrik's Tag-44 Phase-3-Marathon Pre-Mortem
(``reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md``)
identifies **Welle-3 (bridge-audit-writer)** as the #1 cross-Welle
hot-spot.  Welle-3 ships as a *solo* cutover (KW-25, Mon
2026-06-15 08:00..10:00 CEST) but its bridge-audit-writer becomes
the Audit-Oracle for the Welle-4 / Welle-5 / Welle-7 sign-offs that
follow.  Three structural risks couple to this hot-spot:

* A5 -- *Self-Reference-Trap*: bridge-audit-writer auditing itself
  through the same audit-bridge can amplify a drift signal into a
  recursion loop (Pre-Mortem T+12min BackendDecision event-rate
  +340% scenario).
* B3 -- *IIA-1130-Conflict*: AR-designated external pre-auditor for
  the Welle-3 audit-substrate is a marathon pre-condition; if the
  live observation defaults to Henrik (Cutover-Day-Audit spec
  default-path), latency builds on a self-audit.
* Welle-3 -> Welle-4 / Welle-5 / Welle-7 cross-Welle propagation:
  bridge-audit-writer is the single source of audit-truth for three
  downstream Welle sign-offs.

This aggregator emits a daily *hot-spot* envelope for the Welle-3
cutover-window (Tag-45 dispatch through KW-25 cutover) that
surfaces these risks independently of the Marathon-Dashboard's
verdict roll-up.  It is intentionally **narrow**: only Welle-3 and
its three downstream couplings.  The aggregator does not replace
the Marathon-Dashboard; it complements it with a Welle-3-specific
day-over-day indicator stream.

Hot-Spot indicators
-------------------

The aggregator computes four indicators from input probe envelopes:

1.  **SRT (Self-Reference-Trap) pre-detection**.  Looks for
    bridge-audit-writer event-rate spikes vs. baseline.  Input is
    a ``self_reference_trap`` block with optional fields
    ``event_rate_per_min``, ``baseline_event_rate_per_min`` and
    ``observation_window_minutes``.  An event-rate >= 2.0x baseline
    is **CAUTION**; >= 3.4x (Pre-Mortem worst-case threshold) is
    **BLOCK**.  Absence of the block defaults to **NOT-EXEC**.

2.  **CWP (Cross-Welle-Propagation-Risk) indicator**.  Reads the
    Welle-3 probe verdict plus the verdicts of Welle-4 / Welle-5 /
    Welle-7 if available.  If Welle-3 is GREEN/CAUTION but any of
    {4,5,7} is BLOCK, the downstream consumer has already drifted
    from the audit-substrate -- this is the cross-Welle propagation
    risk Henrik calls out.  If Welle-3 itself is BLOCK, the
    indicator is **BLOCK** regardless of downstream state.

3.  **IOP (Independent-Oracle-Probe) score**.  Reads a separate
    ``independent_oracle`` block computed by an independent
    audit-stream (NOT the bridge-audit-writer being probed).  The
    aggregator runs *doppelbetrieb* scoring: it compares the
    bridge-audit-writer's self-reported probe verdict against the
    independent-oracle's verdict and emits an agreement score.
    Disagreement at the GREEN-vs-BLOCK boundary is **BLOCK**.

4.  **IIA-1130 Pre-Auditor-Decision tracking**.  Reads an
    ``iia_1130`` block with an AR-Decision field of one of
    ``pending``, ``external_pre_auditor_designated``,
    ``henrik_default_path``, or ``decision_blocked``.  Pre-Mortem
    B3 sets ``external_pre_auditor_designated`` as the only path
    consistent with Welle-3 marathon-readiness.  Anything else is
    surfaced as **CAUTION** (pending) or **BLOCK** (decision_blocked).

Hot-spot verdict aggregation
----------------------------

The aggregator emits a single **hot_spot_verdict** of GREEN,
CAUTION, BLOCK, or NOT-EXEC, computed across the four indicators:

* Any indicator BLOCK -> hot_spot_verdict = BLOCK.
* No BLOCK, any CAUTION -> hot_spot_verdict = CAUTION.
* All four GREEN -> hot_spot_verdict = GREEN.
* Otherwise (NOT-EXEC mixed with GREEN) -> hot_spot_verdict =
  CAUTION (because Welle-3 hot-spot status without all four
  indicators is incomplete observation).
* All four NOT-EXEC -> hot_spot_verdict = NOT-EXEC.

Output
------

A JSON envelope written to ``--output-json`` plus a Markdown
summary written to ``--output-md`` (also suitable for the
``$GITHUB_STEP_SUMMARY`` append step in the companion workflow).
When a notify-feed path is provided via ``--notify-path``, every
non-GREEN hot_spot_verdict appends a single JSONL line.

Hermetic
--------

stdlib only.  No subprocess, no network, no podman, no SSH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


VALID_VERDICTS = ("GREEN", "CAUTION", "BLOCK", "NOT-EXEC")

# Pre-Mortem-derived constants.
SRT_CAUTION_MULTIPLIER = 2.0
SRT_BLOCK_MULTIPLIER = 3.4  # Pre-Mortem 2.1 worst-case +340% scenario.

# Welle-3 hot-spot downstream consumers per Pre-Mortem Cross-Welle
# matrix.  Welle-3 -> Welle-4 (audit-oracle for state-backing),
# Welle-3 -> Welle-5 (audit-trail substrate), Welle-3 -> Welle-7
# (recovery-audit-trail-source).
WELLE_3_DOWNSTREAM = (4, 5, 7)

# IIA-1130 AR-Decision enum.  Only ``external_pre_auditor_designated``
# is marathon-ready.  Anything else degrades the hot_spot_verdict.
IIA_1130_DECISIONS = (
    "pending",
    "external_pre_auditor_designated",
    "henrik_default_path",
    "decision_blocked",
)


# ---------------------------------------------------------------------------
# Verdict normalisation
# ---------------------------------------------------------------------------


def _normalise_verdict(raw: object) -> str:
    """Coerce a verdict-like value into ``VALID_VERDICTS``."""
    if raw is None:
        return "NOT-EXEC"
    v = str(raw).strip().upper().replace("_", "-")
    if v in ("READY", "OK", "PASS"):
        return "GREEN"
    if v in ("WARN", "WARNING", "YELLOW"):
        return "CAUTION"
    if v in ("FAIL", "RED", "ERROR"):
        return "BLOCK"
    if v in ("NOT-EXEC", "NOT-EXECUTED", "SKIP", "SKIPPED", "MISSING", ""):
        return "NOT-EXEC"
    if v in VALID_VERDICTS:
        return v
    return "BLOCK"  # unknown -> loud fail


def _coerce_float(value: object) -> float | None:
    """Best-effort float coercion; None on failure or negative."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    return f


# ---------------------------------------------------------------------------
# Indicator 1 -- Self-Reference-Trap pre-detection
# ---------------------------------------------------------------------------


def evaluate_srt(block: Mapping | None) -> dict:
    """Compute the Self-Reference-Trap indicator from a probe block.

    Expected block schema (all optional)::

        {
            "event_rate_per_min": float,
            "baseline_event_rate_per_min": float,
            "observation_window_minutes": float,
            "probe_present": bool,
        }
    """
    out = {
        "indicator": "self_reference_trap",
        "verdict": "NOT-EXEC",
        "rationale": "no SRT block provided",
        "event_rate_per_min": None,
        "baseline_event_rate_per_min": None,
        "multiplier": None,
        "observation_window_minutes": None,
    }
    if not isinstance(block, Mapping):
        return out

    rate = _coerce_float(block.get("event_rate_per_min"))
    baseline = _coerce_float(block.get("baseline_event_rate_per_min"))
    window = _coerce_float(block.get("observation_window_minutes"))
    out["event_rate_per_min"] = rate
    out["baseline_event_rate_per_min"] = baseline
    out["observation_window_minutes"] = window

    # Honour an explicit verdict override if the probe gave one.
    explicit = _normalise_verdict(block.get("verdict"))
    if explicit != "NOT-EXEC" and rate is None:
        out["verdict"] = explicit
        out["rationale"] = f"explicit verdict from probe ({explicit})"
        return out

    if rate is None or baseline is None or baseline == 0.0:
        out["verdict"] = "NOT-EXEC"
        out["rationale"] = "SRT input incomplete (rate or baseline missing)"
        return out

    multiplier = rate / baseline
    out["multiplier"] = round(multiplier, 3)
    if multiplier >= SRT_BLOCK_MULTIPLIER:
        out["verdict"] = "BLOCK"
        out["rationale"] = (
            f"event-rate {rate:.1f}/min is {multiplier:.2f}x baseline "
            f"({baseline:.1f}); crosses Pre-Mortem BLOCK threshold "
            f"{SRT_BLOCK_MULTIPLIER:.2f}x"
        )
    elif multiplier >= SRT_CAUTION_MULTIPLIER:
        out["verdict"] = "CAUTION"
        out["rationale"] = (
            f"event-rate {rate:.1f}/min is {multiplier:.2f}x baseline "
            f"({baseline:.1f}); crosses CAUTION threshold "
            f"{SRT_CAUTION_MULTIPLIER:.2f}x"
        )
    else:
        out["verdict"] = "GREEN"
        out["rationale"] = (
            f"event-rate {rate:.1f}/min is {multiplier:.2f}x baseline "
            f"({baseline:.1f}); below CAUTION threshold"
        )
    return out


# ---------------------------------------------------------------------------
# Indicator 2 -- Cross-Welle-Propagation-Risk
# ---------------------------------------------------------------------------


def evaluate_cwp(welle_3_verdict: str, downstream_verdicts: Mapping[int, str]) -> dict:
    """Compute the Cross-Welle-Propagation indicator.

    ``welle_3_verdict`` is normalised already.  ``downstream_verdicts``
    maps welle-number (4, 5, 7) to its normalised verdict.
    """
    out: dict = {
        "indicator": "cross_welle_propagation_risk",
        "verdict": "NOT-EXEC",
        "rationale": "",
        "welle_3_verdict": welle_3_verdict,
        "downstream_verdicts": {
            str(k): downstream_verdicts.get(k, "NOT-EXEC")
            for k in WELLE_3_DOWNSTREAM
        },
        "downstream_block_set": [],
        "downstream_caution_set": [],
    }

    if welle_3_verdict == "BLOCK":
        out["verdict"] = "BLOCK"
        out["rationale"] = (
            "Welle-3 itself is BLOCK; downstream Welle-4/5/7 inherit "
            "broken audit-substrate"
        )
        return out

    if welle_3_verdict == "NOT-EXEC":
        out["verdict"] = "NOT-EXEC"
        out["rationale"] = (
            "Welle-3 probe not executed; cannot assess downstream propagation"
        )
        return out

    block_set = [
        n for n in WELLE_3_DOWNSTREAM
        if downstream_verdicts.get(n, "NOT-EXEC") == "BLOCK"
    ]
    caution_set = [
        n for n in WELLE_3_DOWNSTREAM
        if downstream_verdicts.get(n, "NOT-EXEC") == "CAUTION"
    ]
    out["downstream_block_set"] = block_set
    out["downstream_caution_set"] = caution_set

    if block_set:
        out["verdict"] = "BLOCK"
        out["rationale"] = (
            f"Welle-3={welle_3_verdict} but Welle-{block_set} are BLOCK; "
            "downstream drift from audit-substrate"
        )
        return out
    if caution_set:
        out["verdict"] = "CAUTION"
        out["rationale"] = (
            f"Welle-3={welle_3_verdict} but Welle-{caution_set} are "
            "CAUTION; downstream watching"
        )
        return out
    out["verdict"] = "GREEN" if welle_3_verdict == "GREEN" else "CAUTION"
    out["rationale"] = (
        f"Welle-3={welle_3_verdict}; all downstream Welle-4/5/7 "
        "non-BLOCK; no propagation indicator triggered"
    )
    return out


# ---------------------------------------------------------------------------
# Indicator 3 -- Independent-Oracle-Probe (doppelbetrieb)
# ---------------------------------------------------------------------------


def evaluate_iop(
    welle_3_verdict: str,
    block: Mapping | None,
) -> dict:
    """Compute the Independent-Oracle-Probe doppelbetrieb score.

    Expected block schema::

        {
            "verdict": "GREEN"|"CAUTION"|"BLOCK"|"NOT-EXEC",
            "source": str,              # e.g. "external-oracle-stream"
        }
    """
    out: dict = {
        "indicator": "independent_oracle_probe",
        "verdict": "NOT-EXEC",
        "rationale": "no independent-oracle block provided",
        "welle_3_verdict": welle_3_verdict,
        "independent_verdict": "NOT-EXEC",
        "source": None,
        "agreement_score": None,
    }
    if not isinstance(block, Mapping):
        return out
    independent = _normalise_verdict(block.get("verdict"))
    source = block.get("source")
    out["independent_verdict"] = independent
    out["source"] = str(source) if source is not None else None

    if independent == "NOT-EXEC":
        out["verdict"] = "NOT-EXEC"
        out["rationale"] = "independent-oracle verdict missing"
        return out
    if welle_3_verdict == "NOT-EXEC":
        out["verdict"] = "NOT-EXEC"
        out["rationale"] = (
            "Welle-3 probe verdict missing; cannot doppelbetrieb-compare"
        )
        return out

    # Agreement-score: 1.0 perfect agreement, 0.0 at GREEN-vs-BLOCK
    # boundary (worst doppelbetrieb miss).
    rank = {"GREEN": 0, "CAUTION": 1, "BLOCK": 2}
    distance = abs(rank.get(welle_3_verdict, 1) - rank.get(independent, 1))
    score = 1.0 - (distance / 2.0)
    out["agreement_score"] = round(score, 3)

    if distance == 0:
        out["verdict"] = welle_3_verdict if welle_3_verdict != "NOT-EXEC" else "GREEN"
        out["rationale"] = (
            f"doppelbetrieb agreement: probe={welle_3_verdict}, "
            f"independent={independent}"
        )
        return out
    if distance == 2:
        # GREEN-vs-BLOCK boundary disagreement.
        out["verdict"] = "BLOCK"
        out["rationale"] = (
            f"doppelbetrieb disagreement at GREEN-vs-BLOCK boundary: "
            f"probe={welle_3_verdict}, independent={independent}; "
            "one oracle is wrong, marathon halt"
        )
        return out
    # distance == 1
    out["verdict"] = "CAUTION"
    out["rationale"] = (
        f"doppelbetrieb partial disagreement (one step): "
        f"probe={welle_3_verdict}, independent={independent}"
    )
    return out


# ---------------------------------------------------------------------------
# Indicator 4 -- IIA-1130 Pre-Auditor-Decision tracking
# ---------------------------------------------------------------------------


def evaluate_iia_1130(block: Mapping | None) -> dict:
    """Track AR-Decision on Welle-3 external pre-auditor (Pre-Mortem B3)."""
    out: dict = {
        "indicator": "iia_1130_pre_auditor_decision",
        "verdict": "NOT-EXEC",
        "rationale": "no IIA-1130 block provided",
        "ar_decision": "absent",
        "decision_age_days": None,
        "decision_target_kw": 25,
    }
    if not isinstance(block, Mapping):
        return out
    raw_decision = block.get("ar_decision")
    decision = (str(raw_decision).strip().lower() if raw_decision else "absent")
    if decision in IIA_1130_DECISIONS:
        out["ar_decision"] = decision
    else:
        out["ar_decision"] = "absent"
    age = _coerce_float(block.get("decision_age_days"))
    out["decision_age_days"] = age

    if out["ar_decision"] == "external_pre_auditor_designated":
        out["verdict"] = "GREEN"
        out["rationale"] = (
            "AR-designated external pre-auditor in place; B3 risk mitigated"
        )
    elif out["ar_decision"] == "henrik_default_path":
        out["verdict"] = "BLOCK"
        out["rationale"] = (
            "IIA-1130 conflict: live observation defaults to Henrik "
            "(Cutover-Day-Audit spec default); external pre-auditor "
            "designation missing"
        )
    elif out["ar_decision"] == "decision_blocked":
        out["verdict"] = "BLOCK"
        out["rationale"] = "AR-Decision explicitly blocked"
    elif out["ar_decision"] == "pending":
        out["verdict"] = "CAUTION"
        out["rationale"] = (
            "AR-Decision pending; B3 risk latent. Must resolve before KW-25"
        )
    else:
        # absent
        out["verdict"] = "NOT-EXEC"
        out["rationale"] = "AR-Decision field absent from input"
    return out


# ---------------------------------------------------------------------------
# Hot-spot verdict aggregation
# ---------------------------------------------------------------------------


def aggregate_hot_spot(indicator_verdicts: list[str]) -> str:
    """Aggregate the four indicator verdicts into the hot_spot_verdict."""
    counts = {v: 0 for v in VALID_VERDICTS}
    for v in indicator_verdicts:
        counts[v] = counts.get(v, 0) + 1
    if counts["BLOCK"] >= 1:
        return "BLOCK"
    if counts["CAUTION"] >= 1:
        return "CAUTION"
    if counts["NOT-EXEC"] == 4:
        return "NOT-EXEC"
    if counts["GREEN"] == 4:
        return "GREEN"
    # Mixed GREEN + NOT-EXEC: observation incomplete.
    return "CAUTION"


# ---------------------------------------------------------------------------
# Envelope build + markdown rendering
# ---------------------------------------------------------------------------


def build_envelope(
    inputs: Mapping,
    *,
    today_iso: str | None = None,
    github_env: Mapping[str, str] | None = None,
) -> dict:
    """Build the hot-spot envelope from the structured input dict."""
    github_env = github_env or {}

    welle_3_block = inputs.get("welle_3_probe") or {}
    if not isinstance(welle_3_block, Mapping):
        welle_3_block = {}
    welle_3_verdict = _normalise_verdict(welle_3_block.get("verdict"))

    # Downstream verdicts.
    downstream_block = inputs.get("downstream_probes") or {}
    if not isinstance(downstream_block, Mapping):
        downstream_block = {}
    downstream_verdicts: dict[int, str] = {}
    for n in WELLE_3_DOWNSTREAM:
        entry = downstream_block.get(str(n)) or downstream_block.get(n)
        if isinstance(entry, Mapping):
            downstream_verdicts[n] = _normalise_verdict(entry.get("verdict"))
        elif entry is None:
            downstream_verdicts[n] = "NOT-EXEC"
        else:
            downstream_verdicts[n] = _normalise_verdict(entry)

    srt = evaluate_srt(inputs.get("self_reference_trap"))
    cwp = evaluate_cwp(welle_3_verdict, downstream_verdicts)
    iop = evaluate_iop(welle_3_verdict, inputs.get("independent_oracle"))
    iia = evaluate_iia_1130(inputs.get("iia_1130"))

    indicator_verdicts = [srt["verdict"], cwp["verdict"], iop["verdict"], iia["verdict"]]
    hot_spot = aggregate_hot_spot(indicator_verdicts)

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "workflow": "phase-3c-welle-3-hot-spot-probe",
        "tag": "Tag-45",
        "emitted_at_utc": now_utc,
        "snapshot_date": today_iso or now_utc[:10],
        "github_run_id": github_env.get("GITHUB_RUN_ID"),
        "github_sha": github_env.get("GITHUB_SHA"),
        "github_ref": github_env.get("GITHUB_REF"),
        "welle": 3,
        "component": "bridge_audit_writer",
        "cutover_kw": 25,
        "cutover_day_window": (
            "2026-06-15T08:00:00+02:00/2026-06-15T10:00:00+02:00"
        ),
        "welle_3_verdict": welle_3_verdict,
        "downstream_verdicts": {
            str(k): downstream_verdicts[k] for k in WELLE_3_DOWNSTREAM
        },
        "indicators": {
            "self_reference_trap": srt,
            "cross_welle_propagation_risk": cwp,
            "independent_oracle_probe": iop,
            "iia_1130_pre_auditor_decision": iia,
        },
        "hot_spot_verdict": hot_spot,
        "pre_mortem_anchor": {
            "report": "reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md",
            "failure_modes": ["A5", "B3", "A1 (cross-Welle drift)"],
            "cross_welle_targets": list(WELLE_3_DOWNSTREAM),
        },
    }


def render_markdown(envelope: Mapping) -> str:
    """Render the envelope as a human-readable Markdown report."""
    lines: list[str] = []
    hot = envelope.get("hot_spot_verdict", "NOT-EXEC")
    lines.append(
        f"# Phase-3c Welle-3 Hot-Spot Probe -- {envelope.get('snapshot_date')}"
    )
    lines.append("")
    lines.append(f"**Hot-Spot-Verdict:** `{hot}`")
    lines.append("")
    lines.append(
        f"Welle-3 component: `{envelope.get('component')}`; "
        f"cutover KW-{envelope.get('cutover_kw')} "
        f"({envelope.get('cutover_day_window')})."
    )
    lines.append("")
    lines.append("## Indicator verdicts")
    lines.append("")
    lines.append("| Indicator | Verdict | Rationale |")
    lines.append("|---|---|---|")
    indicators = envelope.get("indicators") or {}
    label_map = {
        "self_reference_trap": "Self-Reference-Trap pre-detection",
        "cross_welle_propagation_risk": "Cross-Welle-Propagation-Risk",
        "independent_oracle_probe": "Independent-Oracle-Probe (doppelbetrieb)",
        "iia_1130_pre_auditor_decision": "IIA-1130 Pre-Auditor-Decision",
    }
    for key in (
        "self_reference_trap",
        "cross_welle_propagation_risk",
        "independent_oracle_probe",
        "iia_1130_pre_auditor_decision",
    ):
        ind = indicators.get(key) or {}
        verdict = ind.get("verdict", "NOT-EXEC")
        rationale = str(ind.get("rationale", "")).replace("|", "/")
        lines.append(f"| {label_map[key]} | `{verdict}` | {rationale} |")
    lines.append("")
    lines.append("## Welle-3 + downstream verdicts")
    lines.append("")
    lines.append("| Welle | Verdict |")
    lines.append("|---|---|")
    lines.append(f"| Welle-3 (bridge-audit-writer, KW-25) | `{envelope.get('welle_3_verdict')}` |")
    downstream = envelope.get("downstream_verdicts") or {}
    for n in WELLE_3_DOWNSTREAM:
        lines.append(f"| Welle-{n} (downstream consumer) | `{downstream.get(str(n), 'NOT-EXEC')}` |")
    lines.append("")
    lines.append("## Pre-Mortem anchor")
    lines.append("")
    anchor = envelope.get("pre_mortem_anchor") or {}
    lines.append(f"* Report: `{anchor.get('report')}`")
    fms = anchor.get("failure_modes") or []
    lines.append(f"* Failure-Modes tracked: {', '.join(fms) if fms else '(none)'}")
    targets = anchor.get("cross_welle_targets") or []
    targets_str = ", ".join(f"Welle-{n}" for n in targets)
    lines.append(f"* Cross-Welle targets: {targets_str or '(none)'}")
    lines.append("")
    if hot != "GREEN":
        lines.append(
            "_Note: non-GREEN hot-spot verdicts append to "
            "`state/welle-3-hot-spot-notify.jsonl` for Mira-Hand sichtung."
            "_"
        )
    return "\n".join(lines) + "\n"


def append_notify(
    notify_path: Path,
    envelope: Mapping,
) -> bool:
    """Append a JSONL notify-event if hot_spot_verdict != GREEN.

    Returns True iff an event was appended.
    """
    verdict = envelope.get("hot_spot_verdict")
    if verdict == "GREEN":
        return False
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts_utc": envelope.get("emitted_at_utc"),
        "workflow": envelope.get("workflow"),
        "snapshot_date": envelope.get("snapshot_date"),
        "hot_spot_verdict": verdict,
        "welle_3_verdict": envelope.get("welle_3_verdict"),
        "indicator_verdicts": {
            k: (envelope.get("indicators") or {}).get(k, {}).get("verdict")
            for k in (
                "self_reference_trap",
                "cross_welle_propagation_risk",
                "independent_oracle_probe",
                "iia_1130_pre_auditor_decision",
            )
        },
        "github_run_id": envelope.get("github_run_id"),
    }
    with notify_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_input(path: Path | None) -> dict:
    """Load the structured input dict from JSON, or return defaults."""
    if path is None:
        return {}
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Welle-3 hot-spot aggregator (Tag-45)",
    )
    ap.add_argument(
        "--input-json",
        type=Path,
        help=(
            "Path to a JSON file with keys "
            "{welle_3_probe, downstream_probes, self_reference_trap, "
            "independent_oracle, iia_1130}. Missing keys default to "
            "NOT-EXEC indicators."
        ),
    )
    ap.add_argument(
        "--today",
        default=None,
        help="Snapshot date yyyy-mm-dd (default: UTC today).",
    )
    ap.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Write the hot-spot envelope JSON to this path.",
    )
    ap.add_argument(
        "--output-md",
        type=Path,
        required=True,
        help="Write the Markdown summary to this path.",
    )
    ap.add_argument(
        "--notify-path",
        type=Path,
        default=None,
        help=(
            "Append a JSONL notify-event when hot_spot_verdict != GREEN."
        ),
    )
    ap.add_argument(
        "--exit-on-block",
        action="store_true",
        help=(
            "Exit with non-zero status if hot_spot_verdict is BLOCK. "
            "Default off (the workflow is signal, not gate)."
        ),
    )
    args = ap.parse_args(argv)

    inputs = _load_input(args.input_json)
    envelope = build_envelope(
        inputs,
        today_iso=args.today,
        github_env={
            k: os.environ.get(k, "") or ""
            for k in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_REF")
        },
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(envelope), encoding="utf-8")

    if args.notify_path is not None:
        append_notify(args.notify_path, envelope)

    print(f"hot_spot_verdict={envelope['hot_spot_verdict']}")
    if args.exit_on_block and envelope["hot_spot_verdict"] == "BLOCK":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
