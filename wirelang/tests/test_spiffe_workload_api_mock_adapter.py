# SPDX-License-Identifier: Apache-2.0
"""Tests for the SPIFFE Workload API mock adapter (Sprint-6 Tag-5).

The mock implementation is hermetic: no network calls, no FS reads.
These tests pin the deterministic-output contract and the four
error-path semantics (unavailable / attestation_failed /
audience_rejected / not-registered).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import pytest

from wirelang.adapters.spiffe_workload_api import (
    JwtSvid,
    MockSpiffeWorkloadApiAdapter,
    MockSvidRecord,
    SpiffeAdapterAttestationFailed,
    SpiffeAdapterAudienceRejected,
    SpiffeAdapterError,
    SpiffeAdapterUnavailable,
    SpiffeWorkloadApiAdapter,
)


# ---------------------------------------------------------------------------
# T-SWA-MOCK-01..03 — happy-path fetch (default record / explicit record /
# explicit spiffe-id lookup).
# ---------------------------------------------------------------------------


def test_t_swa_mock_01_default_record_happy_path() -> None:
    """Default adapter returns a JwtSvid with the default SPIFFE-ID."""

    adapter = MockSpiffeWorkloadApiAdapter()
    svid = asyncio.run(adapter.fetch_jwt_svid("nats-server-1"))

    assert isinstance(svid, JwtSvid)
    assert svid.spiffe_id == "spiffe://wakir.local/agent/reza/aabbccddeeff"
    assert svid.token == "mock.jwt.token"
    assert svid.audiences == ("nats-server-1",)
    assert svid.expires_at == datetime(2099, 1, 1, tzinfo=timezone.utc)


def test_t_swa_mock_02_explicit_record_round_trip() -> None:
    """A custom record is returned byte-equal across audiences."""

    record = MockSvidRecord(
        spiffe_id="spiffe://wakir.local/agent/kai/112233445566",
        token="kai.jwt.token",
        extra_audiences=("nats-cluster-replica",),
        expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
    )
    adapter = MockSpiffeWorkloadApiAdapter(records=(record,))
    svid = asyncio.run(adapter.fetch_jwt_svid("primary-aud"))

    assert svid.spiffe_id == "spiffe://wakir.local/agent/kai/112233445566"
    assert svid.token == "kai.jwt.token"
    assert svid.audiences == ("primary-aud", "nats-cluster-replica")
    assert svid.expires_at == datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_t_swa_mock_03_explicit_spiffe_id_lookup() -> None:
    """Multiple records — explicit spiffe_id resolves to the right one."""

    r1 = MockSvidRecord(
        spiffe_id="spiffe://wakir.local/agent/a/aaaaaaaaaaaa",
        token="a.token",
    )
    r2 = MockSvidRecord(
        spiffe_id="spiffe://wakir.local/agent/b/bbbbbbbbbbbb",
        token="b.token",
    )
    adapter = MockSpiffeWorkloadApiAdapter(records=(r1, r2))

    svid_b = asyncio.run(
        adapter.fetch_jwt_svid(
            "aud",
            spiffe_id="spiffe://wakir.local/agent/b/bbbbbbbbbbbb",
        )
    )
    assert svid_b.token == "b.token"

    svid_a = asyncio.run(
        adapter.fetch_jwt_svid(
            "aud",
            spiffe_id="spiffe://wakir.local/agent/a/aaaaaaaaaaaa",
        )
    )
    assert svid_a.token == "a.token"


# ---------------------------------------------------------------------------
# T-SWA-MOCK-04..07 — error paths.
# ---------------------------------------------------------------------------


def test_t_swa_mock_04_unavailable_raises() -> None:
    """unavailable record raises SpiffeAdapterUnavailable."""

    record = MockSvidRecord(unavailable=True)
    adapter = MockSpiffeWorkloadApiAdapter(records=(record,))

    with pytest.raises(SpiffeAdapterUnavailable):
        asyncio.run(adapter.fetch_jwt_svid("aud"))


def test_t_swa_mock_05_attestation_failed_raises() -> None:
    """attestation_failed record raises SpiffeAdapterAttestationFailed."""

    record = MockSvidRecord(attestation_failed=True)
    adapter = MockSpiffeWorkloadApiAdapter(records=(record,))

    with pytest.raises(SpiffeAdapterAttestationFailed):
        asyncio.run(adapter.fetch_jwt_svid("aud"))


def test_t_swa_mock_06_audience_not_in_permitted_set_raises() -> None:
    """Requesting an audience not in permitted_audiences raises rejection."""

    record = MockSvidRecord(
        permitted_audiences=frozenset({"nats-server-1", "nats-server-2"}),
    )
    adapter = MockSpiffeWorkloadApiAdapter(records=(record,))

    with pytest.raises(SpiffeAdapterAudienceRejected):
        asyncio.run(adapter.fetch_jwt_svid("forbidden-aud"))


def test_t_swa_mock_07_unknown_spiffe_id_raises_attestation_failed() -> None:
    """Requesting an unregistered spiffe_id maps to attestation failure."""

    record = MockSvidRecord(
        spiffe_id="spiffe://wakir.local/agent/known/abcdef012345",
    )
    adapter = MockSpiffeWorkloadApiAdapter(records=(record,))

    with pytest.raises(SpiffeAdapterAttestationFailed):
        asyncio.run(
            adapter.fetch_jwt_svid(
                "aud",
                spiffe_id="spiffe://wakir.local/agent/unknown/aaaaaaaaaaaa",
            )
        )


# ---------------------------------------------------------------------------
# T-SWA-MOCK-08..09 — input validation.
# ---------------------------------------------------------------------------


def test_t_swa_mock_08_empty_audience_raises_adapter_error() -> None:
    """Empty audience string is rejected as SpiffeAdapterError."""

    adapter = MockSpiffeWorkloadApiAdapter()

    with pytest.raises(SpiffeAdapterError):
        asyncio.run(adapter.fetch_jwt_svid(""))


def test_t_swa_mock_09_empty_records_tuple_raises_value_error() -> None:
    """Empty records tuple (deliberate) is rejected at construction."""

    with pytest.raises(ValueError):
        MockSpiffeWorkloadApiAdapter(records=())


# ---------------------------------------------------------------------------
# T-SWA-MOCK-10..12 — determinism / typing / Protocol-conformance.
# ---------------------------------------------------------------------------


def test_t_swa_mock_10_determinism_same_input_byte_equal_output() -> None:
    """Two fetches with identical input produce equal JwtSvid instances."""

    adapter = MockSpiffeWorkloadApiAdapter()
    a = asyncio.run(adapter.fetch_jwt_svid("nats-server-1"))
    b = asyncio.run(adapter.fetch_jwt_svid("nats-server-1"))

    assert a == b
    # frozen dataclass: hashable.
    assert hash(a) == hash(b)


def test_t_swa_mock_11_protocol_conformance() -> None:
    """MockSpiffeWorkloadApiAdapter satisfies the Protocol surface.

    runtime_checkable is NOT applied to the Protocol, so we verify
    structurally: the mock has both async methods.
    """

    adapter = MockSpiffeWorkloadApiAdapter()
    # Verify the mock has the Protocol's two async slots.
    assert hasattr(adapter, "fetch_jwt_svid")
    assert hasattr(adapter, "fetch_x509_svid")
    # Verify both are coroutine functions.
    assert inspect.iscoroutinefunction(adapter.fetch_jwt_svid)
    assert inspect.iscoroutinefunction(adapter.fetch_x509_svid)


def test_t_swa_mock_12_x509_svid_raises_not_implemented() -> None:
    """fetch_x509_svid remains stub-Protocol-aligned (Phase-2c)."""

    adapter = MockSpiffeWorkloadApiAdapter()

    with pytest.raises(NotImplementedError):
        asyncio.run(adapter.fetch_x509_svid())


# ---------------------------------------------------------------------------
# Auxiliary probe — surface-import sanity.
# ---------------------------------------------------------------------------


def test_aux_surface_import_all_public_symbols_resolve() -> None:
    """All __all__ symbols import cleanly (no name typos)."""

    import wirelang.adapters.spiffe_workload_api as mod

    for name in mod.__all__:
        assert hasattr(mod, name), f"__all__ symbol {name!r} not on module"


def test_aux_protocol_surface_is_separate_from_mock() -> None:
    """Protocol and Mock are distinct types (Protocol is structural).

    Protocol is NOT runtime_checkable, so issubclass / isinstance against
    the Protocol surface is intentionally rejected by typing. The
    structural conformance is verified via T-SWA-MOCK-11 (method
    presence + coroutine-function check).
    """

    adapter = MockSpiffeWorkloadApiAdapter()
    # The mock IS an instance of the concrete class.
    assert isinstance(adapter, MockSpiffeWorkloadApiAdapter)
    # The Protocol surface is distinct from the concrete class
    # (verified by type identity, not by isinstance/issubclass).
    assert SpiffeWorkloadApiAdapter is not MockSpiffeWorkloadApiAdapter
