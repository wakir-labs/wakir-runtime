# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for wakir-mira-dispatch (Sprint-Pengine-10 OI-PEFR-7).

The CLI orchestrates the Pre-Framework dispatch (operator-supplied
subprocess) and the Bridge-Forward-Pipe publish on NATS. The hermetic
test surface exercises:

- ``--dry-run`` byte-stable envelope output.
- ``--nats-mock`` ack-counting + publish-recording.
- ``--no-preframework`` mirror-publish-only mode.
- Argument validation.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace

import pytest

from wirelang.cli.mira_dispatch import (
    InMemoryNatsMock,
    dispatch,
    main,
)


# ---------------------------------------------------------------------
# InMemoryNatsMock
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inmemory_nats_mock_records_publish():
    mock = InMemoryNatsMock()
    await mock.publish("foo", b"bar")
    assert mock.published == [("foo", b"bar")]


@pytest.mark.asyncio
async def test_inmemory_nats_mock_flush_no_op():
    mock = InMemoryNatsMock()
    await mock.flush()


@pytest.mark.asyncio
async def test_inmemory_nats_mock_drain_closes():
    mock = InMemoryNatsMock()
    await mock.drain()
    assert mock.closed is True


@pytest.mark.asyncio
async def test_inmemory_nats_mock_publish_after_close_raises():
    mock = InMemoryNatsMock()
    await mock.drain()
    with pytest.raises(RuntimeError):
        await mock.publish("x", b"y")


# ---------------------------------------------------------------------
# dispatch — async core
# ---------------------------------------------------------------------


def _make_args(tmp_path: Path, **overrides) -> SimpleNamespace:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello world")
    defaults = dict(
        persona_slug="tomas",
        auftrag_id="a-1",
        prompt_file=str(prompt_file),
        prompt_stdin=False,
        env="dev",
        org_id="acme",
        source="mira-sandbox",
        nats_url="nats://localhost:4222",
        metadata=[],
        ts_utc="2026-05-15T22:00:00Z",
        preframework_cmd=None,
        no_preframework=True,
        async_dispatch=True,
        sync_dispatch=False,
        nats_mock=True,
        dry_run=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_dispatch_pure_mirror_uses_mock(tmp_path: Path):
    args = _make_args(tmp_path)
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    res = await dispatch(args, nats_client_factory=factory)
    assert res["bridge_forward_returncode"] == 0
    assert res["preframework_skipped"] is True
    assert len(mock.published) == 1
    subject, payload = mock.published[0]
    assert subject == "wakir.dev.agent.agent.task.assigned.tomas"
    obj = json.loads(payload.decode("utf-8"))
    assert obj["auftrag_id"] == "a-1"
    assert obj["prompt_payload"] == "hello world"


@pytest.mark.asyncio
async def test_dispatch_dry_run_no_publish(tmp_path: Path):
    args = _make_args(tmp_path, dry_run=True)
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    buf = io.StringIO()
    with redirect_stdout(buf):
        res = await dispatch(args, nats_client_factory=factory)
    assert mock.published == []
    out = buf.getvalue()
    assert "subject: wakir.dev.agent.agent.task.assigned.tomas" in out


@pytest.mark.asyncio
async def test_dispatch_carries_metadata(tmp_path: Path):
    args = _make_args(
        tmp_path,
        metadata=["sprint=sprint-10", "tag=tag-7"],
    )
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    await dispatch(args, nats_client_factory=factory)
    _, payload = mock.published[0]
    obj = json.loads(payload.decode("utf-8"))
    assert obj["metadata"] == {"sprint": "sprint-10", "tag": "tag-7"}


@pytest.mark.asyncio
async def test_dispatch_preframework_skipped_flag_true_for_no_preframework(tmp_path: Path):
    args = _make_args(tmp_path)
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    res = await dispatch(args, nats_client_factory=factory)
    assert res["preframework_skipped"] is True


@pytest.mark.asyncio
async def test_dispatch_subject_field_correct(tmp_path: Path):
    args = _make_args(tmp_path, persona_slug="reza")
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    res = await dispatch(args, nats_client_factory=factory)
    assert res["subject"] == "wakir.dev.agent.agent.task.assigned.reza"


@pytest.mark.asyncio
async def test_dispatch_staging_env(tmp_path: Path):
    args = _make_args(tmp_path, env="staging")
    mock = InMemoryNatsMock()

    async def factory():
        return mock

    res = await dispatch(args, nats_client_factory=factory)
    assert res["subject"].startswith("wakir.staging.")


@pytest.mark.asyncio
async def test_dispatch_dry_run_writes_canonical_envelope(tmp_path: Path):
    args = _make_args(tmp_path, dry_run=True)

    buf = io.StringIO()
    with redirect_stdout(buf):
        await dispatch(args)
    lines = buf.getvalue().splitlines()
    assert lines[0].startswith("# subject:")
    # Following line is the JSON envelope.
    obj = json.loads(lines[1])
    assert obj["persona_id"] == "tomas"


# ---------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------


def test_main_dry_run_exits_zero(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")
    rc = main([
        "--persona-slug", "tomas",
        "--auftrag-id", "a-1",
        "--prompt-file", str(prompt),
        "--no-preframework",
        "--dry-run",
        "--ts-utc", "2026-05-15T22:00:00Z",
    ])
    assert rc == 0


def test_main_missing_preframework_and_no_flag_fails(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")
    err_buf = io.StringIO()
    with redirect_stderr(err_buf):
        rc = main([
            "--persona-slug", "tomas",
            "--auftrag-id", "a-1",
            "--prompt-file", str(prompt),
            "--dry-run",
        ])
    assert rc == 1
    assert "preframework-cmd" in err_buf.getvalue() or "preframework" in err_buf.getvalue()


def test_main_nats_mock_publishes(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello world")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([
            "--persona-slug", "tomas",
            "--auftrag-id", "a-1",
            "--prompt-file", str(prompt),
            "--no-preframework",
            "--nats-mock",
            "--ts-utc", "2026-05-15T22:00:00Z",
        ])
    assert rc == 0
    out = buf.getvalue()
    res = json.loads(out)
    assert res["preframework_skipped"] is True
    assert res["bridge_forward_returncode"] == 0


def test_main_oversize_prompt_returns_two(tmp_path: Path):
    big = tmp_path / "big.txt"
    big.write_text("x" * (300 * 1024))
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main([
            "--persona-slug", "tomas",
            "--auftrag-id", "a-1",
            "--prompt-file", str(big),
            "--no-preframework",
            "--dry-run",
        ])
    assert rc == 2


def test_main_bad_persona_slug_fails(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main([
            "--persona-slug", "Tomas",  # uppercase
            "--auftrag-id", "a-1",
            "--prompt-file", str(prompt),
            "--no-preframework",
            "--dry-run",
        ])
    # Validation runs before the dry-run branch decides; the envelope
    # validation passes (size-only) and build_subject fails -> rc 1.
    assert rc == 1


def test_main_metadata_kv_parsing(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([
            "--persona-slug", "tomas",
            "--auftrag-id", "a-1",
            "--prompt-file", str(prompt),
            "--no-preframework",
            "--dry-run",
            "--metadata", "sprint=sprint-10",
            "--metadata", "tag=tag-7",
            "--ts-utc", "2026-05-15T22:00:00Z",
        ])
    assert rc == 0
    # Find the JSON line.
    for line in buf.getvalue().splitlines():
        if line.startswith("{"):
            obj = json.loads(line)
            assert obj["metadata"]["sprint"] == "sprint-10"
            assert obj["metadata"]["tag"] == "tag-7"
            break


def test_main_help_works():
    """Help should exit cleanly."""
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0


def test_main_stdin_prompt(tmp_path: Path):
    # We can't easily redirect stdin in this test, so we just verify
    # the parser accepts it.
    err = io.StringIO()
    with redirect_stderr(err):
        try:
            main([
                "--persona-slug", "tomas",
                "--auftrag-id", "a-1",
                "--prompt-stdin",
                "--no-preframework",
                "--dry-run",
                "--ts-utc", "2026-05-15T22:00:00Z",
            ])
        except (BrokenPipeError, EOFError):
            pass


def test_main_oversized_auftrag_id_returns_two(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")
    big_id = "a" * 65  # > MAX_AUFTRAG_ID_OCTETS (64)
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main([
            "--persona-slug", "tomas",
            "--auftrag-id", big_id,
            "--prompt-file", str(prompt),
            "--no-preframework",
            "--dry-run",
        ])
    assert rc == 2


def test_main_dry_run_deterministic_across_repeats(tmp_path: Path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello")

    def _run() -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                "--persona-slug", "tomas",
                "--auftrag-id", "a-1",
                "--prompt-file", str(prompt),
                "--no-preframework",
                "--dry-run",
                "--ts-utc", "2026-05-15T22:00:00Z",
            ])
        return buf.getvalue()

    a = _run()
    b = _run()
    assert a == b
