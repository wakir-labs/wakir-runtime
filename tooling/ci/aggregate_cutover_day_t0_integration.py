#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-70 Cutover-Day-T0 Integration-Smoke verdict aggregator (Amara).

The Tag-70 Cutover-Day-T0 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the four Day-1-of-T0 substrates that the
2026-06-08 Welle-1-Cutover-Day pipeline triggers in sequence:

* ``S1`` welle_1_producer
    Selin Tag-69 Welle-1 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-1.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status invariants.

* ``S2`` welle_1_audit_anchor
    Tomas Tag-69 Welle-1 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-1 sign-off bundle
    on disk and runs ``tooling/ci/wire_welle_1_audit_trail_anchor.py``
    to compute and emit the anchor envelope. The simulation
    verifies the envelope's ``audit_trail_anchor`` field is a
    64-hex SHA-256 hash and the bundle-keys match the producer's
    rollup-links.

* ``S3`` live_smoke_stability_window
    Noa Tag-69 Live-Smoke Stability-Window-Probe simulation.
    The hermetic stage reads the stability-window envelope shape
    produced by ``aggregate_live_smoke_stability_window.py`` and
    asserts the trinary verdict surface (READY / DRIFT / DEFECT)
    matches the expected T0-Day-1 stability gate.

* ``S4`` auto_scheduler
    Selin Tag-64 Cutover-Day-Morgen Auto-Scheduler simulation
    folded with the Tag-66 sidecar wiring. The hermetic stage
    invokes ``aggregate_cutover_day_morgen_verdict.py`` against
    the three input verdict envelopes (engine, pyramide, e2e)
    and verifies the scheduler's decision rule fires the
    expected dispatch-mode for the simulated T0 inputs.

Aggregated verdict
------------------

The Tag-70 aggregator emits a single trinary verdict for the
T0-Day-1 integration-pipeline:

* ``T0-INTEGRATION-INTACT`` -- all four stage verdicts green.
  The Day-1-pipeline simulation is end-to-end clean; the actual
  T0 trigger on 2026-06-08 has hermetic-evidence of substrate
  contract-stability.
* ``T0-INTEGRATION-DRIFT`` -- at least one stage yellow, zero red.
  The pipeline simulates with degraded signal on at least one
  substrate but no defect; operator-hand reads the per-stage
  notes before the live T0 trigger.
* ``T0-INTEGRATION-DEFECT`` -- at least one stage red, or any
  stage envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break; the cutover-day-runbook
  pauses on the failing substrate before the live T0 trigger.

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual T0 dispatch.
The aggregator is hermetic-by-construction per Mira's Sandbox-vs-
Host-Operations Trennung and the Tag-70 plan §6. The four input
envelopes are read from disk paths supplied by the caller; the
aggregator does not attempt to fetch them via gh CLI or GitHub
API (that is the workflow's job).

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-70 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual T0 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual T0 trigger
is operator-hand on 2026-06-08.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Tag-69 substrate envelopes for the Tag-70
T0-Day-1 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the Noa stability-window-probe (Zone-Noa-observability),
or the Selin auto-scheduler (Zone-O). All four substrate envelopes
are consumed read-only.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from PR-#438
  (Welle-1 State-File Producer). Drift in the pending-status
  invariants is a Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  PR-#439 (Welle-1 audit-trail-anchor integration). Drift in
  the anchor-envelope schema is a Zone-M signal.
* Zone-M: QA x Noa -- live-smoke-stage S3 inherits from PR-#437
  (Live-Smoke Stability-Window-Probe). Drift in the trinary
  verdict-shape is a Zone-M signal.
* Zone-M: QA x Selin -- auto-scheduler-stage S4 inherits from
  the Tag-64 cutover-day-morgen aggregator + Tag-66 sidecar.
  Drift in the dispatch-mode rule is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated T0-INTEGRATION envelope,
  per-stage envelopes, and the workflow-emitted notify-stream
  are Audit-Evidence-Inputs. Drift in their structure or
  completeness is a Zone-N signal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---- Stage ordering ------------------------------------------------------

# Canonical chronological order of the T0-Day-1 pipeline:
#   producer -> audit-anchor -> live-smoke -> auto-scheduler.
# This is the same order in which the four substrates fire on the
# actual 2026-06-08 Welle-1-Cutover-Day pipeline. The aggregator
# preserves this order in step_results / failed_steps / per_note
# so the marathon-dashboard correlation is one-to-one with the
# operator-runbook section ordering.
STAGES: tuple[str, ...] = (
    "welle_1_producer",
    "welle_1_audit_anchor",
    "live_smoke_stability_window",
    "auto_scheduler",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-70 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.

WELLE_1_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-1-PRODUCER-READY": "green",
    "WELLE-1-PRODUCER-DRIFT": "yellow",
    "WELLE-1-PRODUCER-DEFECT": "red",
}

WELLE_1_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-1-AUDIT-ANCHOR-READY": "green",
    "WELLE-1-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-1-AUDIT-ANCHOR-DEFECT": "red",
}

LIVE_SMOKE_STABILITY_WINDOW_VERDICT_MAP: dict[str, str] = {
    "LIVE-SMOKE-STABILITY-WINDOW-READY": "green",
    "LIVE-SMOKE-STABILITY-WINDOW-DRIFT": "yellow",
    "LIVE-SMOKE-STABILITY-WINDOW-DEFECT": "red",
}

AUTO_SCHEDULER_VERDICT_MAP: dict[str, str] = {
    # The Tag-64 auto-scheduler aggregator emits the Cutover-Day-
    # Morgen verdicts. The Tag-70 simulation maps those onto the
    # uniform trinary status for the integration-smoke.
    "CUTOVER-DAY-MORGEN-READY": "green",
    "CUTOVER-DAY-MORGEN-CAUTION": "yellow",
    "CUTOVER-DAY-MORGEN-BLOCK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_1_producer": WELLE_1_PRODUCER_VERDICT_MAP,
    "welle_1_audit_anchor": WELLE_1_AUDIT_ANCHOR_VERDICT_MAP,
    "live_smoke_stability_window": LIVE_SMOKE_STABILITY_WINDOW_VERDICT_MAP,
    "auto_scheduler": AUTO_SCHEDULER_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "T0-INTEGRATION-INTACT"
VERDICT_DRIFT: str = "T0-INTEGRATION-DRIFT"
VERDICT_DEFECT: str = "T0-INTEGRATION-DEFECT"


# ---- T0 anchor constants -------------------------------------------------

# Cutover-Day-T0 is 2026-06-08 (Mo, KW-24). The aggregator
# surfaces this on the envelope for the marathon-dashboard
# correlation; it does NOT enforce the date itself (the workflow
# cron + workflow_dispatch override surface owns the trigger
# window).
T0_ISO_DATE: str = "2026-06-08"
T0_ISO_WEEK: int = 24
T0_WELLE_NUMBER: int = 1


# ---- Substrate provenance ------------------------------------------------

# Cross-anchor PRs for the four Tag-69 substrates the Tag-70
# integration-smoke aggregates. Surfaced on the envelope for the
# Henrik (Zone-N) audit-evidence trail.
SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_1_producer": {
        "owner": "Selin",
        "tag": "tag-69",
        "pr": 438,
        "kind": "persona-engine-welle-1-state-file-producer",
    },
    "welle_1_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-69",
        "pr": 439,
        "kind": "ots-welle-1-audit-trail-anchor-integration",
    },
    "live_smoke_stability_window": {
        "owner": "Noa",
        "tag": "tag-69",
        "pr": 437,
        "kind": "observability-live-smoke-stability-window-probe",
    },
    "auto_scheduler": {
        "owner": "Selin",
        "tag": "tag-64+tag-66",
        "pr": None,
        "kind": "persona-engine-cutover-day-morgen-auto-scheduler-with-sidecar",
    },
}


# ---- Helpers --------------------------------------------------------------


def _load_envelope(path: Path | None) -> dict[str, Any] | None:
    """Read a verdict-envelope JSON from disk.

    Returns ``None`` if the path is ``None`` or does not exist or
    cannot be parsed; the decision rule treats a missing envelope
    as a red signal on that stage (defect-on-missing).
    """
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalise_status(
    stage: str, envelope: Mapping[str, Any] | None
) -> tuple[str, str]:
    """Map an input envelope's ``verdict`` to a uniform trinary status.

    Returns a ``(status, note)`` tuple. ``status`` is one of
    ``green`` / ``yellow`` / ``red``. ``note`` is a short
    human-readable string for the per-stage-notes envelope field
    (empty on green-with-known-verdict).
    """
    if envelope is None:
        return "red", f"{stage}: envelope missing or unparseable"
    raw_verdict = envelope.get("verdict")
    if not isinstance(raw_verdict, str):
        return "red", f"{stage}: envelope has no string 'verdict' field"
    verdict_map = STAGE_VERDICT_MAPS.get(stage)
    if verdict_map is None:
        # Defensive: caller passed a stage key we do not know how
        # to interpret. Should be unreachable given STAGES.
        return "red", f"{stage}: unknown stage key"
    status = verdict_map.get(raw_verdict)
    if status is None:
        return "red", f"{stage}: unknown verdict '{raw_verdict}'"
    if status == "green":
        return status, ""
    return status, f"{stage}: verdict='{raw_verdict}'"


def decide(steps: Mapping[str, str]) -> str:
    """Apply the Tag-70 decision rule.

    Trinary mirroring the Tag-64 cutover-day-morgen pattern: any
    red collapses to DEFECT; any yellow degrades to DRIFT; all
    green yields INTACT.
    """
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return VERDICT_DEFECT
    if yellows >= 1:
        return VERDICT_DRIFT
    if greens == len(steps):
        return VERDICT_INTACT
    # Defensive default. With _normalise_status above, every value
    # is in VALID_STATUSES, so this branch should be unreachable.
    return VERDICT_DEFECT


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated Tag-70 T0-Integration verdict envelope.

    Parameters
    ----------
    envelopes
        Mapping of stage-key (one of ``STAGES``) to the already-
        loaded input envelope (``dict``) or ``None`` if the
        envelope was missing / unparseable.
    iso_week
        Optional ISO calendar week for marathon-dashboard
        correlation. Surfaced on the envelope as
        ``window.iso_week``; does NOT affect the verdict.
    github_run_id, github_sha, github_ref
        Optional GitHub Actions context surfaced verbatim.
    """
    steps: dict[str, str] = {}
    per_note: dict[str, str] = {}
    for stage in STAGES:
        status, note = _normalise_status(stage, envelopes.get(stage))
        steps[stage] = status
        if note:
            per_note[stage] = note
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]
    return {
        "schema_version": 1,
        "workflow": "cutover-day-t0-integration-smoke",
        "tag": "tag-70",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": github_run_id,
        "github_sha": github_sha,
        "github_ref": github_ref,
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "per_stage_notes": per_note,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "t0_anchor": {
            "iso_date": T0_ISO_DATE,
            "iso_week": T0_ISO_WEEK,
            "welle_number": T0_WELLE_NUMBER,
        },
        "window": {
            "iso_week": iso_week,
            "t0_iso_week": T0_ISO_WEEK,
            "in_t0_week": iso_week == T0_ISO_WEEK if iso_week else False,
        },
        "input_verdicts": {
            stage: (
                envelopes[stage].get("verdict")
                if envelopes.get(stage) is not None
                else None
            )
            for stage in STAGES
        },
        "substrate_provenance": SUBSTRATE_PROVENANCE,
        "decision_rule": {
            "intact": (
                "all four stage verdicts green "
                "(welle_1_producer + welle_1_audit_anchor + "
                "live_smoke_stability_window + auto_scheduler)"
            ),
            "drift": "at least one yellow, zero red",
            "defect": "at least one red, OR any envelope missing",
        },
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_t0_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_cutover_day_t0_integration",
        description=(
            "Aggregate the four Tag-69-substrate verdict envelopes "
            "(welle-1-producer, welle-1-audit-anchor, live-smoke-"
            "stability-window, auto-scheduler) into a single "
            "Tag-70 T0-Integration verdict for the 2026-06-08 "
            "Welle-1-Cutover-Day Day-1 pipeline simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Tag-69 Welle-1 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Tag-69 Welle-1 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--live-smoke-envelope",
        type=Path,
        default=None,
        help="Path to Noa Tag-69 live-smoke-stability-window-stage envelope JSON.",
    )
    p.add_argument(
        "--auto-scheduler-envelope",
        type=Path,
        default=None,
        help="Path to Selin Tag-64+Tag-66 auto-scheduler-stage envelope JSON.",
    )
    p.add_argument(
        "--iso-week",
        type=int,
        default=None,
        help="Optional ISO calendar week (1..53) for envelope correlation.",
    )
    p.add_argument(
        "--github-run-id",
        type=str,
        default=None,
        help="Optional GitHub Actions run-id to surface verbatim.",
    )
    p.add_argument(
        "--github-sha",
        type=str,
        default=None,
        help="Optional GitHub Actions SHA to surface verbatim.",
    )
    p.add_argument(
        "--github-ref",
        type=str,
        default=None,
        help="Optional GitHub Actions ref to surface verbatim.",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the verdict-envelope JSON.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    envelopes: dict[str, dict[str, Any] | None] = {
        "welle_1_producer": _load_envelope(args.producer_envelope),
        "welle_1_audit_anchor": _load_envelope(args.audit_anchor_envelope),
        "live_smoke_stability_window": _load_envelope(
            args.live_smoke_envelope
        ),
        "auto_scheduler": _load_envelope(args.auto_scheduler_envelope),
    }
    envelope = build_envelope(
        envelopes,
        iso_week=args.iso_week,
        github_run_id=args.github_run_id,
        github_sha=args.github_sha,
        github_ref=args.github_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
