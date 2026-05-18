#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/observability/mira-notify-emitter.py.

Coverage targets the pure-function core (make_event, validate_event,
derive_event_id, NotifyEvent.to_dict/to_jsonl_line) plus the
single-process emit_notify + CLI emit/validate paths.

Anchor: Tag-46 Mira-Notify substance; companion to Tag-45 catalog PR.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (mirrors the test_aggregator_failure_rate_tracker.py
# pattern; emitter uses dashes in its file path).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_EMITTER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "mira-notify-emitter.py"
)

_spec = importlib.util.spec_from_file_location(
    "mira_notify_emitter", str(_EMITTER_PATH)
)
assert _spec is not None and _spec.loader is not None
emitter = importlib.util.module_from_spec(_spec)
sys.modules["mira_notify_emitter"] = emitter
_spec.loader.exec_module(emitter)


# ---------------------------------------------------------------------------
# Pure-function tests.
# ---------------------------------------------------------------------------


class TestDeriveEventId:
    def test_deterministic(self):
        a = emitter.derive_event_id(
            "WakirAlert", "2026-05-18T10:00:00Z", {"welle": "3"}
        )
        b = emitter.derive_event_id(
            "WakirAlert", "2026-05-18T10:00:00Z", {"welle": "3"}
        )
        assert a == b
        assert len(a) == 16

    def test_labels_order_independent(self):
        a = emitter.derive_event_id(
            "X", "2026-05-18T10:00:00Z", {"a": "1", "b": "2"}
        )
        b = emitter.derive_event_id(
            "X", "2026-05-18T10:00:00Z", {"b": "2", "a": "1"}
        )
        assert a == b

    def test_different_inputs_different_ids(self):
        a = emitter.derive_event_id("X", "2026-05-18T10:00:00Z", {})
        b = emitter.derive_event_id("Y", "2026-05-18T10:00:00Z", {})
        c = emitter.derive_event_id("X", "2026-05-18T10:00:01Z", {})
        assert len({a, b, c}) == 3


class TestMakeEvent:
    def test_minimal_page_event(self):
        ev = emitter.make_event(
            alert_name="WakirPhase3FailureModeA1CrossModulDriftPerWelle",
            severity="page",
            summary="A1 drift detected on welle-3",
            runbook_url="https://wakir-labs.example/runbooks/a1",
            failure_mode_id="A1",
            fired_at_utc="2026-05-18T10:00:00Z",
            labels={"welle": "3"},
        )
        assert ev.severity == "page"
        assert ev.event_id  # populated
        assert ev.schema_version == "1"
        assert ev.failure_mode_id == "A1"

    def test_page_without_runbook_raises(self):
        with pytest.raises(ValueError, match="runbook_url is required"):
            emitter.make_event(
                alert_name="X",
                severity="page",
                summary="boom",
                fired_at_utc="2026-05-18T10:00:00Z",
            )

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="severity must be one of"):
            emitter.make_event(
                alert_name="X",
                severity="critical",  # not in our vocabulary
                summary="boom",
                runbook_url="https://example/r",
                fired_at_utc="2026-05-18T10:00:00Z",
            )

    def test_summary_too_long_raises(self):
        with pytest.raises(ValueError, match="summary length"):
            emitter.make_event(
                alert_name="X",
                severity="info",
                summary="x" * 1000,
                fired_at_utc="2026-05-18T10:00:00Z",
            )

    def test_non_z_timestamp_raises(self):
        with pytest.raises(ValueError, match="fired_at_utc must be ISO-8601"):
            emitter.make_event(
                alert_name="X",
                severity="info",
                summary="x",
                fired_at_utc="2026-05-18T10:00:00+00:00",
            )

    def test_fired_at_default_uses_now_utc_iso(self, monkeypatch):
        monkeypatch.setattr(
            emitter, "now_utc_iso", lambda: "2026-05-18T12:34:56Z"
        )
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="hi",
        )
        assert ev.fired_at_utc == "2026-05-18T12:34:56Z"

    def test_event_id_override(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="hi",
            event_id="custom-id",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        assert ev.event_id == "custom-id"

    def test_warning_without_runbook_ok(self):
        # Catalog says only page requires runbook.
        ev = emitter.make_event(
            alert_name="X",
            severity="warning",
            summary="something to watch",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        assert ev.runbook_url is None


class TestSerialisation:
    def test_to_jsonl_line_round_trip(self):
        ev = emitter.make_event(
            alert_name="WakirX",
            severity="info",
            summary="hello",
            fired_at_utc="2026-05-18T10:00:00Z",
            labels={"k": "v"},
            annotations={"team": "sre"},
        )
        line = ev.to_jsonl_line()
        assert line.endswith("\n")
        obj = json.loads(line)
        assert obj["alert_name"] == "WakirX"
        assert obj["labels"] == {"k": "v"}
        assert obj["annotations"] == {"team": "sre"}

    def test_to_dict_sorted_keys_via_json(self):
        ev = emitter.make_event(
            alert_name="A",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        text = ev.to_jsonl_line()
        # Sorted output begins with the alphabetically-first key.
        first_key = json.loads(text)
        keys = list(json.loads(text).keys())
        # We sort in to_jsonl_line via json.dumps(sort_keys=True).
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# I/O + CLI tests.
# ---------------------------------------------------------------------------


class TestEmitNotify:
    def test_appends_jsonl_line(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        ev = emitter.make_event(
            alert_name="A",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        emitter.emit_notify(ev, log_path=log)
        content = log.read_text("utf-8")
        assert content.count("\n") == 1
        emitter.emit_notify(ev, log_path=log)
        content = log.read_text("utf-8")
        assert content.count("\n") == 2  # append, not overwrite

    def test_creates_parent_dirs(self, tmp_path):
        log = tmp_path / "deep" / "nested" / "notify.jsonl"
        ev = emitter.make_event(
            alert_name="A",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        emitter.emit_notify(ev, log_path=log)
        assert log.exists()


class TestCliEmit:
    def test_emit_minimal(self, tmp_path, capsys):
        log = tmp_path / "notify.jsonl"
        rc = emitter.main(
            [
                "emit",
                "--alert-name",
                "WakirX",
                "--severity",
                "info",
                "--summary",
                "test",
                "--fired-at-utc",
                "2026-05-18T10:00:00Z",
                "--log-path",
                str(log),
            ]
        )
        assert rc == 0
        assert log.exists()
        obj = json.loads(log.read_text("utf-8").strip())
        assert obj["alert_name"] == "WakirX"
        assert obj["severity"] == "info"

    def test_emit_page_without_runbook_errors(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        rc = emitter.main(
            [
                "emit",
                "--alert-name",
                "X",
                "--severity",
                "page",
                "--summary",
                "boom",
                "--fired-at-utc",
                "2026-05-18T10:00:00Z",
                "--log-path",
                str(log),
            ]
        )
        assert rc == 2
        assert not log.exists()

    def test_emit_labels_parsing(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        rc = emitter.main(
            [
                "emit",
                "--alert-name",
                "X",
                "--severity",
                "info",
                "--summary",
                "s",
                "--fired-at-utc",
                "2026-05-18T10:00:00Z",
                "--log-path",
                str(log),
                "--labels",
                "welle=3",
                "subject=wakir.persona-engine.x",
            ]
        )
        assert rc == 0
        obj = json.loads(log.read_text("utf-8").strip())
        assert obj["labels"] == {
            "welle": "3",
            "subject": "wakir.persona-engine.x",
        }


class TestCliValidate:
    def test_valid_file(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        emitter.emit_notify(ev, log_path=log)
        assert emitter.main(["validate", str(log)]) == 0

    def test_invalid_file_nonzero(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        # Bypass validation by hand-writing a malformed line.
        log.write_text(
            json.dumps({"alert_name": "X", "severity": "boom"}) + "\n",
            encoding="utf-8",
        )
        assert emitter.main(["validate", str(log)]) == 1

    def test_missing_file_errors(self, tmp_path):
        assert emitter.main(["validate", str(tmp_path / "no.jsonl")]) == 2
