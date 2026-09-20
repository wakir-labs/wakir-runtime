# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Guard for ``tooling/ci/skip_gate.py``.

``pytest`` exits 0 when every selected test is skipped. A lane built
around a skip-by-default marker therefore reports the same green for
"the opt-in was taken and 190 tests passed" and "the opt-in quietly
stopped working and nothing ran at all". The gate exists to separate
those two; these tests exist because a gate that cannot fail separates
nothing.

The central case is ``test_all_skipped_is_not_green``: a report in which
every test carries the opt-in skip reason, which is exactly the shape the
Phase-3c lane would produce if a flag were renamed in a conftest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tooling" / "ci" / "skip_gate.py"

OPT_IN_REASON = (
    "Phase-3c-Acceptance skeleton skip-by-default — opt in with "
    "WAKIR_PHASE_3C_E2E=1 env-var or --phase-3c-acceptance CLI flag"
)
CUTOVER_REASON = "pending welle-cutover — real perf-gauge wiring"


def _load_tool():
    spec = importlib.util.spec_from_file_location("_skip_gate", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_tool()


def _write_report(tmp_path: Path, cases: list[tuple[str, str | None]]) -> Path:
    """A JUnit XML with one testcase per entry; second item is the skip
    reason or ``None`` for a passing test."""
    body = []
    for name, reason in cases:
        if reason is None:
            body.append(f'<testcase classname="m" name="{name}"/>')
        else:
            body.append(
                f'<testcase classname="m" name="{name}">'
                f'<skipped type="pytest.skip" message="{reason}"/>'
                f"</testcase>"
            )
    path = tmp_path / "report.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite '
        f'name="pytest" tests="{len(cases)}">' + "".join(body) + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def test_all_skipped_is_not_green(tmp_path: Path) -> None:
    """The incident shape: 207 selected, 207 skipped, pytest exit 0."""
    report_path = _write_report(
        tmp_path, [(f"t{i}", OPT_IN_REASON) for i in range(207)]
    )
    report = gate.parse_junit(report_path)
    assert report.total == 207
    assert report.executed == 0
    problems = gate.evaluate(
        report, forbidden_skip_patterns=["skip-by-default"], min_executed=190
    )
    assert len(problems) == 2, problems
    assert "forbidden reason" in problems[0]
    assert "reached a verdict" in problems[1]


def test_the_real_shape_passes(tmp_path: Path) -> None:
    """190 executed, 17 skipped for a reason that is not the opt-in."""
    cases: list[tuple[str, str | None]] = [(f"p{i}", None) for i in range(190)]
    cases += [(f"s{i}", CUTOVER_REASON) for i in range(17)]
    report = gate.parse_junit(_write_report(tmp_path, cases))
    assert (report.total, report.executed, report.skipped) == (207, 190, 17)
    assert (
        gate.evaluate(
            report, forbidden_skip_patterns=["skip-by-default"], min_executed=190
        )
        == []
    )


def test_one_opt_in_skip_among_many_passes_is_still_a_problem(tmp_path: Path) -> None:
    """Partial regression — one marker's opt-in stops resolving while the
    other two keep working. The count floor alone would not catch it."""
    cases: list[tuple[str, str | None]] = [(f"p{i}", None) for i in range(200)]
    cases += [("s0", OPT_IN_REASON)]
    report = gate.parse_junit(_write_report(tmp_path, cases))
    problems = gate.evaluate(
        report, forbidden_skip_patterns=["skip-by-default"], min_executed=190
    )
    assert len(problems) == 1
    assert "1 test(s) skipped for a forbidden reason" in problems[0]


def test_executed_floor_catches_a_shrinking_selection(tmp_path: Path) -> None:
    report = gate.parse_junit(
        _write_report(tmp_path, [(f"p{i}", None) for i in range(12)])
    )
    problems = gate.evaluate(
        report, forbidden_skip_patterns=["skip-by-default"], min_executed=190
    )
    assert len(problems) == 1
    assert "only 12 test(s)" in problems[0]


def test_failures_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    path.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2">'
        '<testcase classname="m" name="a"/>'
        '<testcase classname="m" name="b"><failure message="boom"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    report = gate.parse_junit(path)
    assert (report.failed, report.executed) == (1, 2)
    problems = gate.evaluate(report, forbidden_skip_patterns=[], min_executed=None)
    assert len(problems) == 1 and "1 failure(s)" in problems[0]


def test_counts_come_from_the_testcases_not_the_summary_attributes(
    tmp_path: Path,
) -> None:
    """A ``<testsuite>`` whose attributes disagree with its contents is
    exactly the kind of summary this module refuses to trust."""
    path = tmp_path / "report.xml"
    path.write_text(
        '<?xml version="1.0"?><testsuites>'
        '<testsuite name="pytest" tests="207" skipped="0" failures="0">'
        '<testcase classname="m" name="only"><skipped message="x"/></testcase>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    report = gate.parse_junit(path)
    assert (report.total, report.skipped, report.executed) == (1, 1, 0)


def test_missing_report_is_an_error(tmp_path: Path) -> None:
    assert gate.main(["--junit", str(tmp_path / "nope.xml")]) == 1
