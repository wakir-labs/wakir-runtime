# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.identity.ftd_verifier`` (V-908 PS-4).

These tests exercise the Phase-1b FTD-doc verify pipeline end-to-end:

* Three positive-path FTD-doc roundtrips (single-issuer-key,
  multi-key-window, rotation-overlap), each constructed in-test with
  a stable Ed25519 keypair so the test pack does not depend on
  fixture-file maintenance.
* Negative paths covering each row of V-908 spec §4.6
  (FTDSchemaError, FTDIDMismatchError, FTDSignatureError,
  FTDAnchorError, FTDExpiredError, FTDIssuerKeyError) plus the
  DNS-NXDOMAIN failure mode surfaced through the resolver.
* :class:`FTDCache` behaviour: hit, miss, expiry / refresh-margin
  clamp, pin-poison eviction.

Hermetic boundaries:

* No real DNS, no HTTPS. The DNS layer uses a fake
  :class:`TxtResolver` that returns canned TXT-record sets.
* No third-party dependencies. The verifier's pure-Python Ed25519
  verify (used when the ``cryptography`` package is absent) is the
  hot path of the test suite; the same primitive is used to sign
  test fixtures.
* No file-system reads beyond the source files of the module under
  test. The schema file at
  ``wirelang/schemas/federation-trust-document.json`` is loaded only
  to spot-check that the structural validator and the JSON Schema
  agree on the test vectors.

The test loader follows the Tag-5 two-path strategy
(see ``test_dns_anchor.py`` for the rationale): try the package
import first, fall back to a direct file load when the eager
``wirelang/identity/__init__.py`` fails on a missing optional
sibling dependency.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from unittest import mock


# ---------------------------------------------------------------------------
# Module loader -- two-path strategy (matches test_dns_anchor.py)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DNS_ANCHOR_PATH = _REPO_ROOT / "wirelang" / "identity" / "dns_anchor.py"
_FTD_VERIFIER_PATH = _REPO_ROOT / "wirelang" / "identity" / "ftd_verifier.py"
_SCHEMA_PATH = (
    _REPO_ROOT / "wirelang" / "schemas" / "federation-trust-document.json"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_under_test():
    """Load dns_anchor + ftd_verifier irrespective of cryptography presence."""
    try:
        dns_anchor = importlib.import_module("wirelang.identity.dns_anchor")
        ftd_verifier = importlib.import_module("wirelang.identity.ftd_verifier")
        return dns_anchor, ftd_verifier
    except ModuleNotFoundError:
        # Direct-file load. dns_anchor must register under the canonical
        # name so ftd_verifier's relative import ``from .dns_anchor import ...``
        # resolves correctly when we exec ftd_verifier under that same
        # canonical name.
        dns_anchor = _load_module("wirelang.identity.dns_anchor", _DNS_ANCHOR_PATH)
        ftd_verifier = _load_module(
            "wirelang.identity.ftd_verifier", _FTD_VERIFIER_PATH
        )
        return dns_anchor, ftd_verifier


_dns_anchor, _ftd_verifier = _load_under_test()

DnsAnchor = _dns_anchor.DnsAnchor
DnsAnchorError = _dns_anchor.DnsAnchorError
TxtResolver = _dns_anchor.TxtResolver

FTDAnchorError = _ftd_verifier.FTDAnchorError
FTDCache = _ftd_verifier.FTDCache
FTDExpiredError = _ftd_verifier.FTDExpiredError
FTDIDMismatchError = _ftd_verifier.FTDIDMismatchError
FTDIssuerKeyError = _ftd_verifier.FTDIssuerKeyError
FTDSchemaError = _ftd_verifier.FTDSchemaError
FTDSignatureError = _ftd_verifier.FTDSignatureError
FTDVerifyError = _ftd_verifier.FTDVerifyError
ValidIssuerKey = _ftd_verifier.ValidIssuerKey
VerifyResult = _ftd_verifier.VerifyResult
compute_ftd_fingerprint_from_body = _ftd_verifier.compute_ftd_fingerprint_from_body
verify_ftd_document = _ftd_verifier.verify_ftd_document
DEFAULT_FTD_CACHE_REFRESH_MARGIN_S = (
    _ftd_verifier.DEFAULT_FTD_CACHE_REFRESH_MARGIN_S
)


# ---------------------------------------------------------------------------
# Pure-Python Ed25519 sign+verify -- test-only helper.
#
# We need to construct test FTD-docs with a real Ed25519 signature, but
# the test suite must run in environments without the ``cryptography``
# package. The ``ftd_verifier`` module itself ships a pure-Python
# verify (RFC 8032 reference) for the same reason; here we extend that
# with a sign primitive (also pure-Python) used only inside this test
# file. Determinism is guaranteed by RFC 8032 ("EdDSA is deterministic").
#
# These primitives are NOT exported from the production module because
# Wakir does not sign FTD-docs in-process at runtime; signing happens
# in the peer organisation and the signed document arrives over HTTPS.
# Tests are the only consumer of an in-tree Ed25519 sign, and ship the
# implementation locally.
# ---------------------------------------------------------------------------


_P = (1 << 255) - 19
_L = (1 << 252) + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def _sha512_int(b: bytes) -> int:
    return int.from_bytes(hashlib.sha512(b).digest(), "little")


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * pow(2, (_P - 1) // 4, _P)) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * pow(5, _P - 2, _P)) % _P
_BX = _x_recover(_BY)
_B = (_BX % _P, _BY % _P, 1, (_BX * _BY) % _P)


def _edwards_add(P, Q):
    x1, y1, z1, t1 = P
    x2, y2, z2, t2 = Q
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (t1 * 2 * _D * t2) % _P
    dd = (z1 * 2 * z2) % _P
    e_ = (b - a) % _P
    f = (dd - c) % _P
    g = (dd + c) % _P
    h = (b + a) % _P
    return ((e_ * f) % _P, (g * h) % _P, (f * g) % _P, (e_ * h) % _P)


def _scalar_mult(P, e_):
    if e_ == 0:
        return (0, 1, 1, 0)
    Q = _scalar_mult(P, e_ // 2)
    Q = _edwards_add(Q, Q)
    if e_ & 1:
        Q = _edwards_add(Q, P)
    return Q


def _point_compress(P):
    x, y, z, _t = P
    zinv = pow(z, _P - 2, _P)
    x = (x * zinv) % _P
    y = (y * zinv) % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _ed25519_pubkey(seed: bytes) -> bytes:
    """Derive the Ed25519 public key from a 32-byte seed (RFC 8032 §5.1.5)."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 127
    a[31] |= 64
    a_int = int.from_bytes(bytes(a), "little")
    A = _scalar_mult(_B, a_int)
    return _point_compress(A)


def _ed25519_sign(seed: bytes, message: bytes) -> bytes:
    """Sign ``message`` with the 32-byte Ed25519 seed (RFC 8032 §5.1.6)."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 127
    a[31] |= 64
    a_int = int.from_bytes(bytes(a), "little")
    prefix = h[32:64]
    A = _scalar_mult(_B, a_int)
    A_enc = _point_compress(A)
    r = _sha512_int(prefix + message) % _L
    R = _scalar_mult(_B, r)
    R_enc = _point_compress(R)
    k = _sha512_int(R_enc + A_enc + message) % _L
    s = (r + k * a_int) % _L
    return R_enc + s.to_bytes(32, "little")


# ---------------------------------------------------------------------------
# FTD-doc factory -- builds a test FTD-doc with a real Ed25519 signature
# and the matching DNS anchor fingerprint.
# ---------------------------------------------------------------------------


_TEST_ROOT_SEED = bytes.fromhex(
    "1111111111111111111111111111111111111111111111111111111111111111"
)
_TEST_ROOT_PUBKEY = _ed25519_pubkey(_TEST_ROOT_SEED)
_TEST_ROOT_PUBKEY_HEX = _TEST_ROOT_PUBKEY.hex()

_TEST_ISSUER_SEED_A = bytes.fromhex(
    "2222222222222222222222222222222222222222222222222222222222222222"
)
_TEST_ISSUER_PUBKEY_A_HEX = _ed25519_pubkey(_TEST_ISSUER_SEED_A).hex()

_TEST_ISSUER_SEED_B = bytes.fromhex(
    "3333333333333333333333333333333333333333333333333333333333333333"
)
_TEST_ISSUER_PUBKEY_B_HEX = _ed25519_pubkey(_TEST_ISSUER_SEED_B).hex()


def _now_utc() -> datetime:
    return datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)


def _build_ftd_doc(
    *,
    issuer_keys: Iterable[dict],
    ftd_id: str = "did:web:peer-org.example:ftd:v1",
    domain: str = "peer-org.example",
    issued_at: str = "2026-06-01T00:00:00Z",
    expires: str = "2027-06-01T00:00:00Z",
    anchor_host_override: str | None = None,
    root_seed: bytes = _TEST_ROOT_SEED,
    root_pubkey_hex: str = _TEST_ROOT_PUBKEY_HEX,
    extra: dict | None = None,
) -> tuple[dict, str]:
    """Return a (signed FTD-doc, fingerprint_hex) pair.

    The doc is constructed, fingerprint-recomputed, anchor-set, then
    signed. Returns the JSON-ready dict and the fingerprint hex.
    """
    anchor_host = anchor_host_override or f"_wakir-ftd.{domain}"
    body: dict = {
        "wakir_ftd": "0.1.0",
        "id": ftd_id,
        "domain": domain,
        "issued_at": issued_at,
        "expires": expires,
        "ftd_root_pubkey": root_pubkey_hex,
        "issuer_keys": list(issuer_keys),
        "anchor": {
            "kind": "dns-txt",
            "host": anchor_host,
            # Operational mirror of the DNS-published fingerprint.
            # The verifier compares DNS to ``SHA-256(JCS(body \
            # document_signature))``; this body field is informative
            # and is filled with the same value for human-inspection
            # consistency. See ``ftd_verifier.verify_ftd_document``
            # step 5 for the normative comparison rule.
            "fingerprint_sha256": "0" * 64,
        },
    }
    if extra:
        body.update(extra)
    # The verifier recomputes ``SHA-256(JCS(body \ document_signature))``
    # at verify time and compares the resulting digest to the DNS
    # anchor; the on-document ``anchor.fingerprint_sha256`` is
    # informative provenance only. We therefore leave the placeholder
    # in place, compute the digest exactly once, and use that digest
    # for both the signature pre-image and the DNS-anchor value.
    fingerprint = compute_ftd_fingerprint_from_body(body)
    # Sign the body (without document_signature), per V-908 §2.2.
    canonical = _ftd_verifier._jcs_canonicalise(body)
    digest = hashlib.sha256(canonical).digest()
    sig = _ed25519_sign(root_seed, digest)
    body["document_signature"] = {
        "alg": "Ed25519",
        "kid": "ftd-root-1",
        "signature": sig.hex(),
    }
    return body, fingerprint


# ---------------------------------------------------------------------------
# Fake DNS resolver (TxtResolver Protocol).
# ---------------------------------------------------------------------------


class _FakeResolver:
    """In-memory TXT-record resolver for hermetic tests.

    Stores a ``host -> list[str]`` map. ``resolve_txt`` returns the
    list, or raises if the host is registered with a sentinel
    ``Exception`` value. NXDOMAIN is modelled by mapping the host to
    ``[]`` (the dns_anchor protocol contract).
    """

    def __init__(self) -> None:
        self._records: dict[str, object] = {}

    def set(self, host: str, records: list[str]) -> None:
        self._records[host] = records

    def set_error(self, host: str, exc: Exception) -> None:
        self._records[host] = exc

    def set_nxdomain(self, host: str) -> None:
        self._records[host] = []

    def resolve_txt(self, name: str, *, timeout_s: float = 3.0) -> list[str]:
        if name not in self._records:
            return []
        rec = self._records[name]
        if isinstance(rec, Exception):
            raise rec
        return list(rec)


def _txt_anchor(fingerprint_hex: str) -> str:
    return f"v=1; sha256={fingerprint_hex}"


# ---------------------------------------------------------------------------
# Positive-path tests
# ---------------------------------------------------------------------------


class FtdVerifyHappyPathTests(unittest.TestCase):
    """Three canonical positive vectors; cf. V-908 §6.1 PS-4 list."""

    def setUp(self) -> None:
        self.now = _now_utc()
        self.resolver = _FakeResolver()

    def _verify(self, doc: dict, ftd_id: str) -> VerifyResult:
        return verify_ftd_document(
            json.dumps(doc).encode("utf-8"),
            ftd_id,
            resolver=self.resolver,
            now=self.now,
        )

    def test_vector_1_single_issuer_key(self) -> None:
        """One issuer key, valid window covers ``now``."""
        doc, fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-1",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-01T00:00:00Z",
                    "valid_until": "2027-06-01T00:00:00Z",
                }
            ]
        )
        self.resolver.set(doc["anchor"]["host"], [_txt_anchor(fp)])
        result = self._verify(doc, doc["id"])
        self.assertEqual(result.ftd_id, doc["id"])
        self.assertEqual(result.fingerprint_sha256, fp)
        self.assertEqual(len(result.valid_issuer_keys), 1)
        self.assertEqual(
            result.valid_issuer_keys[0].public_key_hex,
            _TEST_ISSUER_PUBKEY_A_HEX,
        )
        self.assertEqual(result.valid_issuer_keys[0].purpose, "biscuit-root")
        self.assertEqual(result.anchor_host, doc["anchor"]["host"])

    def test_vector_2_multi_key_window(self) -> None:
        """Two issuer keys, both currently in window."""
        doc, fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-1",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-01T00:00:00Z",
                    "valid_until": "2026-12-01T00:00:00Z",
                },
                {
                    "kid": "issuer-2",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_B_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-15T00:00:00Z",
                    "valid_until": None,
                },
            ]
        )
        self.resolver.set(doc["anchor"]["host"], [_txt_anchor(fp)])
        # Use a wall-clock that overlaps both keys.
        now = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = verify_ftd_document(
            json.dumps(doc).encode("utf-8"),
            doc["id"],
            resolver=self.resolver,
            now=now,
        )
        self.assertEqual(len(result.valid_issuer_keys), 2)
        kids = sorted(k.kid for k in result.valid_issuer_keys)
        self.assertEqual(kids, ["issuer-1", "issuer-2"])

    def test_vector_3_rotation_overlap(self) -> None:
        """Old key past, new key live; only the new key is returned."""
        doc, fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-old",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-01-01T00:00:00Z",
                    "valid_until": "2026-06-01T00:00:00Z",
                },
                {
                    "kid": "issuer-new",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_B_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-05-15T00:00:00Z",
                    "valid_until": None,
                },
            ]
        )
        self.resolver.set(doc["anchor"]["host"], [_txt_anchor(fp)])
        result = self._verify(doc, doc["id"])
        self.assertEqual(len(result.valid_issuer_keys), 1)
        self.assertEqual(result.valid_issuer_keys[0].kid, "issuer-new")


# ---------------------------------------------------------------------------
# Negative-path tests
# ---------------------------------------------------------------------------


class FtdVerifyNegativePathTests(unittest.TestCase):
    """Each row of V-908 §4.6 produces at least one test."""

    def setUp(self) -> None:
        self.now = _now_utc()
        self.resolver = _FakeResolver()
        self.doc, self.fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-1",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-01T00:00:00Z",
                    "valid_until": "2027-06-01T00:00:00Z",
                }
            ]
        )

    def _verify(self, doc: dict, ftd_id: str | None = None, now: datetime | None = None):
        return verify_ftd_document(
            json.dumps(doc).encode("utf-8"),
            ftd_id if ftd_id is not None else doc["id"],
            resolver=self.resolver,
            now=now if now is not None else self.now,
        )

    def test_schema_error_missing_field(self) -> None:
        broken = copy.deepcopy(self.doc)
        del broken["domain"]
        with self.assertRaises(FTDSchemaError):
            self._verify(broken)

    def test_schema_error_wrong_version(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["wakir_ftd"] = "0.2.0"
        with self.assertRaises(FTDSchemaError):
            self._verify(broken)

    def test_schema_error_uppercase_root_pubkey(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["ftd_root_pubkey"] = broken["ftd_root_pubkey"].upper()
        with self.assertRaises(FTDSchemaError):
            self._verify(broken)

    def test_schema_error_bad_anchor_host(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["anchor"]["host"] = "wakir-ftd.peer-org.example"  # missing leading underscore
        with self.assertRaises(FTDSchemaError):
            self._verify(broken)

    def test_id_mismatch(self) -> None:
        self.resolver.set(self.doc["anchor"]["host"], [_txt_anchor(self.fp)])
        with self.assertRaises(FTDIDMismatchError):
            self._verify(self.doc, ftd_id="did:web:other-org.example:ftd:v1")

    def test_expired(self) -> None:
        self.resolver.set(self.doc["anchor"]["host"], [_txt_anchor(self.fp)])
        late = datetime(2099, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(FTDExpiredError):
            self._verify(self.doc, now=late)

    def test_issuer_key_window_before(self) -> None:
        # Build a fresh doc whose only key starts in the future.
        future_doc, future_fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-future",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2099-01-01T00:00:00Z",
                    "valid_until": None,
                }
            ]
        )
        self.resolver.set(future_doc["anchor"]["host"], [_txt_anchor(future_fp)])
        with self.assertRaises(FTDIssuerKeyError):
            verify_ftd_document(
                json.dumps(future_doc).encode("utf-8"),
                future_doc["id"],
                resolver=self.resolver,
                now=self.now,
            )

    def test_issuer_key_window_after(self) -> None:
        past_doc, past_fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-past",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2025-01-01T00:00:00Z",
                    "valid_until": "2026-01-01T00:00:00Z",
                }
            ]
        )
        self.resolver.set(past_doc["anchor"]["host"], [_txt_anchor(past_fp)])
        with self.assertRaises(FTDIssuerKeyError):
            verify_ftd_document(
                json.dumps(past_doc).encode("utf-8"),
                past_doc["id"],
                resolver=self.resolver,
                now=self.now,
            )

    def test_anchor_dns_nxdomain(self) -> None:
        self.resolver.set_nxdomain(self.doc["anchor"]["host"])
        with self.assertRaises(FTDAnchorError):
            self._verify(self.doc)

    def test_anchor_dns_transport_error(self) -> None:
        self.resolver.set_error(
            self.doc["anchor"]["host"],
            DnsAnchorError("transport failure"),
        )
        with self.assertRaises(FTDAnchorError):
            self._verify(self.doc)

    def test_anchor_fingerprint_mismatch(self) -> None:
        wrong_fp = "0" * 64
        self.resolver.set(self.doc["anchor"]["host"], [_txt_anchor(wrong_fp)])
        with self.assertRaises(FTDAnchorError):
            self._verify(self.doc)

    def test_signature_tampered(self) -> None:
        broken = copy.deepcopy(self.doc)
        # Flip the last byte of the signature.
        sig_hex = broken["document_signature"]["signature"]
        flipped = sig_hex[:-2] + ("00" if sig_hex[-2:] != "00" else "01")
        broken["document_signature"]["signature"] = flipped
        self.resolver.set(broken["anchor"]["host"], [_txt_anchor(self.fp)])
        with self.assertRaises(FTDSignatureError):
            self._verify(broken)

    def test_signature_wrong_root_key(self) -> None:
        # Re-sign under a different seed but keep the public key field
        # as the original, so the signature does not verify.
        broken = copy.deepcopy(self.doc)
        body_for_sig = copy.deepcopy(broken)
        body_for_sig.pop("document_signature", None)
        canonical = _ftd_verifier._jcs_canonicalise(body_for_sig)
        digest = hashlib.sha256(canonical).digest()
        wrong_seed = bytes.fromhex("99" * 32)
        bad_sig = _ed25519_sign(wrong_seed, digest)
        broken["document_signature"]["signature"] = bad_sig.hex()
        self.resolver.set(broken["anchor"]["host"], [_txt_anchor(self.fp)])
        with self.assertRaises(FTDSignatureError):
            self._verify(broken)

    def test_payload_tampered_after_signing(self) -> None:
        broken = copy.deepcopy(self.doc)
        broken["domain"] = "attacker.example"
        # The DNS anchor still claims the original fingerprint;
        # body-fingerprint check fires before signature.
        self.resolver.set(broken["anchor"]["host"], [_txt_anchor(self.fp)])
        with self.assertRaises(FTDAnchorError):
            self._verify(broken)

    def test_invalid_json(self) -> None:
        with self.assertRaises(FTDSchemaError):
            verify_ftd_document(
                b"{not json",
                "did:web:peer.example:ftd:v1",
                resolver=self.resolver,
                now=self.now,
            )

    def test_invalid_utf8(self) -> None:
        with self.assertRaises(FTDSchemaError):
            verify_ftd_document(
                b"\xff\xff\xff",
                "did:web:peer.example:ftd:v1",
                resolver=self.resolver,
                now=self.now,
            )


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


class FtdCacheTests(unittest.TestCase):
    """V-908 §4.3: hit/miss, refresh-margin clamp, pin-poison."""

    def setUp(self) -> None:
        self.now = _now_utc()
        self.resolver = _FakeResolver()
        self.doc, self.fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-1",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-01T00:00:00Z",
                    "valid_until": "2027-06-01T00:00:00Z",
                }
            ]
        )
        self.resolver.set(self.doc["anchor"]["host"], [_txt_anchor(self.fp)])

    def test_cache_miss_then_hit(self) -> None:
        clock_state = {"t": self.now}
        cache = FTDCache(clock=lambda: clock_state["t"])
        result_a = verify_ftd_document(
            json.dumps(self.doc).encode("utf-8"),
            self.doc["id"],
            resolver=self.resolver,
            now=self.now,
            cache=cache,
        )
        self.assertEqual(len(cache), 1)
        # Mutate the resolver so a re-fetch would fail; cache-hit must short-circuit.
        self.resolver.set_error(
            self.doc["anchor"]["host"],
            DnsAnchorError("must not be called"),
        )
        result_b = verify_ftd_document(
            json.dumps(self.doc).encode("utf-8"),
            self.doc["id"],
            resolver=self.resolver,
            now=self.now,
            cache=cache,
        )
        self.assertIs(result_a, result_b)

    def test_cache_refresh_margin_clamps(self) -> None:
        cache = FTDCache(
            clock=lambda: self.now,
            refresh_margin_s=DEFAULT_FTD_CACHE_REFRESH_MARGIN_S,
        )
        verify_ftd_document(
            json.dumps(self.doc).encode("utf-8"),
            self.doc["id"],
            resolver=self.resolver,
            now=self.now,
            cache=cache,
        )
        # Walk the clock past the (expires - refresh_margin) cutoff and
        # observe lazy-eviction.
        # Doc expires 2027-06-01; margin 60min before that.
        late = datetime(2027, 5, 31, 23, 30, 0, tzinfo=timezone.utc)
        cache._clock = lambda: late  # type: ignore[attr-defined]
        self.assertIsNone(cache.get(self.doc["id"]))

    def test_cache_poison_evicts(self) -> None:
        cache = FTDCache(clock=lambda: self.now)
        verify_ftd_document(
            json.dumps(self.doc).encode("utf-8"),
            self.doc["id"],
            resolver=self.resolver,
            now=self.now,
            cache=cache,
        )
        self.assertEqual(len(cache), 1)
        cache.poison(self.doc["id"])
        self.assertEqual(len(cache), 0)
        self.assertIsNone(cache.get(self.doc["id"]))

    def test_cache_poison_unknown_id_is_noop(self) -> None:
        cache = FTDCache(clock=lambda: self.now)
        # Must not raise.
        cache.poison("did:web:nope.example:ftd:v9")
        self.assertEqual(len(cache), 0)

    def test_refresh_margin_skip_when_cutoff_in_past(self) -> None:
        # If refresh-margin pushes cache_until into the past relative to
        # ``now``, put() refuses the entry.
        cache = FTDCache(
            clock=lambda: self.now,
            refresh_margin_s=10**9,  # 31 years
        )
        result = verify_ftd_document(
            json.dumps(self.doc).encode("utf-8"),
            self.doc["id"],
            resolver=self.resolver,
            now=self.now,
            cache=cache,
        )
        self.assertEqual(len(cache), 0)
        self.assertEqual(result.ftd_id, self.doc["id"])


# ---------------------------------------------------------------------------
# Module surface and schema-on-disk consistency
# ---------------------------------------------------------------------------


class FtdModuleSurfaceTests(unittest.TestCase):
    """Public API stability + schema-on-disk consistency."""

    def test_public_surface_stable(self) -> None:
        expected = {
            "DEFAULT_FTD_CACHE_REFRESH_MARGIN_S",
            "FTDAnchorError",
            "FTDCache",
            "FTDExpiredError",
            "FTDIDMismatchError",
            "FTDIssuerKeyError",
            "FTDSchemaError",
            "FTDSignatureError",
            "FTDVerifyError",
            "ValidIssuerKey",
            "VerifyResult",
            "compute_ftd_fingerprint",
            "compute_ftd_fingerprint_from_body",
            "verify_ftd_document",
        }
        self.assertEqual(set(_ftd_verifier.__all__), expected)

    def test_verify_result_is_frozen(self) -> None:
        result = VerifyResult(
            ftd_id="did:web:x.example:ftd:v1",
            ftd_doc={},
            fingerprint_sha256="0" * 64,
            valid_issuer_keys=(),
            anchor_host="_wakir-ftd.x.example",
            verified_at=_now_utc(),
        )
        with self.assertRaises(Exception):
            result.ftd_id = "tampered"  # type: ignore[misc]

    def test_schema_file_required_fields_match_validator(self) -> None:
        # Spot-check that the JSON Schema on disk matches what the
        # structural validator enforces.
        with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        self.assertEqual(
            schema["properties"]["wakir_ftd"]["const"],
            "0.1.0",
        )
        # The structural validator is the source of truth at runtime;
        # the schema file is authoritative for downstream consumers
        # (Phase-1b schema-registry, Phase-2 NATS-KV). These two MUST
        # agree on the version.
        required = set(schema["required"])
        self.assertIn("wakir_ftd", required)
        self.assertIn("anchor", required)
        self.assertIn("document_signature", required)


# ---------------------------------------------------------------------------
# Compute-fingerprint helpers
# ---------------------------------------------------------------------------


class FtdFingerprintHelperTests(unittest.TestCase):
    """The two compute_*-helpers behave consistently for self-anchored docs."""

    def test_fingerprint_helpers_agree(self) -> None:
        doc, fp = _build_ftd_doc(
            issuer_keys=[
                {
                    "kid": "issuer-1",
                    "alg": "Ed25519",
                    "public_key": _TEST_ISSUER_PUBKEY_A_HEX,
                    "purpose": "biscuit-root",
                    "valid_from": "2026-06-01T00:00:00Z",
                    "valid_until": None,
                }
            ]
        )
        from_body = compute_ftd_fingerprint_from_body(doc)
        # Bytes-form: strip document_signature, JCS-canonicalise externally.
        body_no_sig = copy.deepcopy(doc)
        body_no_sig.pop("document_signature", None)
        canonical = _ftd_verifier._jcs_canonicalise(body_no_sig)
        from_bytes = _ftd_verifier.compute_ftd_fingerprint(canonical)
        self.assertEqual(from_body, from_bytes)
        self.assertEqual(from_body, fp)


# ---------------------------------------------------------------------------
# Golden vector pack -- on-disk fixtures
# ---------------------------------------------------------------------------


_VECTOR_DIR = _REPO_ROOT / "tests" / "fixtures" / "wakir-ftd-vectors"


class FtdGoldenVectorTests(unittest.TestCase):
    """Smoke-verify the on-disk vector pack ships verifiable FTD-docs.

    Mirrors the AIP-document golden-vector test pattern. The fixture
    files are produced by the same factory the in-test vectors use,
    so the pack stays byte-stable across runs.
    """

    def _load_vector(self, name: str) -> dict:
        with (_VECTOR_DIR / name).open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _verify_vector(self, vec: dict) -> VerifyResult:
        doc = vec["document"]
        fp = vec["fingerprint_sha256"]
        when = _ftd_verifier._parse_rfc3339(vec["verify_now"])
        resolver = _FakeResolver()
        resolver.set(doc["anchor"]["host"], [_txt_anchor(fp)])
        return verify_ftd_document(
            json.dumps(doc).encode("utf-8"),
            doc["id"],
            resolver=resolver,
            now=when,
        )

    def test_vector_1_roundtrip(self) -> None:
        vec = self._load_vector("vector-1-single-issuer-key.json")
        result = self._verify_vector(vec)
        self.assertEqual(result.fingerprint_sha256, vec["fingerprint_sha256"])
        self.assertEqual(len(result.valid_issuer_keys), 1)

    def test_vector_2_roundtrip(self) -> None:
        vec = self._load_vector("vector-2-multi-key-window.json")
        result = self._verify_vector(vec)
        self.assertEqual(result.fingerprint_sha256, vec["fingerprint_sha256"])
        self.assertEqual(len(result.valid_issuer_keys), 2)

    def test_vector_3_roundtrip(self) -> None:
        vec = self._load_vector("vector-3-rotation-overlap.json")
        result = self._verify_vector(vec)
        self.assertEqual(result.fingerprint_sha256, vec["fingerprint_sha256"])
        self.assertEqual(len(result.valid_issuer_keys), 1)
        self.assertEqual(result.valid_issuer_keys[0].kid, "issuer-new")

    def test_index_lists_all_vectors(self) -> None:
        with (_VECTOR_DIR / "index.json").open("r", encoding="utf-8") as fh:
            idx = json.load(fh)
        on_disk = sorted(
            p.name for p in _VECTOR_DIR.glob("vector-*.json")
        )
        listed = sorted(idx["vectors"])
        self.assertEqual(on_disk, listed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
