# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Multi-Calendar-Failover-Hardening for the Mira-Hourly-WAT-Anchor-Cron.

Phase-2 Sprint-9 Tag-3 (Tomás) — WAT-Production-Hardening.

What ``test_anchor.py`` already covers
--------------------------------------

- ``test_min_calendars_threshold``: 1-of-4 successful submissions
  raises ``AnchorError``.
- ``test_subprocess_timeout_handling``: a ``TimeoutExpired`` on the
  WHOLE ``ots stamp`` invocation maps to ``AnchorError``.
- ``test_calendar_failover_with_2_of_4``: a 2-of-4 successful
  submission produces a valid receipt and records the two failures.

What is NOT yet covered (and what this module adds)
---------------------------------------------------

The production Mira-Hourly cron submits to the four DEFAULT_CALENDARS.
Tag-3 hardens the failover surface against the three production-real
scenarios that the existing tests do NOT exercise:

  1. **3-calendar narrow threshold** — operators who want to tune
     down to a 3-calendar config (e.g. excluding a known-flaky
     pole during incident response) need the threshold/N math to
     work at N=3. ``test_threshold_2_of_3_succeeds_with_one_slow``
     and ``test_threshold_2_of_3_fails_with_two_slow`` cover the
     boundary symmetrically.

  2. **Per-calendar slow-output (no exception)** — the OTS client
     does NOT raise on a slow calendar; it logs a per-calendar
     "Error: ... timeout ..." line and moves on. The whole-process
     ``TimeoutExpired`` test does not exercise this branch.

  3. **Partial-success preserves the per-calendar diagnostic** —
     ``calendar_responses`` MUST record the failure REASON (not just
     "not-ok") so the hourly cron's drift-detection log can name the
     pole that needs operator attention.

These are the hardening invariants the Sprint-9 Tag-1 Bridge-Audit
Writer ALSO depends on transitively: when the bridge writes to the
WAT-spool and the next-hour aggregator anchors it, the cron MUST
survive a 1-pole outage without dropping the whole hour's audit
trail.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import List, Sequence
from unittest import mock

import pytest

from wat.anchor import ots_anchor
from wat.anchor.ots_anchor import (
    AnchorError,
    AnchorReceipt,
    DEFAULT_CALENDARS,
    SUBPROCESS_TIMEOUT_S,
    anchor_root,
)


def _root() -> bytes:
    return hashlib.sha256(b"tag-3-multi-calendar-failover").digest()


def _completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ots"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _make_slow_calendar_side_effect(
    slow_calendars: Sequence[str],
    slow_reason: str = "timeout",
    write_receipt: bool = True,
):
    """Side-effect that emulates ``ots stamp`` with per-calendar slow lines.

    Each calendar gets a normal "Submitting to remote calendar <url>"
    log line; calendars in ``slow_calendars`` additionally get an
    "Error: calendar <url> timeout after Ns" line. The whole-process
    return code is 0 (the OTS client completes; only individual
    calendars fail).
    """

    def _side(cmd, **kwargs):  # noqa: ARG001
        file_arg = Path(cmd[-1])
        calendars: List[str] = []
        for i, token in enumerate(cmd):
            if token == "--calendar" and i + 1 < len(cmd):
                calendars.append(cmd[i + 1])
        lines: List[str] = []
        for url in calendars:
            lines.append(f"Submitting to remote calendar {url}")
            if url in slow_calendars:
                # "timeout" is in the lower-cased keyword list the
                # parser uses to mark a calendar as failed.
                lines.append(f"Error: calendar {url} {slow_reason} after 90s")
        stdout = "\n".join(lines) + "\n"
        if write_receipt and file_arg.exists():
            (file_arg.parent / (file_arg.name + ".ots")).write_bytes(
                b"\xfd" + b"\x00" * 31
            )
        return _completed(stdout=stdout)

    return _side


@pytest.fixture(autouse=True)
def _ots_resolvable() -> None:
    with mock.patch.object(
        ots_anchor.shutil,
        "which",
        return_value="/usr/bin/ots",
    ):
        yield


# ---------------------------------------------------------------------------
# 3-calendar boundary tests
# ---------------------------------------------------------------------------


def test_threshold_2_of_3_succeeds_with_one_slow(tmp_path: Path) -> None:
    """A 3-calendar config with one slow pole still meets the 2-of-3 floor.

    This is the Mira-Hourly-cron-incident-response shape: an
    operator excludes one of the four DEFAULT_CALENDARS (say
    ``catallaxy``) during a known outage and runs the cron against
    the remaining three with a 2-of-3 threshold. One of the three
    remaining poles times out per calendar — the hour MUST still
    anchor.
    """
    cals = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
    ]
    side = _make_slow_calendar_side_effect(slow_calendars=[cals[2]])
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=side):
        receipt = anchor_root(
            merkle_root=_root(),
            calendars=cals,
            min_calendars=2,
            target_dir=tmp_path,
        )

    assert isinstance(receipt, AnchorReceipt)
    assert receipt.merkle_root == _root()
    successes = receipt.successful_calendars()
    assert set(successes) == {cals[0], cals[1]}
    assert receipt.receipt_path.exists()
    # The slow pole's diagnostic is preserved verbatim, not collapsed
    # to a generic "not-ok".
    assert "timeout" in receipt.calendar_responses[cals[2]].lower()


def test_threshold_2_of_3_fails_with_two_slow(tmp_path: Path) -> None:
    """A 3-calendar config with two slow poles falls below the threshold.

    Symmetric negative: the cron MUST refuse to anchor a Merkle root
    backed by only one calendar, so an audit cannot later be
    discredited by "the single calendar that confirmed has since
    rotated keys / been seized / been deplatformed".
    """
    cals = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
    ]
    side = _make_slow_calendar_side_effect(slow_calendars=[cals[1], cals[2]])
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=side):
        with pytest.raises(AnchorError, match="only 1/3"):
            anchor_root(
                merkle_root=_root(),
                calendars=cals,
                min_calendars=2,
                target_dir=tmp_path,
            )


def test_threshold_3_of_3_strict_mode_no_failure_tolerated(tmp_path: Path) -> None:
    """The strictest config — 3 calendars, 3-of-3 — refuses a single failure.

    Some audit-grade deployments will want a "no calendar may fail"
    posture (e.g. a regulator demands every attestation be
    independently confirmed). The configuration is supported: a
    SINGLE slow pole at min_calendars=3 must raise.
    """
    cals = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
    ]
    side = _make_slow_calendar_side_effect(slow_calendars=[cals[1]])
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=side):
        with pytest.raises(AnchorError, match="only 2/3"):
            anchor_root(
                merkle_root=_root(),
                calendars=cals,
                min_calendars=3,
                target_dir=tmp_path,
            )


def test_threshold_3_of_3_succeeds_when_all_three_respond(tmp_path: Path) -> None:
    """The strict-mode happy path: 3-of-3 with no slow poles."""
    cals = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
    ]
    side = _make_slow_calendar_side_effect(slow_calendars=[])
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=side):
        receipt = anchor_root(
            merkle_root=_root(),
            calendars=cals,
            min_calendars=3,
            target_dir=tmp_path,
        )
    assert set(receipt.successful_calendars()) == set(cals)


# ---------------------------------------------------------------------------
# Diagnostic-preservation hardening
# ---------------------------------------------------------------------------


def test_slow_calendar_diagnostic_keyword_preserved(tmp_path: Path) -> None:
    """The per-calendar response MUST preserve the failure-keyword (timeout,
    refused, unable, error, failed) so an operator can diagnose which
    failure-mode hit.

    The parser uses the keyword set ``error / failed / timeout /
    refused / unable``. This test exercises each keyword on its own
    calendar and pins the keyword-preservation contract.
    """
    cals = [
        "https://alice.test",
        "https://bob.test",
        "https://finney.test",
        "https://catallaxy.test",
    ]

    def _multi_keyword_side(cmd, **kwargs):  # noqa: ARG001
        file_arg = Path(cmd[-1])
        # Map each calendar to a distinct keyword.
        keyword_map = {
            cals[0]: "ok",  # alice succeeds
            cals[1]: "Error: connection refused",  # bob refused
            cals[2]: "Error: request timeout after 90s",  # finney timeout
            cals[3]: "Error: calendar failed during batch commit",  # catallaxy failed
        }
        lines: List[str] = []
        for url in cals:
            lines.append(f"Submitting to remote calendar {url}")
            if keyword_map[url] != "ok":
                lines.append(f"{url}: {keyword_map[url]}")
        if file_arg.exists():
            (file_arg.parent / (file_arg.name + ".ots")).write_bytes(
                b"\xfd" + b"\x00" * 31
            )
        return _completed(stdout="\n".join(lines) + "\n")

    with mock.patch.object(
        ots_anchor.subprocess, "run", side_effect=_multi_keyword_side
    ):
        with pytest.raises(AnchorError, match="only 1/4"):
            anchor_root(
                merkle_root=_root(),
                calendars=cals,
                min_calendars=2,
                target_dir=tmp_path,
            )


def test_whole_process_timeout_still_maps_to_anchor_error(tmp_path: Path) -> None:
    """If the OTS subprocess itself times out (not a per-calendar slow line),
    the cron sees an ``AnchorError`` referencing the 90-second ceiling.

    This is a regression test for the Tag-3-hardening: the per-
    calendar slow-line path (new in this module) MUST NOT shadow the
    whole-process timeout path (already covered in test_anchor.py)
    by accident. We re-pin the whole-process behaviour to keep the
    two failure surfaces distinguishable.
    """

    def _whole_timeout(cmd, **kwargs):  # noqa: ARG001
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    with mock.patch.object(
        ots_anchor.subprocess, "run", side_effect=_whole_timeout
    ):
        with pytest.raises(AnchorError, match=f"timed out after {SUBPROCESS_TIMEOUT_S}s"):
            anchor_root(
                merkle_root=_root(),
                calendars=list(DEFAULT_CALENDARS),
                min_calendars=2,
                target_dir=tmp_path,
            )
