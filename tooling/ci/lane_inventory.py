#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Static test-lane inventory for ``wakir-runtime``.

Answers one question mechanically: **which workflow job, if any, points a
test runner at this test module?**

The repository has two test roots (``tests/`` and ``wirelang/``) plus a
third one nobody expects (``infra/spire/federation/tests/``), and CI does
not run any of them wholesale except ``wirelang/``. Most lanes name
individual files. That is a perfectly legitimate design, but it is only
auditable if the mapping is written down and checked — which is what this
module and ``tests/lanes/lane_assignment.json`` do together.

Scope and honesty about it
--------------------------

This is **targeting**, not execution:

* A module counted as "in a lane" is one a runner is pointed at. Whether
  it then collects zero tests (``pytest.importorskip`` at module level) or
  skips at runtime (markers, ``skipif``) is a *runtime* property. The
  companion ``collect_gate.py`` covers the zero-collection half.
* Directory targets are resolved by globbing ``test_*.py`` underneath.
  Verified against a real ``--collect-only`` run at the baseline commit:
  identical sets, with the single documented exception of
  ``tests/wat/external_verifier/test_python_bitcoinlib_drift.py`` which is
  targeted but collects nothing without the matrix-only
  ``python-bitcoinlib``.
* Both ``pytest`` and ``python -m unittest`` invocations are parsed.
  Three workflows — one of them a *required* context — drive test modules
  through ``unittest``, so a pytest-only scan under-reports.

Usage::

    python tooling/ci/lane_inventory.py            # human-readable summary
    python tooling/ci/lane_inventory.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: Directories that hold test modules. ``infra/`` is included because
#: ``infra/spire/federation/tests/`` exists and is easy to overlook.
TEST_ROOTS: tuple[str, ...] = ("tests", "wirelang", "infra")

_JOB_ID_RE = re.compile(r"^  (?P<job_id>[A-Za-z0-9_-]+):\s*$")
_JOB_NAME_RE = re.compile(r"^    name:\s*(?P<name>.+?)\s*$")
_JOBS_RE = re.compile(r"^jobs:\s*$")
_ON_RE = re.compile(r"""^["']?on["']?:\s*$""")
_EVENT_RE = re.compile(r"^  ([a-z_]+):")
_ARRAY_RE = re.compile(r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)=\(\s*$")
_ARRAY_EXPANSION_RE = re.compile(r'"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)\[@\]\}"')


@dataclass(frozen=True)
class Lane:
    """One test-runner invocation inside one workflow job."""

    workflow: str
    job_id: str
    job_name: str
    line: int
    runner: str  # "pytest" | "unittest"
    targets: tuple[str, ...]
    unresolved: tuple[str, ...] = field(default=())
    events: tuple[str, ...] = field(default=())
    path_filtered: bool = False

    @property
    def lane_id(self) -> str:
        return f"{self.workflow}:{self.job_id}:{self.line}"

    @property
    def reachability(self) -> str:
        """How a change can reach this lane.

        ``pr`` is the only value that makes a lane a merge-time signal;
        ``pr-path-filtered`` still requires the change to touch one of the
        workflow's ``paths:`` entries, which is why "the module is in a
        lane" and "the lane runs when the module's subject changes" are
        two different claims.
        """
        if "pull_request" in self.events:
            return "pr-path-filtered" if self.path_filtered else "pr"
        if "push" in self.events:
            return "push-only"
        if "schedule" in self.events:
            return "schedule"
        return "dispatch"


def discover_modules(root: Path = REPO_ROOT) -> list[str]:
    """Every ``test_*.py`` under the known test roots, repo-relative."""
    found: set[str] = set()
    for test_root in TEST_ROOTS:
        base = root / test_root
        if not base.is_dir():
            continue
        for path in base.rglob("test_*.py"):
            if any(part in {".git", ".venv", "node_modules", "target"} for part in path.parts):
                continue
            found.add(path.relative_to(root).as_posix())
    return sorted(found)


def _strip_yaml_noise(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#"):
        return ""
    if stripped.startswith("- name:") or stripped.startswith("name:"):
        return ""
    if stripped.startswith("description:"):
        return ""
    # `run: python -m pytest ...` on a single line
    stripped = re.sub(r"^-?\s*run:\s*", "", stripped)
    # `result=$(python -m pytest ...)` capture form
    stripped = re.sub(r"^\w+=\$\(", "", stripped)
    return stripped


def _join_continuations(lines: list[str], index: int) -> tuple[str, int]:
    cmd = _strip_yaml_noise(lines[index])
    cursor = index
    while cmd.rstrip().endswith("\\"):
        cursor += 1
        if cursor >= len(lines):
            break
        cmd = cmd.rstrip()[:-1] + " " + lines[cursor].strip()
    return cmd, cursor


def parse_triggers(workflow: Path) -> tuple[tuple[str, ...], bool]:
    """``(events, path_filtered)`` for one workflow file.

    Both ``on:`` and the quoted ``"on":`` spelling occur in this repo.
    ``path_filtered`` is True when any event carries a ``paths:`` filter.
    """
    lines = workflow.read_text(encoding="utf-8").splitlines()
    events: list[str] = []
    path_filtered = False
    inside = False
    for line in lines:
        if _ON_RE.match(line):
            inside = True
            continue
        if inside:
            if line and not line.startswith(" ") and not line.startswith("#"):
                break
            match = _EVENT_RE.match(line)
            if match:
                events.append(match.group(1))
            if re.match(r"^\s+paths(-ignore)?:\s*$", line):
                path_filtered = True
    return tuple(events), path_filtered


def _bash_arrays(lines: list[str]) -> dict[str, list[str]]:
    """Collect simple ``VAR=( ... )`` bash arrays defined in a workflow.

    Needed for ``live-vm-acceptance.yml``, which builds its pytest
    argument vector in an array and then expands it. Without this the
    lane looks like it targets nothing.
    """
    arrays: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        match = _ARRAY_RE.match(lines[i])
        if match:
            items: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != ")":
                token = lines[j].strip()
                if token and not token.startswith("#"):
                    items.extend(shlex.split(token))
                j += 1
            arrays[match.group("var")] = items
            i = j
        i += 1
    return arrays


def _split_runner_args(tokens: list[str]) -> tuple[str, list[str]] | None:
    for runner in ("pytest", "unittest"):
        if runner in tokens:
            return runner, tokens[tokens.index(runner) + 1 :]
    return None


def _targets_from_args(runner: str, args: list[str]) -> tuple[list[str], list[str]]:
    """Return (resolved-target-strings, unresolved-tokens)."""
    targets: list[str] = []
    unresolved: list[str] = []
    skip_next = False
    for idx, token in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if token in {"-k", "-m", "--junitxml", "--junit-xml", "--override-ini"}:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if "${" in token or token.startswith("$"):
            unresolved.append(token)
            continue
        if runner == "unittest":
            # dotted module path -> file path
            targets.append(token.replace(".", "/") + ".py")
        else:
            targets.append(token)
        del idx
    return targets, unresolved


def parse_workflows(workflow_dir: Path = WORKFLOW_DIR) -> list[Lane]:
    """Every pytest/unittest invocation in every workflow, with its job."""
    lanes: list[Lane] = []
    for workflow in sorted(workflow_dir.glob("*.yml")):
        lines = workflow.read_text(encoding="utf-8").splitlines()
        arrays = _bash_arrays(lines)
        events, path_filtered = parse_triggers(workflow)
        job_id = job_name = "<unknown>"
        in_jobs = False
        i = 0
        while i < len(lines):
            raw = lines[i]
            if _JOBS_RE.match(raw):
                in_jobs = True
            elif in_jobs:
                job_match = _JOB_ID_RE.match(raw)
                if job_match:
                    job_id = job_match.group("job_id")
                    job_name = job_id
                else:
                    name_match = _JOB_NAME_RE.match(raw)
                    if name_match:
                        job_name = name_match.group("name").strip("'\"")
            cmd, end = _join_continuations(lines, i)
            if cmd and ("pytest" in cmd or "unittest" in cmd):
                cmd = cmd.split(">")[0]
                for var, items in arrays.items():
                    if _ARRAY_EXPANSION_RE.search(cmd) and var in cmd:
                        cmd = _ARRAY_EXPANSION_RE.sub(" ".join(items), cmd)
                try:
                    tokens = shlex.split(cmd)
                except ValueError:
                    tokens = []
                split = _split_runner_args(tokens)
                if split and "install" not in tokens:
                    runner, args = split
                    targets, unresolved = _targets_from_args(runner, args)
                    if targets or unresolved:
                        lanes.append(
                            Lane(
                                workflow=workflow.name,
                                job_id=job_id,
                                job_name=job_name,
                                line=i + 1,
                                runner=runner,
                                targets=tuple(targets),
                                unresolved=tuple(unresolved),
                                events=events,
                                path_filtered=path_filtered,
                            )
                        )
                i = end
            i += 1
    return lanes


def resolve_lane_modules(lane: Lane, root: Path = REPO_ROOT) -> set[str]:
    """Test modules a lane points its runner at (targeting, not execution)."""
    modules: set[str] = set()
    for target in lane.targets:
        path_part = target.split("::", 1)[0]
        candidate = root / path_part
        if candidate.is_dir():
            for path in candidate.rglob("test_*.py"):
                modules.add(path.relative_to(root).as_posix())
        elif candidate.is_file() and candidate.name.startswith("test_"):
            modules.add(candidate.relative_to(root).as_posix())
    return modules


#: Markers that are skipped unless explicitly opted in (see
#: ``[tool.pytest.ini_options] markers`` in ``pyproject.toml`` and the
#: ``--phase-3c-*`` / ``--rollback-drill`` flags in ``conftest.py``).
OPT_IN_MARKERS: tuple[str, ...] = (
    "phase_3_skeleton",
    "phase_3c_acceptance",
    "phase_3c_doppel_welle_acceptance",
    "phase_3c_rollback_drill",
    "live_vm",
)

#: The five profiles a module can be in. Exactly one applies.
PROFILES: tuple[str, ...] = (
    "required",       # a required status context points a runner at it
    "optional-ci",    # a non-required workflow runs it on PR/push/schedule
    "operator-hand",  # only reachable via workflow_dispatch
    "opt-in-marker",  # no lane; guarded by a skip-by-default marker
    "unassigned",     # no lane, no marker: nothing runs it, ever
)


def module_opt_in_markers(module: str, root: Path = REPO_ROOT) -> list[str]:
    """Skip-by-default markers a module carries at module level."""
    try:
        text = (root / module).read_text(encoding="utf-8")
    except OSError:
        return []
    return [m for m in OPT_IN_MARKERS if f"pytest.mark.{m}" in text]


def derive_profile(entry: dict) -> str:
    """The profile a module *actually* has, from workflow facts alone.

    This is the value ``tests/lanes/lane_assignment.json`` is checked
    against. Nothing here reads the declaration, so a declaration cannot
    talk the derivation into agreeing with it.
    """
    if entry["required_lanes"]:
        return "required"
    if entry["lanes"]:
        if all(r == "dispatch" for r in entry["reachability"]):
            return "operator-hand"
        return "optional-ci"
    if entry["opt_in_markers"]:
        return "opt-in-marker"
    return "unassigned"


#: Jobs that are not themselves a required context but whose result is
#: turned into a required context's exit code. See
#: ``inherited_required_jobs`` for why this is a profile-relevant fact
#: and not a convenience.
InheritedJob = tuple[str, str]  # (workflow file name, job id)


def _yaml():
    """PyYAML, imported late and loudly.

    The inheritance derivation below decides whether a module is
    ``required`` or merely ``optional-ci``. Degrading to "no inheritance"
    when PyYAML happens to be absent would make the derived profile a
    function of the local install set, and a lane assignment that changes
    meaning with the environment is worse than none. So: hard error, with
    the install hint in it.
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "lane_inventory needs PyYAML to resolve which jobs inherit a "
            "required context's enforcement. Install it "
            "(`pip install PyYAML`, or the `test` extra) — do not run this "
            "tool without it, because the answer would silently change."
        ) from exc
    return yaml


def _workflow_documents(workflow_dir: Path) -> dict[str, dict]:
    yaml = _yaml()
    out: dict[str, dict] = {}
    for path in sorted(workflow_dir.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out[path.name] = data
    return out


def _needs_list(job: dict) -> list[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return [needs]
    return [n for n in (needs or []) if isinstance(n, str)]


def _dependencies_checked_first(job: dict) -> set[str]:
    """Job ids whose ``.result`` the job's *first* step turns into an exit code.

    Deliberately only the first step, and only an unconditional one. That
    is the same contract
    ``tests/workflows/test_required_context_error_propagation.py`` pins:
    a later check can be papered over by an earlier green step, and a
    conditional guard can be skipped and then fails open again.
    """
    yaml = _yaml()
    steps = job.get("steps") or []
    if not steps or not isinstance(steps[0], dict):
        return set()
    guard = steps[0]
    if "if" in guard:
        return set()
    body = yaml.safe_dump(guard, allow_unicode=True)
    return set(re.findall(r"needs\.([A-Za-z0-9_-]+)\.result", body))


def inherited_required_jobs(
    workflow_dir: Path = WORKFLOW_DIR,
    required_contexts: frozenset[str] = frozenset(),
) -> set[InheritedJob]:
    """Jobs that carry a required context's enforcement without being one.

    ADR-0075 §1 makes in-workflow aggregation the binding pattern: a
    sammel-job with ``if: always()`` plus an explicit per-dependency
    ``needs.<job>.result`` check, instead of a second required status
    context per lane. A gate job under such an aggregator blocks merges
    exactly as hard as the aggregator does — so for the purpose of "which
    profile is this module in", it *is* a required lane.

    The inheritance is granted only when the propagation is actually
    intact:

    * the aggregator declares the job in ``needs:``,
    * it carries a job-level ``if:`` containing ``always()`` (otherwise a
      red dependency skips it, and GitHub does not block a merge on a
      skipped required check), and
    * its first, unconditional step references ``needs.<job>.result``.

    Miss any of the three and the job does not inherit. That is the
    point: adding a job to ``needs:`` without adding it to the result
    check is the fail-open defect of finding R6, and here it shows up a
    second, independent time — as a module whose declared ``required``
    profile no longer matches the derivation.

    Resolved to a fixpoint, so a chain of aggregators propagates only as
    far as the propagation is unbroken.
    """
    documents = _workflow_documents(workflow_dir)
    inherited: set[InheritedJob] = set()
    changed = True
    while changed:
        changed = False
        for workflow, data in documents.items():
            jobs = data.get("jobs") or {}
            if not isinstance(jobs, dict):
                continue
            for job_id, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                enforcing = (
                    job.get("name", job_id) in required_contexts
                    or (workflow, job_id) in inherited
                )
                if not enforcing:
                    continue
                if "always()" not in str(job.get("if", "")):
                    continue
                checked = _dependencies_checked_first(job)
                for dependency in _needs_list(job):
                    if dependency not in checked:
                        continue
                    key = (workflow, dependency)
                    if key not in inherited:
                        inherited.add(key)
                        changed = True
    return inherited


def build_inventory(
    root: Path = REPO_ROOT,
    required_contexts: frozenset[str] = frozenset(),
) -> dict[str, dict]:
    """Derived lane facts for every test module in the tree."""
    workflow_dir = root / ".github" / "workflows"
    lanes = parse_workflows(workflow_dir)
    inherited = inherited_required_jobs(workflow_dir, required_contexts)

    def blank() -> dict:
        return {"lanes": [], "required_lanes": [], "reachability": []}

    inventory: dict[str, dict] = {module: blank() for module in discover_modules(root)}
    for lane in lanes:
        enforced = (
            lane.job_name in required_contexts
            or (lane.workflow, lane.job_id) in inherited
        )
        for module in sorted(resolve_lane_modules(lane, root)):
            entry = inventory.setdefault(module, blank())
            entry["lanes"].append(lane.lane_id)
            entry["reachability"].append(lane.reachability)
            if enforced:
                entry["required_lanes"].append(lane.lane_id)
    for module, entry in inventory.items():
        entry["opt_in_markers"] = module_opt_in_markers(module, root)
        entry["profile"] = derive_profile(entry)
    return inventory


def job_names(root: Path = REPO_ROOT) -> set[str]:
    """Every job display name declared in any workflow.

    Used to catch the failure mode from PR #102: a required status
    context whose name no longer matches any job stays pending forever.
    """
    names: set[str] = set()
    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        lines = workflow.read_text(encoding="utf-8").splitlines()
        in_jobs = False
        job_id = None
        for raw in lines:
            if _JOBS_RE.match(raw):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            job_match = _JOB_ID_RE.match(raw)
            if job_match:
                job_id = job_match.group("job_id")
                names.add(job_id)
                continue
            name_match = _JOB_NAME_RE.match(raw)
            if name_match and job_id:
                names.add(name_match.group("name").strip("'\""))
    return names


def _sync(assignment_path: Path, inventory: dict[str, dict]) -> int:
    """Refresh the module list and the recorded counts in place."""
    doc = json.loads(assignment_path.read_text(encoding="utf-8"))
    previous: dict[str, dict] = doc["modules"]
    groups: dict[str, dict] = doc.get("exemption_groups", {})

    modules: dict[str, dict] = {}
    added, removed, changed, ungrouped = [], [], [], []
    for module in sorted(inventory):
        profile = inventory[module]["profile"]
        entry: dict[str, str] = {"profile": profile}
        old = previous.get(module)
        if old is None:
            added.append(module)
        elif old["profile"] != profile:
            changed.append(f"{module}: {old['profile']} -> {profile}")
        if old and old.get("group") and groups.get(old["group"], {}).get("profile") == profile:
            entry["group"] = old["group"]
        elif profile in {"operator-hand", "opt-in-marker", "unassigned"}:
            ungrouped.append(module)
        modules[module] = entry
    removed = sorted(set(previous) - set(inventory))

    counts = {profile: 0 for profile in PROFILES}
    for entry in inventory.values():
        counts[entry["profile"]] += 1
    doc["measured"].update(
        {
            "test_modules": len(inventory),
            "required": counts["required"],
            "optional_ci": counts["optional-ci"],
            "operator_hand": counts["operator-hand"],
            "opt_in_marker": counts["opt-in-marker"],
            "unassigned": counts["unassigned"],
        }
    )
    doc["modules"] = modules
    assignment_path.write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for label, items in (
        ("added", added),
        ("removed", removed),
        ("profile changed", changed),
        ("NEEDS a group + reason", ungrouped),
    ):
        if items:
            print(f"{label} ({len(items)}):")
            for item in items:
                print(f"  {item}")
    print(f"synced {len(modules)} modules")
    return 0


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--sync",
        action="store_true",
        help=(
            "rewrite the module list in tests/lanes/lane_assignment.json from "
            "the workflows: add new modules, drop deleted ones, refresh "
            "profiles and counts. Exemption groups are preserved where the "
            "profile is unchanged and dropped where it is not, so a module "
            "that changes profile loses its old justification instead of "
            "inheriting it. New exempt modules land without a group, which "
            "keeps tests/lanes/test_lane_assignment.py red until somebody "
            "writes the reason. --sync never invents a justification."
        ),
    )
    args = parser.parse_args(argv)

    assignment_path = REPO_ROOT / "tests" / "lanes" / "lane_assignment.json"
    required: frozenset[str] = frozenset()
    if assignment_path.is_file():
        required = frozenset(json.loads(assignment_path.read_text())["required_contexts"])

    inventory = build_inventory(REPO_ROOT, required)

    if args.sync:
        return _sync(assignment_path, inventory)

    if args.json:
        json.dump(inventory, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    total = len(inventory)
    print(f"test modules: {total}")
    for profile in PROFILES:
        count = sum(1 for e in inventory.values() if e["profile"] == profile)
        print(f"  {profile:14} {count:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
