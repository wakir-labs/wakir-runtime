# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""OpenTelemetry instrumentation surface for the persona-engine
(Sprint-SRE Tag-15, Noa Bergstroem / SRE).

Design goals
------------

1. **No hard dependency on opentelemetry wheels.** The persona-engine
   container ships under a constrained wheel set (PEP-562 lazy-import
   discipline; see ``wirelang/persona_engine/__init__.py`` docstring).
   Adding mandatory ``opentelemetry-api`` + ``opentelemetry-sdk`` +
   ``opentelemetry-exporter-otlp`` deps would re-open the wheel-drift
   class of bugs that Sprint-Pengine-9 Bug-34 closed. Instead this
   module *probes* for ``opentelemetry.metrics`` and
   ``opentelemetry.trace`` at module-import time inside try/except
   shims and exposes a single :class:`PersonaEngineObservability`
   facade whose API stays identical whether the OTel SDK is installed
   or not. When OTel is missing every operation is a structured-JSON
   log line — the same audit-substrate the engine already uses — so
   Operators get *some* observability even on the slim image; when
   OTel is installed the same calls also drive real meters and spans.

2. **Single instrumentation seam per concern.** Six counters / one
   histogram per concern; no metric-sprawl. Spec:

   - ``persona_engine.spawn.latency_seconds`` (Histogram) — boot+spawn
     wall-clock from :meth:`PersonaEngine.boot` entry to first
     ``engineering-output-emission-first`` emit.
   - ``persona_engine.fsm.transitions_total`` (Counter, labels
     ``from_state``, ``to_state``, ``accepted``) — every FSM
     transition attempt; recovery_workflow R-phases label on top
     via the same counter through the ``trigger`` attribute.
   - ``persona_engine.subscribe.lag_seconds`` (Histogram) — wall-clock
     between ``ts_utc`` on the inbound auftrag envelope and the
     subscribe-loop's per-msg dispatch. The single primary subscribe-
     loop SLI.
   - ``persona_engine.v907.verify_duration_seconds`` (Histogram) —
     wall-clock of :func:`v907_verify.verify_v907_pin`. Detects
     persona-canonical-form import drift.
   - ``persona_engine.recovery.trigger_total`` (Counter, label
     ``trigger=<R1|R2|R3|R4>``, ``outcome=<success|failure>``) —
     per-phase recovery_workflow outcomes.
   - ``persona_engine.svid.fetch_failures_total`` (Counter, label
     ``fence_mode=<wheel-missing|fetch-failure>``) — Bug-40 fence
     count. Operators page on this when fence_mode flips to
     ``fetch-failure`` more than once per hour.

   Three trace spans:

   - ``persona_engine.boot`` — wraps :meth:`PersonaEngine.boot`.
   - ``persona_engine.spawn`` — wraps :meth:`PersonaEngine.spawn`.
   - ``persona_engine.subscribe.handle_message`` — wraps the per-
     message handler in :class:`NatsSubscribeLoop`.

3. **Correlation-IDs with SVID-Workload-ID.** When the engine has a
   resolved :class:`SvidFetchResult` (real or fenced), the SPIFFE-ID
   string is recorded as ``workload.spiffe_id`` attribute on every
   span and as a constant label on the meter resource (set once at
   :meth:`PersonaEngineObservability.bind_workload_identity`). This
   is the cross-system correlation key the audit-substrate and the
   OTel-pipeline share.

4. **Test-driven.** The hermetic test surface
   (``test_observability.py``) drives the facade with the no-OTel
   path and an injected in-memory exporter to assert metric semantics
   without binding to the real OTel SDK.

License
-------

BUSL-1.1 (parity with the rest of the persona-engine real-implementation
package; see ``wirelang/persona_engine/__init__.py`` header). The
``opentelemetry-*`` wheels probed at import time are Apache-2.0; that
license posture is compatible — see ``../LICENSE`` for the canonical
top-level Apache-2.0 + per-module BSL union expression.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Optional, TextIO


__all__ = [
    "PersonaEngineObservability",
    "MetricRecord",
    "SpanRecord",
    "is_otel_sdk_available",
    "structured_log_observability",
    "OTEL_ENV_VAR_ENABLED",
    "OTEL_ENV_VAR_SERVICE_NAME",
    "OTEL_ENV_VAR_EXPORTER_OTLP_ENDPOINT",
]


# ---------------------------------------------------------------------------
# Env-var contract (parity with `engine.py` env contract).
# ---------------------------------------------------------------------------

#: Master switch. Set to "1" / "true" / "yes" to enable OTel
#: instrumentation. Default off — engine ships safely without the
#: wheels installed and without a collector reachable.
OTEL_ENV_VAR_ENABLED = "WAKIR_PERSONA_OTEL_ENABLED"

#: OTel ``service.name`` resource attribute. Defaults to
#: ``wakir-persona-engine``; Operators override per-Org if they run
#: multiple engines in one trace-collector.
OTEL_ENV_VAR_SERVICE_NAME = "WAKIR_PERSONA_OTEL_SERVICE_NAME"

#: OTLP gRPC endpoint URL (e.g. ``http://otel-collector:4317``).
#: Mirrors the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var; we
#: read both, with the Wakir-prefixed name taking precedence so the
#: persona-engine container can be wired without inheriting other
#: OTel-aware processes' endpoint.
OTEL_ENV_VAR_EXPORTER_OTLP_ENDPOINT = "WAKIR_PERSONA_OTEL_OTLP_ENDPOINT"

#: Fallback to the canonical OTLP env var name; checked second.
STANDARD_OTLP_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# OTel availability probe.
# ---------------------------------------------------------------------------


def is_otel_sdk_available() -> bool:
    """Return ``True`` iff the ``opentelemetry-api`` wheel is importable.

    The check is intentionally narrow: the facade only needs the API
    package (``opentelemetry.metrics`` + ``opentelemetry.trace``) at
    runtime. The SDK + OTLP exporter are loaded lazily inside
    :meth:`PersonaEngineObservability._maybe_install_real_otel_pipeline`,
    so a deployment with API-only (which is what the no-collector
    fallback path looks like) still binds the no-op meter/tracer
    providers from the API package.
    """
    try:
        import opentelemetry.metrics  # noqa: F401
        import opentelemetry.trace  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# In-memory record dataclasses (hermetic test substrate).
# ---------------------------------------------------------------------------


@dataclass
class MetricRecord:
    """One metric emission. Captured by the in-memory recorder for tests."""

    metric_name: str
    metric_kind: str  # "counter" | "histogram"
    value: float
    attributes: Dict[str, str] = field(default_factory=dict)
    ts_utc: str = field(default_factory=_utc_now_rfc3339)


@dataclass
class SpanRecord:
    """One span lifecycle. Captured by the in-memory recorder for tests."""

    span_name: str
    duration_seconds: float
    attributes: Dict[str, str] = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error"
    error_message: Optional[str] = None
    ts_utc: str = field(default_factory=_utc_now_rfc3339)


# ---------------------------------------------------------------------------
# Sink protocol.
# ---------------------------------------------------------------------------


class _Sink:
    """Common sink interface for metric / span records.

    Two concrete sinks ship:

    - :class:`_StructuredLogSink` — writes JSON line records to the
      engine's existing audit log_sink. Always available; the no-OTel
      fallback.
    - :class:`_InMemorySink` — captures records in lists; the hermetic
      test fixture.

    The real OTel pipeline does **not** route through these sinks; it
    binds directly to ``opentelemetry.metrics.get_meter()`` and
    ``opentelemetry.trace.get_tracer()`` via the SDK. The structured-
    log sink keeps emitting in parallel so the audit substrate stays
    populated even when OTel is wired (cheap insurance).
    """

    def record_metric(self, rec: MetricRecord) -> None:  # pragma: no cover
        raise NotImplementedError

    def record_span(self, rec: SpanRecord) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _StructuredLogSink(_Sink):
    """Writes JSON-line records to a writable text sink."""

    log_sink: TextIO

    def record_metric(self, rec: MetricRecord) -> None:
        payload = {
            "ts_utc": rec.ts_utc,
            "component": "wakir-persona-engine",
            "level": "INFO",
            "msg": "otel-metric",
            "metric_name": rec.metric_name,
            "metric_kind": rec.metric_kind,
            "metric_value": rec.value,
            "attributes": dict(rec.attributes),
        }
        self.log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self.log_sink.flush()

    def record_span(self, rec: SpanRecord) -> None:
        payload = {
            "ts_utc": rec.ts_utc,
            "component": "wakir-persona-engine",
            "level": "INFO" if rec.status == "ok" else "WARN",
            "msg": "otel-span",
            "span_name": rec.span_name,
            "duration_seconds": rec.duration_seconds,
            "status": rec.status,
            "attributes": dict(rec.attributes),
        }
        if rec.error_message is not None:
            payload["error_message"] = rec.error_message
        self.log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self.log_sink.flush()


@dataclass
class _InMemorySink(_Sink):
    """In-memory recorder for hermetic tests."""

    metrics: list = field(default_factory=list)
    spans: list = field(default_factory=list)

    def record_metric(self, rec: MetricRecord) -> None:
        self.metrics.append(rec)

    def record_span(self, rec: SpanRecord) -> None:
        self.spans.append(rec)


# ---------------------------------------------------------------------------
# The observability facade.
# ---------------------------------------------------------------------------


@dataclass
class _OtelHandles:
    """Real OTel meter/tracer handles, when the SDK pipeline is wired."""

    meter: Any = None
    tracer: Any = None
    spawn_latency_histogram: Any = None
    fsm_transitions_counter: Any = None
    subscribe_lag_histogram: Any = None
    v907_verify_duration_histogram: Any = None
    recovery_trigger_counter: Any = None
    svid_fetch_failures_counter: Any = None


class PersonaEngineObservability:
    """The single instrumentation seam.

    Construction
    ------------

    Construct one instance per :class:`PersonaEngine` session. The
    engine wires it during ``__init__`` and calls the methods at the
    instrumentation seams documented in the module docstring. The
    facade is **safe to call** even if the OTel SDK is not installed
    or the collector is unreachable — every method routes through the
    sink protocol and degrades to structured-JSON log lines.

    Env-var contract
    ----------------

    Reads three env vars (see module-level constants). The facade
    only goes "live" (calls into the real OTel SDK) when:

    1. :data:`OTEL_ENV_VAR_ENABLED` is truthy.
    2. ``is_otel_sdk_available()`` returns True.
    3. The SDK initialisation chain succeeds.

    Test seam
    ---------

    Pass ``inmemory_sink=True`` to construct an in-memory recorder
    (and disable the real OTel pipeline regardless of env vars). The
    recorded metric and span lists are accessible via :attr:`records`.
    """

    def __init__(
        self,
        *,
        log_sink: TextIO = sys.stderr,
        env: Optional[Dict[str, str]] = None,
        inmemory_sink: bool = False,
    ) -> None:
        self._env: Dict[str, str] = dict(env) if env is not None else dict(os.environ)
        self._log_sink = log_sink
        if inmemory_sink:
            self._sink: _Sink = _InMemorySink()
            self._inmemory: Optional[_InMemorySink] = self._sink  # type: ignore[assignment]
        else:
            self._sink = _StructuredLogSink(log_sink=log_sink)
            self._inmemory = None
        # OTel-state.
        self._otel_enabled: bool = False
        self._otel: _OtelHandles = _OtelHandles()
        self._spiffe_id: Optional[str] = None
        self._persona_id: Optional[str] = None
        self._org_id: Optional[str] = None
        self._session_id: Optional[str] = None
        # Probe & maybe wire real OTel.
        if not inmemory_sink and self._env.get(OTEL_ENV_VAR_ENABLED, "") and _truthy(
            self._env.get(OTEL_ENV_VAR_ENABLED, "")
        ):
            self._maybe_install_real_otel_pipeline()

    # ------------------------------------------------------------------
    # Bindings.
    # ------------------------------------------------------------------

    def bind_workload_identity(
        self,
        *,
        spiffe_id: Optional[str],
        persona_id: str,
        org_id: str,
        session_id: str,
    ) -> None:
        """Record the SPIFFE workload-ID for correlation.

        Called by :meth:`PersonaEngine.boot` once
        :class:`SvidFetchResult` has been resolved (or right after the
        socket-probe in the Bug-40 fence-to-probe-only path, where
        spiffe_id is still ``None`` and the correlation-key is the
        SVID-probe's expected SPIFFE-ID instead).
        """
        self._spiffe_id = spiffe_id
        self._persona_id = persona_id
        self._org_id = org_id
        self._session_id = session_id

    # ------------------------------------------------------------------
    # Metric emission seams.
    # ------------------------------------------------------------------

    def record_spawn_latency(self, duration_seconds: float, *, outcome: str = "success") -> None:
        attrs = self._base_attributes()
        attrs["outcome"] = outcome
        rec = MetricRecord(
            metric_name="persona_engine.spawn.latency_seconds",
            metric_kind="histogram",
            value=float(duration_seconds),
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.spawn_latency_histogram is not None:
            try:  # pragma: no cover - exercised only with real SDK
                self._otel.spawn_latency_histogram.record(
                    duration_seconds, attributes=attrs
                )
            except Exception:  # noqa: BLE001
                pass

    def record_fsm_transition(
        self, *, from_state: str, to_state: str, accepted: bool
    ) -> None:
        attrs = self._base_attributes()
        attrs["from_state"] = from_state
        attrs["to_state"] = to_state
        attrs["accepted"] = "true" if accepted else "false"
        rec = MetricRecord(
            metric_name="persona_engine.fsm.transitions_total",
            metric_kind="counter",
            value=1.0,
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.fsm_transitions_counter is not None:
            try:  # pragma: no cover
                self._otel.fsm_transitions_counter.add(1, attributes=attrs)
            except Exception:  # noqa: BLE001
                pass

    def record_subscribe_lag(self, lag_seconds: float, *, subject: str) -> None:
        attrs = self._base_attributes()
        attrs["subject"] = subject
        rec = MetricRecord(
            metric_name="persona_engine.subscribe.lag_seconds",
            metric_kind="histogram",
            value=float(lag_seconds),
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.subscribe_lag_histogram is not None:
            try:  # pragma: no cover
                self._otel.subscribe_lag_histogram.record(
                    lag_seconds, attributes=attrs
                )
            except Exception:  # noqa: BLE001
                pass

    def record_v907_verify_duration(
        self, duration_seconds: float, *, mode: str, matched: Optional[bool] = None
    ) -> None:
        attrs = self._base_attributes()
        attrs["mode"] = mode
        if matched is not None:
            attrs["matched"] = "true" if matched else "false"
        rec = MetricRecord(
            metric_name="persona_engine.v907.verify_duration_seconds",
            metric_kind="histogram",
            value=float(duration_seconds),
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.v907_verify_duration_histogram is not None:
            try:  # pragma: no cover
                self._otel.v907_verify_duration_histogram.record(
                    duration_seconds, attributes=attrs
                )
            except Exception:  # noqa: BLE001
                pass

    def record_recovery_trigger(self, *, trigger: str, outcome: str) -> None:
        attrs = self._base_attributes()
        attrs["trigger"] = trigger
        attrs["outcome"] = outcome
        rec = MetricRecord(
            metric_name="persona_engine.recovery.trigger_total",
            metric_kind="counter",
            value=1.0,
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.recovery_trigger_counter is not None:
            try:  # pragma: no cover
                self._otel.recovery_trigger_counter.add(1, attributes=attrs)
            except Exception:  # noqa: BLE001
                pass

    def record_svid_fetch_failure(self, *, fence_mode: str) -> None:
        attrs = self._base_attributes()
        attrs["fence_mode"] = fence_mode
        rec = MetricRecord(
            metric_name="persona_engine.svid.fetch_failures_total",
            metric_kind="counter",
            value=1.0,
            attributes=attrs,
        )
        self._sink.record_metric(rec)
        if self._otel_enabled and self._otel.svid_fetch_failures_counter is not None:
            try:  # pragma: no cover
                self._otel.svid_fetch_failures_counter.add(1, attributes=attrs)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Span emission seam.
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def span(
        self, name: str, *, attributes: Optional[Dict[str, str]] = None
    ) -> Iterator["_SpanContext"]:
        """Context manager wrapping a unit of work as a span.

        Always records a :class:`SpanRecord` via the structured-JSON
        sink. When OTel is wired, also opens a real tracer span. The
        yielded context exposes :meth:`set_attribute` so call sites
        can attach properties mid-flight; failures inside the with-
        block mark the span ``status=error`` and capture the
        exception's ``repr`` as ``error_message`` (parity with the
        OTel SDK's ``record_exception()`` semantics, without binding
        to its types).
        """
        attrs = self._base_attributes()
        if attributes:
            attrs.update({k: str(v) for k, v in attributes.items()})
        start = time.monotonic()
        otel_span_cm = None
        if self._otel_enabled and self._otel.tracer is not None:
            try:  # pragma: no cover
                otel_span_cm = self._otel.tracer.start_as_current_span(
                    name, attributes=attrs
                )
                otel_span_cm.__enter__()
            except Exception:  # noqa: BLE001
                otel_span_cm = None
        ctx = _SpanContext(attributes=attrs)
        status: str = "ok"
        error_message: Optional[str] = None
        try:
            yield ctx
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_message = repr(exc)
            raise
        finally:
            duration = time.monotonic() - start
            rec = SpanRecord(
                span_name=name,
                duration_seconds=duration,
                attributes=dict(ctx.attributes),
                status=status,
                error_message=error_message,
            )
            self._sink.record_span(rec)
            if otel_span_cm is not None:  # pragma: no cover
                try:
                    otel_span_cm.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------
    # Test seam: inspect recorded metrics / spans.
    # ------------------------------------------------------------------

    @property
    def records(self) -> Optional[_InMemorySink]:
        """Return the in-memory sink iff constructed with ``inmemory_sink=True``."""
        return self._inmemory

    # ------------------------------------------------------------------
    # Implementation helpers.
    # ------------------------------------------------------------------

    def _base_attributes(self) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        if self._persona_id is not None:
            attrs["persona_id"] = self._persona_id
        if self._org_id is not None:
            attrs["org_id"] = self._org_id
        if self._session_id is not None:
            attrs["session_id"] = self._session_id
        if self._spiffe_id is not None:
            attrs["workload.spiffe_id"] = self._spiffe_id
        return attrs

    def _maybe_install_real_otel_pipeline(self) -> None:  # pragma: no cover
        """Install the real OTel SDK + OTLP exporter pipeline.

        Failures here log a WARN and leave the facade in the
        structured-log-only path; no exception escapes.
        """
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            self._log_warn(
                "otel-sdk-import-failed",
                {"reason": str(exc)},
            )
            return
        endpoint = self._env.get(OTEL_ENV_VAR_EXPORTER_OTLP_ENDPOINT, "") or self._env.get(
            STANDARD_OTLP_ENDPOINT, ""
        )
        if not endpoint:
            self._log_warn(
                "otel-endpoint-unset",
                {
                    "hint": (
                        "set WAKIR_PERSONA_OTEL_OTLP_ENDPOINT or "
                        "OTEL_EXPORTER_OTLP_ENDPOINT to a reachable "
                        "OTLP gRPC URL (e.g. http://otel-collector:4317)"
                    ),
                },
            )
            return
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as exc:
            self._log_warn(
                "otel-otlp-exporter-import-failed",
                {"reason": str(exc), "endpoint": endpoint},
            )
            return
        service_name = self._env.get(
            OTEL_ENV_VAR_SERVICE_NAME, "wakir-persona-engine"
        )
        try:
            resource = Resource.create(
                {
                    "service.name": service_name,
                    "service.version": self._env.get(
                        "WAKIR_PERSONA_ENGINE_VERSION", "0.4.2-pilot"
                    ),
                }
            )
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, insecure=True)
            )
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=[metric_reader],
            )
            metrics.set_meter_provider(meter_provider)
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint, insecure=True)
                )
            )
            trace.set_tracer_provider(tracer_provider)
            meter = metrics.get_meter("wakir.persona_engine")
            tracer = trace.get_tracer("wakir.persona_engine")
            self._otel = _OtelHandles(
                meter=meter,
                tracer=tracer,
                spawn_latency_histogram=meter.create_histogram(
                    "persona_engine.spawn.latency_seconds",
                    unit="s",
                    description="boot+spawn wall-clock from boot() entry to first engineering output emit",
                ),
                fsm_transitions_counter=meter.create_counter(
                    "persona_engine.fsm.transitions_total",
                    description="lifecycle FSM transition attempts (accepted + rejected)",
                ),
                subscribe_lag_histogram=meter.create_histogram(
                    "persona_engine.subscribe.lag_seconds",
                    unit="s",
                    description="wall-clock between inbound envelope ts_utc and subscribe-loop dispatch",
                ),
                v907_verify_duration_histogram=meter.create_histogram(
                    "persona_engine.v907.verify_duration_seconds",
                    unit="s",
                    description="V-907 pin-verify wall-clock",
                ),
                recovery_trigger_counter=meter.create_counter(
                    "persona_engine.recovery.trigger_total",
                    description="recovery_workflow R-phase outcomes",
                ),
                svid_fetch_failures_counter=meter.create_counter(
                    "persona_engine.svid.fetch_failures_total",
                    description="SVID full-fetch failures driving the fence-to-probe-only path",
                ),
            )
            self._otel_enabled = True
            self._log_info(
                "otel-pipeline-installed",
                {
                    "endpoint": endpoint,
                    "service_name": service_name,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._log_warn(
                "otel-pipeline-install-failed",
                {"reason": repr(exc), "endpoint": endpoint},
            )
            self._otel_enabled = False

    def _log_info(self, msg: str, extra: Dict[str, Any]) -> None:
        payload = {
            "ts_utc": _utc_now_rfc3339(),
            "component": "wakir-persona-engine",
            "level": "INFO",
            "msg": msg,
        }
        payload.update(extra)
        self._log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self._log_sink.flush()

    def _log_warn(self, msg: str, extra: Dict[str, Any]) -> None:
        payload = {
            "ts_utc": _utc_now_rfc3339(),
            "component": "wakir-persona-engine",
            "level": "WARN",
            "msg": msg,
        }
        payload.update(extra)
        self._log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self._log_sink.flush()


# ---------------------------------------------------------------------------
# Span-context handle (exposed via the with-statement target).
# ---------------------------------------------------------------------------


@dataclass
class _SpanContext:
    """Per-span attribute bag yielded by :meth:`PersonaEngineObservability.span`.

    Call ``set_attribute(key, value)`` to attach name/value pairs at
    any point inside the with-block. Values are coerced to ``str``
    on the wire (the in-memory sink keeps them as-is so tests can
    assert on type).
    """

    attributes: Dict[str, str] = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = str(value)


# ---------------------------------------------------------------------------
# Helper factory: structured-log-only facade (no env-var dependency).
# ---------------------------------------------------------------------------


def structured_log_observability(log_sink: TextIO) -> PersonaEngineObservability:
    """Construct an observability facade that always uses the structured-
    log sink — never tries to wire real OTel. Convenience for tests
    and for the sync-engine variant where the OTLP pipeline is wired
    by the async-engine wrapper at a different layer."""
    return PersonaEngineObservability(
        log_sink=log_sink,
        env={},
        inmemory_sink=False,
    )
