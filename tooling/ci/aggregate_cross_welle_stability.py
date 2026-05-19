#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-76 Cross-Welle-Stability-Pin verdict aggregator (Amara).

The Tag-76 Cross-Welle-Stability-Pin workflow bundles the seven
Welle-N-Integration-Smokes (Welle-1..Welle-7) into a single
consolidated Phase-3c-Marathon-Stability-Verdict. The aggregator
folds the seven per-Welle envelopes plus the Cross-Welle-Cascade-
Verifikation envelope into the trinary surface:

* ``CROSS-WELLE-STABILITY-INTACT`` -- all seven per-Welle inputs
  green and the cross-welle cascade-topology consistent (Forward-
  Block-Pattern + Reverse-Block-Pattern verified per AP-9 in
  ``docs/quality-gates/phase-3-marathon-anti-patterns.md`` AP-9 +
  the symmetric Doppel-Welle PAR-path couplings per ADR-0066).

* ``CROSS-WELLE-STABILITY-DRIFT`` -- at least one per-Welle input
  yellow OR the cascade-verification yellow, with zero red.
  Operator-hand reads the per-stage notes before the next live
  Welle trigger.

* ``CROSS-WELLE-STABILITY-DEFECT`` -- at least one per-Welle red,
  OR any per-Welle envelope missing / unparseable, OR the cascade-
  verification red (Forward / Reverse pattern violated).

Aggregator scope
----------------

The aggregator consumes EIGHT input envelopes:

* ``S1`` Welle-1-Integration-Smoke envelope (Tag-69 audit-anchor
  derived stand-in: Welle-1 has no dedicated integration-smoke
  aggregator on main as of Tag-76 -- see
  ``brief_vs_canonical_reconciliation``).

* ``S2`` Welle-2-Integration-Smoke envelope (Tag-70 audit-anchor
  derived stand-in -- same reconciliation surface).

* ``S3`` Welle-3-Integration-Smoke envelope (Tag-71 aggregator
  output; canonical).

* ``S4`` Welle-4-Integration-Smoke envelope (Tag-72 aggregator
  output; canonical).

* ``S5`` Welle-5-Integration-Smoke envelope (Tag-73 aggregator
  output; canonical).

* ``S6`` Welle-6-Integration-Smoke envelope (Tag-74 aggregator
  output; canonical).

* ``S7`` Welle-7-Integration-Smoke envelope (Tag-75 aggregator
  output; canonical).

* ``S8`` Cross-Welle-Cascade-Verifikation envelope (Tag-76
  distinctive substrate; verifies the Forward-Block + Reverse-
  Block patterns hold across the seven Welle-aggregators).

Cross-Welle-Cascade-Verifikation (Stage 8, Tag-76 distinctive)
---------------------------------------------------------------

Per AP-9 in ``docs/quality-gates/phase-3-marathon-anti-patterns.md``
the Welle-3 rollback cascade-set is ``(3, 4, 5, 6, 7)`` (forward-
block-pattern: a Welle-3 DEFECT MUST yield ``blocked_wellen=
(3,4,5,6,7)``; non-Welle-3 rollback MUST NOT cascade backwards but
MUST still set ``marker_admissible=False``). Tag-76 verifies the
forward + reverse patterns hold across the seven per-Welle
aggregator outputs:

* **Forward-Block-Pattern** -- per-Welle ``downstream_cascade``
  surfaces declare canonical ``blocked_wellen_on_defect`` tuples
  per the AP-9 + ADR-0066 + Doppel-Welle PAR-path discipline:

  - Welle-1 forward-block = ``()``  (audit-anchor-only on main;
    no integration-smoke aggregator -- stand-in declares ``()``).
  - Welle-2 forward-block = ``()``  (same audit-anchor-only).
  - Welle-3 forward-block = ``(3, 4, 5, 6, 7)``  (AP-9 anchor
    Welle-3 Bridge-Audit-Writer rollback cascades).
  - Welle-4 forward-block = ``(4, 5, 6, 7)``  (Doppel-Welle-4+5
    + downstream).
  - Welle-5 forward-block = ``(5, 6, 7)``.
  - Welle-6 forward-block = ``(6, 7)``  (Doppel-Welle-6+7 PAR-
    path symmetry).
  - Welle-7 forward-block = ``(6, 7)``  (terminal Welle; same
    tuple as Welle-6 attesting symmetric coupling).

* **Reverse-Block-Pattern** -- the inverse: a downstream Welle
  DEFECT MUST NOT cascade backwards to upstream Wellen. The
  cascade-pattern verifier checks that for every per-Welle DEFECT
  the upstream Wellen are NOT in the block-set.

* **Doppel-Welle-Symmetry** -- the Welle-6 + Welle-7 forward-
  block tuples MUST be identical under PAR-path, attesting the
  symmetric coupling. The Welle-4 + Welle-5 tuples MUST differ
  (Welle-4 includes Welle-5 in cascade; Welle-5 does not include
  Welle-4 -- a one-way upstream-to-downstream coupling per the
  Welle-5 aggregator note).

Cascade-pattern verdict trinary surface:

* ``CASCADE-PATTERN-CONSISTENT`` (green) -- all forward + reverse
  patterns hold + Doppel-Welle symmetries attested.
* ``CASCADE-PATTERN-PARTIAL`` (yellow) -- minor drift (e.g.
  per-Welle envelope present but missing ``downstream_cascade``
  field; aggregator surfaces fallback canonical value).
* ``CASCADE-PATTERN-BROKEN`` (red) -- explicit Forward-Block-
  Pattern violation or Reverse-Block-Pattern violation or
  Doppel-Welle-Symmetry break.

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
signal; workflow-step decisioning is downstream of this helper.

Sandbox-boundary
----------------

stdlib only (``argparse``, ``json``, ``datetime``, ``pathlib``).
No network. No NATS. No SPIRE. No gRPC. No actual Welle dispatch.
The aggregator is hermetic-by-construction per Mira's Sandbox-vs-
Host-Operations Trennung and the Tag-76 Marathon-Closeout plan.

Continuous-Mode (Mira, 2026-05-19)
----------------------------------

Tag-76 is dispatched in the Cutover-Marathon Continuous-Mode
without per-trigger AR approval. The hermetic simulation is the
substrate; the workflow does NOT issue ``gh workflow run`` for
the seven underlying Welle-Integration-Smokes. Per
``feedback_continuous_mode_keine_pause_frage.md`` the workflow
runs to completion on its own without per-stage approvals; per
``feedback_continuous_mode_keine_push_frage.md`` the merge of
this PR is part of the Tag-76 Marathon-Closeout substrate-set
and happens automatically.

Brief-vs-canonical reconciliation (Tag-71+72+73+74+75 lehre)
------------------------------------------------------------

The Tag-76 Auftrag brief was largely canonical-aligned. Three
reconciliations surface for the audit trail:

* Brief framing: "die 7 Welle-Integration-Smokes". Canonical:
  five Welle-Integration-Smoke aggregators exist on main as of
  Tag-76 (Welle-3..Welle-7); Welle-1 and Welle-2 have audit-
  anchor wiring (Tag-69 / Tag-70) but no dedicated integration-
  smoke aggregator. The Tag-76 aggregator surfaces both
  framings: it accepts seven envelopes for completeness, treats
  Welle-1 + Welle-2 envelopes as audit-anchor-derived stand-ins,
  and surfaces the stand-in flag in
  ``per_welle_envelope_provenance``.

* Brief framing: ``pre-cutover-acceptance-run-order.md §3`` 7
  Welle-Datumsanker. Per-Welle aggregators carry per-Welle
  iso_cutover_date constants (e.g. Welle-3 aggregator anchors
  2026-06-12 KW-24; run-order doc §3 anchors Welle-3 to
  2026-06-17 KW-25). Tag-76 surfaces the run-order-doc §3 view
  as canonical for the cross-welle date-axis (the doc is the
  cross-Welle sequencing contract; per-Welle aggregators are
  per-Welle-substrate-views).

* Brief cited ``phase-3-marathon-anti-patterns.md AP-9 (3,4,5,6,7)``
  cascade-topology. Canonical: AP-9 is the Welle-3-Rollback-
  Cascade anchor; the (3,4,5,6,7) tuple is the Welle-3-specific
  forward-block-set. Welle-4..7 forward-block-sets are derived
  from Doppel-Welle PAR-path discipline (ADR-0066) and per-Welle
  aggregator-pinned tuples. The aggregator surfaces all seven
  forward-block tuples in ``forward_cascade_topology``.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This module aggregates Welle-1..Welle-7 integration-smoke envelopes
for the Tag-76 Cross-Welle-Stability-Pin. It does NOT modify any
Welle-N substrate workflow, aggregator, or test-suite. It does NOT
re-derive per-Welle cascade tuples; it consumes them read-only
from the per-Welle envelopes (with canonical fallback values
declared in the aggregator for envelopes missing the
``downstream_cascade`` field).

Cross-Review-Markers
--------------------

* Zone-M: QA x Tomas / Selin / Henrik -- all seven per-Welle
  envelopes are inherited read-only from the Tag-69..Tag-75
  substrate-trio outputs.
* Zone-N: QA x Henrik -- the aggregated CROSS-WELLE envelope and
  the cascade-verification stage envelope are Audit-Evidence-
  Inputs for the Marathon-Closeout Audit-Bundle.
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

# Canonical order of the Tag-76 Cross-Welle aggregator inputs:
# the seven per-Welle integration-smoke envelopes followed by the
# cross-welle cascade-verification envelope. Order is strict-
# chronological by cutover-date across Welle-1..Welle-7 per
# docs/quality-gates/pre-cutover-acceptance-run-order.md §3.
STAGES: tuple[str, ...] = (
    "welle_1_integration_smoke",
    "welle_2_integration_smoke",
    "welle_3_integration_smoke",
    "welle_4_integration_smoke",
    "welle_5_integration_smoke",
    "welle_6_integration_smoke",
    "welle_7_integration_smoke",
    "cross_welle_cascade_verification",
)


# ---- Per-stage verdict-to-status mapping ---------------------------------

# Welle-N aggregator emits WELLE-N-INTACT / -DRIFT / -DEFECT.
def _welle_n_map(n: int) -> dict[str, str]:
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

CASCADE_VERIFICATION_VERDICT_MAP: dict[str, str] = {
    "CASCADE-PATTERN-CONSISTENT": "green",
    "CASCADE-PATTERN-PARTIAL": "yellow",
    "CASCADE-PATTERN-BROKEN": "red",
}

STAGE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "welle_1_integration_smoke": WELLE_1_VERDICT_MAP,
    "welle_2_integration_smoke": WELLE_2_VERDICT_MAP,
    "welle_3_integration_smoke": WELLE_3_VERDICT_MAP,
    "welle_4_integration_smoke": WELLE_4_VERDICT_MAP,
    "welle_5_integration_smoke": WELLE_5_VERDICT_MAP,
    "welle_6_integration_smoke": WELLE_6_VERDICT_MAP,
    "welle_7_integration_smoke": WELLE_7_VERDICT_MAP,
    "cross_welle_cascade_verification": CASCADE_VERIFICATION_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_INTACT: str = "CROSS-WELLE-STABILITY-INTACT"
VERDICT_DRIFT: str = "CROSS-WELLE-STABILITY-DRIFT"
VERDICT_DEFECT: str = "CROSS-WELLE-STABILITY-DEFECT"


# ---- Per-Welle canonical anchors -----------------------------------------

# Per docs/quality-gates/pre-cutover-acceptance-run-order.md §3 the
# canonical per-Welle Cutover-Mittwoch and Sign-off-Freitag dates
# are pinned as the cross-Welle sequencing contract. Per-Welle
# aggregators (Tag-71..Tag-75) carry per-Welle-substrate-view
# dates that may differ from the cross-Welle sequencing-doc view;
# Tag-76 surfaces both axes.
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


# ---- Forward-cascade canonical topology ----------------------------------

# Per AP-9 + per-Welle aggregator pins (Tag-71..Tag-75), the
# canonical forward-block-set for each Welle. Tag-76 verifies
# per-Welle envelope downstream_cascade surfaces match these
# tuples (Forward-Block-Pattern).
FORWARD_CASCADE_TOPOLOGY: dict[int, tuple[int, ...]] = {
    1: (),
    2: (),
    3: (3, 4, 5, 6, 7),
    4: (4, 5, 6, 7),
    5: (5, 6, 7),
    6: (6, 7),
    7: (6, 7),
}


# ---- Doppel-Welle symmetry pairs -----------------------------------------

# Per ADR-0066 the Doppel-Welle pairs are (1,2), (4,5), (6,7).
# Tag-76 verifies the symmetric-coupling discipline:
#   (1,2) -- Doppel-Welle on KW-24 Mi; no integration-smoke
#            aggregator on main, audit-anchor-only.
#   (4,5) -- ASYMMETRIC coupling: Welle-4 forward-block includes
#            Welle-5; Welle-5 forward-block does NOT include
#            Welle-4 (one-way upstream-to-downstream per Welle-5
#            aggregator note).
#   (6,7) -- SYMMETRIC coupling: Welle-6 and Welle-7 forward-block
#            tuples are identical = (6, 7) under PAR-path.
DOPPEL_WELLE_PAIRS: tuple[tuple[int, int], ...] = (
    (1, 2),
    (4, 5),
    (6, 7),
)

DOPPEL_WELLE_SYMMETRY: dict[tuple[int, int], str] = {
    (1, 2): "audit-anchor-only-no-integration-smoke",
    (4, 5): "asymmetric-one-way-upstream-to-downstream",
    (6, 7): "symmetric-par-path-coupling",
}


# ---- Per-Welle envelope provenance ---------------------------------------

PER_WELLE_ENVELOPE_PROVENANCE: dict[int, dict[str, Any]] = {
    1: {
        "owner": "Tomas+Selin",
        "tag": "tag-69",
        "kind": "audit-anchor-only-stand-in",
        "integration_smoke_present": False,
        "aggregator_module": None,
        "audit_anchor_module": "tests/ci/test_welle_1_audit_anchor_tag69.py",
        "note": (
            "Welle-1 has audit-anchor wiring (Tag-69) but no "
            "dedicated integration-smoke aggregator on main as "
            "of Tag-76; Tag-76 accepts the audit-anchor-derived "
            "envelope as a stand-in."
        ),
    },
    2: {
        "owner": "Tomas+Selin",
        "tag": "tag-70",
        "kind": "audit-anchor-only-stand-in",
        "integration_smoke_present": False,
        "aggregator_module": None,
        "audit_anchor_module": "tests/ci/test_welle_2_audit_anchor_tag70.py",
        "note": (
            "Welle-2 has audit-anchor wiring (Tag-70) but no "
            "dedicated integration-smoke aggregator on main as "
            "of Tag-76; Tag-76 accepts the audit-anchor-derived "
            "envelope as a stand-in."
        ),
    },
    3: {
        "owner": "Amara",
        "tag": "tag-71",
        "kind": "integration-smoke-aggregator",
        "integration_smoke_present": True,
        "aggregator_module": "tooling/ci/aggregate_welle_3_integration.py",
        "audit_anchor_module": "tests/ci/test_welle_3_integration_tag71.py",
        "note": "Tag-71 Welle-3 integration-smoke aggregator (canonical).",
    },
    4: {
        "owner": "Amara",
        "tag": "tag-72",
        "kind": "integration-smoke-aggregator",
        "integration_smoke_present": True,
        "aggregator_module": "tooling/ci/aggregate_welle_4_integration.py",
        "audit_anchor_module": "tests/ci/test_welle_4_integration_tag72.py",
        "note": "Tag-72 Welle-4 integration-smoke aggregator (canonical).",
    },
    5: {
        "owner": "Amara",
        "tag": "tag-73",
        "kind": "integration-smoke-aggregator",
        "integration_smoke_present": True,
        "aggregator_module": "tooling/ci/aggregate_welle_5_integration.py",
        "audit_anchor_module": "tests/ci/test_welle_5_integration_tag73.py",
        "note": "Tag-73 Welle-5 integration-smoke aggregator (canonical).",
    },
    6: {
        "owner": "Amara",
        "tag": "tag-74",
        "kind": "integration-smoke-aggregator",
        "integration_smoke_present": True,
        "aggregator_module": "tooling/ci/aggregate_welle_6_integration.py",
        "audit_anchor_module": "tests/ci/test_welle_6_integration_tag74.py",
        "note": "Tag-74 Welle-6 integration-smoke aggregator (canonical).",
    },
    7: {
        "owner": "Amara",
        "tag": "tag-75",
        "kind": "integration-smoke-aggregator",
        "integration_smoke_present": True,
        "aggregator_module": "tooling/ci/aggregate_welle_7_integration.py",
        "audit_anchor_module": "tests/ci/test_welle_7_integration_tag75.py",
        "note": (
            "Tag-75 Welle-7 integration-smoke aggregator "
            "(canonical, terminal Welle, Final-Sealing)."
        ),
    },
}


# ---- Brief-vs-canonical reconciliation -----------------------------------

BRIEF_VS_CANONICAL_RECONCILIATION: dict[str, dict[str, str]] = {
    "seven_integration_smokes_framing": {
        "brief_value": (
            "die 7 Welle-Integration-Smokes (Welle-1..7) zu einem "
            "konsolidierten Phase-3c-Marathon-Stability-Verdict "
            "buendeln"
        ),
        "canonical_value": (
            "five Welle-Integration-Smoke aggregators exist on main "
            "as of Tag-76 (Welle-3..Welle-7, Tag-71..Tag-75); "
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
            "Tag-76 aggregator accepts seven per-Welle envelopes for "
            "completeness; Welle-1/2 envelopes are flagged as audit-"
            "anchor-derived stand-ins in per_welle_envelope_"
            "provenance; both framings surface on the envelope"
        ),
    },
    "welle_datumsanker_authority": {
        "brief_value": (
            "7 Welle-Datumsanker per pre-cutover-acceptance-run-"
            "order.md §3"
        ),
        "canonical_value": (
            "pre-cutover-acceptance-run-order.md §3 is the cross-"
            "Welle sequencing contract (authoritative for Tag-76 "
            "cross-Welle date-axis); per-Welle aggregators carry "
            "per-Welle-substrate-view dates that may differ (e.g. "
            "Welle-3 aggregator pins 2026-06-12 KW-24 while §3 pins "
            "2026-06-17 KW-25 for Welle-3)"
        ),
        "canonical_source": (
            "docs/quality-gates/pre-cutover-acceptance-run-order.md "
            "§3 vs tooling/ci/aggregate_welle_3_integration.py "
            "WELLE_3_ISO_DATE"
        ),
        "resolution": (
            "pre-cutover-acceptance-run-order.md §3 canonical for "
            "Tag-76 cross-Welle date-axis; per-Welle aggregator "
            "dates surface verbatim in per_welle_envelope_"
            "provenance as substrate-view evidence"
        ),
    },
    "cascade_topology_authority": {
        "brief_value": (
            "Cascade-Topologie per phase-3-marathon-anti-patterns.md "
            "AP-9 (3,4,5,6,7)"
        ),
        "canonical_value": (
            "AP-9 is the Welle-3-Rollback-Cascade anchor; the "
            "(3,4,5,6,7) tuple is Welle-3-specific. Welle-4..7 "
            "forward-block-sets are derived from Doppel-Welle PAR-"
            "path discipline (ADR-0066) and per-Welle aggregator "
            "pins. Tag-76 surfaces all seven forward-block tuples "
            "in forward_cascade_topology and verifies them against "
            "the per-Welle envelope downstream_cascade surfaces"
        ),
        "canonical_source": (
            "docs/quality-gates/phase-3-marathon-anti-patterns.md "
            "§AP-9 + decisions/0066-*.md §Beschluss + per-Welle "
            "aggregator FORWARD_CASCADE_BLOCKED_WELLEN_ON_DEFECT "
            "constants (Tag-71..Tag-75)"
        ),
        "resolution": (
            "full cascade-topology pinned in FORWARD_CASCADE_"
            "TOPOLOGY dict (Welle-1..7); Stage-8 cascade-pattern "
            "verifier checks per-Welle envelopes match canonical "
            "tuples; Doppel-Welle symmetry checked for (1,2), (4,5), "
            "(6,7)"
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
    """Apply the Tag-76 decision rule.

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


def verify_forward_block_pattern(
    envelopes: Mapping[str, Mapping[str, Any] | None],
) -> tuple[bool, list[str]]:
    """Check per-Welle envelopes carry canonical forward-block tuples.

    Returns ``(consistent, drift_notes)``. A per-Welle envelope
    missing a ``downstream_cascade.blocked_wellen_on_defect`` field
    is a drift (not a break); an envelope carrying a tuple
    differing from the canonical tuple is a break.
    """
    drift_notes: list[str] = []
    consistent = True
    for welle in range(1, 8):
        stage_key = f"welle_{welle}_integration_smoke"
        env = envelopes.get(stage_key)
        canonical = FORWARD_CASCADE_TOPOLOGY[welle]
        if env is None:
            drift_notes.append(
                f"welle-{welle}: envelope missing, fallback to "
                f"canonical tuple {canonical}"
            )
            continue
        downstream = env.get("downstream_cascade")
        if not isinstance(downstream, Mapping):
            drift_notes.append(
                f"welle-{welle}: envelope has no downstream_cascade "
                f"field, fallback to canonical tuple {canonical}"
            )
            continue
        observed_raw = downstream.get("blocked_wellen_on_defect")
        if not isinstance(observed_raw, list):
            drift_notes.append(
                f"welle-{welle}: downstream_cascade.blocked_wellen_"
                f"on_defect is not a list, fallback to canonical "
                f"tuple {canonical}"
            )
            continue
        observed = tuple(int(x) for x in observed_raw if isinstance(x, int))
        if observed != canonical:
            consistent = False
            drift_notes.append(
                f"welle-{welle}: forward-block tuple drift, observed="
                f"{observed} canonical={canonical} (FORWARD-BLOCK-"
                f"PATTERN-VIOLATION)"
            )
    return consistent, drift_notes


def verify_doppel_welle_symmetry() -> tuple[bool, list[str]]:
    """Check the Doppel-Welle symmetry discipline holds.

    Returns ``(consistent, drift_notes)``. The symmetry assertions
    are hardcoded against the FORWARD_CASCADE_TOPOLOGY dict
    constants (Tag-71..Tag-75 anchors).
    """
    drift_notes: list[str] = []
    consistent = True
    # (6,7) MUST be symmetric: Welle-6 tuple == Welle-7 tuple.
    if FORWARD_CASCADE_TOPOLOGY[6] != FORWARD_CASCADE_TOPOLOGY[7]:
        consistent = False
        drift_notes.append(
            f"doppel-welle (6,7): symmetric PAR-path coupling broken, "
            f"welle-6={FORWARD_CASCADE_TOPOLOGY[6]} != "
            f"welle-7={FORWARD_CASCADE_TOPOLOGY[7]}"
        )
    # (4,5) MUST be asymmetric: Welle-4 contains Welle-5; Welle-5
    # MUST NOT contain Welle-4 (one-way upstream-to-downstream).
    if 5 not in FORWARD_CASCADE_TOPOLOGY[4]:
        consistent = False
        drift_notes.append(
            f"doppel-welle (4,5): asymmetric coupling broken, "
            f"welle-5 not in welle-4 forward-block-set "
            f"welle-4={FORWARD_CASCADE_TOPOLOGY[4]}"
        )
    if 4 in FORWARD_CASCADE_TOPOLOGY[5]:
        consistent = False
        drift_notes.append(
            f"doppel-welle (4,5): asymmetric coupling broken, "
            f"welle-4 IS in welle-5 forward-block-set "
            f"welle-5={FORWARD_CASCADE_TOPOLOGY[5]} (backwards-"
            f"cascade VIOLATION)"
        )
    # (1,2) audit-anchor-only: both tuples MUST be empty.
    if FORWARD_CASCADE_TOPOLOGY[1] != () or FORWARD_CASCADE_TOPOLOGY[2] != ():
        consistent = False
        drift_notes.append(
            f"doppel-welle (1,2): audit-anchor-only discipline "
            f"broken, expected empty tuples, "
            f"welle-1={FORWARD_CASCADE_TOPOLOGY[1]} "
            f"welle-2={FORWARD_CASCADE_TOPOLOGY[2]}"
        )
    return consistent, drift_notes


def verify_reverse_block_pattern() -> tuple[bool, list[str]]:
    """Check no per-Welle forward-block-set contains upstream Wellen.

    A downstream Welle DEFECT MUST NOT block upstream Wellen. For
    each Welle-N, the tuple MUST contain only entries >= N --
    EXCEPT for symmetric Doppel-Welle PAR-path partners. Per
    ADR-0066 + phase-3c-doppel-welle-6-7.md the (6,7) pair carries
    a symmetric coupling: a Welle-7 DEFECT blocks Welle-6 (its
    PAR-path partner that ran in the same Cutover-Mittwoch). This
    is the documented exception to the reverse-block-pattern.
    The exception applies ONLY to Wellen whose Doppel-Welle partner
    is the immediately-preceding Welle (partner == welle - 1) under
    the symmetric-par-path-coupling kind.
    """
    drift_notes: list[str] = []
    consistent = True
    for welle in range(1, 8):
        canonical = FORWARD_CASCADE_TOPOLOGY[welle]
        partner = PER_WELLE_RUN_ORDER_ANCHORS[welle].get("doppel_partner")
        # Symmetric-PAR-path exception: if the partner is the
        # immediately-preceding Welle AND the symmetry kind is
        # symmetric-par-path-coupling, allow that partner in the
        # forward-block tuple as documented Doppel-Welle coupling.
        symmetric_exception: set[int] = set()
        if isinstance(partner, int) and partner == welle - 1:
            pair = (partner, welle)
            sym_kind = DOPPEL_WELLE_SYMMETRY.get(pair)
            if sym_kind == "symmetric-par-path-coupling":
                symmetric_exception.add(partner)
        upstream_violations = [
            w for w in canonical if w < welle and w not in symmetric_exception
        ]
        if upstream_violations:
            consistent = False
            drift_notes.append(
                f"welle-{welle}: REVERSE-BLOCK-PATTERN-VIOLATION; "
                f"upstream entries {upstream_violations} present in "
                f"forward-block-set {canonical}"
            )
    return consistent, drift_notes


def derive_cascade_pattern_verdict(
    envelopes: Mapping[str, Mapping[str, Any] | None],
) -> tuple[str, list[str]]:
    """Compute the Stage-8 cascade-pattern verdict.

    Combines forward-block, reverse-block, and Doppel-Welle
    symmetry checks into a single trinary verdict.
    """
    notes: list[str] = []
    fwd_consistent, fwd_notes = verify_forward_block_pattern(envelopes)
    rev_consistent, rev_notes = verify_reverse_block_pattern()
    sym_consistent, sym_notes = verify_doppel_welle_symmetry()
    notes.extend(fwd_notes)
    notes.extend(rev_notes)
    notes.extend(sym_notes)
    if not (fwd_consistent and rev_consistent and sym_consistent):
        return "CASCADE-PATTERN-BROKEN", notes
    if fwd_notes:
        # Forward-block notes without a break = drift (e.g.
        # envelope missing or field missing, fallback to
        # canonical).
        return "CASCADE-PATTERN-PARTIAL", notes
    return "CASCADE-PATTERN-CONSISTENT", notes


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated Tag-76 Cross-Welle-Stability envelope."""
    # Stage-8 cascade-pattern verdict is computed from the per-Welle
    # envelopes themselves; if no explicit Stage-8 envelope is
    # supplied, the aggregator synthesises one in-memory.
    cascade_env = envelopes.get("cross_welle_cascade_verification")
    cascade_synthesised = False
    if cascade_env is None:
        cascade_verdict, cascade_notes = derive_cascade_pattern_verdict(envelopes)
        cascade_env = {
            "schema_version": 1,
            "stage": "cross_welle_cascade_verification",
            "tag": "tag-76",
            "verdict": cascade_verdict,
            "notes": cascade_notes,
            "synthesised": True,
        }
        cascade_synthesised = True

    envelopes_with_cascade = dict(envelopes)
    envelopes_with_cascade["cross_welle_cascade_verification"] = cascade_env

    steps: dict[str, str] = {}
    per_note: dict[str, str] = {}
    for stage in STAGES:
        status, note = _normalise_status(stage, envelopes_with_cascade.get(stage))
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
            envelopes_with_cascade[f"welle_{n}_integration_smoke"].get("verdict")
            if envelopes_with_cascade.get(f"welle_{n}_integration_smoke")
            is not None
            else None
        )
        for n in range(1, 8)
    }

    return {
        "schema_version": 1,
        "workflow": "cross-welle-stability-pin",
        "tag": "tag-76",
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
        "per_welle_envelope_provenance": {
            str(k): v for k, v in PER_WELLE_ENVELOPE_PROVENANCE.items()
        },
        "per_welle_input_verdicts": per_welle_inputs,
        "forward_cascade_topology": {
            str(k): list(v) for k, v in FORWARD_CASCADE_TOPOLOGY.items()
        },
        "doppel_welle_pairs": [list(p) for p in DOPPEL_WELLE_PAIRS],
        "doppel_welle_symmetry": {
            f"{a}_{b}": kind for (a, b), kind in DOPPEL_WELLE_SYMMETRY.items()
        },
        "cascade_verification": {
            "stage_verdict": cascade_env.get("verdict"),
            "stage_synthesised": cascade_synthesised,
            "notes": cascade_env.get("notes", []),
            "rule": (
                "Cross-Welle-Cascade-Verifikation aggregates forward-"
                "block-pattern (per-Welle envelope downstream_cascade "
                "tuples vs canonical FORWARD_CASCADE_TOPOLOGY), "
                "reverse-block-pattern (no upstream entries in "
                "forward-block-set), and Doppel-Welle-Symmetry "
                "((6,7) symmetric PAR-path; (4,5) asymmetric; (1,2) "
                "audit-anchor-only empty tuples)"
            ),
            "anchor_doc": (
                "docs/quality-gates/phase-3-marathon-anti-patterns.md "
                "§AP-9 + decisions/0066-*.md §Beschluss"
            ),
        },
        "window": {
            "iso_week": iso_week,
            "marathon_iso_weeks": [24, 25, 26, 27],
            "in_marathon_window": (
                iso_week in (24, 25, 26, 27) if iso_week else False
            ),
        },
        "decision_rule": {
            "intact": (
                "all seven per-Welle inputs green AND cross-welle "
                "cascade-verification green"
            ),
            "drift": (
                "at least one per-Welle yellow OR cascade-"
                "verification yellow, zero red"
            ),
            "defect": (
                "at least one per-Welle red, OR any per-Welle "
                "envelope missing, OR cascade-verification red "
                "(Forward / Reverse pattern violated, OR Doppel-"
                "Welle-Symmetry break)"
            ),
        },
        "brief_vs_canonical_reconciliation": BRIEF_VS_CANONICAL_RECONCILIATION,
        "sandbox_boundary": {
            "stdlib_only": True,
            "no_network_io": True,
            "no_actual_welle_dispatch": True,
            "no_gh_workflow_run": True,
            "boundary_anchor": "feedback_sandbox_host_trennung.md",
        },
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_cross_welle_stability",
        description=(
            "Aggregate the seven Welle-N-Integration-Smoke "
            "envelopes (Welle-1..7) + the Cross-Welle-Cascade-"
            "Verifikation envelope into a single Tag-76 CROSS-"
            "WELLE-STABILITY verdict for the Phase-3c-Marathon-"
            "Closeout pipeline simulation."
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
        "--cascade-envelope",
        type=Path,
        default=None,
        help=(
            "Optional Cross-Welle-Cascade-Verifikation envelope "
            "JSON; if absent the aggregator synthesises one from "
            "the per-Welle envelopes."
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
    envelopes["cross_welle_cascade_verification"] = _load_envelope(
        args.cascade_envelope
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
