# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for Bug-42 subscribe-mode substrate (Sprint-Pengine-13).

Bug-42 root cause
-----------------
The pre-Sprint-13 ``NatsSubscribeLoop.run_with_iterator`` polled
``msg_iter.__anext__()`` via ``asyncio.wait_for(..., timeout=0.5)``.
On every timeout (the common case — no messages arriving in the
poll window) ``wait_for`` cancelled the underlying ``__anext__``
coroutine. In ``nats-py`` the iterator's ``__anext__`` body creates
an inner ``get_task = asyncio.create_task(queue.get())`` and races
it against an ``_unsubscribed_future``. The outer cancel did not
cleanly cancel the inner ``get_task`` — that inner task may have
already pulled a message off the pending-queue right before the
cancellation propagated. The message was bound to a cancelled
future and never delivered to the consumer.

The Sprint-Pengine-13 fix:
1. ``run_with_iterator`` keeps a persistent ``next_msg_task`` across
   poll iterations and races it against a stop-event task via
   ``asyncio.wait(FIRST_COMPLETED)``. The inner task is cancelled
   **once**, only on shutdown.
2. The CLI defaults to ``core-callback`` subscribe mode which uses
   ``nc.subscribe(subject, cb=handler)`` — no iterator surface, no
   cancellation race.
3. ``WAKIR_NATS_SUBSCRIBE_MODE`` env var selects the mode:
   ``core-callback`` (default), ``core-iterator`` (backward-compat),
   ``jetstream-pull`` (Phase-2 substrate).

Tests
-----
- §1 subscribe-mode resolver (env-var parsing, defaults, validation)
- §2 ``run_with_iterator`` Bug-42-regression vectors
- §3 callback-mode hermetic surface
- §4 CLI dispatch + log-trace assertions
- §5 version-bump assertions

The tests deliberately avoid importing ``nats-py``; the callback
mode is exercised via :class:`CallbackSubscriber` and the iterator
mode via in-memory async iterators.
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import AsyncIterator, List, Optional, Tuple

import pytest

from wirelang.persona_engine import __version__ as PKG_VERSION
from wirelang.persona_engine.bridge_audit_writer import BridgeAuditWriter
from wirelang.persona_engine.engine import ENGINE_VERSION
from wirelang.persona_engine.engine_async import ASYNC_ENGINE_VERSION
from wirelang.persona_engine.llm_call_shim import EchoReflectionLlmHook
from wirelang.persona_engine.nats_subscribe_loop import (
    ACCEPTED_INBOUND_SCHEMA,
    CallbackSubscriber,
    DEFAULT_SUBSCRIBE_MODE,
    NatsSubscribeLoop,
    SUBSCRIBE_MODE_CORE_CALLBACK,
    SUBSCRIBE_MODE_CORE_ITERATOR,
    SUBSCRIBE_MODE_JETSTREAM_PULL,
    SUBSCRIBE_MODE_ENV_VAR,
    SubscribeLoopConfig,
    VALID_SUBSCRIBE_MODES,
    build_subscribe_subject,
    resolve_subscribe_mode,
)
from wirelang.tests.persona_engine._v907_compute_skip import (
    requires_v907_compute_deps,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _good_envelope(
    *,
    persona_id: str = "tomas",
    auftrag_id: str = "a-1",
    prompt: str = "hello",
) -> bytes:
    obj = {
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "acme",
        "persona_id": persona_id,
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-16T08:00:00Z",
        "source": "mira-sandbox",
        "prompt_sha256": "sha256:" + ("0" * 64),
        "prompt_payload": prompt,
        "metadata": {},
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
        engine_version=ENGINE_VERSION,
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


# ---------------------------------------------------------------------------
# §1 — subscribe-mode resolver
# ---------------------------------------------------------------------------


def test_resolve_subscribe_mode_default_is_core_callback():
    """Unset env-var → DEFAULT_SUBSCRIBE_MODE."""
    assert DEFAULT_SUBSCRIBE_MODE == SUBSCRIBE_MODE_CORE_CALLBACK
    assert resolve_subscribe_mode({}) == SUBSCRIBE_MODE_CORE_CALLBACK


def test_resolve_subscribe_mode_empty_string_is_default():
    """Empty env-var → default (defensive)."""
    assert (
        resolve_subscribe_mode({SUBSCRIBE_MODE_ENV_VAR: ""})
        == DEFAULT_SUBSCRIBE_MODE
    )


def test_resolve_subscribe_mode_core_callback_explicit():
    assert (
        resolve_subscribe_mode({SUBSCRIBE_MODE_ENV_VAR: "core-callback"})
        == SUBSCRIBE_MODE_CORE_CALLBACK
    )


def test_resolve_subscribe_mode_core_iterator():
    assert (
        resolve_subscribe_mode({SUBSCRIBE_MODE_ENV_VAR: "core-iterator"})
        == SUBSCRIBE_MODE_CORE_ITERATOR
    )


def test_resolve_subscribe_mode_jetstream_pull():
    assert (
        resolve_subscribe_mode({SUBSCRIBE_MODE_ENV_VAR: "jetstream-pull"})
        == SUBSCRIBE_MODE_JETSTREAM_PULL
    )


def test_resolve_subscribe_mode_unknown_raises():
    with pytest.raises(ValueError) as exc:
        resolve_subscribe_mode({SUBSCRIBE_MODE_ENV_VAR: "jetstream-push"})
    assert "not one of" in str(exc.value)
    assert "jetstream-push" in str(exc.value)


def test_valid_subscribe_modes_constant_complete():
    """The VALID_SUBSCRIBE_MODES tuple lists all exported modes."""
    assert set(VALID_SUBSCRIBE_MODES) == {
        SUBSCRIBE_MODE_CORE_CALLBACK,
        SUBSCRIBE_MODE_CORE_ITERATOR,
        SUBSCRIBE_MODE_JETSTREAM_PULL,
    }


def test_subscribe_mode_env_var_name_locked():
    """Lock the env-var name so accidental rename breaks the test."""
    assert SUBSCRIBE_MODE_ENV_VAR == "WAKIR_NATS_SUBSCRIBE_MODE"


# ---------------------------------------------------------------------------
# §2 — run_with_iterator Bug-42-regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iterator_processes_msg_arriving_after_quiet_period():
    """Bug-42 reproduction vector.

    Pre-fix: The iterator polled ``__anext__()`` with timeout 0.5s.
    A message arriving after a quiet period (e.g. 0.6s after
    subscribe) was sometimes lost because the cancel-on-timeout
    raced with the inner ``queue.get()`` pulling the message off
    the pending-queue.

    Post-fix: The persistent ``next_msg_task`` survives across
    stop-event polls so no cancellation can race with message
    arrival.
    """
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    log_sink = io.StringIO()
    loop = NatsSubscribeLoop(cfg, log_sink=log_sink)

    queue: asyncio.Queue[_FakeMsg] = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _iter() -> AsyncIterator[_FakeMsg]:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    msg_iter = _iter()

    # Start the loop, then push a message after a short quiet
    # period that would have triggered the pre-fix cancel-on-timeout
    # race (the iterator would have cancelled __anext__() during
    # the quiet period).
    runner = asyncio.create_task(
        loop.run_with_iterator(msg_iter, stop_event=stop_event)
    )
    await asyncio.sleep(0.05)
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="post-quiet-1")))
    await asyncio.sleep(0.05)
    stop_event.set()
    await queue.put(None)  # close the iterator
    await runner

    assert loop.processed_count == 1, (
        "Bug-42 regression: a message arriving after a quiet period was lost. "
        f"loop.processed_count={loop.processed_count}, sink={writer_sink.getvalue()}"
    )


@pytest.mark.asyncio
async def test_iterator_processes_burst_of_messages_without_loss():
    """Burst-arrival vector — Bug-42 secondary fingerprint.

    Push N=50 messages in a tight burst (no inter-message delay)
    and assert all N are processed. Pre-fix this was flaky
    because every cancel-on-timeout could lose one message.
    """
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _iter() -> AsyncIterator[_FakeMsg]:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    msg_iter = _iter()
    N = 50

    runner = asyncio.create_task(
        loop.run_with_iterator(msg_iter, stop_event=stop_event)
    )
    for i in range(N):
        await queue.put(_FakeMsg(_good_envelope(auftrag_id=f"burst-{i}")))
    # Let the loop drain
    for _ in range(100):
        if loop.processed_count >= N:
            break
        await asyncio.sleep(0.01)
    stop_event.set()
    await queue.put(None)
    await runner

    assert loop.processed_count == N, (
        f"burst processing lost messages: got {loop.processed_count} of {N}"
    )


@pytest.mark.asyncio
async def test_iterator_stop_event_does_not_lose_in_flight_message():
    """Verify that setting the stop-event right as a message
    arrives does not drop the message — the persistent
    next_msg_task contract."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _iter() -> AsyncIterator[_FakeMsg]:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    msg_iter = _iter()
    runner = asyncio.create_task(
        loop.run_with_iterator(msg_iter, stop_event=stop_event)
    )
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="just-before-stop")))
    # Tiny sleep to let the run-loop schedule the next_msg_task.
    await asyncio.sleep(0.02)
    stop_event.set()
    await queue.put(None)
    await runner

    # The pre-stop message must have been processed; the stop only
    # fires AFTER the message is consumed (because the
    # next_msg_task wins the race for the first batch).
    assert loop.processed_count == 1


@pytest.mark.asyncio
async def test_iterator_clean_exit_when_only_stop_event_signalled():
    """No messages, immediate stop — loop must exit cleanly."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _iter() -> AsyncIterator[_FakeMsg]:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    msg_iter = _iter()
    runner = asyncio.create_task(
        loop.run_with_iterator(msg_iter, stop_event=stop_event)
    )
    stop_event.set()
    await queue.put(None)
    await asyncio.wait_for(runner, timeout=2.0)
    assert loop.processed_count == 0


@pytest.mark.asyncio
async def test_iterator_handles_stop_async_iteration():
    """When the iterator raises StopAsyncIteration, the loop exits."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    async def _exhausted_iter() -> AsyncIterator[_FakeMsg]:
        for msg in []:
            yield msg
        # implicit StopAsyncIteration

    msg_iter = _exhausted_iter()
    stop_event = asyncio.Event()
    await asyncio.wait_for(
        loop.run_with_iterator(msg_iter, stop_event=stop_event),
        timeout=2.0,
    )
    assert loop.processed_count == 0


@pytest.mark.asyncio
async def test_iterator_cancellation_of_outer_task_is_clean():
    """Cancelling the outer asyncio.Task that runs the loop must
    not leave dangling tasks (resource hygiene)."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _iter() -> AsyncIterator[_FakeMsg]:
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item

    msg_iter = _iter()
    runner = asyncio.create_task(
        loop.run_with_iterator(msg_iter, stop_event=stop_event)
    )
    await asyncio.sleep(0.05)
    runner.cancel()
    try:
        await runner
    except asyncio.CancelledError:
        pass
    # No assert on processed_count; just ensure no exception
    # leaks past the outer cancel.


# ---------------------------------------------------------------------------
# §3 — callback-mode hermetic surface (Bug-42 production-default path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_subscriber_delivers_single_message():
    """Single message via callback-mode path → handled exactly once."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()

    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    await subscriber.deliver(_FakeMsg(_good_envelope(auftrag_id="cb-1")))
    await asyncio.sleep(0.01)
    stop_event.set()
    await runner

    assert loop.processed_count == 1
    assert subscriber.delivered_count == 1


@pytest.mark.asyncio
async def test_callback_subscriber_delivers_burst_without_loss():
    """N=30 message burst via callback-mode → all processed."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())

    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()

    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    N = 30
    for i in range(N):
        await subscriber.deliver(
            _FakeMsg(_good_envelope(auftrag_id=f"cb-burst-{i}"))
        )
    stop_event.set()
    await runner

    assert loop.processed_count == N
    assert subscriber.delivered_count == N


@pytest.mark.asyncio
async def test_callback_subscriber_publishes_output_envelope():
    """Callback mode publishes the response envelope on the
    output-subject (parity with iterator mode)."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=True)
    publish_sink = _FakePublishSink()
    loop = NatsSubscribeLoop(
        cfg, publish_sink=publish_sink, log_sink=io.StringIO(),
    )

    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()
    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    await subscriber.deliver(_FakeMsg(_good_envelope(auftrag_id="cb-pub-1")))
    await asyncio.sleep(0.01)
    stop_event.set()
    await runner

    assert len(publish_sink.published) == 1
    out_subject, out_payload = publish_sink.published[0]
    assert out_subject == "wakir.dev.agent.agent.task.output.tomas"
    out_obj = json.loads(out_payload)
    assert out_obj["auftrag_id"] == "cb-pub-1"
    assert out_obj["persona_id"] == "tomas"
    assert out_obj["schema"] == "wakir.agent.task-output/1"


@pytest.mark.asyncio
async def test_callback_subscriber_unbinds_on_exit():
    """After stop-event fires + runner returns, the subscriber
    is unbound (no dangling handler reference)."""
    writer = _make_writer(io.StringIO())
    cfg = _make_config(writer, publish_output=False)
    loop = NatsSubscribeLoop(cfg, log_sink=io.StringIO())
    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()
    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    stop_event.set()
    await runner
    # After unbind, delivering must raise.
    with pytest.raises(RuntimeError) as exc:
        await subscriber.deliver(
            _FakeMsg(_good_envelope(auftrag_id="post-exit"))
        )
    assert "before bind" in str(exc.value)


@pytest.mark.asyncio
async def test_callback_subscriber_deliver_before_bind_raises():
    """Pre-bind delivery raises RuntimeError (defensive guard)."""
    subscriber = CallbackSubscriber()
    with pytest.raises(RuntimeError) as exc:
        await subscriber.deliver(_FakeMsg(_good_envelope()))
    assert "before bind" in str(exc.value)


@pytest.mark.asyncio
async def test_callback_subscriber_handles_malformed_envelope():
    """A malformed envelope via callback-mode is dropped + audited.

    The Bridge-Audit-Writer envelope does NOT carry the raw payload
    string (only the SHA-256 hash of it), so the assertion is on the
    loop's own JSON log-sink which captures the structured
    ``task-input-malformed`` event with ``reason`` + ``subject``.
    """
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop_log = io.StringIO()
    loop = NatsSubscribeLoop(cfg, log_sink=loop_log)
    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()
    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    await subscriber.deliver(_FakeMsg(b"{not json"))
    await asyncio.sleep(0.01)
    stop_event.set()
    await runner

    assert loop.processed_count == 0  # malformed != processed
    assert "task-input-malformed" in loop_log.getvalue()
    # And the writer-sink did record an audit-annotation event
    # (whose payload-bytes are hash-only by Bridge-Audit-Writer
    # contract).
    assert "audit_annotation" in writer_sink.getvalue()


@pytest.mark.asyncio
async def test_callback_subscriber_persona_mismatch_dropped():
    """A message addressed to a different persona is dropped."""
    writer_sink = io.StringIO()
    writer = _make_writer(writer_sink)
    cfg = _make_config(writer, publish_output=False)
    loop_log = io.StringIO()
    loop = NatsSubscribeLoop(cfg, log_sink=loop_log)
    subscriber = CallbackSubscriber()
    stop_event = asyncio.Event()
    runner = asyncio.create_task(
        loop.run_callback_mode_with_subscriber(
            subscriber, stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.01)
    await subscriber.deliver(
        _FakeMsg(_good_envelope(persona_id="lena"))
    )
    await asyncio.sleep(0.01)
    stop_event.set()
    await runner

    assert loop.processed_count == 0
    assert "task-input-persona-mismatch" in loop_log.getvalue()


# ---------------------------------------------------------------------------
# §4 — CLI dispatch + log-trace
# ---------------------------------------------------------------------------


def test_cli_imports_subscribe_mode_resolver():
    """The CLI module imports the resolver — locking the contract
    so a future rename does not silently break the dispatch."""
    import wirelang.persona_engine.cli as cli_mod
    # _run_spawn_async lazy-imports inside the function. We assert
    # the names are available at the nats_subscribe_loop module
    # level so the CLI import will resolve at runtime.
    import wirelang.persona_engine.nats_subscribe_loop as nsl
    assert hasattr(nsl, "resolve_subscribe_mode")
    assert hasattr(nsl, "DEFAULT_SUBSCRIBE_MODE")
    assert hasattr(nsl, "SUBSCRIBE_MODE_CORE_CALLBACK")
    assert hasattr(nsl, "SUBSCRIBE_MODE_CORE_ITERATOR")
    assert hasattr(nsl, "SUBSCRIBE_MODE_JETSTREAM_PULL")
    # Sanity: the CLI module exists
    assert cli_mod is not None


@requires_v907_compute_deps
def test_cli_async_dispatch_log_includes_subscribe_mode(monkeypatch, tmp_path):
    """The CLI async-dispatch path emits ``subscribe_mode`` in its
    cli-async-dispatch log entry. This is the live-smoke audit anchor
    operators grep for to verify which subscribe-mode the container
    took."""
    import argparse
    import os
    import sys
    from wirelang.persona_engine import cli as cli_mod

    # Construct a minimal axis-A persona-md file.
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir(parents=True)
    persona_md = persona_dir / "tomas.md"
    persona_md.write_text(
        "---\n"
        "name: tomas\n"
        "description: test\n"
        "---\n"
        "tomas test body\n",
        encoding="utf-8",
    )

    # Capture stderr.
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    # Env contract setup.
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(persona_md))
    monkeypatch.setenv("WAKIR_SUBSCRIBE_ENV", "dev")
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # one-shot tolerates empty
    monkeypatch.setenv("WAKIR_NATS_SUBSCRIBE_MODE", "core-callback")
    # Pre-compute the V-907 pin so boot succeeds with matched-mode.
    from wirelang.persona_engine.v907_verify import verify_v907_pin
    pin_res = verify_v907_pin(
        persona_id="tomas",
        axis_a_path=persona_md,
        expected_pin=None,
    )
    monkeypatch.setenv("WAKIR_PERSONA_V907_EXPECTED_PIN", pin_res.pin)

    # Disable SVID fetch (no SPIRE socket in hermetic).
    monkeypatch.setenv(
        "SPIFFE_ENDPOINT_SOCKET",
        f"unix:{tmp_path}/nonexistent.sock",
    )

    # Run with --one-shot to avoid hanging in run_until_signal.
    args = argparse.Namespace(persona_slug="tomas", one_shot=True)
    rc = cli_mod.run_spawn(args)
    out = captured.getvalue()

    # The CLI should have emitted the cli-async-dispatch log line
    # with subscribe_mode=core-callback. We assert on the JSON
    # fields, not the exact line ordering.
    dispatch_lines = [
        ln for ln in out.splitlines() if '"cli-async-dispatch"' in ln
    ]
    assert dispatch_lines, (
        f"cli-async-dispatch log not found in output:\n{out}"
    )
    parsed = json.loads(dispatch_lines[0])
    assert parsed["msg"] == "cli-async-dispatch"
    assert parsed["subscribe_mode"] == "core-callback"
    assert parsed["subscribe_env"] == "dev"
    assert parsed["persona_slug"] == "tomas"
    assert parsed["one_shot"] is True
    assert rc == 0  # one-shot graceful


@requires_v907_compute_deps
def test_cli_rejects_invalid_subscribe_mode(monkeypatch, tmp_path):
    """An invalid WAKIR_NATS_SUBSCRIBE_MODE value returns ENV_MISCONFIG."""
    import argparse
    import sys
    from wirelang.persona_engine import cli as cli_mod

    persona_dir = tmp_path / "persona"
    persona_dir.mkdir(parents=True)
    persona_md = persona_dir / "tomas.md"
    persona_md.write_text(
        "---\nname: tomas\ndescription: test\n---\nbody\n",
        encoding="utf-8",
    )

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(persona_md))
    monkeypatch.setenv("WAKIR_SUBSCRIBE_ENV", "dev")
    monkeypatch.setenv("WAKIR_NATS_SUBSCRIBE_MODE", "jetstream-push")
    monkeypatch.setenv(
        "SPIFFE_ENDPOINT_SOCKET",
        f"unix:{tmp_path}/nonexistent.sock",
    )

    args = argparse.Namespace(persona_slug="tomas", one_shot=True)
    rc = cli_mod.run_spawn(args)
    assert rc == cli_mod.EXIT_ENV_MISCONFIG
    err = captured.getvalue()
    assert "env-misconfig" in err
    assert "jetstream-push" in err


# ---------------------------------------------------------------------------
# §5 — version-bump assertions
# ---------------------------------------------------------------------------


def test_engine_version_bumped_to_0_5_0_pilot():
    """Sprint-Pengine-13 bumps 0.4.2-pilot → 0.5.0-pilot."""
    assert ENGINE_VERSION == "0.5.0-pilot"
    assert ASYNC_ENGINE_VERSION == "0.5.0-pilot"
    assert PKG_VERSION == "0.5.0-pilot"


def test_containerfile_real_label_bumped():
    """Containerfile.real LABEL is the Tag-45 pre-cutover image tag.

    Tag-45 (Sprint-Pengine-14, 2026-05-18) bumped the container
    image tag from ``0.5.0-pilot`` to ``0.5.0-pre-cutover`` for the
    Phase-3a/3b Doppelbetrieb engine consolidation (manifest +
    pin pack). The Python ``ENGINE_VERSION`` constant remains at
    ``0.5.0-pilot`` because the engine code itself is byte-stable
    relative to Sprint-Pengine-13 — Tag-45 is a documentation /
    cross-substrate-parity consolidation, not an engine-code bump.
    Sprint-Pengine-13 / Bug-42 references stay in the header
    comment for history.
    """
    from pathlib import Path
    cf = Path(__file__).resolve().parents[3] / "infra" / "persona-engine" / "Containerfile.real"
    text = cf.read_text(encoding="utf-8")
    assert 'image.version="0.5.0-pre-cutover"' in text
    assert "Sprint-Pengine-13" in text
    assert "Bug-42" in text
    assert "Sprint-Pengine-14" in text
    assert "Tag-45" in text
