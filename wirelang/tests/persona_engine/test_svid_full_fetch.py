# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-2 tests: full SVID-fetch over gRPC.

Hermetic stubs replace the grpcio surface so the tests run without
the grpcio wheel. The stubs cover:

  - Channel factory (returns a fake channel object).
  - Stub factory (returns an object exposing ``FetchX509SVID``).
  - FetchX509SVID server-stream (async-iterator over canned replies).

Cert handling uses cryptography (a wakir-runtime top-level dep) to
forge a leaf cert with the expected SPIFFE-ID SAN URI; the tests
verify the engine extracts the URI + notAfter + bind-state hash.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Iterable, List, Optional, Tuple

import pytest

from wirelang.persona_engine._workload_api_pb2_minimal import (
    X509SVID,
    X509SVIDResponse,
    serialize_x509_svid_response,
    _deserialize_x509_svid_response,
)
from wirelang.persona_engine.svid_workload_identity import (
    SVID_FETCH_SOFT_CAP_SEC,
    SvidFetchError,
    SvidFetchResult,
    WorkloadApiClient,
    expected_spiffe_id_for,
    fetch_workload_svid,
    probe_workload_api_socket,
    resolve_socket_path,
)


# -------------------- Leaf certificate forging --------------------


def _forge_leaf_certificate(spiffe_uri: str, not_after_offset_days: int = 30) -> bytes:
    """Forge a minimal X.509 leaf cert with the given SPIFFE-ID SAN URI."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "wakir-persona-test"),
    ])
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=not_after_offset_days))
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_uri)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    from cryptography.hazmat.primitives.serialization import Encoding

    return cert.public_bytes(Encoding.DER)


# -------------------- Hermetic gRPC stubs --------------------


class _StubStream:
    def __init__(self, replies: List[X509SVIDResponse]) -> None:
        self._replies = list(replies)

    def __aiter__(self) -> "_StubStream":
        return self

    async def __anext__(self) -> X509SVIDResponse:
        if not self._replies:
            raise StopAsyncIteration
        return self._replies.pop(0)


class _StubChannel:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _StubStub:
    def __init__(self, replies: List[X509SVIDResponse]) -> None:
        self._replies = replies
        self.last_metadata: Optional[List[Tuple[str, str]]] = None

    def FetchX509SVID(self, _request, *, metadata=None):
        self.last_metadata = list(metadata or [])
        return _StubStream(self._replies)


def _factories_for(replies: List[X509SVIDResponse]):
    channel = _StubChannel()
    stub = _StubStub(replies)

    def channel_factory(_socket_path: str) -> Any:
        return channel

    def stub_factory(_channel: Any) -> _StubStub:
        return stub

    return channel_factory, stub_factory, channel, stub


# -------------------- constant + helper tests --------------------


def test_expected_spiffe_id_template():
    assert (
        expected_spiffe_id_for("acme", "tomas")
        == "spiffe://wakir.acme/persona/tomas"
    )


def test_resolve_socket_path_default():
    assert resolve_socket_path({}) == "/run/spire/agent-sockets/api.sock"


def test_resolve_socket_path_strips_unix_prefix():
    assert (
        resolve_socket_path({"SPIFFE_ENDPOINT_SOCKET": "unix:///tmp/sock"})
        == "/tmp/sock"
    )


def test_resolve_socket_path_passes_through_non_uri():
    assert (
        resolve_socket_path({"SPIFFE_ENDPOINT_SOCKET": "/tmp/sock"})
        == "/tmp/sock"
    )


def test_soft_cap_constant_positive():
    assert SVID_FETCH_SOFT_CAP_SEC > 0


# -------------------- protobuf round-trip tests --------------------


def test_x509_svid_response_round_trip():
    leaf = b"DERBYTES"
    resp = X509SVIDResponse(
        svids=[X509SVID(spiffe_id="spiffe://wakir.acme/persona/tomas", x509_svid=leaf)],
    )
    blob = serialize_x509_svid_response(resp)
    parsed = _deserialize_x509_svid_response(blob)
    assert len(parsed.svids) == 1
    assert parsed.svids[0].spiffe_id == "spiffe://wakir.acme/persona/tomas"
    assert parsed.svids[0].x509_svid == leaf


def test_x509_svid_response_multi_svid():
    resp = X509SVIDResponse(
        svids=[
            X509SVID(spiffe_id="spiffe://a/persona/1", x509_svid=b"A"),
            X509SVID(spiffe_id="spiffe://b/persona/2", x509_svid=b"BB"),
        ],
    )
    blob = serialize_x509_svid_response(resp)
    parsed = _deserialize_x509_svid_response(blob)
    assert len(parsed.svids) == 2


def test_x509_svid_response_empty_svids():
    resp = X509SVIDResponse()
    blob = serialize_x509_svid_response(resp)
    parsed = _deserialize_x509_svid_response(blob)
    assert parsed.svids == []


def test_x509_svid_response_crl_field():
    resp = X509SVIDResponse(crl=[b"CRL1", b"CRL2"])
    blob = serialize_x509_svid_response(resp)
    parsed = _deserialize_x509_svid_response(blob)
    assert parsed.crl == [b"CRL1", b"CRL2"]


# -------------------- full SVID-fetch happy path --------------------


def test_full_svid_fetch_succeeds_against_stub():
    expected = expected_spiffe_id_for("acme", "tomas")
    leaf_der = _forge_leaf_certificate(expected)
    replies = [
        X509SVIDResponse(svids=[X509SVID(spiffe_id=expected, x509_svid=leaf_der)]),
    ]
    cf, sf, _channel, stub = _factories_for(replies)

    async def go() -> SvidFetchResult:
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    result = asyncio.run(go())
    assert result.spiffe_id == expected
    assert result.matches_expected is True
    assert result.san_uris == (expected,)
    assert result.trust_domain == "wakir.acme"
    assert result.not_after_utc.endswith("Z")
    assert result.bind_state_sha256.startswith("sha256:")
    # gRPC metadata header is set.
    assert stub.last_metadata is not None
    assert ("workload.spiffe.io", "true") in stub.last_metadata


def test_full_svid_fetch_flags_mismatch():
    wrong = "spiffe://wakir.acme/persona/aisha"
    leaf_der = _forge_leaf_certificate(wrong)
    replies = [
        X509SVIDResponse(svids=[X509SVID(spiffe_id=wrong, x509_svid=leaf_der)]),
    ]
    cf, sf, _, _ = _factories_for(replies)

    async def go() -> SvidFetchResult:
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    result = asyncio.run(go())
    assert result.spiffe_id == wrong
    assert result.matches_expected is False


def test_full_svid_fetch_empty_stream_raises():
    cf, sf, _, _ = _factories_for([])

    async def go() -> SvidFetchResult:
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    with pytest.raises(SvidFetchError):
        asyncio.run(go())


def test_full_svid_fetch_empty_svid_list_raises():
    replies = [X509SVIDResponse(svids=[])]
    cf, sf, _, _ = _factories_for(replies)

    async def go() -> SvidFetchResult:
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    with pytest.raises(SvidFetchError):
        asyncio.run(go())


def test_full_svid_fetch_empty_leaf_bytes_raises():
    replies = [
        X509SVIDResponse(svids=[
            X509SVID(spiffe_id="spiffe://wakir.acme/persona/tomas", x509_svid=b""),
        ]),
    ]
    cf, sf, _, _ = _factories_for(replies)

    async def go() -> SvidFetchResult:
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    with pytest.raises(SvidFetchError):
        asyncio.run(go())


def test_full_svid_fetch_bind_state_sha256_stable():
    expected = expected_spiffe_id_for("acme", "tomas")
    leaf_der = _forge_leaf_certificate(expected)
    replies1 = [
        X509SVIDResponse(svids=[X509SVID(spiffe_id=expected, x509_svid=leaf_der)]),
    ]
    replies2 = [
        X509SVIDResponse(svids=[X509SVID(spiffe_id=expected, x509_svid=leaf_der)]),
    ]
    cf1, sf1, _, _ = _factories_for(replies1)
    cf2, sf2, _, _ = _factories_for(replies2)

    async def go(cf, sf):
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    r1 = asyncio.run(go(cf1, sf1))
    r2 = asyncio.run(go(cf2, sf2))
    # Same DER -> same bind-state hash.
    assert r1.bind_state_sha256 == r2.bind_state_sha256


def test_full_svid_fetch_records_san_uris():
    expected = expected_spiffe_id_for("acme", "tomas")
    leaf_der = _forge_leaf_certificate(expected)
    cf, sf, _, _ = _factories_for([
        X509SVIDResponse(svids=[X509SVID(spiffe_id=expected, x509_svid=leaf_der)]),
    ])

    async def go():
        return await fetch_workload_svid(
            org_id="acme",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    result = asyncio.run(go())
    assert expected in result.san_uris


def test_full_svid_fetch_trust_domain_extracted():
    expected = "spiffe://wakir.example.org/persona/tomas"
    leaf_der = _forge_leaf_certificate(expected)
    cf, sf, _, _ = _factories_for([
        X509SVIDResponse(svids=[X509SVID(spiffe_id=expected, x509_svid=leaf_der)]),
    ])

    async def go():
        return await fetch_workload_svid(
            org_id="example.org",
            persona_id="tomas",
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )

    result = asyncio.run(go())
    assert result.trust_domain == "wakir.example.org"
    assert result.matches_expected is True


# -------------------- WorkloadApiClient lifecycle --------------------


def test_workload_api_client_connect_idempotent():
    cf, sf, channel, _ = _factories_for([])

    async def go():
        client = WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )
        await client.connect()
        await client.connect()  # idempotent
        await client.close()
        # close idempotent: second call must not error.
        await client.close()

    asyncio.run(go())
    assert channel.closed is True


def test_workload_api_client_aenter_aexit():
    cf, sf, channel, _ = _factories_for([])

    async def go():
        async with WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        ) as _client:
            pass

    asyncio.run(go())
    assert channel.closed is True


def test_workload_api_client_fetch_before_connect_raises():
    cf, sf, _, _ = _factories_for([])

    async def go():
        client = WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=cf,
            stub_factory=sf,
        )
        # No connect call.
        with pytest.raises(SvidFetchError):
            await client.fetch_x509_svid(org_id="acme", persona_id="tomas")

    asyncio.run(go())


def test_workload_api_client_fetch_timeout():
    """A stream that never yields a reply within the timeout should
    raise asyncio.TimeoutError (wrapped by asyncio.wait_for)."""

    class _SlowStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(10.0)
            raise StopAsyncIteration

    class _SlowStub:
        def FetchX509SVID(self, _request, *, metadata=None):
            return _SlowStream()

    def cf(_p):
        return _StubChannel()

    def sf(_c):
        return _SlowStub()

    async def go():
        async with WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            fetch_timeout_sec=0.1,
            channel_factory=cf,
            stub_factory=sf,
        ) as client:
            with pytest.raises(asyncio.TimeoutError):
                await client.fetch_x509_svid(org_id="acme", persona_id="tomas")

    asyncio.run(go())


# -------------------- Socket-probe boot-gate still works --------------------


def test_socket_probe_absent_path():
    result = probe_workload_api_socket(
        org_id="acme",
        persona_id="tomas",
        socket_path="/nonexistent/sock-abc-12345",
    )
    assert result.socket_present is False
    assert result.socket_connectable is False
    assert result.expected_spiffe_id == "spiffe://wakir.acme/persona/tomas"


def test_socket_probe_present_but_not_connectable(tmp_path):
    p = tmp_path / "fake.sock"
    p.write_text("")  # regular file, not a UNIX socket
    result = probe_workload_api_socket(
        org_id="acme",
        persona_id="tomas",
        socket_path=str(p),
    )
    assert result.socket_present is True
    assert result.socket_connectable is False
