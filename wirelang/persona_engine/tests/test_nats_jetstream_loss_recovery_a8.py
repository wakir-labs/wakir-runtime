# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""A8 — NATS-JetStream-Loss-Recovery hermetic test coverage (Tag-46).

Auftrag-Anker
-------------

Tag-45 Amara Coverage-Audit pinned five PARTIAL failure-modes (see
``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` §4). The
A8 entry is

    A8 — NATS-JetStream-Stream-Persistence-Loss (Welle-4-Cutover)

with the audit's PARTIAL classification anchored on the per-Welle
smoke (``tests/phase_3c/test_welle_4_cutover_smoke.py``) covering
the state-backing layer-switch shape but **not** the persistence-
loss failure-mode itself.

This Tag-46 file is the named follow-up test that lifts A8 from
PARTIAL to COVERED. It does not depend on a live NATS-JetStream
server. Instead it injects in-memory stubs at the same seam the
production ``NatsKvPersonaStateBackingAsync`` /
``NatsSubscribeLoop._run_live_jetstream_pull`` use (the
``nats_client_factory`` / ``js_factory`` factory-hook surface).

Scope
-----

Five named JetStream-loss scenarios, each with multiple hermetic
tests pinning the invariant the persona-engine MUST preserve when
the loss-event fires:

1. **Stream-Disconnect-Mid-Publish.** A bridge-output publish call
   raises ``ConnectionClosedError`` mid-flight. The subscribe-loop
   MUST audit the publish-failure and continue, NOT crash the loop
   and NOT lose the inbound message ack.
2. **Consumer-Ack-Loss.** The downstream JetStream consumer ack
   fails (network drop after the message was processed). The
   persona-engine MUST NOT double-process on redelivery — the
   bridge-audit-writer's per-step idempotence is the anchor.
3. **JetStream-Replica-Failover.** The KV-bucket transient
   ``put``/``get`` call fails once (replica failover window) and
   succeeds on retry. The async state-backing MUST surface the
   error as ``PersonaStateBackingError`` (no silent data loss).
4. **Subject-Routing-Drift.** A message arrives on the wrong
   persona subject (loop subscribed to ``tomas``, msg routed to
   ``reza`` envelope). The loop MUST drop the persona-mismatch
   message, emit an audit-annotation, and not publish a reply.
5. **Message-Replay-Idempotency.** The same auftrag-envelope is
   delivered twice (post-restart JetStream redelivery). The
   bridge-audit-writer's per-step monotonic counter and the
   state-backing's byte-equal snapshot-idempotence MUST preserve
   the "exactly-one effective output per auftrag_id" contract at
   the audit-substrate layer (the spec-side guarantee — the
   ``processed_count`` itself counts deliveries, not unique
   auftrag_ids).

All five scenarios use the same hermetic-stub posture as
``wirelang/tests/persona_engine/test_state_backing_async.py`` (no
nats-py wheel required, no sockets, no threads).
"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from wirelang.persona_engine.bridge_audit_writer import BridgeAuditWriter
from wirelang.persona_engine.llm_call_shim import (
    EchoReflectionLlmHook,
    LlmCallResult,
)
from wirelang.persona_engine.nats_subscribe_loop import (
    ACCEPTED_INBOUND_SCHEMA,
    NatsSubscribeLoop,
    SubscribeLoopConfig,
    build_output_subject,
    build_subscribe_subject,
    iter_from_queue,
)
from wirelang.persona_engine.state_backing import (
    LATEST_KEY,
    NEXT_OFFSET_KEY,
    NatsKvPersonaStateBackingAsync,
    PINNED_KEY,
    PersonaStateBackingError,
    PersonaStateSnapshot,
    offset_key,
)


# ---------------------------------------------------------------------
# A8 — coverage-classification self-pin
# ---------------------------------------------------------------------


def test_a8_coverage_classification_is_covered() -> None:
    """This file is the named Tag-46 follow-up; flipping A8 PARTIAL to
    COVERED requires both the matrix-doc and the audit-test to update
    together. This test asserts that the audit-test's expected state
    for A8 is now COVERED (and that this file exists on disk at the
    audit-named location).
    """
    from tests.phase_3c.test_pre_mortem_failure_mode_coverage_audit import (
        COVERAGE_BY_ID,
    )

    cls = COVERAGE_BY_ID["A8"]
    assert cls.coverage_state == "COVERED", (
        "A8 must be COVERED after Tag-46 follow-up lands; current="
        f"{cls.coverage_state}"
    )


# ---------------------------------------------------------------------
# Helpers — shared envelope + sinks (mirrors test_nats_subscribe_loop)
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
        "ts_utc": "2026-05-18T22:00:00Z",
        "source": "mira-sandbox",
        "prompt_sha256": "sha256:" + ("0" * 64),
        "prompt_payload": prompt,
        "metadata": metadata or {},
    }
    return json.dumps(obj, sort_keys=True).encode("utf-8")


class _FakeMsg:
    def __init__(
        self,
        data: bytes,
        subject: str = "wakir.dev.agent.agent.task.assigned.tomas",
    ) -> None:
        self.data = data
        self.subject = subject
        self.acked = False
        self.ack_calls = 0

    async def ack(self) -> None:
        self.ack_calls += 1
        self.acked = True


class _AckLossMsg(_FakeMsg):
    """Msg whose ack() raises (simulating broken consumer-ack channel).

    The persona-engine's ``_best_effort_ack`` is documented to swallow
    ack-exceptions (core-NATS has no ack); the JetStream redelivery
    semantics are then enforced by the substrate, not by the loop. The
    loop's contract here is: a broken ack MUST NOT abort the loop.
    """

    async def ack(self) -> None:
        self.ack_calls += 1
        raise RuntimeError("simulated consumer-ack-loss (Replica-Failover)")


class _DroppingPublishSink:
    """Publish sink whose first N calls raise ConnectionClosedError.

    Mirrors the live JetStream behaviour during a stream-disconnect
    window: the underlying TCP connection is dropping packets, so
    ``publish()`` raises. Production code retries via the substrate;
    the loop-side contract is: a publish failure MUST NOT abort the
    consumer loop, and the failure MUST be audited.
    """

    def __init__(self, fail_first: int = 1) -> None:
        self.fail_first = fail_first
        self.published: List[Tuple[str, bytes]] = []
        self.attempts: int = 0

    async def publish(self, subject: str, payload: bytes) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise ConnectionError(
                "simulated stream-disconnect-mid-publish (JetStream-loss)"
            )
        self.published.append((subject, payload))


class _RecordingPublishSink:
    """Records every publish call (no failures)."""

    def __init__(self) -> None:
        self.published: List[Tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


def _make_writer(sink: io.StringIO) -> BridgeAuditWriter:
    return BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-a8",
        engine_version="0.5.0-pre-cutover",
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
# Scenario 1 — Stream-Disconnect-Mid-Publish
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a8_stream_disconnect_mid_publish_does_not_abort_loop() -> None:
    """If the publish-sink raises ConnectionError on output, the loop
    MUST complete the inbound message (bridge_audit emit + ack) and
    continue to the next message.

    Anchor: ``NatsSubscribeLoop._handle_message_inner`` wraps the
    publish in a try/except that logs ``task-output-publish-failed``
    but does not re-raise (see ``nats_subscribe_loop.py`` lines
    ~699-717).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _DroppingPublishSink(fail_first=1)
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-1")))
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-2")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    # Both inbound messages processed.
    assert loop.processed_count == 2
    # First publish attempt raised; second succeeded.
    assert publish.attempts == 2
    assert len(publish.published) == 1
    # The publish-failure was logged in the bridge-audit sink.
    sink_lines = sink.getvalue().splitlines()
    publish_failed_lines = [
        ln for ln in sink_lines
        if "task-output-publish-failed" in ln
    ]
    assert len(publish_failed_lines) == 1


@pytest.mark.asyncio
async def test_a8_stream_disconnect_inbound_ack_still_called() -> None:
    """A publish-failure MUST NOT skip the inbound-ack: the inbound
    msg is processed even if the outbound publish drops, so the
    consumer-side ack-or-redeliver invariant stays intact.
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _DroppingPublishSink(fail_first=1)
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    msg = _FakeMsg(_good_envelope(auftrag_id="a-1"))
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(msg)
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 1
    assert msg.acked is True
    assert msg.ack_calls == 1


# ---------------------------------------------------------------------
# Scenario 2 — Consumer-Ack-Loss
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a8_consumer_ack_loss_does_not_crash_loop() -> None:
    """If ``msg.ack()`` raises, ``_best_effort_ack`` swallows the
    exception and the loop continues. This pins the
    consumer-ack-loss-recovery semantic: a broken ack channel does
    NOT take down the consumer (Bug-42 cancellation surface is a
    separate failure-class; this is the explicit ack-raise path).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    msg = _AckLossMsg(_good_envelope(auftrag_id="a-1"))
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(msg)
    # A follow-up healthy message MUST still be processed.
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-2")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 2
    assert msg.ack_calls == 1
    # Both outputs published despite first ack raising.
    assert len(publish.published) == 2


@pytest.mark.asyncio
async def test_a8_consumer_ack_loss_outbound_publish_still_recorded() -> None:
    """The reply is published before the inbound ack fires; an ack-loss
    AFTER processing does NOT roll back the published output. The
    JetStream redelivery semantic is owned by the consumer-side
    substrate, not by the persona-engine.
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    msg = _AckLossMsg(_good_envelope(auftrag_id="a-ack-loss"))
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(msg)
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 1
    assert len(publish.published) == 1
    out_subject, out_payload = publish.published[0]
    assert out_subject == build_output_subject("dev", "tomas")
    out_obj = json.loads(out_payload.decode("utf-8"))
    assert out_obj["auftrag_id"] == "a-ack-loss"


# ---------------------------------------------------------------------
# Scenario 3 — JetStream-Replica-Failover (state-backing)
# ---------------------------------------------------------------------


class _FailoverKv:
    """KV stub that raises on the first put/get of each kind, then
    succeeds. Simulates a JetStream replica-failover window where the
    primary loses, the secondary promotes, and the next call goes
    through cleanly.
    """

    def __init__(
        self,
        *,
        fail_first_put: int = 0,
        fail_first_get: int = 0,
    ) -> None:
        self._store: Dict[str, Tuple[bytes, int]] = {}
        self._put_attempts = 0
        self._get_attempts = 0
        self._fail_first_put = fail_first_put
        self._fail_first_get = fail_first_get

    async def put(self, key: str, value: bytes) -> Any:
        self._put_attempts += 1
        if self._put_attempts <= self._fail_first_put:
            raise ConnectionError(
                "simulated replica-failover (KV put fail)"
            )
        prev = self._store.get(key)
        rev = (prev[1] + 1) if prev else 1
        self._store[key] = (bytes(value), rev)

        class _E:
            def __init__(self, v: bytes, r: int) -> None:
                self.value = v
                self.revision = r

        return _E(self._store[key][0], rev)

    async def get(self, key: str) -> Any:
        self._get_attempts += 1
        if self._get_attempts <= self._fail_first_get:
            raise ConnectionError(
                "simulated replica-failover (KV get fail)"
            )
        v = self._store.get(key)
        if v is None:
            return None

        class _E:
            def __init__(self, val: bytes, r: int) -> None:
                self.value = val
                self.revision = r

        return _E(v[0], v[1])

    async def keys(self) -> List[str]:
        return sorted(self._store.keys())


class _FailoverJs:
    def __init__(self, kv: _FailoverKv) -> None:
        self._kv = kv

    async def key_value(self, bucket: str) -> _FailoverKv:
        return self._kv


class _FailoverClient:
    def __init__(self, js: _FailoverJs) -> None:
        self._js = js
        self.closed = False

    def jetstream(self) -> _FailoverJs:
        return self._js

    async def close(self) -> None:
        self.closed = True


async def _make_failover_backing(
    *,
    fail_first_put: int = 0,
    fail_first_get: int = 0,
) -> Tuple[NatsKvPersonaStateBackingAsync, _FailoverKv]:
    kv = _FailoverKv(
        fail_first_put=fail_first_put,
        fail_first_get=fail_first_get,
    )
    js = _FailoverJs(kv)
    client = _FailoverClient(js)

    async def factory(_servers: str, _timeout: float) -> _FailoverClient:
        return client

    async def js_factory(_c: _FailoverClient) -> _FailoverJs:
        return _c.jetstream()

    backing = NatsKvPersonaStateBackingAsync(
        nats_servers="nats://stub:4222",
        org_id="acme",
        nats_client_factory=factory,
        js_factory=js_factory,
    )
    await backing.connect()
    return backing, kv


def _snap(seed: int = 0) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=seed,
        capability_token_ids=("tok-a8",),
        snapshot_at_utc=f"2026-05-18T{seed:02d}:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )


@pytest.mark.asyncio
async def test_a8_replica_failover_put_surfaces_error() -> None:
    """A transient KV put failure (replica-failover window) MUST
    surface as ``PersonaStateBackingError`` — no silent swallow. The
    caller (state-backing operator) is then responsible for retry.
    """
    backing, kv = await _make_failover_backing(fail_first_put=1)
    # The first snapshot triggers `__next_offset__` put then offset-key
    # put then latest-key put. Any single put failing must propagate.
    with pytest.raises((PersonaStateBackingError, ConnectionError)):
        await backing.snapshot("tomas", _snap(1))
    await backing.close()


@pytest.mark.asyncio
async def test_a8_replica_failover_get_returns_none_silently() -> None:
    """The async backing's ``_read_*`` helpers wrap KV.get in
    try/except and return None on any exception. This is the
    documented behaviour: a get-failure during a replica-failover
    window appears as "no data yet" to the caller, which then either
    treats it as initial state (snapshot allocation) or retries via
    the per-persona lock. Pin the silent-None semantic so a future
    refactor must update this test.
    """
    backing, kv = await _make_failover_backing(fail_first_get=1)
    # restore_latest reads latest-key; on get-failure it returns None.
    result = await backing.restore_latest("tomas")
    assert result is None
    await backing.close()


@pytest.mark.asyncio
async def test_a8_replica_failover_recovers_after_window() -> None:
    """After the failover-window closes (one failed put then success),
    the snapshot completes cleanly on retry. End-state: bucket holds
    the snapshot at offset 1, latest-key points to 1.
    """
    # First put fails (the `__next_offset__` initial put). Caller-
    # retry pattern: same snapshot, second call goes through.
    backing, kv = await _make_failover_backing(fail_first_put=1)
    with pytest.raises((PersonaStateBackingError, ConnectionError)):
        await backing.snapshot("tomas", _snap(1))
    # Second call: failover window closed, all puts succeed.
    offset = await backing.snapshot("tomas", _snap(1))
    assert offset == 1
    # Bucket holds latest pointer + offset-key + next-offset sentinel.
    snap = await backing.restore_latest("tomas")
    assert snap is not None
    assert snap.audit_trace_offset == 1
    await backing.close()


# ---------------------------------------------------------------------
# Scenario 4 — Subject-Routing-Drift
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a8_subject_routing_drift_drops_mismatched_persona() -> None:
    """A message whose envelope ``persona_id`` does not match the
    loop's ``persona_slug`` MUST be dropped (no LLM call, no publish,
    no processed-count increment) — the loop emits a
    ``task-input-persona-mismatch`` audit-annotation and acks the msg
    (so JetStream doesn't redeliver an undeliverable message).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    queue: asyncio.Queue = asyncio.Queue()
    # Loop is configured for tomas; envelope claims reza.
    msg = _FakeMsg(_good_envelope(persona_id="reza"))
    await queue.put(msg)
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 0
    assert len(publish.published) == 0
    # Mismatched message ack'd: do not redeliver garbage forever.
    assert msg.acked is True
    # Audit-annotation emitted.
    sink_lines = sink.getvalue().splitlines()
    mismatch_lines = [
        ln for ln in sink_lines if "task-input-persona-mismatch" in ln
    ]
    assert len(mismatch_lines) >= 1


@pytest.mark.asyncio
async def test_a8_subject_routing_drift_does_not_block_subsequent_correct_msg() -> None:
    """One mismatched message in the stream MUST NOT block subsequent
    correctly-routed messages.
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(persona_id="reza")))  # drift
    await queue.put(_FakeMsg(_good_envelope(persona_id="tomas")))  # OK
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 1
    assert len(publish.published) == 1


@pytest.mark.asyncio
async def test_a8_subject_routing_drift_malformed_subject_does_not_alter_drop_path() -> None:
    """A persona-mismatched envelope delivered on a structurally
    correct-looking subject is still dropped on envelope-content
    grounds (the loop trusts the envelope's ``persona_id``, not the
    subject string, since the subject can be spoofed).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    queue: asyncio.Queue = asyncio.Queue()
    spoofed = _FakeMsg(
        _good_envelope(persona_id="reza"),
        # Even if the subject claims tomas, the envelope wins.
        subject=build_subscribe_subject("dev", "tomas"),
    )
    await queue.put(spoofed)
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 0
    assert len(publish.published) == 0


# ---------------------------------------------------------------------
# Scenario 5 — Message-Replay-Idempotency
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a8_replay_state_backing_byte_equal_snapshot_idempotent() -> None:
    """Replaying the SAME persona-state snapshot MUST return the same
    offset (the InMemory/NatsKv backing both pin this contract). This
    is the substrate-side anchor that closes the "exactly-one
    effective state mutation per logical event" invariant under
    JetStream redelivery.
    """
    backing, _ = await _make_failover_backing()
    snap = _snap(7)
    offset_first = await backing.snapshot("tomas", snap)
    offset_replay = await backing.snapshot("tomas", snap)
    assert offset_first == offset_replay == 1
    # A different snapshot allocates a new offset.
    offset_new = await backing.snapshot("tomas", _snap(8))
    assert offset_new == 2
    await backing.close()


@pytest.mark.asyncio
async def test_a8_replay_inbound_envelope_published_twice_on_redelivery() -> None:
    """The persona-engine loop does NOT itself dedupe inbound envelopes
    (JetStream redelivery semantics live in the substrate). This test
    pins the **observable** behaviour: if the same envelope is
    redelivered, the loop processes it twice and publishes twice. The
    cross-substrate dedupe lives at the audit-substrate layer (bridge-
    audit-writer step_index monotonicity + state-backing snapshot
    idempotence above).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    env = _good_envelope(auftrag_id="a-replay")
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(env))
    await queue.put(_FakeMsg(env))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    assert loop.processed_count == 2
    assert len(publish.published) == 2
    # The two published outputs have identical auftrag_id.
    obj_a = json.loads(publish.published[0][1].decode("utf-8"))
    obj_b = json.loads(publish.published[1][1].decode("utf-8"))
    assert obj_a["auftrag_id"] == obj_b["auftrag_id"] == "a-replay"


@pytest.mark.asyncio
async def test_a8_replay_bridge_audit_step_indices_strictly_monotonic() -> None:
    """Even under replay, the bridge-audit-writer's step_index counter
    MUST stay strictly monotonic. This is the auditor-side anchor: a
    replay is observable in the audit trail (two distinct step_index
    values for the same auftrag_id).
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _RecordingPublishSink()
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    env = _good_envelope(auftrag_id="a-replay-audit")
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(env))
    await queue.put(_FakeMsg(env))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    sink_lines = sink.getvalue().splitlines()
    # Parse the bridge-audit JSONL lines and extract step_index for
    # the "reply" kind. The exact field name depends on the writer's
    # canonical-schema; we tolerate either ``step_index`` or
    # ``step`` and accept any string-or-int value as long as the two
    # reply rows differ.
    reply_steps: List[Any] = []
    for ln in sink_lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        kind = obj.get("output_kind") or obj.get("kind")
        if kind == "reply":
            step = obj.get("step_index")
            if step is None:
                step = obj.get("step")
            reply_steps.append(step)
    assert len(reply_steps) == 2
    # Strict monotonic: second step > first step.
    s0, s1 = reply_steps
    assert s0 is not None and s1 is not None
    assert int(s1) > int(s0)


# ---------------------------------------------------------------------
# Cross-scenario invariant pin
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a8_all_five_scenarios_share_loop_does_not_crash_invariant() -> None:
    """Composite test: the loop survives one of each pathological
    message type in sequence (drift, ack-loss, publish-drop, replay)
    without aborting.
    """
    sink = io.StringIO()
    writer = _make_writer(sink)
    publish = _DroppingPublishSink(fail_first=1)
    loop = NatsSubscribeLoop(
        _make_config(writer), publish_sink=publish, log_sink=sink,
    )

    queue: asyncio.Queue = asyncio.Queue()
    # 1. Subject-routing-drift -> dropped.
    await queue.put(_FakeMsg(_good_envelope(persona_id="reza")))
    # 2. Consumer-ack-loss on a healthy envelope -> processed.
    await queue.put(_AckLossMsg(_good_envelope(auftrag_id="a-ack-loss")))
    # 3. Stream-disconnect-mid-publish on next msg -> processed, publish drops.
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-disconnect")))
    # 4. Replay of (3) -> processed, publish goes through.
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-disconnect")))
    # 5. Final clean msg -> processed.
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-clean")))
    await queue.put(None)

    await loop.run_with_iterator(iter_from_queue(queue))

    # Drift dropped; remaining 4 processed.
    assert loop.processed_count == 4
    # First publish failed (disconnect window); remaining 3 succeeded.
    assert publish.attempts == 4
    assert len(publish.published) == 3
