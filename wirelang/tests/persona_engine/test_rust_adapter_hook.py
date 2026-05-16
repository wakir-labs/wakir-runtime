# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the Rust persona-engine adapter hook skeleton.

Sprint-Rust-Adapter-Hook-Skeleton-MINI follow-on to PR #113
(:mod:`wirelang.persona_engine.bridge_audit_triangle`).

100% hermetic: no real Rust binary, no network, no time sources.
Subprocess invocations target a temp-dir stub-binary (a sh script
or a missing path) so the suite runs in any CI sandbox.

Coverage map (12 vectors, all ≥10-vector contract satisfied):

1.  Env-resolution: default binary path when env is empty.
2.  Env-resolution: ``WAKIR_RUST_ENGINE_BIN`` overrides default.
3.  Env-resolution: explicit constructor arg overrides env-var.
4.  Env-resolution: timeout default, env-var override, and
    explicit-arg override paths.
5.  ``available()`` returns ``False`` for missing path / non-
    executable file / non-existent executable.
6.  ``available()`` returns ``True`` for a real executable
    (chmod-+x sh-script in tmpdir).
7.  ``MockRustAdapterHook`` returns a deterministic CloudEvent
    envelope shaped identically to the Python-sink projection.
8.  ``MockRustAdapterHook.raise_on_compute`` raises the configured
    :class:`RustAdapterError`.
9.  ``SubprocessRustAdapterHook`` invokes the binary and parses
    JSON stdout into a CloudEventEnvelope (sh-script that echoes
    a canned JSON document).
10. ``SubprocessRustAdapterHook`` raises ``RustAdapterError`` with
    ``reason="exit_nonzero"`` when the binary exits non-zero.
11. ``SubprocessRustAdapterHook`` raises ``RustAdapterError`` with
    ``reason="bad_json"`` when stdout is not valid JSON.
12. ``SubprocessRustAdapterHook`` raises ``RustAdapterError`` with
    ``reason="bad_shape"`` when stdout is JSON but not a mapping.
13. ``SubprocessRustAdapterHook`` raises ``RustAdapterError`` with
    ``reason="timeout"`` when the binary exceeds the deadline
    (sleep-script + tiny timeout).
14. ``hook_to_implementation`` wraps the hook into a callable that
    accepts :class:`DiffInput` and forwards to ``compute_output``
    with base64-encoded payload bytes.
15. ``build_triangle_impl_c`` in ``2way`` mode returns the stub
    even when the hook is available (stub-only branch).
16. ``build_triangle_impl_c`` in ``3way`` mode with available hook
    returns the hook-backed implementation.
17. ``build_triangle_impl_c`` in ``3way`` mode with unavailable
    hook falls back to the stub and emits a WARNING log.
18. ``build_triangle_impl_c`` in ``3way`` mode with ``hook=None``
    falls back to the stub and emits a WARNING log.

Total: 18 hermetic vectors (≥10 required).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import stat
from pathlib import Path

import pytest

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffInput,
)
from wirelang.persona_engine.bridge_audit_triangle import (
    BRIDGE_MODE_ENV,
    BridgeMode,
)
from wirelang.persona_engine.rust_adapter_hook import (
    DEFAULT_RUST_ENGINE_BIN,
    DEFAULT_RUST_ENGINE_TIMEOUT_S,
    RUST_ENGINE_BIN_ENV,
    RUST_ENGINE_TIMEOUT_ENV,
    MockRustAdapterHook,
    RustAdapterError,
    SubprocessRustAdapterHook,
    build_triangle_impl_c,
    hook_to_implementation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _diff_input() -> DiffInput:
    return DiffInput(
        org_id="acme",
        persona_id="tomas",
        session_id="sess-xyz",
        step_index=3,
        output_kind="tool_call",
        payload=b"hello-payload",
        ts_utc="2026-05-16T17:30:00Z",
    )


def _write_script(
    tmp_path: Path,
    name: str,
    body: str,
    *,
    executable: bool = True,
) -> Path:
    """Write a sh-script to tmpdir and (optionally) chmod-+x it."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return path


# ---------------------------------------------------------------------------
# Vector 1-4: env-resolution
# ---------------------------------------------------------------------------


def test_env_resolution_defaults_when_empty(monkeypatch):
    """Vector 1: default binary path when env-var unset."""
    monkeypatch.delenv(RUST_ENGINE_BIN_ENV, raising=False)
    monkeypatch.delenv(RUST_ENGINE_TIMEOUT_ENV, raising=False)
    hook = SubprocessRustAdapterHook()
    assert hook.bin_path == DEFAULT_RUST_ENGINE_BIN
    assert hook.timeout_s == DEFAULT_RUST_ENGINE_TIMEOUT_S


def test_env_resolution_env_var_overrides_default(monkeypatch):
    """Vector 2: WAKIR_RUST_ENGINE_BIN env-var overrides default."""
    monkeypatch.setenv(RUST_ENGINE_BIN_ENV, "/opt/custom/rust-engine")
    monkeypatch.setenv(RUST_ENGINE_TIMEOUT_ENV, "12.5")
    hook = SubprocessRustAdapterHook()
    assert hook.bin_path == "/opt/custom/rust-engine"
    assert hook.timeout_s == 12.5


def test_env_resolution_explicit_arg_overrides_env(monkeypatch):
    """Vector 3: constructor arg wins over env-var."""
    monkeypatch.setenv(RUST_ENGINE_BIN_ENV, "/from/env")
    monkeypatch.setenv(RUST_ENGINE_TIMEOUT_ENV, "5.0")
    hook = SubprocessRustAdapterHook(
        bin_path="/explicit/path",
        timeout_s=7.5,
    )
    assert hook.bin_path == "/explicit/path"
    assert hook.timeout_s == 7.5


def test_env_resolution_bad_timeout_falls_back(monkeypatch, caplog):
    """Vector 4: non-positive / unparseable timeout falls back with warning."""
    monkeypatch.setenv(RUST_ENGINE_TIMEOUT_ENV, "not-a-number")
    with caplog.at_level(logging.WARNING):
        hook = SubprocessRustAdapterHook()
    assert hook.timeout_s == DEFAULT_RUST_ENGINE_TIMEOUT_S
    assert any("unparseable" in r.message for r in caplog.records)

    caplog.clear()
    monkeypatch.setenv(RUST_ENGINE_TIMEOUT_ENV, "-5.0")
    with caplog.at_level(logging.WARNING):
        hook2 = SubprocessRustAdapterHook()
    assert hook2.timeout_s == DEFAULT_RUST_ENGINE_TIMEOUT_S
    assert any("non-positive" in r.message for r in caplog.records)

    # Explicit non-positive constructor arg also degrades.
    monkeypatch.delenv(RUST_ENGINE_TIMEOUT_ENV, raising=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        hook3 = SubprocessRustAdapterHook(timeout_s=0)
    assert hook3.timeout_s == DEFAULT_RUST_ENGINE_TIMEOUT_S


# ---------------------------------------------------------------------------
# Vector 5-6: available()
# ---------------------------------------------------------------------------


def test_available_false_when_path_missing(tmp_path):
    """Vector 5a: missing path ⇒ available() is False."""
    hook = SubprocessRustAdapterHook(
        bin_path=str(tmp_path / "does-not-exist"),
    )
    assert hook.available() is False


def test_available_false_when_not_executable(tmp_path):
    """Vector 5b: non-executable file ⇒ available() is False."""
    p = tmp_path / "not-exec"
    p.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    # Strip execute bits.
    p.chmod(0o644)
    hook = SubprocessRustAdapterHook(bin_path=str(p))
    assert hook.available() is False


def test_available_false_empty_path():
    """Vector 5c: empty bin_path string ⇒ available() is False."""
    hook = SubprocessRustAdapterHook(bin_path="")
    assert hook.available() is False


def test_available_true_for_executable(tmp_path):
    """Vector 6: chmod-+x sh-script ⇒ available() is True."""
    p = _write_script(
        tmp_path,
        "rust-engine-stub.sh",
        "#!/bin/sh\nexit 0\n",
    )
    hook = SubprocessRustAdapterHook(bin_path=str(p))
    assert hook.available() is True


# ---------------------------------------------------------------------------
# Vector 7-8: MockRustAdapterHook
# ---------------------------------------------------------------------------


def test_mock_hook_returns_deterministic_envelope():
    """Vector 7: Mock returns canonical engineering-output envelope."""
    mock = MockRustAdapterHook()
    payload_b64 = base64.b64encode(b"hello-payload").decode("ascii")
    env = mock.compute_output(
        {
            "org_id": "acme",
            "persona_id": "tomas",
            "session_id": "s1",
            "step_index": 2,
            "output_kind": "reply",
            "payload_b64": payload_b64,
            "ts_utc": "2026-05-16T17:00:00Z",
            "schema": "wakir.persona.engineering-output/1",
        },
        persona_def="# tomas persona def",
    )
    assert env["event_kind"] == "engineering_output"
    assert env["org_id"] == "acme"
    assert env["persona_id"] == "tomas"
    assert env["session_id"] == "s1"
    assert env["step_index"] == 2
    assert env["output_kind"] == "reply"
    assert env["ts_utc"] == "2026-05-16T17:00:00Z"
    assert env["schema"] == "wakir.persona.engineering-output/1"
    # payload sha is deterministic
    assert env["output_payload_sha256"].startswith("sha256:")
    assert env["engine_version"] == "0.2.0-pilot-rust-stub"
    # capture log records the call
    assert len(mock.captured_calls) == 1
    assert mock.captured_calls[0][1] == "# tomas persona def"


def test_mock_hook_raise_on_compute():
    """Vector 8: raise_on_compute propagates the configured error."""
    err = RustAdapterError(reason="timeout", bin_path="/mock")
    mock = MockRustAdapterHook(raise_on_compute=err)
    with pytest.raises(RustAdapterError) as excinfo:
        mock.compute_output({}, persona_def="")
    assert excinfo.value.reason == "timeout"
    # Capture still records the call (caller-visibility for tests).
    assert len(mock.captured_calls) == 1


# ---------------------------------------------------------------------------
# Vector 9-13: SubprocessRustAdapterHook real subprocess
# ---------------------------------------------------------------------------


def test_subprocess_hook_happy_path(tmp_path):
    """Vector 9: subprocess returns JSON, parsed into envelope."""
    canned = {
        "engine_version": "0.2.0-pilot",
        "event_kind": "engineering_output",
        "org_id": "acme",
        "output_kind": "tool_call",
        "output_payload_sha256": "sha256:" + "b" * 64,
        "persona_id": "tomas",
        "schema": "wakir.persona.engineering-output/1",
        "session_id": "sess-xyz",
        "step_index": 3,
        "ts_utc": "2026-05-16T17:30:00Z",
        "v907_pin": "sha256:" + "a" * 64,
    }
    body = (
        "#!/bin/sh\n"
        "cat > /dev/null\n"
        f"cat <<'EOF'\n{json.dumps(canned)}\nEOF\n"
    )
    bin_path = _write_script(tmp_path, "ok.sh", body)
    hook = SubprocessRustAdapterHook(bin_path=str(bin_path))
    out = hook.compute_output(
        {
            "org_id": "acme",
            "persona_id": "tomas",
            "session_id": "sess-xyz",
            "step_index": 3,
            "output_kind": "tool_call",
            "payload_b64": base64.b64encode(b"x").decode("ascii"),
            "ts_utc": "2026-05-16T17:30:00Z",
        },
        persona_def="# def",
    )
    assert isinstance(out, dict)
    assert out["org_id"] == "acme"
    assert out["engine_version"] == "0.2.0-pilot"


def test_subprocess_hook_exit_nonzero(tmp_path):
    """Vector 10: non-zero exit ⇒ RustAdapterError(reason='exit_nonzero')."""
    body = "#!/bin/sh\ncat > /dev/null\necho 'boom' >&2\nexit 42\n"
    bin_path = _write_script(tmp_path, "nonzero.sh", body)
    hook = SubprocessRustAdapterHook(bin_path=str(bin_path))
    with pytest.raises(RustAdapterError) as excinfo:
        hook.compute_output({}, persona_def="")
    assert excinfo.value.reason == "exit_nonzero"
    assert excinfo.value.returncode == 42
    assert "boom" in excinfo.value.stderr


def test_subprocess_hook_bad_json(tmp_path):
    """Vector 11: stdout non-JSON ⇒ RustAdapterError(reason='bad_json')."""
    body = "#!/bin/sh\ncat > /dev/null\necho 'not-json-at-all'\n"
    bin_path = _write_script(tmp_path, "badjson.sh", body)
    hook = SubprocessRustAdapterHook(bin_path=str(bin_path))
    with pytest.raises(RustAdapterError) as excinfo:
        hook.compute_output({}, persona_def="")
    assert excinfo.value.reason == "bad_json"


def test_subprocess_hook_bad_shape(tmp_path):
    """Vector 12: stdout JSON-array (not a mapping) ⇒ 'bad_shape'."""
    body = "#!/bin/sh\ncat > /dev/null\necho '[1,2,3]'\n"
    bin_path = _write_script(tmp_path, "badshape.sh", body)
    hook = SubprocessRustAdapterHook(bin_path=str(bin_path))
    with pytest.raises(RustAdapterError) as excinfo:
        hook.compute_output({}, persona_def="")
    assert excinfo.value.reason == "bad_shape"


def test_subprocess_hook_timeout(tmp_path):
    """Vector 13: subprocess that sleeps past the deadline ⇒ 'timeout'."""
    body = "#!/bin/sh\ncat > /dev/null\nsleep 5\necho '{}'\n"
    bin_path = _write_script(tmp_path, "slow.sh", body)
    hook = SubprocessRustAdapterHook(
        bin_path=str(bin_path), timeout_s=0.5
    )
    with pytest.raises(RustAdapterError) as excinfo:
        hook.compute_output({}, persona_def="")
    assert excinfo.value.reason == "timeout"


def test_subprocess_hook_not_available_short_circuits():
    """Bonus: compute_output on a not-available hook raises 'not_available'."""
    hook = SubprocessRustAdapterHook(bin_path="/no/such/binary")
    with pytest.raises(RustAdapterError) as excinfo:
        hook.compute_output({}, persona_def="")
    assert excinfo.value.reason == "not_available"


# ---------------------------------------------------------------------------
# Vector 14: hook_to_implementation
# ---------------------------------------------------------------------------


def test_hook_to_implementation_translates_diff_input():
    """Vector 14: Implementation wrapper feeds the hook a base64-payload dict."""
    mock = MockRustAdapterHook()
    impl = hook_to_implementation(mock, persona_def="# persona body")
    out = impl(_diff_input())
    assert out["org_id"] == "acme"
    assert out["persona_id"] == "tomas"
    assert out["session_id"] == "sess-xyz"
    assert out["step_index"] == 3
    # Hook saw base64-encoded payload + the persona_def.
    payload_arg, persona_arg = mock.captured_calls[0]
    assert persona_arg == "# persona body"
    assert payload_arg["payload_b64"] == base64.b64encode(
        b"hello-payload"
    ).decode("ascii")


# ---------------------------------------------------------------------------
# Vector 15-18: build_triangle_impl_c
# ---------------------------------------------------------------------------


def test_build_triangle_impl_c_2way_returns_stub(monkeypatch):
    """Vector 15: 2way mode returns the stub regardless of hook state."""
    monkeypatch.setenv(BRIDGE_MODE_ENV, BridgeMode.TWO_WAY)
    mock = MockRustAdapterHook(is_available=True)
    impl = build_triangle_impl_c(mock)
    out = impl(_diff_input())
    # Stub uses engine_version "0.2.0-pilot" by default; mock would
    # use "0.2.0-pilot-rust-stub".
    assert out["engine_version"] == "0.2.0-pilot"
    # And the mock was NOT consulted.
    assert mock.captured_calls == []


def test_build_triangle_impl_c_3way_available_routes_to_hook(monkeypatch):
    """Vector 16: 3way + available hook ⇒ hook-backed impl."""
    monkeypatch.setenv(BRIDGE_MODE_ENV, BridgeMode.THREE_WAY)
    mock = MockRustAdapterHook(is_available=True)
    impl = build_triangle_impl_c(mock, persona_def="# pd")
    out = impl(_diff_input())
    # Mock's default engine_version surfaces (proves hook-backed path).
    assert out["engine_version"] == "0.2.0-pilot-rust-stub"
    assert len(mock.captured_calls) == 1


def test_build_triangle_impl_c_3way_unavailable_falls_back(
    monkeypatch, caplog
):
    """Vector 17: 3way + unavailable hook ⇒ stub + WARNING log."""
    monkeypatch.setenv(BRIDGE_MODE_ENV, BridgeMode.THREE_WAY)
    mock = MockRustAdapterHook(is_available=False)
    with caplog.at_level(logging.WARNING):
        impl = build_triangle_impl_c(mock)
    out = impl(_diff_input())
    # Stub path (no -rust-stub suffix).
    assert out["engine_version"] == "0.2.0-pilot"
    assert mock.captured_calls == []
    assert any(
        "not available" in r.message for r in caplog.records
    )


def test_build_triangle_impl_c_3way_no_hook_falls_back(
    monkeypatch, caplog
):
    """Vector 18: 3way + hook=None ⇒ stub + WARNING log."""
    monkeypatch.setenv(BRIDGE_MODE_ENV, BridgeMode.THREE_WAY)
    with caplog.at_level(logging.WARNING):
        impl = build_triangle_impl_c(None)
    out = impl(_diff_input())
    assert out["engine_version"] == "0.2.0-pilot"
    assert any(
        "without hook" in r.message for r in caplog.records
    )
