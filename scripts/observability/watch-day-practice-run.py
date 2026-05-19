#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pre-Cutover Watch-Day Practice-Run Simulator (Tag-55).

Context
-------

Tag-54 (PR #347) shipped the Pre-Cutover-Watch-Day Spec at
``docs/observability/pre-cutover-watch-day-spec.md`` plus the
pure-function verdict reference implementation at
``scripts/observability/pre-cutover-watch-day-verdict.py``.

Tag-55 is the **practice-run companion**: a sandbox-mode simulator
that walks through the full 08:00..18:00 CEST six-slot procedure
end-to-end with **mock inputs**. It exercises the verdict-formula
along every path the spec §4 procedure can take, validates every
journal entry against the §10 schema, validates the full §4
slot-sequence, and emits a deterministic practice-run report.

Why this matters
~~~~~~~~~~~~~~~~

The Watch-Day procedure runs at most four times (KW-24..27 Tue).
The operator must execute it correctly the *first* time. The
spec § 9 anti-Alert-Fatigue discipline forbids ad-hoc improvisation
during the live shift. The only safe way to learn the procedure
is to dry-run it; this module is that dry-run, hermetic, with
deterministic mock inputs that exercise every code-path the live
procedure can hit.

Design contract
~~~~~~~~~~~~~~~

* **No live podman / Prometheus / Grafana / GitHub calls.** Every
  external dependency is mocked. The simulator runs offline,
  in a tmp_path-isolated state-directory.
* **Verdict-computation delegates to the Tag-54 verdict module.**
  This module does not re-implement §7; it imports the reference
  implementation and drives it.
* **Journal-entries are validated through the same Tag-54
  validators.** The §10 schema is single-sourced; this module does
  not reimplement it.
* **Scenarios are deterministic.** Each scenario is a frozen
  named-tuple of mock-inputs; the simulator emits the same journal
  bytes given the same scenario.
* **CLI exit-code reflects the practice-run outcome.** Exit 0 means
  every scenario reached its expected verdict and every per-slot
  journal-entry validated. Non-zero exit means the practice-run
  diverged from the spec (a regression in the spec implementation
  or this driver).

Anchor: Tag-55 Noa-SRE Watch-Day-Practice-Run.
Predecessor: Tag-54 Pre-Cutover-Watch-Day Spec (PR #347).
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Loader: import the Tag-54 verdict reference module from its hyphenated
# path. The verdict module is a sibling under scripts/observability/.
# ---------------------------------------------------------------------------

def _load_verdict_module() -> Any:
    here = Path(__file__).resolve().parent
    verdict_path = here / "pre-cutover-watch-day-verdict.py"
    if not verdict_path.exists():
        raise FileNotFoundError(
            f"Tag-54 verdict module not found at {verdict_path!s}"
        )
    spec = importlib.util.spec_from_file_location(
        "pre_cutover_watch_day_verdict", str(verdict_path)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pre_cutover_watch_day_verdict"] = mod
    spec.loader.exec_module(mod)
    return mod


VERDICT = _load_verdict_module()


# ---------------------------------------------------------------------------
# Scenario definitions.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Scenario:
    """A single Watch-Day practice-run scenario.

    The simulator iterates the six §4 slots in order, deriving the
    per-slot view of the world from the scenario fields. The
    expected verdict drives the assertion at the 16:00 slot.
    """

    name: str
    # Inputs that the operator gathers at slot=16 to compute the
    # final verdict.
    dashboards: dict[str, bool]
    alert_groups: dict[str, bool]
    probe_verdicts: dict[str, str]
    ci_gates: dict[str, bool]
    firing_slo_burn_rates: frozenset[str]
    tomorrow_cutover_welles: frozenset[str]
    # Slot-by-slot tallies (the operator records these per slot).
    # Each slot maps to a (dashboards_pass, dashboards_fail,
    # alerts_pass, alerts_fail, probes_pass, probes_fail) tuple.
    slot_tallies: dict[str, tuple[int, int, int, int, int, int]]
    # Expected final §7 verdict at slot=16 (and re-confirmed at 18).
    expected_verdict: str
    # Expected ordered red-blocker reasons (empty for GREEN / AMBER).
    expected_red_blockers: tuple[str, ...] = ()
    # Operator-name to record in the journal-entries.
    operator: str = "noa"


# ---------------------------------------------------------------------------
# Scenario builders.
# ---------------------------------------------------------------------------

def _all_dashboards_green() -> dict[str, bool]:
    return {d: True for d in VERDICT.DASHBOARD_IDS}


def _all_alerts_green() -> dict[str, bool]:
    return {a: True for a in VERDICT.ALERT_GROUP_IDS}


def _all_ci_gates_green() -> dict[str, bool]:
    return {c: True for c in VERDICT.CI_GATE_IDS}


def _all_green_tallies() -> dict[str, tuple[int, int, int, int, int, int]]:
    """Tallies for a fully-green Watch-Day, one entry per §4 slot."""
    base = (10, 0, 2, 0, 2, 0)
    return {slot: base for slot in VERDICT.ALL_SLOTS}


def scenario_all_green() -> Scenario:
    return Scenario(
        name="all-green",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=_all_green_tallies(),
        expected_verdict="GREEN",
        expected_red_blockers=(),
    )


def scenario_amber_dashboard_drift() -> Scenario:
    """Dashboard D4 fails to render -> AMBER (drift-type-A, Noa-domain)."""
    dashboards = _all_dashboards_green()
    dashboards["D4"] = False
    tallies = _all_green_tallies()
    # The 08 and 16 slots are the dashboard-checking slots per §4.1
    # and §4.5; failure reflects in dashboards_fail_count = 1.
    drifted = (9, 1, 2, 0, 2, 0)
    tallies = {**tallies, "08": drifted, "16": drifted, "18": drifted}
    return Scenario(
        name="amber-dashboard-drift",
        dashboards=dashboards,
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=tallies,
        expected_verdict="AMBER",
        expected_red_blockers=(),
    )


def scenario_amber_probe() -> Scenario:
    """One AMBER probe -> AMBER verdict (operator notifies Mira, no auto-block)."""
    tallies = _all_green_tallies()
    # Probe AMBER counts as a fail for the §4 probes_fail counter
    # because the slot tracks ``GREEN-pass / not-GREEN-fail``; the
    # journal-entry numerics are independent of the §7 verdict.
    amber_tally = (10, 0, 2, 0, 1, 1)
    tallies = {**tallies, "08": amber_tally, "16": amber_tally, "18": amber_tally}
    return Scenario(
        name="amber-probe",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "AMBER", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=tallies,
        expected_verdict="AMBER",
        expected_red_blockers=(),
    )


def scenario_red_probe() -> Scenario:
    """Per-Welle pre-cutover-probe RED -> RED -> AR-Hand-Stop (§5.3, §6.1)."""
    tallies = _all_green_tallies()
    red_tally = (10, 0, 2, 0, 1, 1)
    tallies = {**tallies, "08": red_tally, "16": red_tally, "18": red_tally}
    return Scenario(
        name="red-probe",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "RED", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=tallies,
        expected_verdict="RED",
        expected_red_blockers=("probe-verdict-RED:welle-1",),
    )


def scenario_red_hard_zero_slo() -> Scenario:
    """Hard-zero SLO burn-rate firing (SLO-5) -> RED (§5.2 drift-type-B)."""
    return Scenario(
        name="red-hard-zero-slo",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset({"SLO-5"}),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=_all_green_tallies(),
        expected_verdict="RED",
        expected_red_blockers=("hard-zero-slo-burn:SLO-5",),
    )


def scenario_red_welle_slo_fast_burn() -> Scenario:
    """SLO-1 fast-burn while a Welle is in tomorrow's cutover -> RED."""
    return Scenario(
        name="red-welle-slo-fast-burn",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset({"SLO-1"}),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=_all_green_tallies(),
        expected_verdict="RED",
        expected_red_blockers=(
            "welle-slo-fast-burn-with-tomorrow-cutover:SLO-1",
        ),
    )


def scenario_red_ci_gate_fail() -> Scenario:
    """CI gate C1 non-success in trailing 24h -> RED (§3.4)."""
    ci_gates = _all_ci_gates_green()
    ci_gates["C1"] = False
    tallies = _all_green_tallies()
    return Scenario(
        name="red-ci-gate-fail",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates=ci_gates,
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=tallies,
        expected_verdict="RED",
        expected_red_blockers=("ci-gate-failed:C1",),
    )


def scenario_green_slo1_burn_without_cutover_welle() -> Scenario:
    """SLO-1 burn but no tomorrow-cutover-Welle -> not a RED blocker.

    The §7 formula explicitly gates SLO-1 fast-burn on the presence
    of tomorrow-cutover-Welles. If the operator runs the practice
    procedure on a non-cutover Tuesday (no Welle scheduled tomorrow),
    SLO-1 fast-burn alone does not flip the verdict to RED. With
    no probe-verdicts (empty cutover slate), all GREEN conditions
    in §7 still hold and the verdict is GREEN.
    """
    tallies = _all_green_tallies()
    # No probes to count when no Welle is scheduled tomorrow.
    no_probe_tally = (10, 0, 2, 0, 0, 0)
    tallies = {slot: no_probe_tally for slot in VERDICT.ALL_SLOTS}
    return Scenario(
        name="green-slo1-burn-without-cutover-welle",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={},
        ci_gates=_all_ci_gates_green(),
        firing_slo_burn_rates=frozenset({"SLO-1"}),
        tomorrow_cutover_welles=frozenset(),
        slot_tallies=tallies,
        expected_verdict="GREEN",
        expected_red_blockers=(),
    )


def scenario_red_multi_blocker() -> Scenario:
    """Multiple red-blockers at once -> RED with ordered reasons.

    Tests that the §7 implementation surfaces all blockers in the
    spec'd stable order (probe-RED, hard-zero-SLO, welle-SLO,
    ci-gate) so the operator gets a complete picture in one read.
    """
    return Scenario(
        name="red-multi-blocker",
        dashboards=_all_dashboards_green(),
        alert_groups=_all_alerts_green(),
        probe_verdicts={"welle-1": "RED", "welle-2": "GREEN"},
        ci_gates={"C1": False, "C2": True},
        firing_slo_burn_rates=frozenset({"SLO-1", "SLO-5"}),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
        slot_tallies=_all_green_tallies(),
        expected_verdict="RED",
        expected_red_blockers=(
            "probe-verdict-RED:welle-1",
            "hard-zero-slo-burn:SLO-5",
            "welle-slo-fast-burn-with-tomorrow-cutover:SLO-1",
            "ci-gate-failed:C1",
        ),
    )


# Catalogue of all built-in scenarios. Add to this tuple to extend.
ALL_SCENARIOS: tuple[Callable[[], Scenario], ...] = (
    scenario_all_green,
    scenario_amber_dashboard_drift,
    scenario_amber_probe,
    scenario_red_probe,
    scenario_red_hard_zero_slo,
    scenario_red_welle_slo_fast_burn,
    scenario_red_ci_gate_fail,
    scenario_green_slo1_burn_without_cutover_welle,
    scenario_red_multi_blocker,
)


# ---------------------------------------------------------------------------
# Simulator core.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class SlotResult:
    """Result of simulating one §4 slot."""

    slot: str
    journal_entry: dict[str, Any]
    journal_validation: Any  # JournalValidation from verdict module
    pass_: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "journal_entry": self.journal_entry,
            "validation_ok": self.journal_validation.ok,
            "validation_errors": list(self.journal_validation.errors),
            "pass": self.pass_,
        }


@dataclasses.dataclass(frozen=True)
class ScenarioResult:
    """Result of simulating one scenario across all six slots."""

    scenario_name: str
    expected_verdict: str
    computed_verdict: str
    expected_red_blockers: tuple[str, ...]
    computed_red_blockers: tuple[str, ...]
    slot_results: tuple[SlotResult, ...]
    sequence_validation_ok: bool
    sequence_validation_errors: tuple[str, ...]
    pass_: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "expected_verdict": self.expected_verdict,
            "computed_verdict": self.computed_verdict,
            "expected_red_blockers": list(self.expected_red_blockers),
            "computed_red_blockers": list(self.computed_red_blockers),
            "slot_results": [s.to_dict() for s in self.slot_results],
            "sequence_validation_ok": self.sequence_validation_ok,
            "sequence_validation_errors": list(self.sequence_validation_errors),
            "pass": self.pass_,
        }


def _ci_gate_status(boolean: bool) -> str:
    """Map ci_gates dict value to journal-schema literal."""
    return "success" if boolean else "failure"


def build_journal_entry(
    scenario: Scenario, slot: str, verdict_for_slot: str | None
) -> dict[str, Any]:
    """Construct a single §10-schema-conformant journal-entry dict.

    The simulator picks a fixed practice-day timestamp prefix to
    keep output deterministic across runs.
    """
    dpass, dfail, apass, afail, ppass, pfail = scenario.slot_tallies[slot]
    return {
        "slot": slot,
        "timestamp_iso": f"2026-06-09T{slot}:00:00+02:00",
        "operator": scenario.operator,
        "cutover_welle": sorted(scenario.tomorrow_cutover_welles),
        "dashboards_pass_count": dpass,
        "dashboards_fail_count": dfail,
        "alerts_pass_count": apass,
        "alerts_fail_count": afail,
        "probes_pass_count": ppass,
        "probes_fail_count": pfail,
        "ci_gate_c1": _ci_gate_status(scenario.ci_gates.get("C1", False)),
        "ci_gate_c2": _ci_gate_status(scenario.ci_gates.get("C2", False)),
        "verdict": verdict_for_slot,
        "notes": "",
    }


def simulate_scenario(
    scenario: Scenario, state_dir: Path | None = None
) -> ScenarioResult:
    """Run the six-slot §4 procedure for one scenario.

    If ``state_dir`` is provided, the simulator writes the JSONL
    journal to ``state_dir/watch-day-journal.jsonl`` and the final
    one-line verdict to ``state_dir/verdict.txt`` (mirroring the
    spec §8 state-directory layout).
    """
    inputs = VERDICT.WatchDayInputs(
        dashboards=scenario.dashboards,
        alert_groups=scenario.alert_groups,
        probe_verdicts=scenario.probe_verdicts,
        ci_gates=scenario.ci_gates,
        firing_slo_burn_rates=scenario.firing_slo_burn_rates,
        tomorrow_cutover_welles=scenario.tomorrow_cutover_welles,
    )

    computed_verdict = VERDICT.compute_verdict(inputs)
    computed_red_blockers = tuple(VERDICT.red_blocker_reasons(inputs))

    # Build the six journal entries.
    slot_results: list[SlotResult] = []
    entries: list[dict[str, Any]] = []
    for slot in VERDICT.ALL_SLOTS:
        verdict_for_slot: str | None
        if slot in VERDICT.VERDICT_SLOTS:
            verdict_for_slot = computed_verdict
        else:
            verdict_for_slot = None
        entry = build_journal_entry(scenario, slot, verdict_for_slot)
        validation = VERDICT.validate_journal_entry(entry)
        slot_pass = validation.ok
        slot_results.append(
            SlotResult(
                slot=slot,
                journal_entry=entry,
                journal_validation=validation,
                pass_=slot_pass,
            )
        )
        entries.append(entry)

    sequence_validation = VERDICT.validate_journal_sequence(entries)

    # Optional: write the §8 state-directory artefacts.
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
        journal_path = state_dir / "watch-day-journal.jsonl"
        with journal_path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        verdict_path = state_dir / "verdict.txt"
        verdict_path.write_text(computed_verdict + "\n", encoding="utf-8")

    scenario_pass = (
        computed_verdict == scenario.expected_verdict
        and computed_red_blockers == scenario.expected_red_blockers
        and all(s.pass_ for s in slot_results)
        and sequence_validation.ok
    )

    return ScenarioResult(
        scenario_name=scenario.name,
        expected_verdict=scenario.expected_verdict,
        computed_verdict=computed_verdict,
        expected_red_blockers=scenario.expected_red_blockers,
        computed_red_blockers=computed_red_blockers,
        slot_results=tuple(slot_results),
        sequence_validation_ok=sequence_validation.ok,
        sequence_validation_errors=sequence_validation.errors,
        pass_=scenario_pass,
    )


@dataclasses.dataclass(frozen=True)
class PracticeRunReport:
    """Outcome of running every scenario in a practice-run."""

    scenarios: tuple[ScenarioResult, ...]
    total: int
    passed: int
    failed: int
    overall_pass: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "overall_pass": self.overall_pass,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }


def run_practice(
    scenarios: tuple[Scenario, ...] | None = None,
    state_root: Path | None = None,
) -> PracticeRunReport:
    """Execute every scenario, return a PracticeRunReport.

    If ``state_root`` is provided, each scenario writes its journal
    + verdict into ``state_root/<scenario-name>/``.
    """
    if scenarios is None:
        scenarios = tuple(builder() for builder in ALL_SCENARIOS)

    results: list[ScenarioResult] = []
    for scenario in scenarios:
        sd = state_root / scenario.name if state_root is not None else None
        results.append(simulate_scenario(scenario, state_dir=sd))

    passed = sum(1 for r in results if r.pass_)
    failed = len(results) - passed
    return PracticeRunReport(
        scenarios=tuple(results),
        total=len(results),
        passed=passed,
        failed=failed,
        overall_pass=(failed == 0),
    )


# ---------------------------------------------------------------------------
# Reporting helpers.
# ---------------------------------------------------------------------------

def format_human_report(report: PracticeRunReport) -> str:
    """Render the PracticeRunReport as a deterministic plaintext block."""
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("Pre-Cutover Watch-Day Practice-Run Report (Tag-55)")
    lines.append("=" * 68)
    for result in report.scenarios:
        status = "PASS" if result.pass_ else "FAIL"
        lines.append(
            f"[{status}] scenario={result.scenario_name} "
            f"expected={result.expected_verdict} "
            f"computed={result.computed_verdict}"
        )
        if result.computed_red_blockers:
            for reason in result.computed_red_blockers:
                lines.append(f"        red-blocker: {reason}")
        if not result.sequence_validation_ok:
            for err in result.sequence_validation_errors:
                lines.append(f"        sequence-error: {err}")
        for slot_result in result.slot_results:
            if not slot_result.pass_:
                for err in slot_result.journal_validation.errors:
                    lines.append(
                        f"        slot-{slot_result.slot}-error: {err}"
                    )
    lines.append("-" * 68)
    lines.append(
        f"Totals: total={report.total} "
        f"passed={report.passed} failed={report.failed} "
        f"overall={'PASS' if report.overall_pass else 'FAIL'}"
    )
    lines.append("=" * 68)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help=(
            "Optional state-root directory. If provided, each scenario "
            "writes its watch-day-journal.jsonl and verdict.txt into "
            "${state-root}/<scenario-name>/."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report on stdout instead of the human text.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help=(
            "Run only the named scenario(s). May be passed multiple times. "
            "Default: run every built-in scenario."
        ),
    )
    args = parser.parse_args(argv)

    if args.scenario:
        wanted = set(args.scenario)
        scenarios = tuple(
            builder()
            for builder in ALL_SCENARIOS
            if builder().name in wanted
        )
        if not scenarios:
            print(
                f"error: no built-in scenarios matched {sorted(wanted)}",
                file=sys.stderr,
            )
            return 2
    else:
        scenarios = None

    report = run_practice(scenarios=scenarios, state_root=args.state_root)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_human_report(report), end="")

    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
