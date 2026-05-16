# SPDX-License-Identifier: BUSL-1.1
"""Hardening tests for the 3-Way-Mode bridge-audit triangle.

Sprint-Pengine-15-Folge (ADR-0063 §Folgeartefakte Item 3, follow-on
to PR #106).

100% hermetic: no filesystem, no network, no time sources. Every test
fabricates :class:`DiffInput` and :class:`Implementation` adapter
callables in-process so the triangle's pure-comparison behaviour is
exercised without dragging in the Pre-Framework sink, the NATS-KV
substrate, or any real Rust subprocess.

Coverage map (12 vectors, additional to the 10 in
test_bridge_audit_diff_engine.py):

1.  ``resolve_bridge_mode`` defaults to ``"2way"`` when env is empty.
2.  ``resolve_bridge_mode`` reads ``WAKIR_BRIDGE_MODE`` from explicit env.
3.  ``resolve_bridge_mode`` rejects unknown values (Quadlet-typo guard).
4.  2-way mode: triangle degenerates to a single pairwise diff.
5.  2-way mode: ``impl_c`` is accepted but ignored.
6.  3-way mode requires ``impl_c`` — missing adapter raises.
7.  3-way happy path: stub adapter byte-identical to Python sinks ⇒
    ``all_consistent=True`` across all three pairs.
8.  3-way drift in C only: A↔B identical, B↔C + A↔C drift ⇒
    ``all_consistent=False`` with ``schema_version_drift=False``.
9.  3-way transitivity failure: A=B byte-identical, A↔C and B↔C both
    differ on a non-schema field ⇒ ``all_consistent=False``.
10. 3-way schema-version drift detection (``/schema`` field-diff
    surfaces as ``schema_version_drift=True``).
11. Recovery-trigger consistency: same trigger label across all three
    sinks ⇒ ``all_consistent=True``.
12. Recovery-trigger drift: trigger label differs between Python sinks
    and Rust stub ⇒ ``all_consistent=False``, drift surfaces at the
    expected JSON-Pointer path.

Bonus coverage (Writer-side integration):

13. ``BridgeAuditWriter`` consumes ``bridge_mode`` constructor pin.
14. ``BridgeAuditWriter`` consumes ``WAKIR_BRIDGE_MODE`` env-var.
15. ``BridgeAuditWriter`` rejects unknown env-var value at construction.
16. ``BridgeAuditWriter`` invokes Rust-engine adapter in 3-way mode.
17. ``BridgeAuditWriter`` skips Rust-engine adapter in 2-way mode.
18. ``BridgeAuditWriter`` swallows Rust-engine adapter exceptions.

Total: 18 hermetic vectors (≥10 required).
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffInput,
    DiffKind,
)
from wirelang.persona_engine.bridge_audit_triangle import (
    BRIDGE_MODE_ENV,
    DEFAULT_BRIDGE_MODE,
    BridgeMode,
    TriangleReport,
    cross_check_triangle,
    default_python_markdown_projection,
    default_python_structured_projection,
    default_rust_engine_stub,
    resolve_bridge_mode,
)
from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _input() -> DiffInput:
    return DiffInput(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-abc",
        step_index=0,
        output_kind="tool_call",
        payload=b"payload-bytes",
        ts_utc="2026-05-15T15:00:00Z",
    )


def _matched_python_adapters():
    """Return Python-markdown + Python-structured adapters with identical pins."""
    return (
        default_python_markdown_projection(
            engine_version="0.2.0-pilot",
            v907_pin="sha256:" + "a" * 64,
        ),
        default_python_structured_projection(
            engine_version="0.2.0-pilot",
            v907_pin="sha256:" + "a" * 64,
        ),
    )


def _matched_rust_stub():
    """Rust-stub with engine_version pinned to match the Python sinks."""
    return default_rust_engine_stub(
        engine_version="0.2.0-pilot",  # matches Python default
        v907_pin="sha256:" + "a" * 64,
    )


# ---------------------------------------------------------------------------
# 1-3. resolve_bridge_mode env-var handling
# ---------------------------------------------------------------------------


def test_resolve_bridge_mode_defaults_to_2way():
    assert resolve_bridge_mode(env={}) == BridgeMode.TWO_WAY
    assert DEFAULT_BRIDGE_MODE == BridgeMode.TWO_WAY


def test_resolve_bridge_mode_reads_env():
    assert (
        resolve_bridge_mode(env={BRIDGE_MODE_ENV: "3way"})
        == BridgeMode.THREE_WAY
    )
    assert (
        resolve_bridge_mode(env={BRIDGE_MODE_ENV: "2way"})
        == BridgeMode.TWO_WAY
    )


def test_resolve_bridge_mode_rejects_unknown_value():
    with pytest.raises(ValueError, match="unknown WAKIR_BRIDGE_MODE"):
        resolve_bridge_mode(env={BRIDGE_MODE_ENV: "doppelganger"})
    with pytest.raises(ValueError):
        resolve_bridge_mode(env={BRIDGE_MODE_ENV: "4WAY"})
    with pytest.raises(ValueError):
        resolve_bridge_mode(env={BRIDGE_MODE_ENV: ""})


# ---------------------------------------------------------------------------
# 4-5. 2-way mode degradation
# ---------------------------------------------------------------------------


def test_2way_mode_degenerates_to_pairwise():
    a, b = _matched_python_adapters()
    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        mode=BridgeMode.TWO_WAY,
    )
    assert report.mode == BridgeMode.TWO_WAY
    assert report.all_consistent is True
    assert report.report_bc is None
    assert report.report_ac is None
    assert report.schema_version_drift is False
    assert len(report.pairwise_reports()) == 1


def test_2way_mode_ignores_impl_c():
    """Passing a 3rd adapter in 2-way mode is accepted but not invoked."""
    a, b = _matched_python_adapters()
    invoked = {"c": 0}

    def spy_c(_input):
        invoked["c"] += 1
        return {"engine_version": "should-not-be-invoked"}

    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=spy_c,
        mode=BridgeMode.TWO_WAY,
    )
    assert report.all_consistent is True
    assert invoked["c"] == 0
    assert report.report_bc is None


# ---------------------------------------------------------------------------
# 6. 3-way requires impl_c
# ---------------------------------------------------------------------------


def test_3way_mode_requires_impl_c():
    a, b = _matched_python_adapters()
    with pytest.raises(ValueError, match="3way mode requires impl_c"):
        cross_check_triangle(
            _input(),
            impl_a=a,
            impl_b=b,
            impl_c=None,
            mode=BridgeMode.THREE_WAY,
        )


# ---------------------------------------------------------------------------
# 7. 3-way happy path
# ---------------------------------------------------------------------------


def test_3way_stub_byte_identical_all_consistent():
    a, b = _matched_python_adapters()
    c = _matched_rust_stub()
    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=c,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.mode == BridgeMode.THREE_WAY
    assert report.all_consistent is True
    assert report.report_ab.byte_identical is True
    assert report.report_bc is not None and report.report_bc.byte_identical
    assert report.report_ac is not None and report.report_ac.byte_identical
    assert report.schema_version_drift is False
    assert len(report.pairwise_reports()) == 3
    # All three hashes equal in byte-identical case.
    h = report.report_ab.jcs_hash_a
    assert report.report_ab.jcs_hash_b == h
    assert report.report_bc.jcs_hash_a == h
    assert report.report_bc.jcs_hash_b == h
    assert report.report_ac.jcs_hash_a == h
    assert report.report_ac.jcs_hash_b == h


# ---------------------------------------------------------------------------
# 8. Drift in C only (engine_version drift)
# ---------------------------------------------------------------------------


def test_3way_rust_stub_engine_version_drift_surfaces():
    a, b = _matched_python_adapters()
    # Stub keeps its default "-rust-stub" suffix — drift expected.
    c = default_rust_engine_stub()
    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=c,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.all_consistent is False
    # A↔B agree (both Python).
    assert report.report_ab.byte_identical is True
    # B↔C and A↔C disagree on engine_version.
    assert report.report_bc.byte_identical is False
    assert report.report_ac.byte_identical is False
    # The drift is on /engine_version, not /schema.
    assert report.schema_version_drift is False
    bc_paths = [fd.path for fd in report.report_bc.field_diffs]
    assert "/engine_version" in bc_paths


# ---------------------------------------------------------------------------
# 9. Transitivity failure (A=B byte-identical, both differ from C
#    on a non-schema field)
# ---------------------------------------------------------------------------


def test_3way_transitivity_failure_surfaces():
    a, b = _matched_python_adapters()

    # Rust stub drifts on /ts_utc — both A↔C and B↔C will surface this.
    def c_impl(input_: DiffInput):
        return {
            "engine_version": "0.2.0-pilot",
            "event_kind": "engineering_output",
            "org_id": input_.org_id,
            "output_kind": input_.output_kind,
            "output_payload_sha256": "sha256:"
            + hashlib.sha256(input_.payload).hexdigest(),
            "persona_id": input_.persona_id,
            "schema": "wakir.persona.engineering-output/1",
            "session_id": input_.session_id,
            "step_index": input_.step_index,
            "ts_utc": "2099-01-01T00:00:00Z",  # drift
            "v907_pin": "sha256:" + "a" * 64,
        }

    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=c_impl,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.all_consistent is False
    assert report.report_ab.byte_identical is True
    assert report.report_bc.byte_identical is False
    assert report.report_ac.byte_identical is False
    assert report.schema_version_drift is False
    # The /ts_utc field-diff is present in both C-pairs.
    for r in (report.report_bc, report.report_ac):
        paths = [fd.path for fd in r.field_diffs]
        assert "/ts_utc" in paths


# ---------------------------------------------------------------------------
# 10. Schema-version drift detection
# ---------------------------------------------------------------------------


def test_3way_schema_version_drift_surfaces():
    a, b = _matched_python_adapters()

    # Rust stub drifts on /schema only.
    def c_impl(input_: DiffInput):
        return {
            "engine_version": "0.2.0-pilot",
            "event_kind": "engineering_output",
            "org_id": input_.org_id,
            "output_kind": input_.output_kind,
            "output_payload_sha256": "sha256:"
            + hashlib.sha256(input_.payload).hexdigest(),
            "persona_id": input_.persona_id,
            "schema": "wakir.persona.engineering-output/2",  # bumped
            "session_id": input_.session_id,
            "step_index": input_.step_index,
            "ts_utc": input_.ts_utc,
            "v907_pin": "sha256:" + "a" * 64,
        }

    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=c_impl,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.all_consistent is False
    assert report.schema_version_drift is True
    bc_paths = [fd.path for fd in report.report_bc.field_diffs]
    assert "/schema" in bc_paths
    # 2-way slice still reports byte-identical for A↔B.
    assert report.report_ab.byte_identical is True


# ---------------------------------------------------------------------------
# 11-12. Recovery-R-Trigger consistency
# ---------------------------------------------------------------------------


def _recovery_envelope(input_: DiffInput, *, trigger: str, schema: str):
    return {
        "engine_version": "0.2.0-pilot",
        "event_kind": "recovery_workflow",
        "org_id": input_.org_id,
        "persona_id": input_.persona_id,
        "recovery_trigger": trigger,
        "schema": schema,
        "session_id": input_.session_id,
        "step_index": input_.step_index,
        "ts_utc": input_.ts_utc,
    }


def _matched_recovery_adapters(trigger: str):
    schema = "wakir.persona.recovery-workflow/1"

    def make(_t):
        def _impl(input_: DiffInput):
            return _recovery_envelope(input_, trigger=_t, schema=schema)

        return _impl

    return make(trigger), make(trigger), make(trigger)


def test_recovery_trigger_consistent_across_three_sinks():
    a, b, c = _matched_recovery_adapters(trigger="CrashDetected")
    report = cross_check_triangle(
        _input(),
        impl_a=a,
        impl_b=b,
        impl_c=c,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.all_consistent is True
    assert report.schema_version_drift is False


def test_recovery_trigger_drift_surfaces_at_expected_path():
    schema = "wakir.persona.recovery-workflow/1"

    def py_adapter(input_: DiffInput):
        return _recovery_envelope(
            input_, trigger="CrashDetected", schema=schema
        )

    def rust_adapter(input_: DiffInput):
        return _recovery_envelope(
            input_, trigger="DespawnMidOperation", schema=schema
        )

    report = cross_check_triangle(
        _input(),
        impl_a=py_adapter,
        impl_b=py_adapter,
        impl_c=rust_adapter,
        mode=BridgeMode.THREE_WAY,
    )
    assert report.all_consistent is False
    # A↔B match.
    assert report.report_ab.byte_identical is True
    # Drift is on the recovery_trigger field for the C-pairs.
    bc_paths = [fd.path for fd in report.report_bc.field_diffs]
    ac_paths = [fd.path for fd in report.report_ac.field_diffs]
    assert "/recovery_trigger" in bc_paths
    assert "/recovery_trigger" in ac_paths
    # Verify the drift is VALUE_MISMATCH, not type/only-in.
    bc_trigger_diff = next(
        fd for fd in report.report_bc.field_diffs
        if fd.path == "/recovery_trigger"
    )
    assert bc_trigger_diff.kind == DiffKind.VALUE_MISMATCH
    assert bc_trigger_diff.value_a == "CrashDetected"
    assert bc_trigger_diff.value_b == "DespawnMidOperation"


# ---------------------------------------------------------------------------
# Writer-side integration (13-18)
# ---------------------------------------------------------------------------


def _writer(
    tmp_path: Path,
    sink: io.StringIO,
    *,
    bridge_mode=None,
    env=None,
    rust_engine_adapter=None,
) -> BridgeAuditWriter:
    return BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-abc",
        engine_version="0.2.0-pilot",
        v907_pin="sha256:" + "a" * 64,
        preframework_sink_path=tmp_path / "tomas" / "bridge-audit.md",
        wakir_runtime_sink=sink,
        bridge_mode=bridge_mode,
        env=env,
        rust_engine_adapter=rust_engine_adapter,
    )


def test_writer_consumes_bridge_mode_pin(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink, bridge_mode=BridgeMode.THREE_WAY)
    assert w.bridge_mode == BridgeMode.THREE_WAY


def test_writer_consumes_env_var(tmp_path):
    sink = io.StringIO()
    w = _writer(tmp_path, sink, env={BRIDGE_MODE_ENV: "3way"})
    assert w.bridge_mode == BridgeMode.THREE_WAY
    sink2 = io.StringIO()
    w2 = _writer(tmp_path, sink2, env={})  # explicit empty env
    assert w2.bridge_mode == BridgeMode.TWO_WAY


def test_writer_rejects_unknown_env_var(tmp_path):
    sink = io.StringIO()
    with pytest.raises(ValueError, match="unknown WAKIR_BRIDGE_MODE"):
        _writer(tmp_path, sink, env={BRIDGE_MODE_ENV: "bogus"})


def test_writer_invokes_rust_adapter_in_3way(tmp_path):
    sink = io.StringIO()
    invocations = []

    def adapter(evt: EngineeringOutputEvent, payload: bytes):
        invocations.append((evt.step_index, evt.output_kind, payload))

    w = _writer(
        tmp_path,
        sink,
        bridge_mode=BridgeMode.THREE_WAY,
        rust_engine_adapter=adapter,
    )
    w.emit("tool_call", b"hello")
    w.emit("reply", b"world")
    assert len(invocations) == 2
    assert invocations[0] == (0, "tool_call", b"hello")
    assert invocations[1] == (1, "reply", b"world")


def test_writer_skips_rust_adapter_in_2way(tmp_path):
    sink = io.StringIO()
    invocations = []

    def adapter(evt, payload):
        invocations.append(evt)

    w = _writer(
        tmp_path,
        sink,
        bridge_mode=BridgeMode.TWO_WAY,
        rust_engine_adapter=adapter,
    )
    w.emit("tool_call", b"hello")
    assert invocations == []


def test_writer_swallows_rust_adapter_exception(tmp_path):
    sink = io.StringIO()

    def broken_adapter(evt, payload):
        raise RuntimeError("rust-engine-stub crashed")

    w = _writer(
        tmp_path,
        sink,
        bridge_mode=BridgeMode.THREE_WAY,
        rust_engine_adapter=broken_adapter,
    )
    # MUST NOT raise; the two Python sinks must still land.
    evt = w.emit("tool_call", b"hello")
    assert evt.step_index == 0
    # Wakir-Runtime sink got the event.
    assert sink.getvalue()  # non-empty
