# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-2 Doppelbetrieb-Bridge cross-language roundtrip E2E.

Sprint-Tag-14 Mini-Welle (Bridge-Audit-Roundtrip-E2E).

Purpose
-------

The Phase-2 Doppelbetrieb-Bridge consistency drill needs an end-to-end
acceptance criterion that ties the Python emit side to the Rust replay
side. Until this test, the two halves shipped independently:

* PR #106 — Python ``bridge_audit_diff_engine.py`` (single-envelope
  oracle).
* PR #131 — Rust ``persona-engine-bridge-diff`` (Rust diff primitive).
* PR #147 — Rust ``persona-engine-bridge-audit-replay`` (Rust stream-
  level oracle).

This test is the **roundtrip wire-test**: Python emits a real
:class:`~wirelang.persona_engine.bridge_audit_writer.EngineeringOutputEvent`
sequence via :class:`~wirelang.persona_engine.bridge_audit_writer.BridgeAuditWriter`
into a hermetic :class:`io.StringIO` sink, serialises it as JSONL, hands
it to the Rust ``replay_cli`` binary via subprocess, parses the Rust
JSON report, and asserts:

* Python-computed stream-hash equals the Rust-reported stream-hash for
  both the actual and the expected streams.
* The Rust report's divergence list is empty on clean-stream match.
* ``time_to_divergence_steps`` is ``None`` on clean-stream match and a
  pinned step-index on injected drift.

Hermetic envelope
-----------------

* No live network, no live NATS, no container runtime.
* No filesystem writes outside :func:`tempfile.TemporaryDirectory` /
  ``tmp_path``.
* No Pre-Framework Markdown sink (the writer's parent-dir mkdir falls
  through to a no-op when the sandbox path is unwritable; we pin the
  sink path inside ``tmp_path`` instead so the test is hermetic by
  construction).

CI-binary discovery
-------------------

The test locates the Rust ``replay_cli`` binary in this order:

1. ``WAKIR_REPLAY_CLI_BIN`` env-var (CI sets this after a
   ``cargo build`` step).
2. ``CARGO_TARGET_DIR``/debug/replay_cli (local-dev convention used by
   the same env-var the Rust workspace honours).
3. ``<repo-root>/wirelang-rust/target/debug/replay_cli`` (the cargo
   default when no ``CARGO_TARGET_DIR`` override is set).

If none of those paths resolve, the test SKIPs with a clear message
rather than failing. This keeps a Python-only checkout green and lets
the dedicated CI lane gate the cross-language pin.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

import pytest

from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
)
from wirelang.persona_engine.bridge_audit_stream_hash import (
    jsonl_bytes_to_records,
    record_envelope,
    records_to_jsonl_bytes,
    stream_envelope,
    stream_hash,
)


# ---------------------------------------------------------------------------
# Cross-language anchor pins (must match Rust constants).
# ---------------------------------------------------------------------------

#: Python ``stream_hash([])`` and Rust ``stream_hash(&[])``.
F1_STREAM_PIN = (
    "sha256:64d11dbb5fe0c2c5e807d22438aedf3912852d81717e532f5c9d2750afa15469"
)

#: Python ``stream_hash([record-0])`` and Rust ``stream_hash(&[record-0])``.
F2_STREAM_PIN = (
    "sha256:5d259cab58d5d75772f230ac86d18b6a61fd228829cea7aa1887e98cea3cc770"
)

#: Python ``stream_hash([record-0, record-1, record-2])`` and Rust pendant.
F3_STREAM_PIN = (
    "sha256:fca1381878f461ea00520d9ee87d3e8c5b536e028e368c002f8de56d8b643bd4"
)


# ---------------------------------------------------------------------------
# CLI discovery.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    # tests/integration/test_bridge_audit_roundtrip_e2e.py
    #   -> tests/integration -> tests -> <repo-root>
    return Path(__file__).resolve().parent.parent.parent


def _discover_replay_cli() -> Path | None:
    """Locate the Rust ``replay_cli`` binary; return ``None`` if absent.

    See module docstring for the precedence rules. We return ``None``
    rather than raise so the test-skip path stays clean.
    """
    env_pin = os.environ.get("WAKIR_REPLAY_CLI_BIN")
    if env_pin:
        p = Path(env_pin)
        return p if p.is_file() else None

    cargo_target = os.environ.get("CARGO_TARGET_DIR")
    candidates: List[Path] = []
    if cargo_target:
        candidates.append(Path(cargo_target) / "debug" / "replay_cli")
        candidates.append(Path(cargo_target) / "release" / "replay_cli")
    candidates.append(_repo_root() / "wirelang-rust" / "target" / "debug" / "replay_cli")
    candidates.append(_repo_root() / "wirelang-rust" / "target" / "release" / "replay_cli")

    for c in candidates:
        if c.is_file():
            return c
    return None


REPLAY_CLI = _discover_replay_cli()

requires_cli = pytest.mark.skipif(
    REPLAY_CLI is None,
    reason=(
        "Rust replay_cli binary not built. Build with "
        "`cargo build -p persona-engine-bridge-audit-replay --bin replay_cli` "
        "or set WAKIR_REPLAY_CLI_BIN to the binary path."
    ),
)


def _run_replay_cli(
    actual_path: Path,
    expected_path: Path | None = None,
) -> dict:
    """Invoke ``replay_cli`` and return the parsed JSON report.

    The CLI returns exit-code 0 on success, 1 on divergence, 2 on
    usage error. We accept 0 and 1 (both produce a JSON report);
    exit-code 2 raises :class:`AssertionError` with the stderr text
    so the test failure is informative.
    """
    assert REPLAY_CLI is not None, "test should be skipped without CLI"
    argv = [str(REPLAY_CLI), "--actual", str(actual_path)]
    if expected_path is not None:
        argv.extend(["--expected", str(expected_path)])
    res = subprocess.run(argv, capture_output=True, text=True, check=False)
    if res.returncode == 2:
        raise AssertionError(
            f"replay_cli usage error (exit 2): {res.stderr.strip()}"
        )
    assert res.returncode in (0, 1), (
        f"replay_cli unexpected exit {res.returncode}: "
        f"stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    return json.loads(res.stdout)


# ---------------------------------------------------------------------------
# Fixture builders (mirror the Rust smoke-test fixtures byte-for-byte).
# ---------------------------------------------------------------------------


def _mk_record(step: int, output_kind: str, payload_char: str) -> EngineeringOutputEvent:
    return EngineeringOutputEvent(
        org_id="wakir-labs",
        persona_id="mira",
        session_id="sess-001",
        step_index=step,
        output_kind=output_kind,
        output_payload_sha256=f"sha256:{payload_char * 64}",
        engine_version="0.2.0-pilot",
        v907_pin=f"sha256:{'b' * 64}",
        ts_utc=f"2026-05-17T10:00:0{step}Z",
    )


def _f3_stream() -> List[EngineeringOutputEvent]:
    return [
        _mk_record(0, "tool_call", "a"),
        _mk_record(1, "reply", "b"),
        _mk_record(2, "tool_call", "c"),
    ]


def _emit_five_via_writer(tmp_path: Path) -> List[EngineeringOutputEvent]:
    """Emit a 5-record sequence via :class:`BridgeAuditWriter`.

    The writer is the production-side emit path (PR #19); the
    integration test exercises it end-to-end rather than constructing
    bare ``EngineeringOutputEvent`` instances. The Pre-Framework sink
    is pinned inside ``tmp_path`` for hermetic isolation.
    """
    sink = io.StringIO()
    writer = BridgeAuditWriter(
        org_id="wakir-labs",
        persona_id="mira",
        session_id="sess-001",
        engine_version="0.2.0-pilot",
        v907_pin=f"sha256:{'b' * 64}",
        preframework_sink_path=tmp_path / "preframework-bridge-audit.md",
        wakir_runtime_sink=sink,
        bridge_mode="2way",
    )
    payloads = [
        ("tool_call", b"a" * 32),
        ("reply", b"b" * 32),
        ("tool_call", b"c" * 32),
        ("audit_annotation", b"d" * 32),
        ("reply", b"e" * 32),
    ]
    pinned_ts = [
        "2026-05-17T10:00:00Z",
        "2026-05-17T10:00:01Z",
        "2026-05-17T10:00:02Z",
        "2026-05-17T10:00:03Z",
        "2026-05-17T10:00:04Z",
    ]
    events: List[EngineeringOutputEvent] = []
    for (kind, payload), ts in zip(payloads, pinned_ts):
        evt = writer.emit(kind, payload, ts_utc=ts)
        events.append(evt)
    return events


# ---------------------------------------------------------------------------
# Pure-Python pin tests (no Rust binary required).
# ---------------------------------------------------------------------------


def test_01_python_empty_stream_hash_matches_rust_pin():
    """F1 anchor pin: Python ``stream_hash([])`` matches the Rust pin."""
    assert stream_hash([]) == F1_STREAM_PIN


def test_02_python_single_record_stream_hash_matches_rust_pin():
    """F2 anchor pin: single F3-record-0 stream matches the Rust pin."""
    assert stream_hash([_mk_record(0, "tool_call", "a")]) == F2_STREAM_PIN


def test_03_python_three_record_stream_hash_matches_rust_pin():
    """F3 anchor pin: 3-record session matches the Rust pin."""
    assert stream_hash(_f3_stream()) == F3_STREAM_PIN


def test_04_jsonl_roundtrip_preserves_records():
    """records -> JSONL -> records is identity for the F3 fixture."""
    src = _f3_stream()
    wire = records_to_jsonl_bytes(src)
    back = jsonl_bytes_to_records(wire)
    assert len(back) == len(src)
    for a, b in zip(src, back):
        assert record_envelope(a) == record_envelope(b)
    # And stream-hash is preserved across the JSONL roundtrip.
    assert stream_hash(back) == F3_STREAM_PIN


def test_05_bridge_audit_writer_emits_five_records_with_pinned_step_index(tmp_path):
    """BridgeAuditWriter emits a 5-record sequence with step_index 0..4."""
    events = _emit_five_via_writer(tmp_path)
    assert len(events) == 5
    for i, evt in enumerate(events):
        assert evt.step_index == i
    # Stream-envelope hash is stable across re-emission of the same
    # logical input (writer is deterministic under pinned ts_utc).
    h1 = stream_hash(events)
    events2 = _emit_five_via_writer(tmp_path)
    h2 = stream_hash(events2)
    assert h1 == h2, (
        "BridgeAuditWriter emission must be deterministic under pinned ts_utc"
    )


def test_06_stream_envelope_carries_stream_len_invariant():
    """``stream_envelope`` resists silent truncation via ``stream_len``."""
    env = stream_envelope(_f3_stream())
    assert env["stream_len"] == 3
    assert len(env["stream"]) == 3
    # Empty stream too.
    env0 = stream_envelope([])
    assert env0["stream_len"] == 0
    assert env0["stream"] == []


# ---------------------------------------------------------------------------
# Cross-language E2E tests (require Rust replay_cli binary).
# ---------------------------------------------------------------------------


@requires_cli
def test_07_e2e_clean_stream_match_python_emit_rust_replay(tmp_path):
    """E2E clean-stream-match scenario.

    Python emits 5 records via BridgeAuditWriter -> JSONL -> Rust
    replay_cli self-replay -> Rust report must be success with
    ``time_to_divergence_steps == None`` and matching stream-hashes.
    """
    events = _emit_five_via_writer(tmp_path)
    actual = tmp_path / "actual.jsonl"
    actual.write_bytes(records_to_jsonl_bytes(events))

    report = _run_replay_cli(actual)  # no --expected -> self-replay
    assert report["success"] is True, (
        f"clean-stream self-replay must succeed; report: {report}"
    )
    assert report["actual_record_count"] == 5
    assert report["expected_record_count"] == 5
    assert report["divergence_count"] == 0
    assert report["divergences"] == []
    assert report["time_to_divergence_steps"] is None
    assert report["stream_hash_actual"] == report["stream_hash_expected"]

    # Cross-language pin: Python-computed stream-hash matches Rust-reported.
    python_hash = stream_hash(events)
    assert report["stream_hash_actual"] == python_hash, (
        "Rust replay_cli stream-hash must match Python stream_hash pendant"
    )


@requires_cli
def test_08_e2e_single_record_divergence_python_emit_rust_replay(tmp_path):
    """E2E single-record-divergence scenario.

    Two streams differ only at step-2 (output_kind drift from
    ``tool_call`` to ``audit_annotation``). Rust must detect the
    drift, pin ``time_to_divergence_steps == 2``, and surface a single
    divergence with field-diff path ``/output_kind``.
    """
    expected_events = _emit_five_via_writer(tmp_path)
    # Drift step-2 by mutating the dict-form and re-building the event.
    actual_events = list(expected_events)
    drifted = expected_events[2]
    actual_events[2] = EngineeringOutputEvent(
        org_id=drifted.org_id,
        persona_id=drifted.persona_id,
        session_id=drifted.session_id,
        step_index=drifted.step_index,
        output_kind="audit_annotation",  # drifted!
        output_payload_sha256=drifted.output_payload_sha256,
        engine_version=drifted.engine_version,
        v907_pin=drifted.v907_pin,
        ts_utc=drifted.ts_utc,
    )

    actual_path = tmp_path / "actual.jsonl"
    expected_path = tmp_path / "expected.jsonl"
    actual_path.write_bytes(records_to_jsonl_bytes(actual_events))
    expected_path.write_bytes(records_to_jsonl_bytes(expected_events))

    report = _run_replay_cli(actual_path, expected_path)
    assert report["success"] is False, (
        f"single-record drift must surface; report: {report}"
    )
    assert report["time_to_divergence_steps"] == 2
    assert report["divergence_count"] == 1
    div = report["divergences"][0]
    assert div["step_index"] == 2
    assert div["kind"] == "value-mismatch"
    assert "/output_kind" in div["field_diff_paths"], (
        f"output_kind drift must surface in field_diff_paths; got {div}"
    )

    # Python-computed stream-hashes must match Rust's both sides.
    py_actual = stream_hash(actual_events)
    py_expected = stream_hash(expected_events)
    assert report["stream_hash_actual"] == py_actual
    assert report["stream_hash_expected"] == py_expected
    assert py_actual != py_expected, (
        "actual / expected hashes must diverge when streams differ"
    )


@requires_cli
def test_09_e2e_missing_record_detection_python_emit_rust_replay(tmp_path):
    """E2E missing-record-detection scenario.

    Actual stream has only the first 3 of 5 emitted records (steps
    3 and 4 dropped on the wire). Rust must surface two
    ``missing-in-actual`` divergences at steps 3 and 4, with
    ``time_to_divergence_steps == 3``.
    """
    expected_events = _emit_five_via_writer(tmp_path)
    actual_events = expected_events[:3]  # drop step-3 and step-4

    actual_path = tmp_path / "actual.jsonl"
    expected_path = tmp_path / "expected.jsonl"
    actual_path.write_bytes(records_to_jsonl_bytes(actual_events))
    expected_path.write_bytes(records_to_jsonl_bytes(expected_events))

    report = _run_replay_cli(actual_path, expected_path)
    assert report["success"] is False
    assert report["time_to_divergence_steps"] == 3
    assert report["divergence_count"] == 2
    for i, div in enumerate(report["divergences"]):
        step = 3 + i
        assert div["step_index"] == step
        assert div["kind"] == "missing-in-actual"
        assert div["actual_hash"] is None
        assert div["expected_hash"] is not None

    # Cross-lang pin: Python computes the same stream-hashes Rust does.
    assert report["stream_hash_actual"] == stream_hash(actual_events)
    assert report["stream_hash_expected"] == stream_hash(expected_events)


@requires_cli
def test_10_e2e_extra_record_detection_python_emit_rust_replay(tmp_path):
    """E2E extra-record symmetric to missing-record.

    Documents the symmetric drift case for the acceptance criterion:
    actual stream has MORE records than expected; Rust surfaces
    ``extra-in-actual`` divergences.
    """
    expected_events = _emit_five_via_writer(tmp_path)[:3]
    actual_events = _emit_five_via_writer(tmp_path)  # full 5

    actual_path = tmp_path / "actual.jsonl"
    expected_path = tmp_path / "expected.jsonl"
    actual_path.write_bytes(records_to_jsonl_bytes(actual_events))
    expected_path.write_bytes(records_to_jsonl_bytes(expected_events))

    report = _run_replay_cli(actual_path, expected_path)
    assert report["success"] is False
    assert report["time_to_divergence_steps"] == 3
    assert report["divergence_count"] == 2
    for i, div in enumerate(report["divergences"]):
        step = 3 + i
        assert div["step_index"] == step
        assert div["kind"] == "extra-in-actual"
        assert div["actual_hash"] is not None
        assert div["expected_hash"] is None


@requires_cli
def test_11_e2e_writer_to_cli_handles_pinned_fixture(tmp_path):
    """E2E pin: the canonical F3 fixture round-trips Python -> Rust
    with the documented anchor hash on both sides."""
    events = _f3_stream()
    actual_path = tmp_path / "f3.jsonl"
    actual_path.write_bytes(records_to_jsonl_bytes(events))

    report = _run_replay_cli(actual_path)
    assert report["success"] is True
    assert report["actual_record_count"] == 3
    assert report["stream_hash_actual"] == F3_STREAM_PIN
    assert report["stream_hash_expected"] == F3_STREAM_PIN


@requires_cli
def test_12_cli_skips_blank_jsonl_lines(tmp_path):
    """Operator-substrate hygiene: blank lines in JSONL are tolerated."""
    events = _f3_stream()
    body = records_to_jsonl_bytes(events)
    # Inject blank lines before, between, and after records.
    polluted = b"\n\n" + body + b"\n\n"
    actual_path = tmp_path / "polluted.jsonl"
    actual_path.write_bytes(polluted)

    report = _run_replay_cli(actual_path)
    assert report["success"] is True
    assert report["actual_record_count"] == 3
    assert report["stream_hash_actual"] == F3_STREAM_PIN


# ---------------------------------------------------------------------------
# Operator-substrate sanity (Cargo + binary presence).
# ---------------------------------------------------------------------------


def test_13_cli_discovery_resolves_in_normal_layouts():
    """Discovery is robust to either CARGO_TARGET_DIR or the default tree.

    This is a Python-only test (no subprocess). It is intentionally a
    soft check: if the binary is absent in this checkout we just
    verify that none of the candidate paths threw exceptions during
    construction. The dedicated CI lane (and a local `cargo build`)
    are what make the cross-language tests above runnable.
    """
    # Force re-discovery via the same helper to make sure no exception
    # leaks out across env-var perturbations.
    saved = os.environ.pop("WAKIR_REPLAY_CLI_BIN", None)
    try:
        # No binary pin -> falls through candidate list; must not raise.
        p = _discover_replay_cli()
        assert p is None or p.is_file()
    finally:
        if saved is not None:
            os.environ["WAKIR_REPLAY_CLI_BIN"] = saved


def test_14_cargo_workspace_lookup_when_not_skipped():
    """When the CLI is present, ensure the binary is executable.

    Sanity guard for CI lanes: if the lane built the binary, the
    discovery path must return something the OS can ``execve``. A
    ``False`` here means the binary was built without the executable
    bit, which has bitten us once already on cross-mount runners.
    """
    if REPLAY_CLI is None:
        pytest.skip("replay_cli not built; cross-lang lane not active")
    assert os.access(str(REPLAY_CLI), os.X_OK), (
        f"replay_cli at {REPLAY_CLI} must be executable"
    )
    # And the `which` discovery via PATH is not required for the test
    # (we use absolute paths) but a `which` hit would surprise nobody.
    _ = shutil.which("replay_cli")  # may be None; we don't assert.
