# SPDX-License-Identifier: Apache-2.0
"""Negative controls for the collection gate.

A gate nobody has ever seen fail is a decoration. These tests build small
throw-away trees, run ``tooling/ci/collect_gate.py`` against them, and
assert that each failure class actually turns it red — and, just as
important, that the classes the repository depends on staying *green*
stay green.

The four classes:

1. **Hard collection error** — an import that raises. Red in both
   profiles. This is the one the existing ``--collect-only`` steps were
   supposed to catch and only caught by accident of ``bash -e``.
2. **Silent vanishing** — a module-level ``pytest.importorskip`` on a
   dependency the production lane is supposed to have. Zero node IDs,
   pytest exit code 0, nothing red anywhere. Red in the production
   profile.
3. **Deliberate sandbox skip** — the same construct in the sandbox
   profile, which exists precisely so those modules skip. Must stay
   green; breaking this would break the production-vs-sandbox drift
   envelope, which is a required context.
4. **Named exception** — a module on the ``zero_collect_allowed`` list
   whose guard name is on ``import_guard_allowed``. Must stay green, or
   the two matrix-only external-verifier modules would make every run
   red. Both lists are needed because they answer different questions:
   "this module may collect nothing" and "this name may be undeclared".
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "tooling" / "ci" / "collect_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("wakir_collect_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["wakir_collect_gate"] = module
    spec.loader.exec_module(module)
    return module


collect_gate = _load_gate()


def _tree(
    tmp_path: Path,
    modules: dict[str, str],
    allow: dict | None = None,
    guard_allow: dict | None = None,
) -> Path:
    """A minimal repo-shaped tree: a `tests/` root plus an assignment file."""
    (tmp_path / "tests" / "lanes").mkdir(parents=True)
    for name, body in modules.items():
        (tmp_path / "tests" / name).write_text(textwrap.dedent(body), encoding="utf-8")
    assignment = {
        "zero_collect_allowed": allow or {},
        "import_guard_allowed": guard_allow or {},
    }
    (tmp_path / "tests" / "lanes" / "lane_assignment.json").write_text(
        json.dumps(assignment), encoding="utf-8"
    )
    return tmp_path


HEALTHY = """
    def test_ok() -> None:
        assert True
"""

BROKEN_IMPORT = """
    import a_module_that_does_not_exist_anywhere  # noqa: F401

    def test_never_runs() -> None:
        assert True
"""

SILENT_SKIP = """
    import pytest

    pytest.importorskip("a_dependency_this_lane_should_have")

    def test_vanishes_without_a_trace() -> None:
        assert True
"""


def _run_gate(tree: Path, profile: str) -> tuple[int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE_PATH),
            "--profile",
            profile,
            "--root",
            "tests",
            "--repo-root",
            str(tree),
        ],
        cwd=tree,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Positive control first: the gate is capable of passing.
# ---------------------------------------------------------------------------


def test_healthy_tree_passes(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"test_healthy.py": HEALTHY})
    code, output = _run_gate(tree, "production")
    assert code == 0, output
    assert "collected=1" in output


# ---------------------------------------------------------------------------
# Class 1 — a collection error must be red, in both profiles.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["production", "sandbox"])
def test_collection_error_is_red(tmp_path: Path, profile: str) -> None:
    tree = _tree(tmp_path, {"test_healthy.py": HEALTHY, "test_broken.py": BROKEN_IMPORT})
    code, output = _run_gate(tree, profile)
    assert code != 0, output
    assert "collect-only exited" in output
    assert "test_broken.py" in output


def test_bare_pytest_reports_the_same_collection_error(tmp_path: Path) -> None:
    """The gate is not inventing a failure pytest would not have."""
    tree = _tree(tmp_path, {"test_broken.py": BROKEN_IMPORT})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=tree,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# Class 2 — the silent one. Exit code 0 from pytest, red from the gate.
# ---------------------------------------------------------------------------


def test_module_level_importorskip_exits_zero_in_plain_pytest(tmp_path: Path) -> None:
    """The premise, measured rather than asserted from memory.

    If this ever stops being true the gate below is solving a problem
    that no longer exists, and should be reconsidered rather than kept.
    """
    tree = _tree(tmp_path, {"test_silent.py": SILENT_SKIP})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        cwd=tree,
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 5), proc.stdout + proc.stderr
    assert "error" not in proc.stdout.lower()


def test_silent_vanishing_is_red_in_production(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"test_healthy.py": HEALTHY, "test_silent.py": SILENT_SKIP})
    code, output = _run_gate(tree, "production")
    assert code != 0, output
    assert "test_silent.py" in output
    assert "a_dependency_this_lane_should_have" in output


# ---------------------------------------------------------------------------
# Classes 3 and 4 — what must stay green.
# ---------------------------------------------------------------------------


def test_silent_vanishing_is_tolerated_in_sandbox(tmp_path: Path) -> None:
    """The sandbox lane exists so that gated modules skip. Do not break it."""
    tree = _tree(tmp_path, {"test_healthy.py": HEALTHY, "test_silent.py": SILENT_SKIP})
    code, output = _run_gate(tree, "sandbox")
    assert code == 0, output


def test_named_exception_is_tolerated_in_production(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path,
        {"test_healthy.py": HEALTHY, "test_silent.py": SILENT_SKIP},
        allow={"tests/test_silent.py": "matrix-only dependency, named on purpose"},
        guard_allow={"a_dependency_this_lane_should_have": "matrix-only, named on purpose"},
    )
    code, output = _run_gate(tree, "production")
    assert code == 0, output


def test_zero_collect_exception_alone_does_not_excuse_an_undeclared_guard(
    tmp_path: Path,
) -> None:
    """The two lists are not interchangeable — on purpose.

    Excusing the empty collection says nothing about whether the name the
    guard reaches for is one this repository ever declared. Keeping the
    second question open is what turns "module vanished" into "module
    vanished because of a wheel nobody wrote down".
    """
    tree = _tree(
        tmp_path,
        {"test_healthy.py": HEALTHY, "test_silent.py": SILENT_SKIP},
        allow={"tests/test_silent.py": "empty collection excused"},
    )
    code, output = _run_gate(tree, "production")
    assert code != 0, output
    assert "neither declared in pyproject.toml" in output


# ---------------------------------------------------------------------------
# The AST helper must see the call form this repository actually uses.
# ---------------------------------------------------------------------------


def test_import_guard_detection_handles_the_multiline_call_form(tmp_path: Path) -> None:
    """``pytest.importorskip("bitcoin", reason=...)`` spans lines in tests/wat."""
    module = tmp_path / "test_multiline.py"
    module.write_text(
        textwrap.dedent(
            """
            import pytest

            bitcoin = pytest.importorskip(
                "bitcoin",
                reason="python-bitcoinlib not installed",
            )
            """
        ),
        encoding="utf-8",
    )
    assert collect_gate.module_level_import_guards(module) == ["bitcoin"]


def test_import_guard_detection_ignores_guards_inside_tests(tmp_path: Path) -> None:
    """A guard inside a test function skips one test, not a whole module."""
    module = tmp_path / "test_inner.py"
    module.write_text(
        textwrap.dedent(
            """
            import pytest

            def test_one():
                pytest.importorskip("something")
            """
        ),
        encoding="utf-8",
    )
    assert collect_gate.module_level_import_guards(module) == []


def test_real_repository_guards_are_detected() -> None:
    """Anchor the detector to a real module rather than only to fixtures."""
    real = REPO_ROOT / "tests" / "wat" / "external_verifier" / "test_python_bitcoinlib_drift.py"
    if not real.is_file():  # module is owned elsewhere and may move
        pytest.skip(f"{real.relative_to(REPO_ROOT)} not present at this commit")
    assert "bitcoin" in collect_gate.module_level_import_guards(real)
