#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Collection gate: a test module may not disappear quietly.

Why this exists
---------------

``tests.yml`` runs ``pytest --collect-only`` twice, but only to read a
test *count* out of the summary line for the production-vs-sandbox drift
envelope. Counting is the weaker half. Two failure modes never reach the
count comparison as what they are:

1. **A collection error.** Two of them and a re-baselined envelope and
   the delta can still land inside tolerance.
2. **A module that vanishes silently.** A module-level
   ``pytest.importorskip("X")`` on a dependency the lane is *supposed*
   to have yields zero node IDs and exit code 0. Nothing is red; the
   module is simply gone.

The gate makes both red. It does **not** touch the deliberate
production/sandbox split: the sandbox lane exists precisely so that
``rfc8785``/``jsonschema``-guarded modules skip, and the existing hard
guards in ``tests.yml`` ("verify rfc8785 + jsonschema are present /
absent") stay the authority on which lane is which. The zero-collection
and import-guard checks therefore run under ``--profile production``
only — the lane whose contract is "everything is installed, so nothing
may skip at import time".

Profiles
--------

``production``
    Collection errors fail. Every targeted module must yield at least one
    node ID. Every module-level import guard must name something
    ``pyproject.toml`` declares (a dependency or an extra), an in-repo
    package, or an allow-listed exception — a guard on an undeclared name
    means the module runs only where some lane happened to install an
    undeclared wheel, and silently disappears everywhere else. Allow-lists:
    ``zero_collect_allowed`` and ``import_guard_allowed`` in
    ``tests/lanes/lane_assignment.json``.

``sandbox``
    Collection errors fail. Zero-collection is expected and tolerated —
    that is the whole point of the lane.

Usage::

    python tooling/ci/collect_gate.py --profile production --root wirelang
    python tooling/ci/collect_gate.py --profile sandbox --root wirelang
    python tooling/ci/collect_gate.py --profile production \
        --root tests --root wirelang --root infra --no-github-output
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_PATH = REPO_ROOT / "tests" / "lanes" / "lane_assignment.json"

#: Import guards that are legitimately unsatisfiable in a normal lane
#: because the dependency is matrix-only or comes from a sibling repo.
#: Kept in the assignment file so the exception list has one home.
DEFAULT_IMPORT_GUARD_ALLOWED: tuple[str, ...] = ("hypothesis", "bitcoin", "wakir_verify")


class GateFailure(Exception):
    """A gate condition was violated. Carries the operator-facing text."""


def load_allow_lists(assignment_path: Path = ASSIGNMENT_PATH) -> tuple[set[str], set[str]]:
    if not assignment_path.is_file():
        return set(), set(DEFAULT_IMPORT_GUARD_ALLOWED)
    doc = json.loads(assignment_path.read_text(encoding="utf-8"))
    zero = set(doc.get("zero_collect_allowed", {}))
    declared = doc.get("import_guard_allowed", DEFAULT_IMPORT_GUARD_ALLOWED)
    guards = set(declared)  # dict -> its keys, list -> its items
    return zero, guards


def module_level_import_guards(path: Path) -> list[str]:
    """Names passed to a module-level ``pytest.importorskip(...)``.

    AST-based on purpose: the multi-line call form
    ``pytest.importorskip(\\n    "bitcoin",\\n    reason=...)`` is used in
    this repository and a regular expression misses it.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    names: list[str] = []
    for node in tree.body:  # module level only — nested guards are per-test
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.Expr):
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        attr = getattr(func, "attr", None) or getattr(func, "id", None)
        if attr != "importorskip" or not value.args:
            continue
        first = value.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.append(first.value)
    return names



#: Distribution names whose import name differs. Kept explicit and short;
#: guessing this from metadata would need the package installed, which is
#: exactly what the gate must not assume.
DISTRIBUTION_IMPORT_ALIASES: dict[str, str] = {
    "pyyaml": "yaml",
    "python-bitcoinlib": "bitcoin",
    "nats-py": "nats",
    "protobuf": "google",
}


def declared_import_names(repo_root: Path = REPO_ROOT) -> set[str]:
    """Import names of everything ``pyproject.toml`` declares.

    Both ``[project] dependencies`` and every extra count as declared: an
    extra is a documented install path, an undeclared wheel is not.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return set()
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        return set()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    names: set[str] = set()
    for requirement in requirements:
        distribution = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip().lower()
        if not distribution:
            continue
        names.add(DISTRIBUTION_IMPORT_ALIASES.get(distribution, distribution.replace("-", "_")))
    return names


def in_repo_packages(repo_root: Path = REPO_ROOT) -> set[str]:
    """Top-level importable packages that live in this repository."""
    return {
        child.name
        for child in repo_root.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }


def discover(roots: list[str], repo_root: Path = REPO_ROOT) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        base = repo_root / root
        if not base.is_dir():
            raise GateFailure(f"collect-gate: root {root!r} does not exist")
        found.extend(sorted(base.rglob("test_*.py")))
    return found


def run_collection(roots: list[str], repo_root: Path = REPO_ROOT) -> tuple[int, str, str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        # The repository default is `addopts = "-q"`; a second -q on the
        # command line escalates to -qq and swallows both the node IDs
        # and the summary. Same reasoning as the existing collect steps.
        "--override-ini=addopts=",
        "-p",
        "no:cacheprovider",
        *roots,
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def node_ids_by_module(stdout: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in stdout.splitlines():
        if "::" not in line or line.startswith(" "):
            continue
        module = line.split("::", 1)[0].strip()
        if not module.endswith(".py"):
            continue
        counts[module] = counts.get(module, 0) + 1
    return counts


def gate(
    profile: str,
    roots: list[str],
    repo_root: Path = REPO_ROOT,
    assignment_path: Path = ASSIGNMENT_PATH,
) -> int:
    """Run the gate. Returns the collected node-ID count, or raises."""
    zero_allowed, guard_allowed = load_allow_lists(assignment_path)
    modules = discover(roots, repo_root)

    returncode, stdout, stderr = run_collection(roots, repo_root)
    if returncode != 0:
        raise GateFailure(
            "collect-gate: pytest --collect-only exited "
            f"{returncode} for roots {roots}. A collection error is a red "
            "lane, not a smaller test count.\n"
            f"--- stdout ---\n{stdout[-4000:]}\n--- stderr ---\n{stderr[-2000:]}"
        )

    counts = node_ids_by_module(stdout)
    total = sum(counts.values())

    if profile != "production":
        return total

    silent: list[str] = []
    for path in modules:
        rel = path.relative_to(repo_root).as_posix()
        if counts.get(rel, 0) > 0 or rel in zero_allowed:
            continue
        guards = module_level_import_guards(path)
        silent.append(f"{rel} (module-level import guards: {guards or 'none'})")
    if silent:
        raise GateFailure(
            "collect-gate: these modules were collected but produced zero "
            "node IDs in the production profile. Either the module is empty "
            "or a module-level import guard fired on something this lane is "
            "supposed to have installed. Add a lane dependency, or an "
            "explicit entry to `zero_collect_allowed` in "
            "tests/lanes/lane_assignment.json with a reason:\n  "
            + "\n  ".join(sorted(silent))
        )

    unknown: list[str] = []
    declared = declared_import_names(repo_root)
    in_repo = in_repo_packages(repo_root)
    for path in modules:
        rel = path.relative_to(repo_root).as_posix()
        for name in module_level_import_guards(path):
            top = name.split(".", 1)[0]
            if top in declared or top in in_repo or top in guard_allowed or name in guard_allowed:
                continue
            unknown.append(f"{rel}: importorskip({name!r})")
    if unknown:
        raise GateFailure(
            "collect-gate: module-level import guards name modules that are "
            "neither declared in pyproject.toml (dependencies or an extra), "
            "nor in-repo packages, nor on the allow-list. A guard on an "
            "undeclared name means the module runs only where the lane "
            "happens to have installed something nobody declared — and "
            "vanishes everywhere else without a red check. Declare the "
            "dependency, or add the name to `import_guard_allowed` in "
            "tests/lanes/lane_assignment.json with a reason:\n  "
            + "\n  ".join(sorted(unknown))
        )

    return total


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="collection gate for wakir-runtime")
    parser.add_argument("--profile", choices=("production", "sandbox"), required=True)
    parser.add_argument("--root", action="append", dest="roots", required=True)
    parser.add_argument(
        "--github-output",
        default=None,
        help="name of the GITHUB_OUTPUT key to write the collected count to",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    # The assignment file is repo-relative so the gate can be pointed at a
    # throw-away tree in the negative controls without reading this repo's
    # allow-lists by accident.
    assignment_path = repo_root / "tests" / "lanes" / "lane_assignment.json"
    try:
        total = gate(args.profile, args.roots, repo_root, assignment_path)
    except GateFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"collect-gate [{args.profile}] roots={args.roots} collected={total}")
    if args.github_output:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(f"{args.github_output}={total}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
