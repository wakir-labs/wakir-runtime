# SPDX-License-Identifier: BUSL-1.1
"""Tests for wirelang.persona_engine.observability — Sprint-SRE Tag-15.

Hermetic — no opentelemetry wheels, no network. Drives the
:class:`PersonaEngineObservability` facade in in-memory-sink mode
and asserts each instrumentation seam emits a record with the
expected shape.
"""

from __future__ import annotations

import io
import json
import os
import time

import pytest

from wirelang.persona_engine.observability import (
    MetricRecord,
    OTEL_ENV_VAR_ENABLED,
    PersonaEngineObservability,
    SpanRecord,
    is_otel_sdk_available,
    structured_log_observability,
)


# ---------------------------------------------------------------------------
# Construction / probe behaviour
# ---------------------------------------------------------------------------


def test_inmemory_sink_facade_records_empty_at_start():
    obs = PersonaEngineObservability(inmemory_sink=True)
    assert obs.records is not None
    assert obs.records.metrics == []
    assert obs.records.spans == []


def test_structured_log_facade_writes_to_log_sink():
    sink = io.StringIO()
    obs = structured_log_observability(sink)
    obs.bind_workload_identity(
        spiffe_id="spiffe://acme.org/agent/tomas",
        persona_id="tomas",
        org_id="acme",
        session_id="abc-123",
    )
    obs.record_fsm_transition(
        from_state="uninstantiated", to_state="spawning", accepted=True
    )
    lines = [l for l in sink.getvalue().splitlines() if l.strip()]
    assert lines, "structured-log sink must produce at least one record"
    parsed = json.loads(lines[-1])
    assert parsed["metric_name"] == "persona_engine.fsm.transitions_total"
    assert parsed["metric_kind"] == "counter"
    assert parsed["metric_value"] == 1.0
    assert parsed["attributes"]["from_state"] == "uninstantiated"
    assert parsed["attributes"]["to_state"] == "spawning"
    assert parsed["attributes"]["accepted"] == "true"


def test_disabled_env_var_keeps_real_otel_off():
    # Even with the env var set, in-memory mode skips real OTel.
    obs = PersonaEngineObservability(
        env={OTEL_ENV_VAR_ENABLED: "1"},
        inmemory_sink=True,
    )
    # Internal flag (private, but the contract is in-memory mode does
    # not start the real pipeline).
    assert obs._otel_enabled is False


# ---------------------------------------------------------------------------
# Metric emission seams
# ---------------------------------------------------------------------------


def test_record_spawn_latency_captures_value_and_outcome():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id="spiffe://acme.org/agent/tomas",
        persona_id="tomas",
        org_id="acme",
        session_id="abc-123",
    )
    obs.record_spawn_latency(0.42, outcome="success")
    metrics = obs.records.metrics
    assert len(metrics) == 1
    rec = metrics[0]
    assert isinstance(rec, MetricRecord)
    assert rec.metric_name == "persona_engine.spawn.latency_seconds"
    assert rec.metric_kind == "histogram"
    assert rec.value == pytest.approx(0.42)
    assert rec.attributes["outcome"] == "success"
    assert rec.attributes["persona_id"] == "tomas"
    assert rec.attributes["workload.spiffe_id"] == "spiffe://acme.org/agent/tomas"


def test_record_fsm_transition_carries_full_label_set():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None,
        persona_id="reza",
        org_id="acme",
        session_id="s2",
    )
    obs.record_fsm_transition(
        from_state="spawning", to_state="running", accepted=True
    )
    obs.record_fsm_transition(
        from_state="uninstantiated", to_state="running", accepted=False
    )
    metrics = obs.records.metrics
    assert len(metrics) == 2
    # Accepted edge.
    assert metrics[0].attributes["accepted"] == "true"
    # Rejected edge (an invalid-transition attempt).
    assert metrics[1].attributes["accepted"] == "false"
    # No SPIFFE-ID bound — attribute must be absent.
    assert "workload.spiffe_id" not in metrics[0].attributes


def test_record_subscribe_lag_emits_histogram():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id="spiffe://acme.org/agent/tomas",
        persona_id="tomas",
        org_id="acme",
        session_id="s3",
    )
    obs.record_subscribe_lag(0.85, subject="wakir.dev.agent.agent.task.assigned.tomas")
    rec = obs.records.metrics[0]
    assert rec.metric_name == "persona_engine.subscribe.lag_seconds"
    assert rec.metric_kind == "histogram"
    assert rec.value == pytest.approx(0.85)
    assert rec.attributes["subject"] == "wakir.dev.agent.agent.task.assigned.tomas"


def test_record_v907_verify_duration_with_match():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None, persona_id="tomas", org_id="acme", session_id="s4"
    )
    obs.record_v907_verify_duration(0.014, mode="real", matched=True)
    rec = obs.records.metrics[0]
    assert rec.metric_name == "persona_engine.v907.verify_duration_seconds"
    assert rec.value == pytest.approx(0.014)
    assert rec.attributes["mode"] == "real"
    assert rec.attributes["matched"] == "true"


def test_record_v907_verify_duration_without_match_omits_label():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None, persona_id="tomas", org_id="acme", session_id="s5"
    )
    obs.record_v907_verify_duration(0.014, mode="compute_error", matched=None)
    rec = obs.records.metrics[0]
    assert "matched" not in rec.attributes


def test_record_recovery_trigger_per_phase():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None, persona_id="tomas", org_id="acme", session_id="s6"
    )
    obs.record_recovery_trigger(trigger="R1", outcome="success")
    obs.record_recovery_trigger(trigger="R2", outcome="failure")
    assert len(obs.records.metrics) == 2
    assert obs.records.metrics[0].attributes["trigger"] == "R1"
    assert obs.records.metrics[0].attributes["outcome"] == "success"
    assert obs.records.metrics[1].attributes["trigger"] == "R2"
    assert obs.records.metrics[1].attributes["outcome"] == "failure"


def test_record_svid_fetch_failure_per_fence_mode():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None, persona_id="tomas", org_id="acme", session_id="s7"
    )
    obs.record_svid_fetch_failure(fence_mode="wheel-missing")
    obs.record_svid_fetch_failure(fence_mode="fetch-failure")
    metrics = obs.records.metrics
    assert metrics[0].attributes["fence_mode"] == "wheel-missing"
    assert metrics[1].attributes["fence_mode"] == "fetch-failure"
    assert all(
        r.metric_name == "persona_engine.svid.fetch_failures_total" for r in metrics
    )


# ---------------------------------------------------------------------------
# Span emission seam
# ---------------------------------------------------------------------------


def test_span_records_duration_and_attributes_on_clean_exit():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id="spiffe://acme.org/agent/tomas",
        persona_id="tomas",
        org_id="acme",
        session_id="s8",
    )
    with obs.span("persona_engine.boot", attributes={"phase": "test"}) as ctx:
        ctx.set_attribute("axis_a_resolved", True)
        time.sleep(0.001)
    spans = obs.records.spans
    assert len(spans) == 1
    span = spans[0]
    assert isinstance(span, SpanRecord)
    assert span.span_name == "persona_engine.boot"
    assert span.duration_seconds >= 0  # monotonic timer
    assert span.status == "ok"
    assert span.attributes["phase"] == "test"
    assert span.attributes["axis_a_resolved"] == "True"
    assert span.attributes["persona_id"] == "tomas"


def test_span_records_error_on_exception_and_propagates():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id=None, persona_id="tomas", org_id="acme", session_id="s9"
    )
    with pytest.raises(RuntimeError):
        with obs.span("persona_engine.boot"):
            raise RuntimeError("boom")
    spans = obs.records.spans
    assert len(spans) == 1
    span = spans[0]
    assert span.status == "error"
    assert span.error_message is not None
    assert "boom" in span.error_message


# ---------------------------------------------------------------------------
# Engine integration smoke
# ---------------------------------------------------------------------------


def test_engine_constructor_wires_default_observability(tmp_path):
    """PersonaEngine must auto-wire a structured-log observability when none is injected."""
    from wirelang.persona_engine.engine import PersonaEngine, resolve_env

    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(
        "---\nname: tomas\ndomain: dev\nschema_version: persona-v1\n---\nBody.\n"
    )
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
        "WAKIR_PERSONA_AXIS_A_PATH": str(axis_a),
    }
    contract = resolve_env(env=env)
    eng = PersonaEngine(contract, log_sink=io.StringIO())
    assert eng.observability is not None
    assert isinstance(eng.observability, PersonaEngineObservability)


def test_engine_constructor_accepts_injected_observability(tmp_path):
    """Tests must be able to inject an in-memory facade for assertion."""
    from wirelang.persona_engine.engine import PersonaEngine, resolve_env

    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(
        "---\nname: tomas\ndomain: dev\nschema_version: persona-v1\n---\nBody.\n"
    )
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
        "WAKIR_PERSONA_AXIS_A_PATH": str(axis_a),
    }
    contract = resolve_env(env=env)
    obs = PersonaEngineObservability(inmemory_sink=True)
    eng = PersonaEngine(contract, log_sink=io.StringIO(), observability=obs)
    assert eng.observability is obs
    # __init__ binds workload-identity once (without SPIFFE-ID at that
    # point); the bind itself does not emit a metric, but it sets the
    # base-attribute state. Emit one metric to verify.
    eng.observability.record_fsm_transition(
        from_state="uninstantiated", to_state="spawning", accepted=True
    )
    assert obs.records is not None
    rec = obs.records.metrics[0]
    assert rec.attributes["persona_id"] == "tomas"
    assert rec.attributes["org_id"] == "acme"
    assert rec.attributes["session_id"] == eng.session_id


def test_engine_boot_emits_v907_verify_duration_and_span(tmp_path):
    """Boot must record a v907 verify-duration metric and a boot-span."""
    from wirelang.persona_engine.engine import PersonaEngine, resolve_env

    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(
        "---\nname: tomas\nschema_version: persona-v1\n---\nBody.\n"
    )
    env = {
        "WAKIR_PERSONA_ID": "tomas",
        "WAKIR_ORG_ID": "acme",
        "WAKIR_PERSONA_AXIS_A_PATH": str(axis_a),
        # No SVID socket configured → probe will fail-soft.
        "SPIFFE_ENDPOINT_SOCKET": "unix:///dev/null/no-such-socket",
    }
    contract = resolve_env(env=env)
    obs = PersonaEngineObservability(inmemory_sink=True)
    eng = PersonaEngine(contract, log_sink=io.StringIO(), observability=obs)
    eng.boot()
    # Must have emitted exactly one V-907 verify-duration metric.
    v907_metrics = [
        m for m in obs.records.metrics
        if m.metric_name == "persona_engine.v907.verify_duration_seconds"
    ]
    assert len(v907_metrics) == 1
    assert v907_metrics[0].attributes["mode"] in ("real", "stub", "drift", "compute_error")
    # Must have one boot span.
    boot_spans = [s for s in obs.records.spans if s.span_name == "persona_engine.boot"]
    assert len(boot_spans) == 1
    # Boot must not have started the spawn-latency clock-stop yet
    # (that happens in spawn()).
    spawn_latency_metrics = [
        m for m in obs.records.metrics
        if m.metric_name == "persona_engine.spawn.latency_seconds"
    ]
    assert spawn_latency_metrics == []


# ---------------------------------------------------------------------------
# OTel API availability probe
# ---------------------------------------------------------------------------


def test_otel_availability_probe_is_truthy_or_falsy_only():
    """``is_otel_sdk_available()`` must always return a bool."""
    result = is_otel_sdk_available()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Base attribute composition
# ---------------------------------------------------------------------------


def test_base_attributes_include_all_bound_identity():
    obs = PersonaEngineObservability(inmemory_sink=True)
    obs.bind_workload_identity(
        spiffe_id="spiffe://acme.org/agent/tomas",
        persona_id="tomas",
        org_id="acme",
        session_id="xyz",
    )
    obs.record_spawn_latency(0.1)
    rec = obs.records.metrics[0]
    assert rec.attributes["persona_id"] == "tomas"
    assert rec.attributes["org_id"] == "acme"
    assert rec.attributes["session_id"] == "xyz"
    assert rec.attributes["workload.spiffe_id"] == "spiffe://acme.org/agent/tomas"
