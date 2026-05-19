#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-74 Welle-6 Integration-Smoke verdict aggregator (Amara).

The Tag-74 Welle-6 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the four Welle-6 substrates that fire in
sequence on the canonical KW-27 Mi 2026-07-01 cutover-Mittwoch /
KW-27 Fr 2026-07-03 sign-off-Freitag Doppel-Welle-6+7 cutover
window (per ``docs/quality-gates/phase-3-marathon-final-
acceptance.md`` Marathon-Cadence row KW-27 +
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` row
Welle-6 + ``docs/ci/phase-3-marathon-rollback-runbook.md``
Job-Graph J3).

The four substrates aggregated here:

* ``S1`` welle_6_producer
    Selin Tag-74 Welle-6 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-6.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status + welle-number=6
    invariants.

* ``S2`` welle_6_audit_anchor
    Tomas Tag-74 Welle-6 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-6 sign-off bundle
    on disk, computes a deterministic SHA-256 anchor across the
    bundle keys, and emits a producer-facing envelope. The
    simulation verifies the envelope's ``audit_trail_anchor``
    field is a 64-hex SHA-256 hash and the bundle-keys match
    the producer's rollup-links.

* ``S3`` doppel_welle_coupling_gate
    Tag-74 Doppel-Welle-6+7 Coupling-Gate (Amara, distinctive
    Welle-6 substrate). Welle-6 (subscribe_loop) does NOT have a
    snapshot-restore dependency; its distinctive substrate-
    coupling is to Welle-7 recovery_workflow: a NATS-subject-
    drift or R1-capability-token rotation-race between the two
    moduln MUST block the Doppel-Welle parallel cutover. The
    coupling-direction is bi-directional under PAR-path
    (parallel-cutover); the gate probes the READY / PARTNER-
    MISSING / PARTNER-DEFECT trinary surface against the
    Welle-7 recovery_workflow readiness signal.

* ``S4`` downstream_block_cascade
    AP-9-analogue Anti-Pattern downstream-block cascade
    simulation. When Welle-6 fires DEFECT (subscribe_loop
    rollback), the downstream Welle 7 (recovery_workflow) must
    be blocked by the forward-cascade-rule because the Doppel-
    Welle-6+7 PAR-path requires both moduln on rust within a
    single boot envelope. Welle-6 itself is also in the blocked-
    set (rollback of Welle-6 cancels the Welle-6 cutover). The
    hermetic stage probes the cascade-rule under three scenarios
    (Welle-6-INTACT -> no block; Welle-6-DRIFT -> warning, no
    block; Welle-6-DEFECT -> welle-6,7 blocked).

    Note: Wellen-1/2/3/4/5 are NOT in the forward-cascade-set
    for Welle-6 (they are upstream of Welle-6 in the cutover
    order, even though Welle-4+5 fire in parallel as Doppel-
    Welle-4+5). The forward-cascade is strictly forward.

* ``S5`` aggregate
    Final trinary aggregator (this module). Folds the four stage
    verdicts into a single WELLE-6-INTACT / DRIFT / DEFECT signal.

Aggregated verdict
------------------

The Tag-74 aggregator emits a single trinary verdict for the
Welle-6 subscribe_loop pipeline:

* ``WELLE-6-INTACT`` -- all four stage verdicts green.
  The Welle-6 cutover pipeline simulation is end-to-end clean;
  the actual Welle-6 trigger on 2026-07-01 has hermetic-evidence
  of substrate contract-stability and Doppel-Welle-6+7-coupling
  discipline.
* ``WELLE-6-DRIFT`` -- at least one stage yellow, zero red.
  The pipeline simulates with degraded signal on at least one
  substrate but no defect; operator-hand reads the per-stage
  notes before the live Welle-6 trigger (e.g. doppel-coupling
  PARTNER-MISSING is a yellow flag operator must address before
  cutover-Mittwoch).
* ``WELLE-6-DEFECT`` -- at least one stage red, or any stage
  envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break OR a doppel-coupling
  PARTNER-DEFECT OR a cascade-rule break; the cutover-runbook
  pauses on the failing substrate before the live Welle-6
  trigger, and the AP-9-analogue downstream-cascade is
  consulted to determine the blocked-wellen surface (6,7).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle-6
dispatch. The aggregator is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-74 plan. The
four input envelopes are read from disk paths supplied by the
caller; the aggregator does not attempt to fetch them via gh CLI
or GitHub API (that is the workflow's job).

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-74 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual Welle-6 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual Welle-6
trigger is operator-hand on 2026-07-01.

Brief-vs-canonical reconciliation (Tag-71+72+73 lehre)
------------------------------------------------------

The Tag-74 Auftrag brief carried three non-canonical values that
this aggregator corrects against the repo doku-tree (per
``feedback_high_tempo_spawn_collision.md`` and the brief-werte-
verifikation discipline):

* Brief said "Cross-Substrate-Parity-Welle KW-26 Fr".
  Canonical per ``docs/ci/phase-3-marathon-rollback-runbook.md``
  Job-Graph is **J3 W6 subscribe_loop rust->python**;
  canonical per ``docs/quality-gates/pre-cutover-acceptance-
  run-order.md`` row Welle-6 + ``docs/quality-gates/phase-3-
  marathon-final-acceptance.md`` row KW-27 is **KW-27 Mi
  2026-07-01 cutover / KW-27 Fr 2026-07-03 sign-off**, NOT
  "KW-26 Fr". The "Cross-Substrate-Parity" framing is a
  parallel KW-24-Acceptance-view per
  ``docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md``
  §6 (Welle-6 = Cross-Substrate-Parity). Tag-72/73 already
  pinned the Marathon-Rollback-Runbook view as canonical;
  Tag-74 follows the same precedent and surfaces the Cross-
  Substrate-Parity view as parallel-substrate-evidence on the
  envelope.
* Brief implied the canonical week is KW-26. In fact
  ``state/welle-6.json`` carries ``kw_cutover_anchor: "KW-26"``
  which conflicts with ``pre-cutover-acceptance-run-order.md``
  row Welle-6 (KW-27 Doppel-Welle-6+7). The state-file drift
  is surfaced as a pin-drift marker on the envelope; the state-
  file is NOT modified by this smoke (Amara scope: surface, not
  patch; ADR-0036 producer-domain is Selin).
* Brief framing "Welle-6 Integration-Smoke" matches the Tag-71
  /72/73 precedent verbatim; no drift on the smoke-name axis.
  The doppel-welle-6+7 framing (vs. solo-Welle-5 Tag-73
  precedent) is surfaced on the envelope.

All three corrections are surfaced verbatim on the envelope under
``brief_vs_canonical_reconciliation`` for the audit trail.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-6 substrate envelopes for the Tag-74
Welle-6 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the rollback-runbook (Zone-K), or the forward-cascade-
rule helpers (Selin-domain). All four substrate envelopes are
consumed read-only. The state/welle-6.json kw-anchor drift is
surfaced but NOT patched (Selin-domain).

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from the
  Welle-6 state-file producer.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  the Welle-6 audit-trail-anchor wire-helper.
* Zone-M: QA x Selin+Tomas -- doppel-coupling-gate-stage S3
  inherits from the Welle-7 recovery_workflow substrate
  readiness signal. Drift in the READY/PARTNER-MISSING/
  PARTNER-DEFECT trinary is a Zone-M signal.
* Zone-M: QA x Selin -- downstream-cascade-stage S4 inherits
  from the forward-cascade-rule analogue of AP-9 for Welle-6
  (``blocked_wellen=(6,7)`` on DEFECT). Drift in the cascade-
  mapping is a Zone-M signal.
* Zone-N: QA x Henrik -- the aggregated WELLE-6 envelope,
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

# Canonical chronological order of the Welle-6 pipeline:
#   producer -> audit-anchor -> doppel-coupling-gate -> downstream-cascade.
# This is the order in which the four substrate-checks fire on the
# actual 2026-07-01 Welle-6-Cutover-Day pipeline. The aggregator
# preserves this order in step_results / failed_steps / per_note
# so the marathon-dashboard correlation is one-to-one with the
# operator-runbook section ordering.
STAGES: tuple[str, ...] = (
    "welle_6_producer",
    "welle_6_audit_anchor",
    "doppel_welle_coupling_gate",
    "downstream_block_cascade",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-74 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.

WELLE_6_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-6-PRODUCER-READY": "green",
    "WELLE-6-PRODUCER-DRIFT": "yellow",
    "WELLE-6-PRODUCER-DEFECT": "red",
}

WELLE_6_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-6-AUDIT-ANCHOR-READY": "green",
    "WELLE-6-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-6-AUDIT-ANCHOR-DEFECT": "red",
}

DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP: dict[str, str] = {
    # Tag-74 Doppel-Welle-6+7 coupling-gate trinary surface:
    # READY = green (Welle-7 partner recovery_workflow INTACT,
    # subscribe_loop flip safe under PAR-path);
    # PARTNER-MISSING = yellow (Welle-7 partner state not
    # observable; operator-hand verification required before
    # Welle-6 flip; may also indicate SEQ-path posture);
    # PARTNER-DEFECT = red (Welle-7 partner recovery_workflow
    # DEFECT, subscribe_loop PAR-path flip MUST NOT proceed;
    # abort or fall back to SEQ-path).
    "DOPPEL-COUPLING-READY": "green",
    "DOPPEL-COUPLING-PARTNER-MISSING": "yellow",
    "DOPPEL-COUPLING-PARTNER-DEFECT": "red",
}

DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP: dict[str, str] = {
    # The cascade-stage emits CASCADE-CONSISTENT when the forward-
    # cascade rule fires correctly under all three probe scenarios
    # (welle-6-INTACT / DRIFT / DEFECT); CASCADE-DRIFT when one
    # probe surface has soft mismatch; CASCADE-BREAK when the
    # cascade-mapping diverges from blocked_wellen=(6,7) on
    # DEFECT.
    "CASCADE-CONSISTENT": "green",
    "CASCADE-DRIFT": "yellow",
    "CASCADE-BREAK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_6_producer": WELLE_6_PRODUCER_VERDICT_MAP,
    "welle_6_audit_anchor": WELLE_6_AUDIT_ANCHOR_VERDICT_MAP,
    "doppel_welle_coupling_gate": DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP,
    "downstream_block_cascade": DOWNSTREAM_BLOCK_CASCADE_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "WELLE-6-INTACT"
VERDICT_DRIFT: str = "WELLE-6-DRIFT"
VERDICT_DEFECT: str = "WELLE-6-DEFECT"


# ---- Welle-6 anchor constants --------------------------------------------

# Welle-6 (subscribe_loop, Doppel-Welle-6+7 parallel) is
# anchored on 2026-07-01 (KW-27 Mi) cutover / 2026-07-03 (KW-27 Fr)
# sign-off per `docs/quality-gates/phase-3-marathon-final-
# acceptance.md` row KW-27 and `docs/quality-gates/pre-cutover-
# acceptance-run-order.md` row Welle-6. The aggregator surfaces
# this on the envelope for the marathon-dashboard correlation; it
# does NOT enforce the date itself (the workflow trigger surface
# owns the trigger window).
WELLE_6_ISO_CUTOVER_DATE: str = "2026-07-01"
WELLE_6_ISO_SIGNOFF_DATE: str = "2026-07-03"
WELLE_6_ISO_WEEK: int = 27
WELLE_6_WELLE_NUMBER: int = 6
WELLE_6_MODUL_MARATHON: str = "subscribe_loop"
WELLE_6_MODUL_ACCEPTANCE_VIEW: str = "cross_substrate_parity"
WELLE_6_ROLLBACK_JOB: str = "J3"
WELLE_6_DOPPEL_WELLE_PARTNER: int = 7


# ---- Forward-cascade constants -------------------------------------------

# Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` AP-9
# (rollback-cascade analogue for Welle-6) and `docs/ci/phase-3-
# marathon-rollback-runbook.md` reverse-cutover order J3: a Welle-6
# DEFECT (subscribe_loop rollback) blocks downstream Wellen 6/7
# (Welle-6 itself + Welle-7 recovery_workflow). Wellen-1/2/3/4/5
# are upstream of Welle-6 and are NOT in the forward-cascade-set.
# Note: Welle-7 (Doppel-Welle partner) IS in the cascade-set even
# though both fire in parallel under PAR-path; the Doppel-Welle
# coupling discipline requires the partner to be blocked when
# Welle-6 reverts (forward-cascade is symmetric within the
# Doppel-Welle pair under PAR-path).
FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT: tuple[int, ...] = (6, 7)


# ---- Substrate provenance ------------------------------------------------

# Cross-anchor records for the four Welle-6 substrates the Tag-74
# integration-smoke aggregates. Surfaced on the envelope for the
# Henrik (Zone-N) audit-evidence trail.
SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_6_producer": {
        "owner": "Selin",
        "tag": "tag-74",
        "pr": None,
        "kind": "persona-engine-welle-6-state-file-producer",
    },
    "welle_6_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-74",
        "pr": None,
        "kind": "ots-welle-6-audit-trail-anchor-integration",
    },
    "doppel_welle_coupling_gate": {
        "owner": "Amara",
        "tag": "tag-74",
        "pr": None,
        "kind": "doppel-welle-6-7-coupling-gate-subscribe-loop",
    },
    "downstream_block_cascade": {
        "owner": "Selin",
        "tag": "ap-9-analogue",
        "pr": None,
        "kind": "persona-engine-welle-6-forward-block-cascade-rule",
    },
}


# ---- Parallel substrate views (Welle-6 has two doc-tree framings) --------

# The two canonical doc-tree views of Welle-6. Tag-74 pins the
# Marathon-Rollback-Runbook view as canonical (consistent with
# Tag-72+73 Welle-4+5 precedent) and surfaces the KW-24-Acceptance
# view as parallel-substrate-evidence for the audit trail.
PARALLEL_SUBSTRATE_VIEWS: dict[str, dict[str, Any]] = {
    "marathon_rollback_runbook_view": {
        "doc": "docs/ci/phase-3-marathon-rollback-runbook.md",
        "anchor": "J3 W6 subscribe_loop rust->python",
        "modul": "subscribe_loop",
        "is_canonical_for_tag_74": True,
    },
    "kw_24_acceptance_view": {
        "doc": "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md",
        "anchor": "§6 Welle-6 KW-26 Fr Cross-Substrate-Parity",
        "modul": "cross_substrate_parity",
        "is_canonical_for_tag_74": False,
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

# Tag-71+72+73 lehre: the Tag-74 Auftrag brief carried three non-
# canonical values that the aggregator surfaces verbatim on the
# envelope for the audit trail (per `feedback_high_tempo_spawn_
# collision.md` and brief-werte-verifikation discipline).
BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "welle_6_modul": {
        "brief_value": "Cross-Substrate-Parity-Welle",
        "canonical_value": (
            "J3 W6 subscribe_loop rust->python "
            "(Marathon-Rollback-Runbook view); cross_substrate_parity "
            "is parallel KW-24-Acceptance view per "
            "kw-24-welle-1-7-acceptance-criteria.md §6"
        ),
        "canonical_source": (
            "docs/ci/phase-3-marathon-rollback-runbook.md Job-Graph "
            "(J3 W6 subscribe_loop; Tag-72/73 Welle-4/5 precedent)"
        ),
        "resolution": (
            "Marathon-Rollback-Runbook wins for Tag-74 canonical; "
            "Cross-Substrate-Parity view surfaced as parallel-"
            "substrate-evidence"
        ),
    },
    "welle_6_kw_anchor": {
        "brief_value": "KW-26 Fr (Cross-Substrate-Parity-Welle KW-26 Fr)",
        "canonical_value": (
            "KW-27 Mi 2026-07-01 cutover / KW-27 Fr 2026-07-03 sign-off"
        ),
        "canonical_source": (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "row Welle-6 (Doppel-Welle-6+7 parallel) + "
            "docs/quality-gates/phase-3-marathon-final-acceptance.md "
            "row KW-27"
        ),
        "resolution": (
            "canonical wins (KW-27, not KW-26); brief KW-26 framing "
            "matches the KW-24-Acceptance-view §6 chronology which "
            "was superseded by the Marathon-Cadence in ADR-0066"
        ),
    },
    "welle_6_state_file_kw_anchor": {
        "brief_value": (
            "state/welle-6.json kw_cutover_anchor=KW-26 (matches brief)"
        ),
        "canonical_value": "KW-27 Mi 2026-07-01 cutover (Doppel-Welle-6+7)",
        "canonical_source": (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "row Welle-6 + phase-3-marathon-final-acceptance.md row KW-27"
        ),
        "resolution": (
            "canonical wins (state-file pin-drift surfaced; "
            "state-file NOT patched per Amara scope discipline, "
            "ADR-0036 producer-domain is Selin)"
        ),
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
    """Apply the Tag-74 decision rule.

    Trinary mirroring the Tag-71/72/73 Welle-3/4/5 pattern: any
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
    """Apply forward-cascade-rule to the aggregated Welle-6 verdict.

    Per `docs/quality-gates/phase-3-marathon-anti-patterns.md`
    AP-9-analogue forward-cascade for Welle-6 (subscribe_loop
    rollback) and `docs/ci/phase-3-marathon-rollback-runbook.md`
    reverse-cutover-order J3, a Welle-6 DEFECT (rollback) blocks
    forward Wellen (6,7). A DRIFT yields no block but surfaces a
    warning; INTACT yields no block.

    Note: Welle-7 IS in the cascade-set as the Doppel-Welle partner
    under PAR-path. The coupling-direction is symmetric within
    the Doppel-Welle-6+7 pair (Tag-74 specific surface; differs
    from Tag-73 Welle-5 one-way coupling to Welle-4).
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
    """Build the aggregated Tag-74 Welle-6-Integration verdict envelope."""
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
        "workflow": "welle-6-integration-smoke",
        "tag": "tag-74",
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
        "welle_6_anchor": {
            "iso_cutover_date": WELLE_6_ISO_CUTOVER_DATE,
            "iso_signoff_date": WELLE_6_ISO_SIGNOFF_DATE,
            "iso_week": WELLE_6_ISO_WEEK,
            "welle_number": WELLE_6_WELLE_NUMBER,
            "modul": WELLE_6_MODUL_MARATHON,
            "modul_acceptance_view": WELLE_6_MODUL_ACCEPTANCE_VIEW,
            "rollback_job": WELLE_6_ROLLBACK_JOB,
            "doppel_welle_partner": WELLE_6_DOPPEL_WELLE_PARTNER,
        },
        "window": {
            "iso_week": iso_week,
            "welle_6_iso_week": WELLE_6_ISO_WEEK,
            "in_welle_6_week": (
                iso_week == WELLE_6_ISO_WEEK if iso_week else False
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
            "partner_welle": WELLE_6_DOPPEL_WELLE_PARTNER,
            "anchor": (
                "docs/quality-gates/pre-cutover-acceptance-run-order.md "
                "row Welle-6 (Doppel-Welle-6+7 parallel) + "
                "docs/quality-gates/phase-3c-doppel-welle-6-7.md"
            ),
            "coupling_direction": (
                "bi-directional under PAR-path: subscribe_loop and "
                "recovery_workflow flip together in a single boot "
                "envelope per ADR-0066 §Beschluss; SEQ-path fallback "
                "decouples the pair sequentially"
            ),
            "partner_defect_blocks_welle_6": True,
            "par_path_anchor": "ADR-0066 §Beschluss Doppel-Welle-Cadence",
            "seq_path_anchor": (
                "docs/quality-gates/phase-3c-doppel-welle-6-7.md §3"
            ),
        },
        "downstream_cascade": {
            "rule": (
                "AP-9-analogue forward-cascade for Welle-6 "
                "subscribe_loop rollback (phase-3-marathon-"
                "anti-patterns.md + phase-3-marathon-rollback-runbook.md)"
            ),
            "blocked_wellen_on_defect": list(
                FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
            ),
            "blocked_wellen_now": list(blocked),
            "cascade_armed": verdict == VERDICT_DEFECT,
            "doppel_welle_symmetry_note": (
                "Welle-7 IS in the forward-cascade-set under PAR-path; "
                "the Doppel-Welle-6+7 pair is symmetric within a single "
                "boot envelope. Tag-74 diverges from Tag-73 Welle-5 "
                "one-way coupling: Welle-6's partner Welle-7 blocks on "
                "Welle-6 DEFECT."
            ),
        },
        "decision_rule": {
            "intact": (
                "all four stage verdicts green "
                "(welle_6_producer + welle_6_audit_anchor + "
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
            "no_actual_welle_6_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_welle_6_integration",
        description=(
            "Aggregate the four Welle-6 substrate verdict envelopes "
            "(welle-6-producer, welle-6-audit-anchor, doppel-welle-"
            "coupling-gate, downstream-block-cascade) into a single "
            "Tag-74 WELLE-6-INTEGRATION verdict for the 2026-07-01 "
            "Welle-6 subscribe_loop Doppel-Welle-6+7 "
            "Cutover-Mittwoch pipeline simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Welle-6 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-6 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--doppel-coupling-envelope",
        type=Path,
        default=None,
        help="Path to Amara Welle-6 doppel-welle-coupling-gate verdict envelope JSON.",
    )
    p.add_argument(
        "--cascade-envelope",
        type=Path,
        default=None,
        help="Path to Welle-6 forward-cascade verdict envelope JSON.",
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
        "welle_6_producer": _load_envelope(args.producer_envelope),
        "welle_6_audit_anchor": _load_envelope(args.audit_anchor_envelope),
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
