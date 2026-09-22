# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""The level-3 drill is a dated obligation, not a sentence in a runbook.

``docs/observability/substrate-liveness-drill-evidence.json`` records
when the seven-day acceptance window started and when the fallback drill
was last run. This test compares those dates against the calendar, in the
spirit of ADR-0075 section 3: *a date that is never compared to today is
not a deadline, it is a longer way of writing an undated exception.*

Three rules, and each of them closes a way of never being wrong:

1. **The obligation cannot be deferred for ever.** While
   ``seven_day_window_started_on`` is null there is no eighth day to owe
   a drill on — so the file carries ``activate_by``, and a null window
   past that date is red. Without it, "we have not started yet" would be
   a permanently green answer, which is the exact shape of the defect
   the melder was built for.
2. **The first drill is due on day eight.** Not "after the seven-day
   window", which is a phrase, but on a computed date.
3. **The drill recurs.** A fallback test that is run once, on the day
   somebody is proud of it, decays into documentation of a thing that
   used to work. That sentence is the May bilanz: *6/6 PASS* on
   2026-05-15 was true, and meaningless by 2026-05-17.

A run recorded with any result other than ``red-as-expected`` does not
satisfy the obligation. The drill's whole purpose is to come out red on
a substrate that looks healthy; a drill that came out green did not
prove the melder works, it proved it does not.

The arithmetic is tested against injected dates, so these tests do not
change their answer depending on the day they run. The single assertion
that *does* look at today is the last one, and that is the point of the
file.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "observability" / "substrate-liveness-drill-evidence.json"

MIN_RENEWAL_REASON = 60  # same floor as tooling/ci/exemption_expiry.py

OK = "ok"
OVERDUE_ACTIVATION = "overdue-activation"
OVERDUE_DRILL = "overdue-drill"


def load() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def evaluate(document: dict, today: dt.date) -> tuple[str, str]:
    """``(state, human-readable explanation)`` for one specific day."""
    started_raw = document.get("seven_day_window_started_on")

    if started_raw is None:
        activate_by = _date(document["activate_by"])
        if today > activate_by:
            return (
                OVERDUE_ACTIVATION,
                f"the seven-day acceptance window has still not started, and "
                f"activate_by was {activate_by.isoformat()}. Either start it, or "
                f"renew the date with a reason.",
            )
        return OK, f"not yet active; window must start by {activate_by.isoformat()}"

    started = _date(started_raw)
    first_due = started + dt.timedelta(
        days=int(document["first_drill_due_days_after_window_start"])
    )
    good_runs = sorted(
        _date(run["ran_on"])
        for run in document.get("runs", [])
        if run.get("result") == "red-as-expected"
    )
    qualifying = [ran for ran in good_runs if ran >= first_due]

    if not qualifying:
        if today >= first_due:
            return (
                OVERDUE_DRILL,
                f"the seven-day window started {started.isoformat()}, so the "
                f"fallback drill was due {first_due.isoformat()} and no "
                f"red-as-expected run is recorded on or after that date.",
            )
        return OK, f"first drill due {first_due.isoformat()}"

    next_due = qualifying[-1] + dt.timedelta(days=int(document["recheck_interval_days"]))
    if today >= next_due:
        return (
            OVERDUE_DRILL,
            f"the last drill was {qualifying[-1].isoformat()}; the next was due "
            f"{next_due.isoformat()}.",
        )
    return OK, f"next drill due {next_due.isoformat()}"


# --- the file itself --------------------------------------------------


def test_evidence_file_is_well_formed():
    doc = load()
    assert doc["schema"] == "wakir.substrate-liveness-drill-evidence/v1"
    assert doc["owner"]
    _date(doc["activate_by"])
    assert int(doc["first_drill_due_days_after_window_start"]) > 0
    assert int(doc["recheck_interval_days"]) > 0
    assert isinstance(doc["runs"], list)
    started = doc.get("seven_day_window_started_on")
    if started is not None:
        _date(started)
    for run in doc["runs"]:
        _date(run["ran_on"])
        assert run["result"] in {"red-as-expected", "unexpected"}
        assert run.get("evidence"), "a drill run without evidence is a claim"


def test_every_renewal_carries_a_reason_long_enough_to_be_one():
    """A renewal reason short enough to fit in a commit subject is not a
    reason, it is a shrug. Same floor as the exemption machinery."""
    for entry in load().get("renewals", []):
        _date(entry["renewed_on"])
        assert len(entry.get("renewal_reason", "")) >= MIN_RENEWAL_REASON


# --- rule 1: deferral has an end --------------------------------------


def test_null_window_is_ok_before_the_activation_date():
    doc = {**load(), "seven_day_window_started_on": None, "activate_by": "2026-11-30"}
    state, _ = evaluate(doc, dt.date(2026, 11, 29))
    assert state == OK


def test_null_window_is_red_after_the_activation_date():
    """'We have not started yet' must not be a permanently green answer."""
    doc = {**load(), "seven_day_window_started_on": None, "activate_by": "2026-11-30"}
    state, why = evaluate(doc, dt.date(2026, 12, 1))
    assert state == OVERDUE_ACTIVATION
    assert "still not started" in why


# --- rule 2: day eight is a date, not a phrase ------------------------


def test_drill_not_yet_due_before_day_eight():
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "runs": [],
    }
    state, why = evaluate(doc, dt.date(2026, 10, 8))
    assert state == OK
    assert "2026-10-09" in why


def test_drill_overdue_on_day_eight_with_no_run():
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "runs": [],
    }
    state, _ = evaluate(doc, dt.date(2026, 10, 9))
    assert state == OVERDUE_DRILL


def test_a_run_before_day_eight_does_not_satisfy_the_obligation():
    """Running the drill during the seven days proves it works on a
    substrate that has not yet been up for seven days. That is the
    question it was not asked."""
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "runs": [
            {"ran_on": "2026-10-03", "result": "red-as-expected", "evidence": "run/1"}
        ],
    }
    state, _ = evaluate(doc, dt.date(2026, 10, 9))
    assert state == OVERDUE_DRILL


def test_a_green_drill_does_not_satisfy_the_obligation():
    """The drill must come out red on a substrate that looks healthy. A
    drill that came out green did not prove the melder works — it proved
    it does not, and recording it as done would be the exact class of
    defect under attack here."""
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "runs": [{"ran_on": "2026-10-10", "result": "unexpected", "evidence": "run/2"}],
    }
    state, _ = evaluate(doc, dt.date(2026, 10, 11))
    assert state == OVERDUE_DRILL


def test_a_qualifying_run_satisfies_the_obligation():
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "recheck_interval_days": 90,
        "runs": [
            {"ran_on": "2026-10-09", "result": "red-as-expected", "evidence": "run/3"}
        ],
    }
    state, why = evaluate(doc, dt.date(2026, 10, 20))
    assert state == OK
    assert "2027-01-07" in why


# --- rule 3: it recurs ------------------------------------------------


def test_the_obligation_comes_back():
    doc = {
        **load(),
        "seven_day_window_started_on": "2026-10-01",
        "first_drill_due_days_after_window_start": 8,
        "recheck_interval_days": 90,
        "runs": [
            {"ran_on": "2026-10-09", "result": "red-as-expected", "evidence": "run/3"}
        ],
    }
    state, why = evaluate(doc, dt.date(2027, 1, 7))
    assert state == OVERDUE_DRILL
    assert "next was due" in why


# --- and the one assertion that looks at today ------------------------


def test_the_drill_obligation_is_not_overdue_today():
    """This is the assertion the file exists for. It turns a required
    lane red on the day the obligation lapses, which is the only
    difference between a deadline and a note."""
    state, why = evaluate(load(), dt.date.today())
    assert state == OK, (
        f"substrate-liveness drill obligation is {state}: {why}\n"
        "Record the run in docs/observability/substrate-liveness-drill-evidence.json, "
        "or renew the date with a reason. Do not delete the entry."
    )
