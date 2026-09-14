#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exemption dates, compared against the calendar (ADR-0075 §3).

Why this file exists
--------------------

``tests/lanes/lane_assignment.json`` has carried a ``review_by`` date on
every exemption group since the test inventory landed. Nothing compared
those dates to today. The only assertion was that the string parsed as
an ISO date, and a ``grep`` for ``today`` or ``now()`` across the lane
tooling returned zero hits. A date that is never compared to today is
not a deadline; it is a longer way of writing an undated exception.

ADR-0075 §3 (approved 2026-09-15, hard variant; alternative (d),
"expiry dates as a warning only", was rejected) settles it:

    Every documented exemption from a check — lane exemption, deselect,
    allow-list entry, opt-in marker — carries a mandatory expiry field,
    and **the date is compared against the calendar at check time**. An
    expired exemption turns the corresponding required lane red; it does
    not quietly stop applying.

    Damper: warning from ``review_by - 14 days``, red from ``review_by``.
    Renewal is allowed and requires ``renewed_on`` and
    ``renewal_reason`` — which replaces silent lapse with a visible
    decision that has an author.

The in-house reference implementation is ``wakir-protocol``
``tooling/compat/allowlist.py`` (``until`` mandatory, ``until < today``
raises). This module takes the semantics, not the code, and adds the
damper the ADR asks for.

What this deliberately does not do
----------------------------------

It cannot see history, so it cannot tell a first date from a quietly
extended one. That half is enforced by
``tooling/ci/check_exemption_renewal.py``, which diffs the file against
the pull request's base commit. The two together are the mechanism; this
half alone would let someone move a date rather than renew it.

Usage::

    python tooling/ci/exemption_expiry.py --check     # exit 1 when expired
    python tooling/ci/exemption_expiry.py --summary   # markdown, never fails
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_PATH = REPO_ROOT / "tests" / "lanes" / "lane_assignment.json"

#: Days before ``review_by`` at which the summary starts warning. The
#: damper from ADR-0075 §3 — it limits the surprise, not the
#: interruption.
WARN_DAYS = 14

#: A renewal reason short enough to fit in a commit subject is not a
#: reason, it is a shrug. Same threshold logic as the 120-character
#: floor on exemption reasons in ``test_lane_assignment.py``.
MIN_RENEWAL_REASON = 60

OK = "ok"
WARNING = "warning"
EXPIRED = "expired"


@dataclass(frozen=True)
class GroupStatus:
    """One exemption group, evaluated against one specific day."""

    name: str
    profile: str
    owner: str
    review_by: dt.date
    days_left: int
    state: str
    renewed_on: dt.date | None = None

    @property
    def is_expired(self) -> bool:
        return self.state == EXPIRED


class ExpiryProblem(Exception):
    """A malformed or expired exemption. Carries the operator-facing text."""


def _parse_date(value: object, where: str) -> dt.date:
    if not isinstance(value, str):
        raise ExpiryProblem(f"{where}: expected an ISO date string, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ExpiryProblem(f"{where}: {value!r} is not an ISO date ({exc})") from exc


def load_document(path: Path = ASSIGNMENT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


#: The three places this repository records an exemption from a check.
#: ADR-0075 §3 names all of them — lane exemption, deselect, allow-list
#: entry, opt-in marker — and gives them one rule, so they are read
#: through one function rather than three.
ALLOW_LISTS: tuple[str, ...] = ("zero_collect_allowed", "import_guard_allowed")


def _exemptions(document: dict) -> list[tuple[str, dict]]:
    """``(display name, entry)`` for every exemption in the document.

    The two collect-gate allow-lists are empty at the time this check
    was written, and the file says keeping them empty is the point. They
    are read anyway: an entry added later would otherwise be the one
    exemption in the repository with no end date, and it would be added
    on a day when somebody is in a hurry.
    """
    found = [(name, group) for name, group in document["exemption_groups"].items()]
    for list_name in ALLOW_LISTS:
        entries = document.get(list_name) or {}
        if not isinstance(entries, dict):
            raise ExpiryProblem(
                f"{list_name} must be an object keyed by the allow-listed "
                "name, so each entry can carry a reason and a date"
            )
        for key, entry in entries.items():
            if not isinstance(entry, dict):
                raise ExpiryProblem(
                    f"{list_name}[{key!r}]: an allow-list entry is an "
                    "exemption, so it needs an object with `reason`, "
                    "`owner` and `review_by` — not a bare value. "
                    "ADR-0075 §3."
                )
            found.append((f"{list_name}[{key}]", entry))
    return found


def evaluate(
    document: dict, today: dt.date, warn_days: int = WARN_DAYS
) -> list[GroupStatus]:
    """Every exemption group's state on ``today``, sorted by urgency.

    Raises ``ExpiryProblem`` for a group that is malformed — a missing
    date, an unparsable one, a renewal without an author's reason. A
    malformed exemption is treated exactly like an expired one, because
    the alternative is an exemption that cannot be checked at all.
    """
    groups = document.get("exemption_groups")
    if not isinstance(groups, dict) or not groups:
        raise ExpiryProblem(
            "no exemption_groups in the assignment document — either the "
            "file is wrong or this check is pointed at the wrong file, and "
            "both mean the expiry gate is not running"
        )

    statuses: list[GroupStatus] = []
    for name, group in sorted(_exemptions(document)):
        where = f"exemption {name!r}"
        if "review_by" not in group:
            raise ExpiryProblem(
                f"{where}: no review_by. ADR-0075 §3 makes the expiry field "
                "mandatory for every exemption, including deliberate ones — "
                "a standing exception with no end date is the state the ADR "
                "closes."
            )
        review_by = _parse_date(group["review_by"], f"{where} review_by")

        renewed_on: dt.date | None = None
        has_reason = bool(str(group.get("renewal_reason", "")).strip())
        if "renewed_on" in group:
            renewed_on = _parse_date(group["renewed_on"], f"{where} renewed_on")
            if renewed_on > today:
                raise ExpiryProblem(
                    f"{where}: renewed_on {renewed_on} is in the future "
                    f"(today is {today})"
                )
            reason = str(group.get("renewal_reason", "")).strip()
            if len(reason) < MIN_RENEWAL_REASON:
                raise ExpiryProblem(
                    f"{where}: renewed_on is set but renewal_reason is "
                    f"{len(reason)} characters. ADR-0075 §3 trades the silent "
                    "lapse for a visible decision with an author; a renewal "
                    "without a reason is the silent lapse with extra steps."
                )
            if review_by <= renewed_on:
                raise ExpiryProblem(
                    f"{where}: renewed_on {renewed_on} is not before review_by "
                    f"{review_by}. A renewal moves the date forward; this one "
                    "does not."
                )
        elif has_reason:
            raise ExpiryProblem(
                f"{where}: renewal_reason without renewed_on — the reason "
                "records a decision nobody dated."
            )

        days_left = (review_by - today).days
        if days_left < 0:
            state = EXPIRED
        elif days_left <= warn_days:
            state = WARNING
        else:
            state = OK
        statuses.append(
            GroupStatus(
                name=name,
                profile=str(group.get("profile", "?")),
                owner=str(group.get("owner", "?")),
                review_by=review_by,
                days_left=days_left,
                state=state,
                renewed_on=renewed_on,
            )
        )
    statuses.sort(key=lambda s: (s.days_left, s.name))
    return statuses


def expired(statuses: list[GroupStatus]) -> list[GroupStatus]:
    return [s for s in statuses if s.is_expired]


def failure_text(statuses: list[GroupStatus]) -> str:
    """The message an engineer reads on the day the gate goes red."""
    lines = [
        "expired exemptions (ADR-0075 §3): an exemption whose review date "
        "has passed fails the lane it exempts. It does not quietly stop "
        "applying.",
        "",
    ]
    for status in expired(statuses):
        lines.append(
            f"  {status.name}: review_by {status.review_by} passed "
            f"{-status.days_left} day(s) ago — owner {status.owner}"
        )
    lines += [
        "",
        "Three ways forward, in the order they should be considered:",
        "  1. Do the thing the date was for (promote the lane, run the "
        "drill, delete the exception). Best outcome; the date did its job.",
        "  2. Renew it: set `renewed_on` to today and write a "
        "`renewal_reason` that says why it is still true. This is allowed "
        "and is supposed to cost a reviewed diff with your name on it.",
        "  3. If the exception is obsolete, delete the group and the "
        "modules' `group` keys with it.",
        "",
        "What is not a way forward: widening the warning window, or moving "
        "the date without a renewal reason. `tooling/ci/check_exemption_"
        "renewal.py` fails the second one on the pull request.",
    ]
    return "\n".join(lines)


_ICON = {OK: "ok", WARNING: "⚠ warning", EXPIRED: "✗ EXPIRED"}


def render_markdown(statuses: list[GroupStatus], today: dt.date) -> str:
    lines = [
        "## Exemption expiry (ADR-0075 §3)",
        "",
        f"Evaluated against `{today.isoformat()}`. "
        f"Warning from `review_by − {WARN_DAYS}` days, red from `review_by`.",
        "",
        "| group | profile | owner | review_by | days left | state |",
        "|---|---|---|---:|---:|---|",
    ]
    for s in statuses:
        renewed = f" (renewed {s.renewed_on})" if s.renewed_on else ""
        lines.append(
            f"| `{s.name}`{renewed} | {s.profile} | {s.owner} | "
            f"{s.review_by} | {s.days_left} | {_ICON[s.state]} |"
        )
    warnings = [s for s in statuses if s.state == WARNING]
    if warnings:
        lines += [
            "",
            "**Within the warning window.** Nothing is failing yet. Each of "
            "these becomes a red required lane on its review date:",
            "",
        ]
        lines += [f"- `{s.name}` → {s.review_by} ({s.owner})" for s in warnings]
    if expired(statuses):
        lines += ["", "**Expired — the lane-assignment suite is failing.**", ""]
        lines += [f"- `{s.name}` → {s.review_by} ({s.owner})" for s in expired(statuses)]
    return "\n".join(lines) + "\n"


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when an exemption is expired or malformed",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help=(
            "write the markdown table to $GITHUB_STEP_SUMMARY (or stdout). "
            "Never fails on its own — the gate is --check and the pytest "
            "module that wraps it."
        ),
    )
    parser.add_argument("--assignment", default=str(ASSIGNMENT_PATH))
    args = parser.parse_args(argv)

    # Deliberately no `--today` override. A flag that moves the calendar
    # is a flag that turns this gate off, and it would be used on exactly
    # the day it should not be. The tests inject a date through
    # `evaluate(...)` directly, which is not reachable from a workflow.
    today = dt.date.today()
    document = load_document(Path(args.assignment))

    try:
        statuses = evaluate(document, today)
    except ExpiryProblem as exc:
        print(str(exc), file=sys.stderr)
        return 1

    table = render_markdown(statuses, today)
    if args.summary:
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(table)
        else:
            sys.stdout.write(table)

    if args.check:
        if expired(statuses):
            print(failure_text(statuses), file=sys.stderr)
            return 1
        print(
            f"exemption expiry ok on {today}: "
            f"{len(statuses)} group(s), "
            f"{sum(1 for s in statuses if s.state == WARNING)} in the warning window"
        )
    elif not args.summary:
        sys.stdout.write(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
