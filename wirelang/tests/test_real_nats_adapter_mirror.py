# SPDX-License-Identifier: Apache-2.0
"""Sprint-8 Tag-1 RealAdapter-Mirror test suite.

Covers six surfaces:

1. Mock-Mirror roundtrip (connect / publish / status / close).
2. Live-adapter reachability-skip-with-marker (when localhost:4222
   is unreachable, the live adapter raises NatsAdapterUnavailable
   without involving nats-py).
3. Live-adapter Fallback-Path bei fehlender SPIRE (auth_mode
   resolves to "mock-jwt" when SPIRE_AGENT_SOCKET is unset / "none").
4. Live-adapter live-SPIFFE-Gate (auth_mode="live-spiffe" raises
   NatsAdapterAuthenticationError on connect — Operator-Hand-block).
5. Cross-Trust-Domain-Bridge-Anbindung (status surface exposes
   live_mode_marker that the bridge / orchestrator can audit).
6. Live-adapter mit NATS-localhost-falls-verfügbar-sonst-skip-with-
   marker (real NATS-roundtrip — passes when nats-server is up,
   skipped otherwise).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from wirelang.adapters.real_nats_adapter import (
    MockNatsConnectionAdapter,
    NatsAdapterAuthenticationError,
    NatsAdapterError,
    NatsAdapterStatus,
    NatsAdapterUnavailable,
    RealNatsConnectionAdapter,
    is_nats_reachable,
)


# ---------------------------------------------------------------------------
# Test 1 — Mock-Mirror roundtrip
# ---------------------------------------------------------------------------


def test_mock_nats_adapter_roundtrip_records_publish_and_status() -> None:
    """Mock adapter: connect → publish → status → close roundtrip.

    Verifies the hermetic in-process surface: connect flips
    ``connected``; publish records the (subject, payload) tuple;
    status reports ``adapter_kind="mock"``; close resets state.
    Also checks input-validation guards.
    """

    async def _drive() -> None:
        adapter = MockNatsConnectionAdapter(auth_mode="mock-jwt")

        # Pre-connect status
        pre_status = adapter.status()
        assert isinstance(pre_status, NatsAdapterStatus)
        assert pre_status.adapter_kind == "mock"
        assert pre_status.connected is False
        assert pre_status.auth_mode == "mock-jwt"
        assert pre_status.live_mode_marker is None

        # Publish before connect raises
        with pytest.raises(NatsAdapterUnavailable):
            await adapter.publish("wakir.dev.test.event", b"payload-1")

        # Connect, then publish two messages
        await adapter.connect()
        assert adapter.status().connected is True

        await adapter.publish("wakir.dev.test.event", b"payload-1")
        await adapter.publish("wakir.dev.test.event.sub", b"payload-2")

        # Recorded publications are append-only and byte-identical
        assert adapter.published == [
            ("wakir.dev.test.event", b"payload-1"),
            ("wakir.dev.test.event.sub", b"payload-2"),
        ]

        # Input-validation guards
        with pytest.raises(NatsAdapterError):
            await adapter.publish("", b"empty-subject")
        with pytest.raises(NatsAdapterError):
            await adapter.publish("wakir.x", "not-bytes")  # type: ignore[arg-type]

        # Close is idempotent
        await adapter.close()
        await adapter.close()
        assert adapter.status().connected is False

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Test 2 — Live-adapter reachability-skip-with-marker
# ---------------------------------------------------------------------------


def test_real_adapter_unreachable_raises_unavailable_without_nats_py(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live adapter against an unreachable endpoint: fast-fail via
    reachability-probe, NatsAdapterUnavailable raised.

    Uses an obviously-unreachable URL (``nats://127.0.0.1:1`` —
    privileged port, not listening). The reachability-probe MUST
    fail and the adapter MUST raise NatsAdapterUnavailable
    BEFORE importing ``nats-py``.
    """

    # Ensure SPIRE_AGENT_SOCKET is not "live-spiffe" so we reach the
    # reachability-probe path (else we'd hit the live-SPIFFE gate first).
    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "none")

    async def _drive() -> None:
        adapter = RealNatsConnectionAdapter(
            server_url="nats://127.0.0.1:1",
            connect_timeout_seconds=0.2,
        )
        status_pre = adapter.status()
        assert status_pre.adapter_kind == "live"
        assert status_pre.connected is False
        assert status_pre.live_mode_marker == (
            "sprint-8-tag-1-real-adapter-mirror"
        )

        with pytest.raises(NatsAdapterUnavailable) as exc_info:
            await adapter.connect()
        assert "127.0.0.1:1" in str(exc_info.value)
        assert "Operator-Hand-Fedora-Host" in str(exc_info.value)

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Test 3 — Fallback-Path bei fehlender SPIRE (auth_mode resolution)
# ---------------------------------------------------------------------------


def test_real_adapter_auth_mode_falls_back_to_mock_jwt_without_spire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auth_mode resolution: SPIRE_AGENT_SOCKET unset/none/empty
    → "mock-jwt"; any other value → "live-spiffe".
    """

    # Case A: unset
    monkeypatch.delenv("SPIRE_AGENT_SOCKET", raising=False)
    adapter_a = RealNatsConnectionAdapter(server_url="nats://x:4222")
    assert adapter_a.auth_mode == "mock-jwt"
    assert adapter_a.status().auth_mode == "mock-jwt"

    # Case B: explicit "none"
    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "none")
    adapter_b = RealNatsConnectionAdapter(server_url="nats://x:4222")
    assert adapter_b.auth_mode == "mock-jwt"

    # Case C: explicit "  NONE  " (whitespace + casing)
    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "  NONE  ")
    adapter_c = RealNatsConnectionAdapter(server_url="nats://x:4222")
    assert adapter_c.auth_mode == "mock-jwt"

    # Case D: empty string
    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "")
    adapter_d = RealNatsConnectionAdapter(server_url="nats://x:4222")
    assert adapter_d.auth_mode == "mock-jwt"

    # Case E: a real URI → live-spiffe label (but the connect path
    # will still refuse — see Test 4)
    monkeypatch.setenv(
        "SPIRE_AGENT_SOCKET", "unix:///tmp/spire-agent/public/api.sock"
    )
    adapter_e = RealNatsConnectionAdapter(server_url="nats://x:4222")
    assert adapter_e.auth_mode == "live-spiffe"


# ---------------------------------------------------------------------------
# Test 4 — Live-SPIFFE-Gate raises NatsAdapterAuthenticationError
# ---------------------------------------------------------------------------


def test_real_adapter_live_spiffe_path_is_operator_hand_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When auth_mode resolves to "live-spiffe", connect() refuses
    with NatsAdapterAuthenticationError — the live-SPIFFE-JWT path
    is Operator-Hand-blocked per Sprint-7-Closeout-Stempel M-2.

    The refusal happens AFTER the reachability-probe passes (we use
    a probe-side guard so the gate exercises with a reachable
    endpoint — we monkey-patch is_nats_reachable to True).
    """

    monkeypatch.setenv(
        "SPIRE_AGENT_SOCKET", "unix:///tmp/spire-agent/public/api.sock"
    )

    # Patch the reachability probe so we reach the live-SPIFFE gate
    import wirelang.adapters.real_nats_adapter.adapter as adapter_mod

    monkeypatch.setattr(
        adapter_mod, "is_nats_reachable", lambda *a, **kw: True
    )

    async def _drive() -> None:
        adapter = RealNatsConnectionAdapter(server_url="nats://x:4222")
        assert adapter.auth_mode == "live-spiffe"
        with pytest.raises(NatsAdapterAuthenticationError) as exc_info:
            await adapter.connect()
        # Error message references the Operator-Hand-block and the
        # bypass instruction
        assert "Operator-Hand-block" in str(exc_info.value)
        assert "SPIRE_AGENT_SOCKET=none" in str(exc_info.value)
        assert "Sprint-7-Closeout-Stempel M-2" in str(exc_info.value)

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Test 5 — Cross-Trust-Domain-Bridge-Anbindung (status surface)
# ---------------------------------------------------------------------------


def test_real_adapter_status_surface_for_cross_trust_domain_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The status surface exposes the markers the SpiffeCross-
    TrustDomainBridge (Sprint-7 Tag-3) needs to audit which auth
    mode the underlying NATS-connection runs in.

    - live_mode_marker pins the Sprint-8 Tag-1 RealAdapter-Mirror
      identifier (so a bridge audit can confirm the adapter is
      the mirror slot and not a stub).
    - adapter_kind separates "mock" vs "live" so the bridge can
      refuse to federate over a mock adapter in a production-
      mode policy.
    - auth_mode reports the SPIRE-Fallback-Policy outcome so the
      bridge can refuse to federate when auth_mode != "live-spiffe"
      under a strict-federation-trust-policy.
    """

    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "none")

    mock_adapter = MockNatsConnectionAdapter(
        server_url="nats://test:4222", auth_mode="mock-jwt"
    )
    live_adapter = RealNatsConnectionAdapter(
        server_url="nats://localhost:4222"
    )

    mock_status = mock_adapter.status()
    live_status = live_adapter.status()

    # Mock adapter: no live-mode marker, adapter_kind=mock
    assert mock_status.adapter_kind == "mock"
    assert mock_status.live_mode_marker is None
    assert mock_status.server_url == "nats://test:4222"

    # Live adapter: live-mode marker set, adapter_kind=live
    assert live_status.adapter_kind == "live"
    assert (
        live_status.live_mode_marker
        == "sprint-8-tag-1-real-adapter-mirror"
    )
    assert live_status.server_url == "nats://localhost:4222"
    assert live_status.auth_mode == "mock-jwt"  # SPIRE fallback path

    # Reachability probe is hermetic and tolerant of malformed URLs
    assert is_nats_reachable("nats://127.0.0.1:1") is False
    assert is_nats_reachable("not-a-url") is False
    assert is_nats_reachable("nats://") is False
    assert is_nats_reachable(None) in (True, False)  # env-dependent


# ---------------------------------------------------------------------------
# Test 6 — Live NATS roundtrip (skip-with-marker if unreachable)
# ---------------------------------------------------------------------------


def test_real_adapter_live_nats_roundtrip_if_reachable_else_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If localhost:4222 is reachable, perform a real NATS
    connect / publish / close roundtrip. Otherwise skip with a
    clear marker — the sandbox-CI baseline does NOT have NATS
    running, so this test is expected to skip there.

    This is the **functional Live-Adapter-Mirror-Roundtrip**
    distinct from the unreachable-fast-fail test (Test 2). The
    skip-with-marker pattern keeps the test green in the sandbox
    while exercising the real path on an Operator-Hand-Fedora-Host.
    """

    monkeypatch.setenv("SPIRE_AGENT_SOCKET", "none")

    server_url = os.environ.get(
        "WIRELANG_NATS_URL", "nats://localhost:4222"
    )
    if not is_nats_reachable(server_url, timeout_seconds=0.3):
        pytest.skip(
            f"skip-with-marker: NATS server not reachable at "
            f"{server_url} (sandbox-default; Operator-Hand-Fedora-Host "
            f"required for live roundtrip)"
        )

    async def _drive() -> None:
        adapter = RealNatsConnectionAdapter(
            server_url=server_url, connect_timeout_seconds=2.0
        )
        await adapter.connect()
        try:
            assert adapter.status().connected is True
            await adapter.publish(
                "wakir.dev.sprint-8-tag-1.real-adapter-test",
                b"sprint-8-tag-1-real-adapter-mirror-payload",
            )
        finally:
            await adapter.close()
        assert adapter.status().connected is False

    asyncio.run(_drive())
