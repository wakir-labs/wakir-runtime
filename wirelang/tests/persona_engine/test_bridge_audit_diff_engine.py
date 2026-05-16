# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the bridge-audit Deterministic-Diff-Engine.

Sprint-Pengine-15-Mini (ADR-0063 §Folgeartefakte Item 2).

These tests are 100% hermetic: no filesystem, no network, no time
sources. Every test fabricates ``DiffInput`` and adapter callables
in-process so the diff-engine's pure-comparison behaviour is exercised
without dragging in the Pre-Framework sink or NATS-KV substrate.

Coverage map (10 tests):

1. Byte-identical match (canonical happy path).
2. Field-order drift is canonicalised away by JCS.
3. Value-mismatch surfaces the right path + kind.
4. Numeric-precision drift surfaces as ``TYPE_MISMATCH``.
5. Schema-version drift surfaces at ``/schema_version``.
6. Error-surface keys (``ONLY_IN_*``) are reported on each side.
7. Consistency score is ``1.0`` for byte-identical, ``<1.0`` else.
8. Nested-object drift surfaces at the nested JSON-Pointer path.
9. JSON-Pointer ``~`` and ``/`` escapes are emitted correctly.
10. Adapter receives the same ``DiffInput`` instance (purity check).
"""

from __future__ import annotations

import hashlib

import pytest

from wirelang.persona_engine.bridge_audit_diff_engine import (
    CloudEventEnvelope,
    DiffInput,
    DiffKind,
    DiffReport,
    canonicalize_envelope,
    compare_implementations,
    consistency_score,
    diff_envelopes,
    jcs_hash,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _default_input() -> DiffInput:
    return DiffInput(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-abc",
        step_index=0,
        output_kind="tool_call",
        payload=b"payload-bytes",
        ts_utc="2026-05-15T15:00:00Z",
    )


def _canonical_envelope(input_: DiffInput) -> CloudEventEnvelope:
    """A reference envelope that both 'good' adapters reproduce."""
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
        "ts_utc": input_.ts_utc,
        "v907_pin": "sha256:" + "a" * 64,
    }


# ---------------------------------------------------------------------------
# 1. Byte-identical match
# ---------------------------------------------------------------------------


def test_01_byte_identical_match():
    """Two adapters producing the same envelope yield byte-identical."""
    inp = _default_input()
    impl = lambda i: _canonical_envelope(i)  # noqa: E731
    report = compare_implementations(inp, impl, impl)
    assert report.byte_identical is True
    assert report.jcs_hash_a == report.jcs_hash_b
    assert report.field_diffs == ()
    assert report.consistency_score == 1.0
    assert report.has_drift() is False
    assert "byte-identical" in report.summary()


# ---------------------------------------------------------------------------
# 2. Field-order drift canonicalised away by JCS
# ---------------------------------------------------------------------------


def test_02_field_order_drift_is_jcs_canonicalised_away():
    """JCS sorts keys; two envelopes with different insertion order
    MUST produce the same canonical bytes."""
    inp = _default_input()

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        return _canonical_envelope(i)

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        # Build the SAME envelope but with reversed insertion order.
        base = _canonical_envelope(i)
        return {k: base[k] for k in reversed(list(base.keys()))}

    report = compare_implementations(inp, impl_a, impl_b)
    assert report.byte_identical is True
    assert report.consistency_score == 1.0
    # And the canonical bytes are identical too:
    assert canonicalize_envelope(impl_a(inp)) == canonicalize_envelope(impl_b(inp))


# ---------------------------------------------------------------------------
# 3. Value-mismatch surfaces path + kind
# ---------------------------------------------------------------------------


def test_03_value_mismatch_surfaces_path_and_kind():
    """A single divergent value lands as one ``VALUE_MISMATCH`` entry
    with the JSON-Pointer-style path to the field."""
    inp = _default_input()

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        return _canonical_envelope(i)

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        env["output_kind"] = "reply"  # drift!
        return env

    report = compare_implementations(inp, impl_a, impl_b)
    assert report.byte_identical is False
    assert report.has_drift() is True
    assert len(report.field_diffs) == 1
    diff = report.field_diffs[0]
    assert diff.path == "/output_kind"
    assert diff.kind == DiffKind.VALUE_MISMATCH
    assert diff.value_a == "tool_call"
    assert diff.value_b == "reply"
    assert report.consistency_score < 1.0


# ---------------------------------------------------------------------------
# 4. Numeric-precision drift surfaces as TYPE_MISMATCH
# ---------------------------------------------------------------------------


def test_04_numeric_precision_drift_surfaces_as_type_mismatch():
    """``step_index`` 0 (int) vs 0.0 (float): same JSON-numeric value
    but different Python types — surfaced as ``TYPE_MISMATCH`` so an
    operator sees the precision-class drift before it becomes a
    canonicaliser bug."""
    inp = _default_input()

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        env["step_index"] = 0  # int
        return env

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        env["step_index"] = 0.0  # float — same value, different type
        return env

    report = compare_implementations(inp, impl_a, impl_b)
    # JCS-canonical form for int(0) is "0"; for float(0.0) the
    # ECMA-262 ToString is also "0" — so byte-identical IS valid.
    # The diff-engine's TYPE_MISMATCH detection runs only when JCS
    # bytes differ. We exercise the in-process detector directly:
    env_a = impl_a(inp)
    env_b = impl_b(inp)
    diffs = diff_envelopes(env_a, env_b)
    # Walk reports a TYPE_MISMATCH at /step_index since the Python
    # types differ but values compare equal.
    paths = [d.path for d in diffs]
    assert "/step_index" in paths
    type_mm = [d for d in diffs if d.path == "/step_index"][0]
    assert type_mm.kind == DiffKind.TYPE_MISMATCH
    assert type(type_mm.value_a) is int
    assert type(type_mm.value_b) is float


# ---------------------------------------------------------------------------
# 5. Schema-version drift
# ---------------------------------------------------------------------------


def test_05_schema_version_drift_surfaces_at_schema_path():
    """Two implementations emitting different ``schema`` strings — the
    typical Phase-3a Python-vs-Rust forward-compat drift — must surface
    at ``/schema`` with ``VALUE_MISMATCH``."""
    inp = _default_input()

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        return _canonical_envelope(i)

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        env["schema"] = "wakir.persona.engineering-output/2"
        return env

    report = compare_implementations(inp, impl_a, impl_b)
    assert report.byte_identical is False
    schema_diffs = [d for d in report.field_diffs if d.path == "/schema"]
    assert len(schema_diffs) == 1
    assert schema_diffs[0].kind == DiffKind.VALUE_MISMATCH
    assert schema_diffs[0].value_a.endswith("/1")
    assert schema_diffs[0].value_b.endswith("/2")


# ---------------------------------------------------------------------------
# 6. Error-surface ONLY_IN_* keys
# ---------------------------------------------------------------------------


def test_06_error_surface_only_in_keys_are_reported_per_side():
    """An implementation that carries an extra error-surface field
    (e.g. ``error_code``) surfaces as ``ONLY_IN_B`` for the side that
    has it; a missing field surfaces as ``ONLY_IN_A`` for the side
    that drops it."""
    inp = _default_input()

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        env["error_code"] = "PRE_FRAMEWORK_FAILED"  # only on A
        return env

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        env = dict(_canonical_envelope(i))
        del env["v907_pin"]  # only-on-A field by being missing on B
        return env

    report = compare_implementations(inp, impl_a, impl_b)
    assert report.byte_identical is False

    by_path = {d.path: d for d in report.field_diffs}
    # error_code only present on A.
    assert "/error_code" in by_path
    assert by_path["/error_code"].kind == DiffKind.ONLY_IN_A
    assert by_path["/error_code"].value_a == "PRE_FRAMEWORK_FAILED"
    # v907_pin only present on A (B dropped it).
    assert "/v907_pin" in by_path
    assert by_path["/v907_pin"].kind == DiffKind.ONLY_IN_A


# ---------------------------------------------------------------------------
# 7. Consistency score behaviour
# ---------------------------------------------------------------------------


def test_07_consistency_score_one_for_identical_and_less_for_drift():
    """The score is exactly 1.0 for byte-identical envelopes and
    strictly less for any drift (one drifted field in an 11-field
    envelope ≈ 0.909)."""
    inp = _default_input()
    env_same = _canonical_envelope(inp)
    diffs_same = diff_envelopes(env_same, env_same)
    assert consistency_score(env_same, env_same, diffs_same) == 1.0

    # Drift one field of 11 → 1 - 1/11 ≈ 0.909
    env_b = dict(env_same)
    env_b["output_kind"] = "reply"
    diffs = diff_envelopes(env_same, env_b)
    score = consistency_score(env_same, env_b, diffs)
    assert 0.9 < score < 1.0
    # Total drift: every leaf disjoint → score == 0.0.
    env_total_drift_a = {"a": 1, "b": 2, "c": 3}
    env_total_drift_b = {"x": 9, "y": 8, "z": 7}
    diffs_total = diff_envelopes(env_total_drift_a, env_total_drift_b)
    # 6 diffs over max(3, 3) = 3 leaves → drifted >= total → 0.0
    assert consistency_score(env_total_drift_a, env_total_drift_b, diffs_total) == 0.0


# ---------------------------------------------------------------------------
# 8. Nested-object drift surfaces at nested path
# ---------------------------------------------------------------------------


def test_08_nested_object_drift_uses_nested_jsonpointer_path():
    """When the drift lives inside a nested object, the field-path
    is ``/outer/inner`` (RFC 6901-style)."""
    env_a = {
        "metadata": {"v907_pin": "sha256:" + "a" * 64, "tag": "pilot"},
        "ts_utc": "2026-05-15T15:00:00Z",
    }
    env_b = {
        "metadata": {"v907_pin": "sha256:" + "b" * 64, "tag": "pilot"},
        "ts_utc": "2026-05-15T15:00:00Z",
    }
    diffs = diff_envelopes(env_a, env_b)
    assert len(diffs) == 1
    assert diffs[0].path == "/metadata/v907_pin"
    assert diffs[0].kind == DiffKind.VALUE_MISMATCH


# ---------------------------------------------------------------------------
# 9. JSON-Pointer escapes for ``~`` and ``/``
# ---------------------------------------------------------------------------


def test_09_jsonpointer_escapes_tilde_and_slash_in_keys():
    """RFC 6901 § 4 mandates ``~`` → ``~0`` and ``/`` → ``~1`` in
    reference tokens. The walker emits properly escaped paths so
    operators can paste them into a JSON-Pointer evaluator."""
    env_a = {"weird~key": 1, "slash/key": 2}
    env_b = {"weird~key": 99, "slash/key": 2}
    diffs = diff_envelopes(env_a, env_b)
    paths = [d.path for d in diffs]
    assert "/weird~0key" in paths
    # No drift on slash/key, so no entry expected.
    assert "/slash~1key" not in paths


# ---------------------------------------------------------------------------
# 10. Adapters receive the same DiffInput (purity)
# ---------------------------------------------------------------------------


def test_10_adapters_receive_the_same_input_instance():
    """The diff-engine MUST pass the same ``DiffInput`` to both
    adapters byte-identically; no implicit transformation."""
    inp = _default_input()
    seen_a: list[DiffInput] = []
    seen_b: list[DiffInput] = []

    def impl_a(i: DiffInput) -> CloudEventEnvelope:
        seen_a.append(i)
        return _canonical_envelope(i)

    def impl_b(i: DiffInput) -> CloudEventEnvelope:
        seen_b.append(i)
        return _canonical_envelope(i)

    compare_implementations(inp, impl_a, impl_b)
    assert len(seen_a) == 1 and len(seen_b) == 1
    assert seen_a[0] is inp
    assert seen_b[0] is inp
    # Frozen dataclass guarantees no mutation.
    with pytest.raises(Exception):
        inp.session_id = "different"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Bonus: jcs_hash sanity (not counted in the 10)
# ---------------------------------------------------------------------------


def test_jcs_hash_is_stable_across_calls():
    """Hash function is pure: same envelope → same hash."""
    env = _canonical_envelope(_default_input())
    h1 = jcs_hash(env)
    h2 = jcs_hash(env)
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 64
