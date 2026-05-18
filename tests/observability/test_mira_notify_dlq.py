#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/observability/mira-notify-dlq.py.

Coverage targets (Tag-51 substance):

1.  ``read_dead_letter_file`` -- empty / non-existent / multi-record /
    corrupted-envelope-line surfaces.
2.  ``classify_error`` -- each of the bounded categories.
3.  ``build_inspect_report`` -- totals, histograms, earliest/latest.
4.  ``apply_patches`` -- each patch rule + idempotency.
5.  ``try_construct_event`` -- success path + missing-event_id branch.
6.  ``run_replay`` dry-run -- counts only, no inbox writes, no DLQ mutation.
7.  ``run_replay`` apply -- inbox files created, dedupe-set appended.
8.  ``run_replay`` apply -- patches required to recover a real failure.
9.  ``run_replay`` apply -- dedupe-skip path (already materialised).
10. ``run_prune`` -- drops resolved entries only.
11. CLI ``inspect`` markdown + JSON output.
12. CLI ``replay --apply`` end-to-end with dead-letter eviction.
13. CLI ``prune --apply`` end-to-end with mtime-stable retention.
14. ``write_dead_letter_file`` -- empty list truncates, non-empty re-writes.

Sandbox posture: stdlib + pytest only; ``tmp_path`` for isolation.

Anchor: Tag-51 substance.  Producer side: Tag-46 emitter/receiver.

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
_OBS_DIR = _REPO_ROOT / "scripts" / "observability"
_EMITTER_PATH = _OBS_DIR / "mira-notify-emitter.py"
_RECEIVER_PATH = _OBS_DIR / "mira-notify-receiver.py"
_DLQ_PATH = _OBS_DIR / "mira-notify-dlq.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load in dependency order; the DLQ module re-loads these by path so
# we explicitly seed the import-cache here for predictability.
emitter = _load("mira_notify_emitter", _EMITTER_PATH)
receiver = _load("mira_notify_receiver", _RECEIVER_PATH)
dlq = _load("mira_notify_dlq", _DLQ_PATH)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _make_dlq_envelope(error: str, raw: str | dict) -> str:
    if isinstance(raw, dict):
        raw_str = json.dumps(raw, sort_keys=True)
    else:
        raw_str = raw
    return json.dumps({"_error": error, "_raw": raw_str}, sort_keys=True)


def _write_dlq(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _valid_payload(**overrides) -> dict:
    """A payload that would pass emitter validation."""
    base = {
        "schema_version": emitter.SCHEMA_VERSION,
        "alert_name": "WakirReadyDrift",
        "severity": "info",
        "fired_at_utc": "2026-05-18T10:00:00Z",
        "summary": "ok",
        "labels": {"welle": "3"},
        "annotations": {},
        "failure_mode_id": None,
        "runbook_url": None,
        "description": None,
        "source": "test",
    }
    base.update(overrides)
    base["event_id"] = emitter.derive_event_id(
        base["alert_name"], base["fired_at_utc"], base["labels"]
    )
    return base


# ---------------------------------------------------------------------------
# 1. read_dead_letter_file.
# ---------------------------------------------------------------------------


class TestReadDeadLetterFile:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        records = dlq.read_dead_letter_file(tmp_path / "missing.jsonl")
        assert records == []

    def test_empty_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        p.write_text("", encoding="utf-8")
        assert dlq.read_dead_letter_file(p) == []

    def test_multi_record(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        _write_dlq(
            p,
            [
                _make_dlq_envelope("invalid JSON: x", "{not json"),
                _make_dlq_envelope("missing event_id", _valid_payload()),
            ],
        )
        records = dlq.read_dead_letter_file(p)
        assert len(records) == 2
        assert records[0].line_no == 1
        assert records[1].line_no == 2
        assert "invalid JSON" in records[0].error

    def test_corrupted_envelope_line(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        _write_dlq(p, ["{not-json-envelope", _make_dlq_envelope("e", "{}")])
        records = dlq.read_dead_letter_file(p)
        assert len(records) == 2
        assert "corrupted envelope" in records[0].error

    def test_envelope_not_object(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        _write_dlq(p, ['["a"]'])
        records = dlq.read_dead_letter_file(p)
        assert len(records) == 1
        assert "envelope is not a JSON object" in records[0].error


# ---------------------------------------------------------------------------
# 2. classify_error.
# ---------------------------------------------------------------------------


class TestClassifyError:
    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("empty line", "empty_line"),
            ("invalid JSON: Expecting value", "invalid_json"),
            ("JSON root is not an object", "json_root_not_object"),
            ("cannot construct NotifyEvent: TypeError", "construct_error"),
            ("missing event_id", "missing_event_id"),
            ("schema_version must be '1', got ''", "schema_version_mismatch"),
            ("alert_name must be a non-empty string", "missing_alert_name"),
            (
                "severity must be one of ('page', 'warning', 'info'), got 'crit'",
                "invalid_severity",
            ),
            (
                "fired_at_utc must be ISO-8601 with Z suffix, got '2026-05-18'",
                "invalid_fired_at_utc",
            ),
            ("summary must be a non-empty string", "missing_summary"),
            ("summary length 201 exceeds limit 200", "summary_too_long"),
            ("runbook_url is required for severity=page", "missing_runbook_for_page"),
            ("labels entry 'x'=1 must be string->string", "invalid_labels_shape"),
            ("something else entirely", "other"),
        ],
    )
    def test_categories(self, msg: str, expected: str):
        assert dlq.classify_error(msg) == expected


# ---------------------------------------------------------------------------
# 3. build_inspect_report.
# ---------------------------------------------------------------------------


class TestBuildInspectReport:
    def test_empty(self):
        report = dlq.build_inspect_report([])
        assert report.total == 0
        assert report.by_category == {}
        assert report.by_alert_name == {}
        assert report.earliest_fired_at_utc is None
        assert report.latest_fired_at_utc is None

    def test_counts_and_window(self, tmp_path: Path):
        # Build three records covering distinct categories.
        recs = [
            dlq.DeadLetterRecord(
                error="missing event_id",
                raw=json.dumps(
                    _valid_payload(
                        alert_name="A1", fired_at_utc="2026-05-18T10:00:00Z"
                    )
                ),
                line_no=1,
            ),
            dlq.DeadLetterRecord(
                error="schema_version must be '1', got ''",
                raw=json.dumps(
                    _valid_payload(
                        alert_name="A1", fired_at_utc="2026-05-18T11:00:00Z"
                    )
                ),
                line_no=2,
            ),
            dlq.DeadLetterRecord(
                error="invalid JSON: ...",
                raw="{not-json",
                line_no=3,
            ),
        ]
        report = dlq.build_inspect_report(recs)
        assert report.total == 3
        assert report.by_category["missing_event_id"] == 1
        assert report.by_category["schema_version_mismatch"] == 1
        assert report.by_category["invalid_json"] == 1
        assert report.by_alert_name == {"A1": 2}
        assert report.earliest_fired_at_utc == "2026-05-18T10:00:00Z"
        assert report.latest_fired_at_utc == "2026-05-18T11:00:00Z"


# ---------------------------------------------------------------------------
# 4. apply_patches.
# ---------------------------------------------------------------------------


class TestApplyPatches:
    def test_set_schema_version(self):
        obj = {"alert_name": "X", "schema_version": "0"}
        out = dlq.apply_patches(obj, dlq.PatchOptions(set_schema_version=True))
        assert out["schema_version"] == emitter.SCHEMA_VERSION

    def test_fill_missing_fired_at(self, monkeypatch):
        monkeypatch.setattr(dlq, "now_utc_iso", lambda: "2026-05-19T00:00:00Z")
        obj = {"alert_name": "X"}
        out = dlq.apply_patches(
            obj, dlq.PatchOptions(fill_missing_fired_at_utc=True)
        )
        assert out["fired_at_utc"] == "2026-05-19T00:00:00Z"

    def test_normalise_severity(self):
        obj = {"severity": "  PAGE  "}
        out = dlq.apply_patches(
            obj, dlq.PatchOptions(normalise_severity=True)
        )
        assert out["severity"] == "page"

    def test_default_severity_for_missing(self):
        obj = {"alert_name": "X"}
        out = dlq.apply_patches(
            obj,
            dlq.PatchOptions(
                normalise_severity=True, default_severity="info"
            ),
        )
        assert out["severity"] == "info"

    def test_backfill_labels_and_annotations(self):
        out = dlq.apply_patches({}, dlq.PatchOptions())
        assert out["labels"] == {}
        assert out["annotations"] == {}

    def test_derive_event_id_when_missing(self):
        obj = {
            "alert_name": "X",
            "fired_at_utc": "2026-05-19T00:00:00Z",
            "labels": {"a": "b"},
        }
        out = dlq.apply_patches(obj, dlq.PatchOptions())
        assert out["event_id"] == emitter.derive_event_id(
            "X", "2026-05-19T00:00:00Z", {"a": "b"}
        )


# ---------------------------------------------------------------------------
# 5. try_construct_event.
# ---------------------------------------------------------------------------


class TestTryConstructEvent:
    def test_happy_path(self):
        ev, err = dlq.try_construct_event(_valid_payload())
        assert err is None
        assert ev is not None
        assert ev.alert_name == "WakirReadyDrift"

    def test_missing_event_id(self):
        obj = _valid_payload()
        obj["event_id"] = ""
        ev, err = dlq.try_construct_event(obj)
        assert ev is None
        assert "missing event_id" in (err or "")

    def test_validation_failure(self):
        obj = _valid_payload(severity="crit")
        obj["event_id"] = emitter.derive_event_id(
            obj["alert_name"], obj["fired_at_utc"], obj["labels"]
        )
        ev, err = dlq.try_construct_event(obj)
        assert ev is None
        assert "severity must be one of" in (err or "")


# ---------------------------------------------------------------------------
# 6. run_replay dry-run.
# ---------------------------------------------------------------------------


class TestRunReplayDryRun:
    def test_dry_run_does_not_write_inbox(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        recs = [
            dlq.DeadLetterRecord(
                error="something",
                raw=json.dumps(_valid_payload()),
                line_no=1,
            )
        ]
        result = dlq.run_replay(
            recs, inbox, patches=dlq.PatchOptions(), apply=False
        )
        assert result.attempted == 1
        assert result.replayed == 1
        assert result.inbox_files == []
        # Dry-run leaves the dead-letter records in place.
        assert len(result.remaining_records) == 1
        # No filesystem mutation in inbox.
        assert not (inbox / receiver.DEDUPE_FILENAME).exists()


# ---------------------------------------------------------------------------
# 7. run_replay apply: happy path.
# ---------------------------------------------------------------------------


class TestRunReplayApplyHappy:
    def test_replay_writes_inbox_and_dedupe(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        recs = [
            dlq.DeadLetterRecord(
                error="x", raw=json.dumps(_valid_payload()), line_no=1
            )
        ]
        result = dlq.run_replay(
            recs, inbox, patches=dlq.PatchOptions(), apply=True
        )
        assert result.replayed == 1
        assert len(result.inbox_files) == 1
        assert result.inbox_files[0].exists()
        dedupe = (inbox / receiver.DEDUPE_FILENAME).read_text("utf-8")
        assert _valid_payload()["event_id"] in dedupe
        assert result.remaining_records == []


# ---------------------------------------------------------------------------
# 8. run_replay apply: patches recover a real failure.
# ---------------------------------------------------------------------------


class TestRunReplayApplyPatchRecovery:
    def test_schema_version_patch_recovers(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        broken = _valid_payload()
        broken["schema_version"] = ""  # caused the original dead-letter
        # event_id was computed from a "valid" event but since labels
        # didn't change, re-deriving will give the same id.
        recs = [
            dlq.DeadLetterRecord(
                error="schema_version must be '1', got ''",
                raw=json.dumps(broken),
                line_no=1,
            )
        ]
        # Without patch, replay should still fail.
        result_nopatch = dlq.run_replay(
            recs, inbox, patches=dlq.PatchOptions(), apply=False
        )
        assert result_nopatch.replayed == 0
        assert result_nopatch.still_failed == 1
        # With patch, replay should succeed.
        result_patch = dlq.run_replay(
            recs,
            inbox,
            patches=dlq.PatchOptions(set_schema_version=True),
            apply=True,
        )
        assert result_patch.replayed == 1
        assert result_patch.remaining_records == []


# ---------------------------------------------------------------------------
# 9. run_replay apply: dedupe-skip path.
# ---------------------------------------------------------------------------


class TestRunReplayDedupeSkip:
    def test_dedupe_skip(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        payload = _valid_payload()
        # Pre-populate the dedupe set so replay finds the event_id
        # already present.
        receiver.append_dedupe(inbox, payload["event_id"])
        recs = [
            dlq.DeadLetterRecord(
                error="x", raw=json.dumps(payload), line_no=1
            )
        ]
        result = dlq.run_replay(
            recs, inbox, patches=dlq.PatchOptions(), apply=True
        )
        assert result.replayed == 0
        assert result.skipped_dedupe == 1
        assert result.inbox_files == []
        # The dead-letter record is consumed (dropped from remaining).
        assert result.remaining_records == []


# ---------------------------------------------------------------------------
# 10. run_prune.
# ---------------------------------------------------------------------------


class TestRunPrune:
    def test_prune_drops_resolved_only(self, tmp_path: Path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        resolved = _valid_payload(alert_name="Resolved")
        unresolved = _valid_payload(alert_name="Unresolved")
        receiver.append_dedupe(inbox, resolved["event_id"])
        recs = [
            dlq.DeadLetterRecord(
                error="x", raw=json.dumps(resolved), line_no=1
            ),
            dlq.DeadLetterRecord(
                error="x", raw=json.dumps(unresolved), line_no=2
            ),
        ]
        result = dlq.run_prune(recs, inbox, patches=dlq.PatchOptions())
        assert result.pruned == 1
        assert result.kept == 1
        assert len(result.remaining_records) == 1
        assert (
            result.remaining_records[0].alert_name() == "Unresolved"
        )


# ---------------------------------------------------------------------------
# 11. CLI inspect.
# ---------------------------------------------------------------------------


class TestCLIInspect:
    def test_markdown_output(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        _write_dlq(
            dlq_file,
            [
                _make_dlq_envelope("invalid JSON: x", "{not-json"),
                _make_dlq_envelope("missing event_id", _valid_payload()),
            ],
        )
        rc = dlq.main(
            [
                "--inbox",
                str(inbox),
                "inspect",
                "--format",
                "markdown",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Mira-Notify DLQ Inspect Report" in out
        assert "invalid_json" in out
        assert "missing_event_id" in out

    def test_json_output(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        _write_dlq(
            dlq_file,
            [_make_dlq_envelope("missing event_id", _valid_payload())],
        )
        rc = dlq.main(
            [
                "--inbox",
                str(inbox),
                "inspect",
                "--format",
                "json",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total"] == 1
        assert data["by_category"]["missing_event_id"] == 1

    def test_inspect_empty_file(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        rc = dlq.main(
            ["--inbox", str(inbox), "inspect", "--format", "json"]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# 12. CLI replay --apply end-to-end.
# ---------------------------------------------------------------------------


class TestCLIReplayApply:
    def test_replay_apply_end_to_end(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        payload = _valid_payload()
        _write_dlq(dlq_file, [_make_dlq_envelope("x", payload)])
        rc = dlq.main(
            [
                "--inbox",
                str(inbox),
                "replay",
                "--apply",
                "--format",
                "json",
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["replayed"] == 1
        # Dead-letter file is truncated after successful replay.
        assert dlq_file.read_text("utf-8") == ""
        # Inbox file materialised.
        inbox_files = list(inbox.glob("notify-*.md"))
        assert len(inbox_files) == 1

    def test_replay_dry_run_leaves_dlq_intact(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        _write_dlq(dlq_file, [_make_dlq_envelope("x", _valid_payload())])
        before = dlq_file.read_text("utf-8")
        rc = dlq.main(
            ["--inbox", str(inbox), "replay", "--format", "json"]
        )
        assert rc == 0
        # Without --apply the dead-letter file is unchanged.
        assert dlq_file.read_text("utf-8") == before
        # And no inbox markdown was written.
        assert list(inbox.glob("notify-*.md")) == []

    def test_replay_nonzero_exit_on_unrecoverable(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        # Garbage raw payload that cannot be patched.
        _write_dlq(dlq_file, [_make_dlq_envelope("invalid JSON", "{not")])
        rc = dlq.main(
            ["--inbox", str(inbox), "replay", "--apply", "--format", "json"]
        )
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["still_failed"] == 1


# ---------------------------------------------------------------------------
# 13. CLI prune --apply end-to-end.
# ---------------------------------------------------------------------------


class TestCLIPruneApply:
    def test_prune_apply_evicts_resolved(self, tmp_path: Path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        resolved = _valid_payload(alert_name="R")
        unresolved = _valid_payload(alert_name="U")
        receiver.append_dedupe(inbox, resolved["event_id"])
        dlq_file = inbox / receiver.DEAD_LETTER_FILENAME
        _write_dlq(
            dlq_file,
            [
                _make_dlq_envelope("x", resolved),
                _make_dlq_envelope("x", unresolved),
            ],
        )
        rc = dlq.main(
            [
                "--inbox",
                str(inbox),
                "prune",
                "--apply",
                "--format",
                "json",
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["pruned"] == 1
        assert data["kept"] == 1
        # The dead-letter file now holds only the unresolved entry.
        remaining_lines = [
            line for line in dlq_file.read_text("utf-8").splitlines() if line.strip()
        ]
        assert len(remaining_lines) == 1
        envelope = json.loads(remaining_lines[0])
        inner = json.loads(envelope["_raw"])
        assert inner["alert_name"] == "U"


# ---------------------------------------------------------------------------
# 14. write_dead_letter_file.
# ---------------------------------------------------------------------------


class TestWriteDeadLetterFile:
    def test_empty_list_truncates(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        p.write_text("garbage\nmore\n", encoding="utf-8")
        dlq.write_dead_letter_file(p, [])
        assert p.read_text("utf-8") == ""

    def test_round_trip(self, tmp_path: Path):
        p = tmp_path / "dlq.jsonl"
        recs = [
            dlq.DeadLetterRecord(error="e1", raw='{"a":1}', line_no=1),
            dlq.DeadLetterRecord(error="e2", raw='{"b":2}', line_no=2),
        ]
        dlq.write_dead_letter_file(p, recs)
        back = dlq.read_dead_letter_file(p)
        assert [r.error for r in back] == ["e1", "e2"]
        assert [r.raw for r in back] == ['{"a":1}', '{"b":2}']

    def test_custom_dlq_file_arg(self, tmp_path: Path, capsys):
        custom = tmp_path / "elsewhere.jsonl"
        _write_dlq(custom, [_make_dlq_envelope("x", _valid_payload())])
        rc = dlq.main(
            [
                "--inbox",
                str(tmp_path / "inbox"),
                "--dlq-file",
                str(custom),
                "inspect",
                "--format",
                "json",
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 1
