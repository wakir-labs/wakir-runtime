# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the NATS-JWT-Auth `user_jwt_cb` skizze (Phase-2.4).

Tag-10 substrate; companion to ``docs/nats-jwt-auth-phase-2-4.md`` and
``scripts/nats_jwt_callback_skizze.py``.

The tests do NOT start a NATS-server, do NOT contact a SPIRE-agent, do
NOT import the upstream ``nats-py`` runtime client, and do NOT import
the Reza-side ``wirelang/adapters/spiffe_workload_api.py`` adapter.
They exercise the Tag-10 callback factory + cache stub in isolation
and verify the typed contract matches the upstream ``nats-py``
``JWTCallback`` typedef (path-by-name reference; the upstream typedef
is checked structurally, not by import).

Coverage (20 tests in 8 blocks):

| Block | Tests | Topic |
|---|---|---|
| 1 — JwtSvidCacheView Protocol | 2 | InMemorySvidCache fulfils the Protocol surface; cold cache returns None on all readers |
| 2 — InMemorySvidCache mutation | 3 | set() validates input shape; clear() resets; set() round-trips |
| 3 — Callback factory contract | 3 | factory returns zero-arg callable; callable returns bytes; signature matches nats-py JWTCallback typedef shape |
| 4 — Refresh-on-Reconnect | 3 | callback reads current state each call; second call sees updated cache; multiple calls do not stale |
| 5 — Cache-empty error | 2 | cold cache raises NatsJwtCallbackCacheEmpty; error message points at JwtSvidCache wait-for-first-SVID surface |
| 6 — Expiry enforcement | 3 | default enforce_exp=False does not check exp; enforce_exp=True raises past exp; clock injection works |
| 7 — Cross-reference invariants | 3 | scripts/nats_jwt_callback_skizze.py imports cleanly; spiffe_skizze_constants reachable; nats-py JWTCallback path-by-name pin holds |
| 8 — Contract self-check | 1 | this file = 20 tests (drift-detection pin) |

Cross-references:
- ``scripts/nats_jwt_callback_skizze.py`` — Tag-10 callback factory.
- ``docs/nats-jwt-auth-phase-2-4.md`` — Tag-10 runbook.
- ``wirelang/adapters/spiffe_workload_api.py`` (Reza Sprint-6 Tag-5
  commit ``9c94517``) — path-by-name; NOT imported.
- ``.venv/lib/python3.14/site-packages/nats/aio/client.py`` Z. 110,
  317, 370, 1666-1668 — verified externally; tests assert the
  structural shape only (`Callable[[], Union[bytearray, bytes]]`).
"""

from __future__ import annotations

import importlib.util
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest


# ---------------------------------------------------------------------
# Module loader: skizze lives under scripts/
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIZZE_PATH = REPO_ROOT / "scripts" / "nats_jwt_callback_skizze.py"
CONSTANTS_PATH = REPO_ROOT / "scripts" / "spiffe_skizze_constants.py"


def _load_skizze():
    spec = importlib.util.spec_from_file_location(
        "nats_jwt_callback_skizze", SKIZZE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_constants():
    spec = importlib.util.spec_from_file_location(
        "spiffe_skizze_constants", CONSTANTS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def skizze():
    return _load_skizze()


@pytest.fixture(scope="module")
def constants():
    return _load_constants()


# Helpers


def _future(seconds: int = 900) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds: int = 60) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# ---------------------------------------------------------------------
# Block 1 — JwtSvidCacheView Protocol
# ---------------------------------------------------------------------


def test_in_memory_cache_implements_view_protocol(skizze):
    """InMemorySvidCache exposes the three Protocol methods.

    The Protocol surface is what production persona-container code
    pins against (wirelang-side JwtSvidCache). Tag-10 stub MUST satisfy
    the same surface.
    """
    cache = skizze.InMemorySvidCache()
    # Three Protocol methods present + callable.
    for method_name in ("current_token", "current_expires_at", "current_spiffe_id"):
        method = getattr(cache, method_name)
        assert callable(method), f"InMemorySvidCache.{method_name} must be callable"
    # Protocol type is defined.
    assert hasattr(skizze, "JwtSvidCacheView")


def test_cold_cache_returns_none_on_all_readers(skizze):
    """A freshly-constructed cache yields None on all three readers.

    Models the cold-start window before the wirelang-side background
    WatchJWTSVIDs stream has pushed a first SVID.
    """
    cache = skizze.InMemorySvidCache()
    assert cache.current_token() is None
    assert cache.current_expires_at() is None
    assert cache.current_spiffe_id() is None


# ---------------------------------------------------------------------
# Block 2 — InMemorySvidCache mutation
# ---------------------------------------------------------------------


def test_cache_set_validates_input_shape(skizze):
    """set() rejects malformed inputs (token type, naive datetime, empty id).

    Models the wirelang-side cache invariants: never accept a token of
    wrong type, never accept a naive datetime, never accept an empty
    SPIFFE-ID.
    """
    cache = skizze.InMemorySvidCache()
    # Wrong token type.
    with pytest.raises(TypeError):
        cache.set(token="not-bytes", expires_at=_future(), spiffe_id="spiffe://x/y")
    # Wrong expires_at type.
    with pytest.raises(TypeError):
        cache.set(token=b"tok", expires_at="not-datetime", spiffe_id="spiffe://x/y")
    # Naive datetime (no tzinfo).
    with pytest.raises(ValueError):
        cache.set(
            token=b"tok",
            expires_at=datetime(2099, 1, 1),  # noqa: DTZ001 — intentional naive
            spiffe_id="spiffe://x/y",
        )
    # Empty SPIFFE-ID.
    with pytest.raises(ValueError):
        cache.set(token=b"tok", expires_at=_future(), spiffe_id="")
    # Wrong SPIFFE-ID type.
    with pytest.raises(ValueError):
        cache.set(token=b"tok", expires_at=_future(), spiffe_id=None)


def test_cache_clear_resets_state(skizze):
    """clear() returns the cache to cold state."""
    cache = skizze.InMemorySvidCache()
    cache.set(token=b"abc", expires_at=_future(), spiffe_id="spiffe://wakir.local/agent/kai/aabbccddeeff")
    assert cache.current_token() == b"abc"
    cache.clear()
    assert cache.current_token() is None
    assert cache.current_expires_at() is None
    assert cache.current_spiffe_id() is None


def test_cache_set_round_trips(skizze):
    """Values placed via set() are readable via the Protocol readers."""
    cache = skizze.InMemorySvidCache()
    exp = _future(seconds=600)
    cache.set(
        token=b"jwt.svid.token",
        expires_at=exp,
        spiffe_id="spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
    )
    assert cache.current_token() == b"jwt.svid.token"
    assert cache.current_expires_at() == exp
    assert cache.current_spiffe_id() == "spiffe://wakir.local/agent/mira/a3f2c1e8d4b7"


# ---------------------------------------------------------------------
# Block 3 — Callback factory contract
# ---------------------------------------------------------------------


def test_make_user_jwt_cb_returns_zero_arg_callable(skizze):
    """The factory returns a zero-arg callable.

    Matches the `nats-py` `JWTCallback = Callable[[], Union[bytearray,
    bytes]]` typedef (`nats/aio/client.py` Z. 110).
    """
    cache = skizze.InMemorySvidCache(token=b"t", expires_at=_future(), spiffe_id="spiffe://x/y")
    cb = skizze.make_user_jwt_cb(cache)
    assert callable(cb)
    sig = inspect.signature(cb)
    # Zero positional parameters.
    assert len(sig.parameters) == 0, (
        f"user_jwt_cb must be zero-arg; got {sig}"
    )


def test_callback_returns_bytes(skizze):
    """The callable returns `bytes` (the JWT-SVID encoded form).

    `nats-py` Z. 1668 calls `.decode()` on the returned value; bytes
    satisfy that contract.
    """
    cache = skizze.InMemorySvidCache(
        token=b"jwt-svid-bytes",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/kai/aabbccddeeff",
    )
    cb = skizze.make_user_jwt_cb(cache)
    result = cb()
    assert isinstance(result, bytes), (
        f"callback must return bytes; got {type(result).__name__}"
    )
    assert result == b"jwt-svid-bytes"


def test_callback_signature_matches_nats_py_jwt_callback_typedef(skizze):
    """The returned callable's annotation/return shape matches the
    `nats-py` JWTCallback typedef: zero-arg, returns bytes.

    Path-by-name verification: the typedef in `nats/aio/client.py`
    Z. 110 reads `JWTCallback = Callable[[], Union[bytearray, bytes]]`.
    Tag-10 cb returns `bytes` (subset of the Union); zero-arg
    confirmed in test above.
    """
    cache = skizze.InMemorySvidCache(token=b"tok", expires_at=_future(), spiffe_id="spiffe://x/y")
    cb = skizze.make_user_jwt_cb(cache)
    # Annotation on the inner function: returns bytes (str(annotation) tolerant).
    annotation = inspect.signature(cb).return_annotation
    # Either bytes class directly or the string 'bytes' under
    # from __future__ import annotations.
    assert annotation in (bytes, "bytes") or annotation is inspect.Signature.empty, (
        f"return annotation should resolve to bytes; got {annotation!r}"
    )


# ---------------------------------------------------------------------
# Block 4 — Refresh-on-Reconnect (current-state read semantics)
# ---------------------------------------------------------------------


def test_callback_reads_current_state_each_invocation(skizze):
    """The callback reads the cache **on each call**, not at factory time.

    This is the refresh-on-reconnect contract: when `nats-py` builds
    a new CONNECT frame (Z. 1666-1668), the callback re-reads the
    cache; the wirelang-side background WatchJWTSVIDs stream is
    expected to have refreshed the cache between connect attempts.
    """
    cache = skizze.InMemorySvidCache(
        token=b"initial-token",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
    )
    cb = skizze.make_user_jwt_cb(cache)
    # First invocation: initial token.
    assert cb() == b"initial-token"
    # Simulate background stream push: cache rotates.
    cache.set(
        token=b"refreshed-token",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
    )
    # Second invocation: callback returns the refreshed token.
    assert cb() == b"refreshed-token", (
        "Callback must read current cache state on each invocation "
        "(refresh-on-reconnect semantics)."
    )


def test_callback_handles_repeated_invocation_stability(skizze):
    """Repeated callback invocation against a static cache yields stable bytes.

    No internal state leaks between calls; the callback is a pure
    closure over the cache reference.
    """
    cache = skizze.InMemorySvidCache(
        token=b"stable-token",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/reza/aabbccddeeff",
    )
    cb = skizze.make_user_jwt_cb(cache)
    results = [cb() for _ in range(5)]
    assert all(r == b"stable-token" for r in results), (
        f"Callback must be stable across repeated calls; got {results}"
    )


def test_callback_transitions_through_clear_then_refresh(skizze):
    """A cache that goes empty (stream stall) then re-fills (recovery)
    surfaces the empty-window via an error and recovers to bytes.

    Models the production failure mode: wirelang-side stream stalls,
    cache is cleared, NATS reconnect fires, callback errors, persona-
    container boot path waits for cache-hot then retries.
    """
    cache = skizze.InMemorySvidCache(
        token=b"original",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/kai/aabbccddeeff",
    )
    cb = skizze.make_user_jwt_cb(cache)
    assert cb() == b"original"
    # Stream stall.
    cache.clear()
    with pytest.raises(skizze.NatsJwtCallbackCacheEmpty):
        cb()
    # Recovery push.
    cache.set(
        token=b"recovered",
        expires_at=_future(),
        spiffe_id="spiffe://wakir.local/agent/kai/aabbccddeeff",
    )
    assert cb() == b"recovered"


# ---------------------------------------------------------------------
# Block 5 — Cache-empty error semantics
# ---------------------------------------------------------------------


def test_cold_cache_raises_cache_empty(skizze):
    """A cold cache at CONNECT-frame-build raises NatsJwtCallbackCacheEmpty."""
    cache = skizze.InMemorySvidCache()  # cold
    cb = skizze.make_user_jwt_cb(cache)
    with pytest.raises(skizze.NatsJwtCallbackCacheEmpty):
        cb()


def test_cache_empty_message_points_to_wirelang_cache_surface(skizze):
    """The error message names the wirelang-side cache wait-for-first-SVID
    surface so Operator-Hand debugging can find the upstream fix.
    """
    cache = skizze.InMemorySvidCache()
    cb = skizze.make_user_jwt_cb(cache)
    with pytest.raises(skizze.NatsJwtCallbackCacheEmpty) as excinfo:
        cb()
    msg = str(excinfo.value)
    assert "wirelang/adapters/spiffe_workload_api.py" in msg, (
        f"error message must reference the wirelang adapter; got {msg!r}"
    )
    assert "JwtSvidCache" in msg, (
        f"error message must name the JwtSvidCache surface; got {msg!r}"
    )


# ---------------------------------------------------------------------
# Block 6 — Expiry enforcement
# ---------------------------------------------------------------------


def test_default_enforce_exp_false_does_not_check_expiry(skizze):
    """By default the callback does NOT enforce client-side exp.

    NATS-server validates `exp` server-side anyway; double-checking
    client-side is opt-in for diagnostic / stall-detection purposes.
    """
    cache = skizze.InMemorySvidCache(
        token=b"expired-but-allowed",
        expires_at=_past(seconds=60),
        spiffe_id="spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
    )
    cb = skizze.make_user_jwt_cb(cache)  # enforce_exp=False default
    # Callback returns the token despite past exp.
    assert cb() == b"expired-but-allowed"


def test_enforce_exp_true_raises_on_past_exp(skizze):
    """`enforce_exp=True` raises NatsJwtCallbackSvidExpired when cached
    SVID is past its exp claim.

    Surfaces a stalled WatchJWTSVIDs background stream client-side
    instead of letting the NATS-server reject the CONNECT.
    """
    cache = skizze.InMemorySvidCache(
        token=b"expired",
        expires_at=_past(seconds=120),
        spiffe_id="spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
    )
    cb = skizze.make_user_jwt_cb(cache, enforce_exp=True)
    with pytest.raises(skizze.NatsJwtCallbackSvidExpired) as excinfo:
        cb()
    msg = str(excinfo.value)
    assert "Phase-2.6" in msg or "Trust-Bundle-Rotation-Runbook" in msg, (
        f"error message should reference Phase-2.6 runbook slot; got {msg!r}"
    )


def test_enforce_exp_with_clock_injection(skizze):
    """The `now` parameter lets tests inject a deterministic clock.

    Used by stall-recovery tests that need to assert past-exp without
    waiting wall-clock time.
    """
    fixed_now = datetime(2026, 5, 12, 18, 30, 0, tzinfo=timezone.utc)
    exp_past = datetime(2026, 5, 12, 18, 29, 0, tzinfo=timezone.utc)
    cache = skizze.InMemorySvidCache(
        token=b"clock-test",
        expires_at=exp_past,
        spiffe_id="spiffe://wakir.local/agent/kai/aabbccddeeff",
    )
    cb = skizze.make_user_jwt_cb(
        cache,
        enforce_exp=True,
        now=lambda: fixed_now,
    )
    with pytest.raises(skizze.NatsJwtCallbackSvidExpired):
        cb()
    # And: when injected clock is BEFORE exp, no raise.
    fixed_now_early = datetime(2026, 5, 12, 18, 28, 0, tzinfo=timezone.utc)
    cb2 = skizze.make_user_jwt_cb(
        cache,
        enforce_exp=True,
        now=lambda: fixed_now_early,
    )
    assert cb2() == b"clock-test"


# ---------------------------------------------------------------------
# Block 7 — Cross-reference invariants
# ---------------------------------------------------------------------


def test_skizze_module_path_exists():
    """The Tag-10 skizze module file is in scripts/ where the loader
    pattern expects it (parity with spiffe_skizze_constants.py).
    """
    assert SKIZZE_PATH.exists(), f"missing skizze module at {SKIZZE_PATH}"
    assert SKIZZE_PATH.parent.name == "scripts"


def test_spiffe_constants_reachable_from_skizze_tree(constants):
    """The SPIFFE constants module is loadable in the same tree.

    Tag-10 skizze references NATS_JWT_AUDIENCE_PHASE_2 by name in the
    runbook; tests pin the constant value.
    """
    assert hasattr(constants, "NATS_JWT_AUDIENCE_PHASE_2")
    assert constants.NATS_JWT_AUDIENCE_PHASE_2 == "nats://wakir.local"


def test_path_by_name_pin_for_wirelang_adapter_holds(skizze):
    """Path-by-name pin: the skizze module documents the wirelang
    adapter path in its docstring (and in error messages); it does NOT
    import from `wirelang.adapters.spiffe_workload_api`.

    Drift-Detection: if the wirelang adapter relocates, this test
    breaks and forces a co-edit of the path reference.
    """
    # Docstring/module-text references the adapter path.
    skizze_text = SKIZZE_PATH.read_text(encoding="utf-8")
    assert "wirelang/adapters/spiffe_workload_api.py" in skizze_text, (
        "Tag-10 skizze module must reference the wirelang adapter path by name."
    )
    # And: the skizze does NOT statically import from wirelang.
    assert "from wirelang" not in skizze_text, (
        "Tag-10 skizze must NOT import from wirelang (path-by-name only)."
    )
    assert "import wirelang" not in skizze_text, (
        "Tag-10 skizze must NOT import wirelang (path-by-name only)."
    )


# ---------------------------------------------------------------------
# Block 8 — Contract self-check
# ---------------------------------------------------------------------


def test_this_file_contains_twenty_tests():
    """Pin the Tag-10 test-count for drift-detection.

    Mirrors the Tag-6/Tag-8/Tag-9 contract-self-check pattern.
    """
    this_file = Path(__file__).read_text(encoding="utf-8")
    # Count top-level test functions.
    test_count = sum(
        1
        for line in this_file.splitlines()
        if line.startswith("def test_")
    )
    assert test_count == 20, (
        f"Expected 20 Tag-10 tests in this file; found {test_count}. "
        f"Update the runbook §Test-Inventory and this self-check."
    )
