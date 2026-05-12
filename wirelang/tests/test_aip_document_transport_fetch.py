# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.identity.aip_document_transport_fetch``.

Phase-2 Sprint-4 Tag-4. Tests cover the URL mapping (aip:web → HTTPS),
the V-908 HTTPS-transport composition, the optional DNS-anchor
cross-check (soft + hard modes), and end-to-end composition with the
Tag-3 ``kid_resolver``.

All tests are hermetic: a fake ``urlopen`` is injected into the
V-908 :class:`HTTPSDocumentTransport` and a stub
:class:`TxtResolver` is supplied for the DNS-anchor path. No real
HTTPS calls and no real DNS queries leave the process.
"""

from __future__ import annotations

import copy
import hashlib
import json
import urllib.error
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wirelang.identity import (
    AipDnsAnchorMismatchError,
    AipFetchResult,
    AipUrlSchemeError,
    ResolvedPublicKey,
    aip_web_to_https_url,
    fetch_aip_document,
    resolve_kid,
)
from wirelang.identity.aip_document_transport_fetch import (
    DNS_ANCHOR_PREFIX,
    WELL_KNOWN_AIP_PREFIX,
    _jcs_anchor_hex,
)
from wirelang.identity.aip_https_backend import (
    HTTPSBackendError,
    HTTPSDocumentTransport,
    HTTPSStatusError,
)
from wirelang.identity.dns_anchor import DnsAnchorError, TxtResolver


# ---------------------------------------------------------------------------
# Fakes (mirroring test_aip_https_backend.py for byte-consistency)
# ---------------------------------------------------------------------------


class _FakeHeaders(dict):
    """Lowercased-dict stand-in for an http.client.HTTPMessage."""

    def get(self, key, default=None):
        return super().get(key.lower() if isinstance(key, str) else key, default)


@dataclass
class _FakeResponse:
    status: int
    body: bytes
    headers: _FakeHeaders

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            return self.body
        return self.body[:n]


@dataclass
class _Call:
    url: str
    method: str
    headers: dict
    timeout: float


class _FakeUrlopen:
    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self.calls: list[_Call] = []

    def __call__(self, request, *, timeout, context=None):
        headers_dict = {
            (k.lower() if isinstance(k, str) else k): v
            for (k, v) in (request.header_items() or [])
        }
        self.calls.append(
            _Call(
                url=request.full_url,
                method=request.get_method(),
                headers=headers_dict,
                timeout=float(timeout),
            )
        )
        if not self._script:
            raise AssertionError(
                "FakeUrlopen called more times than scripted; call %d to %r"
                % (len(self.calls), request.full_url)
            )
        next_step = self._script.pop(0)
        if isinstance(next_step, BaseException):
            raise next_step
        return next_step


def _make_response(body: dict | bytes, *, status: int = 200) -> _FakeResponse:
    if isinstance(body, dict):
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    else:
        raw = body
    headers = _FakeHeaders()
    headers["content-type"] = "application/json"
    return _FakeResponse(status=status, body=raw, headers=headers)


class _FakeTxtResolver:
    """Programmable TxtResolver stand-in.

    Maps anchor-host -> list[str] script entries. A list of TXT records
    is returned verbatim; an Exception instance is raised; ``None``
    triggers a :class:`DnsAnchorError` (no record).
    """

    def __init__(self, table: dict[str, object]) -> None:
        self._table = dict(table)
        self.calls: list[tuple[str, float]] = []

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        self.calls.append((name, float(timeout_s)))
        if name not in self._table:
            # Mimic a "no record" condition without leaking a typed error
            # from this class: return [] and let parse_anchor raise.
            return []
        entry = self._table[name]
        if isinstance(entry, BaseException):
            raise entry
        assert isinstance(entry, list)
        return list(entry)


# ---------------------------------------------------------------------------
# AIP-doc fixtures
# ---------------------------------------------------------------------------


_SEED_A: bytes = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
"""RFC 8032 test-vector 1 seed."""


def _keypair(seed: bytes) -> tuple[bytes, bytes]:
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key()
    priv = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub


def _aip_doc(pub: bytes, *, persona_id: str = "treasury-issuer") -> dict:
    return {
        "aip": "1.0",
        "id": f"aip:web:wakir.dev/personas/{persona_id}",
        "name": persona_id,
        "public_keys": [
            {
                "kid": "biscuit-root-1",
                "alg": "Ed25519",
                "key_hex": pub.hex(),
                "validafter": "2026-05-01T00:00:00Z",
                "validuntil": None,
                "purpose": "biscuit-root",
            },
        ],
        "delegation": {"mode": "chained"},
        "protocols": ["wirelang/0.1"],
        "expires": "2027-05-01T00:00:00Z",
        "document_signature": {
            "alg": "Ed25519",
            "kid": "biscuit-root-1",
            "signature": "00" * 64,
        },
    }


def _anchor_hex_for(aip_doc: dict) -> str:
    """Compute the wire-form anchor hex (mirrors module's internal)."""
    body = copy.deepcopy(aip_doc)
    body.pop("document_signature", None)
    # Reuse the module's helper to guarantee byte-identity with the
    # production fingerprint computation.
    return _jcs_anchor_hex(aip_doc)


def _anchor_txt(hex_fp: str) -> str:
    return f"v=1; sha256={hex_fp}"


def _transport(script: list[object]) -> tuple[HTTPSDocumentTransport, _FakeUrlopen]:
    fake = _FakeUrlopen(script)
    transport = HTTPSDocumentTransport(urlopen=fake)
    return transport, fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_T_AIP_FT_01_aip_web_to_https_url_canonical() -> None:
    """aip:web:host/path → https://host/.well-known/aip/path.json."""
    url, host = aip_web_to_https_url(
        "aip:web:wakir.dev/personas/treasury-issuer"
    )
    assert host == "wakir.dev"
    assert url == (
        "https://wakir.dev"
        + WELL_KNOWN_AIP_PREFIX
        + "personas/treasury-issuer.json"
    )

    # No-path form → index.json under .well-known/aip/.
    url2, host2 = aip_web_to_https_url("aip:web:peer-a.example")
    assert host2 == "peer-a.example"
    assert url2 == (
        "https://peer-a.example" + WELL_KNOWN_AIP_PREFIX + "index.json"
    )

    # Trailing .json on persona-path is stripped (canonical form).
    url3, _ = aip_web_to_https_url("aip:web:wakir.dev/issuer.json")
    assert url3 == (
        "https://wakir.dev" + WELL_KNOWN_AIP_PREFIX + "issuer.json"
    )

    # Pre-resolved https:// passes through verbatim.
    url4, host4 = aip_web_to_https_url(
        "https://wakir.dev/.well-known/aip/treasury-issuer.json"
    )
    assert host4 == "wakir.dev"
    assert url4 == "https://wakir.dev/.well-known/aip/treasury-issuer.json"


def test_T_AIP_FT_02_aip_web_to_https_url_rejects_bad_inputs() -> None:
    """Structural URL-scheme failures raise AipUrlSchemeError."""
    with pytest.raises(AipUrlSchemeError):
        aip_web_to_https_url("")
    with pytest.raises(AipUrlSchemeError):
        aip_web_to_https_url("aip:web:")
    with pytest.raises(AipUrlSchemeError):
        aip_web_to_https_url("aip:web:/persona-path-only")
    with pytest.raises(AipUrlSchemeError):
        aip_web_to_https_url("did:web:wakir.dev:personas:x")
    # V-908 §3.3 forbids plaintext http://.
    with pytest.raises(AipUrlSchemeError, match="V-908"):
        aip_web_to_https_url("http://wakir.dev/.well-known/aip/x.json")
    with pytest.raises(AipUrlSchemeError):
        aip_web_to_https_url("https://")


def test_T_AIP_FT_03_fetch_happy_path_no_dns() -> None:
    """Plain https fetch without DNS-anchor cross-check returns body."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    transport, fake = _transport([_make_response(doc)])

    result = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport,
    )

    assert isinstance(result, AipFetchResult)
    assert result.aip_id == "aip:web:wakir.dev/personas/treasury-issuer"
    assert result.host == "wakir.dev"
    assert result.url == (
        "https://wakir.dev"
        + WELL_KNOWN_AIP_PREFIX
        + "personas/treasury-issuer.json"
    )
    assert result.aip_doc["id"] == doc["id"]
    assert result.body_bytes  # non-empty
    assert isinstance(result.jcs_sha256_hex, str)
    assert len(result.jcs_sha256_hex) == 64
    assert result.dns_anchor is None
    assert result.anchor_matched is False

    # Exactly one HTTPS call, at the mapped URL.
    assert len(fake.calls) == 1
    assert fake.calls[0].url == result.url


def test_T_AIP_FT_04_fetch_propagates_https_status_error() -> None:
    """HTTP 404 surfaces as the V-908 HTTPSStatusError, unwrapped."""
    err = urllib.error.HTTPError(
        "https://wakir.dev/.well-known/aip/missing.json",
        404,
        "Not Found",
        _FakeHeaders(),
        None,
    )
    try:
        err.close()
    except Exception:
        pass

    transport, _ = _transport([err])

    with pytest.raises(HTTPSStatusError) as excinfo:
        fetch_aip_document(
            "aip:web:wakir.dev/personas/missing",
            transport=transport,
        )
    assert excinfo.value.status == 404


def test_T_AIP_FT_05_fetch_rejects_non_object_root_body() -> None:
    """A JSON-array root body raises HTTPSPayloadError via the transport.

    The V-908 :class:`HTTPSDocumentTransport` already enforces "body
    must be a JSON object" at the transport layer; Tag-4's defensive
    guard is therefore dead code in the production wire and we test
    the transport's contract here. This pins both invariants in one
    place.
    """
    from wirelang.identity.aip_https_backend import HTTPSPayloadError

    transport, _ = _transport([_make_response(b"[1,2,3]")])

    with pytest.raises(HTTPSPayloadError, match="not a JSON object"):
        fetch_aip_document(
            "aip:web:wakir.dev/personas/array-body",
            transport=transport,
        )


def test_T_AIP_FT_06_dns_anchor_soft_match() -> None:
    """anchor_required=False with matching DNS TXT → anchor_matched=True."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    fp = _anchor_hex_for(doc)

    transport, _ = _transport([_make_response(doc)])
    dns = _FakeTxtResolver(
        {f"{DNS_ANCHOR_PREFIX}wakir.dev": [_anchor_txt(fp)]}
    )

    result = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport,
        dns_resolver=dns,
        anchor_required=False,
    )

    assert result.anchor_matched is True
    assert result.dns_anchor is not None
    assert result.dns_anchor.fingerprint == fp
    assert result.dns_anchor.host == f"{DNS_ANCHOR_PREFIX}wakir.dev"
    assert result.jcs_sha256_hex == fp

    # DNS resolver was queried with the prefixed host.
    assert dns.calls == [(f"{DNS_ANCHOR_PREFIX}wakir.dev", 3.0)]


def test_T_AIP_FT_07_dns_anchor_soft_absent() -> None:
    """anchor_required=False with absent TXT → anchor=None, no raise."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    transport, _ = _transport([_make_response(doc)])

    # Empty table → resolver returns [] → parse_anchor raises → soft mode
    # swallows.
    dns = _FakeTxtResolver({})

    result = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport,
        dns_resolver=dns,
        anchor_required=False,
    )

    assert result.dns_anchor is None
    assert result.anchor_matched is False


def test_T_AIP_FT_08_dns_anchor_hard_mismatch_raises() -> None:
    """anchor_required=True with mismatched TXT → AipDnsAnchorMismatchError."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    fp = _anchor_hex_for(doc)
    wrong_fp = hashlib.sha256(b"wrong").hexdigest()

    transport, _ = _transport([_make_response(doc)])
    dns = _FakeTxtResolver(
        {f"{DNS_ANCHOR_PREFIX}wakir.dev": [_anchor_txt(wrong_fp)]}
    )

    with pytest.raises(AipDnsAnchorMismatchError) as excinfo:
        fetch_aip_document(
            "aip:web:wakir.dev/personas/treasury-issuer",
            transport=transport,
            dns_resolver=dns,
            anchor_required=True,
        )
    assert excinfo.value.host == "wakir.dev"
    assert excinfo.value.aip_id.startswith("aip:web:")
    assert excinfo.value.expected == fp
    assert excinfo.value.observed == wrong_fp


def test_T_AIP_FT_09_dns_anchor_hard_absent_raises() -> None:
    """anchor_required=True with no TXT → AipDnsAnchorMismatchError."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    transport, _ = _transport([_make_response(doc)])
    dns = _FakeTxtResolver({})  # → resolver returns [] → DnsAnchorError

    with pytest.raises(AipDnsAnchorMismatchError, match="lookup failed"):
        fetch_aip_document(
            "aip:web:wakir.dev/personas/treasury-issuer",
            transport=transport,
            dns_resolver=dns,
            anchor_required=True,
        )


def test_T_AIP_FT_10_anchor_required_without_resolver_raises() -> None:
    """anchor_required=True with dns_resolver=None → eager raise."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    transport, fake = _transport([_make_response(doc)])

    with pytest.raises(AipDnsAnchorMismatchError, match="dns_resolver is None"):
        fetch_aip_document(
            "aip:web:wakir.dev/personas/treasury-issuer",
            transport=transport,
            anchor_required=True,
        )
    # HTTPS fetch still occurred (the eager raise happens post-fetch in
    # the current implementation; the contract documents this).
    assert len(fake.calls) == 1


def test_T_AIP_FT_11_cross_layer_with_kid_resolver() -> None:
    """End-to-end: fetch → resolve_kid produces correct public key."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    transport, _ = _transport([_make_response(doc)])

    result = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport,
    )

    resolved = resolve_kid(result.aip_doc, kid="biscuit-root-1")
    assert isinstance(resolved, ResolvedPublicKey)
    assert resolved.public_key == pub
    assert resolved.kid == "biscuit-root-1"
    assert resolved.purpose == "biscuit-root"


def test_T_AIP_FT_12_determinism_and_passthrough() -> None:
    """Repeated calls produce byte-equal results; pre-resolved https:// passes through."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)

    # First call via aip:web.
    transport1, _ = _transport([_make_response(doc)])
    r1 = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport1,
    )

    # Second call same input, fresh transport, byte-equal response.
    transport2, _ = _transport([_make_response(doc)])
    r2 = fetch_aip_document(
        "aip:web:wakir.dev/personas/treasury-issuer",
        transport=transport2,
    )

    assert r1.jcs_sha256_hex == r2.jcs_sha256_hex
    assert r1.url == r2.url
    assert r1.host == r2.host
    assert r1.aip_doc == r2.aip_doc

    # Pre-resolved https:// shape produces same body (URL passes through;
    # host is parsed identically).
    transport3, fake3 = _transport([_make_response(doc)])
    r3 = fetch_aip_document(
        "https://wakir.dev/.well-known/aip/personas/treasury-issuer.json",
        transport=transport3,
    )
    assert r3.url == (
        "https://wakir.dev/.well-known/aip/personas/treasury-issuer.json"
    )
    assert r3.host == "wakir.dev"
    assert r3.aip_doc == doc
    assert r3.jcs_sha256_hex == r1.jcs_sha256_hex
    assert len(fake3.calls) == 1
