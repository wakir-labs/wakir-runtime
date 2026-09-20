# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""A lane that skips everything it was built to run still exits 0.

Why this file exists
--------------------

``tooling/ci/collect_gate.py`` closes one half of the "green but empty"
class: a module that vanishes into an import guard yields zero node IDs
and a clean exit. This closes the other half. ``pytest`` exits 0 when
every selected test is *skipped*, so a lane wired around a skip-by-default
marker reports success in exactly two situations that look identical from
outside: the opt-in was taken and the tests passed, or the opt-in silently
stopped working and nothing ran.

That is not hypothetical here. The Phase-3c acceptance suite -- 207 tests,
the written acceptance criteria for the 2026-05-20 cutover -- sat behind
``WAKIR_PHASE_3C_E2E`` / ``--phase-3c-acceptance`` and friends and was
never switched on by any workflow. Its lane is only worth having if the
lane can tell "ran and passed" from "skipped and passed". Renaming an
opt-in flag in a conftest, or dropping one of the three from the pytest
invocation, would otherwise leave the lane green and empty.

What it checks
--------------

Against a JUnit XML report:

* ``--forbid-skip-reason PATTERN`` -- no test may be skipped for a reason
  matching the pattern. Used with the opt-in wording, this is the
  vacuity guard and needs no maintenance as the suite grows.
* ``--min-executed N`` -- at least N tests must have run to a verdict
  (passed or failed; skipped does not count). A coarser net for the case
  where tests disappear from the selection entirely.

Failures and errors in the report are reported too, though pytest's own
exit code already covers those; carrying them here keeps a single
readable summary in the job log.

Usage::

    python -m pytest ... --junitxml=report.xml
    python tooling/ci/skip_gate.py --junit report.xml \\
        --forbid-skip-reason "skip-by-default" --min-executed 190
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Report:
    """Flattened counts plus the skip reasons, from a JUnit XML file."""

    total: int = 0
    skipped: int = 0
    failed: int = 0
    errored: int = 0
    skips: list[tuple[str, str]] = field(default_factory=list)

    @property
    def executed(self) -> int:
        """Tests that reached a verdict. Skipped tests did not."""
        return self.total - self.skipped


def parse_junit(path: Path) -> Report:
    """Counts from a JUnit XML report, one entry per ``<testcase>``.

    Counted from the test cases rather than the ``<testsuite>``
    attributes on purpose: the attributes are a summary someone else
    wrote, and this module exists because summaries can be true and
    empty at the same time.
    """
    root = ET.parse(path).getroot()
    cases = root.iter("testcase")
    report = Report()
    for case in cases:
        report.total += 1
        name = "{}::{}".format(
            case.get("classname", "") or "<no-class>", case.get("name", "") or "<no-name>"
        )
        skipped = case.find("skipped")
        if skipped is not None:
            report.skipped += 1
            reason = skipped.get("message") or (skipped.text or "")
            report.skips.append((name, reason.strip()))
            continue
        if case.find("failure") is not None:
            report.failed += 1
        if case.find("error") is not None:
            report.errored += 1
    return report


def evaluate(
    report: Report,
    *,
    forbidden_skip_patterns: list[str],
    min_executed: int | None,
) -> list[str]:
    """Problems found. Empty list means the gate passes."""
    problems: list[str] = []

    for pattern in forbidden_skip_patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        hits = [(name, reason) for name, reason in report.skips if compiled.search(reason)]
        if hits:
            problems.append(
                f"{len(hits)} test(s) skipped for a forbidden reason "
                f"(pattern {pattern!r}). The lane did not execute what it "
                f"selected; a green result here means nothing. First few:\n"
                + "\n".join(f"    {name}: {reason}" for name, reason in hits[:5])
            )

    if min_executed is not None and report.executed < min_executed:
        problems.append(
            f"only {report.executed} test(s) reached a verdict; at least "
            f"{min_executed} expected. Either tests were removed without "
            f"updating this floor, or the selection stopped matching them."
        )

    if report.failed or report.errored:
        problems.append(
            f"{report.failed} failure(s) and {report.errored} error(s) in the report."
        )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument(
        "--forbid-skip-reason",
        action="append",
        default=[],
        metavar="PATTERN",
        help="regex; no test may be skipped for a reason matching it",
    )
    parser.add_argument("--min-executed", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.junit.exists():
        print(f"skip-gate: no report at {args.junit}", file=sys.stderr)
        return 1

    report = parse_junit(args.junit)
    print(
        f"skip-gate: {report.total} test(s); {report.executed} executed, "
        f"{report.skipped} skipped, {report.failed} failed, {report.errored} errored."
    )
    for name, reason in report.skips:
        print(f"skip-gate: skipped {name}: {reason}")

    problems = evaluate(
        report,
        forbidden_skip_patterns=args.forbid_skip_reason,
        min_executed=args.min_executed,
    )
    if problems:
        for problem in problems:
            print(f"::error::skip-gate: {problem}")
        return 1
    print("skip-gate: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
