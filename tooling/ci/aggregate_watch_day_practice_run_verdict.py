#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Aggregator + per-scenario pinning helper for the Tag-56 Watch-Day-
Practice-Run CI workflow (`.github/workflows/phase-3c-watch-day-
practice-run.yml`).

Four modes (selected by ``--mode``):

* ``pin`` - Per-scenario verdict + red-blocker pinning. Reads the
  practice-run JSON report (``--report``) and asserts each scenario
  reached its expected verdict and expected red-blocker tuple. Exit
  0 on full match, 2 if any scenario diverges (treated as ``yellow``
  in the workflow because the substrate ran but the regression-pin
  caught drift), 1 on internal errors (report missing / malformed).

* ``sequence`` - Slot-sequence-validation per scenario. Asserts each
  scenario's ``sequence_validation_ok`` is ``true``. Same exit-code
  convention as ``pin``.

* ``aggregate`` - Tri-state decision-aggregation (READY/CAUTION/
  BLOCK). Reads ``STEP1_STATUS``..``STEP4_STATUS`` from the
  environment and emits a JSON verdict-envelope to ``--output``.
  Verdict rules:
    * READY    - all four steps green.
    * CAUTION  - exactly one step yellow, the rest green.
    * BLOCK    - any step red, or 2+ yellow.

* ``replay`` - Tag-59 hermetic replay-mode. Loads a committed
  practice-run fixture (``--fixture-path``) and compares its
  byte-for-byte SHA-256 + per-scenario verdict/red-blocker tuple to
  the pinned expectation. Emits a REPLAY-STABLE / REPLAY-DRIFT
  envelope. Used by the Tag-59 replay workflow to detect drift in
  the captured artifact between the time it was pinned (Tag-59) and
  any future re-run (KW-24..27 Watch-Days). Exit 0 = stable, 2 =
  drift, 1 = fixture missing / malformed.

The module is intentionally pure-stdlib: it is invoked from the
CI workflow with no third-party dependencies installed. The tests
in ``tests/ci/test_phase_3c_watch_day_practice_run_workflow.py``
walk the full truth-table.

Anchor: Tag-56 Noa-SRE Watch-Day-Practice-Run CI-Gate.
Predecessors:
  Tag-54 spec + verdict (PR #347),
  Tag-55 practice-run simulator (PR #353).
Tag-59 extension: ``replay`` mode for hermetic dry-run-replay
  workflow (KW-24 Pre-Sealing).
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Truth-table constants. Single-sourced here so the workflow YAML
# and the tests stay aligned.
# ---------------------------------------------------------------------------

STEP_KEYS: tuple[str, ...] = (
    "STEP1_STATUS",
    "STEP2_STATUS",
    "STEP3_STATUS",
    "STEP4_STATUS",
)

VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})

VERDICT_READY = "READY"
VERDICT_CAUTION = "CAUTION"
VERDICT_BLOCK = "BLOCK"


# ---------------------------------------------------------------------------
# Exit codes (kept stable so the workflow's bash dispatch can rely
# on them).
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1       # internal error (report missing / malformed)
EXIT_DIVERGED = 2    # substrate ran but regression-pin caught drift


# ---------------------------------------------------------------------------
# Mode: pin
# ---------------------------------------------------------------------------


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        print(f"::error::report missing: {path}", file=sys.stderr)
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"::error::report malformed: {exc}", file=sys.stderr)
        return None


def mode_pin(report_path: Path) -> int:
    """Per-scenario verdict + red-blocker pinning."""
    report = _load_report(report_path)
    if report is None:
        return EXIT_ERROR
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        print("::error::report contains no scenarios", file=sys.stderr)
        return EXIT_ERROR
    diverged: list[str] = []
    for sc in scenarios:
        name = sc.get("scenario", "<unknown>")
        if sc.get("computed_verdict") != sc.get("expected_verdict"):
            diverged.append(
                f"{name}: verdict {sc.get('computed_verdict')!r} "
                f"!= expected {sc.get('expected_verdict')!r}"
            )
            continue
        computed_blockers = tuple(sc.get("computed_red_blockers") or ())
        expected_blockers = tuple(sc.get("expected_red_blockers") or ())
        if computed_blockers != expected_blockers:
            diverged.append(
                f"{name}: red_blockers {list(computed_blockers)!r} "
                f"!= expected {list(expected_blockers)!r}"
            )
    if diverged:
        print("::warning::per-scenario verdict-pin caught drift:", file=sys.stderr)
        for d in diverged:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_DIVERGED
    print(f"per-scenario verdict-pin: all {len(scenarios)} scenarios match")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: sequence
# ---------------------------------------------------------------------------


def mode_sequence(report_path: Path) -> int:
    """Slot-sequence-validation per scenario."""
    report = _load_report(report_path)
    if report is None:
        return EXIT_ERROR
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        print("::error::report contains no scenarios", file=sys.stderr)
        return EXIT_ERROR
    diverged: list[str] = []
    for sc in scenarios:
        name = sc.get("scenario", "<unknown>")
        if not sc.get("sequence_validation_ok", False):
            errors = sc.get("sequence_validation_errors") or []
            diverged.append(f"{name}: {errors!r}")
    if diverged:
        print(
            "::warning::slot-sequence-validation caught drift:", file=sys.stderr
        )
        for d in diverged:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_DIVERGED
    print(
        f"slot-sequence-validation: all {len(scenarios)} scenarios well-formed"
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: aggregate
# ---------------------------------------------------------------------------


def normalize_status(raw: str | None) -> str:
    """Map a raw env-string to a known status. Empty/unknown -> red."""
    if raw is None:
        return "red"
    raw = raw.strip().lower()
    if raw in VALID_STATUSES:
        return raw
    return "red"


def compute_verdict(statuses: dict[str, str]) -> str:
    """Compute the tri-state verdict from the four step-statuses."""
    s = [statuses[k] for k in STEP_KEYS]
    reds = sum(1 for x in s if x == "red")
    yellows = sum(1 for x in s if x == "yellow")
    greens = sum(1 for x in s if x == "green")
    if reds == 0 and yellows == 0 and greens == 4:
        return VERDICT_READY
    if reds == 0 and yellows == 1:
        return VERDICT_CAUTION
    return VERDICT_BLOCK


def build_envelope(
    statuses: dict[str, str], missing: str
) -> dict[str, Any]:
    verdict = compute_verdict(statuses)
    return {
        "verdict": verdict,
        "steps": {
            "step1_inventory": statuses["STEP1_STATUS"],
            "step2_hermetic_practice_run": statuses["STEP2_STATUS"],
            "step3_per_scenario_verdict_pinning": statuses["STEP3_STATUS"],
            "step4_slot_sequence_validation": statuses["STEP4_STATUS"],
        },
        "inventory_missing": [m for m in (missing or "").split(",") if m],
        "schema_version": 1,
    }


def mode_aggregate(output_path: Path) -> int:
    statuses = {k: normalize_status(os.environ.get(k)) for k in STEP_KEYS}
    missing = os.environ.get("INVENTORY_MISSING", "")
    envelope = build_envelope(statuses, missing)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"verdict={envelope['verdict']}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: replay (Tag-59)
# ---------------------------------------------------------------------------


REPLAY_STABLE = "REPLAY-STABLE"
REPLAY_DRIFT = "REPLAY-DRIFT"

# Tag-59 pinned fixture SHA-256. The fixture is the deterministic
# JSON-output of `scripts/observability/watch-day-practice-run.py
# --json` at the time Tag-59 was sealed. Any future re-capture must
# produce byte-identical output; if not, the practice-run simulator
# has drifted and the operator's training is invalidated.
#
# Tag-61: This now corresponds to the GREEN-day sample; the canonical
# fixture file has been renamed to `watch-day-practice-run-sample-
# green.json` and joined by `*-caution.json` and `*-red.json`
# variants. See ``FIXTURE_SETS`` below.
TAG59_FIXTURE_SHA256 = (
    "6cbb7e574e27baa1d08b7d0cafcbd0b4154b2b1194f14936c84fcca8f3d82cfc"
)

# Tag-59 pinned per-scenario verdict expectations. Single-sourced
# here so the replay-mode can detect drift even if the fixture file
# is replaced with a syntactically-valid-but-wrong-content variant.
TAG59_PINNED_VERDICTS: tuple[tuple[str, str], ...] = (
    ("all-green", "GREEN"),
    ("amber-dashboard-drift", "AMBER"),
    ("amber-probe", "AMBER"),
    ("red-probe", "RED"),
    ("red-hard-zero-slo", "RED"),
    ("red-welle-slo-fast-burn", "RED"),
    ("red-ci-gate-fail", "RED"),
    ("green-slo1-burn-without-cutover-welle", "GREEN"),
    ("red-multi-blocker", "RED"),
)


# ---------------------------------------------------------------------------
# Tag-61 multi-sample-fixture-set extension.
#
# Where Tag-59 pinned a single (GREEN-day) practice-run output, the
# operator's KW-24..27 Watch-Day runbook needs replay-coverage across
# all three verdict-classes that the Tag-54 spec emits:
#
#   * GREEN-day   - 9/9 scenarios match expected; overall_pass=True.
#                   Operator action: proceed.
#   * CAUTION-day - 8/9 scenarios match; one scenario drifted from
#                   its expected verdict (here: amber-dashboard-
#                   drift was over-fired to GREEN by a simulator
#                   refactor). Operator action: investigate, decide.
#   * RED-day     - 6/9 scenarios diverged; multiple blockers
#                   missed/over-fired plus one slot-sequence
#                   validation error. Operator action: block cutover.
#
# The replay-helper now selects which pinned-tuple to compare against
# via ``--fixture-set {green|caution|red}``. The Tag-59 default
# remains GREEN for backwards compatibility (workflows that pre-date
# Tag-61 keep working).
#
# CAUTION/RED pins also include ``overall_pass`` expectation so the
# "broken-fixture-but-honest" failure mode stays detectable even when
# the per-scenario tuple drift is the intended day-state.
# ---------------------------------------------------------------------------


TAG61_GREEN_FIXTURE_SHA256 = TAG59_FIXTURE_SHA256
TAG61_GREEN_PINNED_VERDICTS = TAG59_PINNED_VERDICTS
TAG61_GREEN_OVERALL_PASS = True

TAG61_CAUTION_FIXTURE_SHA256 = (
    "c94f6a0382060e546a213f2cd5a4e13f8fcc101e1b9ac7fe444b74fefac992c0"
)
# CAUTION-day pinned tuple: amber-dashboard-drift's computed_verdict
# drifted to "GREEN" while expected stayed "AMBER". All other
# scenarios match the GREEN-day tuple.
TAG61_CAUTION_PINNED_VERDICTS: tuple[tuple[str, str], ...] = (
    ("all-green", "GREEN"),
    ("amber-dashboard-drift", "GREEN"),  # drifted (computed)
    ("amber-probe", "AMBER"),
    ("red-probe", "RED"),
    ("red-hard-zero-slo", "RED"),
    ("red-welle-slo-fast-burn", "RED"),
    ("red-ci-gate-fail", "RED"),
    ("green-slo1-burn-without-cutover-welle", "GREEN"),
    ("red-multi-blocker", "RED"),
)
TAG61_CAUTION_OVERALL_PASS = False

TAG61_RED_FIXTURE_SHA256 = (
    "d23dc0352ea1717d6f30c991c25341f0ae5155b04950872e7634e73c379d901f"
)
# RED-day pinned tuple: amber-probe over-fired to RED; red-probe and
# red-multi-blocker have computed_red_blockers drift; red-multi-
# blocker also has sequence_validation drift.
TAG61_RED_PINNED_VERDICTS: tuple[tuple[str, str], ...] = (
    ("all-green", "GREEN"),
    ("amber-dashboard-drift", "AMBER"),
    ("amber-probe", "RED"),              # over-fired (computed)
    ("red-probe", "RED"),
    ("red-hard-zero-slo", "RED"),
    ("red-welle-slo-fast-burn", "RED"),
    ("red-ci-gate-fail", "RED"),
    ("green-slo1-burn-without-cutover-welle", "GREEN"),
    ("red-multi-blocker", "RED"),
)
TAG61_RED_OVERALL_PASS = False


FIXTURE_SETS: dict[str, dict[str, Any]] = {
    "green": {
        "fixture_name": "watch-day-practice-run-sample-green.json",
        "sha256": TAG61_GREEN_FIXTURE_SHA256,
        "verdicts": TAG61_GREEN_PINNED_VERDICTS,
        "overall_pass": TAG61_GREEN_OVERALL_PASS,
    },
    "caution": {
        "fixture_name": "watch-day-practice-run-sample-caution.json",
        "sha256": TAG61_CAUTION_FIXTURE_SHA256,
        "verdicts": TAG61_CAUTION_PINNED_VERDICTS,
        "overall_pass": TAG61_CAUTION_OVERALL_PASS,
    },
    "red": {
        "fixture_name": "watch-day-practice-run-sample-red.json",
        "sha256": TAG61_RED_FIXTURE_SHA256,
        "verdicts": TAG61_RED_PINNED_VERDICTS,
        "overall_pass": TAG61_RED_OVERALL_PASS,
    },
}


def resolve_fixture_set(name: str) -> dict[str, Any]:
    """Resolve a fixture-set name to its pinned-spec dict.

    Raises KeyError with a helpful message if the name is unknown.
    """
    if name not in FIXTURE_SETS:
        raise KeyError(
            f"unknown fixture-set {name!r}; "
            f"valid: {sorted(FIXTURE_SETS.keys())}"
        )
    return FIXTURE_SETS[name]


def _sha256_of_file(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def mode_replay(
    fixture_path: Path,
    output_path: Path,
    expected_sha256: str = TAG59_FIXTURE_SHA256,
    expected_verdicts: tuple[tuple[str, str], ...] = TAG59_PINNED_VERDICTS,
    expected_overall_pass: bool = True,
    fixture_set_name: str = "green",
) -> int:
    """Hermetic replay-mode: re-validate a pinned fixture.

    Layer 1 - File-hash pinning. The fixture must hash to the
    pinned SHA-256 for its fixture-set. Any byte-level drift
    fails REPLAY-DRIFT.

    Layer 2 - Per-scenario verdict pinning. The fixture must contain
    exactly the nine pinned scenario-name x computed_verdict pairs
    in order, for its fixture-set. A reordering, rename, or verdict-
    change fails REPLAY-DRIFT.

    Layer 3 - overall_pass pinning. The fixture's ``overall_pass``
    flag must match the fixture-set's expectation. Tag-59 fixed this
    to ``True`` (GREEN-only); Tag-61 generalises to per-set
    (CAUTION/RED sets pin ``False``).

    All three layers must pass for REPLAY-STABLE.

    ``fixture_set_name`` is recorded in the output envelope for
    operator-facing context; it does not affect drift detection by
    itself.
    """
    drift_reasons: list[str] = []

    actual_sha = _sha256_of_file(fixture_path)
    if actual_sha is None:
        print(f"::error::fixture missing: {fixture_path}", file=sys.stderr)
        return EXIT_ERROR
    if actual_sha != expected_sha256:
        drift_reasons.append(
            f"sha256 drift: actual={actual_sha} pinned={expected_sha256}"
        )

    report = _load_report(fixture_path)
    if report is None:
        return EXIT_ERROR

    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        print("::error::fixture has no scenarios", file=sys.stderr)
        return EXIT_ERROR

    actual_pairs = tuple(
        (sc.get("scenario", "<unknown>"), sc.get("computed_verdict", "<missing>"))
        for sc in scenarios
    )
    if actual_pairs != expected_verdicts:
        drift_reasons.append(
            f"verdict-pair drift: actual={list(actual_pairs)!r} "
            f"pinned={list(expected_verdicts)!r}"
        )

    # Tag-61: pin overall_pass per fixture-set rather than hard-coded
    # to True. The "broken-fixture-but-honest" failure mode still
    # surfaces because the expected value is single-sourced in
    # FIXTURE_SETS.
    actual_overall_pass = report.get("overall_pass")
    if actual_overall_pass != expected_overall_pass:
        drift_reasons.append(
            f"overall_pass drift: actual={actual_overall_pass!r} "
            f"pinned={expected_overall_pass!r}"
        )

    verdict = REPLAY_DRIFT if drift_reasons else REPLAY_STABLE
    envelope = {
        "verdict": verdict,
        "fixture_set": fixture_set_name,
        "fixture_path": str(fixture_path),
        "fixture_sha256_actual": actual_sha,
        "fixture_sha256_pinned": expected_sha256,
        "overall_pass_actual": actual_overall_pass,
        "overall_pass_pinned": expected_overall_pass,
        "scenarios_actual": [list(p) for p in actual_pairs],
        "scenarios_pinned": [list(p) for p in expected_verdicts],
        "drift_reasons": drift_reasons,
        "schema_version": 2,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, sort_keys=True)
        fh.write("\n")
    if drift_reasons:
        print(
            f"::warning::watch-day-practice-run replay caught drift "
            f"(set={fixture_set_name}, {len(drift_reasons)} reason(s)):",
            file=sys.stderr,
        )
        for r in drift_reasons:
            print(f"  - {r}", file=sys.stderr)
        print(f"verdict={verdict}")
        return EXIT_DIVERGED
    print(f"verdict={verdict}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_watch_day_practice_run_verdict",
        description=(
            "Aggregator + per-scenario pinning helper for the Tag-56 "
            "Watch-Day-Practice-Run CI workflow."
        ),
    )
    # ``--mode`` is required *unless* the convenience alias
    # ``--replay-mode`` is given. We enforce that in ``main``
    # because argparse cannot express "required-unless" natively.
    p.add_argument(
        "--mode",
        choices=("pin", "sequence", "aggregate", "replay"),
        required=False,
        default=None,
        help="Which step the helper runs for.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("out/watch-day-practice-run-report.json"),
        help="Path to the practice-run JSON report (for pin/sequence modes).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("out/watch-day-practice-run-verdict.json"),
        help="Output path for the aggregated verdict envelope.",
    )
    # Tag-59 replay-mode flags.
    p.add_argument(
        "--fixture-path",
        type=Path,
        default=None,
        help=(
            "Path to the pinned practice-run fixture (replay mode). "
            "If omitted, derived from --fixture-set."
        ),
    )
    p.add_argument(
        "--replay-mode",
        action="store_true",
        help=(
            "Alias: force --mode=replay. Convenience flag for the "
            "Tag-59 replay workflow."
        ),
    )
    # Tag-61: pick which day-class the fixture represents. Each set
    # has its own pinned SHA-256 + per-scenario verdict tuple +
    # overall_pass expectation. ``green`` preserves the Tag-59
    # default for backwards compatibility.
    p.add_argument(
        "--fixture-set",
        choices=tuple(sorted(FIXTURE_SETS.keys())),
        default="green",
        help=(
            "Which Watch-Day verdict-class the replay fixture "
            "represents (Tag-61 multi-sample). Default: green."
        ),
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    # Tag-59: ``--replay-mode`` is an alias for ``--mode replay``.
    # If neither is given we surface the required-arg error
    # explicitly (argparse no longer flags it because --mode is now
    # ``required=False`` for the replay-alias case).
    if args.replay_mode:
        mode = "replay"
    elif args.mode is not None:
        mode = args.mode
    else:
        parser.error("--mode is required (or pass --replay-mode)")
        return EXIT_ERROR  # unreachable
    if mode == "pin":
        return mode_pin(args.report)
    if mode == "sequence":
        return mode_sequence(args.report)
    if mode == "aggregate":
        return mode_aggregate(args.output)
    if mode == "replay":
        # Tag-61: resolve fixture-set -> pinned spec. If
        # --fixture-path was not given, derive it from the set's
        # canonical filename under tests/observability/fixtures/.
        try:
            spec = resolve_fixture_set(args.fixture_set)
        except KeyError as exc:
            parser.error(str(exc))
            return EXIT_ERROR  # unreachable
        fixture_path = args.fixture_path
        if fixture_path is None:
            fixture_path = Path(
                "tests/observability/fixtures"
            ) / spec["fixture_name"]
        return mode_replay(
            fixture_path,
            args.output,
            expected_sha256=spec["sha256"],
            expected_verdicts=spec["verdicts"],
            expected_overall_pass=spec["overall_pass"],
            fixture_set_name=args.fixture_set,
        )
    parser.error(f"unknown mode: {mode}")
    return EXIT_ERROR  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
