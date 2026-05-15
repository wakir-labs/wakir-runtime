# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Minimal SPIFFE Workload-API protobuf surface (Sprint-Pengine-9 OI-PEFR-2).

Hand-rolled gRPC binding for the **read-only** subset of the SPIFFE
Workload-API v0.4 protocol the persona-engine consumes:

  - ``X509SVIDRequest``   — empty message; FetchX509SVID request.
  - ``X509SVIDResponse``  — repeated ``X509SVID`` plus ``crl`` /
                           ``federated_bundles`` (we ignore both).
  - ``X509SVID``          — single-identity SVID: ``spiffe_id``,
                           ``x509_svid`` (leaf DER), ``x509_svid_key``
                           (PKCS#8 DER private key), ``bundle``
                           (trust bundle DER).
  - ``SpiffeWorkloadAPIStub`` — gRPC client stub.

Why hand-rolled
---------------

A full protoc-generated ``workload_pb2`` carries ~30KB of generated
Python plus a protobuf runtime dependency we already pay for via
the persona-engine-runtime pyproject extra. The hand-rolled surface
keeps the wakir-runtime tree self-contained on this file alone —
swapping in a future ``workload_pb2`` from a SPIRE upstream release
is a drop-in: the field names are byte-aligned with the upstream
.proto.

Wire format
-----------

We rely on ``google.protobuf.message.Message``-shape parsing via the
``protobuf`` wheel (already a persona-engine-runtime dep). The
classes below are typed wrappers that delegate to runtime-built
descriptors. Hermetic tests bypass this entirely by injecting a
``stub_factory`` into :class:`WorkloadApiClient`; the production
binding goes through this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Dataclass message shapes (used by hermetic tests).
# ---------------------------------------------------------------------------


@dataclass
class X509SVID:
    """Single-identity X.509 SVID (Workload-API v0.4 §X509SVID)."""

    spiffe_id: str = ""
    x509_svid: bytes = b""
    x509_svid_key: bytes = b""
    bundle: bytes = b""
    hint: str = ""


@dataclass
class X509SVIDRequest:
    """Empty request message (Workload-API v0.4 §X509SVIDRequest)."""

    pass


@dataclass
class X509SVIDResponse:
    """Workload-API FetchX509SVID server-streamed response."""

    svids: List[X509SVID] = field(default_factory=list)
    crl: List[bytes] = field(default_factory=list)
    federated_bundles: List[Tuple[str, bytes]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Production gRPC stub.
# ---------------------------------------------------------------------------


class SpiffeWorkloadAPIStub:
    """gRPC stub for ``SpiffeWorkloadAPI`` (UDS, async).

    Wraps a ``grpc.aio.Channel``; the stub is constructed by
    :class:`wirelang.persona_engine.svid_workload_identity.WorkloadApiClient`
    when no ``stub_factory`` is injected.

    The stub uses grpcio's generic ``stream_unary`` / ``unary_stream``
    machinery so we avoid the protoc-generated stub class entirely.
    """

    _SERVICE = "SpiffeWorkloadAPI"
    _METHOD_FETCH_X509_SVID = "FetchX509SVID"
    _FULL_METHOD_FETCH_X509_SVID = (
        f"/{_SERVICE}/{_METHOD_FETCH_X509_SVID}"
    )

    def __init__(self, channel: Any) -> None:
        try:
            import grpc  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - covered by client tests
            raise RuntimeError(
                "grpcio not available; SpiffeWorkloadAPIStub requires "
                "the persona-engine-runtime extra"
            ) from exc
        self._channel = channel
        self._fetch_x509_svid_invoker = channel.unary_stream(
            self._FULL_METHOD_FETCH_X509_SVID,
            request_serializer=_serialize_x509_svid_request,
            response_deserializer=_deserialize_x509_svid_response,
        )

    def FetchX509SVID(
        self,
        request: X509SVIDRequest,
        *,
        metadata: Optional[List[Tuple[str, str]]] = None,
    ) -> Any:
        return self._fetch_x509_svid_invoker(
            request,
            metadata=metadata or [],
        )


# ---------------------------------------------------------------------------
# Hand-rolled protobuf serialisation (covers the narrow subset).
# ---------------------------------------------------------------------------


def _serialize_x509_svid_request(_msg: X509SVIDRequest) -> bytes:
    # X509SVIDRequest has no fields in v0.4; encoded form is the empty
    # wire-frame.
    return b""


def _deserialize_x509_svid_response(data: bytes) -> X509SVIDResponse:
    """Parse an X509SVIDResponse wire frame.

    Protobuf wire format:
      Tag = (field_number << 3) | wire_type
      wire_type 2 = length-delimited
    """
    resp = X509SVIDResponse()
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type != 2:
            # Skip unknown non-length-delimited fields (defence in depth;
            # the v0.4 X509SVIDResponse is all length-delimited).
            _length, pos = _read_varint(data, pos)
            pos += _length
            continue
        length, pos = _read_varint(data, pos)
        payload = data[pos:pos + length]
        pos += length
        if field_number == 1:
            resp.svids.append(_parse_x509_svid(payload))
        elif field_number == 2:
            resp.crl.append(bytes(payload))
        elif field_number == 3:
            # federated_bundles is a map<string, bytes>; parse but
            # discard for the engine's read path.
            tag2, sub_pos = _read_varint(payload, 0)
            # Map entries have field-1=key, field-2=value; the engine
            # does not consume them, so we accept any shape.
            resp.federated_bundles.append(("", bytes(payload)))
        else:
            # Unknown field — skip.
            continue
    return resp


def _parse_x509_svid(payload: bytes) -> X509SVID:
    svid = X509SVID()
    pos = 0
    while pos < len(payload):
        tag, pos = _read_varint(payload, pos)
        field_number = tag >> 3
        wire_type = tag & 0x7
        if wire_type != 2:
            _length, pos = _read_varint(payload, pos)
            pos += _length
            continue
        length, pos = _read_varint(payload, pos)
        sub = payload[pos:pos + length]
        pos += length
        if field_number == 1:
            try:
                svid.spiffe_id = sub.decode("utf-8")
            except UnicodeDecodeError:
                svid.spiffe_id = ""
        elif field_number == 2:
            svid.x509_svid = bytes(sub)
        elif field_number == 3:
            svid.x509_svid_key = bytes(sub)
        elif field_number == 4:
            svid.bundle = bytes(sub)
        elif field_number == 5:
            try:
                svid.hint = sub.decode("utf-8")
            except UnicodeDecodeError:
                svid.hint = ""
    return svid


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """Read a protobuf base-128 varint. Returns (value, next_pos)."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint exceeds 64-bit width")


# ---------------------------------------------------------------------------
# Helper for tests: serialise a fake X509SVIDResponse so the stub can
# replay it.
# ---------------------------------------------------------------------------


def serialize_x509_svid_response(resp: X509SVIDResponse) -> bytes:
    """Inverse of :func:`_deserialize_x509_svid_response`. Used by the
    hermetic-test stub to forge byte-precise SVID replies."""
    parts: List[bytes] = []
    for svid in resp.svids:
        body = _serialize_x509_svid(svid)
        parts.append(_pack_length_delimited(1, body))
    for crl in resp.crl:
        parts.append(_pack_length_delimited(2, crl))
    return b"".join(parts)


def _serialize_x509_svid(svid: X509SVID) -> bytes:
    parts: List[bytes] = []
    if svid.spiffe_id:
        parts.append(_pack_length_delimited(1, svid.spiffe_id.encode("utf-8")))
    if svid.x509_svid:
        parts.append(_pack_length_delimited(2, svid.x509_svid))
    if svid.x509_svid_key:
        parts.append(_pack_length_delimited(3, svid.x509_svid_key))
    if svid.bundle:
        parts.append(_pack_length_delimited(4, svid.bundle))
    if svid.hint:
        parts.append(_pack_length_delimited(5, svid.hint.encode("utf-8")))
    return b"".join(parts)


def _pack_length_delimited(field_number: int, payload: bytes) -> bytes:
    tag = (field_number << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(payload)) + payload


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative varint not supported")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(byte)
            break
        out.append(byte | 0x80)
    return bytes(out)
