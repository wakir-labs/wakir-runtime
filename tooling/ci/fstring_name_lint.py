# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Undefined names inside f-string placeholders, found statically.

Why this file exists
--------------------

On 2026-09-14 the archaeology-removal pass (PR #533) replaced the word
``Welle`` with ``wave`` across the test tree. The replacement ran over
f-string *placeholders* as well as prose, so 21 expressions in
``tests/acceptance/phase_3c/_ac_assertions.py`` became ``{wave}`` while
the surrounding function parameter stayed ``welle``.

Every one of those 21 sits inside an assertion's failure message. On the
happy path the message is never formatted, so the defect is invisible;
the moment an acceptance criterion is violated the helper raises
``NameError`` instead of ``AssertionError`` with a diagnosis. The suite
that would have caught it was under a lane exemption and did not run, so
the change merged green and stayed green for six days.

That is the failure class this module addresses, and it is a class the
test suite cannot fully cover on its own: nine of the 21 placeholders sit
on paths a negative control exercises; the other twelve sit on paths whose
negative controls are themselves skipped pending real cutover wiring. A
test can only catch a broken message by provoking the message. A static
check catches all of them for the price of one AST walk.

What it does and does not claim
-------------------------------

It resolves names the way CPython scopes them -- module globals, function
parameters, every binding anywhere in the enclosing function body (Python
scoping is function-wide, not block-wide), comprehension targets, ``except
... as``, ``with ... as``, walrus targets, imports, nested function and
lambda parameters, class names, and builtins -- and reports a ``Name``
load inside a ``FormattedValue`` that none of those bind.

It is deliberately *not* a general undefined-name linter. Names outside
f-strings are left alone: a plain ``NameError`` fires on the first run of
any code path, whereas an f-string placeholder in an error message fires
only on the path nobody exercises. Narrowing the scope to placeholders is
what keeps the false-positive rate at zero over this repository (verified
2026-09-20: 0 findings across the whole tree after the fix, 21 before).

Star-imports (``from x import *``) defeat static name resolution. A module
containing one is skipped, and the skip is reported, so the gap is visible
rather than silent.

Usage::

    python tooling/ci/fstring_name_lint.py            # whole repository
    python tooling/ci/fstring_name_lint.py tests      # one or more roots

Exit code 1 when anything is found.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]

BUILTIN_NAMES = frozenset(dir(builtins))

#: Names CPython injects into every module namespace.
MODULE_DUNDERS = frozenset(
    {
        "__file__",
        "__name__",
        "__doc__",
        "__package__",
        "__spec__",
        "__loader__",
        "__builtins__",
        "__path__",
        "__debug__",
    }
)

#: Directories never worth walking.
SKIP_DIR_PARTS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "target", ".mypy_cache"}
)


@dataclass(frozen=True)
class Finding:
    """One undefined name inside one f-string placeholder."""

    path: str
    lineno: int
    name: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"{self.path}:{self.lineno}: undefined name in f-string: {self.name}"


class _Scope:
    """A lexical scope with a parent chain."""

    __slots__ = ("names", "parent")

    def __init__(self, parent: "_Scope | None" = None) -> None:
        self.names: set[str] = set()
        self.parent = parent

    def binds(self, name: str) -> bool:
        scope: _Scope | None = self
        while scope is not None:
            if name in scope.names:
                return True
            scope = scope.parent
        return False


def _bind_target(target: ast.AST, scope: _Scope) -> None:
    """Bind every ``Name`` in an assignment target (tuples included)."""
    for node in ast.walk(target):
        if isinstance(node, ast.Name):
            scope.names.add(node.id)


def _bind_arguments(args: ast.arguments, scope: _Scope) -> None:
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        scope.names.add(arg.arg)
    if args.vararg is not None:
        scope.names.add(args.vararg.arg)
    if args.kwarg is not None:
        scope.names.add(args.kwarg.arg)


def _bind_everything_under(node: ast.AST, scope: _Scope, *, skip: ast.AST) -> None:
    """Bind every name any construct under ``node`` introduces.

    Python binds function-wide, not block-wide, so a name assigned in the
    last line of a function is in scope in the first. Walking the whole
    subtree and binding eagerly matches that, and errs towards
    permissiveness everywhere it does not -- the safe direction for a
    lint whose false positives would cost more than its false negatives.
    """
    for sub in ast.walk(node):
        if sub is skip:
            continue
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                _bind_target(target, scope)
        elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
            _bind_target(sub.target, scope)
        elif isinstance(sub, (ast.For, ast.AsyncFor)):
            _bind_target(sub.target, scope)
        elif isinstance(sub, ast.withitem):
            if sub.optional_vars is not None:
                _bind_target(sub.optional_vars, scope)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                scope.names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(sub, ast.comprehension):
            _bind_target(sub.target, scope)
        elif isinstance(sub, ast.ExceptHandler):
            if sub.name:
                scope.names.add(sub.name)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            scope.names.update(sub.names)
        elif isinstance(sub, ast.NamedExpr):
            _bind_target(sub.target, scope)
        elif isinstance(sub, ast.Lambda):
            _bind_arguments(sub.args, scope)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.names.add(sub.name)
            _bind_arguments(sub.args, scope)
        elif isinstance(sub, ast.ClassDef):
            scope.names.add(sub.name)
        elif isinstance(sub, ast.MatchAs):
            if sub.name:
                scope.names.add(sub.name)
        elif isinstance(sub, ast.MatchStar):
            if sub.name:
                scope.names.add(sub.name)
        elif isinstance(sub, ast.MatchMapping):
            if sub.rest:
                scope.names.add(sub.rest)


def _module_scope(tree: ast.Module) -> _Scope:
    scope = _Scope()
    scope.names.update(MODULE_DUNDERS)
    _bind_everything_under(tree, scope, skip=tree)
    return scope


def _check_fstrings(node: ast.AST, scope: _Scope, path: str) -> Iterator[Finding]:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.JoinedStr):
            continue
        for value in sub.values:
            if not isinstance(value, ast.FormattedValue):
                continue
            for inner in ast.walk(value.value):
                if not isinstance(inner, ast.Name):
                    continue
                if not isinstance(inner.ctx, ast.Load):
                    continue
                if scope.binds(inner.id) or inner.id in BUILTIN_NAMES:
                    continue
                yield Finding(path, inner.lineno, inner.id)


def _walk(node: ast.AST, scope: _Scope, path: str) -> Iterator[Finding]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.names.add(child.name)
            inner = _Scope(scope)
            _bind_arguments(child.args, inner)
            _bind_everything_under(child, inner, skip=child)
            yield from _check_fstrings(child, inner, path)
        elif isinstance(child, ast.ClassDef):
            scope.names.add(child.name)
            inner = _Scope(scope)
            _bind_everything_under(child, inner, skip=child)
            yield from _walk(child, inner, path)
        else:
            yield from _walk(child, scope, path)


def has_star_import(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "*" for alias in node.names)
        for node in ast.walk(tree)
    )


def check_source(source: str, path: str = "<string>") -> list[Finding]:
    """Findings for one module's source. Empty for unparsable sources."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if has_star_import(tree):
        return []
    scope = _module_scope(tree)
    findings = list(_check_fstrings_module_level(tree, scope, path))
    findings.extend(_walk(tree, scope, path))
    return sorted(set(findings), key=lambda f: (f.path, f.lineno, f.name))


def _check_fstrings_module_level(
    tree: ast.Module, scope: _Scope, path: str
) -> Iterator[Finding]:
    """Placeholders in module-level code, outside any def or class."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield from _check_fstrings(node, scope, path)


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*.py")):
            if SKIP_DIR_PARTS.intersection(path.parts):
                continue
            yield path


def check_paths(roots: Iterable[Path]) -> tuple[list[Finding], list[str]]:
    """Findings plus the modules skipped because of a star-import."""
    findings: list[Finding] = []
    skipped: list[str] = []
    for path in iter_python_files(roots):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix() if _under(path) else str(path)
        if has_star_import(tree):
            skipped.append(rel)
            continue
        findings.extend(check_source(source, rel))
    return findings, skipped


def _under(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="*",
        default=None,
        help="files or directories to scan (default: the repository root)",
    )
    args = parser.parse_args(argv)
    roots = [Path(r) for r in args.roots] if args.roots else [REPO_ROOT]

    findings, skipped = check_paths(roots)
    for entry in skipped:
        print(f"fstring-name-lint: skipped (star-import): {entry}")
    for finding in findings:
        print(str(finding))
    if findings:
        print(
            f"fstring-name-lint: {len(findings)} undefined name(s) in f-string "
            f"placeholders. These raise NameError only on the code path that "
            f"formats the string, which is usually the error path.",
            file=sys.stderr,
        )
        return 1
    print("fstring-name-lint: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
