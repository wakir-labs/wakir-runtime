#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/observability/mira-notify-receiver.py.

Coverage targets:

* ``parse_event_line`` - JSON / validation error reporting.
* ``render_inbox_markdown`` / ``inbox_filename`` - inbox file shape.
* ``run_intake`` - dedupe, dead-letter, materialisation counts.
* CLI ``--mode=file`` and ``--mode=tail`` happy paths.

Anchor: Tag-46 Mira-Notify substance.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_RECEIVER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "mira-notify-receiver.py"
)
_EMITTER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "mira-notify-emitter.py"
)

# Load emitter first so receiver's importlib lookup finds it.
_espec = importlib.util.spec_from_file_location(
    "mira_notify_emitter", str(_EMITTER_PATH)
)
assert _espec is not None and _espec.loader is not None
emitter = importlib.util.module_from_spec(_espec)
sys.modules["mira_notify_emitter"] = emitter
_espec.loader.exec_module(emitter)

_rspec = importlib.util.spec_from_file_location(
    "mira_notify_receiver", str(_RECEIVER_PATH)
)
assert _rspec is not None and _rspec.loader is not None
receiver = importlib.util.module_from_spec(_rspec)
sys.modules["mira_notify_receiver"] = receiver
_rspec.loader.exec_module(receiver)


def _valid_event_line(**overrides) -> str:
    """Build a single valid JSONL line for tests."""
    kwargs = dict(
        alert_name="WakirX",
        severity="info",
        summary="ok",
        fired_at_utc="2026-05-18T10:00:00Z",
        labels={"welle": "3"},
    )
    kwargs.update(overrides)
    ev = emitter.make_event(**kwargs)
    return ev.to_jsonl_line()


# ---------------------------------------------------------------------------
# Pure-function tests.
# ---------------------------------------------------------------------------


class TestParseEventLine:
    def test_valid(self):
        ev, err = receiver.parse_event_line(_valid_event_line())
        assert err is None
        assert ev is not None
        assert ev.alert_name == "WakirX"

    def test_empty_line(self):
        ev, err = receiver.parse_event_line("")
        assert ev is None
        assert err == "empty line"

    def test_invalid_json(self):
        ev, err = receiver.parse_event_line("{not-json")
        assert ev is None
        assert "invalid JSON" in (err or "")

    def test_root_not_object(self):
        ev, err = receiver.parse_event_line('["a","b"]')
        assert ev is None
        assert err == "JSON root is not an object"

    def test_missing_event_id(self):
        # Build a valid event, then strip event_id.
        obj = json.loads(_valid_event_line())
        obj["event_id"] = ""
        line = json.dumps(obj)
        ev, err = receiver.parse_event_line(line)
        assert ev is None
        assert err == "missing event_id"

    def test_validation_error_propagates(self):
        obj = json.loads(_valid_event_line())
        obj["severity"] = "critical"  # not in vocabulary
        line = json.dumps(obj)
        ev, err = receiver.parse_event_line(line)
        assert ev is None
        assert "severity must be one of" in (err or "")


class TestRenderMarkdown:
    def test_contains_title_and_event_id(self):
        ev = emitter.make_event(
            alert_name="WakirFoo",
            severity="page",
            summary="something",
            runbook_url="https://example/r",
            failure_mode_id="A1",
            fired_at_utc="2026-05-18T10:00:00Z",
            labels={"welle": "3"},
        )
        md = receiver.render_inbox_markdown(ev)
        assert "# Mira-Notify [PAGE] - WakirFoo" in md
        assert ev.event_id in md
        assert "https://example/r" in md
        assert "A1" in md
        assert "welle: 3" in md

    def test_includes_description_when_present(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="s",
            description="multi-line\ncontext here",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        md = receiver.render_inbox_markdown(ev)
        assert "## Description" in md
        assert "multi-line" in md

    def test_omits_description_section_when_none(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        md = receiver.render_inbox_markdown(ev)
        assert "## Description" not in md


class TestInboxFilename:
    def test_severity_prefix(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="page",
            summary="s",
            runbook_url="https://example/r",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        name = receiver.inbox_filename(ev)
        assert name.startswith("notify-page-")
        assert name.endswith(".md")

    def test_warning_prefix(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="warning",
            summary="s",
            fired_at_utc="2026-05-18T10:00:00Z",
        )
        assert receiver.inbox_filename(ev).startswith("notify-warn-")

    def test_no_colons_in_filename(self):
        ev = emitter.make_event(
            alert_name="X",
            severity="info",
            summary="s",
            fired_at_utc="2026-05-18T10:30:45Z",
        )
        name = receiver.inbox_filename(ev)
        assert ":" not in name


# ---------------------------------------------------------------------------
# Intake driver tests.
# ---------------------------------------------------------------------------


class TestRunIntake:
    def test_materialises_inbox_files(self, tmp_path):
        inbox = tmp_path / "inbox"
        lines = [
            _valid_event_line(alert_name="A1"),
            _valid_event_line(alert_name="A2"),
        ]
        result = receiver.run_intake(lines, inbox)
        assert result.materialised == 2
        assert result.deduped == 0
        assert result.dead_lettered == 0
        files = list(inbox.glob("notify-*.md"))
        assert len(files) == 2

    def test_dedupes_repeat_events(self, tmp_path):
        inbox = tmp_path / "inbox"
        line = _valid_event_line(alert_name="A1")
        receiver.run_intake([line], inbox)
        result = receiver.run_intake([line], inbox)
        assert result.materialised == 0
        assert result.deduped == 1

    def test_dead_letters_invalid_events(self, tmp_path):
        inbox = tmp_path / "inbox"
        lines = [
            _valid_event_line(alert_name="A1"),
            "{not-json",
            json.dumps({"alert_name": "X", "severity": "boom"}),
        ]
        result = receiver.run_intake(lines, inbox)
        assert result.materialised == 1
        assert result.dead_lettered == 2
        dl = (inbox / ".notify-dead-letter.jsonl").read_text("utf-8")
        assert dl.count("\n") == 2

    def test_exit_code_nonzero_on_dead_letter(self, tmp_path):
        inbox = tmp_path / "inbox"
        result = receiver.run_intake(["{not-json"], inbox)
        assert result.exit_code() == 1

    def test_exit_code_zero_when_all_good(self, tmp_path):
        inbox = tmp_path / "inbox"
        result = receiver.run_intake([_valid_event_line()], inbox)
        assert result.exit_code() == 0

    def test_dedupe_persists_across_runs(self, tmp_path):
        inbox = tmp_path / "inbox"
        line = _valid_event_line(alert_name="A1")
        receiver.run_intake([line], inbox)
        # Second receiver invocation: dedupe set loaded from disk.
        dedupe = receiver.load_dedupe_set(inbox)
        assert len(dedupe) == 1
        result = receiver.run_intake([line, line], inbox)
        assert result.deduped == 2
        assert result.materialised == 0


# ---------------------------------------------------------------------------
# CLI surface tests.
# ---------------------------------------------------------------------------


class TestCliFileMode:
    def test_file_mode_happy(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        inbox = tmp_path / "inbox"
        log.write_text(
            _valid_event_line(alert_name="A1")
            + _valid_event_line(alert_name="A2"),
            encoding="utf-8",
        )
        rc = receiver.main(
            [
                "--mode=file",
                "--input",
                str(log),
                "--inbox",
                str(inbox),
                "--quiet",
            ]
        )
        assert rc == 0
        assert len(list(inbox.glob("notify-*.md"))) == 2

    def test_file_mode_missing_input_returns_zero_with_no_events(
        self, tmp_path
    ):
        # iter_lines_from_file returns iter(()) for missing files; this
        # is by design (the alert-manager hasn't dropped a snapshot yet).
        inbox = tmp_path / "inbox"
        rc = receiver.main(
            [
                "--mode=file",
                "--input",
                str(tmp_path / "no.jsonl"),
                "--inbox",
                str(inbox),
                "--quiet",
            ]
        )
        assert rc == 0


class TestCliTailMode:
    def test_tail_mode_consumes_then_stops(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        inbox = tmp_path / "inbox"
        log.write_text(
            _valid_event_line(alert_name="A1")
            + _valid_event_line(alert_name="A2"),
            encoding="utf-8",
        )
        rc = receiver.main(
            [
                "--mode=tail",
                "--input",
                str(log),
                "--inbox",
                str(inbox),
                "--max-events",
                "2",
                "--poll-seconds",
                "0",
                "--quiet",
            ]
        )
        assert rc == 0
        assert len(list(inbox.glob("notify-*.md"))) == 2
        # Offset file was written; another run with the same offset
        # should consume zero new events.
        offset_path = log.with_suffix(log.suffix + receiver.OFFSET_SUFFIX)
        assert offset_path.exists()

    def test_tail_mode_resumes_from_offset(self, tmp_path):
        log = tmp_path / "notify.jsonl"
        inbox = tmp_path / "inbox"
        log.write_text(_valid_event_line(alert_name="A1"), encoding="utf-8")
        rc1 = receiver.main(
            [
                "--mode=tail",
                "--input",
                str(log),
                "--inbox",
                str(inbox),
                "--max-events",
                "1",
                "--poll-seconds",
                "0",
                "--quiet",
            ]
        )
        assert rc1 == 0
        # Append a second event; second run picks it up but not the
        # already-consumed first event.
        with log.open("a", encoding="utf-8") as fh:
            fh.write(_valid_event_line(alert_name="A2"))
        rc2 = receiver.main(
            [
                "--mode=tail",
                "--input",
                str(log),
                "--inbox",
                str(inbox),
                "--max-events",
                "1",
                "--poll-seconds",
                "0",
                "--quiet",
            ]
        )
        assert rc2 == 0
        files = sorted(p.name for p in inbox.glob("notify-*.md"))
        # Two distinct events materialised.
        assert len(files) == 2


class TestCliStdinMode:
    def test_stdin_mode(self, tmp_path, monkeypatch):
        inbox = tmp_path / "inbox"
        buf = io.StringIO(
            _valid_event_line(alert_name="A1")
            + _valid_event_line(alert_name="A2")
        )
        monkeypatch.setattr(sys, "stdin", buf)
        rc = receiver.main(
            ["--mode=stdin", "--inbox", str(inbox), "--quiet"]
        )
        assert rc == 0
        assert len(list(inbox.glob("notify-*.md"))) == 2
