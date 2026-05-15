# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the NATS-Subscribe-Loop (Sprint-Pengine-10 OI-PEFR-6).

Tests cover:
- Subject build helpers.
- Inbound envelope parsing (positive + negative cases).
- Output envelope construction.
- Full loop drive via in-memory async iterator + mock publish sink.
- FSM sub-state tracker.
- Malformed/persona-mismatch handling.
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import List, Optional, Tuple

import pytest

from wirelang.persona_engine.bridge_audit_writer import BridgeAuditWriter
from wirelang.persona_engine.llm_call_shim import (
    EchoReflectionLlmHook,
    LlmCallResult,
)
from wirelang.persona_engine.nats_subscribe_loop import (
    ACCEPTED_INBOUND_SCHEMA,
    InboundEnvelopeError,
    NatsSubscribeLoop,
    OUTBOUND_OUTPUT_SCHEMA,
    ParsedAuftrag,
    SubscribeLoopConfig,
    TaskProcessingTracker,
    build_output_envelope,
    build_output_subject,
    build_subscribe_subject,
    iter_from_queue,
    parse_inbound_envelope,
)


# ---------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------


def _good_envelope(
    *,
    persona_id: str = "tomas",
    auftrag_id: str = "a-1",
    prompt: str = "hello",
    metadata: Optional[dict] = None,
) -> bytes:
    obj = {
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "acme",
        "persona_id": persona_id,
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-15T22:00:00Z",
        "source": "mira-sandbox",
        "prompt_sha256": "sha256:" + ("0" * 64),
        "prompt_payload": prompt,
        "metadata": metadata or {},
    }
    return json.dumps(obj, sort_keys=True).encode("utf-8")


class _FakeMsg:
    def __init__(self, data: bytes, subject: str = "wakir.dev.agent.agent.task.assigned.tomas"):
        self.data = data
        self.subject = subject
        self.acked = False

    async def ack(self) -> None:
        self.acked = True


class _FakePublishSink:
    def __init__(self) -> None:
        self.published: List[Tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


def _make_writer(sink: io.StringIO) -> BridgeAuditWriter:
    return BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-1",
        engine_version="0.4.0-pilot",
        v907_pin="sha256:" + ("a" * 64),
        wakir_runtime_sink=sink,
    )


def _make_config(
    writer: BridgeAuditWriter,
    *,
    publish_output: bool = True,
) -> SubscribeLoopConfig:
    return SubscribeLoopConfig(
        env="dev",
        persona_slug="tomas",
        org_id="acme",
        bridge_writer=writer,
        hook=EchoReflectionLlmHook(),
        publish_output=publish_output,
    )


# ---------------------------------------------------------------------
# Subject builders
# ---------------------------------------------------------------------


def test_build_subscribe_subject_canonical():
    assert build_subscribe_subject("dev", "tomas") == (
        "wakir.dev.agent.agent.task.assigned.tomas"
    )


def test_build_subscribe_subject_staging():
    assert build_subscribe_subject("staging", "alice") == (
        "wakir.staging.agent.agent.task.assigned.alice"
    )


def test_build_subscribe_subject_bad_env():
    with pytest.raises(ValueError):
        build_subscribe_subject("production", "tomas")


def test_build_subscribe_subject_bad_persona_slug_uppercase():
    with pytest.raises(ValueError):
        build_subscribe_subject("dev", "Tomas")


def test_build_subscribe_subject_bad_persona_slug_leading_digit():
    with pytest.raises(ValueError):
        build_subscribe_subject("dev", "1tomas")


def test_build_subscribe_subject_bad_persona_slug_dot():
    with pytest.raises(ValueError):
        build_subscribe_subject("dev", "to.mas")


def test_build_output_subject_canonical():
    assert build_output_subject("dev", "tomas") == (
        "wakir.dev.agent.agent.task.output.tomas"
    )


def test_build_output_subject_bad_env():
    with pytest.raises(ValueError):
        build_output_subject("foo", "tomas")


def test_build_output_subject_bad_persona():
    with pytest.raises(ValueError):
        build_output_subject("dev", "T")


# ---------------------------------------------------------------------
# parse_inbound_envelope
# ---------------------------------------------------------------------


def test_parse_good_envelope():
    parsed = parse_inbound_envelope(_good_envelope())
    assert isinstance(parsed, ParsedAuftrag)
    assert parsed.persona_id == "tomas"
    assert parsed.auftrag_id == "a-1"
    assert parsed.prompt_payload == "hello"


def test_parse_preserves_metadata():
    parsed = parse_inbound_envelope(
        _good_envelope(metadata={"sprint": "sprint-10", "tag": "tag-6"})
    )
    assert parsed.metadata == {"sprint": "sprint-10", "tag": "tag-6"}


def test_parse_default_empty_metadata():
    obj = json.loads(_good_envelope().decode("utf-8"))
    del obj["metadata"]
    parsed = parse_inbound_envelope(
        json.dumps(obj).encode("utf-8")
    )
    assert parsed.metadata == {}


def test_parse_rejects_non_utf8():
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(b"\xff\xfe\xfd")


def test_parse_rejects_non_json():
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(b"not json")


def test_parse_rejects_array_root():
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(b"[]")


def test_parse_rejects_wrong_schema():
    obj = json.loads(_good_envelope().decode("utf-8"))
    obj["schema"] = "wakir.agent.task-other/1"
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(json.dumps(obj).encode("utf-8"))


def test_parse_rejects_wrong_event_kind():
    obj = json.loads(_good_envelope().decode("utf-8"))
    obj["event_kind"] = "agent.task.completed"
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(json.dumps(obj).encode("utf-8"))


def test_parse_rejects_missing_required_fields():
    obj = json.loads(_good_envelope().decode("utf-8"))
    del obj["auftrag_id"]
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(json.dumps(obj).encode("utf-8"))


def test_parse_rejects_empty_required_field():
    obj = json.loads(_good_envelope().decode("utf-8"))
    obj["auftrag_id"] = ""
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(json.dumps(obj).encode("utf-8"))


def test_parse_rejects_metadata_not_object():
    obj = json.loads(_good_envelope().decode("utf-8"))
    obj["metadata"] = "string-not-object"
    with pytest.raises(InboundEnvelopeError):
        parse_inbound_envelope(json.dumps(obj).encode("utf-8"))


# ---------------------------------------------------------------------
# build_output_envelope
# ---------------------------------------------------------------------


def test_build_output_envelope_schema():
    payload = build_output_envelope(
        org_id="acme", persona_id="tomas", auftrag_id="a-1",
        prompt_sha256="sha256:0" + "0" * 63,
        reply_text="reply", reply_sha256="sha256:1" + "1" * 63,
        hook_kind="echo-reflection", ts_utc="2026-05-15T22:00:00Z",
        engine_version="0.4.0-pilot", v907_pin="sha256:a" + "a" * 63,
        session_id="sess-1", step_index=0, metadata={},
    )
    obj = json.loads(payload.decode("utf-8"))
    assert obj["schema"] == OUTBOUND_OUTPUT_SCHEMA
    assert obj["event_kind"] == "agent.task.output"


def test_build_output_envelope_deterministic():
    a = build_output_envelope(
        org_id="acme", persona_id="t", auftrag_id="a",
        prompt_sha256="sha256:p", reply_text="r", reply_sha256="sha256:r",
        hook_kind="echo-reflection", ts_utc="2026-01-01T00:00:00Z",
        engine_version="v", v907_pin="sha256:v",
        session_id="s", step_index=0, metadata={"k": "v"},
    )
    b = build_output_envelope(
        org_id="acme", persona_id="t", auftrag_id="a",
        prompt_sha256="sha256:p", reply_text="r", reply_sha256="sha256:r",
        hook_kind="echo-reflection", ts_utc="2026-01-01T00:00:00Z",
        engine_version="v", v907_pin="sha256:v",
        session_id="s", step_index=0, metadata={"k": "v"},
    )
    assert a == b


def test_build_output_envelope_carries_metadata():
    payload = build_output_envelope(
        org_id="acme", persona_id="tomas", auftrag_id="a-1",
        prompt_sha256="sha256:p", reply_text="r", reply_sha256="sha256:r",
        hook_kind="echo-reflection", ts_utc="2026-05-15T22:00:00Z",
        engine_version="v", v907_pin="sha256:v",
        session_id="s", step_index=0,
        metadata={"sprint": "sprint-10"},
    )
    obj = json.loads(payload.decode("utf-8"))
    assert obj["metadata"] == {"sprint": "sprint-10"}


# ---------------------------------------------------------------------
# TaskProcessingTracker
# ---------------------------------------------------------------------


def test_tracker_initial_state():
    t = TaskProcessingTracker()
    assert t.current_auftrag_id is None
    assert t.last_completed_auftrag_id is None
    assert t.tasks_processed == 0


def test_tracker_begin_then_complete():
    t = TaskProcessingTracker()
    t.begin("a-1")
    assert t.current_auftrag_id == "a-1"
    t.complete("a-1")
    assert t.current_auftrag_id is None
    assert t.last_completed_auftrag_id == "a-1"
    assert t.tasks_processed == 1


def test_tracker_malformed_counter():
    t = TaskProcessingTracker()
    t.malformed()
    t.malformed()
    assert t.tasks_malformed == 2


def test_tracker_hook_failed_counter():
    t = TaskProcessingTracker()
    t.begin("a-1")
    t.hook_failed("a-1")
    assert t.tasks_failed_hook == 1
    assert t.current_auftrag_id is None


# ---------------------------------------------------------------------
# NatsSubscribeLoop — full drive
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_processes_single_msg():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope()))
    await queue.put(None)  # sentinel

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.processed_count == 1
    assert len(publish.published) == 1
    out_subject, out_payload = publish.published[0]
    assert out_subject == "wakir.dev.agent.agent.task.output.tomas"
    out_obj = json.loads(out_payload.decode("utf-8"))
    assert out_obj["auftrag_id"] == "a-1"


@pytest.mark.asyncio
async def test_loop_processes_multiple_msgs():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-1")))
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-2")))
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-3")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.processed_count == 3
    assert len(publish.published) == 3


@pytest.mark.asyncio
async def test_loop_acks_message():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    msg = _FakeMsg(_good_envelope())
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(msg)
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert msg.acked is True


@pytest.mark.asyncio
async def test_loop_handles_malformed_envelope():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(b"not-json"))
    await queue.put(_FakeMsg(_good_envelope()))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.config.tracker.tasks_malformed == 1
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_loop_handles_persona_mismatch():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    # Envelope persona_id=reza, loop configured for tomas.
    await queue.put(_FakeMsg(_good_envelope(persona_id="reza")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    # Mismatched message dropped: no processed task, no publish.
    assert loop.processed_count == 0
    assert len(publish.published) == 0


@pytest.mark.asyncio
async def test_loop_no_publish_when_publish_sink_none():
    sink = io.StringIO()
    writer = _make_writer(sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, publish_sink=None, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope()))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_loop_stop_event_aborts():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope()))
    # Don't put a sentinel — the loop should hang waiting; stop_event aborts.
    stop_event = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0.1)
        stop_event.set()

    await asyncio.gather(
        loop.run_with_iterator(iter_from_queue(queue), stop_event=stop_event),
        _stop_soon(),
    )
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_loop_cancellation_clean():
    sink = io.StringIO()
    writer = _make_writer(sink)
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=None, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(loop.run_with_iterator(iter_from_queue(queue)))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # The loop should swallow the CancelledError per spec.
    assert task.done()


@pytest.mark.asyncio
async def test_loop_emits_audit_for_completion():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope()))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    # Bridge-audit-writer wrote engineering-output records to the sink.
    sink_text = sink.getvalue()
    # At least one record with reply payload + one audit_annotation.
    assert '"reply"' in sink_text
    assert "task-processing-begin" in sink_text
    assert "task-processing-complete" in sink_text


@pytest.mark.asyncio
async def test_loop_output_envelope_carries_metadata():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(
        _FakeMsg(
            _good_envelope(metadata={"sprint": "sprint-10", "tag": "tag-7"})
        )
    )
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    _, out_payload = publish.published[0]
    out_obj = json.loads(out_payload.decode("utf-8"))
    assert out_obj["metadata"] == {"sprint": "sprint-10", "tag": "tag-7"}


@pytest.mark.asyncio
async def test_loop_output_includes_session_step_index():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope()))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    _, out_payload = publish.published[0]
    out_obj = json.loads(out_payload.decode("utf-8"))
    assert out_obj["session_id"] == "sess-1"
    # First reply event in this writer's step counter (assertion: present and int).
    assert isinstance(out_obj["step_index"], int)


@pytest.mark.asyncio
async def test_loop_request_stop_sets_event_when_running():
    sink = io.StringIO()
    writer = _make_writer(sink)
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=None, log_sink=sink)
    queue: asyncio.Queue = asyncio.Queue()

    stop_event = asyncio.Event()

    async def _drive():
        await loop.run_with_iterator(iter_from_queue(queue), stop_event=stop_event)

    task = asyncio.create_task(_drive())
    await asyncio.sleep(0.05)
    loop.request_stop()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_loop_iter_from_queue_sentinel_stops():
    """iter_from_queue stops on the sentinel."""
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(b"x"))
    await queue.put(None)
    items = []
    async for msg in iter_from_queue(queue):
        items.append(msg)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_loop_emits_audit_for_malformed():
    sink = io.StringIO()
    writer = _make_writer(sink)
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=None, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(b"garbage"))
    await queue.put(None)
    await loop.run_with_iterator(iter_from_queue(queue))
    assert "task-input-malformed" in sink.getvalue()


@pytest.mark.asyncio
async def test_loop_emits_audit_for_persona_mismatch():
    sink = io.StringIO()
    writer = _make_writer(sink)
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=None, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(persona_id="reza")))
    await queue.put(None)
    await loop.run_with_iterator(iter_from_queue(queue))
    assert "task-input-persona-mismatch" in sink.getvalue()


@pytest.mark.asyncio
async def test_loop_tracker_advances_per_message():
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    for i in range(5):
        await queue.put(_FakeMsg(_good_envelope(auftrag_id=f"a-{i}")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.config.tracker.tasks_processed == 5
    assert loop.config.tracker.last_completed_auftrag_id == "a-4"


@pytest.mark.asyncio
async def test_loop_hook_exception_does_not_break_loop():
    """A failing hook on one message must not stop the loop."""
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()

    class _FlakyHook:
        def __init__(self):
            self.n = 0

        def call(self, *, persona_id, auftrag_id, prompt_payload, ts_utc=None):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("boom")
            return LlmCallResult(
                persona_id=persona_id, auftrag_id=auftrag_id,
                prompt_sha256="sha256:p", reply_text="ok",
                reply_sha256="sha256:r", ts_utc=ts_utc or "2026-01-01T00:00:00Z",
                hook_kind="flaky",
            )

    cfg = SubscribeLoopConfig(
        env="dev", persona_slug="tomas", org_id="acme",
        bridge_writer=writer, hook=_FlakyHook(), publish_output=True,
    )
    loop = NatsSubscribeLoop(cfg, publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-1")))
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-2")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    # Second message processed; first one logged + skipped.
    assert loop.processed_count == 1
    assert loop.config.tracker.tasks_failed_hook == 1


@pytest.mark.asyncio
async def test_loop_no_ack_method_tolerated():
    """If the inbound msg has no ack() (core-pubsub), the loop runs anyway."""
    class _NoAckMsg:
        def __init__(self, data):
            self.data = data
            self.subject = "wakir.dev.agent.agent.task.assigned.tomas"
        # NB: no ack().

    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_NoAckMsg(_good_envelope()))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_loop_ack_exception_tolerated():
    class _BadAckMsg:
        def __init__(self, data):
            self.data = data
            self.subject = "wakir.dev.agent.agent.task.assigned.tomas"

        async def ack(self):
            raise RuntimeError("ack failed")

    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _FakePublishSink()
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=publish, log_sink=sink)

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_BadAckMsg(_good_envelope()))
    await queue.put(None)
    await loop.run_with_iterator(iter_from_queue(queue))
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_loop_stop_event_pre_set_returns_quickly():
    sink = io.StringIO()
    writer = _make_writer(sink)
    loop = NatsSubscribeLoop(_make_config(writer), publish_sink=None, log_sink=sink)
    queue: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(
        loop.run_with_iterator(iter_from_queue(queue), stop_event=stop),
        timeout=1.0,
    )
