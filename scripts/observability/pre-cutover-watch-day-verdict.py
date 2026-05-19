#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pre-Cutover Watch-Day Verdict Computer (Tag-54).

Context
-------

Tag-54 ships ``docs/observability/pre-cutover-watch-day-spec.md``,
the operator playbook for the calendar day immediately before any
Welle-Cutover-Mittwoch per ADR-0066 cutover-plan. The spec defines:

* The activation-checklist (10 dashboards D1..D10, 2 alert-rule
  groups A1..A2, per-Welle probe-verdicts P1, 2 CI gates C1..C2).
* The six-slot Watch-Day procedure (08:00..18:00 CEST).
* The deterministic Watch-Day-Verdict formula at slot=16.

This module is the **pure-function reference implementation** of
the §7 verdict-formula plus the §10 journal-entry schema. It is
*not* a runtime daemon; the Watch-Day operator executes the
procedure by hand and invokes this module to compute the verdict
from inputs gathered during the shift.

The decoupling matters: the verdict-formula is the contract; this
module is the executable contract; the spec is the human-readable
contract. Hermetic tests pin all three to the same truth.

Anchor: Tag-54 Noa-SRE Pre-Cutover-Watch-Day-Spec.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

# Activation-checklist identifiers per spec §3.
DASHBOARD_IDS: tuple[str, ...] = (
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
)
ALERT_GROUP_IDS: tuple[str, ...] = ("A1", "A2")
CI_GATE_IDS: tuple[str, ...] = ("C1", "C2")

VERDICT_GREEN = "GREEN"
VERDICT_AMBER = "AMBER"
VERDICT_RED = "RED"
ALL_VERDICTS: tuple[str, ...] = (VERDICT_GREEN, VERDICT_AMBER, VERDICT_RED)

# Probe-verdict values (per Welle).
PROBE_GREEN = "GREEN"
PROBE_AMBER = "AMBER"
PROBE_RED = "RED"
ALL_PROBE_VERDICTS: tuple[str, ...] = (PROBE_GREEN, PROBE_AMBER, PROBE_RED)

# Hard-zero SLO identifiers (Tag-52). Burn-rate alert on any of these
# is an immediate cutover-blocker per spec §5.2.
HARD_ZERO_SLOS: frozenset[str] = frozenset(
    {"SLO-2", "SLO-5", "SLO-6", "SLO-7"}
)

# Welle-specific SLO. Fast-burn for a tomorrow-cutover-Welle is a
# direct cutover-blocker per spec §5.2.
WELLE_SLO = "SLO-1"

# Required slot identifiers (spec §4).
ALL_SLOTS: tuple[str, ...] = ("08", "10", "12", "14", "16", "18")

# Verdict-bearing slots.
VERDICT_SLOTS: tuple[str, ...] = ("16", "18")

# Required journal-entry fields (spec §10).
REQUIRED_JOURNAL_FIELDS: tuple[str, ...] = (
    "slot",
    "timestamp_iso",
    "operator",
    "cutover_welle",
    "dashboards_pass_count",
    "dashboards_fail_count",
    "alerts_pass_count",
    "alerts_fail_count",
    "probes_pass_count",
    "probes_fail_count",
    "ci_gate_c1",
    "ci_gate_c2",
    "verdict",
    "notes",
)


# ---------------------------------------------------------------------------
# Pure data structures.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class WatchDayInputs:
    """Operator-gathered Watch-Day evidence for the slot=16 verdict.

    All fields reflect the state of the cutover-target environment
    on the Watch-Day, *not* historical data. Each field maps 1:1
    to a row in spec §3 activation-checklist.
    """

    # §3.1 Dashboards: maps D1..D10 -> True (rendered, panels OK)
    # or False (any failure).
    dashboards: dict[str, bool]

    # §3.2 Alert-rule groups: maps A1..A2 -> True (promtool 0
    # AND loaded AND evaluable) or False.
    alert_groups: dict[str, bool]

    # §3.3 Per-Welle pre-cutover-probe verdicts. Keys are Welle ids
    # (e.g. "welle-1"); values are GREEN / AMBER / RED.
    probe_verdicts: dict[str, str]

    # §3.4 CI gates. Maps C1, C2 -> True (success in trailing 24h)
    # or False.
    ci_gates: dict[str, bool]

    # Currently firing SLO burn-rate alerts. Each entry is the SLO
    # identifier (e.g. "SLO-1", "SLO-5"). Empty set means no
    # burn-rate alert firing.
    firing_slo_burn_rates: frozenset[str]

    # Set of Welle identifiers scheduled for tomorrow's cutover
    # (e.g. {"welle-1", "welle-2"}). Used to gate SLO-1 fast-burn
    # logic against the actually-cutover Welles.
    tomorrow_cutover_welles: frozenset[str]


# ---------------------------------------------------------------------------
# Verdict formula (spec §7).
# ---------------------------------------------------------------------------

def compute_verdict(inputs: WatchDayInputs) -> str:
    """Compute the Watch-Day-Verdict deterministically per spec §7.

    Returns one of GREEN / AMBER / RED. No "operator gut-feel"
    override; if the operator wants to override, that is an
    AR-Hand-Stop conversation per spec §6.1, not a verdict-flip
    via this function.
    """
    red_blockers = _red_blockers(inputs)
    if red_blockers:
        return VERDICT_RED

    if _is_green(inputs):
        return VERDICT_GREEN

    return VERDICT_AMBER


def red_blocker_reasons(inputs: WatchDayInputs) -> list[str]:
    """Return human-readable reasons the verdict is (or would be) RED.

    Empty list means no RED-blocker. Order is stable so reasons
    can be displayed in a deterministic UI / journal-notes field.
    """
    return _red_blockers(inputs)


def _red_blockers(inputs: WatchDayInputs) -> list[str]:
    reasons: list[str] = []

    # Red-blocker 1: any D-1 probe-verdict == RED.
    red_probes = sorted(
        welle
        for welle, verdict in inputs.probe_verdicts.items()
        if verdict == PROBE_RED
    )
    for welle in red_probes:
        reasons.append(f"probe-verdict-RED:{welle}")

    # Red-blocker 2: any hard-zero SLO burn-rate firing.
    hard_zero_firing = sorted(
        inputs.firing_slo_burn_rates & HARD_ZERO_SLOS
    )
    for slo in hard_zero_firing:
        reasons.append(f"hard-zero-slo-burn:{slo}")

    # Red-blocker 3: SLO-1 fast-burn AND any tomorrow-cutover-Welle
    # exists. SLO-1 is the per-Welle SLO; if it is firing while a
    # cutover-Welle is scheduled tomorrow, that is a direct blocker.
    if (
        WELLE_SLO in inputs.firing_slo_burn_rates
        and inputs.tomorrow_cutover_welles
    ):
        reasons.append(
            f"welle-slo-fast-burn-with-tomorrow-cutover:{WELLE_SLO}"
        )

    # Red-blocker 4: either CI gate missing / non-success.
    failed_gates = sorted(
        gate
        for gate in CI_GATE_IDS
        if not inputs.ci_gates.get(gate, False)
    )
    for gate in failed_gates:
        reasons.append(f"ci-gate-failed:{gate}")

    return reasons


def _is_green(inputs: WatchDayInputs) -> bool:
    """All §7 GREEN-conditions must hold."""
    # 1: every dashboard rendered.
    for dash_id in DASHBOARD_IDS:
        if not inputs.dashboards.get(dash_id, False):
            return False

    # 2: every alert-rule group loaded and evaluable.
    for ag_id in ALERT_GROUP_IDS:
        if not inputs.alert_groups.get(ag_id, False):
            return False

    # 3: every probe-verdict is GREEN (AMBER would drop to AMBER
    # verdict, RED would have hit a red-blocker already).
    for welle, verdict in inputs.probe_verdicts.items():
        if verdict != PROBE_GREEN:
            return False

    # 4: both CI gates GREEN.
    for gate in CI_GATE_IDS:
        if not inputs.ci_gates.get(gate, False):
            return False

    # 5: no hard-zero SLO firing.
    if inputs.firing_slo_burn_rates & HARD_ZERO_SLOS:
        return False

    # 6: no SLO-1 fast-burn with a tomorrow-cutover-Welle.
    if (
        WELLE_SLO in inputs.firing_slo_burn_rates
        and inputs.tomorrow_cutover_welles
    ):
        return False

    return True


# ---------------------------------------------------------------------------
# Activation-checklist coverage helpers.
# ---------------------------------------------------------------------------

def missing_dashboards(inputs: WatchDayInputs) -> list[str]:
    """Return dashboard-ids that did *not* render (sorted)."""
    return sorted(
        d for d in DASHBOARD_IDS if not inputs.dashboards.get(d, False)
    )


def missing_alert_groups(inputs: WatchDayInputs) -> list[str]:
    """Return alert-group-ids that did *not* load (sorted)."""
    return sorted(
        a for a in ALERT_GROUP_IDS if not inputs.alert_groups.get(a, False)
    )


def amber_probes(inputs: WatchDayInputs) -> list[str]:
    """Return Welle-ids whose probe-verdict is AMBER (sorted).

    AMBER probes do not auto-block but the operator notifies Mira
    per spec §4.5.
    """
    return sorted(
        welle
        for welle, v in inputs.probe_verdicts.items()
        if v == PROBE_AMBER
    )


# ---------------------------------------------------------------------------
# Journal-entry schema validation (spec §10).
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class JournalValidation:
    """Result of validating a single journal-entry JSON object."""

    ok: bool
    errors: tuple[str, ...]


def validate_journal_entry(entry: dict[str, Any]) -> JournalValidation:
    """Validate one journal-entry JSON object against spec §10.

    Returns a JournalValidation with ``ok`` False if any required
    field is missing or has the wrong type / value per spec.
    """
    errors: list[str] = []

    # All required fields present.
    for field in REQUIRED_JOURNAL_FIELDS:
        if field not in entry:
            errors.append(f"missing-field:{field}")

    if errors:
        return JournalValidation(ok=False, errors=tuple(errors))

    # Field-type / value checks.
    slot = entry["slot"]
    if slot not in ALL_SLOTS:
        errors.append(f"invalid-slot:{slot}")

    if not isinstance(entry["timestamp_iso"], str) or not entry["timestamp_iso"]:
        errors.append("invalid-timestamp_iso")

    if not isinstance(entry["operator"], str) or not entry["operator"]:
        errors.append("invalid-operator")

    if not isinstance(entry["cutover_welle"], list):
        errors.append("invalid-cutover_welle-type")

    for k in (
        "dashboards_pass_count", "dashboards_fail_count",
        "alerts_pass_count", "alerts_fail_count",
        "probes_pass_count", "probes_fail_count",
    ):
        v = entry[k]
        if not isinstance(v, int) or v < 0:
            errors.append(f"invalid-counter:{k}")

    for k in ("ci_gate_c1", "ci_gate_c2"):
        v = entry[k]
        if v not in ("success", "failure", "missing"):
            errors.append(f"invalid-ci-gate:{k}={v}")

    verdict = entry["verdict"]
    if slot in VERDICT_SLOTS:
        if verdict not in ALL_VERDICTS:
            errors.append(f"verdict-required-for-slot-{slot}")
    else:
        if verdict is not None:
            errors.append(f"verdict-must-be-null-for-slot-{slot}")

    if not isinstance(entry["notes"], str):
        errors.append("invalid-notes-type")

    return JournalValidation(ok=not errors, errors=tuple(errors))


def validate_journal_sequence(entries: Iterable[dict[str, Any]]) -> JournalValidation:
    """Validate the *sequence* of journal entries for one Watch-Day.

    Requirements per spec §4 + §10:

    * Exactly the six slots 08/10/12/14/16/18 appear, each once.
    * Slots appear in ascending order (08, 10, 12, 14, 16, 18).
    * Slot=16 and slot=18 carry a verdict; the slot=18 verdict
      equals the slot=16 verdict (slot=18 is the close-out
      re-confirmation per spec §4.6).
    """
    entries_list = list(entries)
    errors: list[str] = []

    # Per-entry validation first.
    for i, entry in enumerate(entries_list):
        v = validate_journal_entry(entry)
        if not v.ok:
            errors.append(f"entry-{i}:" + ",".join(v.errors))

    if errors:
        return JournalValidation(ok=False, errors=tuple(errors))

    # Sequence: exactly six slots in ascending order.
    slot_seq = [e["slot"] for e in entries_list]
    if slot_seq != list(ALL_SLOTS):
        errors.append(
            f"slot-sequence-mismatch:expected={list(ALL_SLOTS)},got={slot_seq}"
        )
        return JournalValidation(ok=False, errors=tuple(errors))

    # Verdict re-confirmation at slot=18.
    slot_16_entry = entries_list[4]
    slot_18_entry = entries_list[5]
    if slot_16_entry["verdict"] != slot_18_entry["verdict"]:
        errors.append(
            "verdict-reconfirmation-mismatch:"
            f"slot16={slot_16_entry['verdict']},"
            f"slot18={slot_18_entry['verdict']}"
        )

    return JournalValidation(ok=not errors, errors=tuple(errors))


# ---------------------------------------------------------------------------
# Escalation-class lookup (spec §6).
# ---------------------------------------------------------------------------

# Severity-class P (Page) and T (Ticket) triggers. The mapping is
# verbatim from spec §6.1 and §6.2.
ESCALATION_CLASSES: dict[str, str] = {
    "watch-day-verdict-red": "P",
    "ar-hand-stop-invoked": "P",
    "hard-zero-slo-breach": "P",
    "drift-type-a-kai-domain": "T",
    "drift-type-a-noa-domain": "T",
    "wat-pipeline-regression": "T",
    "drift-type-b-informational": "T",
}


def severity_class_for(trigger: str) -> str:
    """Return ``P`` (page) or ``T`` (ticket) for a known trigger.

    Raises ``KeyError`` for unknown triggers — by design; the
    spec §6 list is the closed set Noa escalates on. Anything
    outside that set is anti-eskalations-drift per spec §6.4.
    """
    return ESCALATION_CLASSES[trigger]


# ---------------------------------------------------------------------------
# CLI: read inputs from JSON file, emit verdict.
# ---------------------------------------------------------------------------

def _inputs_from_dict(d: dict[str, Any]) -> WatchDayInputs:
    return WatchDayInputs(
        dashboards=dict(d.get("dashboards", {})),
        alert_groups=dict(d.get("alert_groups", {})),
        probe_verdicts=dict(d.get("probe_verdicts", {})),
        ci_gates=dict(d.get("ci_gates", {})),
        firing_slo_burn_rates=frozenset(d.get("firing_slo_burn_rates", [])),
        tomorrow_cutover_welles=frozenset(d.get("tomorrow_cutover_welles", [])),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs",
        required=True,
        type=Path,
        help="Path to JSON file with watch-day inputs.",
    )
    parser.add_argument(
        "--out-verdict",
        type=Path,
        default=None,
        help="Optional path to write the one-line verdict file.",
    )
    args = parser.parse_args(argv)

    data = json.loads(args.inputs.read_text(encoding="utf-8"))
    inputs = _inputs_from_dict(data)
    verdict = compute_verdict(inputs)
    reasons = red_blocker_reasons(inputs)

    print(f"verdict={verdict}")
    if reasons:
        for r in reasons:
            print(f"red-blocker:{r}")

    if args.out_verdict:
        args.out_verdict.write_text(verdict + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
