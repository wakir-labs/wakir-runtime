# SPDX-License-Identifier: BUSL-1.1
"""Unit tests for the Doppel-Audit-Trail bridge writer.

Covers the public API of ``wat.anchor.bridge_audit_writer``:

- ``write_bridge_audit`` happy-path returns ``ok`` and writes both sinks.
- Failure-Injection: ``_fail_wat=True`` returns ``wat-failed`` and
  does not touch the activity-log.
- Failure-Injection: ``_fail_pre_framework=True`` returns
  ``pre-framework-failed`` and rolls back the WAT-side spool.
- Activity-log line format matches the canonical
  ``YYYY-MM-DD · Akteur · Aktion · Bezug`` shape.
- Deterministic ``event_id`` derivation.
- ``count_wat_markers`` and ``count_activity_log_lines_for_persona``
  helpers report consistent values after writes.

Consistency over a 1000+-event 24h mock-trace lives in the sibling
file ``test_bridge_audit_writer_consistency.py``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from wat.anchor.bridge_audit_writer import (
    BridgeWriteResult,
    STATUS_OK,
    STATUS_PRE_FRAMEWORK_FAILED,
    STATUS_WAT_FAILED,
    count_activity_log_lines_for_persona,
    count_wat_markers,
    write_bridge_audit,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bridge_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Return (spool_root, activity_log_path) under tmp_path."""
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("# Activity Log — test fixture\n\n", encoding="utf-8")
    return spool_root, activity_log


def _payload_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_write_bridge_audit_happy_path_returns_ok(bridge_paths):
    spool_root, activity_log = bridge_paths
    result = write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("pr#42"),
        metadata={"ref": "PR#42 wakir-runtime"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T08:30:00Z",
    )
    assert isinstance(result, BridgeWriteResult)
    assert result.status == STATUS_OK
    assert result.ok is True
    assert result.wat_spool_path is not None
    assert result.wat_spool_path.exists()
    assert result.error == ""


def test_write_bridge_audit_writes_both_sinks(bridge_paths):
    spool_root, activity_log = bridge_paths
    write_bridge_audit(
        persona_id="reza",
        action_type="adr-vote",
        payload_hash=_payload_hash("vote-adr-0056"),
        metadata={"ref": "ADR-0056"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T09:00:00Z",
    )
    # WAT side: exactly one leaf line in the hour-spool.
    wat_count = count_wat_markers(spool_root, "reza")
    assert wat_count == 1
    # Pre-Framework side: exactly one canonical line for reza.
    pre_count = count_activity_log_lines_for_persona(activity_log, "reza")
    assert pre_count == 1


def test_activity_log_line_format_is_canonical(bridge_paths):
    spool_root, activity_log = bridge_paths
    write_bridge_audit(
        persona_id="mira",
        action_type="hourly-tick",
        payload_hash=_payload_hash("tick-2026-05-13"),
        metadata={"ref": "hourly-08:00-CEST"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T06:00:00Z",
    )
    text = activity_log.read_text(encoding="utf-8")
    # Canonical line: YYYY-MM-DD · Akteur · Aktion · Bezug
    assert "\n2026-05-13 · mira · hourly-tick · " in text
    # Bezug carries the operator-ref + short payload prefix.
    assert "hourly-08:00-CEST · payload=" in text


def test_event_id_is_deterministic(bridge_paths, tmp_path):
    """Same inputs MUST produce the same event_id across re-invocations.

    The bridge derives ``event_id`` from ``SHA-256(persona|time|action|hash)``
    truncated to 32 hex chars. Re-running the same call produces the
    same identifier, which makes idempotent retry safe at the audit
    layer.
    """
    spool_root_a = tmp_path / "spool-a"
    spool_root_b = tmp_path / "spool-b"
    log_a = tmp_path / "log-a.md"
    log_b = tmp_path / "log-b.md"
    log_a.write_text("# A\n", encoding="utf-8")
    log_b.write_text("# B\n", encoding="utf-8")

    common_args = dict(
        persona_id="tomas",
        action_type="git-commit",
        payload_hash=_payload_hash("abc123"),
        metadata={},
        event_time="2026-05-13T10:00:00Z",
    )
    write_bridge_audit(
        spool_root=spool_root_a, activity_log_path=log_a, **common_args
    )
    write_bridge_audit(
        spool_root=spool_root_b, activity_log_path=log_b, **common_args
    )
    leaf_a = (spool_root_a / "tomas" / "2026-05-13T10.jsonl").read_text()
    leaf_b = (spool_root_b / "tomas" / "2026-05-13T10.jsonl").read_text()
    assert leaf_a == leaf_b


# ---------------------------------------------------------------------------
# Failure injection: WAT side
# ---------------------------------------------------------------------------


def test_wat_failure_returns_wat_failed_status(bridge_paths):
    spool_root, activity_log = bridge_paths
    result = write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("payload-x"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T11:00:00Z",
        _fail_wat=True,
    )
    assert result.status == STATUS_WAT_FAILED
    assert result.ok is False
    assert "wat-append-failed" in result.error


def test_wat_failure_does_not_touch_activity_log(bridge_paths):
    spool_root, activity_log = bridge_paths
    baseline = activity_log.read_text(encoding="utf-8")
    write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("payload-y"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T11:30:00Z",
        _fail_wat=True,
    )
    after = activity_log.read_text(encoding="utf-8")
    assert after == baseline
    # WAT side has nothing either.
    assert count_wat_markers(spool_root, "tomas") == 0


# ---------------------------------------------------------------------------
# Failure injection: Pre-Framework side
# ---------------------------------------------------------------------------


def test_pre_framework_failure_rolls_back_wat_side(bridge_paths):
    spool_root, activity_log = bridge_paths
    # Seed a prior successful write so the spool file already exists
    # with a known byte offset. The failed second call must truncate
    # back to exactly that offset.
    seed = write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("seed"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T12:00:00Z",
    )
    assert seed.ok
    spool_path = seed.wat_spool_path
    assert spool_path is not None
    pinned_size = spool_path.stat().st_size

    failing = write_bridge_audit(
        persona_id="tomas",
        action_type="pr-merge",
        payload_hash=_payload_hash("doomed"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T12:30:00Z",
        _fail_pre_framework=True,
    )
    assert failing.status == STATUS_PRE_FRAMEWORK_FAILED
    assert failing.ok is False
    assert "pre-framework-append-failed" in failing.error

    # Spool MUST be byte-restored to the pre-call offset.
    assert spool_path.stat().st_size == pinned_size
    # Both sinks now agree on the single seed line.
    assert count_wat_markers(spool_root, "tomas") == 1
    assert count_activity_log_lines_for_persona(activity_log, "tomas") == 1


def test_pre_framework_failure_first_call_leaves_empty_spool(bridge_paths):
    """If the very first call fails on the Pre-Framework side, the
    spool file MUST be truncated back to zero bytes (or removed),
    matching its pre-call 'did not exist' state."""
    spool_root, activity_log = bridge_paths
    result = write_bridge_audit(
        persona_id="kai",
        action_type="pr-open",
        payload_hash=_payload_hash("kai-first"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T13:00:00Z",
        _fail_pre_framework=True,
    )
    assert result.status == STATUS_PRE_FRAMEWORK_FAILED
    # The spool file may exist as zero-byte after truncate, or not exist
    # if the rollback could not find it — either way, the WAT count is 0.
    assert count_wat_markers(spool_root, "kai") == 0
    assert count_activity_log_lines_for_persona(activity_log, "kai") == 0


# ---------------------------------------------------------------------------
# Helper coverage
# ---------------------------------------------------------------------------


def test_count_helpers_ignore_other_personas(bridge_paths):
    spool_root, activity_log = bridge_paths
    write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("t1"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T14:00:00Z",
    )
    write_bridge_audit(
        persona_id="reza",
        action_type="adr-vote",
        payload_hash=_payload_hash("r1"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T14:01:00Z",
    )
    assert count_wat_markers(spool_root, "tomas") == 1
    assert count_wat_markers(spool_root, "reza") == 1
    assert count_activity_log_lines_for_persona(activity_log, "tomas") == 1
    assert count_activity_log_lines_for_persona(activity_log, "reza") == 1


def test_count_activity_log_skips_free_form_headers(bridge_paths):
    """The activity-log contains Mira-Hourly prose with persona names
    embedded — the line counter MUST ignore anything that doesn't
    match the strict canonical prefix.
    """
    spool_root, activity_log = bridge_paths
    # Seed the file with prose that mentions ``tomas`` in non-canonical
    # positions. The counter should still report 1 after a single
    # bridge write.
    activity_log.write_text(
        "# Activity Log\n\n"
        "## 2026-05-13 08:00 CEST — Hourly check OK\n\n"
        "Some free-form prose mentioning tomas in the middle.\n"
        "Another line · tomas · not-a-bridge-entry · without-date-prefix\n",
        encoding="utf-8",
    )
    write_bridge_audit(
        persona_id="tomas",
        action_type="pr-open",
        payload_hash=_payload_hash("only-real"),
        metadata={},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time="2026-05-13T15:00:00Z",
    )
    assert count_activity_log_lines_for_persona(activity_log, "tomas") == 1
