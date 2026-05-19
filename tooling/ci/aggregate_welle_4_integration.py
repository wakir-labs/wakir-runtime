#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-72 Welle-4 Integration-Smoke verdict aggregator (Amara).

The Tag-72 Welle-4 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the four Welle-4 substrates that fire in
sequence on the canonical KW-26 Mi 2026-06-24 cutover-Mittwoch /
KW-26 Fr 2026-06-26 sign-off-Freitag Doppel-Welle-4+5 cutover
window (per ``docs/quality-gates/phase-3-marathon-final-
acceptance.md`` Marathon-Cadence row KW-26 and
``docs/quality-gates/pre-cutover-acceptance-run-order.md``).

The four substrates aggregated here:

* ``S1`` welle_4_producer
    Selin Tag-72 Welle-4 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-4.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status + welle-number=4
    invariants.

* ``S2`` welle_4_audit_anchor
    Tomas Tag-72 Welle-4 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-4 sign-off bundle
    on disk, computes a deterministic SHA-256 anchor across the
    bundle keys, and emits a producer-facing envelope. The
    simulation verifies the envelope's ``audit_trail_anchor``
    field is a 64-hex SHA-256 hash and the bundle-keys match
    the producer's rollup-links.

* ``S3`` snapshot_restore_gate
    Welle-4-specific Snapshot-Restore-Pflicht-Verifikation (Tomas
    Tag-56 Phase-3-Marathon-Rollback-Runbook §J5: "W4 state_backing
    rust->python + snapshot-restore-planned"; ``docs/ci/phase-3-
    marathon-rollback-runbook.md`` rows 39-41, 72, 113). Welle-4
    is the State-Backing welle; its rollback path REQUIRES a
    snapshot-restore plan because rolling back the state-backing
    backend without a restored snapshot leaves the agent-state
    inconsistent across the flip. The hermetic stage probes the
    READY / PLANNED-MISSING / PLAN-DEFECT trinary surface and
    asserts the per-Welle status mapping
    (``Welle-4 without --with-snapshot-restore=true`` -> yellow
    per the rollback-runbook row 113).

* ``S4`` downstream_block_cascade
    AP-9-analogue Anti-Pattern downstream-block cascade
    simulation. When Welle-4 fires DEFECT (state-backing
    rollback), the downstream Wellen 5/6/7 (lifecycle_state_
    machine, subscribe_loop, recovery_workflow) must be blocked
    by the forward-cascade-rule because they rest on the Welle-4
    state-backing backend invariants. The hermetic stage probes
    the cascade-rule under three scenarios (Welle-4-INTACT -> no
    block; Welle-4-DRIFT -> warning, no block; Welle-4-DEFECT ->
    welle-4,5,6,7 blocked).

* ``S5`` aggregate
    Final trinary aggregator (this module). Folds the four stage
    verdicts into a single WELLE-4-INTACT / DRIFT / DEFECT signal.

Aggregated verdict
------------------

The Tag-72 aggregator emits a single trinary verdict for the
Welle-4 State-Backing pipeline:

* ``WELLE-4-INTACT`` -- all four stage verdicts green.
  The Welle-4 cutover pipeline simulation is end-to-end clean;
  the actual Welle-4 trigger on 2026-06-24 has hermetic-evidence
  of substrate contract-stability and snapshot-restore-pflicht
  discipline.
* ``WELLE-4-DRIFT`` -- at least one stage yellow, zero red.
  The pipeline simulates with degraded signal on at least one
  substrate but no defect; operator-hand reads the per-stage
  notes before the live Welle-4 trigger (e.g.
  snapshot-restore PLANNED-MISSING is a yellow flag operator
  must address before cutover).
* ``WELLE-4-DEFECT`` -- at least one stage red, or any stage
  envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break OR a snapshot-restore
  PLAN-DEFECT OR a cascade-rule break; the cutover-runbook
  pauses on the failing substrate before the live Welle-4
  trigger, and the AP-9-analogue downstream-cascade is
  consulted to determine the blocked-wellen surface (4,5,6,7).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle-4
dispatch. The aggregator is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-72 plan. The
four input envelopes are read from disk paths supplied by the
caller; the aggregator does not attempt to fetch them via gh CLI
or GitHub API (that is the workflow's job).

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-72 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual Welle-4 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual Welle-4
trigger is operator-hand on 2026-06-24.

Brief-vs-canonical reconciliation (Tag-71 lehre)
-----------------------------------------------

The Tag-72 Auftrag brief carried two non-canonical values that
this aggregator corrects against the repo doku-tree (per
``feedback_high_tempo_spawn_collision.md`` and the Tag-71
brief-werte-verifikation discipline):

* Brief said "Welle-4 KW-25 Mo". Canonical per
  ``docs/quality-gates/phase-3-marathon-final-acceptance.md``
  row KW-26 and ``docs/quality-gates/pre-cutover-acceptance-
  run-order.md`` row Welle-4 is **KW-26 Mi 2026-06-24
  cutover-Mittwoch / KW-26 Fr 2026-06-26 sign-off-Freitag**
  (Doppel-Welle-4+5 parallel with Welle-5).
* Brief said "Tomas-Tag-56 Rollback-Workflow §J4". Canonical
  per ``docs/ci/phase-3-marathon-rollback-runbook.md`` Job-Graph
  is **§J5 W4 state_backing rust->python + snapshot-restore-
  planned**. §J4 is W5 lifecycle_state_machine.

Both corrections are surfaced verbatim on the envelope under
``brief_vs_canonical_reconciliation`` for the audit trail.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-4 substrate envelopes for the Tag-72
Welle-4 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the Tomas Tag-56 rollback-runbook (Zone-K), or the
forward-cascade-rule helpers (Selin-domain). All four substrate
envelopes are consumed read-only.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from the
  Welle-4 state-file producer.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  the Welle-4 audit-trail-anchor wire-helper.
* Zone-M: QA x Tomas -- snapshot-restore-gate-stage S3 inherits
  from the Tag-56 rollback-runbook §J5 Welle-4 snapshot-restore-
  planned mapping. Drift in the READY/PLANNED-MISSING/PLAN-DEFECT
  trinary is a Zone-M signal.
* Zone-M: QA x Selin -- downstream-cascade-stage S4 inherits
  from the forward-cascade-rule analogue of AP-9 for Welle-4
  (``blocked_wellen=(4,5,6,7)`` on DEFECT). Drift in the
  cascade-mapping is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-4 envelope,
  per-stage envelopes, and the workflow-emitted notify-stream
  are Audit-Evidence-Inputs.
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

# Canonical chronological order of the Welle-4 pipeline:
#   producer -> audit-anchor -> snapshot-restore-gate -> downstream-cascade.
# This is the order in which the four substrate-checks fire on the
# actual 2026-06-24 Welle-4-Cutover-Day pipeline. The aggregator
# preserves this order in step_results / failed_steps / per_note
# so the marathon-dashboard correlation is one-to-one with the
# operator-runbook section ordering.
STAGES: tuple[str, ...] = (
    "welle_4_producer",
    "welle_4_audit_anchor",
    "snapshot_restore_gate",
    "downstream_block_cascade",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-72 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.

WELLE_4_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-4-PRODUCER-READY": "green",
    "WELLE-4-PRODUCER-DRIFT": "yellow",
    "WELLE-4-PRODUCER-DEFECT": "red",
}

WELLE_4_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-4-AUDIT-ANCHOR-READY": "green",
    "WELLE-4-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-4-AUDIT-ANCHOR-DEFECT": "red",
}

SNAPSHOT_RESTORE_GATE_VERDICT_MAP: dict[str, str] = {
    # Tag-56 §J5 Welle-4 snapshot-restore-pflicht trinary surface:
    # READY = green (snapshot-restore plan present + verifiable);
    # PLANNED-MISSING = yellow (per rollback-runbook row 113:
    # "Welle-4 without --with-snapshot-restore=true" -> yellow);
    # PLAN-DEFECT = red (plan present but schema-invalid or
    # claims non-Welle-4 binding).
    "SNAPSHOT-RESTORE-READY": "green",
    "SNAPSHOT-RESTORE-PLANNED-MISSING": "yellow",
    "SNAPSHOT-RESTORE-PLAN-DEFECT": "red",
}

DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP: dict[str, str] = {
    # The cascade-stage emits CASCADE-CONSISTENT when the forward-
    # cascade rule fires correctly under all three probe scenarios
    # (welle-4-INTACT / DRIFT / DEFECT); CASCADE-DRIFT when one
    # probe surface has soft mismatch; CASCADE-BREAK when the
    # cascade-mapping diverges from blocked_wellen=(4,5,6,7) on
    # DEFECT.
    "CASCADE-CONSISTENT": "green",
    "CASCADE-DRIFT": "yellow",
    "CASCADE-BREAK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_4_producer": WELLE_4_PRODUCER_VERDICT_MAP,
    "welle_4_audit_anchor": WELLE_4_AUDIT_ANCHOR_VERDICT_MAP,
    "snapshot_restore_gate": SNAPSHOT_RESTORE_GATE_VERDICT_MAP,
    "downstream_block_cascade": DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "WELLE-4-INTACT"
VERDICT_DRIFT: str = "WELLE-4-DRIFT"
VERDICT_DEFECT: str = "WELLE-4-DEFECT"


# ---- Welle-4 anchor constants --------------------------------------------

# Welle-4 (State-Backing, Doppel-Welle-4+5 parallel) is anchored on
# 2026-06-24 (KW-26 Mi) cutover / 2026-06-26 (KW-26 Fr) sign-off per
# `docs/quality-gates/phase-3-marathon-final-acceptance.md` row
# KW-26 and `docs/quality-gates/pre-cutover-acceptance-run-order.md`
# row Welle-4. The aggregator surfaces this on the envelope for
# the marathon-dashboard correlation; it does NOT enforce the date
# itself (the workflow trigger surface owns the trigger window).
WELLE_4_ISO_CUTOVER_DATE: str = "2026-06-24"
WELLE_4_ISO_SIGNOFF_DATE: str = "2026-06-26"
WELLE_4_ISO_WEEK: int = 26
WELLE_4_WELLE_NUMBER: int = 4
WELLE_4_MODUL: str = "state_backing"


# ---- Forward-cascade constants -------------------------------------------

# Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` AP-9
# (rollback-cascade analogue for Welle-4) and `docs/ci/phase-3-
# marathon-rollback-runbook.md` reverse-cutover order: a Welle-4
# DEFECT (state-backing rollback) blocks downstream Wellen 4/5/6/7
# (Welle-4 itself + Welle-5 lifecycle_state_machine which is the
# Doppel-Welle-4+5 partner, Welle-6 subscribe_loop, Welle-7
# recovery_workflow). Welle-1/2/3 are upstream of Welle-4 and are
# NOT in the forward-cascade-set.
FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT: tuple[int, ...] = (4, 5, 6, 7)


# ---- Substrate provenance ------------------------------------------------

# Cross-anchor records for the four Welle-4 substrates the Tag-72
# integration-smoke aggregates. Surfaced on the envelope for the
# Henrik (Zone-N) audit-evidence trail.
SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_4_producer": {
        "owner": "Selin",
        "tag": "tag-72",
        "pr": None,
        "kind": "persona-engine-welle-4-state-file-producer",
    },
    "welle_4_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-72",
        "pr": None,
        "kind": "ots-welle-4-audit-trail-anchor-integration",
    },
    "snapshot_restore_gate": {
        "owner": "Tomas",
        "tag": "tag-56+tag-72",
        "pr": None,
        "kind": "rollback-runbook-welle-4-snapshot-restore-pflicht-j5",
    },
    "downstream_block_cascade": {
        "owner": "Selin",
        "tag": "ap-9-analogue",
        "pr": None,
        "kind": "persona-engine-welle-4-forward-block-cascade-rule",
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

# Tag-71 lehre: the Tag-72 Auftrag brief carried two non-canonical
# values that the aggregator surfaces verbatim on the envelope for
# the audit trail (per `feedback_high_tempo_spawn_collision.md`
# and brief-werte-verifikation discipline).
BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "welle_4_date": {
        "brief_value": "KW-25 Mo",
        "canonical_value": "KW-26 Mi 2026-06-24 cutover / KW-26 Fr 2026-06-26 sign-off",
        "canonical_source": (
            "docs/quality-gates/phase-3-marathon-final-acceptance.md "
            "row KW-26 + docs/quality-gates/pre-cutover-acceptance-run-order.md"
        ),
        "resolution": "canonical wins (Doppel-Welle-4+5 parallel)",
    },
    "rollback_workflow_job": {
        "brief_value": "Tomas-Tag-56 Rollback-Workflow J4",
        "canonical_value": "J5 W4 state_backing rust->python + snapshot-restore-planned",
        "canonical_source": (
            "docs/ci/phase-3-marathon-rollback-runbook.md Job-Graph "
            "(J4 is W5 lifecycle_state_machine; J5 is W4 state_backing)"
        ),
        "resolution": "canonical wins (J5 is Welle-4)",
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
        return "red", f"{stage}: unknown stage key"
    status = verdict_map.get(raw_verdict)
    if status is None:
        return "red", f"{stage}: unknown verdict '{raw_verdict}'"
    if status == "green":
        return status, ""
    return status, f"{stage}: verdict='{raw_verdict}'"


def decide(steps: Mapping[str, str]) -> str:
    """Apply the Tag-72 decision rule.

    Trinary mirroring the Tag-71 Welle-3 pattern: any red collapses
    to DEFECT; any yellow degrades to DRIFT; all green yields INTACT.
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
    return VERDICT_DEFECT


def downstream_blocked_wellen(verdict: str) -> tuple[int, ...]:
    """Apply forward-cascade-rule to the aggregated Welle-4 verdict.

    Per `docs/quality-gates/phase-3-marathon-anti-patterns.md`
    AP-9-analogue forward-cascade for Welle-4 (state-backing
    rollback) and `docs/ci/phase-3-marathon-rollback-runbook.md`
    reverse-cutover-order J5 (W4 state_backing rust->python +
    snapshot-restore-planned), a Welle-4 DEFECT (rollback) blocks
    forward Wellen (4,5,6,7). A DRIFT yields no block but surfaces
    a warning; INTACT yields no block.
    """
    if verdict == VERDICT_DEFECT:
        return FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
    return ()


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated Tag-72 Welle-4-Integration verdict envelope."""
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
        "workflow": "welle-4-integration-smoke",
        "tag": "tag-72",
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
        "welle_4_anchor": {
            "iso_cutover_date": WELLE_4_ISO_CUTOVER_DATE,
            "iso_signoff_date": WELLE_4_ISO_SIGNOFF_DATE,
            "iso_week": WELLE_4_ISO_WEEK,
            "welle_number": WELLE_4_WELLE_NUMBER,
            "modul": WELLE_4_MODUL,
            "doppel_welle_partner": 5,
        },
        "window": {
            "iso_week": iso_week,
            "welle_4_iso_week": WELLE_4_ISO_WEEK,
            "in_welle_4_week": (
                iso_week == WELLE_4_ISO_WEEK if iso_week else False
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
        "snapshot_restore_pflicht": {
            "anchor": (
                "docs/ci/phase-3-marathon-rollback-runbook.md "
                "J5 (W4 state_backing rust->python + "
                "snapshot-restore-planned)"
            ),
            "rule_row_113": (
                "Welle-4 without --with-snapshot-restore=true -> yellow"
            ),
            "welle_4_required": True,
        },
        "downstream_cascade": {
            "rule": (
                "AP-9-analogue forward-cascade for Welle-4 state_backing "
                "rollback (phase-3-marathon-anti-patterns.md + "
                "phase-3-marathon-rollback-runbook.md)"
            ),
            "blocked_wellen_on_defect": list(
                FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
            ),
            "blocked_wellen_now": list(blocked),
            "cascade_armed": verdict == VERDICT_DEFECT,
        },
        "decision_rule": {
            "intact": (
                "all four stage verdicts green "
                "(welle_4_producer + welle_4_audit_anchor + "
                "snapshot_restore_gate + downstream_block_cascade)"
            ),
            "drift": "at least one yellow, zero red",
            "defect": (
                "at least one red, OR any envelope missing, "
                "OR snapshot-restore PLAN-DEFECT, OR cascade-rule break"
            ),
        },
        "brief_vs_canonical_reconciliation": BRIEF_VS_CANONICAL_RECONCILIATION,
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_4_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_welle_4_integration",
        description=(
            "Aggregate the four Welle-4 substrate verdict envelopes "
            "(welle-4-producer, welle-4-audit-anchor, snapshot-"
            "restore-gate, downstream-block-cascade) into a single "
            "Tag-72 WELLE-4-INTEGRATION verdict for the 2026-06-24 "
            "Welle-4 State-Backing Doppel-Welle-4+5 Cutover-Mittwoch "
            "pipeline simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Welle-4 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-4 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--snapshot-restore-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-4 snapshot-restore-gate verdict envelope JSON.",
    )
    p.add_argument(
        "--cascade-envelope",
        type=Path,
        default=None,
        help="Path to Welle-4 forward-cascade verdict envelope JSON.",
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
        "welle_4_producer": _load_envelope(args.producer_envelope),
        "welle_4_audit_anchor": _load_envelope(args.audit_anchor_envelope),
        "snapshot_restore_gate": _load_envelope(args.snapshot_restore_envelope),
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
