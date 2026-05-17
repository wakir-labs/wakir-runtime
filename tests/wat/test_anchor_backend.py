# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Unit tests for the WAT anchor-submit backend dispatcher.

Tag-16 Mini-Welle — Phase-3b production-wiring acceptance gate.

The dispatcher under test is ``wat.anchor.anchor_backend``. It routes
``anchor_root`` calls between the legacy in-process Python flow
(``WAKIR_ANCHOR_BACKEND=python``, the default) and the Rust
``submit_worker`` binary (``WAKIR_ANCHOR_BACKEND=rust_submit_worker``).

Hermetic posture
----------------

* Every subprocess call is patched at module boundary (no real
  ``ots`` calls, no real binary spawn unless the test explicitly
  covers the "binary missing" path).
* The Rust binary is *not* required to be built for these tests; the
  ``_run_submit_worker`` indirection is patched directly.
* The single test that does exercise the real binary
  (``test_real_binary_smoke_ots_cli_path_aborts_without_ots``) is
  guarded behind a ``WAKIR_SUBMIT_WORKER_BIN`` environment lookup
  and skips cleanly when the binary is not on disk. CI is expected to
  build the binary before invoking this suite (mirroring the
  Tag-14 ``replay_cli`` pattern in ``.github/workflows/tests.yml``).

Test inventory (12 tests, covers the five Sprint-Auftrag-named cases
plus seven dispatcher invariants):

    Sprint-Auftrag-named:
      1.  test_backend_python_default_noop_passthrough
      2.  test_backend_rust_success_path
      3.  test_backend_rust_throttled_passthrough
      4.  test_backend_rust_dead_letter_emits_error
      5.  test_backend_rust_binary_missing_fallback_python

    Dispatcher invariants:
      6.  test_unknown_backend_value_falls_back_to_python
      7.  test_resolve_binary_prefers_explicit_env
      8.  test_resolve_binary_warns_on_invalid_explicit_path
      9.  test_rust_retrying_translates_to_anchor_error
      10. test_rust_idle_translates_to_anchor_error
      11. test_rust_subprocess_timeout_surfaces_as_anchor_error
      12. test_rust_malformed_stdout_surfaces_as_anchor_error
      13. test_real_binary_smoke_ots_cli_path_aborts_without_ots
"""

from __future__ import annotations

import json
import os
import subprocess
import warnings
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest

from wat.anchor import anchor_backend, ots_anchor
from wat.anchor.anchor_backend import (
    ALLOWED_BACKENDS,
    BACKEND_PYTHON,
    BACKEND_RUST,
    BridgeResult,
    ENV_BACKEND,
    ENV_SUBMIT_WORKER_BIN,
    anchor_root_via_backend,
    resolve_submit_worker_binary,
    selected_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def root32() -> bytes:
    """32-byte test Merkle root. Distinguishable per-byte for diagnostics."""
    return bytes(range(32))


@pytest.fixture
def calendars() -> list[str]:
    """Two stable calendar URLs — the dispatcher only echoes these."""
    return [
        "https://alice.btc.calendar.opentimestamps.org",
        "https://bob.btc.calendar.opentimestamps.org",
    ]


@pytest.fixture
def empty_env_getenv():
    """``getenv`` stub returning None for everything (clean slate)."""

    def _getenv(_key: str) -> Optional[str]:
        return None

    return _getenv


def _fake_bridge_result(
    *,
    result_kind: str,
    event_id: str = "test-event",
    attempt: Optional[int] = None,
    next_delay_secs: Optional[int] = None,
    terminal_error: Optional[str] = None,
    receipt_path: Optional[str] = None,
) -> BridgeResult:
    return BridgeResult(
        result_kind=result_kind,
        event_id=event_id,
        attempt=attempt,
        next_delay_secs=next_delay_secs,
        terminal_error=terminal_error,
        receipt_path=receipt_path,
    )


# ---------------------------------------------------------------------------
# Sprint-Auftrag-named test 1: backend=python default is a no-op passthrough.
# ---------------------------------------------------------------------------


def test_backend_python_default_noop_passthrough(
    tmp_path: Path, root32: bytes, calendars: list[str], empty_env_getenv
) -> None:
    """When ``WAKIR_ANCHOR_BACKEND`` is unset, the dispatcher delegates
    straight to ``ots_anchor.anchor_root`` and returns its receipt."""
    sentinel_receipt = ots_anchor.AnchorReceipt(
        merkle_root=root32,
        submission_time="2026-05-17T10:00:00Z",
        calendar_responses={u: "ok" for u in calendars},
        receipt_path=tmp_path / "root.bin.ots",
    )

    with mock.patch.object(
        ots_anchor, "anchor_root", return_value=sentinel_receipt
    ) as patched:
        receipt = anchor_root_via_backend(
            merkle_root=root32,
            calendars=calendars,
            min_calendars=2,
            target_dir=tmp_path,
            getenv=empty_env_getenv,
        )

    assert patched.called, "python backend must call ots_anchor.anchor_root"
    assert receipt.merkle_root == root32
    assert receipt.calendar_responses == {u: "ok" for u in calendars}
    assert receipt.submission_time == "2026-05-17T10:00:00Z"
    assert receipt.successful_calendars() == calendars


# ---------------------------------------------------------------------------
# Sprint-Auftrag-named test 2: backend=rust success path.
# ---------------------------------------------------------------------------


def test_backend_rust_success_path(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    """A ``success`` bridge result produces an AnchorReceiptLike whose
    receipt_path mirrors the binary-reported path."""
    fake_receipt_path = str(tmp_path / "root.bin.ots")

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(tmp_path / "fake_submit_worker_bin")
        return None

    # Materialise the "binary" as an actual file so the resolver
    # accepts it.
    (tmp_path / "fake_submit_worker_bin").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(tmp_path / "fake_submit_worker_bin", 0o755)

    bridge = _fake_bridge_result(
        result_kind="success",
        event_id="wat-anchor-2026051710-000102030405",
        receipt_path=fake_receipt_path,
    )

    with mock.patch.object(
        anchor_backend, "_run_submit_worker", return_value=bridge
    ) as patched:
        receipt = anchor_root_via_backend(
            merkle_root=root32,
            calendars=calendars,
            min_calendars=2,
            target_dir=tmp_path,
            persona_id="wat-anchor-cron",
            event_id="wat-anchor-2026051710-000102030405",
            getenv=_getenv,
        )

    assert patched.called, "rust backend must invoke _run_submit_worker"
    assert receipt.merkle_root == root32
    assert str(receipt.receipt_path) == fake_receipt_path
    assert receipt.successful_calendars() == calendars
    # The JSON payload passed to the binary should carry the hex root.
    (_, kwargs) = patched.call_args_list[0][0], patched.call_args_list[0][1]
    payload_arg = patched.call_args_list[0][0][1]
    parsed = json.loads(payload_arg)
    assert parsed["payload_root_hex"] == root32.hex()
    assert parsed["calendars"] == calendars
    assert parsed["min_calendars"] == 2
    assert parsed["target_dir"] == str(tmp_path)


# ---------------------------------------------------------------------------
# Sprint-Auftrag-named test 3: backend=rust throttled passthrough.
# ---------------------------------------------------------------------------


def test_backend_rust_throttled_passthrough(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    """A ``throttled`` bridge result translates to an AnchorError tagged
    with the event id so the cron can retry on the next tick."""
    binary = tmp_path / "fake_submit_worker_bin"
    binary.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    bridge = _fake_bridge_result(
        result_kind="throttled", event_id="wat-anchor-throttled"
    )

    with mock.patch.object(
        anchor_backend, "_run_submit_worker", return_value=bridge
    ):
        with pytest.raises(ots_anchor.AnchorError, match="throttled"):
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )


# ---------------------------------------------------------------------------
# Sprint-Auftrag-named test 4: backend=rust dead-letter emits error.
# ---------------------------------------------------------------------------


def test_backend_rust_dead_letter_emits_error(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    """A ``dead`` bridge result with terminal_error surfaces as an
    AnchorError carrying that error string."""
    binary = tmp_path / "fake_submit_worker_bin"
    binary.write_text("#!/bin/sh\nexit 1\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    bridge = _fake_bridge_result(
        result_kind="dead",
        event_id="wat-anchor-dead",
        terminal_error="mock_permanent transport",
    )

    with mock.patch.object(
        anchor_backend, "_run_submit_worker", return_value=bridge
    ):
        with pytest.raises(ots_anchor.AnchorError) as excinfo:
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )
    assert "dead-lettered" in str(excinfo.value)
    assert "mock_permanent transport" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Sprint-Auftrag-named test 5: rust backend with missing binary falls back.
# ---------------------------------------------------------------------------


def test_backend_rust_binary_missing_fallback_python(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    """When backend=rust_submit_worker but no binary is resolvable,
    the dispatcher warns and falls back to the python backend."""

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        return None  # ENV_SUBMIT_WORKER_BIN unset

    sentinel_receipt = ots_anchor.AnchorReceipt(
        merkle_root=root32,
        submission_time="2026-05-17T11:00:00Z",
        calendar_responses={u: "ok" for u in calendars},
        receipt_path=tmp_path / "root.bin.ots",
    )

    # Make shutil.which always return None to simulate "binary not on
    # PATH" (resolver short-circuits before any real PATH lookup).
    with mock.patch.object(
        anchor_backend.shutil, "which", return_value=None
    ), mock.patch.object(
        ots_anchor, "anchor_root", return_value=sentinel_receipt
    ) as patched_python:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            receipt = anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )

    assert patched_python.called, "must fall back to legacy python backend"
    assert receipt.merkle_root == root32
    msgs = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert any("submit_worker binary not resolvable" in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# Dispatcher invariant 6: unknown backend value warns and falls back.
# ---------------------------------------------------------------------------


def test_unknown_backend_value_falls_back_to_python() -> None:
    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return "rust_typo_backend"
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        backend = selected_backend(getenv=_getenv)

    assert backend == BACKEND_PYTHON
    msgs = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert any("unknown" in m and "rust_typo_backend" in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# Dispatcher invariant 7: explicit env path is preferred over PATH.
# ---------------------------------------------------------------------------


def test_resolve_binary_prefers_explicit_env(tmp_path: Path) -> None:
    explicit = tmp_path / "my_submit_worker"
    explicit.write_text("#!/bin/sh\n")
    os.chmod(explicit, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(explicit)
        return None

    found = resolve_submit_worker_binary(
        getenv=_getenv,
        which=lambda _name: "/usr/bin/should-not-be-picked",
    )
    assert found == str(explicit)


# ---------------------------------------------------------------------------
# Dispatcher invariant 8: invalid explicit path warns and falls through.
# ---------------------------------------------------------------------------


def test_resolve_binary_warns_on_invalid_explicit_path(tmp_path: Path) -> None:
    bad = tmp_path / "does_not_exist"

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(bad)
        return None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        found = resolve_submit_worker_binary(getenv=_getenv, which=lambda _: None)
    assert found is None
    msgs = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert any("does not point at a file" in m for m in msgs), msgs


# ---------------------------------------------------------------------------
# Dispatcher invariant 9: retrying -> AnchorError carrying attempt + delay.
# ---------------------------------------------------------------------------


def test_rust_retrying_translates_to_anchor_error(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    binary = tmp_path / "fake_bin"
    binary.write_text("#!/bin/sh\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    bridge = _fake_bridge_result(
        result_kind="retrying",
        event_id="ev",
        attempt=3,
        next_delay_secs=42,
    )
    with mock.patch.object(
        anchor_backend, "_run_submit_worker", return_value=bridge
    ):
        with pytest.raises(ots_anchor.AnchorError) as excinfo:
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )
    msg = str(excinfo.value)
    assert "attempt=3" in msg
    assert "next_delay_secs=42" in msg


# ---------------------------------------------------------------------------
# Dispatcher invariant 10: idle is a soft anomaly -> AnchorError.
# ---------------------------------------------------------------------------


def test_rust_idle_translates_to_anchor_error(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    binary = tmp_path / "fake_bin"
    binary.write_text("#!/bin/sh\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    bridge = _fake_bridge_result(result_kind="idle", event_id="ev-idle")
    with mock.patch.object(
        anchor_backend, "_run_submit_worker", return_value=bridge
    ):
        with pytest.raises(ots_anchor.AnchorError, match="idle"):
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )


# ---------------------------------------------------------------------------
# Dispatcher invariant 11: subprocess.TimeoutExpired -> AnchorError.
# ---------------------------------------------------------------------------


def test_rust_subprocess_timeout_surfaces_as_anchor_error(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    binary = tmp_path / "fake_bin"
    binary.write_text("#!/bin/sh\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=[str(binary)], timeout=90)

    with mock.patch.object(
        anchor_backend.subprocess, "run", side_effect=_raise_timeout
    ):
        with pytest.raises(ots_anchor.AnchorError, match="timed out"):
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )


# ---------------------------------------------------------------------------
# Dispatcher invariant 12: malformed binary stdout -> AnchorError.
# ---------------------------------------------------------------------------


def test_rust_malformed_stdout_surfaces_as_anchor_error(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    binary = tmp_path / "fake_bin"
    binary.write_text("#!/bin/sh\n")
    os.chmod(binary, 0o755)

    def _getenv(k: str) -> Optional[str]:
        if k == ENV_BACKEND:
            return BACKEND_RUST
        if k == ENV_SUBMIT_WORKER_BIN:
            return str(binary)
        return None

    proc = subprocess.CompletedProcess(
        args=[str(binary)],
        returncode=0,
        stdout="not json at all\n",
        stderr="",
    )
    with mock.patch.object(
        anchor_backend.subprocess, "run", return_value=proc
    ):
        with pytest.raises(ots_anchor.AnchorError, match="malformed JSON"):
            anchor_root_via_backend(
                merkle_root=root32,
                calendars=calendars,
                min_calendars=2,
                target_dir=tmp_path,
                getenv=_getenv,
            )


# ---------------------------------------------------------------------------
# Dispatcher invariant 13: real-binary smoke (when CI has it built).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("WAKIR_SUBMIT_WORKER_BIN"),
    reason=(
        "WAKIR_SUBMIT_WORKER_BIN unset — skip real-binary smoke; CI sets "
        "this after `cargo build --bin submit_worker` (see workflows/tests.yml)."
    ),
)
def test_real_binary_smoke_ots_cli_path_aborts_without_ots(
    tmp_path: Path, root32: bytes, calendars: list[str]
) -> None:
    """End-to-end smoke: spawn the real binary with the default
    ``ots_cli`` transport. With ``ots`` NOT on PATH (CI deliberately
    does not install opentimestamps-client for this lane), the binary
    must exit 3 with a clear error — proving the bridge wires up
    correctly even on the negative path."""
    bin_path = os.environ["WAKIR_SUBMIT_WORKER_BIN"]
    assert Path(bin_path).is_file(), f"binary missing at {bin_path!r}"

    # Force ots out of PATH for this subprocess invocation. We
    # construct a sanitised PATH that excludes any directory the host
    # may have where `ots` lives. Easiest: empty PATH (the binary will
    # still find /lib loader resolution via the linker, just not
    # `ots`).
    env = {**os.environ, "PATH": "/nonexistent", "WAKIR_SUBMIT_WORKER_TRANSPORT": "ots_cli"}
    payload = {
        "event_id": "smoke-test",
        "timestamp_utc": "2026-05-17T10:00:00Z",
        "persona_id": "wat-anchor-cron",
        "payload_root_hex": root32.hex(),
        "calendars": list(calendars),
        "min_calendars": 2,
        "target_dir": str(tmp_path),
    }
    proc = subprocess.run(
        [bin_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )
    assert proc.returncode == 3, (
        f"expected exit 3 (ots-missing internal-config error), got "
        f"{proc.returncode}; stderr={proc.stderr!r} stdout={proc.stdout!r}"
    )
    assert "ots binary not on PATH" in proc.stderr


# ---------------------------------------------------------------------------
# Sanity: the allowed-backends tuple matches what the dispatcher accepts.
# ---------------------------------------------------------------------------


def test_allowed_backends_tuple_matches_constants() -> None:
    assert set(ALLOWED_BACKENDS) == {BACKEND_PYTHON, BACKEND_RUST}
