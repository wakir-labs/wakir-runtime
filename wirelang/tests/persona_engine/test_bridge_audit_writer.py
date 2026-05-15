# SPDX-License-Identifier: BUSL-1.1
"""Tests for bridge-audit-writer double-sink emission."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
    ENGINEERING_OUTPUT_SCHEMA,
    sha256_hex,
)


def _writer(tmp_path: Path, sink: io.StringIO) -> BridgeAuditWriter:
    return BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-abc",
        engine_version="0.2.0-pilot",
        v907_pin="sha256:" + "a" * 64,
        preframework_sink_path=tmp_path / "tomas" / "bridge-audit.md",
        wakir_runtime_sink=sink,
    )


def test_emit_returns_event_with_correct_fields(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    evt = w.emit("tool_call", b"payload-bytes")
    assert isinstance(evt, EngineeringOutputEvent)
    assert evt.org_id == "acme"
    assert evt.persona_id == "tomas"
    assert evt.session_id == "sess-abc"
    assert evt.step_index == 0
    assert evt.output_kind == "tool_call"
    assert evt.output_payload_sha256 == sha256_hex(b"payload-bytes")


def test_emit_increments_step_counter(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    e0 = w.emit("tool_call", b"a")
    e1 = w.emit("tool_call", b"b")
    e2 = w.emit("tool_call", b"c")
    assert (e0.step_index, e1.step_index, e2.step_index) == (0, 1, 2)


def test_emit_writes_jcs_bytes_to_wakir_runtime_sink(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    evt = w.emit("reply", b"hello")
    line = sink.getvalue().strip()
    obj = json.loads(line)
    assert obj["event_kind"] == "engineering_output"
    assert obj["schema"] == ENGINEERING_OUTPUT_SCHEMA
    assert obj["output_kind"] == "reply"
    assert obj["output_payload_sha256"] == evt.output_payload_sha256


def test_emit_writes_preframework_sink_markdown(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    w.emit("tool_call", b"x")
    md_path = tmp_path / "tomas" / "bridge-audit.md"
    assert md_path.is_file()
    content = md_path.read_text(encoding="utf-8")
    assert "## step 0 — tool_call" in content
    assert "```json" in content


def test_unknown_output_kind_rejected(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    with pytest.raises(ValueError):
        w.emit("garbage_kind", b"x")


def test_payload_hash_is_sha256_prefixed():
    h = sha256_hex(b"abc")
    assert h.startswith("sha256:")
    assert len(h) == 7 + 64


def test_jcs_bytes_alphabetical_keys(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink)
    evt = w.emit("audit_annotation", b"")
    text = evt.to_jcs_bytes().decode("utf-8")
    # alphabetical-order keys: engine_version < event_kind < org_id < ...
    expected_keys = [
        "engine_version",
        "event_kind",
        "org_id",
        "output_kind",
        "output_payload_sha256",
        "persona_id",
        "schema",
        "session_id",
        "step_index",
        "ts_utc",
        "v907_pin",
    ]
    positions = [text.index(f'"{k}"') for k in expected_keys]
    assert positions == sorted(positions)


def test_preframework_sink_missing_parent_skipped_gracefully(tmp_path):
    sink = io.StringIO()
    # Construct a sink path under a non-writable mount point (use a
    # file as parent — mkdir will fail). We instead point at a path
    # under tmp_path/no-perms with a file blocking the dir.
    blocker = tmp_path / "blocker"
    blocker.write_text("file-not-dir")
    bad_sink_path = blocker / "subdir" / "bridge.md"
    w = BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-abc",
        engine_version="0.2.0-pilot",
        v907_pin="sha256:" + "a" * 64,
        preframework_sink_path=bad_sink_path,
        wakir_runtime_sink=sink,
    )
    # Should not raise — Pre-Framework sink is best-effort.
    evt = w.emit("tool_call", b"y")
    # Wakir-Runtime sink still received the event.
    assert sink.getvalue().strip() != ""
    assert evt.output_kind == "tool_call"
