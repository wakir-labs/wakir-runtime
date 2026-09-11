#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Time-boxed allowlist for the cross-repo compatibility gate.

File: ``tooling/compat/compat-allowlist.json``

.. code-block:: json

    {
      "schema": "wakir-compat-allowlist/v1",
      "entries": [
        {
          "path": "wirelang/schemas/example.json",
          "until": "2026-09-30",
          "tracking": "https://github.com/wakir-labs/wakir-runtime/pull/123",
          "reason": "optional free text"
        }
      ]
    }

Rules (identical in wakir-protocol):

* ``path`` — repo-relative path of the mirrored file **in this repo**
  whose drift is tolerated. Exact match, no globs.
* ``until`` — ISO date (``YYYY-MM-DD``). Mandatory. An entry without
  it, with an unparsable value, or with a date in the past is a gate
  failure — there is no such thing as a permanent waiver.
* ``tracking`` — ``https://github.com/<org>/<repo>/pull/<n>`` or
  ``.../issues/<n>``. Mandatory.
* ``reason`` — optional, ignored by the gate.

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

_TRACKING_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(pull|issues)/[0-9]+$"
)


class AllowlistError(ValueError):
    """Raised when the allowlist file or one of its entries is invalid."""


@dataclass(frozen=True)
class AllowlistEntry:
    path: str
    until: _dt.date
    tracking: str
    reason: str = ""

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
        unknown = set(raw) - {"path", "until", "tracking", "reason"}
        if unknown:
            raise AllowlistError(f"entries[{index}] has unknown keys: {sorted(unknown)}")
        path = raw.get("path")
        if not isinstance(path, str) or not path or path.startswith("/") or "*" in path:
            raise AllowlistError(f"entries[{index}].path must be a non-empty repo-relative path")
        if path in seen:
            raise AllowlistError(f"entries[{index}].path duplicates an earlier entry: {path!r}")
        seen.add(path)
        if "until" not in raw:
            raise AllowlistError(f"entries[{index}] is missing mandatory 'until'")
        until = _parse_date(raw["until"], index)
        tracking = raw.get("tracking")
        if not isinstance(tracking, str) or not _TRACKING_RE.match(tracking):
            raise AllowlistError(
                f"entries[{index}].tracking must be a GitHub PR or issue URL, got {tracking!r}"
            )
        reason = raw.get("reason", "")
        if not isinstance(reason, str):
            raise AllowlistError(f"entries[{index}].reason must be a string")
        entries.append(AllowlistEntry(path=path, until=until, tracking=tracking, reason=reason))
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
