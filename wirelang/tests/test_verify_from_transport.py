# SPDX-License-Identifier: Apache-2.0
"""Tag-9 ``verify_from_transport`` bridge test suite.

Seven tests covering the seven ``VerifyError.kind`` outcomes plus
the happy path (Tag-9 spec § 2.5):

  1  Happy path — AIP body roundtrip with valid signature.
  2  ``transport-failed`` — transport raises an exception.
  3  ``json-parse-failed`` — body_bytes is not valid JSON.
  4  ``schema-failed`` — body missing a required field.
  5  ``id-mismatch`` — body.id != requested doc_id.
  6  ``signature-failed`` — signature verifier returns False.
  7  ``hash-mismatch`` — caller's expected_jcs_sha256 does not match.

All tests use a stub :class:`MockTransport` that implements the
duck-typed protocol; no real network or cryptography is required for
the failure-path tests. The happy-path test uses ``cryptography``
for a real Ed25519 signature.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Optional

import pytest

from wirelang.identity import _jcs_pure
from wirelang.identity.verify_bridge import (
    DocumentTransport,
    VerifyError,
    VerifyResult,
    make_https_aip_verify_fn,
    verify_from_transport,
)


# ---------------------------------------------------------------------------
# Mock transport
# ---------------------------------------------------------------------------


@dataclass
class _StubResponse:
    body: Optional[dict]
    body_bytes: bytes


class MockTransport:
    """Minimal transport stub.

    Constructed with a fixed response (or an exception to raise on
    ``get``). Records the URI that was requested.
    """

    def __init__(
        self,
        *,
        response: Optional[_StubResponse] = None,
        exc: Optional[Exception] = None,
    ) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[str] = []

    def get(self, uri: str):
        self.calls.append(uri)
        if self._exc is not None:
            raise self._exc
        if self._response is None:
            raise RuntimeError("MockTransport has no canned response")
        return self._response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_body() -> dict:
    return {
        "aip": "1.0",
        "id": "aip:web:example.org/agents/test",
        "name": "test-agent",
        "public_keys": [
            {
                "kid": "biscuit-root-1",
                "alg": "Ed25519",
                "key_hex": "00" * 32,
                "validafter": "2026-05-01T00:00:00Z",
            }
        ],
        "delegation": {"mode": "closed"},
        "protocols": [],
        "expires": "2027-05-01T00:00:00Z",
    }


def _stub_schema_loader(name: str) -> dict:
    """Tiny schema covering the minimal body — no const / format /
    pattern so the pure-python validator handles it without
    NotImplementedError.
    """
    if name != "aip-document/0.1.0":
        raise KeyError(name)
    return {
        "type": "object",
        "required": [
            "aip",
            "id",
            "name",
            "public_keys",
            "delegation",
            "protocols",
            "expires",
            "document_signature",
        ],
        "properties": {
            "aip": {"type": "string", "minLength": 1},
            "id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "public_keys": {"type": "array", "minItems": 1},
            "delegation": {"type": "object"},
            "protocols": {"type": "array"},
            "expires": {"type": "string", "minLength": 1},
            "document_signature": {"type": "object"},
        },
    }


def _accept_all_verifier(body: dict, sig: dict, pubkey: bytes) -> bool:
    return True


def _reject_all_verifier(body: dict, sig: dict, pubkey: bytes) -> bool:
    return False


def _stub_pubkey_resolver(body: dict) -> bytes:
    return b"\x00" * 32


def _signed_body() -> tuple[dict, str]:
    """Return ``(body, expected_hash)`` with a real Ed25519 signature."""
    cryptography_mod = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    body = _minimal_body()
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    body["public_keys"][0]["key_hex"] = pub_bytes.hex()

    # Compute signing input the same way aip_signing does.
    body_for_signing = copy.deepcopy(body)
    canonical = _jcs_pure.canonicalize(body_for_signing)
    digest = hashlib.sha256(canonical).digest()
    sig = priv.sign(digest)
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": sig.hex(),
    }
    expected_hash = hashlib.sha256(canonical).hexdigest()
    return body, expected_hash


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_aip_body_roundtrip() -> None:
    cryptography_mod = pytest.importorskip("cryptography")

    body, expected_hash = _signed_body()
    transport = MockTransport(
        response=_StubResponse(body=body, body_bytes=json.dumps(body).encode())
    )

    # Use the real aip_signing.verify_aip_signature path (via default).
    result = verify_from_transport(
        transport,
        body["id"],
        schema_loader=_stub_schema_loader,
        expected_jcs_sha256=expected_hash,
    )
    assert result.ok, f"unexpected failure: {result.error}"
    assert result.document is body  # same object handed through
    assert result.jcs_sha256 == expected_hash
    assert result.source == body["id"]
    assert result.error is None


# ---------------------------------------------------------------------------
# 2. transport-failed
# ---------------------------------------------------------------------------


def test_transport_failure_returns_transport_failed_kind() -> None:
    transport = MockTransport(exc=RuntimeError("connection refused"))
    result = verify_from_transport(
        transport,
        "aip:web:example.org/x",
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "transport-failed"
    assert "connection refused" in result.error.message


# ---------------------------------------------------------------------------
# 3. json-parse-failed
# ---------------------------------------------------------------------------


def test_invalid_json_returns_json_parse_failed_kind() -> None:
    transport = MockTransport(
        response=_StubResponse(body=None, body_bytes=b"not json {")
    )
    result = verify_from_transport(
        transport,
        "aip:web:example.org/x",
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "json-parse-failed"


# ---------------------------------------------------------------------------
# 4. schema-failed
# ---------------------------------------------------------------------------


def test_schema_failure_returns_schema_failed_kind() -> None:
    body = _minimal_body()
    body.pop("id")  # required by stub schema
    transport = MockTransport(
        response=_StubResponse(body=body, body_bytes=json.dumps(body).encode())
    )
    result = verify_from_transport(
        transport,
        "aip:web:example.org/x",
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "schema-failed"


# ---------------------------------------------------------------------------
# 5. id-mismatch
# ---------------------------------------------------------------------------


def test_id_mismatch_returns_id_mismatch_kind() -> None:
    body = _minimal_body()
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "ab" * 64,
    }
    transport = MockTransport(
        response=_StubResponse(body=body, body_bytes=json.dumps(body).encode())
    )
    requested = "aip:web:example.org/different"
    result = verify_from_transport(
        transport,
        requested,
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "id-mismatch"
    assert "different" in result.error.message


# ---------------------------------------------------------------------------
# 6. signature-failed
# ---------------------------------------------------------------------------


def test_signature_failure_returns_signature_failed_kind() -> None:
    body = _minimal_body()
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "ab" * 64,
    }
    transport = MockTransport(
        response=_StubResponse(body=body, body_bytes=json.dumps(body).encode())
    )
    result = verify_from_transport(
        transport,
        body["id"],
        schema_loader=_stub_schema_loader,
        signature_verifier=_reject_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "signature-failed"


# ---------------------------------------------------------------------------
# 7. hash-mismatch
# ---------------------------------------------------------------------------


def test_hash_pin_mismatch_returns_hash_mismatch_kind() -> None:
    body = _minimal_body()
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "ab" * 64,
    }
    transport = MockTransport(
        response=_StubResponse(body=body, body_bytes=json.dumps(body).encode())
    )
    wrong_pin = "00" * 32
    result = verify_from_transport(
        transport,
        body["id"],
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
        expected_jcs_sha256=wrong_pin,
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.kind == "hash-mismatch"
    assert wrong_pin in result.error.message
    assert result.error.cause is None


# ---------------------------------------------------------------------------
# PS-7 wiring: make_https_aip_verify_fn returns a verify_fn callable
# compatible with the Tag-8 HTTPSAipResolver constructor.
# ---------------------------------------------------------------------------


def test_make_https_aip_verify_fn_passes_through_on_happy_path() -> None:
    cryptography_mod = pytest.importorskip("cryptography")

    body, _expected_hash = _signed_body()
    body_bytes = json.dumps(body).encode()
    verify_fn = make_https_aip_verify_fn(schema_loader=_stub_schema_loader)

    out = verify_fn(body["id"], body_bytes, body)
    assert out is body


def test_make_https_aip_verify_fn_raises_on_bad_signature() -> None:
    body = _minimal_body()
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "ab" * 64,
    }
    body_bytes = json.dumps(body).encode()
    verify_fn = make_https_aip_verify_fn(
        schema_loader=_stub_schema_loader,
        signature_verifier=_reject_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    with pytest.raises(RuntimeError) as exc_info:
        verify_fn(body["id"], body_bytes, body)
    err = exc_info.value.args[0]
    assert isinstance(err, VerifyError)
    assert err.kind == "signature-failed"


def test_make_https_aip_verify_fn_with_https_aip_resolver_end_to_end() -> None:
    """End-to-end PS-7 wiring: Tag-8 HTTPSAipResolver + Tag-9 verify_fn.

    Uses Tag-8's transport with a stub urlopen so no network is touched.
    """
    cryptography_mod = pytest.importorskip("cryptography")

    from wirelang.identity.aip_https_backend import (
        HTTPSAipResolver,
        HTTPSDocumentTransport,
    )

    # Production wires aip:web: URIs end-to-end (the resolver is
    # called with body["id"] verbatim); HTTPS scheme rewriting is the
    # caller's concern. For this PS-7-end-to-end test we need a https://
    # body.id so HTTPSDocumentTransport accepts it. We rewrite the
    # signed body's id to the https:// form, recompute the signature
    # against the new canonical bytes.
    body_https, _ = _signed_body()
    https_id = "https://example.org/agents/test"
    body_https["id"] = https_id
    # Re-sign with the new id (re-using the signing key embedded in
    # the body's public_keys[0] would require recovering the priv;
    # instead we use the accept-all signature_verifier on this path).
    body_bytes = json.dumps(body_https).encode()

    # Stub urlopen returning a fake response object.
    class _FakeHeaders:
        def items(self):
            return [
                ("ETag", "\"v1\""),
                ("Cache-Control", "max-age=300"),
                ("Content-Type", "application/json"),
            ]

    class _FakeResponse:
        def __init__(self) -> None:
            self.status = 200
            self.url = https_id
            self.headers = _FakeHeaders()
            self._body = body_bytes
            self._read = False

        def read(self, n: int = -1) -> bytes:
            if self._read:
                return b""
            self._read = True
            return self._body

        def geturl(self) -> str:
            return self.url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *, timeout, context=None):  # noqa: ARG001
        return _FakeResponse()

    transport = HTTPSDocumentTransport(urlopen=fake_urlopen)
    verify_fn = make_https_aip_verify_fn(
        schema_loader=_stub_schema_loader,
        signature_verifier=_accept_all_verifier,
        pubkey_resolver=_stub_pubkey_resolver,
    )
    resolver = HTTPSAipResolver(transport=transport, verify_fn=verify_fn)

    out = resolver.resolve(https_id)
    # Successful pass-through: the parsed body is returned by verify_fn
    # and forwarded by the resolver unchanged.
    assert isinstance(out, dict)
    assert out["id"] == https_id
    assert out["aip"] == "1.0"
