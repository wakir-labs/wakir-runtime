# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Guard for ``tooling/ci/fstring_name_lint.py`` and for the tree it scans.

The lint exists because of a concrete incident: PR #533 renamed "Welle"
to "wave" across the test tree on 2026-09-14 and took 21 f-string
placeholders in ``tests/acceptance/phase_3c/_ac_assertions.py`` with it,
leaving ``{wave}`` next to a parameter still named ``welle``. Every one
sat in an assertion's failure message, so nothing showed until an
acceptance criterion was violated -- at which point the helper raised
``NameError`` rather than naming the drift. The suite that would have
caught it was exempt from every lane and did not run.

Two halves here, and the first is the one that matters:

1. **Negative controls.** A lint that cannot fail is not a lint. The
   cases below reconstruct the incident shape and several neighbours,
   and assert the checker flags them. Without these, the tree-wide
   assertion in part 2 would pass just as happily against a checker that
   returns an empty list unconditionally.
2. **The tree assertion.** Zero findings across the repository.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tooling" / "ci" / "fstring_name_lint.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("_fstring_name_lint", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: ``@dataclass`` resolves annotations through
    # ``sys.modules[cls.__module__]`` and raises without it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lint = _load_tool()


# ---------------------------------------------------------------------------
# Negative controls — the checker must flag these.
# ---------------------------------------------------------------------------


THE_INCIDENT = '''
def assert_ac_1(records, welle):
    assert all(r.ok for r in records), (
        f"AC-1[{wave}]: consistency report not green"
    )
'''


NESTED_IN_A_CLASS = '''
class Gate:
    def report(self, welle):
        return f"gate {wave} red"
'''


INSIDE_A_COMPREHENSION = '''
def render(items, welle):
    return [f"{wave}:{item}" for item in items]
'''


MODULE_LEVEL = '''
BANNER = f"phase {wave}"
'''


FORMAT_SPEC_ONLY = '''
def render(value, width):
    return f"{value:>{widht}}"
'''


@pytest.mark.parametrize(
    "source,expected_name",
    [
        pytest.param(THE_INCIDENT, "wave", id="the-2026-09-14-incident-shape"),
        pytest.param(NESTED_IN_A_CLASS, "wave", id="method-body"),
        pytest.param(INSIDE_A_COMPREHENSION, "wave", id="comprehension-body"),
        pytest.param(MODULE_LEVEL, "wave", id="module-level-fstring"),
        pytest.param(FORMAT_SPEC_ONLY, "widht", id="typo-in-nested-format-spec"),
    ],
)
def test_checker_flags_undefined_placeholder(source: str, expected_name: str) -> None:
    findings = lint.check_source(source, "synthetic.py")
    assert [f.name for f in findings] == [expected_name], (
        f"expected exactly one finding for {expected_name!r}; got {findings}"
    )


# ---------------------------------------------------------------------------
# Positive controls — the checker must stay quiet on these.
# ---------------------------------------------------------------------------


CORRECT_PARAMETER = '''
def assert_ac_1(records, welle):
    assert records, f"AC-1[{welle}]: empty"
'''

NESTED_FUNCTION_PARAMETER = '''
def outer():
    def inner(cmd):
        return f"ran {cmd}"
    return inner
'''

LAMBDA_PARAMETER = '''
render = lambda host: f"host {host}"
'''

ASSIGNED_LATER_IN_THE_FUNCTION = '''
def f(items):
    def describe():
        return f"{total} items"
    total = len(items)
    return describe
'''

WALRUS_AND_EXCEPT_AND_WITH = '''
import contextlib

def f(path):
    with contextlib.nullcontext() as ctx:
        try:
            if (n := len(path)) > 0:
                return f"{n} {ctx}"
        except ValueError as err:
            return f"{err}"
    return ""
'''

BUILTIN_AND_DUNDER = '''
def f(values):
    return f"{len(values)} from {__file__}"
'''

COMPREHENSION_TARGET = '''
def f(values):
    return [f"{v}" for v in values]
'''

GLOBAL_CONSTANT = '''
WINDOW = 5

def f():
    return f"window {WINDOW}"
'''


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(CORRECT_PARAMETER, id="correct-parameter"),
        pytest.param(NESTED_FUNCTION_PARAMETER, id="nested-function-parameter"),
        pytest.param(LAMBDA_PARAMETER, id="lambda-parameter"),
        pytest.param(ASSIGNED_LATER_IN_THE_FUNCTION, id="function-wide-scoping"),
        pytest.param(WALRUS_AND_EXCEPT_AND_WITH, id="walrus-except-with"),
        pytest.param(BUILTIN_AND_DUNDER, id="builtin-and-module-dunder"),
        pytest.param(COMPREHENSION_TARGET, id="comprehension-target"),
        pytest.param(GLOBAL_CONSTANT, id="module-global"),
    ],
)
def test_checker_stays_quiet_on_valid_sources(source: str) -> None:
    assert lint.check_source(source, "synthetic.py") == []


def test_star_import_is_skipped_not_guessed_at() -> None:
    """A star-import defeats static name resolution. Skipping is the
    honest answer; guessing would produce noise that trains people to
    ignore the lint."""
    source = "from os.path import *\n\ndef f():\n    return f'{join}'\n"
    assert lint.check_source(source, "synthetic.py") == []
    assert lint.has_star_import(__import__("ast").parse(source)) is True


# ---------------------------------------------------------------------------
# The tree assertion.
# ---------------------------------------------------------------------------


def test_repository_has_no_undefined_fstring_placeholders() -> None:
    findings, _skipped = lint.check_paths([REPO_ROOT])
    assert findings == [], (
        "undefined names inside f-string placeholders:\n"
        + "\n".join(str(f) for f in findings)
        + "\n\nThese raise NameError only when the string is formatted, which "
        "for an assertion message means only when the assertion fails — the "
        "path least likely to be exercised and most likely to matter."
    )


def test_star_import_skips_are_few_enough_to_read() -> None:
    """The skip list is the lint's blind spot. Keeping it small and
    printed is the point; this pins that it does not grow quietly."""
    _findings, skipped = lint.check_paths([REPO_ROOT])
    assert len(skipped) <= 3, (
        "more modules use `from x import *` than this guard expected; each "
        "one is a module the f-string lint cannot resolve names in: "
        f"{skipped}"
    )
