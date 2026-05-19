#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-71 Welle-3 Integration-Smoke verdict aggregator (Amara).

The Tag-71 Welle-3 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the five Welle-3 substrates that fire in
sequence on the 2026-06-12 (KW-24 Fr) Welle-3 Bridge-Audit-Writer
cutover day:

* ``S1`` welle_3_producer
    Selin Tag-71 Welle-3 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-3.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status invariants.

* ``S2`` welle_3_audit_anchor
    Tomas Tag-71 Welle-3 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-3 sign-off bundle
    on disk, computes a deterministic SHA-256 anchor across the
    bundle keys, and emits a producer-facing envelope. The
    simulation verifies the envelope's ``audit_trail_anchor``
    field is a 64-hex SHA-256 hash and the bundle-keys match
    the producer's rollup-links.

* ``S3`` pre_auditor_gate
    §11-Disziplin pre-auditor decision-gate simulation (Henrik
    pre-auditor designation per `docs/quality-gates/pre-mortem-
    failure-mode-coverage.md`). The hermetic stage synthesises
    the pre-auditor decision envelope for Welle-3 and asserts the
    PROCEED / CAUTION / BLOCK trinary surface matches the §11
    discipline (decision pinned before the live cutover).

* ``S4`` downstream_block_cascade
    AP-9 Anti-Pattern downstream-block cascade simulation. When
    Welle-3 fires DEFECT, Welle-4/5/6/7 must be blocked by the
    cascade-rule per ``docs/quality-gates/phase-3-marathon-anti-
    patterns.md`` AP-9 (``blocked_wellen=(3,4,5,6,7)``). The
    hermetic stage probes the cascade-rule under three scenarios
    (Welle-3-INTACT -> no block; Welle-3-DRIFT -> warning;
    Welle-3-DEFECT -> 4,5,6,7 blocked).

* ``S5`` aggregate
    Final trinary aggregator (this module). Folds the four stage
    verdicts into a single WELLE-3-INTACT / DRIFT / DEFECT signal.

Aggregated verdict
------------------

The Tag-71 aggregator emits a single trinary verdict for the
Welle-3 Bridge-Audit-Writer pipeline:

* ``WELLE-3-INTACT`` -- all four stage verdicts green.
  The Welle-3 cutover pipeline simulation is end-to-end clean;
  the actual Welle-3 trigger on 2026-06-12 has hermetic-evidence
  of substrate contract-stability and §11 pre-auditor discipline.
* ``WELLE-3-DRIFT`` -- at least one stage yellow, zero red.
  The pipeline simulates with degraded signal on at least one
  substrate but no defect; operator-hand reads the per-stage
  notes before the live Welle-3 trigger.
* ``WELLE-3-DEFECT`` -- at least one stage red, or any stage
  envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break OR a §11 pre-auditor BLOCK
  decision OR a cascade-rule break; the cutover-runbook pauses
  on the failing substrate before the live Welle-3 trigger,
  and the AP-9 downstream-cascade is consulted to determine
  the blocked-wellen surface (4,5,6,7).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle-3
dispatch. The aggregator is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-71 plan §6. The
four input envelopes are read from disk paths supplied by the
caller; the aggregator does not attempt to fetch them via gh CLI
or GitHub API (that is the workflow's job).

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-71 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual Welle-3 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual Welle-3
trigger is operator-hand on 2026-06-12.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-3 substrate envelopes for the Tag-71
Welle-3 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the Henrik pre-auditor designation surface (Zone-N),
or the AP-9 cascade-rule helpers (Selin-domain). All four
substrate envelopes are consumed read-only.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from the
  Welle-3 state-file producer. Drift in the pending-status
  invariants is a Zone-M signal.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  the Welle-3 audit-trail-anchor wire-helper (Tag-71 substrate).
  Drift in the anchor-envelope schema is a Zone-M signal.
* Zone-N: QA x Henrik -- pre-auditor-gate-stage S3 inherits
  from the §11-Disziplin pre-auditor designation surface
  (Henrik pre-mortem coverage map row B3). Drift in the
  PROCEED/CAUTION/BLOCK trinary is a Zone-N signal.
* Zone-M: QA x Selin -- downstream-cascade-stage S4 inherits
  from the AP-9 anti-pattern cascade rule (``blocked_wellen=
  (3,4,5,6,7)``). Drift in the cascade-mapping is a Zone-M
  signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-3 envelope,
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

# Canonical chronological order of the Welle-3 pipeline:
#   producer -> audit-anchor -> pre-auditor-gate -> downstream-cascade.
# This is the order in which the four substrate-checks fire on the
# actual 2026-06-12 Welle-3-Cutover-Day pipeline. The aggregator
# preserves this order in step_results / failed_steps / per_note
# so the marathon-dashboard correlation is one-to-one with the
# operator-runbook section ordering.
STAGES: tuple[str, ...] = (
    "welle_3_producer",
    "welle_3_audit_anchor",
    "pre_auditor_gate",
    "downstream_block_cascade",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-71 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.

WELLE_3_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-3-PRODUCER-READY": "green",
    "WELLE-3-PRODUCER-DRIFT": "yellow",
    "WELLE-3-PRODUCER-DEFECT": "red",
}

WELLE_3_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-3-AUDIT-ANCHOR-READY": "green",
    "WELLE-3-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-3-AUDIT-ANCHOR-DEFECT": "red",
}

PRE_AUDITOR_GATE_VERDICT_MAP: dict[str, str] = {
    # §11-Disziplin trinary surface: PROCEED = green,
    # CAUTION = yellow, BLOCK = red.
    "PRE-AUDITOR-PROCEED": "green",
    "PRE-AUDITOR-CAUTION": "yellow",
    "PRE-AUDITOR-BLOCK": "red",
}

DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP: dict[str, str] = {
    # The cascade-stage emits CASCADE-CONSISTENT when the AP-9
    # rule fires correctly under all three probe scenarios
    # (welle-3-INTACT / DRIFT / DEFECT); CASCADE-DRIFT when one
    # probe surface has soft mismatch; CASCADE-BREAK when the
    # cascade-mapping diverges from blocked_wellen=(3,4,5,6,7).
    "CASCADE-CONSISTENT": "green",
    "CASCADE-DRIFT": "yellow",
    "CASCADE-BREAK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_3_producer": WELLE_3_PRODUCER_VERDICT_MAP,
    "welle_3_audit_anchor": WELLE_3_AUDIT_ANCHOR_VERDICT_MAP,
    "pre_auditor_gate": PRE_AUDITOR_GATE_VERDICT_MAP,
    "downstream_block_cascade": DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "WELLE-3-INTACT"
VERDICT_DRIFT: str = "WELLE-3-DRIFT"
VERDICT_DEFECT: str = "WELLE-3-DEFECT"


# ---- Welle-3 anchor constants --------------------------------------------

# Welle-3 (Bridge-Audit-Writer) is anchored on 2026-06-12 (KW-24 Fr)
# per `docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md`
# row 3 (Bridge-Audit, KW-24, Fr 2026-06-12, T+4d). The aggregator
# surfaces this on the envelope for the marathon-dashboard
# correlation; it does NOT enforce the date itself (the workflow
# trigger surface owns the trigger window).
WELLE_3_ISO_DATE: str = "2026-06-12"
WELLE_3_ISO_WEEK: int = 24
WELLE_3_WELLE_NUMBER: int = 3


# ---- AP-9 downstream-cascade constants -----------------------------------

# Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` AP-9
# the welle_3_rollback / DEFECT case yields
# blocked_wellen=(3,4,5,6,7). The aggregator surfaces the
# downstream blocked-wellen tuple for the audit-evidence trail.
AP_9_BLOCKED_WELLEN_ON_DEFECT: tuple[int, ...] = (3, 4, 5, 6, 7)


# ---- Substrate provenance ------------------------------------------------

# Cross-anchor records for the four Welle-3 substrates the Tag-71
# integration-smoke aggregates. Surfaced on the envelope for the
# Henrik (Zone-N) audit-evidence trail.
SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_3_producer": {
        "owner": "Selin",
        "tag": "tag-71",
        "pr": None,
        "kind": "persona-engine-welle-3-state-file-producer",
    },
    "welle_3_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-71",
        "pr": None,
        "kind": "ots-welle-3-audit-trail-anchor-integration",
    },
    "pre_auditor_gate": {
        "owner": "Henrik",
        "tag": "tag-46+tag-71",
        "pr": None,
        "kind": "audit-welle-3-pre-auditor-designation-paragraph-11",
    },
    "downstream_block_cascade": {
        "owner": "Selin",
        "tag": "ap-9",
        "pr": None,
        "kind": "persona-engine-ap-9-downstream-block-cascade-rule",
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
    """Apply the Tag-71 decision rule.

    Trinary mirroring the Tag-70 T0-integration pattern: any red
    collapses to DEFECT; any yellow degrades to DRIFT; all green
    yields INTACT.
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


def downstream_blocked_wellen(verdict: str) -> tuple[int, ...]:
    """Apply AP-9 cascade-rule to the aggregated Welle-3 verdict.

    Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` AP-9,
    a Welle-3 DEFECT (rollback) blocks downstream wellen
    (3,4,5,6,7). A DRIFT yields no block but surfaces a warning;
    INTACT yields no block.
    """
    if verdict == VERDICT_DEFECT:
        return AP_9_BLOCKED_WELLEN_ON_DEFECT
    return ()


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated Tag-71 Welle-3-Integration verdict envelope.

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
    blocked = downstream_blocked_wellen(verdict)
    return {
        "schema_version": 1,
        "workflow": "welle-3-integration-smoke",
        "tag": "tag-71",
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
        "welle_3_anchor": {
            "iso_date": WELLE_3_ISO_DATE,
            "iso_week": WELLE_3_ISO_WEEK,
            "welle_number": WELLE_3_WELLE_NUMBER,
        },
        "window": {
            "iso_week": iso_week,
            "welle_3_iso_week": WELLE_3_ISO_WEEK,
            "in_welle_3_week": (
                iso_week == WELLE_3_ISO_WEEK if iso_week else False
            ),
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
        "downstream_cascade": {
            "ap_9_rule": "AP-9 (phase-3-marathon-anti-patterns.md)",
            "blocked_wellen_on_defect": list(AP_9_BLOCKED_WELLEN_ON_DEFECT),
            "blocked_wellen_now": list(blocked),
            "cascade_armed": verdict == VERDICT_DEFECT,
        },
        "decision_rule": {
            "intact": (
                "all four stage verdicts green "
                "(welle_3_producer + welle_3_audit_anchor + "
                "pre_auditor_gate + downstream_block_cascade)"
            ),
            "drift": "at least one yellow, zero red",
            "defect": (
                "at least one red, OR any envelope missing, "
                "OR pre-auditor BLOCK, OR cascade-rule break"
            ),
        },
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_3_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_welle_3_integration",
        description=(
            "Aggregate the four Welle-3 substrate verdict envelopes "
            "(welle-3-producer, welle-3-audit-anchor, pre-auditor-"
            "gate, downstream-block-cascade) into a single Tag-71 "
            "WELLE-3-INTEGRATION verdict for the 2026-06-12 "
            "Welle-3 Bridge-Audit-Writer Cutover-Day pipeline "
            "simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Welle-3 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-3 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--pre-auditor-envelope",
        type=Path,
        default=None,
        help="Path to Henrik §11 pre-auditor-gate verdict envelope JSON.",
    )
    p.add_argument(
        "--cascade-envelope",
        type=Path,
        default=None,
        help="Path to AP-9 downstream-block-cascade verdict envelope JSON.",
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
        "welle_3_producer": _load_envelope(args.producer_envelope),
        "welle_3_audit_anchor": _load_envelope(args.audit_anchor_envelope),
        "pre_auditor_gate": _load_envelope(args.pre_auditor_envelope),
        "downstream_block_cascade": _load_envelope(args.cascade_envelope),
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
