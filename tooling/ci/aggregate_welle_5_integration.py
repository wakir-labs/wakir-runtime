#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-73 Welle-5 Integration-Smoke verdict aggregator (Amara).

The Tag-73 Welle-5 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the four Welle-5 substrates that fire in
sequence on the canonical KW-26 Mi 2026-06-24 cutover-Mittwoch /
KW-26 Fr 2026-06-26 sign-off-Freitag Doppel-Welle-4+5 cutover
window (per ``docs/quality-gates/phase-3-marathon-final-
acceptance.md`` Marathon-Cadence row KW-26 +
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` row
Welle-5 + ``docs/ci/phase-3-marathon-rollback-runbook.md``
Job-Graph J4).

The four substrates aggregated here:

* ``S1`` welle_5_producer
    Selin Tag-73 Welle-5 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-5.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status + welle-number=5
    invariants.

* ``S2`` welle_5_audit_anchor
    Tomas Tag-73 Welle-5 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-5 sign-off bundle
    on disk, computes a deterministic SHA-256 anchor across the
    bundle keys, and emits a producer-facing envelope. The
    simulation verifies the envelope's ``audit_trail_anchor``
    field is a 64-hex SHA-256 hash and the bundle-keys match
    the producer's rollup-links.

* ``S3`` doppel_welle_coupling_gate
    Tag-73 Doppel-Welle-4+5 Coupling-Gate (Amara, distinctive
    Welle-5 substrate). Welle-5 (lifecycle_state_machine) does
    NOT have a snapshot-restore dependency (that was Welle-4-
    specific per Tag-56 J5). Instead, Welle-5's distinctive
    substrate-coupling is to Welle-4 state_backing: lifecycle_
    state_machine rests on state_backing invariants. A Welle-4
    state_backing DEFECT MUST block Welle-5 lifecycle_state_
    machine from flipping (per ``docs/quality-gates/pre-cutover-
    acceptance-run-order.md`` row Welle-5 "Doppel-Welle-4+5
    parallel" + AP-9-analogue forward-cascade discipline). The
    hermetic stage probes the READY / PARTNER-MISSING / PARTNER-
    DEFECT trinary surface of the coupling-gate.

* ``S4`` downstream_block_cascade
    AP-9-analogue Anti-Pattern downstream-block cascade
    simulation. When Welle-5 fires DEFECT (lifecycle_state_machine
    rollback), the downstream Wellen 6/7 (subscribe_loop, recovery_
    workflow) must be blocked by the forward-cascade-rule because
    they rest on the Welle-5 lifecycle_state_machine invariants.
    Welle-5 itself is also in the blocked-set (rollback of Welle-5
    cancels the Welle-5 cutover). The hermetic stage probes the
    cascade-rule under three scenarios (Welle-5-INTACT -> no
    block; Welle-5-DRIFT -> warning, no block; Welle-5-DEFECT ->
    welle-5,6,7 blocked).

    Note: Welle-4 is NOT in the forward-cascade-set for Welle-5
    (Welle-4 is upstream of Welle-5 in the cutover order, even
    though Welle-4+5 fire in parallel as Doppel-Welle). The
    coupling-direction is one-way: Welle-5 depends on Welle-4
    state_backing (Stage 3), not vice versa.

* ``S5`` aggregate
    Final trinary aggregator (this module). Folds the four stage
    verdicts into a single WELLE-5-INTACT / DRIFT / DEFECT signal.

Aggregated verdict
------------------

The Tag-73 aggregator emits a single trinary verdict for the
Welle-5 lifecycle_state_machine pipeline:

* ``WELLE-5-INTACT`` -- all four stage verdicts green.
  The Welle-5 cutover pipeline simulation is end-to-end clean;
  the actual Welle-5 trigger on 2026-06-24 has hermetic-evidence
  of substrate contract-stability and Doppel-Welle-coupling
  discipline.
* ``WELLE-5-DRIFT`` -- at least one stage yellow, zero red.
  The pipeline simulates with degraded signal on at least one
  substrate but no defect; operator-hand reads the per-stage
  notes before the live Welle-5 trigger (e.g. doppel-coupling
  PARTNER-MISSING is a yellow flag operator must address before
  cutover).
* ``WELLE-5-DEFECT`` -- at least one stage red, or any stage
  envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break OR a doppel-coupling
  PARTNER-DEFECT OR a cascade-rule break; the cutover-runbook
  pauses on the failing substrate before the live Welle-5
  trigger, and the AP-9-analogue downstream-cascade is
  consulted to determine the blocked-wellen surface (5,6,7).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle-5
dispatch. The aggregator is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-73 plan. The
four input envelopes are read from disk paths supplied by the
caller; the aggregator does not attempt to fetch them via gh CLI
or GitHub API (that is the workflow's job).

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-73 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual Welle-5 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual Welle-5
trigger is operator-hand on 2026-06-24.

Brief-vs-canonical reconciliation (Tag-71+72 lehre)
---------------------------------------------------

The Tag-73 Auftrag brief carried three non-canonical values that
this aggregator corrects against the repo doku-tree (per
``feedback_high_tempo_spawn_collision.md`` and the brief-werte-
verifikation discipline):

* Brief said "Welle-5 Capability-Token (Reza, Zone-L)".
  Canonical per ``docs/ci/phase-3-marathon-rollback-runbook.md``
  Job-Graph is **J4 W5 lifecycle_state_machine rust->python**.
  The Capability-Token framing is a parallel KW-24-Acceptance-
  view per ``docs/quality-gates/kw-24-welle-1-7-acceptance-
  criteria.md`` §5 (Welle-5 = capability-token enforce-mode).
  Tag-72 already pinned the Marathon-Rollback-Runbook view as
  canonical for Welle-4 (state_backing); Tag-73 follows the same
  precedent and surfaces the Capability-Token view as parallel-
  substrate-evidence on the envelope.
* Brief implied ``state/welle-5.json`` is canonical. In fact
  ``state/welle-5.json`` carries ``kw_cutover_anchor: "KW-25"``
  which conflicts with ``pre-cutover-acceptance-run-order.md``
  row Welle-5 (KW-26 Doppel-Welle-4+5). The state-file drift
  is surfaced as a pin-drift marker on the envelope; the state-
  file is NOT modified by this smoke (Amara scope: surface, not
  patch; ADR-0036 producer-domain is Selin).
* Brief framing "Doppel-Welle-4+5 parallel" matches canonical.
  This is consistent with Tag-72's Welle-4 framing and is
  surfaced verbatim on the envelope.

All three corrections are surfaced verbatim on the envelope under
``brief_vs_canonical_reconciliation`` for the audit trail.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-5 substrate envelopes for the Tag-73
Welle-5 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the rollback-runbook (Zone-K), or the forward-cascade-
rule helpers (Selin-domain). All four substrate envelopes are
consumed read-only. The state/welle-5.json kw-anchor drift is
surfaced but NOT patched (Selin-domain).

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from the
  Welle-5 state-file producer.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  the Welle-5 audit-trail-anchor wire-helper.
* Zone-M: QA x Selin+Tomas -- doppel-coupling-gate-stage S3
  inherits from the Welle-4 state_backing substrate readiness
  signal. Drift in the READY/PARTNER-MISSING/PARTNER-DEFECT
  trinary is a Zone-M signal.
* Zone-M: QA x Selin -- downstream-cascade-stage S4 inherits
  from the forward-cascade-rule analogue of AP-9 for Welle-5
  (``blocked_wellen=(5,6,7)`` on DEFECT). Drift in the
  cascade-mapping is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-5 envelope,
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

# Canonical chronological order of the Welle-5 pipeline:
#   producer -> audit-anchor -> doppel-coupling-gate -> downstream-cascade.
# This is the order in which the four substrate-checks fire on the
# actual 2026-06-24 Welle-5-Cutover-Day pipeline. The aggregator
# preserves this order in step_results / failed_steps / per_note
# so the marathon-dashboard correlation is one-to-one with the
# operator-runbook section ordering.
STAGES: tuple[str, ...] = (
    "welle_5_producer",
    "welle_5_audit_anchor",
    "doppel_welle_coupling_gate",
    "downstream_block_cascade",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-73 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.

WELLE_5_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-5-PRODUCER-READY": "green",
    "WELLE-5-PRODUCER-DRIFT": "yellow",
    "WELLE-5-PRODUCER-DEFECT": "red",
}

WELLE_5_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-5-AUDIT-ANCHOR-READY": "green",
    "WELLE-5-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-5-AUDIT-ANCHOR-DEFECT": "red",
}

DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP: dict[str, str] = {
    # Tag-73 Doppel-Welle-4+5 coupling-gate trinary surface:
    # READY = green (Welle-4 partner state_backing INTACT,
    # lifecycle_state_machine flip safe);
    # PARTNER-MISSING = yellow (Welle-4 partner state not
    # observable; operator-hand verification required before
    # Welle-5 flip);
    # PARTNER-DEFECT = red (Welle-4 partner state_backing DEFECT,
    # lifecycle_state_machine flip MUST NOT proceed).
    "DOPPEL-COUPLING-READY": "green",
    "DOPPEL-COUPLING-PARTNER-MISSING": "yellow",
    "DOPPEL-COUPLING-PARTNER-DEFECT": "red",
}

DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP: dict[str, str] = {
    # The cascade-stage emits CASCADE-CONSISTENT when the forward-
    # cascade rule fires correctly under all three probe scenarios
    # (welle-5-INTACT / DRIFT / DEFECT); CASCADE-DRIFT when one
    # probe surface has soft mismatch; CASCADE-BREAK when the
    # cascade-mapping diverges from blocked_wellen=(5,6,7) on
    # DEFECT.
    "CASCADE-CONSISTENT": "green",
    "CASCADE-DRIFT": "yellow",
    "CASCADE-BREAK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_5_producer": WELLE_5_PRODUCER_VERDICT_MAP,
    "welle_5_audit_anchor": WELLE_5_AUDIT_ANCHOR_VERDICT_MAP,
    "doppel_welle_coupling_gate": DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP,
    "downstream_block_cascade": DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "WELLE-5-INTACT"
VERDICT_DRIFT: str = "WELLE-5-DRIFT"
VERDICT_DEFECT: str = "WELLE-5-DEFECT"


# ---- Welle-5 anchor constants --------------------------------------------

# Welle-5 (lifecycle_state_machine, Doppel-Welle-4+5 parallel) is
# anchored on 2026-06-24 (KW-26 Mi) cutover / 2026-06-26 (KW-26 Fr)
# sign-off per `docs/quality-gates/phase-3-marathon-final-
# acceptance.md` row KW-26 and `docs/quality-gates/pre-cutover-
# acceptance-run-order.md` row Welle-5. The aggregator surfaces
# this on the envelope for the marathon-dashboard correlation; it
# does NOT enforce the date itself (the workflow trigger surface
# owns the trigger window).
WELLE_5_ISO_CUTOVER_DATE: str = "2026-06-24"
WELLE_5_ISO_SIGNOFF_DATE: str = "2026-06-26"
WELLE_5_ISO_WEEK: int = 26
WELLE_5_WELLE_NUMBER: int = 5
WELLE_5_MODUL_MARATHON: str = "lifecycle_state_machine"
WELLE_5_MODUL_ACCEPTANCE_VIEW: str = "capability_token"
WELLE_5_ROLLBACK_JOB: str = "J4"
WELLE_5_DOPPEL_WELLE_PARTNER: int = 4


# ---- Forward-cascade constants -------------------------------------------

# Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` AP-9
# (rollback-cascade analogue for Welle-5) and `docs/ci/phase-3-
# marathon-rollback-runbook.md` reverse-cutover order: a Welle-5
# DEFECT (lifecycle_state_machine rollback) blocks downstream
# Wellen 5/6/7 (Welle-5 itself + Welle-6 subscribe_loop, Welle-7
# recovery_workflow). Welle-1/2/3/4 are upstream of Welle-5 and
# are NOT in the forward-cascade-set. Note: Welle-4 (Doppel-Welle
# partner) is upstream in the cutover order even though both fire
# in parallel; the coupling-direction is one-way (Welle-5 depends
# on Welle-4 state_backing, not vice versa).
FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT: tuple[int, ...] = (5, 6, 7)


# ---- Substrate provenance ------------------------------------------------

# Cross-anchor records for the four Welle-5 substrates the Tag-73
# integration-smoke aggregates. Surfaced on the envelope for the
# Henrik (Zone-N) audit-evidence trail.
SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_5_producer": {
        "owner": "Selin",
        "tag": "tag-73",
        "pr": None,
        "kind": "persona-engine-welle-5-state-file-producer",
    },
    "welle_5_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-73",
        "pr": None,
        "kind": "ots-welle-5-audit-trail-anchor-integration",
    },
    "doppel_welle_coupling_gate": {
        "owner": "Amara",
        "tag": "tag-73",
        "pr": None,
        "kind": "doppel-welle-4-5-coupling-gate-lifecycle-state-machine",
    },
    "downstream_block_cascade": {
        "owner": "Selin",
        "tag": "ap-9-analogue",
        "pr": None,
        "kind": "persona-engine-welle-5-forward-block-cascade-rule",
    },
}


# ---- Parallel substrate views (Welle-5 has two doc-tree framings) --------

# The two canonical doc-tree views of Welle-5. Tag-73 pins the
# Marathon-Rollback-Runbook view as canonical (consistent with
# Tag-72 Welle-4 precedent) and surfaces the KW-24-Acceptance view
# as parallel-substrate-evidence for the audit trail.
PARALLEL_SUBSTRATE_VIEWS: dict[str, dict[str, Any]] = {
    "marathon_rollback_runbook_view": {
        "doc": "docs/ci/phase-3-marathon-rollback-runbook.md",
        "anchor": "J4 W5 lifecycle_state_machine rust->python",
        "modul": "lifecycle_state_machine",
        "is_canonical_for_tag_73": True,
    },
    "kw_24_acceptance_view": {
        "doc": "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md",
        "anchor": "§5 Welle-5 KW-25 Fr Capability-Token (Reza, Zone-L)",
        "modul": "capability_token",
        "is_canonical_for_tag_73": False,
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

# Tag-71+72 lehre: the Tag-73 Auftrag brief carried three non-
# canonical values that the aggregator surfaces verbatim on the
# envelope for the audit trail (per `feedback_high_tempo_spawn_
# collision.md` and brief-werte-verifikation discipline).
BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "welle_5_modul": {
        "brief_value": "Capability-Token (Reza, Zone-L)",
        "canonical_value": (
            "J4 W5 lifecycle_state_machine rust->python "
            "(Marathon-Rollback-Runbook view); capability_token "
            "is parallel KW-24-Acceptance view per "
            "kw-24-welle-1-7-acceptance-criteria.md §5"
        ),
        "canonical_source": (
            "docs/ci/phase-3-marathon-rollback-runbook.md Job-Graph "
            "(J4 W5 lifecycle_state_machine; Tag-72 Welle-4 J5 "
            "state_backing precedent)"
        ),
        "resolution": (
            "Marathon-Rollback-Runbook wins for Tag-73 canonical; "
            "KW-24-Acceptance view surfaced as parallel-substrate-evidence"
        ),
    },
    "welle_5_state_file_kw_anchor": {
        "brief_value": "state/welle-5.json kw_cutover_anchor=KW-25 (implied canonical)",
        "canonical_value": "KW-26 Mi 2026-06-24 cutover / KW-26 Fr 2026-06-26 sign-off",
        "canonical_source": (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "row Welle-5 (Doppel-Welle-4+5 parallel)"
        ),
        "resolution": (
            "canonical wins (state-file pin-drift surfaced; "
            "state-file NOT patched per Amara scope discipline, "
            "ADR-0036 producer-domain is Selin)"
        ),
    },
    "doppel_welle_4_5_framing": {
        "brief_value": "Doppel-Welle-4+5 parallel, Capability-Token",
        "canonical_value": (
            "Doppel-Welle-4+5 parallel KW-26 Mi 2026-06-24 "
            "lifecycle_state_machine (Marathon) / capability_token "
            "(KW-24-Acceptance)"
        ),
        "canonical_source": (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "row Welle-5 + Tag-72 Welle-4 precedent"
        ),
        "resolution": "Doppel-Welle framing canonical; modul-framing reconciled above",
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
    """Apply the Tag-73 decision rule.

    Trinary mirroring the Tag-71/Tag-72 Welle-3/Welle-4 pattern: any
    red collapses to DEFECT; any yellow degrades to DRIFT; all green
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
    return VERDICT_DEFECT


def downstream_blocked_wellen(verdict: str) -> tuple[int, ...]:
    """Apply forward-cascade-rule to the aggregated Welle-5 verdict.

    Per `docs/quality-gates/phase-3-marathon-anti-patterns.md`
    AP-9-analogue forward-cascade for Welle-5 (lifecycle_state_
    machine rollback) and `docs/ci/phase-3-marathon-rollback-
    runbook.md` reverse-cutover-order J4, a Welle-5 DEFECT
    (rollback) blocks forward Wellen (5,6,7). A DRIFT yields no
    block but surfaces a warning; INTACT yields no block.

    Note: Welle-4 is NOT in the cascade-set even though it is the
    Doppel-Welle partner. The coupling-direction is one-way
    (Welle-5 depends on Welle-4 state_backing, not vice versa).
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
    """Build the aggregated Tag-73 Welle-5-Integration verdict envelope."""
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
        "workflow": "welle-5-integration-smoke",
        "tag": "tag-73",
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
        "welle_5_anchor": {
            "iso_cutover_date": WELLE_5_ISO_CUTOVER_DATE,
            "iso_signoff_date": WELLE_5_ISO_SIGNOFF_DATE,
            "iso_week": WELLE_5_ISO_WEEK,
            "welle_number": WELLE_5_WELLE_NUMBER,
            "modul": WELLE_5_MODUL_MARATHON,
            "modul_acceptance_view": WELLE_5_MODUL_ACCEPTANCE_VIEW,
            "rollback_job": WELLE_5_ROLLBACK_JOB,
            "doppel_welle_partner": WELLE_5_DOPPEL_WELLE_PARTNER,
        },
        "window": {
            "iso_week": iso_week,
            "welle_5_iso_week": WELLE_5_ISO_WEEK,
            "in_welle_5_week": (
                iso_week == WELLE_5_ISO_WEEK if iso_week else False
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
        "parallel_substrate_views": PARALLEL_SUBSTRATE_VIEWS,
        "doppel_welle_coupling": {
            "partner_welle": WELLE_5_DOPPEL_WELLE_PARTNER,
            "anchor": (
                "docs/quality-gates/pre-cutover-acceptance-run-order.md "
                "row Welle-5 (Doppel-Welle-4+5 parallel)"
            ),
            "coupling_direction": (
                "one-way: Welle-5 lifecycle_state_machine depends on "
                "Welle-4 state_backing; Welle-4 does NOT depend on Welle-5"
            ),
            "partner_defect_blocks_welle_5": True,
        },
        "downstream_cascade": {
            "rule": (
                "AP-9-analogue forward-cascade for Welle-5 "
                "lifecycle_state_machine rollback (phase-3-marathon-"
                "anti-patterns.md + phase-3-marathon-rollback-runbook.md)"
            ),
            "blocked_wellen_on_defect": list(
                FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
            ),
            "blocked_wellen_now": list(blocked),
            "cascade_armed": verdict == VERDICT_DEFECT,
            "welle_4_not_in_cascade_note": (
                "Welle-4 is upstream of Welle-5 in the cutover order "
                "even though both fire in parallel as Doppel-Welle; "
                "the coupling-direction is one-way."
            ),
        },
        "decision_rule": {
            "intact": (
                "all four stage verdicts green "
                "(welle_5_producer + welle_5_audit_anchor + "
                "doppel_welle_coupling_gate + downstream_block_cascade)"
            ),
            "drift": "at least one yellow, zero red",
            "defect": (
                "at least one red, OR any envelope missing, "
                "OR doppel-coupling PARTNER-DEFECT, OR cascade-rule break"
            ),
        },
        "brief_vs_canonical_reconciliation": BRIEF_VS_CANONICAL_RECONCILIATION,
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_5_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_welle_5_integration",
        description=(
            "Aggregate the four Welle-5 substrate verdict envelopes "
            "(welle-5-producer, welle-5-audit-anchor, doppel-welle-"
            "coupling-gate, downstream-block-cascade) into a single "
            "Tag-73 WELLE-5-INTEGRATION verdict for the 2026-06-24 "
            "Welle-5 lifecycle_state_machine Doppel-Welle-4+5 "
            "Cutover-Mittwoch pipeline simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Welle-5 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-5 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--doppel-coupling-envelope",
        type=Path,
        default=None,
        help="Path to Amara Welle-5 doppel-welle-coupling-gate verdict envelope JSON.",
    )
    p.add_argument(
        "--cascade-envelope",
        type=Path,
        default=None,
        help="Path to Welle-5 forward-cascade verdict envelope JSON.",
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
        "welle_5_producer": _load_envelope(args.producer_envelope),
        "welle_5_audit_anchor": _load_envelope(args.audit_anchor_envelope),
        "doppel_welle_coupling_gate": _load_envelope(args.doppel_coupling_envelope),
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
