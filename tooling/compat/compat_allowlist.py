#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Time-boxed allowlist for the cross-repo compatibility gate.

File: ``tooling/compat/compat-allowlist.json`` — same format as
``wakir-protocol/tooling/compat/compat-allowlist.json``.

.. code-block:: json

    {
      "schema": "wakir-compat-allowlist/v1",
      "entries": [
        {
          "repo": "protocol",
          "path": "wirelang/schemas/example.json",
          "reason": "why the drift is tolerated and what removes it",
          "until": "2026-09-30",
          "tracking": "https://github.com/wakir-labs/wakir-runtime/pull/123"
        }
      ]
    }

Every entry carries exactly these five mandatory members, no others:

* ``repo`` — the *other* side whose copy drifts from ours
  (``protocol`` or ``verify``; ``runtime`` is accepted for symmetry
  with the protocol-side file).
* ``path`` — repo-relative path of the mirrored file **in this repo**
  whose drift is tolerated. Exact match, no globs.
* ``reason`` — non-empty free text.
* ``until`` — ISO date (``YYYY-MM-DD``). A missing or unparsable
  value or a date in the past is a gate failure — there is no such
  thing as a permanent waiver.
* ``tracking`` — ``https://github.com/wakir-labs/<repo>/pull/<n>`` or
  ``.../issues/<n>``.

The gate reports entries that did not match any drift as ``warn`` so
stale waivers are visible and get removed.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ALLOWLIST_SCHEMA = "wakir-compat-allowlist/v1"

REQUIRED_KEYS = frozenset({"repo", "path", "reason", "until", "tracking"})
REPOS = frozenset({"runtime", "protocol", "verify"})

_TRACKING_RE = re.compile(
    r"^https://github\.com/wakir-labs/[A-Za-z0-9_.-]+/(pull|issues)/[0-9]+$"
)


class AllowlistError(ValueError):
    """Raised when the allowlist file or one of its entries is invalid."""


@dataclass(frozen=True)
class AllowlistEntry:
    repo: str
    path: str
    reason: str
    until: _dt.date
    tracking: str

    def is_active(self, today: _dt.date) -> bool:
        return self.until >= today


def _parse_date(value: Any, index: int) -> _dt.date:
    if not isinstance(value, str):
        raise AllowlistError(f"entries[{index}].until must be a YYYY-MM-DD string")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise AllowlistError(f"entries[{index}].until is not a valid date: {value!r}") from exc


def parse_entries(data: Any) -> list[AllowlistEntry]:
    """Validate the parsed allowlist document and return its entries."""
    if not isinstance(data, dict):
        raise AllowlistError("allowlist top-level must be a JSON object")
    if data.get("schema") != ALLOWLIST_SCHEMA:
        raise AllowlistError(
            f"allowlist schema must be {ALLOWLIST_SCHEMA!r}, got {data.get('schema')!r}"
        )
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise AllowlistError("allowlist 'entries' must be a list")

    entries: list[AllowlistEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise AllowlistError(f"entries[{index}] must be an object")
        missing = REQUIRED_KEYS - set(raw)
        if missing:
            if "until" in missing:
                raise AllowlistError(f"entries[{index}] is missing mandatory 'until'")
            raise AllowlistError(f"entries[{index}] is missing mandatory keys: {sorted(missing)}")
        unknown = set(raw) - REQUIRED_KEYS
        if unknown:
            raise AllowlistError(f"entries[{index}] has unknown keys: {sorted(unknown)}")

        repo = raw["repo"]
        if repo not in REPOS:
            raise AllowlistError(f"entries[{index}].repo must be one of {sorted(REPOS)}, got {repo!r}")
        path = raw["path"]
        if not isinstance(path, str) or not path or path.startswith("/") or "*" in path:
            raise AllowlistError(f"entries[{index}].path must be a non-empty repo-relative path")
        if path in seen:
            raise AllowlistError(f"entries[{index}].path duplicates an earlier entry: {path!r}")
        seen.add(path)
        reason = raw["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistError(f"entries[{index}].reason must be a non-empty string")
        until = _parse_date(raw["until"], index)
        tracking = raw["tracking"]
        if not isinstance(tracking, str) or not _TRACKING_RE.match(tracking):
            raise AllowlistError(
                f"entries[{index}].tracking must be a wakir-labs GitHub PR or issue URL, got {tracking!r}"
            )
        entries.append(AllowlistEntry(repo=repo, path=path, reason=reason, until=until, tracking=tracking))
    return entries


def load_allowlist(path: str | Path) -> list[AllowlistEntry]:
    """Load and validate the allowlist at ``path``.

    A missing file is equivalent to an empty allowlist.
    """
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AllowlistError(f"allowlist {file_path} is not valid JSON: {exc}") from exc
    return parse_entries(data)


def expired_entries(entries: Iterable[AllowlistEntry], today: _dt.date) -> list[AllowlistEntry]:
    """Entries whose ``until`` date lies in the past."""
    return [entry for entry in entries if not entry.is_active(today)]


def active_index(entries: Iterable[AllowlistEntry], today: _dt.date) -> dict[str, AllowlistEntry]:
    """Map ``path -> entry`` for entries still in force."""
    return {entry.path: entry for entry in entries if entry.is_active(today)}
