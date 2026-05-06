# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Unit tests for the WAT OTS anchor pipeline.

The implementation under test is BSL-1.1; the tests themselves are
Apache-2.0 so downstream re-implementers can re-use the same vectors.

Subprocess strategy
-------------------

These tests do not contact real OTS calendar servers. Every
``subprocess.run`` call is patched at module import boundary
(``wat.anchor.ots_anchor.subprocess.run``) to return canned
``CompletedProcess`` instances with realistic OTS CLI output.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
from pathlib import Path
from typing import List, Sequence
from unittest import mock

import pytest

from wat.anchor import backfill, ots_anchor
from wat.anchor.backfill import (
    DEFAULT_SOFT_WINDOW_DAYS,
    UpgradeResult,
    process_pending_queue,
)
from wat.anchor.ots_anchor import (
    AnchorError,
    AnchorReceipt,
    DEFAULT_CALENDARS,
    SUBPROCESS_TIMEOUT_S,
    UpgradedReceipt,
    anchor_root,
    upgrade_pending,
    verify_receipt,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_ots_resolvable() -> None:
    """Make ``shutil.which('ots')`` succeed without depending on PATH state."""
    with mock.patch.object(
        ots_anchor.shutil,
        "which",
        return_value="/usr/bin/ots",
    ):
        yield


def _root() -> bytes:
    return hashlib.sha256(b"test-merkle-root").digest()


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


def _make_stamp_side_effect(
    fail_calendars: Sequence[str] = (),
    write_receipt: bool = True,
):
    """Return a side_effect that emulates ``ots stamp``.

    On each call: writes ``root.bin.ots`` next to the input file
    (mirroring real OTS behaviour) and produces stdout that names
    the calendars and includes "Error" lines for the failing ones.
    """

    def _side_effect(cmd, **kwargs):  # noqa: ARG001 — kwargs unused
        # Find the file path argument (last positional).
        file_arg = Path(cmd[-1])
        # Find calendar URLs that were passed.
        calendars: List[str] = []
        for i, token in enumerate(cmd):
            if token == "--calendar" and i + 1 < len(cmd):
                calendars.append(cmd[i + 1])
        lines: List[str] = []
        for url in calendars:
            lines.append(f"Submitting to remote calendar {url}")
            if url in fail_calendars:
                lines.append(f"Error: calendar {url} returned 502 Bad Gateway")
        stdout = "\n".join(lines) + "\n"
        if write_receipt and file_arg.exists():
            (file_arg.parent / (file_arg.name + ".ots")).write_bytes(b"\xfd" + b"\x00" * 31)
        return _completed(stdout=stdout)

    return _side_effect


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------


def test_anchor_receipt_dataclass(tmp_path: Path) -> None:
    """AnchorReceipt is frozen, exposes the four documented fields, and
    its ``successful_calendars`` helper filters on ``"ok"``."""
    root = _root()
    receipt = AnchorReceipt(
        merkle_root=root,
        submission_time="2026-05-06T12:00:00Z",
        calendar_responses={
            "https://alice.example": "ok",
            "https://bob.example": "Error: 502",
            "https://finney.example": "ok",
        },
        receipt_path=tmp_path / "root.bin.ots",
    )
    assert receipt.merkle_root == root
    assert receipt.submission_time.endswith("Z")
    assert receipt.successful_calendars() == [
        "https://alice.example",
        "https://finney.example",
    ]
    # Frozen dataclass: assignment must raise.
    with pytest.raises(dataclasses_FrozenInstanceError := __import__(
        "dataclasses"
    ).FrozenInstanceError):
        receipt.merkle_root = b"\x00" * 32  # type: ignore[misc]


def test_min_calendars_threshold(tmp_path: Path) -> None:
    """anchor_root rejects a successful submission count below the threshold."""
    cals = [
        "https://alice.example",
        "https://bob.example",
        "https://finney.example",
        "https://catallaxy.example",
    ]
    side = _make_stamp_side_effect(
        # Only one calendar succeeds — below the 2-of-N threshold.
        fail_calendars=cals[1:],
        write_receipt=True,
    )
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=side):
        with pytest.raises(AnchorError, match="only 1/4"):
            anchor_root(
                merkle_root=_root(),
                calendars=cals,
                min_calendars=2,
                target_dir=tmp_path,
            )

    # Sanity: invalid threshold values raise ValueError early.
    with pytest.raises(ValueError):
        anchor_root(_root(), calendars=cals, min_calendars=0, target_dir=tmp_path)
    with pytest.raises(ValueError):
        anchor_root(_root(), calendars=cals, min_calendars=99, target_dir=tmp_path)


def test_subprocess_timeout_handling(tmp_path: Path) -> None:
    """A ``TimeoutExpired`` from the OTS subprocess maps to AnchorError
    and the timeout argument was set to 90s."""
    captured_timeouts: List[int] = []

    def _raise_timeout(cmd, **kwargs):  # noqa: ARG001
        captured_timeouts.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 0))

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_raise_timeout):
        with pytest.raises(AnchorError, match=f"timed out after {SUBPROCESS_TIMEOUT_S}s"):
            anchor_root(
                merkle_root=_root(),
                calendars=list(DEFAULT_CALENDARS),
                min_calendars=2,
                target_dir=tmp_path,
            )

    assert captured_timeouts, "subprocess.run must have been called"
    assert captured_timeouts[0] == SUBPROCESS_TIMEOUT_S == 90


def test_calendar_failover_with_2_of_4(tmp_path: Path) -> None:
    """With four calendars and a 2-of-4 policy, a submission that loses
    two calendars still succeeds and records the failures."""
    cals = [
        "https://alice.example",
        "https://bob.example",
        "https://finney.example",
        "https://catallaxy.example",
    ]
    # Half down, half up.
    side = _make_stamp_side_effect(
        fail_calendars=[cals[0], cals[2]],
        write_receipt=True,
    )
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
    assert set(successes) == {cals[1], cals[3]}
    assert receipt.receipt_path.exists()
    # Failed calendars are recorded with their error string, not "ok".
    assert receipt.calendar_responses[cals[0]] != "ok"
    assert receipt.calendar_responses[cals[2]] != "ok"


def test_upgrade_pending_to_finalised(tmp_path: Path) -> None:
    """upgrade_pending parses the bitcoin block height out of ots info
    output and reports the receipt as finalised."""
    receipt_path = tmp_path / "root.bin.ots"
    receipt_path.write_bytes(b"\xfd" + b"\x00" * 31)
    root_path = tmp_path / "root.bin"
    root_path.write_bytes(_root())

    info_stdout = (
        "File sha256 hash: " + _root().hex() + "\n"
        "Timestamp:\n"
        "Bitcoin block 837421 attests existence as of 2026-05-06 11:42:00 UTC\n"
    )

    def _side(cmd, **kwargs):  # noqa: ARG001
        if cmd[1] == "upgrade":
            return _completed(stdout="Success! Timestamp complete\n")
        if cmd[1] == "info":
            return _completed(stdout=info_stdout)
        return _completed()

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_side):
        upgraded = upgrade_pending(receipt_path)

    assert isinstance(upgraded, UpgradedReceipt)
    assert upgraded.is_finalised is True
    assert upgraded.bitcoin_block_height == 837421
    assert upgraded.merkle_root == _root()
    assert upgraded.receipt_path == receipt_path
    assert upgraded.upgraded_at.endswith("Z")


def test_verify_receipt_valid(tmp_path: Path) -> None:
    """verify_receipt returns True on a Bitcoin-confirmed receipt."""
    receipt_path = tmp_path / "root.bin.ots"
    receipt_path.write_bytes(b"\xfd" + b"\x00" * 31)
    root = _root()

    def _side(cmd, **kwargs):  # noqa: ARG001
        return _completed(
            stdout=(
                "Calendar https://alice.example: Success!\n"
                "Bitcoin block 837421 attests existence as of 2026-05-06 11:42 UTC\n"
                "Success!\n"
            )
        )

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_side):
        assert verify_receipt(receipt_path, root) is True


def test_verify_receipt_invalid_root_rejected(tmp_path: Path) -> None:
    """verify_receipt returns False when ots verify exits non-zero (i.e.
    the supplied root does not hash to the receipt's tip)."""
    receipt_path = tmp_path / "root.bin.ots"
    receipt_path.write_bytes(b"\xfd" + b"\x00" * 31)
    bogus_root = hashlib.sha256(b"not-the-real-root").digest()

    def _side(cmd, **kwargs):  # noqa: ARG001
        return _completed(
            returncode=1,
            stderr="Failed: hash mismatch\n",
        )

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_side):
        assert verify_receipt(receipt_path, bogus_root) is False

    # Sanity: a still-pending receipt also returns False even on rc=0.
    def _pending(cmd, **kwargs):  # noqa: ARG001
        return _completed(stdout="Pending confirmation in Bitcoin blockchain\n")

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_pending):
        assert verify_receipt(receipt_path, _root()) is False


def test_backfill_queue_age_filter(tmp_path: Path) -> None:
    """process_pending_queue flags pending receipts older than the
    soft window without dropping the recent ones."""
    fresh = tmp_path / "fresh" / "root.bin.ots"
    fresh.parent.mkdir(parents=True)
    fresh.write_bytes(b"\xfd" + b"\x00" * 31)

    stale = tmp_path / "stale" / "root.bin.ots"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"\xfd" + b"\x00" * 31)
    # Backdate the stale file to ten days ago.
    ten_days_ago = (dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=10)).timestamp()
    os.utime(stale, (ten_days_ago, ten_days_ago))

    def _side(cmd, **kwargs):  # noqa: ARG001
        if cmd[1] == "upgrade":
            return _completed(stdout="Calendar response received; still pending\n")
        if cmd[1] == "info":
            # No "Bitcoin block" line -> still pending.
            return _completed(stdout="Pending confirmation in Bitcoin blockchain\n")
        return _completed()

    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=_side):
        results = process_pending_queue(tmp_path, max_age_days=DEFAULT_SOFT_WINDOW_DAYS)

    assert len(results) == 2
    by_path = {r.receipt_path: r for r in results}
    assert not by_path[fresh].soft_window_breached
    assert by_path[stale].soft_window_breached
    assert by_path[stale].finalised is False
    assert by_path[stale].age_days >= 10.0


# ---------------------------------------------------------------------------
# Extra self-motivated tests
# ---------------------------------------------------------------------------


def test_anchor_root_rejects_wrong_root_length(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        anchor_root(b"too-short", target_dir=tmp_path)


def test_verify_receipt_rejects_wrong_root_length(tmp_path: Path) -> None:
    receipt = tmp_path / "root.bin.ots"
    receipt.write_bytes(b"\xfd" + b"\x00" * 31)
    with pytest.raises(ValueError):
        verify_receipt(receipt, b"\x00" * 16)


def test_upgrade_pending_missing_receipt_raises(tmp_path: Path) -> None:
    with pytest.raises(AnchorError):
        upgrade_pending(tmp_path / "does-not-exist.ots")


def test_backfill_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert process_pending_queue(tmp_path / "nope") == []
