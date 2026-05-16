# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""NATS-Subscribe-Loop — Sprint-Pengine-10 OI-PEFR-6.

This module wires the Wakir-Runtime persona-engine to the
Bridge-Forward-Pipe (Tomás Sprint-10 Tag-6 spec
``wirelang/specs/bridge-forward-pipe-v1.md``).

Subscribe contract
------------------

The engine subscribes to the canonical subject

    wakir.<env>.agent.agent.task.assigned.<persona_slug>

where ``<env>`` is ``WAKIR_ENV`` (default ``dev``) and
``<persona_slug>`` is ``WAKIR_PERSONA_ID`` (default ``tomas``). One
message per Mira-side bridge-forward publish.

Per-message flow
----------------

1. The async subscribe-loop receives a NATS msg with JCS-canonical
   envelope (schema ``wakir.agent.task-assigned/1``).
2. Envelope is parsed via :class:`AuftragEnvelope` (re-import from
   ``wirelang.cli.bridge_forward``); structural-error -> drop +
   audit-emit ``task-input-malformed``.
3. FSM transition ``running`` -> ``processing-task`` (logged as a
   sub-state transition; the spec-FSM has no ``processing-task``
   formal state, so this is captured as an audit-annotation only).
4. The :class:`LlmCallHook` is invoked with the prompt; the result's
   ``reply_text`` is written via :class:`BridgeAuditWriter` as a
   ``reply`` engineering-output (so the Doppelbetrieb-Score-CLI
   ingests the response on the companion subject).
5. The reply is also published to NATS on
   ``wakir.<env>.agent.agent.task.output.<persona_slug>`` so live
   subscribers (e.g. operator dashboards) see the round-trip without
   waiting for the audit-substrate to forward.
6. NATS ack (msg.ack() if JetStream; no-op for core-pub-sub).
7. FSM sub-state ``processing-task`` -> ``running``.

Ack semantics
-------------

The Bridge-Forward-Pipe v1 uses **core NATS pub-sub** (not JetStream)
per the Tomás Sprint-10 Tag-6 spec §4.2. Core NATS does not require
ack — the subscribe-loop emits an **audit-ack** (a structured-log
record with ``msg=task-ack``) but does not call ``msg.ack()``. If the
substrate migrates to JetStream in Phase-3, the ack-path lights up via
``_ack_message()`` (a single method on this loop).

Hermetic-test surface
---------------------

The loop accepts a ``msg_iterator`` factory so tests inject a fake
NATS-msg stream. Production code wires ``msg_iterator`` to a real
``nats.aio.client.Subscription.messages`` async iterator; tests pass
an in-memory ``asyncio.Queue``-backed iterator. No ``nats-py`` import
at module-import time (the connection-side import is lazy at
``run_live()`` time).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    TextIO,
    Tuple,
)

from .bridge_audit_writer import BridgeAuditWriter
from .llm_call_shim import LlmCallHook, LlmCallResult
from .observability import PersonaEngineObservability


SUBSCRIBE_SUBJECT_TEMPLATE = (
    "wakir.{env}.agent.agent.task.assigned.{persona_slug}"
)

PUBLISH_OUTPUT_SUBJECT_TEMPLATE = (
    "wakir.{env}.agent.agent.task.output.{persona_slug}"
)

#: Schema-id we accept on inbound envelopes.
ACCEPTED_INBOUND_SCHEMA = "wakir.agent.task-assigned/1"

#: Schema-id we emit on the output publish.
OUTBOUND_OUTPUT_SCHEMA = "wakir.agent.task-output/1"

#: Persona-slug regex (matches the bridge-forward spec §3.2 grammar).
PERSONA_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _compute_subscribe_lag_seconds(ts_utc_str: str) -> Optional[float]:
    """Compute now-UTC minus envelope-ts_utc, in seconds.

    Accepts the RFC-3339 second-precision shape the engine emits
    (``YYYY-MM-DDTHH:MM:SSZ``). Returns ``None`` if the string fails
    to parse — the lag metric is best-effort; a malformed timestamp
    is logged through the audit substrate, not counted as zero-lag.
    """
    try:
        # Tolerate the trailing 'Z' with calendar.timegm-style parse.
        if ts_utc_str.endswith("Z"):
            t_struct = time.strptime(ts_utc_str, "%Y-%m-%dT%H:%M:%SZ")
        else:
            # Fall back to ISO-8601 fractional / offset form.
            t_struct = time.strptime(
                ts_utc_str.split("+")[0].split(".")[0],
                "%Y-%m-%dT%H:%M:%S",
            )
        import calendar
        envelope_epoch = calendar.timegm(t_struct)
        now_epoch = int(time.time())
        return float(now_epoch - envelope_epoch)
    except (ValueError, TypeError):
        return None


class _NullSpanCtx:
    """No-op span-context handle, used when no observability facade is wired."""

    def set_attribute(self, key: str, value: object) -> None:
        return None


@contextlib.contextmanager
def _null_span_cm():
    """Sync context manager that yields a :class:`_NullSpanCtx`.

    Used in :meth:`NatsSubscribeLoop._handle_message` when
    ``config.observability`` is ``None`` so the with-statement runs
    unchanged regardless of whether OTel is wired.
    """
    yield _NullSpanCtx()


# ---------------------------------------------------------------------------
# Subject helpers
# ---------------------------------------------------------------------------


def build_subscribe_subject(env: str, persona_slug: str) -> str:
    """Build the canonical agent.task.assigned subscribe subject."""
    if env not in ("dev", "staging", "prod"):
        raise ValueError(
            f"env must be one of dev/staging/prod, got {env!r}"
        )
    if not PERSONA_SLUG_RE.match(persona_slug):
        raise ValueError(
            f"persona_slug must match [a-z][a-z0-9_-]*, got {persona_slug!r}"
        )
    return SUBSCRIBE_SUBJECT_TEMPLATE.format(
        env=env, persona_slug=persona_slug
    )


def build_output_subject(env: str, persona_slug: str) -> str:
    """Build the canonical agent.task.output publish subject."""
    if env not in ("dev", "staging", "prod"):
        raise ValueError(
            f"env must be one of dev/staging/prod, got {env!r}"
        )
    if not PERSONA_SLUG_RE.match(persona_slug):
        raise ValueError(
            f"persona_slug must match [a-z][a-z0-9_-]*, got {persona_slug!r}"
        )
    return PUBLISH_OUTPUT_SUBJECT_TEMPLATE.format(
        env=env, persona_slug=persona_slug
    )


# ---------------------------------------------------------------------------
# Inbound message protocol
# ---------------------------------------------------------------------------


class InboundMessage(Protocol):
    """Duck-typed minimal NATS message surface the loop needs.

    Compatible with ``nats.aio.msg.Msg`` and the hermetic test fake.
    Only ``data`` and ``subject`` are touched; ``ack()`` is best-effort
    and tolerated to be absent (core pub-sub case).
    """

    data: bytes
    subject: str

    async def ack(self) -> None:
        ...


class PublishSink(Protocol):
    """Duck-typed NATS publish surface.

    Live binding: ``nats.aio.client.Client.publish`` async method.
    Hermetic test fake: an in-memory recorder.
    """

    async def publish(self, subject: str, payload: bytes) -> None:
        ...


# ---------------------------------------------------------------------------
# FSM sub-state tracker (audit-annotation only; the formal FSM stays at
# ``running``).
# ---------------------------------------------------------------------------


@dataclass
class TaskProcessingTracker:
    """Tracks current task processing sub-state for audit purposes.

    The formal :class:`LifecycleStateMachine` has no ``processing-task``
    state — spec §3.3 keeps the FSM minimal. We surface the per-task
    sub-state as audit-annotation events so the Doppelbetrieb-Vergleich
    can see when the engine is mid-flight.
    """

    current_auftrag_id: Optional[str] = None
    last_completed_auftrag_id: Optional[str] = None
    tasks_processed: int = 0
    tasks_malformed: int = 0
    tasks_failed_hook: int = 0

    def begin(self, auftrag_id: str) -> None:
        self.current_auftrag_id = auftrag_id

    def complete(self, auftrag_id: str) -> None:
        self.last_completed_auftrag_id = auftrag_id
        self.current_auftrag_id = None
        self.tasks_processed += 1

    def malformed(self) -> None:
        self.tasks_malformed += 1

    def hook_failed(self, auftrag_id: str) -> None:
        self.current_auftrag_id = None
        self.tasks_failed_hook += 1


# ---------------------------------------------------------------------------
# Envelope parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedAuftrag:
    """Parsed inbound auftrag envelope.

    Only the fields the loop consumes are captured here. Pass-through
    fields like ``metadata`` are preserved as-is in the output envelope
    for audit-trail completeness.
    """

    schema: str
    event_kind: str
    org_id: str
    persona_id: str
    auftrag_id: str
    ts_utc: str
    source: str
    prompt_sha256: str
    prompt_payload: str
    metadata: dict


class InboundEnvelopeError(ValueError):
    """Inbound envelope failed shape or schema validation."""


def parse_inbound_envelope(raw: bytes) -> ParsedAuftrag:
    """Parse a Bridge-Forward-Pipe inbound envelope.

    Validates:

    - JSON-decodable UTF-8 bytes.
    - ``schema == ACCEPTED_INBOUND_SCHEMA``.
    - ``event_kind == "agent.task.assigned"``.
    - All required string fields present and non-empty.
    """
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InboundEnvelopeError(f"json-decode-failed: {exc}") from exc
    if not isinstance(obj, dict):
        raise InboundEnvelopeError("envelope-not-object")
    schema = obj.get("schema")
    if schema != ACCEPTED_INBOUND_SCHEMA:
        raise InboundEnvelopeError(
            f"unexpected-schema: got {schema!r}, expected "
            f"{ACCEPTED_INBOUND_SCHEMA!r}"
        )
    event_kind = obj.get("event_kind")
    if event_kind != "agent.task.assigned":
        raise InboundEnvelopeError(
            f"unexpected-event_kind: got {event_kind!r}"
        )
    required = (
        "org_id",
        "persona_id",
        "auftrag_id",
        "ts_utc",
        "source",
        "prompt_sha256",
        "prompt_payload",
    )
    for field_name in required:
        val = obj.get(field_name)
        if not isinstance(val, str) or not val:
            raise InboundEnvelopeError(
                f"missing-or-empty-field: {field_name!r}"
            )
    metadata = obj.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InboundEnvelopeError("metadata-not-object")
    return ParsedAuftrag(
        schema=schema,
        event_kind=event_kind,
        org_id=obj["org_id"],
        persona_id=obj["persona_id"],
        auftrag_id=obj["auftrag_id"],
        ts_utc=obj["ts_utc"],
        source=obj["source"],
        prompt_sha256=obj["prompt_sha256"],
        prompt_payload=obj["prompt_payload"],
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Output envelope (sent on agent.task.output subject)
# ---------------------------------------------------------------------------


def build_output_envelope(
    *,
    org_id: str,
    persona_id: str,
    auftrag_id: str,
    prompt_sha256: str,
    reply_text: str,
    reply_sha256: str,
    hook_kind: str,
    ts_utc: str,
    engine_version: str,
    v907_pin: str,
    session_id: str,
    step_index: int,
    metadata: dict,
) -> bytes:
    """Build the JCS-canonical output envelope and return UTF-8 bytes."""
    envelope = {
        "schema": OUTBOUND_OUTPUT_SCHEMA,
        "event_kind": "agent.task.output",
        "org_id": org_id,
        "persona_id": persona_id,
        "auftrag_id": auftrag_id,
        "ts_utc": ts_utc,
        "prompt_sha256": prompt_sha256,
        "reply_payload": reply_text,
        "reply_sha256": reply_sha256,
        "hook_kind": hook_kind,
        "engine_version": engine_version,
        "v907_pin": v907_pin,
        "session_id": session_id,
        "step_index": step_index,
        "metadata": dict(metadata),
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Subscribe-loop
# ---------------------------------------------------------------------------


@dataclass
class SubscribeLoopConfig:
    """Subscribe-loop construction parameters."""

    env: str
    persona_slug: str
    org_id: str
    bridge_writer: BridgeAuditWriter
    hook: LlmCallHook
    tracker: TaskProcessingTracker = field(default_factory=TaskProcessingTracker)
    publish_output: bool = True
    #: Sprint-SRE Tag-15 — optional observability facade. When set, the
    #: loop records ``persona_engine.subscribe.lag_seconds`` histograms
    #: per inbound message (lag = now-utc minus ts_utc from the
    #: envelope, in seconds) and wraps each handle_message call in a
    #: ``persona_engine.subscribe.handle_message`` span. Default is
    #: ``None`` so existing call sites (and hermetic tests that pass
    #: their own loops in) keep their byte-stable behaviour.
    observability: Optional[PersonaEngineObservability] = None


class NatsSubscribeLoop:
    """Async subscribe-loop owner.

    Two run modes:

    - :meth:`run_with_iterator` — consume an :class:`AsyncIterator` of
      :class:`InboundMessage`. Hermetic-test entry point.
    - :meth:`run_live` — lazy-import ``nats-py``, connect, subscribe,
      drive the iterator-mode internally. Production entry point.

    The loop is single-instance per persona; the engine owns one
    instance from :meth:`AsyncPersonaEngine.set_subscribe_loop` and
    spawns one asyncio.Task running it.
    """

    def __init__(
        self,
        config: SubscribeLoopConfig,
        *,
        publish_sink: Optional[PublishSink] = None,
        log_sink: Optional[TextIO] = None,
    ) -> None:
        self.config = config
        self.publish_sink = publish_sink
        self.log_sink = log_sink
        self._stop_event: Optional[asyncio.Event] = None
        self._processed_count = 0

    # ------------------------------------------------------------------

    def _log(self, payload: dict) -> None:
        if self.log_sink is None:
            return
        payload.setdefault("ts_utc", _utc_now_rfc3339())
        payload.setdefault("component", "nats-subscribe-loop")
        self.log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self.log_sink.flush()

    # ------------------------------------------------------------------

    @property
    def processed_count(self) -> int:
        return self._processed_count

    def request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    # ------------------------------------------------------------------

    async def _handle_message(self, msg: InboundMessage) -> None:
        if self.config.observability is not None:
            span_cm = self.config.observability.span(
                "persona_engine.subscribe.handle_message",
                attributes={"subject": getattr(msg, "subject", "")},
            )
        else:
            span_cm = _null_span_cm()
        with span_cm as span_ctx:
            await self._handle_message_inner(msg, span_ctx)

    async def _handle_message_inner(
        self, msg: InboundMessage, span_ctx: Any
    ) -> None:
        try:
            parsed = parse_inbound_envelope(msg.data)
        except InboundEnvelopeError as exc:
            self.config.tracker.malformed()
            self.config.bridge_writer.emit(
                output_kind="audit_annotation",
                payload=(
                    f"task-input-malformed reason={exc} "
                    f"subject={msg.subject}"
                ).encode("utf-8"),
            )
            self._log({
                "level": "WARN",
                "msg": "task-input-malformed",
                "reason": str(exc),
                "subject": msg.subject,
            })
            await self._best_effort_ack(msg)
            return

        if parsed.persona_id != self.config.persona_slug:
            self.config.bridge_writer.emit(
                output_kind="audit_annotation",
                payload=(
                    f"task-input-persona-mismatch "
                    f"expected={self.config.persona_slug} "
                    f"got={parsed.persona_id}"
                ).encode("utf-8"),
            )
            self._log({
                "level": "WARN",
                "msg": "task-input-persona-mismatch",
                "expected": self.config.persona_slug,
                "got": parsed.persona_id,
            })
            await self._best_effort_ack(msg)
            return

        # Subscribe-lag metric: difference between the envelope's
        # ts_utc and the loop's dispatch time. Capture in seconds.
        if self.config.observability is not None:
            lag_seconds = _compute_subscribe_lag_seconds(parsed.ts_utc)
            if lag_seconds is not None:
                self.config.observability.record_subscribe_lag(
                    lag_seconds=lag_seconds,
                    subject=getattr(msg, "subject", ""),
                )
            if hasattr(span_ctx, "set_attribute"):
                span_ctx.set_attribute("auftrag_id", parsed.auftrag_id)
                span_ctx.set_attribute("persona_id", parsed.persona_id)

        self.config.tracker.begin(parsed.auftrag_id)
        self.config.bridge_writer.emit(
            output_kind="audit_annotation",
            payload=(
                f"task-processing-begin auftrag_id={parsed.auftrag_id} "
                f"prompt_sha256={parsed.prompt_sha256} "
                f"source={parsed.source}"
            ).encode("utf-8"),
        )
        self._log({
            "level": "INFO",
            "msg": "task-processing-begin",
            "auftrag_id": parsed.auftrag_id,
            "prompt_sha256": parsed.prompt_sha256,
            "source": parsed.source,
        })

        try:
            result: LlmCallResult = self.config.hook.call(
                persona_id=parsed.persona_id,
                auftrag_id=parsed.auftrag_id,
                prompt_payload=parsed.prompt_payload,
            )
        except Exception as exc:  # pragma: no cover - hook-defined
            self.config.tracker.hook_failed(parsed.auftrag_id)
            self.config.bridge_writer.emit(
                output_kind="audit_annotation",
                payload=(
                    f"task-hook-failed auftrag_id={parsed.auftrag_id} "
                    f"reason={exc!r}"
                ).encode("utf-8"),
            )
            self._log({
                "level": "ERROR",
                "msg": "task-hook-failed",
                "auftrag_id": parsed.auftrag_id,
                "reason": repr(exc),
            })
            await self._best_effort_ack(msg)
            return

        # Emit the reply through the BridgeAuditWriter as a real
        # engineering-output ("reply" kind). This is the substrate the
        # Doppelbetrieb-Score-CLI compares.
        reply_event = self.config.bridge_writer.emit(
            output_kind="reply",
            payload=result.reply_text.encode("utf-8"),
            ts_utc=result.ts_utc,
        )

        # Optionally publish on the output-subject (live-NATS-loop).
        if self.config.publish_output and self.publish_sink is not None:
            output_subject = build_output_subject(
                self.config.env, self.config.persona_slug,
            )
            output_envelope = build_output_envelope(
                org_id=self.config.org_id,
                persona_id=parsed.persona_id,
                auftrag_id=parsed.auftrag_id,
                prompt_sha256=parsed.prompt_sha256,
                reply_text=result.reply_text,
                reply_sha256=result.reply_sha256,
                hook_kind=result.hook_kind,
                ts_utc=result.ts_utc,
                engine_version=self.config.bridge_writer.engine_version,
                v907_pin=self.config.bridge_writer.v907_pin,
                session_id=self.config.bridge_writer.session_id,
                step_index=reply_event.step_index,
                metadata=parsed.metadata,
            )
            try:
                await self.publish_sink.publish(
                    output_subject, output_envelope,
                )
                self._log({
                    "level": "INFO",
                    "msg": "task-output-published",
                    "auftrag_id": parsed.auftrag_id,
                    "subject": output_subject,
                    "reply_sha256": result.reply_sha256,
                })
            except Exception as exc:  # pragma: no cover - network
                self._log({
                    "level": "ERROR",
                    "msg": "task-output-publish-failed",
                    "auftrag_id": parsed.auftrag_id,
                    "subject": output_subject,
                    "reason": repr(exc),
                })

        self.config.tracker.complete(parsed.auftrag_id)
        self._processed_count += 1
        self.config.bridge_writer.emit(
            output_kind="audit_annotation",
            payload=(
                f"task-processing-complete auftrag_id={parsed.auftrag_id} "
                f"reply_sha256={result.reply_sha256} "
                f"tasks_processed={self.config.tracker.tasks_processed}"
            ).encode("utf-8"),
        )
        self._log({
            "level": "INFO",
            "msg": "task-processing-complete",
            "auftrag_id": parsed.auftrag_id,
            "reply_sha256": result.reply_sha256,
            "tasks_processed": self.config.tracker.tasks_processed,
        })

        await self._best_effort_ack(msg)

    async def _best_effort_ack(self, msg: InboundMessage) -> None:
        ack = getattr(msg, "ack", None)
        if ack is None:
            return
        try:
            res = ack()
            if asyncio.iscoroutine(res):
                await res
        except Exception:  # pragma: no cover - core-pubsub has no ack
            pass

    # ------------------------------------------------------------------

    async def run_with_iterator(
        self,
        msg_iter: AsyncIterator[InboundMessage],
        *,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Drive the loop from an externally-supplied async iterator.

        The iterator is consumed until either:

        - It is exhausted (``StopAsyncIteration``).
        - ``stop_event`` is set (the engine signals shutdown).
        - The owning task is cancelled.
        """
        self._stop_event = stop_event or asyncio.Event()
        try:
            while not self._stop_event.is_set():
                # Pull next msg with a small wait so we honour
                # stop_event without blocking indefinitely.
                try:
                    msg = await asyncio.wait_for(
                        msg_iter.__anext__(), timeout=0.5,
                    )
                except asyncio.TimeoutError:
                    continue
                except StopAsyncIteration:
                    return
                await self._handle_message(msg)
        except asyncio.CancelledError:
            return

    async def run_live(
        self,
        *,
        nats_url: str,
        token: Optional[str] = None,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:  # pragma: no cover - live binding exercised by SSH-smoke
        """Production entry: lazy-import nats-py, connect, subscribe, run.

        Hermetic tests should use :meth:`run_with_iterator` with an
        in-memory fake instead.
        """
        import nats  # type: ignore

        nc = await nats.connect(nats_url, token=token)
        try:
            self.publish_sink = nc  # nats.Client has async publish.
            subject = build_subscribe_subject(
                self.config.env, self.config.persona_slug,
            )
            sub = await nc.subscribe(subject)
            self._log({
                "level": "INFO",
                "msg": "subscribe-bound",
                "subject": subject,
                "nats_url": nats_url,
            })
            await self.run_with_iterator(
                sub.messages, stop_event=stop_event,
            )
        finally:
            await nc.drain()


# ---------------------------------------------------------------------------
# Iterator-from-queue helper (used by tests + run_live composition)
# ---------------------------------------------------------------------------


async def iter_from_queue(
    queue: "asyncio.Queue[InboundMessage]",
    *,
    sentinel: Any = None,
) -> AsyncIterator[InboundMessage]:
    """Yield messages from an asyncio.Queue; stop on ``sentinel``."""
    while True:
        item = await queue.get()
        if item is sentinel:
            return
        yield item


__all__ = [
    "ACCEPTED_INBOUND_SCHEMA",
    "InboundEnvelopeError",
    "InboundMessage",
    "NatsSubscribeLoop",
    "OUTBOUND_OUTPUT_SCHEMA",
    "ParsedAuftrag",
    "PUBLISH_OUTPUT_SUBJECT_TEMPLATE",
    "PublishSink",
    "SUBSCRIBE_SUBJECT_TEMPLATE",
    "SubscribeLoopConfig",
    "TaskProcessingTracker",
    "build_output_envelope",
    "build_output_subject",
    "build_subscribe_subject",
    "iter_from_queue",
    "parse_inbound_envelope",
]
