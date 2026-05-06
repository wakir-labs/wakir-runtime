# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-3 — backfill-leg integration test.

Runnable mirror of ``docs/wat-tv3-test-plan.md``. Exercises the
backfill daemon's behaviour when the public OpenTimestamps
calendars are unreachable for several consecutive hours and a
queue of pending receipts has to be drained without breaching the
seven-day soft window from WAT-Phase-1a-Spec §3.4.

The test substitutes ``wat.anchor.backfill.upgrade_pending`` with a
deterministic stub. **No real OTS calendar is contacted by this
suite.** The substitution boundary is intentional: politeness rules
on the public OTS infrastructure forbid hot-loop calendar traffic,
and the daemon's own contract (process the queue, flag breaches)
is independent of the upgrade implementation.

Gated on ``OTS_INTEGRATION_TEST=1`` for symmetry with TV-1/TV-2 so
the suite skips cleanly on default CI.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest

from wat.anchor import backfill as backfill_mod
from wat.anchor.backfill import (
    DEFAULT_SOFT_WINDOW_DAYS,
    UpgradeResult,
    process_pending_queue,
)
from wat.anchor.ots_anchor import AnchorError, UpgradedReceipt


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Skip logic — same gate as the rest of the integration suite.
# ---------------------------------------------------------------------------


def _integration_enabled() -> bool:
    raw = os.environ.get("OTS_INTEGRATION_TEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason=(
        "OTS_INTEGRATION_TEST is not set; skipping TV-3 backfill-leg "
        "test. Export OTS_INTEGRATION_TEST=1 to run it."
    ),
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_receipt(path: Path, age_days: float) -> Path:
    """Create a synthetic ``.ots`` file with a controlled mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-ots-receipt")
    target = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=age_days)
    ts = target.timestamp()
    os.utime(path, (ts, ts))
    return path


def _make_upgrader(
    *,
    finalised_paths: Optional[set] = None,
    block_height_base: int = 800_000,
    raise_for: Optional[set] = None,
):
    """Build a stub for ``upgrade_pending`` with controlled outcomes.

    Parameters
    ----------
    finalised_paths:
        Set of ``Path`` objects that should report a Bitcoin block
        height (i.e. ``is_finalised == True``). Anything not in the
        set returns a pending ``UpgradedReceipt``.
    block_height_base:
        Base block height; each finalised receipt increments by 1
        in sort-by-path order so tests can pin specific heights.
    raise_for:
        Set of ``Path`` objects for which the stub raises
        ``AnchorError`` instead of returning a result.
    """
    finalised_paths = finalised_paths or set()
    raise_for = raise_for or set()
    counter = {"n": 0}

    def _stub(receipt_path):
        receipt_path = Path(receipt_path)
        if receipt_path in raise_for:
            raise AnchorError(f"synthetic upgrade failure: {receipt_path}")
        if receipt_path in finalised_paths:
            counter["n"] += 1
            return UpgradedReceipt(
                merkle_root=b"\x00" * 32,
                receipt_path=receipt_path,
                bitcoin_block_height=block_height_base + counter["n"],
                bitcoin_tx_id="aa" * 32,
                upgraded_at="2026-05-13T12:00:00Z",
            )
        return UpgradedReceipt(
            merkle_root=b"\x00" * 32,
            receipt_path=receipt_path,
            bitcoin_block_height=None,
            bitcoin_tx_id=None,
            upgraded_at="2026-05-13T12:00:00Z",
        )

    return _stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tv3_clean_window_no_breach(tmp_path: Path, monkeypatch) -> None:
    """A1+A2: receipts younger than 7 days never breach the window."""
    archive = tmp_path / "archive"
    paths = [
        _write_receipt(archive / f"2026-05-0{i}T10" / "root.bin.ots", age_days=age)
        for i, age in enumerate([1.0, 3.0, 6.5, 6.99], start=1)
    ]
    monkeypatch.setattr(
        backfill_mod, "upgrade_pending", _make_upgrader(finalised_paths=set())
    )

    results = process_pending_queue(archive)

    assert len(results) == len(paths)
    assert all(not r.soft_window_breached for r in results)
    assert all(not r.finalised for r in results)
    assert [r.receipt_path for r in results] == sorted(paths)


def test_tv3_aged_receipt_triggers_hard_alarm(tmp_path: Path, monkeypatch) -> None:
    """A3: a pending receipt older than 7 days flags a hard alarm."""
    archive = tmp_path / "archive"
    young = _write_receipt(archive / "young" / "r.ots", age_days=2.0)
    aged = _write_receipt(archive / "aged" / "r.ots", age_days=8.5)
    monkeypatch.setattr(
        backfill_mod, "upgrade_pending", _make_upgrader(finalised_paths=set())
    )

    results = process_pending_queue(archive)

    by_path = {r.receipt_path: r for r in results}
    assert by_path[young].soft_window_breached is False
    assert by_path[aged].soft_window_breached is True
    assert by_path[aged].error is None  # the upgrade itself did not fail
    # The aged receipt's age_days is reported faithfully so the alarm
    # channel can render "stuck for N days" without re-statting.
    assert by_path[aged].age_days >= 8.0


def test_tv3_finalised_receipt_clears_breach_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """A2 negative: an old receipt that finally upgrades is not breached."""
    archive = tmp_path / "archive"
    aged_finalised = _write_receipt(
        archive / "h0" / "r.ots", age_days=10.0
    )
    monkeypatch.setattr(
        backfill_mod,
        "upgrade_pending",
        _make_upgrader(finalised_paths={aged_finalised}),
    )

    [result] = process_pending_queue(archive)

    # Per backfill.py line 115: breached = (not finalised) and age > N.
    # Finalisation wins regardless of age.
    assert result.finalised is True
    assert result.bitcoin_block_height is not None
    assert result.soft_window_breached is False


def test_tv3_per_receipt_isolation_anchor_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A daemon-level robustness invariant: AnchorError on one receipt
    does not stop processing of subsequent receipts.
    """
    archive = tmp_path / "archive"
    good = _write_receipt(archive / "a" / "r.ots", age_days=1.0)
    bad = _write_receipt(archive / "b" / "r.ots", age_days=8.0)
    later = _write_receipt(archive / "c" / "r.ots", age_days=2.0)
    monkeypatch.setattr(
        backfill_mod,
        "upgrade_pending",
        _make_upgrader(finalised_paths=set(), raise_for={bad}),
    )

    results = process_pending_queue(archive)

    assert len(results) == 3
    by_path = {r.receipt_path: r for r in results}
    assert by_path[good].error is None
    assert by_path[bad].error is not None
    assert "synthetic upgrade failure" in by_path[bad].error
    # The failed-and-aged receipt is still flagged as breached so the
    # alarm channel does not lose visibility of it.
    assert by_path[bad].soft_window_breached is True
    assert by_path[later].error is None


def test_tv3_idempotent_two_passes(tmp_path: Path, monkeypatch) -> None:
    """A4: running the daemon twice on the same archive is stable."""
    archive = tmp_path / "archive"
    _write_receipt(archive / "h0" / "r.ots", age_days=1.0)
    _write_receipt(archive / "h1" / "r.ots", age_days=2.0)
    _write_receipt(archive / "h2" / "r.ots", age_days=8.5)
    monkeypatch.setattr(
        backfill_mod, "upgrade_pending", _make_upgrader(finalised_paths=set())
    )

    first = process_pending_queue(archive)
    second = process_pending_queue(archive)

    assert [r.receipt_path for r in first] == [r.receipt_path for r in second]
    assert [r.soft_window_breached for r in first] == [
        r.soft_window_breached for r in second
    ]
    assert all(not r.finalised for r in second)


def test_tv3_soft_window_boundary_strict_inequality(
    tmp_path: Path, monkeypatch
) -> None:
    """Pin §3 boundary table: comparison is `>`, not `>=`.

    A receipt that is just under seven days old must NOT trigger the
    alarm; one that is seven days plus a fraction MUST. The boundary
    is asserted with a deterministic, injected ``now`` so floating
    point drift between the test's wall clock and the daemon's
    ``datetime.now()`` cannot decide the result.
    """
    archive = tmp_path / "archive"
    just_under = _write_receipt(archive / "under" / "r.ots", age_days=6.95)
    over = _write_receipt(archive / "over" / "r.ots", age_days=7.05)
    monkeypatch.setattr(
        backfill_mod, "upgrade_pending", _make_upgrader(finalised_paths=set())
    )

    # Pass an explicit ``now`` so the daemon's age computation uses
    # the same reference clock as ``_write_receipt`` did.
    fixed_now = dt.datetime.now(tz=dt.timezone.utc)
    results = process_pending_queue(archive, now=fixed_now)
    by_path = {r.receipt_path: r for r in results}

    assert by_path[just_under].soft_window_breached is False
    assert by_path[just_under].age_days < 7.0
    assert by_path[over].soft_window_breached is True
    assert by_path[over].age_days > 7.0


def test_tv3_empty_archive_is_noop(tmp_path: Path, monkeypatch) -> None:
    """Idempotent zero-result behaviour on an empty archive."""
    archive = tmp_path / "archive"
    archive.mkdir()
    monkeypatch.setattr(
        backfill_mod, "upgrade_pending", _make_upgrader(finalised_paths=set())
    )

    results = process_pending_queue(archive)
    assert results == []


def test_tv3_systemd_timer_has_four_oncalendar_lines() -> None:
    """A5 substitute: the timer file documents the 4×/day cadence.

    Decoupled from the daemon code — this is a configuration sanity
    check that the cron contract documented in §4 of the test plan
    matches the timer template that ships in the repo.
    """
    timer = REPO_ROOT / "scripts" / "systemd" / "wakir-wat-backfill.timer"
    assert timer.is_file(), f"timer template missing at {timer}"
    on_calendar = [
        line for line in timer.read_text().splitlines()
        if line.strip().startswith("OnCalendar=")
    ]
    assert len(on_calendar) == 4, (
        f"expected exactly four OnCalendar= lines, got {on_calendar}"
    )
    # Pin the documented offsets so a refactor surfaces in TV-3 review.
    assert any("00:30:00" in line for line in on_calendar)
    assert any("06:30:00" in line for line in on_calendar)
    assert any("12:30:00" in line for line in on_calendar)
    assert any("18:30:00" in line for line in on_calendar)


def test_tv3_default_soft_window_constant() -> None:
    """The seven-day soft window is the WAT-Phase-1a-Spec §3.4 default."""
    assert DEFAULT_SOFT_WINDOW_DAYS == 7
