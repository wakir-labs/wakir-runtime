#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-75 Welle-7 Integration-Smoke verdict aggregator (Amara).

The Tag-75 Welle-7 Integration-Smoke workflow runs a hermetic
end-to-end simulation of the five Welle-7 substrates that fire in
sequence on the canonical KW-27 Mi 2026-07-01 cutover-Mittwoch /
KW-27 Fr 2026-07-03 sign-off-Freitag Doppel-Welle-6+7 cutover
window (per ``docs/quality-gates/phase-3-marathon-final-
acceptance.md`` Marathon-Cadence row KW-27 +
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` row
Welle-7 + ``docs/ci/phase-3-marathon-rollback-runbook.md``
Job-Graph J2).

Welle-7 is the FINAL-SEALING Welle of the Marathon. Per
``pre-cutover-acceptance-run-order.md`` §3 the Post-Welle-7 slot is
the ONLY slot where the Global Acceptance-Verdict fires (L1-full
State-Machine + L3-full Marathon + L2-record-validation across
Welle-1..Welle-7). Tag-75 simulates the final-sealing substrate-
trio + Welle-7's distinctive IIA-1130 Pre-Auditor gate.

Substrates aggregated
---------------------

* ``S1`` welle_7_producer
    Selin Tag-75 Welle-7 State-File Producer simulation. The
    hermetic stage renders the canonical ``state/welle-7.json``
    via ``tooling/ci/render_engine_state_file_stub.py`` and
    verifies the schema-pin + pending-status + welle-number=7
    invariants.

* ``S2`` welle_7_audit_anchor
    Tomas Tag-75 Welle-7 Audit-Trail-Anchor simulation. The
    hermetic stage assembles a synthetic Welle-7 sign-off bundle
    on disk, computes a deterministic SHA-256 anchor across the
    bundle keys, and emits a producer-facing envelope.

* ``S3`` doppel_welle_coupling_gate
    Tag-75 Doppel-Welle-6+7 Coupling-Gate (W7 side; partner=W6
    subscribe_loop). Mirrors the Tag-74 Stage-3 surface from the
    W7 viewpoint: a Welle-6 subscribe_loop DEFECT MUST block
    Welle-7 PAR-path flip under the Doppel-Welle-6+7 symmetric
    coupling per ADR-0066 §Beschluss and phase-3c-doppel-welle-
    6-7.md §2.

* ``S4`` iia_1130_pre_auditor_gate
    Tag-75 distinctive substrate. Welle-7 is the ORIGINAL IIA-1130
    case (Henrik Tag-39 Welle-6+7 Pre-Audit-Bundle): the audit-
    stream-contract author cannot self-certify the recovery
    story. Per AP-7 in phase-3-marathon-final-acceptance.md the
    substitute control is the AR-Hand-Pre-Auditor-Decision
    recorded in ``state/welle-7-pre-auditor-decision.json``. The
    stage probes the decision-file presence + schema + decision-
    value trinary.

* ``S5`` final_sealing_verification
    Tag-75 distinctive substrate. Welle-7 is the Final-Sealing
    Welle per pre-cutover-acceptance-run-order.md §3. The stage
    probes the discoverability of the three Post-Welle-7 Global-
    Acceptance Layer-anchors (L1-full + L3-full + L2-record-
    validation), emitting READY/PARTIAL/BREAK.

* ``S6`` aggregate
    Final trinary aggregator (this module). Folds the five stage
    verdicts into a single WELLE-7-INTACT/DRIFT/DEFECT signal.

Aggregated verdict
------------------

The Tag-75 aggregator emits a single trinary verdict for the
Welle-7 recovery_workflow pipeline:

* ``WELLE-7-INTACT`` -- all five stage verdicts green.
  Welle-7 cutover pipeline simulation is end-to-end clean; the
  actual Welle-7 trigger on 2026-07-01 has hermetic-evidence of
  substrate contract-stability, Doppel-Welle-6+7-coupling
  discipline, IIA-1130 Pre-Auditor-Decision APPROVED, and the
  Post-Welle-7 Global-Acceptance Layer-anchors all discoverable.

* ``WELLE-7-DRIFT`` -- at least one stage yellow, zero red. The
  pipeline simulates with degraded signal but no defect;
  operator-hand reads the per-stage notes before the live
  Welle-7 trigger (e.g. PRE-AUDITOR-PENDING means AR-Hand-
  Designation still owed; FINAL-SEALING-PARTIAL means one Layer
  anchor missing).

* ``WELLE-7-DEFECT`` -- at least one stage red, or any stage
  envelope missing / unparseable. The pipeline simulation
  reveals a substrate contract-break OR a doppel-coupling
  PARTNER-DEFECT OR a Pre-Auditor REJECTED/MALFORMED OR a
  FINAL-SEALING-BREAK; the cutover-runbook pauses on the failing
  substrate before the live Welle-7 trigger.

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle-7
dispatch. The aggregator is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-75 plan.

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-75 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the actual Welle-7 substrates. Per
``feedback_continuous_mode_keine_push_frage.md`` the workflow
runs to completion on its own; per
``feedback_live_bringup_sandbox_gap.md`` the actual Welle-7
trigger is operator-hand on 2026-07-01, and the IIA-1130
Pre-Auditor-Decision is AR-Hand-Governance.

Brief-vs-canonical reconciliation (Tag-71+72+73+74 lehre)
---------------------------------------------------------

The Tag-75 Auftrag brief was largely canonical-aligned. One
pin-drift surface for the audit trail:

* Brief framing: Welle-7 modul = "Final-Sealing".
  Canonical: Welle-7 substrate-modul is recovery_workflow per
  docs/ci/phase-3-marathon-rollback-runbook.md J2 (J2 W7
  recovery_workflow rust->python). "Final-Sealing" is the
  schedule-role, not the substrate-modul. The envelope surfaces
  both: substrate_modul=recovery_workflow, schedule_role=
  final_sealing_welle.
* Brief cited "ADR-0066 vs KW-24-Acceptance §7". Canonical:
  ADR-0066 (four-Wochen-Cadence) is authoritative; KW-24-
  Acceptance §7 is the Welle-7 row in the parallel KW-24-
  Acceptance-view that was superseded by ADR-0066. The envelope
  surfaces both; ADR-0066 wins.
* Brief cited §11 Pre-Auditor-Disziplin (Tag-66 + Tag-71-Spec).
  Canonical: §11 IIA-1130 anchor is the AR-Hand-Pre-Auditor-
  Decision substitute-control for Welle-7 self-audit trap (AP-7
  in phase-3-marathon-final-acceptance.md §AP-7 +
  state/welle-7-pre-auditor-decision.json schema).

All three reconciliations surfaced verbatim on the envelope
under ``brief_vs_canonical_reconciliation``.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-7 substrate envelopes for the Tag-75
Welle-7 integration-smoke. It does NOT modify the Selin
state-file-producer (Zone-O), the Tomas audit-trail-anchor wiring
(Zone-K), the rollback-runbook (Zone-K), the Pre-Auditor-Decision
schema (Henrik/AR-Hand-domain), or the Layer test-suites (Tag-40/
Tag-41/Tag-43 domains). All five substrate envelopes are consumed
read-only.

Cross-Review-Markers
--------------------

* Zone-M: QA x Selin -- producer-stage S1 inherits from the
  Welle-7 state-file producer.
* Zone-M: QA x Tomas -- audit-anchor-stage S2 inherits from
  the Welle-7 audit-trail-anchor wire-helper.
* Zone-M: QA x Selin+Tomas -- doppel-coupling-gate-stage S3
  inherits from the Welle-6 subscribe_loop substrate readiness
  signal. Drift in the READY/PARTNER-MISSING/PARTNER-DEFECT
  trinary is a Zone-M signal.
* Zone-N: QA x Henrik -- IIA-1130 Pre-Auditor-Gate stage S4
  inherits from the AR-Hand-Pre-Auditor-Decision recorded in
  state/welle-7-pre-auditor-decision.json. The substitute-
  control is AR-Hand-Governance, NOT Henrik-self-certified;
  Henrik consumes the envelope as Audit-Evidence.
* Zone-M: QA x Tomas (audit-trail), Selin (state-machine
  invariants) -- Final-Sealing-Verification stage S5 probes
  Layer-1 (Tomas Tag-40) + Layer-3 (Tomas Tag-43) + Layer-2
  (Selin Tag-41) anchor discoverability.
* Zone-N: QA x Henrik -- the aggregated WELLE-7 envelope,
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

# Canonical chronological order of the Welle-7 pipeline:
#   producer -> audit-anchor -> doppel-coupling-gate ->
#   iia-1130-pre-auditor -> final-sealing-verification.
STAGES: tuple[str, ...] = (
    "welle_7_producer",
    "welle_7_audit_anchor",
    "doppel_welle_coupling_gate",
    "iia_1130_pre_auditor_gate",
    "final_sealing_verification",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

WELLE_7_PRODUCER_VERDICT_MAP: dict[str, str] = {
    "WELLE-7-PRODUCER-READY": "green",
    "WELLE-7-PRODUCER-DRIFT": "yellow",
    "WELLE-7-PRODUCER-DEFECT": "red",
}

WELLE_7_AUDIT_ANCHOR_VERDICT_MAP: dict[str, str] = {
    "WELLE-7-AUDIT-ANCHOR-READY": "green",
    "WELLE-7-AUDIT-ANCHOR-DRIFT": "yellow",
    "WELLE-7-AUDIT-ANCHOR-DEFECT": "red",
}

DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP: dict[str, str] = {
    # Tag-75 Doppel-Welle-6+7 coupling-gate trinary surface
    # (W7 side; partner=W6 subscribe_loop):
    # READY = green (Welle-6 partner subscribe_loop INTACT,
    # recovery_workflow flip safe under PAR-path);
    # PARTNER-MISSING = yellow (Welle-6 partner state not
    # observable; operator-hand verification required);
    # PARTNER-DEFECT = red (Welle-6 partner subscribe_loop
    # DEFECT, recovery_workflow PAR-path flip MUST NOT proceed;
    # abort or fall back to SEQ-path).
    "DOPPEL-COUPLING-READY": "green",
    "DOPPEL-COUPLING-PARTNER-MISSING": "yellow",
    "DOPPEL-COUPLING-PARTNER-DEFECT": "red",
}

IIA_1130_PRE_AUDITOR_VERDICT_MAP: dict[str, str] = {
    # Tag-75 distinctive: Welle-7 IIA-1130 Pre-Auditor-Gate
    # decision-tracking trinary surface. Mirrors phase-3c-welle-7-
    # hot-spot-probe.yml Check-4. APPROVED is green; PENDING and
    # MISSING are yellow (AR-Hand-Designation pending /
    # decision-file not yet staged); REJECTED and MALFORMED are
    # red (Pre-Auditor explicitly rejected OR decision-file
    # invalid).
    "PRE-AUDITOR-APPROVED": "green",
    "PRE-AUDITOR-PENDING": "yellow",
    "PRE-AUDITOR-MISSING": "yellow",
    "PRE-AUDITOR-REJECTED": "red",
    "PRE-AUDITOR-MALFORMED": "red",
}

FINAL_SEALING_VERIFICATION_VERDICT_MAP: dict[str, str] = {
    # Tag-75 distinctive: Welle-7 Final-Sealing-Verification
    # Layer-anchor discoverability surface. READY = all three
    # Layer anchors present; PARTIAL = exactly one missing
    # (yellow); BREAK = two or more missing (red).
    "FINAL-SEALING-READY": "green",
    "FINAL-SEALING-PARTIAL": "yellow",
    "FINAL-SEALING-BREAK": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_7_producer": WELLE_7_PRODUCER_VERDICT_MAP,
    "welle_7_audit_anchor": WELLE_7_AUDIT_ANCHOR_VERDICT_MAP,
    "doppel_welle_coupling_gate": DOPPEL_WELLE_COUPLING_GATE_VERDICT_MAP,
    "iia_1130_pre_auditor_gate": IIA_1130_PRE_AUDITOR_VERDICT_MAP,
    "final_sealing_verification": FINAL_SEALING_VERIFICATION_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "WELLE-7-INTACT"
VERDICT_DRIFT: str = "WELLE-7-DRIFT"
VERDICT_DEFECT: str = "WELLE-7-DEFECT"


# ---- Welle-7 anchor constants --------------------------------------------

# Welle-7 (recovery_workflow, Doppel-Welle-6+7 parallel) is
# anchored on 2026-07-01 (KW-27 Mi) cutover / 2026-07-03 (KW-27 Fr)
# sign-off per `docs/quality-gates/phase-3-marathon-final-
# acceptance.md` row KW-27 and `docs/quality-gates/pre-cutover-
# acceptance-run-order.md` row Welle-7. The aggregator surfaces
# this on the envelope for the marathon-dashboard correlation.
WELLE_7_ISO_CUTOVER_DATE: str = "2026-07-01"
WELLE_7_ISO_SIGNOFF_DATE: str = "2026-07-03"
WELLE_7_ISO_WEEK: int = 27
WELLE_7_WELLE_NUMBER: int = 7
WELLE_7_MODUL_MARATHON: str = "recovery_workflow"
WELLE_7_SCHEDULE_ROLE: str = "final_sealing_welle"
WELLE_7_ROLLBACK_JOB: str = "J2"
WELLE_7_DOPPEL_WELLE_PARTNER: int = 6


# ---- Forward-cascade constants -------------------------------------------

# Welle-7 is the TERMINAL Welle. A Welle-7 DEFECT (rollback)
# blocks (6, 7) under Doppel-Welle-6+7 PAR-path symmetry. This is
# the SAME tuple as Tag-74 Welle-6 forward-cascade -- attesting
# the symmetric Doppel-Welle coupling on the W7 side.
FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT: tuple[int, ...] = (6, 7)


# ---- Final-Sealing Layer anchors -----------------------------------------

# Per pre-cutover-acceptance-run-order.md row Welle-7 Post-Welle
# column the Global Acceptance-Verdict requires the three Layer
# anchors below. Tag-75 Stage 5 probes their discoverability.
GLOBAL_ACCEPTANCE_LAYER_ANCHORS: dict[str, dict[str, Any]] = {
    "l1_state_machine": {
        "path": "tests/phase_3c/test_phase_3_final_regression.py",
        "tag": "tag-40",
        "tests_count": 28,
        "role": "Aggregate marker-emit-gate; fires Post-Welle-7 only (Global).",
    },
    "l3_marathon_schluss": {
        "path": "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
        "tag": "tag-43",
        "tests_count": 27,
        "role": "Four-Wochen-sequence threading; fires Post-Welle-7 only (Global).",
    },
    "l2_record_validation": {
        "path": "tests/phase_3c/test_cutover_day_e2e_drill.py",
        "tag": "tag-41",
        "tests_count": 45,
        "role": "Per-Day sign-off-record producer across Welle-1..7.",
    },
}


# ---- Substrate provenance ------------------------------------------------

SUBSTRATE_PROVENANCE: dict[str, dict[str, Any]] = {
    "welle_7_producer": {
        "owner": "Selin",
        "tag": "tag-75",
        "pr": None,
        "kind": "persona-engine-welle-7-state-file-producer",
    },
    "welle_7_audit_anchor": {
        "owner": "Tomas",
        "tag": "tag-75",
        "pr": None,
        "kind": "ots-welle-7-audit-trail-anchor-integration",
    },
    "doppel_welle_coupling_gate": {
        "owner": "Amara",
        "tag": "tag-75",
        "pr": None,
        "kind": "doppel-welle-6-7-coupling-gate-recovery-workflow-w7-side",
    },
    "iia_1130_pre_auditor_gate": {
        "owner": "Amara",
        "tag": "tag-75",
        "pr": None,
        "kind": "iia-1130-pre-auditor-decision-tracking-gate",
        "decision_owner": "AR-Hand (substitute-control for Henrik self-audit trap)",
    },
    "final_sealing_verification": {
        "owner": "Amara",
        "tag": "tag-75",
        "pr": None,
        "kind": "post-welle-7-global-acceptance-anchor-discoverability",
    },
}


# ---- Parallel substrate views (Welle-7 has two doc-tree framings) --------

PARALLEL_SUBSTRATE_VIEWS: dict[str, dict[str, Any]] = {
    "marathon_rollback_runbook_view": {
        "doc": "docs/ci/phase-3-marathon-rollback-runbook.md",
        "anchor": "J2 W7 recovery_workflow rust->python",
        "modul": "recovery_workflow",
        "is_canonical_for_tag_75": True,
    },
    "kw_24_acceptance_view": {
        "doc": "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md",
        "anchor": "§7 Welle-7 (parallel KW-24-Acceptance view, superseded by ADR-0066)",
        "modul": "recovery_workflow",
        "is_canonical_for_tag_75": False,
    },
    "pre_cutover_run_order_view": {
        "doc": "docs/quality-gates/pre-cutover-acceptance-run-order.md",
        "anchor": "§3 row Welle-7 (Doppel-Welle-6+7 + Post-Welle Global Acceptance-Verdict)",
        "modul": "recovery_workflow",
        "is_canonical_for_tag_75": True,
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "welle_7_modul_framing": {
        "brief_value": (
            "Welle-7 = Final-Sealing-Welle (schedule-role framing)"
        ),
        "canonical_value": (
            "substrate_modul=recovery_workflow (J2 W7 in Marathon-"
            "Rollback-Runbook); schedule_role=final_sealing_welle "
            "(Post-Welle-7 Global Acceptance-Verdict slot per "
            "pre-cutover-acceptance-run-order.md §3)"
        ),
        "canonical_source": (
            "docs/ci/phase-3-marathon-rollback-runbook.md Job-Graph "
            "(J2 W7 recovery_workflow rust->python) + "
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "§3 row Welle-7"
        ),
        "resolution": (
            "both framings surfaced on the envelope; substrate_modul "
            "+ schedule_role both anchored"
        ),
    },
    "anchor_trio_authority": {
        "brief_value": (
            "ADR-0066 vs KW-24-Acceptance §7 (cited as anchor trio)"
        ),
        "canonical_value": (
            "ADR-0066 (four-Wochen-Cadence) wins; KW-24-Acceptance §7 "
            "is the Welle-7 row in the parallel view superseded by "
            "ADR-0066"
        ),
        "canonical_source": (
            "decisions/0066-*.md §Beschluss + "
            "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md §7"
        ),
        "resolution": (
            "ADR-0066 canonical for Tag-75; KW-24-Acceptance §7 "
            "surfaced as parallel-view evidence"
        ),
    },
    "pre_auditor_disciplin_anchor_chain": {
        "brief_value": (
            "§11 Pre-Auditor-Disziplin (Tag-66 + Tag-71-Spec) "
            "[citing IIA-1130]"
        ),
        "canonical_value": (
            "§11 IIA-1130 anchor = AR-Hand-Pre-Auditor-Decision "
            "substitute-control for Welle-7 self-audit trap (AP-7); "
            "decision-file schema in state/welle-7-pre-auditor-"
            "decision.json; hot-spot-probe Check-4 surface"
        ),
        "canonical_source": (
            "docs/quality-gates/phase-3-marathon-final-acceptance.md "
            "§AP-7 + .github/workflows/phase-3c-welle-7-hot-spot-"
            "probe.yml Check-4 + Henrik Tag-39 Welle-6+7 Pre-Audit-"
            "Bundle"
        ),
        "resolution": (
            "full anchor-chain surfaced on the envelope; IIA-1130 "
            "Independence-and-Objectivity standard (Henrik cannot "
            "self-certify the recovery story) is the authoritative "
            "frame"
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
    """Map an input envelope's ``verdict`` to a uniform trinary status."""
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
    """Apply the Tag-75 decision rule.

    Trinary mirroring the Tag-71/72/73/74 Welle-3/4/5/6 pattern:
    any red collapses to DEFECT; any yellow degrades to DRIFT;
    all green yields INTACT.
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
    """Apply forward-cascade-rule to the aggregated Welle-7 verdict.

    Welle-7 is the TERMINAL Welle in cutover-order; rollback
    blocks (6,7) under the Doppel-Welle-6+7 PAR-path symmetric
    coupling. INTACT and DRIFT yield no block (DRIFT surfaces a
    warning).
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
    """Build the aggregated Tag-75 Welle-7-Integration verdict envelope."""
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
        "workflow": "welle-7-integration-smoke",
        "tag": "tag-75",
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
        "welle_7_anchor": {
            "iso_cutover_date": WELLE_7_ISO_CUTOVER_DATE,
            "iso_signoff_date": WELLE_7_ISO_SIGNOFF_DATE,
            "iso_week": WELLE_7_ISO_WEEK,
            "welle_number": WELLE_7_WELLE_NUMBER,
            "substrate_modul": WELLE_7_MODUL_MARATHON,
            "schedule_role": WELLE_7_SCHEDULE_ROLE,
            "rollback_job": WELLE_7_ROLLBACK_JOB,
            "doppel_welle_partner": WELLE_7_DOPPEL_WELLE_PARTNER,
            "is_terminal_welle": True,
            "is_final_sealing_welle": True,
        },
        "window": {
            "iso_week": iso_week,
            "welle_7_iso_week": WELLE_7_ISO_WEEK,
            "in_welle_7_week": (
                iso_week == WELLE_7_ISO_WEEK if iso_week else False
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
            "partner_welle": WELLE_7_DOPPEL_WELLE_PARTNER,
            "anchor": (
                "docs/quality-gates/pre-cutover-acceptance-run-order.md "
                "row Welle-7 (Doppel-Welle-6+7 parallel) + "
                "docs/quality-gates/phase-3c-doppel-welle-6-7.md"
            ),
            "coupling_direction": (
                "bi-directional under PAR-path: recovery_workflow and "
                "subscribe_loop flip together in a single boot "
                "envelope per ADR-0066 §Beschluss; SEQ-path fallback "
                "decouples the pair sequentially"
            ),
            "partner_defect_blocks_welle_7": True,
            "symmetry_with_tag_74": True,
            "par_path_anchor": "ADR-0066 §Beschluss Doppel-Welle-Cadence",
            "seq_path_anchor": (
                "docs/quality-gates/phase-3c-doppel-welle-6-7.md §3"
            ),
        },
        "downstream_cascade": {
            "rule": (
                "Forward-cascade for Welle-7 recovery_workflow "
                "rollback under Doppel-Welle-6+7 PAR-path symmetric "
                "coupling (phase-3-marathon-rollback-runbook.md J2 "
                "+ phase-3c-doppel-welle-6-7.md §2)"
            ),
            "blocked_wellen_on_defect": list(
                FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT
            ),
            "blocked_wellen_now": list(blocked),
            "cascade_armed": verdict == VERDICT_DEFECT,
            "terminal_welle_note": (
                "Welle-7 is the TERMINAL Welle in cutover-order. "
                "Wellen-1..5 are upstream and already complete by "
                "Welle-7 fire-time; they are NOT in the forward-block "
                "set. The Doppel-Welle partner Welle-6 IS in the "
                "block-set under PAR-path symmetric coupling (same "
                "tuple as Tag-74 Welle-6 forward-cascade)."
            ),
        },
        "iia_1130_pre_auditor": {
            "anchor": (
                "phase-3-marathon-final-acceptance.md §AP-7 + "
                ".github/workflows/phase-3c-welle-7-hot-spot-probe.yml "
                "Check-4 + Henrik Tag-39 Welle-6+7 Pre-Audit-Bundle"
            ),
            "standard": (
                "IIA-1130 Independence and Objectivity: the audit-"
                "stream-contract author (Henrik) cannot self-certify "
                "the recovery story; AR-Hand designates external "
                "Pre-Auditor as substitute-control"
            ),
            "decision_file": "state/welle-7-pre-auditor-decision.json",
            "decision_owner": "AR-Hand (substitute-control)",
            "decision_value_axis": ["APPROVED", "PENDING", "REJECTED"],
            "missing_state_axis": "PRE-AUDITOR-MISSING (pending-AR-designation)",
            "malformed_state_axis": "PRE-AUDITOR-MALFORMED (schema or value invalid)",
        },
        "final_sealing": {
            "post_welle_7_global_acceptance_slot": (
                "KW-27 Fr 2026-07-03 sign-off-Freitag (per pre-cutover-"
                "acceptance-run-order.md §3 row Welle-7 Post-Welle "
                "column)"
            ),
            "layer_anchors": GLOBAL_ACCEPTANCE_LAYER_ANCHORS,
            "discoverability_thresholds": {
                "ready": "all 3 anchors present",
                "partial": "exactly 1 anchor missing (yellow)",
                "break": "2 or more anchors missing (red)",
            },
            "stage_role": (
                "Stage 5 probes Layer-anchor discoverability only; "
                "the actual L1/L2/L3 test-suites fire as separate "
                "Marathon-Final-Acceptance gates on Post-Welle-7 "
                "sign-off-Freitag."
            ),
        },
        "decision_rule": {
            "intact": (
                "all five stage verdicts green "
                "(welle_7_producer + welle_7_audit_anchor + "
                "doppel_welle_coupling_gate + iia_1130_pre_auditor_gate "
                "+ final_sealing_verification)"
            ),
            "drift": "at least one yellow, zero red",
            "defect": (
                "at least one red, OR any envelope missing, "
                "OR doppel-coupling PARTNER-DEFECT, OR Pre-Auditor "
                "REJECTED/MALFORMED, OR FINAL-SEALING-BREAK"
            ),
        },
        "brief_vs_canonical_reconciliation": BRIEF_VS_CANONICAL_RECONCILIATION,
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_7_dispatch": True,
            "no_gh_workflow_run": True,
            "no_ar_hand_pre_auditor_decision_emission": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_welle_7_integration",
        description=(
            "Aggregate the five Welle-7 substrate verdict envelopes "
            "(welle-7-producer, welle-7-audit-anchor, doppel-welle-"
            "coupling-gate W7 side, iia-1130-pre-auditor-gate, "
            "final-sealing-verification) into a single Tag-75 "
            "WELLE-7-INTEGRATION verdict for the 2026-07-01 Welle-7 "
            "recovery_workflow Doppel-Welle-6+7 Cutover-Mittwoch "
            "+ 2026-07-03 Post-Welle-7 Global-Acceptance pipeline "
            "simulation."
        ),
    )
    p.add_argument(
        "--producer-envelope",
        type=Path,
        default=None,
        help="Path to Selin Welle-7 producer-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--audit-anchor-envelope",
        type=Path,
        default=None,
        help="Path to Tomas Welle-7 audit-anchor-stage verdict envelope JSON.",
    )
    p.add_argument(
        "--doppel-coupling-envelope",
        type=Path,
        default=None,
        help="Path to Amara Welle-7 doppel-welle-coupling-gate (W7 side) verdict envelope JSON.",
    )
    p.add_argument(
        "--pre-auditor-envelope",
        type=Path,
        default=None,
        help="Path to Amara Welle-7 IIA-1130 pre-auditor-gate verdict envelope JSON.",
    )
    p.add_argument(
        "--final-sealing-envelope",
        type=Path,
        default=None,
        help="Path to Amara Welle-7 final-sealing-verification verdict envelope JSON.",
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
        "welle_7_producer": _load_envelope(args.producer_envelope),
        "welle_7_audit_anchor": _load_envelope(args.audit_anchor_envelope),
        "doppel_welle_coupling_gate": _load_envelope(args.doppel_coupling_envelope),
        "iia_1130_pre_auditor_gate": _load_envelope(args.pre_auditor_envelope),
        "final_sealing_verification": _load_envelope(args.final_sealing_envelope),
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
