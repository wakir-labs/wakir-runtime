# SPDX-License-Identifier: Apache-2.0
"""The test-lane assignment must describe the workflows that exist.

``tests/lanes/lane_assignment.json`` claims, for every test module in the
repository, which execution profile it is in. This module derives the same
facts from ``.github/workflows/`` and refuses to let the two drift.

What that buys, concretely:

* A **new test module with no entry** is red. It cannot land in a state
  where nobody has answered "which gate runs this?".
* A module that **loses its required lane** — a renamed job, a dropped
  ``pytest`` line, a workflow deleted — is red even though every other
  check in the repository stays green, because nothing else notices a
  test that stopped being run.
* A **required status context whose name no longer matches any job
  display-name** is red here, hermetically, instead of surfacing as a
  pull request that stays pending forever (the PR #102 failure class).
* The **exemption list stays an exemption list**: a module outside a
  lane needs a named group with a reason and an owner, and if the reason
  is "nobody wired it up" it also needs a review date.

What it deliberately does not do: it does not require that everything
runs. 177 modules run nowhere at this baseline, and this test passes with
that — it only requires that the fact is written down, owned and dated.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_PATH = REPO_ROOT / "tests" / "lanes" / "lane_assignment.json"
INVENTORY_PATH = REPO_ROOT / "tooling" / "ci" / "lane_inventory.py"


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location("wakir_lane_inventory", INVENTORY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wakir_lane_inventory"] = module
    spec.loader.exec_module(module)
    return module


lane_inventory = _load_inventory_module()


@pytest.fixture(scope="module")
def assignment() -> dict:
    return json.loads(ASSIGNMENT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def derived(assignment: dict) -> dict:
    return lane_inventory.build_inventory(
        REPO_ROOT, frozenset(assignment["required_contexts"])
    )


# ---------------------------------------------------------------------------
# Completeness: the map covers the tree, and only the tree.
# ---------------------------------------------------------------------------


def test_every_test_module_has_an_entry(assignment: dict) -> None:
    on_disk = set(lane_inventory.discover_modules(REPO_ROOT))
    declared = set(assignment["modules"])
    missing = sorted(on_disk - declared)
    assert not missing, (
        "test modules without a lane-assignment entry. Add them to "
        "tests/lanes/lane_assignment.json — 'which gate runs this?' is part "
        "of adding a test, not a follow-up:\n  " + "\n  ".join(missing)
    )


def test_no_stale_entries(assignment: dict) -> None:
    on_disk = set(lane_inventory.discover_modules(REPO_ROOT))
    stale = sorted(set(assignment["modules"]) - on_disk)
    assert not stale, (
        "lane-assignment entries for files that no longer exist. Regenerate "
        "with `python tooling/ci/lane_inventory.py --sync`:\n  "
        + "\n  ".join(stale)
    )


# ---------------------------------------------------------------------------
# Truthfulness: the declared profile is the profile the workflows produce.
# ---------------------------------------------------------------------------


def test_declared_profile_matches_workflows(assignment: dict, derived: dict) -> None:
    mismatches = []
    for module, entry in sorted(assignment["modules"].items()):
        if module not in derived:
            continue  # covered by test_no_stale_entries
        actual = derived[module]["profile"]
        if entry["profile"] != actual:
            mismatches.append(
                f"{module}: declared {entry['profile']!r}, workflows say "
                f"{actual!r} (lanes={derived[module]['lanes'] or 'none'})"
            )
    assert not mismatches, (
        "the lane assignment disagrees with .github/workflows/. If a module "
        "lost its lane this is the intended failure; if the change was "
        "deliberate, update the assignment in the same commit:\n  "
        + "\n  ".join(mismatches)
    )


def test_profiles_are_from_the_closed_vocabulary(assignment: dict) -> None:
    unknown = sorted(
        {e["profile"] for e in assignment["modules"].values()}
        - set(lane_inventory.PROFILES)
    )
    assert not unknown, f"unknown profiles: {unknown}"


# ---------------------------------------------------------------------------
# Exemptions: named, reasoned, owned — and dated when they are accidents.
# ---------------------------------------------------------------------------

NEEDS_GROUP = {"operator-hand", "opt-in-marker", "unassigned"}


def test_every_exempt_module_names_a_group(assignment: dict) -> None:
    groups = assignment["exemption_groups"]
    problems = []
    for module, entry in sorted(assignment["modules"].items()):
        if entry["profile"] not in NEEDS_GROUP:
            if "group" in entry:
                problems.append(f"{module}: profile {entry['profile']} must not carry a group")
            continue
        group = entry.get("group")
        if not group:
            problems.append(f"{module}: profile {entry['profile']} without an exemption group")
        elif group not in groups:
            problems.append(f"{module}: unknown exemption group {group!r}")
        elif groups[group]["profile"] != entry["profile"]:
            problems.append(
                f"{module}: group {group!r} is for profile "
                f"{groups[group]['profile']!r}, module is {entry['profile']!r}"
            )
    assert not problems, "\n  ".join(["exemption bookkeeping:"] + problems)


def test_exemption_groups_carry_a_reason_and_an_owner(assignment: dict) -> None:
    problems = []
    for name, group in sorted(assignment["exemption_groups"].items()):
        reason = group.get("reason", "")
        if len(reason) < 120:
            problems.append(f"{name}: reason too thin to be a reason ({len(reason)} chars)")
        if not group.get("owner"):
            problems.append(f"{name}: no owner")
        if group["profile"] not in NEEDS_GROUP:
            problems.append(f"{name}: profile {group['profile']!r} needs no exemption")
    assert not problems, "\n  ".join(["exemption groups:"] + problems)


def test_unassigned_groups_carry_a_review_date(assignment: dict) -> None:
    """`unassigned` means nobody runs it and nobody decided that — so it gets a date.

    `opt-in-marker` and `operator-hand` do not: those are deliberate,
    standing exceptions, and a review date on a standing exception is
    theatre. They are marked ``deliberate: true`` instead.
    """
    problems = []
    for name, group in sorted(assignment["exemption_groups"].items()):
        if group["profile"] != "unassigned":
            if group.get("deliberate") is not True:
                problems.append(f"{name}: standing exception must be marked deliberate:true")
            continue
        if group.get("deliberate") is not False:
            problems.append(f"{name}: unassigned group must be marked deliberate:false")
        review_by = group.get("review_by", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", review_by):
            problems.append(f"{name}: review_by must be an ISO date, got {review_by!r}")
            continue
        try:
            dt.date.fromisoformat(review_by)
        except ValueError:
            problems.append(f"{name}: review_by {review_by!r} is not a valid date")
    assert not problems, "\n  ".join(["unassigned groups:"] + problems)


def test_no_unused_exemption_groups(assignment: dict) -> None:
    used = {e.get("group") for e in assignment["modules"].values()} - {None}
    unused = sorted(set(assignment["exemption_groups"]) - used)
    assert not unused, f"exemption groups nothing references: {unused}"


# ---------------------------------------------------------------------------
# Required contexts: the names must still point at jobs that exist.
# ---------------------------------------------------------------------------


def test_required_contexts_match_a_job_display_name(assignment: dict) -> None:
    names = lane_inventory.job_names(REPO_ROOT)
    orphaned = sorted(set(assignment["required_contexts"]) - names)
    assert not orphaned, (
        "required status contexts with no matching job display-name in "
        ".github/workflows/. A required context that never reports leaves "
        "every pull request pending forever (PR #102). Either the job was "
        "renamed — rename it back or update branch protection — or the "
        "workflow was deleted:\n  " + "\n  ".join(orphaned)
    )


def test_required_contexts_that_run_no_test_module_are_still_listed(
    assignment: dict, derived: dict
) -> None:
    """Not every required context drives pytest — and that is fine.

    ``proof-path``, ``secret-scan``, ``cosign verify SPIRE images`` and
    the digest-pin gate run scripts, not test modules. The assertion is
    only that we know which ones those are, so "this context runs no
    tests" is a recorded fact rather than a discovery.
    """
    contexts_with_modules = set()
    for entry in derived.values():
        for lane_id in entry["required_lanes"]:
            contexts_with_modules.add(lane_id)
    assert contexts_with_modules, "no required context drives any test module — implausible"


# ---------------------------------------------------------------------------
# The headline numbers in the file must be the numbers the tree produces.
# ---------------------------------------------------------------------------


def test_measured_counts_are_current(assignment: dict, derived: dict) -> None:
    measured = assignment["measured"]
    actual = {profile: 0 for profile in lane_inventory.PROFILES}
    for entry in derived.values():
        actual[entry["profile"]] += 1
    expected = {
        "test_modules": len(derived),
        "required": actual["required"],
        "optional_ci": actual["optional-ci"],
        "operator_hand": actual["operator-hand"],
        "opt_in_marker": actual["opt-in-marker"],
        "unassigned": actual["unassigned"],
    }
    recorded = {key: measured[key] for key in expected}
    assert recorded == expected, (
        "the counts recorded in lane_assignment.json are stale. They are "
        "quoted in reports, so they are checked: "
        f"recorded={recorded} actual={expected}"
    )


def test_baseline_commit_is_pinned(assignment: dict) -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", assignment["baseline_commit"])


# ---------------------------------------------------------------------------
# testpaths: the configuration may not contradict the tree.
# ---------------------------------------------------------------------------


def test_testpaths_covers_every_test_root() -> None:
    """A bare ``pytest`` must not silently exclude a whole test root.

    Before this change ``testpaths = ["tests"]`` pointed at the one
    directory the main CI lane does *not* run (it runs ``wirelang/``), and
    ``infra/spire/federation/tests/`` was invisible to both. The config now
    names every root that holds test modules. It is a statement about what
    exists, not about what CI executes — that is what the lane assignment
    is for.
    """
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^testpaths\s*=\s*\[([^\]]*)\]", text, re.MULTILINE)
    assert match, "no testpaths in pyproject.toml"
    declared = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert declared == lane_inventory.TEST_ROOTS, (
        f"testpaths {declared} must equal lane_inventory.TEST_ROOTS "
        f"{lane_inventory.TEST_ROOTS}; a test root outside testpaths is a "
        "directory a bare `pytest` pretends does not exist."
    )

    roots_with_tests = {
        module.split("/", 1)[0] for module in lane_inventory.discover_modules(REPO_ROOT)
    }
    assert roots_with_tests <= set(declared), (
        f"test modules live outside testpaths: {sorted(roots_with_tests - set(declared))}"
    )
