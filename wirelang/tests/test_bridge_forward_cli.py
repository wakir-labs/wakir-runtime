# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-Bridge-Forward-CLI-MINI subscribe-loop
snapshot CLI (Amara PR #116 §5 substance-bestaetigung).

The CLI is in ``wirelang/bridge/cli.py``. The hermetic test surface uses
the ``--snapshot-file`` and ``--snapshot-stdin`` paths plus the in-
process ``snapshot_loader`` keyword on :func:`main`. NATS-mock-fixtures
in this module emit deterministic snapshot dicts that mirror what a
JetStream ``stream_info``/``consumer_info`` probe would produce; no
``nats-py`` import, no network, no clock skew.

Spec-Anker
----------
- ``wirelang/specs/bridge-forward-pipe-v1.md`` (Sprint-10 Tag-6)
- Amara PR #116 §5 — five-key snapshot contract
- ADR-0058 — Wakir-Runtime + Wirelang protocol-layer
- Selin Sprint-Pengine-13 Bug-42 — subscribe-loop inventory trigger
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from wirelang.bridge.cli import (
    REQUIRED_SUMMARY_KEYS,
    SUBSCRIBE_LOOP_SUMMARY_SCHEMA,
    SummaryFormatError,
    format_summary_json,
    format_summary_line,
    load_snapshot_from_file,
    main,
    validate_summary,
)


# ---------------------------------------------------------------------
# NATS-mock fixtures (hermetic; emit dicts shaped like what a real
# JetStream stream_info + consumer_info probe would produce). These are
# pure-Python; no ``nats-py`` import, no network, no clock skew.
# ---------------------------------------------------------------------


def _mock_nats_quiet_snapshot() -> dict:
    """A subscribe-loop bound to a subject pattern that has never
    received a message. ``last_message_at`` is None and the lag /
    processed counts reflect a quiet stream."""
    return {
        "subject_pattern": "wakir.dev.agent.agent.task.assigned.*",
        "current_lag_seconds": None,
        "messages_processed_total": 0,
        "active_consumers": 1,
        "last_message_at": None,
    }


def _mock_nats_busy_snapshot() -> dict:
    """A subscribe-loop with a non-trivial backlog and one inbound seen
    a few seconds ago. Mirrors the Operator-Hand-Live-VM expected shape
    on a warm cluster."""
    return {
        "subject_pattern": "wakir.staging.agent.agent.task.assigned.tomas",
        "current_lag_seconds": 12.34,
        "messages_processed_total": 42,
        "active_consumers": 2,
        "last_message_at": "2026-05-16T18:22:11Z",
    }


def _mock_nats_high_lag_snapshot() -> dict:
    """A subscribe-loop that has fallen behind. The SLI alert path
    consumes this shape; the CLI must surface the lag faithfully."""
    return {
        "subject_pattern": "wakir.prod.agent.agent.task.assigned.reza",
        "current_lag_seconds": 3600.0,
        "messages_processed_total": 9001,
        "active_consumers": 1,
        "last_message_at": "2026-05-16T17:00:00Z",
    }


@pytest.fixture
def quiet_snapshot() -> dict:
    return _mock_nats_quiet_snapshot()


@pytest.fixture
def busy_snapshot() -> dict:
    return _mock_nats_busy_snapshot()


@pytest.fixture
def high_lag_snapshot() -> dict:
    return _mock_nats_high_lag_snapshot()


# ---------------------------------------------------------------------
# Test 1 — validate_summary accepts the three canonical mock shapes.
# ---------------------------------------------------------------------


def test_validate_summary_accepts_quiet_busy_high_lag(
    quiet_snapshot, busy_snapshot, high_lag_snapshot
):
    """The three NATS-mock-fixtures MUST validate. They represent the
    full envelope of subscribe-loop telemetry shapes (quiet / busy /
    high-lag) the Operator-Hand-Live-VM probe is expected to emit."""
    for snap in (quiet_snapshot, busy_snapshot, high_lag_snapshot):
        out = validate_summary(snap)
        # Round-trip: validated dict is byte-equal to the canonical
        # ordering of the input.
        assert list(out.keys()) == list(REQUIRED_SUMMARY_KEYS)
        for key in REQUIRED_SUMMARY_KEYS:
            assert out[key] == snap[key]


# ---------------------------------------------------------------------
# Test 2 — validate_summary rejects shape errors. One assertion per
# contract clause; iterate inputs.
# ---------------------------------------------------------------------


def test_validate_summary_rejects_shape_errors(quiet_snapshot):
    """Every contract-clause in :func:`validate_summary` must reject a
    minimally-mutated quiet snapshot."""

    def mutate(snap, **changes):
        new = dict(snap)
        for k, v in changes.items():
            if v is _DELETE:
                del new[k]
            else:
                new[k] = v
        return new

    # Missing key.
    with pytest.raises(SummaryFormatError, match="missing required keys"):
        validate_summary(mutate(quiet_snapshot, subject_pattern=_DELETE))

    # Extra key.
    with pytest.raises(SummaryFormatError, match="unexpected keys"):
        validate_summary(mutate(quiet_snapshot, extra_field="oops"))

    # Empty subject_pattern.
    with pytest.raises(SummaryFormatError, match="non-empty string"):
        validate_summary(mutate(quiet_snapshot, subject_pattern=""))

    # Wrong subject-pattern prefix.
    with pytest.raises(SummaryFormatError, match="must begin with 'wakir.'"):
        validate_summary(mutate(quiet_snapshot, subject_pattern="other.dev.x"))

    # Non-mapping input.
    with pytest.raises(SummaryFormatError, match="must be a mapping"):
        validate_summary(["not", "a", "dict"])  # type: ignore[arg-type]


_DELETE = object()


# ---------------------------------------------------------------------
# Test 3 — validate_summary rejects numeric-range violations.
# ---------------------------------------------------------------------


def test_validate_summary_rejects_numeric_range_violations(busy_snapshot):
    """``current_lag_seconds`` must be >= 0 when not null;
    ``messages_processed_total`` and ``active_consumers`` must be
    non-negative ints. Booleans are rejected (Python ``bool`` is a
    subclass of ``int`` — silent acceptance would be a footgun)."""
    # Negative lag.
    snap = dict(busy_snapshot)
    snap["current_lag_seconds"] = -1.0
    with pytest.raises(SummaryFormatError, match=">= 0"):
        validate_summary(snap)

    # Negative processed count.
    snap = dict(busy_snapshot)
    snap["messages_processed_total"] = -5
    with pytest.raises(SummaryFormatError, match="non-negative int"):
        validate_summary(snap)

    # Negative consumer count.
    snap = dict(busy_snapshot)
    snap["active_consumers"] = -1
    with pytest.raises(SummaryFormatError, match="non-negative int"):
        validate_summary(snap)

    # Boolean masquerading as int — the contract is "int", not "bool".
    snap = dict(busy_snapshot)
    snap["messages_processed_total"] = True
    with pytest.raises(SummaryFormatError, match="non-negative int"):
        validate_summary(snap)


# ---------------------------------------------------------------------
# Test 4 — validate_summary enforces cross-field invariants.
# ---------------------------------------------------------------------


def test_validate_summary_enforces_cross_field_invariants(quiet_snapshot):
    """Two cross-field invariants:
    1. If ``last_message_at`` is null, ``current_lag_seconds`` MUST be
       null too (lag is defined against last-message).
    2. If ``messages_processed_total > 0``, ``last_message_at`` MUST be
       set (we processed at least one message — there is a last one)."""
    # Invariant 1.
    snap = dict(quiet_snapshot)
    snap["current_lag_seconds"] = 1.5  # but last_message_at is None
    with pytest.raises(
        SummaryFormatError, match="must be null when last_message_at is null"
    ):
        validate_summary(snap)

    # Invariant 2.
    snap = dict(quiet_snapshot)
    snap["messages_processed_total"] = 7  # but last_message_at is None
    with pytest.raises(
        SummaryFormatError,
        match="last_message_at must be set when messages_processed_total > 0",
    ):
        validate_summary(snap)


# ---------------------------------------------------------------------
# Test 5 — RFC3339 parse-paths.
# ---------------------------------------------------------------------


def test_validate_summary_accepts_z_suffix_rfc3339(busy_snapshot):
    """The persona-engine emits ``%Y-%m-%dT%H:%M:%SZ``. Our validator
    must accept Z-suffix RFC3339, NOT just ``+00:00`` offset form."""
    # Z-suffix (persona-engine native form).
    snap = dict(busy_snapshot, last_message_at="2026-05-16T18:22:11Z")
    validate_summary(snap)
    # +00:00 form.
    snap = dict(busy_snapshot, last_message_at="2026-05-16T18:22:11+00:00")
    validate_summary(snap)
    # Garbage timestamp.
    snap = dict(busy_snapshot, last_message_at="not-a-timestamp")
    with pytest.raises(SummaryFormatError, match="RFC3339-Z parseable"):
        validate_summary(snap)


# ---------------------------------------------------------------------
# Test 6 — main(--snapshot-file --json) end-to-end via tmp_path.
# ---------------------------------------------------------------------


def test_main_snapshot_file_json_output(tmp_path, busy_snapshot):
    """Hermetic end-to-end: write a fixture JSON to disk, point the
    CLI at it via --snapshot-file, capture stdout, assert byte-exact
    JSON output (sorted keys, no whitespace)."""
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(json.dumps(busy_snapshot), encoding="utf-8")

    out = io.StringIO()
    rc = main(
        ["--snapshot-file", str(snap_path), "--json"],
        stdout_stream=out,
    )
    assert rc == 0
    line = out.getvalue()
    assert line.endswith("\n")
    # Parse-back and compare to fixture for semantic equivalence.
    parsed = json.loads(line)
    assert parsed == busy_snapshot
    # Byte-exact sorted-keys / minimal-sep form.
    expected = json.dumps(
        busy_snapshot, sort_keys=True, separators=(",", ":")
    )
    assert line.rstrip("\n") == expected


# ---------------------------------------------------------------------
# Test 7 — main(--snapshot-stdin --summary) end-to-end.
# ---------------------------------------------------------------------


def test_main_snapshot_stdin_summary_output(busy_snapshot):
    """--snapshot-stdin path with --summary output. Asserts the
    human-readable line shape (operator-stable contract)."""
    stdin = io.StringIO(json.dumps(busy_snapshot))
    stdout = io.StringIO()
    rc = main(
        ["--snapshot-stdin", "--summary"],
        stdin_stream=stdin,
        stdout_stream=stdout,
    )
    assert rc == 0
    line = stdout.getvalue().rstrip("\n")
    assert line == (
        "subject_pattern=wakir.staging.agent.agent.task.assigned.tomas "
        "lag=12.34s "
        "processed=42 "
        "consumers=2 "
        "last=2026-05-16T18:22:11Z"
    )


# ---------------------------------------------------------------------
# Test 8 — main(snapshot_loader=...) in-process injection covers the
# NATS-mock-fixture path. Exercises all three mock shapes.
# ---------------------------------------------------------------------


def test_main_in_process_loader_covers_all_mock_shapes(
    quiet_snapshot, busy_snapshot, high_lag_snapshot
):
    """The ``snapshot_loader`` keyword bypasses arg-dispatch and feeds
    the validator + renderer directly. This is the hermetic seam tests
    use to exercise the full NATS-mock matrix without filesystem I/O."""
    for snap in (quiet_snapshot, busy_snapshot, high_lag_snapshot):
        stdout = io.StringIO()
        rc = main(
            # --snapshot-file is a placeholder; snapshot_loader takes
            # priority. We pass it to satisfy the mutually-exclusive-
            # arg-group "required" constraint.
            ["--snapshot-file", "/dev/null", "--json"],
            snapshot_loader=lambda s=snap: s,
            stdout_stream=stdout,
        )
        assert rc == 0
        parsed = json.loads(stdout.getvalue())
        assert parsed == snap


# ---------------------------------------------------------------------
# Test 9 — main returns non-zero rc on contract violations.
# ---------------------------------------------------------------------


def test_main_returns_rc_2_on_contract_violation(tmp_path):
    """A snapshot that violates the contract must produce rc=2 (not
    rc=1, which is reserved for arg / format errors before the
    validator runs). Operator-runbook differentiates these paths."""
    bad = {
        "subject_pattern": "wakir.dev.agent.agent.task.assigned.*",
        "current_lag_seconds": -1.0,  # negative — invariant violation
        "messages_processed_total": 0,
        "active_consumers": 1,
        "last_message_at": None,
    }
    snap_path = tmp_path / "bad.json"
    snap_path.write_text(json.dumps(bad), encoding="utf-8")
    stdout = io.StringIO()
    rc = main(
        ["--snapshot-file", str(snap_path), "--json"],
        stdout_stream=stdout,
    )
    assert rc == 2
    # No output on the failure path — stderr only.
    assert stdout.getvalue() == ""


# ---------------------------------------------------------------------
# Test 10 — main returns rc=1 on snapshot-file not found.
# ---------------------------------------------------------------------


def test_main_returns_rc_1_on_missing_file(tmp_path):
    """Missing snapshot file is an operator-arg error, rc=1. Reserved
    for pre-validator failures so the runbook can differentiate this
    from rc=2 contract violations."""
    missing = tmp_path / "does-not-exist.json"
    stdout = io.StringIO()
    rc = main(
        ["--snapshot-file", str(missing), "--json"],
        stdout_stream=stdout,
    )
    assert rc == 1
    assert stdout.getvalue() == ""


# ---------------------------------------------------------------------
# Test 11 — output is byte-deterministic across repeats (hermetic).
# ---------------------------------------------------------------------


def test_output_is_byte_deterministic_across_repeats(busy_snapshot):
    """Same fixture in, same bytes out — across repeated invocations.
    This is the hermetic-substrate floor that lets PR-bundle merges be
    reproducible across operator hosts."""
    expected_json = format_summary_json(busy_snapshot)
    expected_line = format_summary_line(busy_snapshot)
    for _ in range(5):
        assert format_summary_json(busy_snapshot) == expected_json
        assert format_summary_line(busy_snapshot) == expected_line


# ---------------------------------------------------------------------
# Test 12 — load_snapshot_from_file round-trip (with a non-object
# JSON root being rejected).
# ---------------------------------------------------------------------


def test_load_snapshot_from_file_rejects_non_object_root(tmp_path):
    """JSON arrays / strings / numbers at the file root must be
    rejected by :func:`load_snapshot_from_file`. The contract is a
    JSON *object* with the five required keys; we fail fast at the
    loader so the validator sees only well-typed input."""
    array_path = tmp_path / "array.json"
    array_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SummaryFormatError, match="did not parse to a JSON object"):
        load_snapshot_from_file(str(array_path))


# ---------------------------------------------------------------------
# Test 13 — schema constant exposure (single source of truth).
# ---------------------------------------------------------------------


def test_schema_constants_are_canonical():
    """The schema-id and required-key tuple are the single source of
    truth for this CLI. We assert their exact values so downstream
    consumers (Operator-Hand-Live-VM smoke harness, Henrik audit, the
    persona-engine subscribe-loop emitter if/when it grows a Reply-To
    summary endpoint) all agree on the shape."""
    assert SUBSCRIBE_LOOP_SUMMARY_SCHEMA == "wakir.bridge.subscribe-loop-summary/1"
    assert REQUIRED_SUMMARY_KEYS == (
        "subject_pattern",
        "current_lag_seconds",
        "messages_processed_total",
        "active_consumers",
        "last_message_at",
    )
