#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-77 Marathon-Final-Smoke E2E verdict aggregator (Amara).

The Tag-77 Marathon-Final-Smoke-E2E workflow is the umbrella
hermetic smoke for the Phase-3c Cutover-Marathon. It bundles
**eleven** stages into a single consolidated MARATHON-FINAL
verdict:

  * Stages 1..7 -- the seven per-Welle-Integration-Smoke envelopes
    (Welle-1..Welle-7; Tag-69 + Tag-70 audit-anchor stand-ins for
    Welle-1+2, Tag-71..Tag-75 canonical for Welle-3..Welle-7).
  * Stage 8 -- the Tag-76 Cross-Welle-Stability-Pin substrate
    envelope (forward-block + reverse-block + Doppel-Welle
    symmetry pattern).
  * Stage 9 -- the Tag-76 Marathon-Closeout-Aggregator substrate
    envelope (Welle-1..7 Final-Sealing-Verifier-Family bundler,
    Reza Tag-76 #479).
  * Stage 10 -- the Tag-76 Phase-3-COMPLETE-Marker-Audit-Bundle
    substrate envelope (Welle-1..7 audit-anchor markers bundled
    into the Phase-3-COMPLETE hand-off, Tomas Tag-76 #484).
  * Stage 11 -- the aggregated MARATHON-FINAL verdict.

Decision surface
----------------

The aggregator folds the ten input envelopes into the trinary
MARATHON-FINAL surface:

* ``MARATHON-FINAL-INTACT`` -- all ten stage inputs green.
  The seven Wellen are INTACT, the cross-Welle stability pin is
  INTACT, the closeout aggregator is MARATHON-CLOSEOUT-READY, and
  the Phase-3-COMPLETE-Marker-Audit-Bundle is BUNDLE-READY. This
  is the umbrella "Phase-3 Marathon is sealable" condition.

* ``MARATHON-FINAL-DRIFT`` -- at least one stage yellow, zero red.
  Operator-hand reads per-stage notes before the next live
  Welle / closeout trigger.

* ``MARATHON-FINAL-DEFECT`` -- at least one stage red, OR any
  envelope missing / unparseable, OR an unknown verdict surfaces.

Aggregator scope
----------------

The aggregator consumes TEN input envelopes (Stages 1..10) and
emits the umbrella verdict (Stage 11). It does NOT re-derive any
substrate decision; it consumes them read-only from the per-stage
envelopes that the workflow assembles inside the hermetic GitHub
Actions sandbox. The aggregator is therefore the **thinnest**
roll-up over the Tag-76 substrate; no Welle-N or closeout logic is
re-implemented.

Canonical anchors
-----------------

* ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3 --
  seven Welle-Datumsanker (cross-Welle sequencing contract;
  authoritative for the cross-Welle date-axis).
* ``docs/quality-gates/phase-3-marathon-anti-patterns.md`` §AP-9 --
  Welle-3-Rollback-Cascade anchor (3, 4, 5, 6, 7) Forward-Block
  topology.
* ``decisions/0066-marathon-cadence-vier-wochen.md`` §Beschluss --
  Doppel-Welle PAR-path discipline ((1,2), (4,5), (6,7)).
* Tag-76 Cross-Welle-Stability-Pin substrate (Amara PR #483) --
  Stage 8 input.
* Tag-76 Marathon-Closeout-Aggregator substrate (Reza PR #479) --
  Stage 9 input.
* Tag-76 Phase-3-COMPLETE-Marker-Audit-Bundle substrate
  (Tomas PR #484) -- Stage 10 input.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle dispatch,
no Phase-3-COMPLETE-marker emit, no closeout signing. The
aggregator is hermetic-by-construction per Mira's Sandbox-vs-Host-
Operations Trennung and the Tag-77 Marathon-Polish plan.

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-77 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the underlying Welle-N, Cross-Welle, Closeout, or Phase-3-COMPLETE
workflows. Per ``feedback_continuous_mode_keine_pause_frage.md``
the workflow runs to completion on its own without per-stage
approvals; per ``feedback_continuous_mode_keine_push_frage.md``
the merge of this PR is part of the Tag-77 Marathon-Polish
substrate-set and happens automatically.

Brief-vs-canonical reconciliation
---------------------------------

The Tag-77 brief was canonical-aligned. Two reconciliations
surface for the audit trail:

* Brief framing: "Stage 1..7: alle 7 Welle-Integration-Smokes".
  Canonical: five Welle-Integration-Smoke aggregators exist on
  main as of Tag-77 (Welle-3..Welle-7 = Tag-71..Tag-75); Welle-1
  (Tag-69) and Welle-2 (Tag-70) carry audit-anchor wiring only.
  Tag-77 surfaces this distinction in the per-Welle envelope
  provenance carried forward from the Tag-76 Cross-Welle-
  Stability-Pin substrate (Stage 8 envelope ``per_welle_envelope_
  provenance`` field).

* Brief framing: "Stage 9: Marathon-Closeout-Aggregator" vs
  "Stage 10: Phase-3-COMPLETE-Marker-Audit-Bundle". Canonical:
  these are two distinct Tag-76 substrates -- the Reza closeout
  aggregator (PR #479) emits a MARATHON-CLOSEOUT-READY /
  PARTIAL / DEFECT verdict; the Tomas Phase-3-COMPLETE-Marker
  audit-bundle (PR #484) emits a BUNDLE-READY / BUNDLE-PARTIAL /
  BUNDLE-DEFECT verdict (the per-marker Welle-1..7-Kind-
  Disjointness pin). Tag-77 surfaces both as separate stages with
  distinct envelope shapes (no re-implementation; verdict-string
  read-only).

Cross-Review-Markers
--------------------

* Zone-M: QA x Tomas / Selin / Reza / Henrik -- all ten input
  envelopes are inherited read-only from the Tag-69..Tag-76
  substrate-trio outputs. Tag-77 adds zero substrate decisions;
  it is umbrella-only.
* Zone-N: QA x Henrik -- the aggregated MARATHON-FINAL envelope is
  the umbrella Audit-Evidence-Input for the Marathon-Closeout
  Audit-Bundle (over and above the per-substrate envelopes which
  remain individually consumable).
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

# Canonical order of the Tag-77 Marathon-Final-Smoke aggregator
# inputs: the seven per-Welle integration-smoke envelopes followed
# by the three Marathon-Closeout substrates (Cross-Welle-Stability,
# Marathon-Closeout-Aggregator, Phase-3-COMPLETE-Marker-Audit-
# Bundle). Order is strict-chronological by cutover-date across
# Welle-1..Welle-7 (per docs/quality-gates/pre-cutover-acceptance-
# run-order.md §3), then by substrate-emission-tag (Stage 8 = Tag-76
# Amara, Stage 9 = Tag-76 Reza, Stage 10 = Tag-76 Tomas).
STAGES: tuple[str, ...] = (
    "welle_1_integration_smoke",
    "welle_2_integration_smoke",
    "welle_3_integration_smoke",
    "welle_4_integration_smoke",
    "welle_5_integration_smoke",
    "welle_6_integration_smoke",
    "welle_7_integration_smoke",
    "cross_welle_stability_pin",
    "marathon_closeout_aggregator",
    "phase_3_complete_marker_audit_bundle",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------


def _welle_n_map(n: int) -> dict[str, str]:
    """Per-Welle integration-smoke trinary surface."""
    return {
        f"WELLE-{n}-INTACT": "green",
        f"WELLE-{n}-DRIFT": "yellow",
        f"WELLE-{n}-DEFECT": "red",
    }


WELLE_1_VERDICT_MAP: dict[str, str] = _welle_n_map(1)
WELLE_2_VERDICT_MAP: dict[str, str] = _welle_n_map(2)
WELLE_3_VERDICT_MAP: dict[str, str] = _welle_n_map(3)
WELLE_4_VERDICT_MAP: dict[str, str] = _welle_n_map(4)
WELLE_5_VERDICT_MAP: dict[str, str] = _welle_n_map(5)
WELLE_6_VERDICT_MAP: dict[str, str] = _welle_n_map(6)
WELLE_7_VERDICT_MAP: dict[str, str] = _welle_n_map(7)

# Tag-76 Cross-Welle-Stability-Pin (Amara, PR #483) trinary surface.
CROSS_WELLE_STABILITY_VERDICT_MAP: dict[str, str] = {
    "CROSS-WELLE-STABILITY-INTACT": "green",
    "CROSS-WELLE-STABILITY-DRIFT": "yellow",
    "CROSS-WELLE-STABILITY-DEFECT": "red",
}

# Tag-76 Marathon-Closeout-Aggregator (Reza, PR #479) trinary surface.
# The Reza aggregator emits MARATHON-CLOSEOUT-READY (green) /
# PARTIAL (yellow) / DEFECT (red).
MARATHON_CLOSEOUT_VERDICT_MAP: dict[str, str] = {
    "MARATHON-CLOSEOUT-READY": "green",
    "PARTIAL": "yellow",
    "DEFECT": "red",
}

# Tag-76 Phase-3-COMPLETE-Marker-Audit-Bundle (Tomas, PR #484).
# The producer-envelope surfaces BUNDLE-READY / BUNDLE-PARTIAL /
# BUNDLE-DEFECT for the Welle-1..7-Kind-Disjointness-Pin status.
PHASE_3_COMPLETE_BUNDLE_VERDICT_MAP: dict[str, str] = {
    "BUNDLE-READY": "green",
    "BUNDLE-PARTIAL": "yellow",
    "BUNDLE-DEFECT": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_1_integration_smoke": WELLE_1_VERDICT_MAP,
    "welle_2_integration_smoke": WELLE_2_VERDICT_MAP,
    "welle_3_integration_smoke": WELLE_3_VERDICT_MAP,
    "welle_4_integration_smoke": WELLE_4_VERDICT_MAP,
    "welle_5_integration_smoke": WELLE_5_VERDICT_MAP,
    "welle_6_integration_smoke": WELLE_6_VERDICT_MAP,
    "welle_7_integration_smoke": WELLE_7_VERDICT_MAP,
    "cross_welle_stability_pin": CROSS_WELLE_STABILITY_VERDICT_MAP,
    "marathon_closeout_aggregator": MARATHON_CLOSEOUT_VERDICT_MAP,
    "phase_3_complete_marker_audit_bundle": PHASE_3_COMPLETE_BUNDLE_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "MARATHON-FINAL-INTACT"
VERDICT_DRIFT: str = "MARATHON-FINAL-DRIFT"
VERDICT_DEFECT: str = "MARATHON-FINAL-DEFECT"


# ---- Per-Welle canonical anchors -----------------------------------------

# Per docs/quality-gates/pre-cutover-acceptance-run-order.md §3.
# Same map as Tag-76 cross-Welle-stability-pin (Amara PR #483); kept
# here verbatim so the Tag-77 verdict envelope is self-contained.
PER_WELLE_RUN_ORDER_ANCHORS: dict[int, dict[str, Any]] = {
    1: {
        "iso_cutover_date": "2026-06-10",
        "iso_signoff_date": "2026-06-12",
        "iso_week": 24,
        "doppel_partner": 2,
        "modul": "audit_writer_singleton",
    },
    2: {
        "iso_cutover_date": "2026-06-10",
        "iso_signoff_date": "2026-06-12",
        "iso_week": 24,
        "doppel_partner": 1,
        "modul": "kw_24_marker_emit",
    },
    3: {
        "iso_cutover_date": "2026-06-17",
        "iso_signoff_date": "2026-06-19",
        "iso_week": 25,
        "doppel_partner": None,
        "modul": "bridge_audit_writer",
    },
    4: {
        "iso_cutover_date": "2026-06-24",
        "iso_signoff_date": "2026-06-26",
        "iso_week": 26,
        "doppel_partner": 5,
        "modul": "state_backing",
    },
    5: {
        "iso_cutover_date": "2026-06-24",
        "iso_signoff_date": "2026-06-26",
        "iso_week": 26,
        "doppel_partner": 4,
        "modul": "lifecycle_state_machine",
    },
    6: {
        "iso_cutover_date": "2026-07-01",
        "iso_signoff_date": "2026-07-03",
        "iso_week": 27,
        "doppel_partner": 7,
        "modul": "subscribe_loop",
    },
    7: {
        "iso_cutover_date": "2026-07-01",
        "iso_signoff_date": "2026-07-03",
        "iso_week": 27,
        "doppel_partner": 6,
        "modul": "recovery_workflow",
    },
}


# ---- Substrate provenance ------------------------------------------------

# Per-stage substrate provenance: which Tag-N substrate emits the
# envelope, who owns it, where the canonical artefact lives. Surfaced
# verbatim in the Tag-77 envelope as ``stage_provenance``.
STAGE_PROVENANCE: dict[str, dict[str, str]] = {
    "welle_1_integration_smoke": {
        "tag": "tag-69",
        "owner": "Tomas+Selin",
        "kind": "audit-anchor-only-stand-in",
        "canonical_artefact": "tests/ci/test_welle_1_audit_anchor_tag69.py",
    },
    "welle_2_integration_smoke": {
        "tag": "tag-70",
        "owner": "Tomas+Selin",
        "kind": "audit-anchor-only-stand-in",
        "canonical_artefact": "tests/ci/test_welle_2_audit_anchor_tag70.py",
    },
    "welle_3_integration_smoke": {
        "tag": "tag-71",
        "owner": "Amara",
        "kind": "integration-smoke-aggregator",
        "canonical_artefact": "tooling/ci/aggregate_welle_3_integration.py",
    },
    "welle_4_integration_smoke": {
        "tag": "tag-72",
        "owner": "Amara",
        "kind": "integration-smoke-aggregator",
        "canonical_artefact": "tooling/ci/aggregate_welle_4_integration.py",
    },
    "welle_5_integration_smoke": {
        "tag": "tag-73",
        "owner": "Amara",
        "kind": "integration-smoke-aggregator",
        "canonical_artefact": "tooling/ci/aggregate_welle_5_integration.py",
    },
    "welle_6_integration_smoke": {
        "tag": "tag-74",
        "owner": "Amara",
        "kind": "integration-smoke-aggregator",
        "canonical_artefact": "tooling/ci/aggregate_welle_6_integration.py",
    },
    "welle_7_integration_smoke": {
        "tag": "tag-75",
        "owner": "Amara",
        "kind": "integration-smoke-aggregator-terminal-final-sealing",
        "canonical_artefact": "tooling/ci/aggregate_welle_7_integration.py",
    },
    "cross_welle_stability_pin": {
        "tag": "tag-76",
        "owner": "Amara",
        "kind": "cross-welle-stability-aggregator",
        "canonical_artefact": "tooling/ci/aggregate_cross_welle_stability.py",
    },
    "marathon_closeout_aggregator": {
        "tag": "tag-76",
        "owner": "Reza",
        "kind": "marathon-closeout-verifier-family-bundler",
        "canonical_artefact": "tooling/audit/verify_marathon_closeout.py",
    },
    "phase_3_complete_marker_audit_bundle": {
        "tag": "tag-76",
        "owner": "Tomas",
        "kind": "phase-3-complete-marker-producer-envelope",
        "canonical_artefact": "tooling/ci/wire_phase_3_complete_audit_bundle.py",
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "seven_integration_smokes_framing": {
        "brief_value": (
            "Stage 1..7: alle 7 Welle-Integration-Smokes "
            "(Welle-1..7) zu einem konsolidierten Marathon-Final-"
            "Smoke-E2E"
        ),
        "canonical_value": (
            "five Welle-Integration-Smoke aggregators exist on main "
            "as of Tag-77 (Welle-3..Welle-7, Tag-71..Tag-75); "
            "Welle-1 (Tag-69) and Welle-2 (Tag-70) have audit-"
            "anchor-only wiring without dedicated integration-smoke "
            "aggregators"
        ),
        "canonical_source": (
            "main-tip git ls-tree: tooling/ci/aggregate_welle_"
            "[3-7]_integration.py + tests/ci/test_welle_[1,2]_"
            "audit_anchor_tag[69,70].py"
        ),
        "resolution": (
            "Tag-77 aggregator accepts seven per-Welle envelopes for "
            "completeness; Welle-1/2 envelopes are flagged as audit-"
            "anchor-derived stand-ins in stage_provenance"
        ),
    },
    "closeout_vs_complete_marker_distinct_substrates": {
        "brief_value": (
            "Stage 9: Marathon-Closeout-Aggregator + Stage 10: "
            "Phase-3-COMPLETE-Marker-Audit-Bundle"
        ),
        "canonical_value": (
            "Two distinct Tag-76 substrates: Reza Marathon-Closeout-"
            "Aggregator (PR #479, MARATHON-CLOSEOUT-READY / PARTIAL "
            "/ DEFECT trinary surface over the seven Final-Sealing-"
            "Verifier outcomes) vs Tomas Phase-3-COMPLETE-Marker-"
            "Audit-Bundle (PR #484, BUNDLE-READY / BUNDLE-PARTIAL "
            "/ BUNDLE-DEFECT trinary surface over the Welle-1..7-"
            "Kind-Disjointness-Pin)"
        ),
        "canonical_source": (
            "tooling/audit/verify_marathon_closeout.py compute_"
            "verdict (Reza Tag-76 #479); "
            "tooling/ci/wire_phase_3_complete_audit_bundle.py "
            "build_envelope (Tomas Tag-76 #484)"
        ),
        "resolution": (
            "Tag-77 surfaces both as separate stages with distinct "
            "envelope shapes and distinct verdict maps; no re-"
            "implementation; verdict-string read-only"
        ),
    },
    "anti_pattern_anchor_ap_9": {
        "brief_value": (
            "Cascade-Topologie per phase-3-marathon-anti-patterns.md "
            "AP-9"
        ),
        "canonical_value": (
            "AP-9 is the Welle-3-Rollback-Cascade anchor; the "
            "(3,4,5,6,7) tuple is Welle-3-specific. The full "
            "cross-Welle cascade topology including Welle-4..7 "
            "forward-block-sets is consumed by Tag-77 only "
            "indirectly via the Stage-8 Cross-Welle-Stability-Pin "
            "envelope (Amara PR #483); Tag-77 does NOT re-verify "
            "the cascade pattern (Stage 8 already does)"
        ),
        "canonical_source": (
            "docs/quality-gates/phase-3-marathon-anti-patterns.md "
            "§AP-9 + decisions/0066-*.md §Beschluss + Tag-76 Cross-"
            "Welle-Stability-Pin envelope ``cascade_verification`` "
            "sub-field"
        ),
        "resolution": (
            "Tag-77 inherits the cascade-verification result via "
            "the Stage-8 envelope verdict (CROSS-WELLE-STABILITY-"
            "INTACT consumes a green cascade); the per-Welle "
            "envelope downstream_cascade tuples are read-only at "
            "this layer (Stage 8 verified them already)"
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
    """Apply the Tag-77 umbrella decision rule.

    Trinary mirroring the per-Welle pattern: any red collapses to
    DEFECT; any yellow degrades to DRIFT; all green yields INTACT.
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


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated Tag-77 Marathon-Final-Smoke envelope."""
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

    per_welle_inputs = {
        f"welle_{n}": (
            envelopes[f"welle_{n}_integration_smoke"].get("verdict")
            if envelopes.get(f"welle_{n}_integration_smoke") is not None
            else None
        )
        for n in range(1, 8)
    }

    closeout_substrate_verdicts = {
        stage: (
            envelopes[stage].get("verdict")
            if envelopes.get(stage) is not None
            else None
        )
        for stage in (
            "cross_welle_stability_pin",
            "marathon_closeout_aggregator",
            "phase_3_complete_marker_audit_bundle",
        )
    }

    return {
        "schema_version": 1,
        "workflow": "marathon-final-smoke-e2e",
        "tag": "tag-77",
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
        "per_welle_run_order_anchors": {
            str(k): v for k, v in PER_WELLE_RUN_ORDER_ANCHORS.items()
        },
        "stage_provenance": dict(STAGE_PROVENANCE),
        "per_welle_input_verdicts": per_welle_inputs,
        "closeout_substrate_verdicts": closeout_substrate_verdicts,
        "window": {
            "iso_week": iso_week,
            "marathon_iso_weeks": [24, 25, 26, 27],
            "in_marathon_window": (
                iso_week in (24, 25, 26, 27) if iso_week else False
            ),
        },
        "decision_rule": {
            "intact": (
                "all ten stage inputs green: seven Wellen INTACT + "
                "Cross-Welle-Stability INTACT + Marathon-Closeout "
                "READY + Phase-3-COMPLETE-Marker-Audit-Bundle READY"
            ),
            "drift": (
                "at least one stage yellow, zero red. Operator-hand "
                "reads per-stage notes before next live Welle / "
                "closeout trigger"
            ),
            "defect": (
                "at least one stage red, OR any envelope missing, "
                "OR unknown verdict surfaces, OR malformed envelope"
            ),
        },
        "brief_vs_canonical_reconciliation": BRIEF_VS_CANONICAL_RECONCILIATION,
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_dispatch": True,
            "no_gh_workflow_run": True,
            "no_marker_emission": True,
            "no_closeout_signing": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
        "umbrella_role": {
            "tag_77_role": (
                "thinnest roll-up over Tag-76 substrates "
                "(Cross-Welle-Stability + Marathon-Closeout + "
                "Phase-3-COMPLETE-Marker-Audit-Bundle); no "
                "substrate-decisions re-implemented"
            ),
            "consumes_read_only": [
                "tooling/ci/aggregate_cross_welle_stability.py "
                "(Amara Tag-76 #483)",
                "tooling/audit/verify_marathon_closeout.py "
                "(Reza Tag-76 #479)",
                "tooling/ci/wire_phase_3_complete_audit_bundle.py "
                "(Tomas Tag-76 #484)",
                "tooling/ci/aggregate_welle_[3-7]_integration.py "
                "(Amara Tag-71..Tag-75)",
            ],
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_marathon_final_smoke",
        description=(
            "Aggregate the seven Welle-N-Integration-Smoke "
            "envelopes (Welle-1..7) + the Cross-Welle-Stability-"
            "Pin envelope + the Marathon-Closeout-Aggregator "
            "envelope + the Phase-3-COMPLETE-Marker-Audit-Bundle "
            "envelope into a single Tag-77 MARATHON-FINAL verdict "
            "for the Phase-3c-Marathon-Polish pipeline simulation."
        ),
    )
    for n in range(1, 8):
        p.add_argument(
            f"--welle-{n}-envelope",
            type=Path,
            default=None,
            help=(
                f"Path to Welle-{n} Integration-Smoke verdict "
                f"envelope JSON."
            ),
        )
    p.add_argument(
        "--cross-welle-stability-envelope",
        type=Path,
        default=None,
        help=(
            "Path to the Tag-76 Cross-Welle-Stability-Pin verdict "
            "envelope JSON (Amara PR #483)."
        ),
    )
    p.add_argument(
        "--marathon-closeout-envelope",
        type=Path,
        default=None,
        help=(
            "Path to the Tag-76 Marathon-Closeout-Aggregator "
            "verdict envelope JSON (Reza PR #479)."
        ),
    )
    p.add_argument(
        "--phase-3-complete-bundle-envelope",
        type=Path,
        default=None,
        help=(
            "Path to the Tag-76 Phase-3-COMPLETE-Marker-Audit-"
            "Bundle verdict envelope JSON (Tomas PR #484)."
        ),
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
    envelopes: dict[str, dict[str, Any] | None] = {}
    for n in range(1, 8):
        envelope_arg = getattr(args, f"welle_{n}_envelope")
        envelopes[f"welle_{n}_integration_smoke"] = _load_envelope(envelope_arg)
    envelopes["cross_welle_stability_pin"] = _load_envelope(
        args.cross_welle_stability_envelope
    )
    envelopes["marathon_closeout_aggregator"] = _load_envelope(
        args.marathon_closeout_envelope
    )
    envelopes["phase_3_complete_marker_audit_bundle"] = _load_envelope(
        args.phase_3_complete_bundle_envelope
    )
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
