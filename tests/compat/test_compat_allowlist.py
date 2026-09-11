# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``tooling/compat/compat_allowlist.py``."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLING = REPO_ROOT / "tooling" / "compat"


def _load(name: str):
    if str(TOOLING) not in sys.path:
        sys.path.insert(0, str(TOOLING))
    spec = importlib.util.spec_from_file_location(name, TOOLING / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


allow = _load("compat_allowlist")

TODAY = dt.date(2026, 9, 11)
TRACKING = "https://github.com/wakir-labs/wakir-runtime/pull/999"


def _doc(*entries):
    return {"schema": allow.ALLOWLIST_SCHEMA, "entries": list(entries)}


def _entry(**overrides):
    base = {"path": "wirelang/schemas/x.json", "until": "2026-12-31", "tracking": TRACKING}
    base.update(overrides)
    for key in [k for k, v in base.items() if v is ...]:
        base.pop(key)
    return base


def test_valid_entry_parses_and_is_active():
    entries = allow.parse_entries(_doc(_entry(reason="bridge until mirror PR")))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.path == "wirelang/schemas/x.json"
    assert entry.until == dt.date(2026, 12, 31)
    assert entry.tracking == TRACKING
    assert entry.is_active(TODAY)
    assert allow.active_index(entries, TODAY) == {"wirelang/schemas/x.json": entry}
    assert allow.expired_entries(entries, TODAY) == []


def test_missing_until_is_invalid():
    with pytest.raises(allow.AllowlistError, match="missing mandatory 'until'"):
        allow.parse_entries(_doc(_entry(until=...)))


@pytest.mark.parametrize("bad", ["someday", "2026-13-01", 20261231, None, ""])
def test_unparsable_until_is_invalid(bad):
    with pytest.raises(allow.AllowlistError):
        allow.parse_entries(_doc(_entry(until=bad)))


def test_expired_entry_is_reported_not_active():
    entries = allow.parse_entries(_doc(_entry(until="2026-09-10")))
    assert not entries[0].is_active(TODAY)
    assert allow.expired_entries(entries, TODAY) == entries
    assert allow.active_index(entries, TODAY) == {}


def test_until_equal_to_today_is_still_active():
    entries = allow.parse_entries(_doc(_entry(until=TODAY.isoformat())))
    assert entries[0].is_active(TODAY)


@pytest.mark.parametrize(
    "bad",
    [
        ...,
        "",
        "PR 123",
        "http://github.com/wakir-labs/wakir-runtime/pull/1",
        "https://github.com/wakir-labs/wakir-runtime",
        "https://github.com/wakir-labs/wakir-runtime/pull/",
        "https://gitlab.com/x/y/merge_requests/1",
    ],
)
def test_tracking_must_be_github_pr_or_issue_url(bad):
    with pytest.raises(allow.AllowlistError, match="tracking"):
        allow.parse_entries(_doc(_entry(tracking=bad)))


def test_issue_url_is_accepted():
    entries = allow.parse_entries(_doc(_entry(tracking="https://github.com/wakir-labs/wakir-protocol/issues/7")))
    assert entries[0].tracking.endswith("/issues/7")


@pytest.mark.parametrize("bad", ["", "/abs/path.json", "wirelang/schemas/*.json", 42])
def test_path_must_be_relative_exact(bad):
    with pytest.raises(allow.AllowlistError, match="path"):
        allow.parse_entries(_doc(_entry(path=bad)))


def test_duplicate_paths_rejected():
    with pytest.raises(allow.AllowlistError, match="duplicates"):
        allow.parse_entries(_doc(_entry(), _entry()))


def test_unknown_keys_rejected():
    with pytest.raises(allow.AllowlistError, match="unknown keys"):
        allow.parse_entries(_doc(_entry(permanent=True)))


def test_wrong_schema_or_shape_rejected():
    with pytest.raises(allow.AllowlistError, match="schema"):
        allow.parse_entries({"schema": "other/v1", "entries": []})
    with pytest.raises(allow.AllowlistError, match="entries"):
        allow.parse_entries({"schema": allow.ALLOWLIST_SCHEMA, "entries": {}})
    with pytest.raises(allow.AllowlistError, match="object"):
        allow.parse_entries([])


def test_load_missing_file_is_empty(tmp_path: Path):
    assert allow.load_allowlist(tmp_path / "nope.json") == []


def test_load_invalid_json_raises(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(allow.AllowlistError, match="not valid JSON"):
        allow.load_allowlist(path)


def test_shipped_allowlist_is_valid_and_not_expired():
    shipped = TOOLING / "compat-allowlist.json"
    entries = allow.load_allowlist(shipped)
    assert json.loads(shipped.read_text(encoding="utf-8"))["schema"] == allow.ALLOWLIST_SCHEMA
    assert allow.expired_entries(entries, dt.date.today()) == []
