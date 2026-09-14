# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""What a lane targets, minus what it ignores — and why that matters here.

Two inventory facts are pinned in this module.

**``--ignore`` is subtracted.** A lane that points pytest at a directory
and then ignores three files inside it runs everything else in that
directory and nothing more. Crediting it with the three would put
modules in a lane that demonstrably does not run them, which is the one
claim ``tests/lanes/lane_assignment.json`` exists to make impossible.

**The observation lane does not double-target.** This is not tidiness.
The first run of ``test-observation-lane.yml`` on 2026-09-15 was red with
19 failures, and none of them said anything about the modules the lane
was built to observe:

* ``tests/infra/test_quadlet_lint.py`` has a lane in
  ``e2e-bringup-ci.yml`` that runs inside a Fedora 40 container **on
  purpose** — the workflow says so in a comment — because Ubuntu's
  podman 4.9 rejects a Quadlet key the units use. Run on
  ``ubuntu-latest`` it fails for a reason about the runner.
* ``tests/infra/test_pilot_bringup_e2e_container.py`` bind-mounts the
  checkout into a container and overwrites two committed SPIRE config
  files with stub content. In its own job nothing reads them again. In a
  shared session it took 14 later tests with it: one cause, sixteen
  symptoms, and the sixteen are the ones a reader sees first.

A module that already has a lane is not being observed by a second one;
it is being run again somewhere its lane deliberately is not. So the
rule is a rule, and it is checked here rather than remembered.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "tooling" / "ci" / "lane_inventory.py"
OBSERVATION_WORKFLOW = "test-observation-lane.yml"

pytest.importorskip("yaml")


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location(
        "wakir_lane_inventory_targets", INVENTORY_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wakir_lane_inventory_targets"] = module
    spec.loader.exec_module(module)
    return module


lane_inventory = _load_inventory_module()


# ---------------------------------------------------------------------------
# --ignore, on a throw-away tree.
# ---------------------------------------------------------------------------


def _tree(tmp_path: Path, command: str) -> Path:
    tests = tmp_path / "tests" / "sample"
    tests.mkdir(parents=True)
    for name in ("test_one.py", "test_two.py", "test_three.py"):
        (tests / name).write_text("def test_x():\n    pass\n", encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "sample.yml").write_text(
        textwrap.dedent(
            f"""\
            name: sample
            on:
              pull_request: {{}}
            jobs:
              run:
                name: sample job
                runs-on: ubuntu-latest
                steps:
                  - run: {command}
            """
        ),
        encoding="utf-8",
    )
    return tmp_path


def _resolved(root: Path) -> set[str]:
    lanes = lane_inventory.parse_workflows(root / ".github" / "workflows")
    assert len(lanes) == 1, f"expected one lane, parsed {len(lanes)}"
    return lane_inventory.resolve_lane_modules(lanes[0], root)


def test_a_directory_target_resolves_to_its_modules(tmp_path: Path) -> None:
    root = _tree(tmp_path, "python -m pytest tests/sample/")
    assert _resolved(root) == {
        "tests/sample/test_one.py",
        "tests/sample/test_two.py",
        "tests/sample/test_three.py",
    }


def test_ignore_equals_form_is_subtracted(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        "python -m pytest tests/sample/ --ignore=tests/sample/test_two.py",
    )
    assert _resolved(root) == {
        "tests/sample/test_one.py",
        "tests/sample/test_three.py",
    }


def test_ignore_separate_argument_form_is_subtracted(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        "python -m pytest tests/sample/ --ignore tests/sample/test_two.py",
    )
    assert _resolved(root) == {
        "tests/sample/test_one.py",
        "tests/sample/test_three.py",
    }


def test_the_ignore_value_is_not_mistaken_for_a_target(tmp_path: Path) -> None:
    """The bug this shape invites: ``--ignore X`` parsed as "ignore, and
    also run X". Subtracting then adding the same path is a no-op that
    looks correct in a diff."""
    root = _tree(
        tmp_path,
        "python -m pytest --ignore tests/sample/test_two.py tests/sample/",
    )
    assert "tests/sample/test_two.py" not in _resolved(root)


# ---------------------------------------------------------------------------
# The live observation lane.
# ---------------------------------------------------------------------------


def test_the_observation_lane_targets_nothing_that_has_another_lane() -> None:
    assignment = json.loads(
        (REPO_ROOT / "tests" / "lanes" / "lane_assignment.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = lane_inventory.build_inventory(
        REPO_ROOT, frozenset(assignment["required_contexts"])
    )
    doubled = {
        module: sorted(
            lane.split(":", 1)[0]
            for lane in entry["lanes"]
            if not lane.startswith(OBSERVATION_WORKFLOW)
        )
        for module, entry in sorted(inventory.items())
        if any(lane.startswith(OBSERVATION_WORKFLOW) for lane in entry["lanes"])
        and any(not lane.startswith(OBSERVATION_WORKFLOW) for lane in entry["lanes"])
    }
    assert not doubled, (
        "the observation lane also runs modules that already have a lane:\n  "
        + "\n  ".join(f"{m}: also in {lanes}" for m, lanes in doubled.items())
        + "\nThe observation lane exists for modules no workflow runs. A module "
        "with its own lane usually has one for a reason — a container image, a "
        "podman version, an install set — and running it here runs it in the "
        "environment its own lane deliberately avoids. Add an `--ignore=` entry "
        "for it in .github/workflows/test-observation-lane.yml."
    )


def test_the_observation_lane_still_targets_something() -> None:
    """Negative control for the assertion above: an over-eager ignore list
    could satisfy it by making the lane empty."""
    assignment = json.loads(
        (REPO_ROOT / "tests" / "lanes" / "lane_assignment.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = lane_inventory.build_inventory(
        REPO_ROOT, frozenset(assignment["required_contexts"])
    )
    observed = [
        module
        for module, entry in inventory.items()
        if any(lane.startswith(OBSERVATION_WORKFLOW) for lane in entry["lanes"])
    ]
    assert len(observed) >= 70, (
        f"the observation lane targets only {len(observed)} modules; it was "
        "built for 80. An ignore list that grows until the lane is empty is a "
        "lane that has been switched off one line at a time."
    )
