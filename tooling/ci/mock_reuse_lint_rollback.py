#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Mock-substrate for the REUSE-Wrap Pre-Merge Lint Enforce-Flip rollback (Tag-63).

Purpose
-------

The actual ``REUSE_WRAP_LINT_ENFORCE`` repo-variable flip is
operator-hand (`gh variable set ...`) under the Mira-Sandbox-vs-
Host-Operations rule. The rollback (set the variable back to ``0``
when a post-flip regression appears) is *also* operator-hand for
the same reason.

What this mock-substrate gives us is a hermetic exercise of the
rollback **decision-logic**: "given a workflow-run-history and an
enforce-state, should the operator roll back, hold, or escalate?"
The decision-logic is the same in hermetic-sandbox and on the
host; only the side-effect (the actual ``gh variable set`` call)
is gated by the boundary.

This file is consumed by:

* ``.github/workflows/reuse-wrap-enforce-flip-stability-window-probe.yml``
  Stage 3 -- as an auxiliary sanity check that rollback-logic
  still compiles + still emits canonical verdicts.
* ``tests/ci/test_reuse_lint_enforce_flip_actual_plan_tag63.py`` --
  exercising the verdict matrix on synthetic inputs.

Decision matrix
---------------

The mock takes three inputs:

* ``enforce_state``     - current repo-var value, ``"0"`` or ``"1"``.
* ``recent_main_runs``  - list of dicts ``{"conclusion": str, "head_sha": str}``
                          for the last K main-branch workflow runs (most-recent first).
* ``flake_budget``      - integer, default 0. A non-zero flake budget
                          means up to N transient red runs are still
                          "HOLD" rather than "ROLLBACK".

And emits one of:

* ``MOCK-ROLLBACK-NO-OP``    - enforce already off, nothing to do.
* ``MOCK-ROLLBACK-HOLD``     - enforce on, but the red runs fit
                                within the flake-budget; do not roll
                                back yet, watch one more cycle.
* ``MOCK-ROLLBACK-RECOMMEND``- enforce on, red runs exceed the flake-
                                budget; the operator should run the
                                §6.2 un-flip recipe from the plan-doc.
* ``MOCK-ROLLBACK-ESCALATE`` - enforce on, *all* recent main runs are
                                red, and the budget cannot save us.
                                This is the "the gate is broken,
                                not just flaky" verdict.

Hermetic
--------

stdlib only. No subprocess into the network. Designed to import
cleanly from the test-suite and the workflow-step alike.
"""

# REUSE-IgnoreEnd

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Iterable

# REUSE-IgnoreStart
_VERDICT_NO_OP = "MOCK-ROLLBACK-NO-OP"
_VERDICT_HOLD = "MOCK-ROLLBACK-HOLD"
_VERDICT_RECOMMEND = "MOCK-ROLLBACK-RECOMMEND"
_VERDICT_ESCALATE = "MOCK-ROLLBACK-ESCALATE"
# REUSE-IgnoreEnd

_VALID_ENFORCE_STATES = ("0", "1")
_GREEN_CONCLUSIONS = frozenset({"success"})
_RED_CONCLUSIONS = frozenset({"failure", "timed_out", "cancelled"})


@dataclass(frozen=True)
class RollbackVerdict:
    """Outcome of the rollback-decision evaluation."""

    verdict: str
    enforce_state: str
    runs_seen: int
    runs_red: int
    runs_green: int
    flake_budget: int
    reason: str


def _classify_runs(runs: Iterable[dict]) -> tuple[int, int]:
    """Return ``(green, red)`` counts from a run-history list.

    Anything outside the canonical green/red sets is silently
    ignored -- it might be ``in_progress``, ``neutral``, or
    something else we have not modelled. The rollback decision
    only weighs settled green/red conclusions, since a
    still-running build cannot meaningfully tip the balance.
    """
    green = 0
    red = 0
    for r in runs:
        c = r.get("conclusion")
        if c in _GREEN_CONCLUSIONS:
            green += 1
        elif c in _RED_CONCLUSIONS:
            red += 1
    return green, red


def decide_rollback(
    *,
    enforce_state: str,
    recent_main_runs: list[dict],
    flake_budget: int = 0,
) -> RollbackVerdict:
    """Return the canonical rollback verdict for the given inputs.

    See module docstring for the decision matrix. Pure function;
    deterministic; no side-effects.
    """
    if enforce_state not in _VALID_ENFORCE_STATES:
        raise ValueError(
            f"invalid enforce_state {enforce_state!r}; "
            f"expected one of {_VALID_ENFORCE_STATES}"
        )
    if flake_budget < 0:
        raise ValueError(f"flake_budget must be >= 0, got {flake_budget}")

    green, red = _classify_runs(recent_main_runs)
    runs_seen = green + red

    if enforce_state == "0":
        return RollbackVerdict(
            verdict=_VERDICT_NO_OP,
            enforce_state=enforce_state,
            runs_seen=runs_seen,
            runs_red=red,
            runs_green=green,
            flake_budget=flake_budget,
            reason="enforce already off; no rollback action required",
        )

    # enforce_state == "1" from here on.
    if runs_seen == 0:
        return RollbackVerdict(
            verdict=_VERDICT_HOLD,
            enforce_state=enforce_state,
            runs_seen=0,
            runs_red=0,
            runs_green=0,
            flake_budget=flake_budget,
            reason="no settled main runs observed; hold and re-check next cycle",
        )

    if red == 0:
        return RollbackVerdict(
            verdict=_VERDICT_HOLD,
            enforce_state=enforce_state,
            runs_seen=runs_seen,
            runs_red=0,
            runs_green=green,
            flake_budget=flake_budget,
            reason="all settled main runs are green; no rollback needed",
        )

    if red == runs_seen and runs_seen >= 2:
        # Every observed run is red AND we have at least two samples.
        # Single-sample all-red stays in the budget-comparison branch
        # so it can degrade gracefully into HOLD when budget >= 1.
        return RollbackVerdict(
            verdict=_VERDICT_ESCALATE,
            enforce_state=enforce_state,
            runs_seen=runs_seen,
            runs_red=red,
            runs_green=0,
            flake_budget=flake_budget,
            reason="all recent main runs red; gate appears broken, escalate",
        )

    if red <= flake_budget:
        return RollbackVerdict(
            verdict=_VERDICT_HOLD,
            enforce_state=enforce_state,
            runs_seen=runs_seen,
            runs_red=red,
            runs_green=green,
            flake_budget=flake_budget,
            reason=(
                f"{red} red run(s) within flake-budget of {flake_budget}; "
                "hold and re-check next cycle"
            ),
        )

    return RollbackVerdict(
        verdict=_VERDICT_RECOMMEND,
        enforce_state=enforce_state,
        runs_seen=runs_seen,
        runs_red=red,
        runs_green=green,
        flake_budget=flake_budget,
        reason=(
            f"{red} red run(s) exceed flake-budget of {flake_budget}; "
            "run plan-doc §6.2 un-flip recipe"
        ),
    )


def render_verdict_text(verdict: RollbackVerdict) -> str:
    """Render the canonical text report for the rollback verdict."""
    lines = [
        f"{verdict.verdict}: enforce_state={verdict.enforce_state}",
        f"  runs_seen   = {verdict.runs_seen}",
        f"  runs_green  = {verdict.runs_green}",
        f"  runs_red    = {verdict.runs_red}",
        f"  flake_budget= {verdict.flake_budget}",
        f"  reason      = {verdict.reason}",
    ]
    return "\n".join(lines) + "\n"


def render_verdict_json(verdict: RollbackVerdict) -> str:
    """Render the verdict as a JSON object on a single line."""
    payload = {
        "verdict": verdict.verdict,
        "enforce_state": verdict.enforce_state,
        "runs_seen": verdict.runs_seen,
        "runs_green": verdict.runs_green,
        "runs_red": verdict.runs_red,
        "flake_budget": verdict.flake_budget,
        "reason": verdict.reason,
    }
    return json.dumps(payload, sort_keys=True)


def _self_verify() -> int:
    """Check that the four canonical verdicts each round-trip.

    The self-verify mode is consumed by the workflow as a cheap
    sanity-check that the rollback-mock did not regress at
    import-time. It also catches any future helper-edit that
    accidentally drops one of the four verdict strings.
    """
    cases = [
        (
            "no-op when off",
            decide_rollback(
                enforce_state="0",
                recent_main_runs=[{"conclusion": "failure", "head_sha": "x"}],
            ),
            _VERDICT_NO_OP,
        ),
        (
            "hold when all green",
            decide_rollback(
                enforce_state="1",
                recent_main_runs=[
                    {"conclusion": "success", "head_sha": "a"},
                    {"conclusion": "success", "head_sha": "b"},
                ],
            ),
            _VERDICT_HOLD,
        ),
        (
            "recommend when red exceeds budget",
            decide_rollback(
                enforce_state="1",
                recent_main_runs=[
                    {"conclusion": "failure", "head_sha": "a"},
                    {"conclusion": "success", "head_sha": "b"},
                    {"conclusion": "failure", "head_sha": "c"},
                ],
                flake_budget=1,
            ),
            _VERDICT_RECOMMEND,
        ),
        (
            "escalate when all red",
            decide_rollback(
                enforce_state="1",
                recent_main_runs=[
                    {"conclusion": "failure", "head_sha": "a"},
                    {"conclusion": "failure", "head_sha": "b"},
                ],
            ),
            _VERDICT_ESCALATE,
        ),
    ]
    failed: list[str] = []
    for label, actual, expected in cases:
        if actual.verdict != expected:
            failed.append(
                f"  - {label}: expected {expected}, got {actual.verdict}"
            )
    if failed:
        sys.stderr.write("self-verify FAILED:\n")
        sys.stderr.write("\n".join(failed) + "\n")
        return 1
    sys.stdout.write("self-verify OK: all 4 canonical verdicts round-trip\n")
    return 0


def _parse_runs_argument(raw: str) -> list[dict]:
    """Parse a CLI ``--runs`` argument.

    The CLI accepts either a JSON list literal (preferred) or a
    shorthand comma-separated list of conclusions (e.g.
    ``success,success,failure``). The shorthand is convenient for
    a workflow-step that does not want to YAML-encode JSON inside
    a shell heredoc.
    """
    raw = raw.strip()
    if raw.startswith("["):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("--runs JSON must be a list")
        result: list[dict] = []
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError(
                    f"--runs[{i}] must be a dict, got {type(item).__name__}"
                )
            result.append(item)
        return result
    if not raw:
        return []
    return [
        {"conclusion": part.strip(), "head_sha": f"shorthand-{i}"}
        for i, part in enumerate(raw.split(","))
        if part.strip()
    ]


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mock-substrate for the REUSE-Wrap Pre-Merge Lint "
            "Enforce-Flip rollback decision-logic (Tag-63)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("decide", "self-verify"),
        default="decide",
        help=(
            "decide: emit a verdict for the given inputs. "
            "self-verify: assert the four canonical verdicts each "
            "round-trip cleanly. (Workflow uses self-verify as a "
            "cheap import-time sanity-check.)"
        ),
    )
    parser.add_argument(
        "--enforce-state",
        choices=_VALID_ENFORCE_STATES,
        default="1",
        help="current REUSE_WRAP_LINT_ENFORCE repo-var value",
    )
    parser.add_argument(
        "--runs",
        default="[]",
        help=(
            "recent main-branch runs, either a JSON list of "
            "{\"conclusion\": str, \"head_sha\": str} dicts, "
            "or a shorthand comma-separated conclusion list."
        ),
    )
    parser.add_argument(
        "--flake-budget",
        type=int,
        default=0,
        help="how many red runs to tolerate as flake before recommending rollback",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format for the verdict",
    )
    args = parser.parse_args(argv)

    if args.mode == "self-verify":
        return _self_verify()

    runs = _parse_runs_argument(args.runs)
    verdict = decide_rollback(
        enforce_state=args.enforce_state,
        recent_main_runs=runs,
        flake_budget=args.flake_budget,
    )
    if args.format == "json":
        sys.stdout.write(render_verdict_json(verdict) + "\n")
    else:
        sys.stdout.write(render_verdict_text(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
