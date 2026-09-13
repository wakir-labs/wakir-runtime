# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tests for the archaeology lint (ADR-0072 sub-item 4d).

A gate that is not itself tested is a gate that quietly stops failing.
Two things are pinned here: the allowlist schema — an exception must name
either the pin that holds the literal or the zone that owns it, never
neither and never both — and the current state of the tree, which must be
clean under the lint as shipped.

Hermetic: stdlib + pytest + PyYAML, no network, no subprocess beyond the
`git ls-files` the lint itself runs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_PATH = REPO_ROOT / "tooling" / "ci" / "archaeology_lint.py"
ALLOWLIST_PATH = REPO_ROOT / ".archaeology-allowlist.yaml"


def _load_lint():
    spec = importlib.util.spec_from_file_location("archaeology_lint", LINT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `dataclasses` resolves annotations via `sys.modules[cls.__module__]`,
    # so the module has to be registered before it executes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lint = _load_lint()


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "allowlist.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Allowlist schema
# ---------------------------------------------------------------------------


def test_shipped_allowlist_loads() -> None:
    """The allowlist in the repository satisfies its own schema."""
    entries = lint.load_allowlist(ALLOWLIST_PATH)
    assert entries, "allowlist must not be empty while the tree still has exceptions"


def test_every_shipped_entry_names_a_justification() -> None:
    """No entry may be an unexplained exception."""
    for entry in lint.load_allowlist(ALLOWLIST_PATH):
        assert bool(entry.pinned_by) != bool(entry.deferred_to), entry.path
        assert entry.reason.strip(), entry.path


def test_entry_without_justification_is_rejected(tmp_path: Path) -> None:
    """An entry with neither `pinned_by` nor `deferred_to` fails hard."""
    path = _write(tmp_path, """
version: 1
entries:
  - path: "docs/**"
    reason: "because"
""")
    with pytest.raises(lint.AllowlistError, match="pinned_by"):
        lint.load_allowlist(path)


def test_entry_with_both_justifications_is_rejected(tmp_path: Path) -> None:
    """Claiming both a pin and an owner hides which one is true."""
    path = _write(tmp_path, """
version: 1
entries:
  - path: "docs/**"
    reason: "because"
    pinned_by: "tests/test_x.py"
    deferred_to: "some zone"
""")
    with pytest.raises(lint.AllowlistError, match="mutually exclusive"):
        lint.load_allowlist(path)


def test_entry_without_reason_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, """
version: 1
entries:
  - path: "docs/**"
    pinned_by: "tests/test_x.py"
""")
    with pytest.raises(lint.AllowlistError, match="reason"):
        lint.load_allowlist(path)


def test_empty_pinned_by_is_rejected(tmp_path: Path) -> None:
    """`pinned_by: ""` is an exception without a pin."""
    path = _write(tmp_path, """
version: 1
entries:
  - path: "docs/**"
    reason: "because"
    pinned_by: "   "
""")
    with pytest.raises(lint.AllowlistError):
        lint.load_allowlist(path)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    """A typo in a field name must not silently disable the requirement."""
    path = _write(tmp_path, """
version: 1
entries:
  - path: "docs/**"
    reason: "because"
    pinned_bye: "tests/test_x.py"
""")
    with pytest.raises(lint.AllowlistError, match="unknown field"):
        lint.load_allowlist(path)


def test_wrong_version_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, """
version: 2
entries: []
""")
    with pytest.raises(lint.AllowlistError, match="version"):
        lint.load_allowlist(path)


def test_missing_allowlist_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(lint.AllowlistError, match="not found"):
        lint.load_allowlist(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# Pattern and matching behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample",
    ["Tag-61 closeout", "Sprint-9 bundle", "AR-Hand override", "Watch-Day verdict",
     "Skizze", "Aufsichtsrat", "Mira", "Henrik", "Tomás", "Reza", "Selin", "Noa "],
)
def test_enforced_vocabulary_matches(sample: str) -> None:
    import re
    assert re.search(lint.ENFORCED_PATTERN, sample), sample


@pytest.mark.parametrize(
    "sample",
    ["welle-4-alerts", "cutover window", "KW-26", "marathon closeout",
     "mira-notify-bridge", "kaizen", "the tag is 0.7.0-rust"],
)
def test_living_vocabulary_does_not_match(sample: str) -> None:
    """The four domain words and lower-case component names stay legal.

    This is the scope decision of the gate, not an accident: enforcing
    them would have meant allowlisting living identifiers by the dozen.
    """
    import re
    assert not re.search(lint.ENFORCED_PATTERN, sample), sample


def test_directory_glob_covers_nested_paths() -> None:
    entries = [lint.Entry("docs/**", "r", "tests/test_x.py", None)]
    assert lint.matches("docs/a/b/c.md", entries) is not None
    assert lint.matches("other/a.md", entries) is None


def test_archive_and_the_lint_itself_are_not_scanned() -> None:
    """The archive is the designated resting place; the lint holds samples."""
    assert not lint.is_scanned("docs/archive/README.md")
    assert not lint.is_scanned("tooling/ci/archaeology_lint.py")
    assert not lint.is_scanned("tests/ci/test_archaeology_lint.py")
    assert lint.is_scanned("tests/ci/test_other.py")


def test_binary_files_are_not_scanned() -> None:
    assert not lint.is_scanned("meta/timestamps/abc.ots")
    assert not lint.is_scanned("docs/img/diagram.png")


# ---------------------------------------------------------------------------
# The tree as shipped
# ---------------------------------------------------------------------------


def test_repository_is_clean_under_the_lint() -> None:
    """No archaeology outside the allowlist, and no stale allowlist entry."""
    entries = lint.load_allowlist(ALLOWLIST_PATH)
    violations, used, _ = lint.scan(entries)
    assert not violations, (
        "archaeology outside the allowlist: "
        + ", ".join(sorted(violations))
    )
    stale = sorted(e.path for e in entries if e.path not in used)
    assert not stale, f"allowlist entries matching nothing: {stale}"
