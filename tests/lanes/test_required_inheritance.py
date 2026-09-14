# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""A gate job under an aggregator is required — but only while the wiring holds.

ADR-0075 §1 settles the aggregation question: the binding pattern is a
sammel-job *inside* one workflow with ``if: always()`` and an explicit
per-dependency ``needs.<job>.result`` check, not a second required status
context per lane. §1.7 of the CTO decision paper draws the operational
consequence — new lanes are **attached** to that aggregator instead of
being registered in branch protection, because a new required context
means a branch-protection change plus exact display names (the PR #102
forever-pending class).

That makes a derivation question unavoidable. A gate job attached this
way is not itself a branch-protection context, but a red gate job turns
the aggregator red, and the aggregator blocks the merge. For the
question ``tests/lanes/lane_assignment.json`` answers — *which profile is
this module in* — the honest answer is ``required``.

The inheritance is not unconditional, and that is the substance of this
module. It is granted only while all three halves of the propagation are
intact: ``needs:``, job-level ``always()``, and the first unconditional
step turning each dependency result into the job's own exit code. Break
any one and the inheritance stops.

Why that matters beyond bookkeeping: adding a job to ``needs:`` and
forgetting it in the result check is exactly finding R6, the fail-open
class, in the exact file it was found in. With this derivation the
omission surfaces a second, independent time — as a module whose
declared ``required`` profile no longer matches what the workflows do,
i.e. as a red ``test_declared_profile_matches_workflows``. Two unrelated
guards over one defect class, which is the point of having two.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "tooling" / "ci" / "lane_inventory.py"

pytest.importorskip("yaml")


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location(
        "wakir_lane_inventory_inheritance", INVENTORY_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wakir_lane_inventory_inheritance"] = module
    spec.loader.exec_module(module)
    return module


lane_inventory = _load_inventory_module()

REQUIRED = frozenset({"the required context"})


AGGREGATOR_TEMPLATE = """\
name: synthetic
on:
  pull_request: {{}}
jobs:
  gate-a:
    name: Gate-A
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest tests/synthetic/
  aggregate:
    name: the required context
    needs:
      - gate-a
{condition}    steps:
{guard}      - run: echo substance
"""

ALWAYS = "    if: always()\n"

GUARD = """\
      - name: Require every gate job to have succeeded
        env:
          GATE_RESULTS: |
            gate-a=${{ needs.gate-a.result }}
        run: test "${GATE_RESULTS#*=}" = success
"""

GUARD_WITHOUT_GATE_A = """\
      - name: Require every gate job to have succeeded
        env:
          GATE_RESULTS: |
            gate-b=${{ needs.gate-b.result }}
        run: test "${GATE_RESULTS#*=}" = success
"""

CONDITIONAL_GUARD = """\
      - name: Require every gate job to have succeeded
        if: success()
        env:
          GATE_RESULTS: |
            gate-a=${{ needs.gate-a.result }}
        run: test "${GATE_RESULTS#*=}" = success
"""


def _write(tmp_path: Path, body: str) -> Path:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "synthetic.yml").write_text(textwrap.dedent(body), encoding="utf-8")
    return workflow_dir


def test_gate_job_inherits_when_the_wiring_is_complete(tmp_path: Path) -> None:
    workflow_dir = _write(
        tmp_path, AGGREGATOR_TEMPLATE.format(condition=ALWAYS, guard=GUARD)
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == {
        ("synthetic.yml", "gate-a")
    }


def test_no_inheritance_when_the_result_check_forgets_the_job(tmp_path: Path) -> None:
    """The R6 omission, restated as a derivation fact.

    ``gate-a`` is in ``needs:`` and the aggregator runs on ``always()``,
    but nothing turns ``needs.gate-a.result`` into an exit code. The
    aggregator can therefore report green over a red ``gate-a`` — so
    ``gate-a`` enforces nothing and its modules are not required.
    """
    workflow_dir = _write(
        tmp_path,
        AGGREGATOR_TEMPLATE.format(condition=ALWAYS, guard=GUARD_WITHOUT_GATE_A),
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == set()


def test_no_inheritance_without_job_level_always(tmp_path: Path) -> None:
    """Without ``always()`` a red dependency *skips* the aggregator, and a
    skipped required check does not block a merge."""
    workflow_dir = _write(
        tmp_path, AGGREGATOR_TEMPLATE.format(condition="", guard=GUARD)
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == set()


def test_no_inheritance_when_the_guard_is_conditional(tmp_path: Path) -> None:
    """A conditional first step can be skipped, and then it fails open again."""
    workflow_dir = _write(
        tmp_path,
        AGGREGATOR_TEMPLATE.format(condition=ALWAYS, guard=CONDITIONAL_GUARD),
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == set()


def test_no_inheritance_when_the_guard_is_not_the_first_step(tmp_path: Path) -> None:
    """A later check is one a green earlier step can paper over."""
    workflow_dir = _write(
        tmp_path,
        """\
        name: synthetic
        on:
          pull_request: {}
        jobs:
          gate-a:
            name: Gate-A
            runs-on: ubuntu-latest
            steps:
              - run: python -m pytest tests/synthetic/
          aggregate:
            name: the required context
            needs:
              - gate-a
            if: always()
            steps:
              - run: echo substance
              - name: Require every gate job to have succeeded
                env:
                  GATE_RESULTS: |
                    gate-a=${{ needs.gate-a.result }}
                run: test "${GATE_RESULTS#*=}" = success
        """,
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == set()


def test_inheritance_is_transitive_only_while_propagation_holds(tmp_path: Path) -> None:
    """A chain propagates exactly as far as every link checks its results."""
    workflow_dir = _write(
        tmp_path,
        """\
        name: synthetic
        on:
          pull_request: {}
        jobs:
          leaf:
            name: Leaf
            runs-on: ubuntu-latest
            steps:
              - run: python -m pytest tests/synthetic/
          middle:
            name: Middle
            needs:
              - leaf
            if: always()
            steps:
              - name: guard
                env:
                  R: ${{ needs.leaf.result }}
                run: test "$R" = success
          aggregate:
            name: the required context
            needs:
              - middle
            if: always()
            steps:
              - name: guard
                env:
                  R: ${{ needs.middle.result }}
                run: test "$R" = success
        """,
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == {
        ("synthetic.yml", "middle"),
        ("synthetic.yml", "leaf"),
    }


def test_chain_stops_at_the_first_broken_link(tmp_path: Path) -> None:
    workflow_dir = _write(
        tmp_path,
        """\
        name: synthetic
        on:
          pull_request: {}
        jobs:
          leaf:
            name: Leaf
            runs-on: ubuntu-latest
            steps:
              - run: python -m pytest tests/synthetic/
          middle:
            name: Middle
            needs:
              - leaf
            steps:
              - name: guard
                env:
                  R: ${{ needs.leaf.result }}
                run: test "$R" = success
          aggregate:
            name: the required context
            needs:
              - middle
            if: always()
            steps:
              - name: guard
                env:
                  R: ${{ needs.middle.result }}
                run: test "$R" = success
        """,
    )
    assert lane_inventory.inherited_required_jobs(workflow_dir, REQUIRED) == {
        ("synthetic.yml", "middle")
    }


# ---------------------------------------------------------------------------
# The live tree.
# ---------------------------------------------------------------------------


def test_the_live_acceptance_gate_aggregator_propagates_to_every_gate_job() -> None:
    """Negative control for the assertions above against the real file.

    If ``runtime-acceptance-gates.yml`` ever stops propagating, the
    synthetic cases above would still pass while the repository quietly
    lost its enforcement. This pins the live wiring: every job the
    aggregator declares in ``needs:`` inherits.
    """
    yaml = pytest.importorskip("yaml")
    path = REPO_ROOT / ".github" / "workflows" / "runtime-acceptance-gates.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    aggregator = data["jobs"]["runtime-acceptance-gates"]
    declared = set(aggregator["needs"])
    assert declared, "the aggregator declares no dependencies — implausible"

    inherited = lane_inventory.inherited_required_jobs(
        REPO_ROOT / ".github" / "workflows",
        frozenset({"runtime acceptance gates"}),
    )
    missing = sorted(declared - {job for wf, job in inherited if wf == path.name})
    assert not missing, (
        "jobs the acceptance-gate aggregator depends on but whose result "
        "its first step does not check: "
        f"{missing}. That is a fail-open gate (finding R6): the aggregator "
        "can report green while one of them is red. Add each job to the "
        "GATE_RESULTS block in the same edit that adds it to `needs:`."
    )
