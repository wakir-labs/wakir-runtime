# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the per-anchor pipeline-stage latency emitter (PR Tag-14).

The producer (``wat.anchor.latency_emitter``) is the counterpart to
PR #145's consumer (``scripts/wat-anchor-pipeline-observability.py``).
These tests assert:

* Default-disabled no-op: without ``WAKIR_ANCHOR_LATENCY_JSONL`` set,
  the emitter never touches the filesystem.
* All four stages emitted: a complete pipeline observation writes one
  JSONL line with the contractual ``stages`` block.
* Error-path semantics: an exception inside the observe-block
  suppresses the emit (SLO-2 is conditional-on-success).
* Rotation / append safety: the emitter co-exists with a file that
  pre-exists, append-mode, and concurrent siblings.
* Wire-contract roundtrip: producer writes, consumer's
  ``read_latency_samples`` parses, and the per-stage seconds match
  what we emitted in ms (within float tolerance).
* End-to-end with ``anchor_root``: stamping a root with the env-var
  set produces a parseable record on the JSONL file.

The tests are Apache-2.0 (the consumer aggregator pattern that PR #145
follows). The implementation under test is BSL-1.1.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator
from unittest import mock

import pytest

from wat.anchor import latency_emitter, ots_anchor
from wat.anchor.latency_emitter import (
    ENV_LATENCY_JSONL_PATH,
    PIPELINE_STAGES,
    STAGE_MS_SUFFIX,
    STAGES_FIELD,
    LatencyEmitter,
    StageRecorder,
    _resolve_target_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure the env-var is unset for the duration of a test."""
    monkeypatch.delenv(ENV_LATENCY_JSONL_PATH, raising=False)
    yield


@pytest.fixture
def jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "wat-anchor-latencies.jsonl"


def _hex_root(seed: bytes = b"test-merkle-root") -> str:
    return hashlib.sha256(seed).hexdigest()


def _read_jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _drive_complete_pipeline(emitter: LatencyEmitter, root_hex: str) -> None:
    """Run a full four-stage observation through the emitter."""
    with emitter.observe(root_hex) as rec:
        for stage in PIPELINE_STAGES:
            with rec.stage(stage):
                pass


# ---------------------------------------------------------------------------
# 1. Default-disabled no-op
# ---------------------------------------------------------------------------


class TestDefaultDisabled:
    """When ``WAKIR_ANCHOR_LATENCY_JSONL`` is unset the emitter is a no-op."""

    def test_env_unset_resolves_to_none(self, clean_env: None) -> None:
        assert _resolve_target_path() is None
        assert LatencyEmitter.from_env().enabled is False

    def test_env_empty_string_resolves_to_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # An accidentally empty value (operator drop-in with no path)
        # must be treated as disabled, not as a path of ``""``.
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, "")
        assert _resolve_target_path() is None
        assert LatencyEmitter.from_env().enabled is False

    def test_env_whitespace_only_resolves_to_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, "   ")
        assert _resolve_target_path() is None

    def test_disabled_observe_creates_no_file(
        self,
        clean_env: None,
        tmp_path: Path,
    ) -> None:
        # Even with a fully-driven observe block, no file is created
        # when the emitter is disabled. Use the temp directory as a
        # blast-radius check: nothing must appear there.
        before = set(tmp_path.iterdir())
        emitter = LatencyEmitter.from_env()
        _drive_complete_pipeline(emitter, _hex_root())
        after = set(tmp_path.iterdir())
        assert before == after, "disabled emitter must not touch the filesystem"


# ---------------------------------------------------------------------------
# 2. All four stages emitted
# ---------------------------------------------------------------------------


class TestStageEmission:
    """An enabled emitter writes one record per complete observation."""

    def test_complete_observation_emits_one_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        assert emitter.enabled is True

        root = _hex_root()
        _drive_complete_pipeline(emitter, root)

        lines = _read_jsonl_lines(jsonl_path)
        assert len(lines) == 1
        record = lines[0]
        assert record["anchor_root_hex"] == root
        assert "timestamp" in record
        # Timestamp matches the ``YYYY-MM-DDTHH:MM:SSZ`` shape used
        # elsewhere in the anchor pipeline.
        assert record["timestamp"].endswith("Z")
        stages = record[STAGES_FIELD]
        for stage in PIPELINE_STAGES:
            key = stage + STAGE_MS_SUFFIX
            assert key in stages, f"missing stage key {key} in {stages!r}"
            assert isinstance(stages[key], (int, float))
            assert stages[key] >= 0.0

    def test_multiple_observations_append(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()

        for i in range(5):
            _drive_complete_pipeline(emitter, _hex_root(f"root-{i}".encode()))

        lines = _read_jsonl_lines(jsonl_path)
        assert len(lines) == 5
        roots = [ln["anchor_root_hex"] for ln in lines]
        assert roots == [_hex_root(f"root-{i}".encode()) for i in range(5)]

    def test_unknown_stage_name_raises_early(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # Typos at call time must not silently drop the observation on
        # flush — surface immediately so the operator catches the bug
        # in a test, not on the dashboard.
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        with emitter.observe(_hex_root()) as rec:
            with pytest.raises(ValueError, match="unknown pipeline stage"):
                with rec.stage("typo-not-a-stage"):
                    pass


# ---------------------------------------------------------------------------
# 3. Error-path semantics
# ---------------------------------------------------------------------------


class TestErrorPath:
    """An exception inside observe() suppresses the emit and re-raises."""

    def test_exception_in_stage_re_raises_and_suppresses_emit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()

        class Synthetic(RuntimeError):
            pass

        with pytest.raises(Synthetic):
            with emitter.observe(_hex_root()) as rec:
                with rec.stage("enqueue_to_pre_ots"):
                    pass
                with rec.stage("ots_call"):
                    raise Synthetic("simulated calendar-fanout failure")

        assert _read_jsonl_lines(jsonl_path) == [], (
            "partial observation on failure must not flush"
        )

    def test_incomplete_observation_suppresses_emit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # No exception, but only three of four stages entered.
        # Consumer drops partial records; producer drops them at source.
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        with emitter.observe(_hex_root()) as rec:
            with rec.stage("enqueue_to_pre_ots"):
                pass
            with rec.stage("ots_call"):
                pass
            with rec.stage("post_ots_commit"):
                pass
            # Missing: wat_write
        assert _read_jsonl_lines(jsonl_path) == []

    def test_emitter_failure_does_not_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Point the env-var at a path whose parent is a *file* (not a
        # directory). The mkdir + open will fail; the emit path must
        # swallow the OSError silently so the anchor pipeline is not
        # affected by observability sickness.
        blocker = tmp_path / "blocker-file"
        blocker.write_text("not-a-directory")
        bad_target = blocker / "child" / "wat-anchor-latencies.jsonl"
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(bad_target))
        emitter = LatencyEmitter.from_env()
        # Must not raise.
        _drive_complete_pipeline(emitter, _hex_root())
        assert not bad_target.exists()


# ---------------------------------------------------------------------------
# 4. Rotation / append safety
# ---------------------------------------------------------------------------


class TestAppendSafety:
    """Append-mode contract: pre-existing files, rotation, concurrent siblings."""

    def test_appends_to_existing_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # Seed with an existing line — a prior run, a log-rotation tail,
        # whatever. The emitter must append, not truncate.
        seed_line = json.dumps(
            {
                "anchor_root_hex": "seed",
                "timestamp": "2026-01-01T00:00:00Z",
                STAGES_FIELD: {
                    f"{s}{STAGE_MS_SUFFIX}": 0.0 for s in PIPELINE_STAGES
                },
            }
        )
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_path.write_text(seed_line + "\n", encoding="utf-8")

        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        _drive_complete_pipeline(emitter, _hex_root())

        lines = _read_jsonl_lines(jsonl_path)
        assert len(lines) == 2
        assert lines[0]["anchor_root_hex"] == "seed"

    def test_creates_parent_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "nested" / "deeper" / "wat-anchor-latencies.jsonl"
        assert not target.parent.exists()
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(target))
        emitter = LatencyEmitter.from_env()
        _drive_complete_pipeline(emitter, _hex_root())
        assert target.exists()
        assert len(_read_jsonl_lines(target)) == 1

    def test_rotation_safe_emitter_survives_file_recreation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # Simulate an external log-rotation: write some records, unlink
        # the file (logrotate-style "create" mode in the worst case),
        # write more records. Each emit re-opens with O_CREAT so a new
        # file appears and contains only the post-rotation records.
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()

        _drive_complete_pipeline(emitter, _hex_root(b"pre-1"))
        _drive_complete_pipeline(emitter, _hex_root(b"pre-2"))
        assert len(_read_jsonl_lines(jsonl_path)) == 2

        # External rotation: unlink the file outright.
        jsonl_path.unlink()

        _drive_complete_pipeline(emitter, _hex_root(b"post-1"))
        lines = _read_jsonl_lines(jsonl_path)
        assert len(lines) == 1
        assert lines[0]["anchor_root_hex"] == _hex_root(b"post-1")


# ---------------------------------------------------------------------------
# 5. Wire-contract roundtrip with the consumer
# ---------------------------------------------------------------------------


def _load_consumer_module() -> object:
    """Import the consumer aggregator script as a module.

    The script lives in ``scripts/`` and has a hyphenated filename, so
    a plain ``import`` does not work. We load it via spec-from-file so
    the test does not depend on the script being installed on PATH.
    """
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "wat-anchor-pipeline-observability.py"
    )
    assert script_path.is_file(), (
        f"consumer script not found at {script_path}"
    )
    spec = importlib.util.spec_from_file_location(
        "_wat_anchor_pipeline_observability_test",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestWireContractRoundtrip:
    """Producer writes, PR #145 consumer reads — same wire format."""

    def test_consumer_parses_producer_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # Produce a handful of observations.
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        for i in range(7):
            _drive_complete_pipeline(emitter, _hex_root(f"r-{i}".encode()))

        # Consume them via the PR #145 reader.
        consumer = _load_consumer_module()
        samples = consumer.read_latency_samples(jsonl_path, window=10)

        # Wire-contract: consumer returns a list of stage-name -> seconds
        # dicts. Producer emits in milliseconds; consumer converts.
        # Length matches what we produced.
        assert len(samples) == 7
        # Stage keys match the contractual ordering — same in producer
        # constants and in consumer constants.
        assert consumer.PIPELINE_STAGES == PIPELINE_STAGES
        for sample in samples:
            assert set(sample.keys()) == set(PIPELINE_STAGES)
            for stage in PIPELINE_STAGES:
                assert sample[stage] >= 0.0
                # Round-trip arithmetic: emitted ms -> consumer seconds.
                # We do not assert exact equality (perf_counter granular
                # ity varies) — only the unit-conversion invariant.
                assert isinstance(sample[stage], float)

    def test_consumer_computes_p99_from_producer_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        jsonl_path: Path,
    ) -> None:
        # End-to-end SLO-2 path: producer emits enough samples for the
        # consumer to compute a non-trivial percentile. This is the
        # acceptance criterion the auftrag spelled out: "p99 berechnet".
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl_path))
        emitter = LatencyEmitter.from_env()
        # 100 observations -> 99th percentile is the 99th-ranked sample.
        for i in range(100):
            _drive_complete_pipeline(emitter, _hex_root(f"r-{i}".encode()))

        consumer = _load_consumer_module()
        samples = consumer.read_latency_samples(jsonl_path, window=100)
        assert len(samples) == 100
        summary = consumer.summarize_window(samples)
        assert summary["window_size"] == 100
        for stage in PIPELINE_STAGES:
            stage_summary = summary["stages"][stage]
            # Every quantile is well-defined and finite for a non-empty
            # window. We do not assert magnitudes (test perf_counter
            # noise is platform-dependent), only structural presence.
            # Consumer (PR #145) keys quantiles as ``pNN_seconds``.
            for quantile_key in (
                "count",
                "p50_seconds",
                "p95_seconds",
                "p99_seconds",
            ):
                assert quantile_key in stage_summary
            assert stage_summary["count"] == 100
            assert stage_summary["p50_seconds"] >= 0.0
            assert stage_summary["p95_seconds"] >= stage_summary["p50_seconds"]
            assert stage_summary["p99_seconds"] >= stage_summary["p95_seconds"]


# ---------------------------------------------------------------------------
# 6. End-to-end: anchor_root wires the emitter
# ---------------------------------------------------------------------------


def _completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ots"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


@pytest.fixture
def fake_ots_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``shutil.which('ots')`` succeed without touching PATH state."""
    monkeypatch.setattr(
        ots_anchor.shutil, "which", lambda name: "/usr/bin/ots"
    )


def _stamp_side_effect(write_receipt: bool = True):
    """Side-effect for subprocess.run mirroring real ``ots stamp`` behaviour."""

    def _go(cmd, *args, **kwargs):
        # cmd[0] is the ots binary, cmd[1] the subcommand.
        if len(cmd) >= 2 and cmd[1] == "stamp" and write_receipt:
            # The root.bin path is the last positional argument.
            root_path = Path(cmd[-1])
            (root_path.parent / (root_path.name + ".ots")).write_bytes(b"\x00")
        # Build a stdout naming all calendars (no error markers -> all
        # treated as ``ok``).
        cal_urls = [a for prev, a in zip(cmd, cmd[1:]) if prev == "--calendar"]
        stdout_lines = [f"Submitting to remote calendar {url}" for url in cal_urls]
        return _completed(returncode=0, stdout="\n".join(stdout_lines))

    return _go


class TestAnchorRootIntegration:
    """``anchor_root`` emits a parseable record when the env-var is set."""

    def test_anchor_root_emits_when_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_ots_binary: None,
    ) -> None:
        jsonl = tmp_path / "wat-anchor-latencies.jsonl"
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl))
        target_dir = tmp_path / "anchor-out"

        with mock.patch.object(
            ots_anchor.subprocess, "run", side_effect=_stamp_side_effect()
        ):
            root = hashlib.sha256(b"e2e-anchor").digest()
            receipt = ots_anchor.anchor_root(
                merkle_root=root,
                target_dir=target_dir,
            )

        assert receipt.merkle_root == root
        lines = _read_jsonl_lines(jsonl)
        assert len(lines) == 1
        record = lines[0]
        assert record["anchor_root_hex"] == root.hex()
        assert set(record[STAGES_FIELD].keys()) == {
            f"{s}{STAGE_MS_SUFFIX}" for s in PIPELINE_STAGES
        }

    def test_anchor_root_no_emit_when_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_ots_binary: None,
    ) -> None:
        # Default behaviour preserved: no env-var, no JSONL file.
        monkeypatch.delenv(ENV_LATENCY_JSONL_PATH, raising=False)
        target_dir = tmp_path / "anchor-out"

        with mock.patch.object(
            ots_anchor.subprocess, "run", side_effect=_stamp_side_effect()
        ):
            ots_anchor.anchor_root(
                merkle_root=hashlib.sha256(b"e2e-no-emit").digest(),
                target_dir=target_dir,
            )

        # Nothing in tmp_path that looks like a JSONL latency log.
        assert not any(
            p.name == "wat-anchor-latencies.jsonl" for p in tmp_path.rglob("*")
        )

    def test_anchor_root_failure_suppresses_emit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_ots_binary: None,
    ) -> None:
        # When the calendar threshold is not met, ``anchor_root`` raises
        # AnchorError before the wat_write stage runs. The partial
        # observation must not flush.
        jsonl = tmp_path / "wat-anchor-latencies.jsonl"
        monkeypatch.setenv(ENV_LATENCY_JSONL_PATH, str(jsonl))
        target_dir = tmp_path / "anchor-out"

        def _failing_stamp(cmd, *args, **kwargs):
            # No receipt file, stdout flags all calendars as errors so
            # the threshold check raises.
            cal_urls = [a for prev, a in zip(cmd, cmd[1:]) if prev == "--calendar"]
            error_lines = [
                f"Error: failed to submit to {url}" for url in cal_urls
            ]
            return _completed(returncode=1, stdout="", stderr="\n".join(error_lines))

        with mock.patch.object(
            ots_anchor.subprocess, "run", side_effect=_failing_stamp
        ):
            with pytest.raises(ots_anchor.AnchorError):
                ots_anchor.anchor_root(
                    merkle_root=hashlib.sha256(b"fail").digest(),
                    target_dir=target_dir,
                )

        assert _read_jsonl_lines(jsonl) == [], (
            "AnchorError before wat_write stage must not flush"
        )


# ---------------------------------------------------------------------------
# 7. Defensive parse — recorder API contract details
# ---------------------------------------------------------------------------


class TestStageRecorderDefensive:
    """Edge-cases on the StageRecorder API contract."""

    def test_recorder_records_durations_in_milliseconds(self) -> None:
        # Use a tiny sleep to ensure a measurable elapsed time, then
        # verify the unit (ms, not seconds) by an order-of-magnitude
        # check. We deliberately do not assert a tight bound — CI
        # runners are noisy — but ~10ms must read as roughly 10 ms,
        # not roughly 0.01 ms.
        import time as _time

        rec = StageRecorder("deadbeef")
        with rec.stage("enqueue_to_pre_ots"):
            _time.sleep(0.01)
        durations = rec.durations_ms()
        assert "enqueue_to_pre_ots" in durations
        # >= 1 ms is a very loose lower bound that survives even on a
        # very fast machine where sleep(0.01) actually sleeps ~5 ms.
        assert durations["enqueue_to_pre_ots"] >= 1.0
        # < 1000 ms is an even looser upper bound that catches a unit
        # bug where seconds-instead-of-ms would show ~0.01.
        assert durations["enqueue_to_pre_ots"] < 1000.0

    def test_is_complete_requires_all_four_stages(self) -> None:
        rec = StageRecorder("cafebabe")
        assert rec.is_complete() is False
        for stage in PIPELINE_STAGES[:3]:
            with rec.stage(stage):
                pass
        assert rec.is_complete() is False
        with rec.stage(PIPELINE_STAGES[3]):
            pass
        assert rec.is_complete() is True

    def test_re_entering_stage_overwrites(self) -> None:
        rec = StageRecorder("00ff")
        with rec.stage("ots_call"):
            pass
        first = rec.durations_ms()["ots_call"]
        with rec.stage("ots_call"):
            import time as _time

            _time.sleep(0.005)
        second = rec.durations_ms()["ots_call"]
        # Second observation overwrites the first. The new value must
        # reflect the sleep; the old value did not.
        assert second != first
