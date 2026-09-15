# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""An exemption date that is never compared to today is not a deadline.

This module is the gate ADR-0075 §3 asks for, in its hard form. The
supervisory board approved the hard variant on 2026-09-15 and rejected
alternative (d), "expiry dates as a warning only", with the record of
the softer choice in front of it: 22 modules marked ``deliberate: true``
that had never run.

So: an expired ``review_by`` fails here, and this module runs inside the
required ``wirelang suite with rfc8785 + jsonschema`` context. On the
morning a date passes, the repository goes red. That is not a side
effect; it is the decision.

Structure
---------

The live assertions are two: nothing in ``lane_assignment.json`` is
expired, and nothing in it is malformed. Everything else here is a
negative control against injected documents, because a gate whose
failure path has never been executed is a gate nobody has tested — the
class of defect this whole wave is about. Each control names the way it
could go wrong.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tooling" / "ci" / "exemption_expiry.py"
RENEWAL_TOOL_PATH = REPO_ROOT / "tooling" / "ci" / "check_exemption_renewal.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


expiry = _load(TOOL_PATH, "wakir_exemption_expiry")
renewal = _load(RENEWAL_TOOL_PATH, "wakir_exemption_renewal")

TODAY = dt.date(2026, 9, 15)


def _doc(**overrides) -> dict:
    group = {
        "profile": "unassigned",
        "reason": "x" * 130,
        "owner": "someone",
        "deliberate": False,
        "review_by": "2026-12-31",
    }
    group.update(overrides)
    return {"exemption_groups": {"a-group": group}}


# ---------------------------------------------------------------------------
# The live file.
# ---------------------------------------------------------------------------


def test_no_exemption_in_the_repository_has_expired() -> None:
    """The gate itself. Red on the day a review date passes.

    When this fails, the failure text names the group, the owner and the
    three legitimate ways forward. Widening the warning window is not
    one of them.
    """
    document = expiry.load_document()
    today = dt.date.today()
    try:
        statuses = expiry.evaluate(document, today)
    except expiry.ExpiryProblem as exc:  # malformed is as bad as expired
        pytest.fail(str(exc))
    assert not expiry.expired(statuses), expiry.failure_text(statuses)


def test_every_group_in_the_repository_carries_a_usable_date() -> None:
    """Mandatory field, not merely a conventional one.

    ``evaluate`` raises on a group without ``review_by``, on an
    unparsable one, and on a renewal whose author did not write a
    reason. Calling it here is how the live file gets that treatment.
    """
    statuses = expiry.evaluate(expiry.load_document(), dt.date.today())
    assert statuses, "no exemption groups evaluated — the gate would be vacuous"
    for status in statuses:
        assert isinstance(status.review_by, dt.date)
        assert status.owner and status.owner != "?", f"{status.name}: no owner"


def test_the_gate_does_not_take_the_calendar_from_the_caller() -> None:
    """No workflow may tell this check what day it is.

    A ``--today`` flag would be the obvious escape hatch, used on exactly
    the day it should not be. The CLI has none; the tests reach
    ``evaluate`` directly, which is not reachable from a workflow step.
    """
    source = TOOL_PATH.read_text(encoding="utf-8")
    assert '"--today"' not in source and "'--today'" not in source
    workflows = REPO_ROOT / ".github" / "workflows"
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "exemption_expiry.py" not in text:
            continue
        assert "--today" not in text, (
            f"{path.name} passes a date to the expiry gate. The gate reads "
            "the system calendar; a caller-supplied date turns it off."
        )


# ---------------------------------------------------------------------------
# Negative controls: the failure path, executed.
# ---------------------------------------------------------------------------


def test_an_expired_date_is_red_not_a_warning() -> None:
    """The decision of 2026-09-15, as a test.

    One day past ``review_by`` is `expired`, not `warning`. If this ever
    becomes a warning again, alternative (d) has been reintroduced by
    accident.
    """
    statuses = expiry.evaluate(_doc(review_by="2026-09-14"), TODAY)
    assert [s.state for s in statuses] == [expiry.EXPIRED]
    assert expiry.expired(statuses)
    text = expiry.failure_text(statuses)
    assert "a-group" in text and "1 day(s) ago" in text


def test_the_day_itself_is_already_red() -> None:
    """``review_by`` is the last day it is *not* valid, not the last day it is.

    An off-by-one here would be invisible for six weeks and then wrong
    for exactly one day, which is the worst possible way to be wrong.
    """
    assert expiry.evaluate(_doc(review_by="2026-09-15"), TODAY)[0].state == (
        expiry.WARNING
    )
    assert expiry.evaluate(_doc(review_by="2026-09-14"), TODAY)[0].state == (
        expiry.EXPIRED
    )


def test_the_warning_window_is_fourteen_days_and_does_not_fail() -> None:
    assert expiry.WARN_DAYS == 14
    inside = expiry.evaluate(_doc(review_by="2026-09-29"), TODAY)
    assert inside[0].state == expiry.WARNING
    assert not expiry.expired(inside), "a warning must not fail the lane"

    outside = expiry.evaluate(_doc(review_by="2026-09-30"), TODAY)
    assert outside[0].state == expiry.OK


def test_a_missing_date_is_a_problem_not_a_pass() -> None:
    """The failure mode the old file had: absence read as "fine"."""
    group = _doc()["exemption_groups"]["a-group"]
    del group["review_by"]
    with pytest.raises(expiry.ExpiryProblem, match="no review_by"):
        expiry.evaluate({"exemption_groups": {"a-group": group}}, TODAY)


def test_a_malformed_date_is_a_problem() -> None:
    with pytest.raises(expiry.ExpiryProblem, match="not an ISO date"):
        expiry.evaluate(_doc(review_by="soon"), TODAY)


def test_an_empty_document_fails_rather_than_passing_vacuously() -> None:
    """A gate over nothing is the shape of every finding in this wave."""
    with pytest.raises(expiry.ExpiryProblem, match="no exemption_groups"):
        expiry.evaluate({"exemption_groups": {}}, TODAY)


def test_renewal_requires_a_reason_with_substance() -> None:
    with pytest.raises(expiry.ExpiryProblem, match="renewal_reason"):
        expiry.evaluate(
            _doc(review_by="2026-12-31", renewed_on="2026-09-15", renewal_reason="ok"),
            TODAY,
        )


def test_renewal_requires_a_date_for_the_reason() -> None:
    with pytest.raises(expiry.ExpiryProblem, match="without renewed_on"):
        expiry.evaluate(_doc(renewal_reason="y" * 80), TODAY)


def test_a_renewal_must_move_the_date_forward() -> None:
    with pytest.raises(expiry.ExpiryProblem, match="not before review_by"):
        expiry.evaluate(
            _doc(
                review_by="2026-09-01",
                renewed_on="2026-09-15",
                renewal_reason="y" * 80,
            ),
            TODAY,
        )


def test_a_well_formed_renewal_passes() -> None:
    statuses = expiry.evaluate(
        _doc(
            review_by="2026-12-31",
            renewed_on="2026-09-15",
            renewal_reason=(
                "The SPIRE federation root has now run in CI four times "
                "without a divergence from local behaviour; the promotion "
                "waits on maintainer capacity, not on evidence."
            ),
        ),
        TODAY,
    )
    assert statuses[0].state == expiry.OK
    assert statuses[0].renewed_on == dt.date(2026, 9, 15)


def test_the_summary_names_what_is_about_to_break() -> None:
    table = expiry.render_markdown(
        expiry.evaluate(_doc(review_by="2026-09-20"), TODAY), TODAY
    )
    assert "warning" in table and "a-group" in table and "2026-09-20" in table


# ---------------------------------------------------------------------------
# The allow-lists are exemptions too.
# ---------------------------------------------------------------------------


def test_an_allow_list_entry_needs_a_date_like_any_other_exemption() -> None:
    """Both collect-gate allow-lists are empty, and that is the state to
    defend — but the rule has to exist before the first entry, because
    the first entry will be added on a day when somebody is in a hurry.
    """
    document = _doc()
    document["zero_collect_allowed"] = {
        "tests/somewhere/test_thing.py": {"reason": "r" * 130, "owner": "someone"}
    }
    with pytest.raises(expiry.ExpiryProblem, match="no review_by"):
        expiry.evaluate(document, TODAY)


def test_a_bare_allow_list_value_is_refused() -> None:
    document = _doc()
    document["import_guard_allowed"] = {"some_wheel": "because"}
    with pytest.raises(expiry.ExpiryProblem, match="needs an object"):
        expiry.evaluate(document, TODAY)


def test_an_expired_allow_list_entry_is_red() -> None:
    document = _doc()
    document["import_guard_allowed"] = {
        "some_wheel": {
            "reason": "r" * 130,
            "owner": "someone",
            "review_by": "2026-08-01",
        }
    }
    statuses = expiry.evaluate(document, TODAY)
    names = {s.name for s in expiry.expired(statuses)}
    assert names == {"import_guard_allowed[some_wheel]"}


def test_the_live_allow_lists_are_still_empty() -> None:
    """Not a rule, a record. If this ever fails, read the entry's reason
    and its date — that is what they are for."""
    document = expiry.load_document()
    assert document["zero_collect_allowed"] == {}
    assert document["import_guard_allowed"] == {}


# ---------------------------------------------------------------------------
# The half a hermetic test cannot do: was the date moved, or renewed?
# ---------------------------------------------------------------------------


def _pair(before: dict, after: dict) -> tuple[dict, dict]:
    return (
        {"exemption_groups": {"a-group": before}},
        {"exemption_groups": {"a-group": after}},
    )


def test_moving_a_date_without_renewing_is_refused() -> None:
    """The comfortable way out, closed.

    On the morning the lane goes red, editing one character brings the
    exemption back for six weeks and leaves no trace. This is the check
    that turns that edit into a rejected pull request.
    """
    base, head = _pair(
        {"review_by": "2026-09-30"},
        {"review_by": "2026-12-31"},
    )
    problems = renewal.renewal_problems(base, head)
    assert len(problems) == 1 and "without setting `renewed_on`" in problems[0]


def test_renewing_properly_is_accepted() -> None:
    base, head = _pair(
        {"review_by": "2026-09-30"},
        {
            "review_by": "2026-12-31",
            "renewed_on": "2026-09-15",
            "renewal_reason": (
                "The manual opt-in run is scheduled for the week of "
                "2026-10-05 and needs an operator window that does not exist "
                "before then."
            ),
        },
    )
    assert renewal.renewal_problems(base, head) == []


def test_recycling_the_previous_renewal_reason_is_refused() -> None:
    reason = "z" * 80
    base, head = _pair(
        {"review_by": "2026-09-30", "renewed_on": "2026-08-01", "renewal_reason": reason},
        {"review_by": "2026-12-31", "renewed_on": "2026-09-15", "renewal_reason": reason},
    )
    problems = renewal.renewal_problems(base, head)
    assert len(problems) == 1 and "previous renewal" in problems[0]


def test_a_new_group_sets_its_first_date_without_a_renewal() -> None:
    """Creating an exemption is not renewing one."""
    base = {"exemption_groups": {}}
    head = {"exemption_groups": {"a-group": {"review_by": "2026-12-31"}}}
    assert renewal.renewal_problems(base, head) == []


def test_an_unchanged_date_is_not_a_renewal() -> None:
    base, head = _pair({"review_by": "2026-09-30"}, {"review_by": "2026-09-30"})
    assert renewal.renewal_problems(base, head) == []
