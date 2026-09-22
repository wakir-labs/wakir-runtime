# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Guard for ``tooling/ci/private_address_lint.py``.

The lint exists because a rule that is only written down is not a rule.
A test for it has to prove the same thing about itself, so the cases
below are built around negative controls: it is not enough that the real
tree is green, because an empty scanner is green too. Every assertion
that something passes is paired with an injected case that must fail.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from tooling.ci import private_address_lint as lint

REPO_ROOT = Path(__file__).resolve().parents[2]

TODAY = dt.date(2026, 9, 22)

# Split so this file's own fixtures do not need the lint to skip it, and
# so a careless grep over the test suite does not re-introduce what the
# lint removes. The lint excludes this path explicitly anyway; the split
# keeps both guards honest.
_PILOT = "192.168." + "178.116"
_BRIDGE = "10." + "0.42.10"
_TWELVE = "172." + "20.1.5"
_WILDCARD = "192.168." + "178.*"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repository. The lint reads ``git ls-files``."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "clean.md").write_text("nothing to see\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _add(repo: Path, name: str, body: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"add {name}")


def _entry(**overrides: object) -> dict:
    entry = {
        "path": "infra/example.md",
        "addresses": [_PILOT],
        "reason": (
            "The bring-up recipe quotes this address from a vendor document "
            "that cannot be paraphrased without losing the step it belongs "
            "to; it goes when that section is rewritten."
        ),
        "owner": "infra",
        "until": "2026-12-31",
        "tracking": "https://github.com/wakir-labs/wakir-runtime/pull/559",
    }
    entry.update(overrides)
    return entry


def _allowlist(tmp_path: Path, *entries: dict) -> Path:
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            {"schema": lint.ALLOWLIST_SCHEMA, "entries": list(entries)}, indent=2
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Negative control: the scanner actually fires.
# ---------------------------------------------------------------------------


def test_clean_tree_is_green(repo: Path) -> None:
    report = lint.evaluate(lint.scan_tree(repo), (), TODAY)
    assert report.findings == ()
    assert report.ok


def test_injected_address_makes_it_red(repo: Path) -> None:
    """The control for the test above. A green scanner and a broken one
    are indistinguishable on a clean tree."""
    _add(repo, "infra/example.md", f"peer host is {_PILOT} today\n")
    report = lint.evaluate(lint.scan_tree(repo), (), TODAY)
    assert not report.ok
    assert len(report.violations) == 1
    finding = report.violations[0]
    assert finding.address == _PILOT
    assert finding.path == "infra/example.md"
    assert finding.line == 1


@pytest.mark.parametrize(
    ("literal", "rule_fragment"),
    [
        (_PILOT, "192.168.0.0/16"),
        (_BRIDGE, "10.0.0.0/8"),
        (_TWELVE, "172.16.0.0/12"),
        (_WILDCARD, "wildcard"),
    ],
)
def test_every_enforced_block_is_caught(
    repo: Path, literal: str, rule_fragment: str
) -> None:
    """All of RFC1918, not just the prefix the 2026-09 scrub happened to
    find. A lint that knew one prefix would be guarding the past."""
    _add(repo, "doc.md", f"host: {literal}\n")
    findings = lint.scan_tree(repo)
    assert len(findings) == 1, findings
    assert findings[0].address == literal
    assert rule_fragment in findings[0].rule


@pytest.mark.parametrize(
    "literal",
    [
        "192.0.2.116",  # RFC 5737 TEST-NET-1 — the replacement we chose
        "198.51.100.10",  # TEST-NET-2
        "203.0.113.99",  # TEST-NET-3
        "8.8.8.8",  # public
        "172.15.0.1",  # just below the /12
        "172.32.0.1",  # just above the /12
        "193.168.1.1",  # not 192
        "10.300.1.1",  # not an address at all
        "1.10.0.42.5",  # a longer dotted run, e.g. a version
    ],
)
def test_addresses_outside_the_enforced_set_are_not_flagged(
    repo: Path, literal: str
) -> None:
    """False positives cost more than they look: every one of them has to
    become an allow-list entry, and an allow-list that long stops being
    read."""
    _add(repo, "doc.md", f"value: {literal}\n")
    assert lint.scan_tree(repo) == ()


def test_binary_and_untracked_files_are_skipped(repo: Path) -> None:
    (repo / "untracked.md").write_text(f"{_PILOT}\n", encoding="utf-8")
    blob = repo / "payload.bin"
    blob.write_bytes(b"\x00\x01" + _PILOT.encode() + b"\x00")
    _git(repo, "add", "payload.bin")
    _git(repo, "commit", "-qm", "blob")
    assert lint.scan_tree(repo) == ()


def test_the_scan_reads_the_tree_and_not_the_history(repo: Path) -> None:
    """The load-bearing scope decision: history is deliberately not
    rewritten, so the gate must not claim to police it."""
    _add(repo, "gone.md", f"{_PILOT}\n")
    assert len(lint.scan_tree(repo)) == 1
    (repo / "gone.md").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "remove")

    # Still in the history, gone from the tree: green.
    assert lint.scan_tree(repo) == ()
    log = subprocess.run(
        ["git", "log", "-p"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert _PILOT in log.stdout, "fixture broken: the address should still be in the log"


# ---------------------------------------------------------------------------
# Allow-list: covers, expires, and fails loudly when malformed.
# ---------------------------------------------------------------------------


def test_allowlisted_address_with_a_live_date_is_green(repo: Path, tmp_path: Path) -> None:
    _add(repo, "infra/example.md", f"{_PILOT}\n")
    entries = lint.load_allowlist(_allowlist(tmp_path, _entry()))
    report = lint.evaluate(lint.scan_tree(repo), entries, TODAY)
    assert report.ok
    assert len(report.allowed) == 1
    assert report.violations == ()


def test_allowlisted_address_with_an_expired_date_is_red(
    repo: Path, tmp_path: Path
) -> None:
    """ADR-0075 §3: an expired exemption fails the gate. It does not
    quietly stop applying, and it does not quietly keep applying."""
    _add(repo, "infra/example.md", f"{_PILOT}\n")
    entries = lint.load_allowlist(
        _allowlist(tmp_path, _entry(until="2026-09-21"))
    )
    report = lint.evaluate(lint.scan_tree(repo), entries, TODAY)
    assert not report.ok
    assert len(report.expired) == 1
    # And the address it used to cover is a violation again, rather than
    # silently staying covered by a dead entry.
    assert len(report.violations) == 1
    assert "expired allow-list entries" in lint.failure_text(report)


def test_entry_inside_the_warning_window_is_still_green(
    repo: Path, tmp_path: Path
) -> None:
    _add(repo, "infra/example.md", f"{_PILOT}\n")
    soon = (TODAY + dt.timedelta(days=3)).isoformat()
    entries = lint.load_allowlist(_allowlist(tmp_path, _entry(until=soon)))
    report = lint.evaluate(lint.scan_tree(repo), entries, TODAY)
    assert report.ok
    assert len(report.warning) == 1


def test_entry_is_scoped_to_its_path_and_its_addresses(
    repo: Path, tmp_path: Path
) -> None:
    """A path-only waiver would also permit the next address added to the
    same file, and the same address in a different file."""
    _add(repo, "infra/example.md", f"{_PILOT}\n{_BRIDGE}\n")
    _add(repo, "other.md", f"{_PILOT}\n")
    entries = lint.load_allowlist(_allowlist(tmp_path, _entry()))
    report = lint.evaluate(lint.scan_tree(repo), entries, TODAY)
    violations = {(f.path, f.address) for f in report.violations}
    assert violations == {
        ("infra/example.md", _BRIDGE),
        ("other.md", _PILOT),
    }


def test_unused_entry_is_reported_but_does_not_fail(
    repo: Path, tmp_path: Path
) -> None:
    entries = lint.load_allowlist(_allowlist(tmp_path, _entry()))
    report = lint.evaluate(lint.scan_tree(repo), entries, TODAY)
    assert report.ok
    assert len(report.unused) == 1


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"until": "not-a-date"}, "not an ISO date"),
        ({"reason": "too short"}, "characters"),
        ({"tracking": "https://example.com/x/1"}, "tracking"),
        ({"owner": "  "}, "owner"),
        ({"addresses": []}, "non-empty list"),
        ({"addresses": ["192.0.2.1"]}, "hides nothing"),
    ],
)
def test_malformed_entry_is_refused(
    tmp_path: Path, overrides: dict, fragment: str
) -> None:
    path = _allowlist(tmp_path, _entry(**overrides))
    with pytest.raises(lint.AllowlistError) as excinfo:
        lint.load_allowlist(path)
    assert fragment in str(excinfo.value)


def test_missing_mandatory_member_is_refused(tmp_path: Path) -> None:
    entry = _entry()
    del entry["until"]
    with pytest.raises(lint.AllowlistError) as excinfo:
        lint.load_allowlist(_allowlist(tmp_path, entry))
    assert "until" in str(excinfo.value)


def test_absent_allowlist_is_an_error_not_an_empty_one(tmp_path: Path) -> None:
    with pytest.raises(lint.AllowlistError) as excinfo:
        lint.load_allowlist(tmp_path / "nope.json")
    assert "not found" in str(excinfo.value)


def test_wrong_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"schema": "other/v9", "entries": []}), encoding="utf-8")
    with pytest.raises(lint.AllowlistError):
        lint.load_allowlist(path)


# ---------------------------------------------------------------------------
# The gate as it runs in CI.
# ---------------------------------------------------------------------------


def test_self_exclusion_is_exactly_three_files() -> None:
    """A self-exclusion is a hole in the scanner. It is pinned here so
    widening it into a directory means editing this assertion and saying
    why in the diff."""
    assert lint.SELF_EXCLUDED == (
        "tooling/ci/private_address_lint.py",
        "tooling/ci/private-address-allowlist.json",
        "tests/ci/test_private_address_lint.py",
    )
    for rel in lint.SELF_EXCLUDED:
        assert (REPO_ROOT / rel).is_file(), f"excluded path does not exist: {rel}"


def test_shipped_allowlist_parses_and_has_no_expired_entries() -> None:
    entries = lint.load_allowlist(lint.ALLOWLIST_PATH)
    expired = [e.path for e in entries if e.is_expired(dt.date.today())]
    assert not expired, f"expired allow-list entries: {expired}"


def test_the_real_tree_has_no_private_addresses() -> None:
    """The gate itself. Green here is only meaningful because
    ``test_injected_address_makes_it_red`` proves the scanner fires."""
    entries = lint.load_allowlist(lint.ALLOWLIST_PATH)
    report = lint.evaluate(lint.scan_tree(REPO_ROOT), entries, dt.date.today())
    assert report.ok, lint.failure_text(report)


def test_cli_check_exits_zero_on_the_real_tree() -> None:
    assert lint._main(["--check"]) == 0
