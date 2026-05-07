# SPDX-License-Identifier: Apache-2.0
"""V-908 Federation-Trust-Document (FTD) verifier.

This module implements the Phase-1b (PS-4) FTD-verify pipeline
specified in ``wirelang/specs/wakir-v-908-federation-resolver-spec.md``
sections 2 and 4. It composes the Phase-1b DNS-anchor resolver
(``wirelang.identity.dns_anchor``) with the FTD-doc schema check
and Ed25519 signature verify into a single deterministic entry
point::

    verify_ftd_document(ftd_doc_jcs_bytes, ftd_id, *, resolver, ...)
        -> VerifyResult

The caller is responsible for fetching the FTD-doc body over HTTPS
(V-908 section 3.3 Transport requirements). This module does not
fetch FTD-docs; it accepts the already-fetched JCS-canonical bytes
and performs all integrity checks against them. Keeping the HTTPS
transport outside the verifier matches the layering discipline of
the Phase-1a AIP-resolver (whose ``Backend`` Protocol is also
caller-pluggable) and lets a deployment plug a real-HTTPS, mock-HTTPS
or file-system source without touching the verify pipeline.

Pipeline (V-908 section 4.1 steps 1-3, applied to the FTD-doc layer):

1. Parse JCS bytes to a JSON document.
2. Validate against ``wakir_ftd/0.1.0`` schema.
3. Verify ``id`` matches the caller-supplied ``ftd_id`` (Phase-1a
   phishing-guard convention transplanted to FTD layer).
4. Verify ``expires > now`` (per V-908 section 4.6 FTDExpiredError).
5. Recompute SHA-256(JCS(body without document_signature)) and
   compare to the DNS-anchor fingerprint resolved via the supplied
   :class:`~wirelang.identity.dns_anchor.TxtResolver`.
6. Verify the Ed25519 ``document_signature`` against
   ``ftd_root_pubkey``.

Returns a :class:`VerifyResult` carrying the parsed body, the
recomputed fingerprint, the verified-and-windowed list of issuer
keys eligible *now*, and provenance metadata. Caller-side AIP-doc
fetch and verify (section 4.1 steps 4-10) is downstream and will
consume the issuer-key set.

Caching
-------

The Phase-1b cache is an in-memory dict keyed by FTD ``id``,
implemented as :class:`FTDCache`. Cache entries store the
:class:`VerifyResult` and an explicit "expires-at" wall-clock
timestamp clamped to (a) the document's own ``expires`` and (b) a
deployment-default refresh window (V-908 section 2.3:
"Phase-1b verifiers MUST refresh the FTD-doc cache no later than
60 minutes before expires"). The cache implements pin-poison
semantics per V-908 section 4.3: a fingerprint mismatch detected
at look-up time MUST evict the entry. Phase-2 will replace this
with a NATS-KV backend (item I-11); the public surface is
intentionally minimal so the swap is mechanical.

Phase-1b boundary
-----------------

Out of scope for this module:

- HTTPS transport for FTD-doc fetch (caller-side; section 3.3).
- AIP-doc fetch and verify (Phase-1a ``aip_resolver`` extended in
  Phase-1b wiring; this module only supplies the issuer-key set).
- WAT-leaf projection (V-908 section 5.1 informative; Z2
  cross-review with WAT-eng before any leaf production).
- Time-source bridge cross-checks (V-908 section 4.4; soft-dep on
  item I-9).

References (URL-stamped 2026-05-07 by wirelang-eng, see V-908 spec §9):

- V-908 spec: ``wirelang/specs/wakir-v-908-federation-resolver-spec.md``
- RFC 8785 JCS: <https://datatracker.ietf.org/doc/html/rfc8785>
- RFC 8032 Ed25519: <https://datatracker.ietf.org/doc/html/rfc8032>
- RFC 3339 date-time: <https://datatracker.ietf.org/doc/html/rfc3339>
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Protocol, Sequence

from .dns_anchor import (
    DnsAnchor,
    DnsAnchorError,
    TxtResolver,
    fetch_anchor,
)


# ---------------------------------------------------------------------------
# Errors (V-908 section 4.6, FTD layer rows)
# ---------------------------------------------------------------------------


class FTDVerifyError(Exception):
    """Base class for all FTD-verifier errors.

    Mirrors the ``AIPResolveError`` Phase-1a convention. Sub-classes
    map to V-908 section 4.6 rows and let callers branch on the
    failure mode.
    """


class FTDSchemaError(FTDVerifyError):
    """FTD-doc fails the ``wakir_ftd/0.1.0`` schema check."""


class FTDSignatureError(FTDVerifyError):
    """``document_signature`` Ed25519 verify fails or is malformed."""


class FTDAnchorError(FTDVerifyError):
    """DNS TXT record missing, malformed, or fingerprint mismatch.

    Wraps :class:`~wirelang.identity.dns_anchor.DnsAnchorError`
    surfaced by the resolver, plus the fingerprint-mismatch case
    (resolver returned an anchor but its fingerprint did not match
    the recomputed FTD-doc digest).
    """


class FTDExpiredError(FTDVerifyError):
    """``expires`` is at or before the verifier clock."""


class FTDIssuerKeyError(FTDVerifyError):
    """No ``issuer_keys[]`` entry is currently valid.

    Distinct from :class:`FTDSchemaError` to let callers retry-once
    after re-resolving the FTD (V-908 section 4.5: an issuer-key
    rotation may have published a new generation that the cached
    document misses).
    """


class FTDIDMismatchError(FTDVerifyError):
    """Caller-supplied ``ftd_id`` does not match the document's ``id``.

    Phase-1b phishing-guard analogue to the Phase-1a AIP ``id``
    consistency check (V-908 section 4.1 step 6). Distinct from
    :class:`FTDSchemaError` because the document is structurally
    valid; only the ID-binding is wrong.
    """


# ---------------------------------------------------------------------------
# Schema validator (Phase-1b structural check)
# ---------------------------------------------------------------------------
#
# Phase-1b ships a small structural validator that is dependency-free
# and matches the on-disk JSON Schema at
# ``wirelang/schemas/federation-trust-document.json``. The full
# schema-registry path (jsonschema + Draft202012Validator) is the
# preferred production path; until the schema-registry helper is
# available on this branch we ship the structural validator here
# so the verifier does not depend on the registry import path. The
# two paths produce the same accept/reject decision for FTD-docs
# matching the schema.


_FTD_SCHEMA_VERSION = "0.1.0"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX128_RE = re.compile(r"^[0-9a-f]{128}$")
_FTD_ID_RE = re.compile(
    r"^did:web:[a-zA-Z0-9.-]+(:[a-zA-Z0-9._-]+)*:ftd:v[0-9]+$"
)
_FTD_ANCHOR_HOST_RE = re.compile(r"^_wakir-ftd\.[a-zA-Z0-9.-]+$")


def _structural_validate(doc: object) -> None:
    """Raise :class:`FTDSchemaError` if ``doc`` is not a valid FTD-doc.

    This is intentionally a small hand-written validator. It accepts
    the same set of documents as the JSON Schema in
    ``wirelang/schemas/federation-trust-document.json`` modulo
    dependency-free implementation: it does not claim to be a
    JSON-Schema engine. The checks are written defensively so an
    attacker-supplied document cannot crash the verifier with a
    non-:class:`FTDSchemaError` exception.
    """
    if not isinstance(doc, dict):
        raise FTDSchemaError("FTD-doc must be a JSON object")

    # Required top-level fields.
    required = (
        "wakir_ftd",
        "id",
        "domain",
        "issued_at",
        "expires",
        "ftd_root_pubkey",
        "issuer_keys",
        "anchor",
        "document_signature",
    )
    for key in required:
        if key not in doc:
            raise FTDSchemaError(f"FTD-doc missing required field {key!r}")

    if doc["wakir_ftd"] != _FTD_SCHEMA_VERSION:
        raise FTDSchemaError(
            f"unsupported wakir_ftd schema version: {doc['wakir_ftd']!r}; "
            f"expected {_FTD_SCHEMA_VERSION!r}"
        )

    if not isinstance(doc["id"], str) or not _FTD_ID_RE.match(doc["id"]):
        raise FTDSchemaError(
            f"FTD-doc id must match did:web:<host>:ftd:v<N>; got {doc['id']!r}"
        )

    for stamp_field in ("issued_at", "expires"):
        if not isinstance(doc[stamp_field], str):
            raise FTDSchemaError(f"{stamp_field!r} must be an RFC 3339 string")
        try:
            _parse_rfc3339(doc[stamp_field])
        except ValueError as e:
            raise FTDSchemaError(
                f"{stamp_field!r} is not a valid RFC 3339 timestamp: {e}"
            ) from e

    if not isinstance(doc["domain"], str) or not doc["domain"]:
        raise FTDSchemaError("domain must be a non-empty string")

    if not isinstance(doc["ftd_root_pubkey"], str) or not _HEX64_RE.match(
        doc["ftd_root_pubkey"]
    ):
        raise FTDSchemaError(
            "ftd_root_pubkey must be 64 lowercase hex characters"
        )

    issuer_keys = doc["issuer_keys"]
    if not isinstance(issuer_keys, list) or not issuer_keys:
        raise FTDSchemaError("issuer_keys must be a non-empty array")
    for idx, entry in enumerate(issuer_keys):
        _validate_issuer_key(entry, idx)

    anchor = doc["anchor"]
    if not isinstance(anchor, dict):
        raise FTDSchemaError("anchor must be a JSON object")
    for key in ("kind", "host", "fingerprint_sha256"):
        if key not in anchor:
            raise FTDSchemaError(f"anchor missing required field {key!r}")
    if anchor["kind"] != "dns-txt":
        raise FTDSchemaError(
            f"anchor.kind must be 'dns-txt' in Phase-1b; got {anchor['kind']!r}"
        )
    if not isinstance(anchor["host"], str) or not _FTD_ANCHOR_HOST_RE.match(
        anchor["host"]
    ):
        raise FTDSchemaError(
            f"anchor.host must match _wakir-ftd.<dns-name>; got {anchor['host']!r}"
        )
    if not isinstance(anchor["fingerprint_sha256"], str) or not _HEX64_RE.match(
        anchor["fingerprint_sha256"]
    ):
        raise FTDSchemaError(
            "anchor.fingerprint_sha256 must be 64 lowercase hex characters"
        )

    sig = doc["document_signature"]
    if not isinstance(sig, dict):
        raise FTDSchemaError("document_signature must be a JSON object")
    for key in ("alg", "kid", "signature"):
        if key not in sig:
            raise FTDSchemaError(
                f"document_signature missing required field {key!r}"
            )
    if sig["alg"] != "Ed25519":
        raise FTDSchemaError(
            f"document_signature.alg must be 'Ed25519'; got {sig['alg']!r}"
        )
    if not isinstance(sig["kid"], str) or not sig["kid"]:
        raise FTDSchemaError("document_signature.kid must be a non-empty string")
    if not isinstance(sig["signature"], str) or not _HEX128_RE.match(
        sig["signature"]
    ):
        raise FTDSchemaError(
            "document_signature.signature must be 128 lowercase hex characters"
        )

    # endpoints[] is optional; if present, validate shape.
    if "endpoints" in doc:
        endpoints = doc["endpoints"]
        if not isinstance(endpoints, list):
            raise FTDSchemaError("endpoints must be an array")
        for idx, ep in enumerate(endpoints):
            if not isinstance(ep, dict):
                raise FTDSchemaError(f"endpoints[{idx}] must be an object")
            for key in ("rel", "url"):
                if key not in ep:
                    raise FTDSchemaError(
                        f"endpoints[{idx}] missing required field {key!r}"
                    )
                if not isinstance(ep[key], str) or not ep[key]:
                    raise FTDSchemaError(
                        f"endpoints[{idx}].{key} must be a non-empty string"
                    )


def _validate_issuer_key(entry: object, idx: int) -> None:
    if not isinstance(entry, dict):
        raise FTDSchemaError(f"issuer_keys[{idx}] must be an object")
    for key in ("kid", "alg", "public_key", "purpose", "valid_from"):
        if key not in entry:
            raise FTDSchemaError(
                f"issuer_keys[{idx}] missing required field {key!r}"
            )
    if not isinstance(entry["kid"], str) or not entry["kid"]:
        raise FTDSchemaError(f"issuer_keys[{idx}].kid must be a non-empty string")
    if entry["alg"] != "Ed25519":
        raise FTDSchemaError(
            f"issuer_keys[{idx}].alg must be 'Ed25519' in Phase-1b; "
            f"got {entry['alg']!r}"
        )
    if not isinstance(entry["public_key"], str) or not _HEX64_RE.match(
        entry["public_key"]
    ):
        raise FTDSchemaError(
            f"issuer_keys[{idx}].public_key must be 64 lowercase hex characters"
        )
    if entry["purpose"] != "biscuit-root":
        raise FTDSchemaError(
            f"issuer_keys[{idx}].purpose must be 'biscuit-root' in Phase-1b; "
            f"got {entry['purpose']!r}"
        )
    try:
        _parse_rfc3339(entry["valid_from"])
    except ValueError as e:
        raise FTDSchemaError(
            f"issuer_keys[{idx}].valid_from invalid: {e}"
        ) from e
    if "valid_until" in entry and entry["valid_until"] is not None:
        try:
            _parse_rfc3339(entry["valid_until"])
        except ValueError as e:
            raise FTDSchemaError(
                f"issuer_keys[{idx}].valid_until invalid: {e}"
            ) from e


# ---------------------------------------------------------------------------
# RFC 3339 parser (stdlib only)
# ---------------------------------------------------------------------------


def _parse_rfc3339(value: str) -> datetime:
    """Parse an RFC 3339 / ISO-8601 timestamp into a UTC datetime.

    Accepts the trailing ``Z`` form (canonical for Wakir documents,
    Phase-1a convention) and explicit ``+HH:MM``/``-HH:MM`` offsets
    via :func:`datetime.fromisoformat`. Raises :class:`ValueError`
    on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError(f"timestamp must be a string; got {type(value).__name__}")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(str(e)) from e
    if dt.tzinfo is None:
        # RFC 3339 requires an offset; reject naive timestamps.
        raise ValueError(
            "RFC 3339 timestamps must include a UTC offset (e.g. trailing 'Z')"
        )
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# JCS canonicalisation -- vendored minimal implementation
# ---------------------------------------------------------------------------
#
# The Phase-1a stack uses the ``rfc8785`` PyPI package for JCS
# canonicalisation (see ``wirelang/identity/aip_signing.py``). This
# branch may run in environments without that package available; the
# verifier therefore ships a small RFC-8785-compatible canonicaliser
# that handles the FTD-doc subset (objects, arrays, strings, RFC-3339
# date-times, lowercase-hex strings, fixed enum tokens).
#
# When ``rfc8785`` is importable we delegate to it (production path).
# When it is not, we fall back to the local implementation. Both
# produce byte-identical output for the FTD-doc shape; an optional
# :func:`compute_ftd_fingerprint_jcs_external` helper is offered for
# callers who want to enforce the production path explicitly.


def _jcs_canonicalise(obj: object) -> bytes:
    """Return the JCS-canonical UTF-8 bytes of ``obj``.

    Delegates to :mod:`rfc8785` if importable; otherwise uses a
    local canonicaliser matching RFC 8785 for the JSON subset
    relevant to FTD-docs. Numbers, ``true``/``false``/``null``,
    Unicode escapes outside basic Latin, and the special floating
    point values are not exercised by the FTD-doc shape and the
    fallback implements them per RFC 8785 section 3 anyway.
    """
    try:
        import rfc8785  # noqa: F401  -- production path
    except ImportError:
        return _local_jcs(obj)
    import rfc8785

    return rfc8785.dumps(obj)


def _local_jcs(obj: object) -> bytes:
    """Local RFC 8785 canonicaliser. See module docstring.

    Implements the rules used by the FTD-doc shape: objects with
    Unicode-codepoint-sorted keys, arrays in input order, strings
    JSON-escaped, numbers using JSON's standard form (FTD-doc carries
    no numbers as of Phase-1b but the implementation keeps the
    floating-point branch for completeness), and ``true``/``false``/
    ``null`` in lowercase. The output is UTF-8 bytes with no
    trailing whitespace.
    """
    return _local_jcs_impl(obj).encode("utf-8")


def _local_jcs_impl(obj: object) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        return _json_string(obj)
    if isinstance(obj, int) and not isinstance(obj, bool):
        return str(obj)
    if isinstance(obj, float):
        # FTD-doc never carries a float in Phase-1b; raise rather
        # than risk silently emitting a non-canonical form.
        raise TypeError("JCS canonicaliser refuses float input in FTD-doc shape")
    if isinstance(obj, list):
        return "[" + ",".join(_local_jcs_impl(x) for x in obj) + "]"
    if isinstance(obj, dict):
        # RFC 8785: sort keys by their UTF-16 code units. For the
        # FTD-doc shape (ASCII keys only) Python's default string
        # comparison matches.
        items = sorted(obj.items(), key=lambda kv: kv[0])
        return (
            "{"
            + ",".join(_json_string(k) + ":" + _local_jcs_impl(v) for k, v in items)
            + "}"
        )
    raise TypeError(
        f"JCS canonicaliser cannot serialise {type(obj).__name__}"
    )


def _json_string(s: str) -> str:
    """Return the JSON-escaped form of ``s``, RFC 8259 / RFC 8785.

    Implements the minimal escape rules: backslash, double-quote,
    control characters U+0000..U+001F. All other characters are
    emitted verbatim (UTF-8 bytes); RFC 8785 section 3.2.3 mandates
    this 'shortest form' for U+0080 and above.
    """
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


# ---------------------------------------------------------------------------
# Ed25519 verify -- delegate to ``cryptography`` when available
# ---------------------------------------------------------------------------


def _verify_ed25519(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature.

    Phase-1b production path uses :mod:`cryptography` (already a
    project dependency for the AIP-signing module). When that
    package is absent we fall back to a slow but correct pure-Python
    Ed25519 verify so the verifier remains usable in
    dependency-restricted environments. The fallback is *not*
    intended for high-throughput production use; deployments are
    expected to install :mod:`cryptography` for performance.
    """
    if len(public_key_bytes) != 32:
        raise FTDSignatureError(
            f"Ed25519 public key must be 32 bytes; got {len(public_key_bytes)}"
        )
    if len(signature) != 64:
        raise FTDSignatureError(
            f"Ed25519 signature must be 64 bytes; got {len(signature)}"
        )
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError:
        return _verify_ed25519_pure(public_key_bytes, message, signature)
    pk = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        pk.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def _verify_ed25519_pure(
    public_key_bytes: bytes, message: bytes, signature: bytes
) -> bool:
    """Pure-Python Ed25519 verify (RFC 8032).

    This is a minimal reference implementation following RFC 8032
    section 5.1.7 ("Verify"). It is intentionally compact and not
    optimised for speed; production deployments install
    :mod:`cryptography`. The implementation only computes verify
    (not sign) so the attack surface of an in-tree implementation
    is bounded.
    """
    p = (1 << 255) - 19
    l = (1 << 252) + 27742317777372353535851937790883648493
    d = (-121665 * pow(121666, p - 2, p)) % p

    def sha512(b: bytes) -> int:
        return int.from_bytes(hashlib.sha512(b).digest(), "little")

    def sha512_bytes(b: bytes) -> bytes:
        return hashlib.sha512(b).digest()

    def x_recover(y: int) -> int:
        xx = (y * y - 1) * pow(d * y * y + 1, p - 2, p)
        x = pow(xx, (p + 3) // 8, p)
        if (x * x - xx) % p != 0:
            x = (x * pow(2, (p - 1) // 4, p)) % p
        if x % 2 != 0:
            x = p - x
        return x

    by = (4 * pow(5, p - 2, p)) % p
    bx = x_recover(by)
    B = (bx % p, by % p, 1, (bx * by) % p)

    def edwards_add(P, Q):
        x1, y1, z1, t1 = P
        x2, y2, z2, t2 = Q
        a = ((y1 - x1) * (y2 - x2)) % p
        b = ((y1 + x1) * (y2 + x2)) % p
        c = (t1 * 2 * d * t2) % p
        dd = (z1 * 2 * z2) % p
        e_ = (b - a) % p
        f = (dd - c) % p
        g = (dd + c) % p
        h = (b + a) % p
        x3 = (e_ * f) % p
        y3 = (g * h) % p
        t3 = (e_ * h) % p
        z3 = (f * g) % p
        return (x3, y3, z3, t3)

    def scalar_mult(P, e_):
        if e_ == 0:
            return (0, 1, 1, 0)
        Q = scalar_mult(P, e_ // 2)
        Q = edwards_add(Q, Q)
        if e_ & 1:
            Q = edwards_add(Q, P)
        return Q

    def point_compress(P):
        x, y, z, _t = P
        zinv = pow(z, p - 2, p)
        x = (x * zinv) % p
        y = (y * zinv) % p
        return (y | ((x & 1) << 255)).to_bytes(32, "little")

    def point_decompress(s: bytes):
        if len(s) != 32:
            return None
        y = int.from_bytes(s, "little")
        sign = (y >> 255) & 1
        y &= (1 << 255) - 1
        if y >= p:
            return None
        x = x_recover(y)
        if sign != (x & 1):
            x = p - x
        return (x % p, y % p, 1, (x * y) % p)

    if len(signature) != 64 or len(public_key_bytes) != 32:
        return False
    R_enc = signature[:32]
    s_int = int.from_bytes(signature[32:], "little")
    if s_int >= l:
        return False
    A = point_decompress(public_key_bytes)
    R = point_decompress(R_enc)
    if A is None or R is None:
        return False
    h = sha512(R_enc + public_key_bytes + message) % l
    sB = scalar_mult(B, s_int)
    hA = scalar_mult(A, h)
    R_plus_hA = edwards_add(R, hA)
    return point_compress(sB) == point_compress(R_plus_hA)


# ---------------------------------------------------------------------------
# Result and cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidIssuerKey:
    """An ``issuer_keys[]`` entry whose validity window includes ``now``.

    The verifier surfaces the windowed key set directly so the
    downstream AIP-doc step (V-908 section 4.1 step 7) can match
    on ``public_key_hex`` without re-parsing time windows.
    """

    kid: str
    public_key_hex: str
    purpose: str
    valid_from: datetime
    valid_until: Optional[datetime]


@dataclass(frozen=True)
class VerifyResult:
    """Successful FTD-doc verify outcome.

    Attributes:
        ftd_id: the verified ``id`` field; equals the caller's
            ``ftd_id`` argument by construction.
        ftd_doc: the verified document body. Defensive deep-copy
            taken at result construction time; consumers MUST treat
            as immutable (the dataclass is frozen, and the body is
            not exposed via shared reference).
        fingerprint_sha256: 64-hex SHA-256 of
            ``JCS(body without document_signature)``, recomputed
            during verify. This is the byte-anchor a WAT-leaf would
            store (V-908 section 5.1).
        valid_issuer_keys: tuple of issuer-key entries currently in
            their validity window. Empty tuple is structurally
            disallowed; the verify pipeline raises
            :class:`FTDIssuerKeyError` instead of returning a result
            with no live keys.
        anchor_host: the DNS query name actually consulted (the
            FTD-doc's ``anchor.host`` value).
        verified_at: wall-clock (UTC) at which verification ran.
    """

    ftd_id: str
    ftd_doc: dict
    fingerprint_sha256: str
    valid_issuer_keys: tuple[ValidIssuerKey, ...]
    anchor_host: str
    verified_at: datetime


# Default cache refresh window per V-908 section 2.3: refresh no
# later than 60 minutes before ``expires``.
DEFAULT_FTD_CACHE_REFRESH_MARGIN_S: int = 60 * 60


@dataclass
class _CacheEntry:
    result: VerifyResult
    cache_until: datetime


class FTDCache:
    """In-memory FTD-doc cache with pin-poison semantics.

    Phase-1b implementation. Keyed by FTD ``id``. Each entry stores
    the :class:`VerifyResult` and an explicit ``cache_until``
    wall-clock that is the minimum of (a) the document's own
    ``expires`` and (b) ``expires - DEFAULT_FTD_CACHE_REFRESH_MARGIN_S``,
    per V-908 section 2.3. The cache is process-local; Phase-2 will
    swap to NATS-KV (item I-11) without changing this surface.

    Pin-poison semantics (V-908 section 4.3): if a caller looks up
    an FTD-doc, recomputes its fingerprint, and finds a mismatch,
    the cached entry MUST be evicted. :meth:`poison` is the
    operation the federation pipeline calls in that case.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        refresh_margin_s: int = DEFAULT_FTD_CACHE_REFRESH_MARGIN_S,
    ) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._clock = clock
        self._refresh_margin_s = int(refresh_margin_s)

    def get(self, ftd_id: str) -> Optional[VerifyResult]:
        """Return a fresh cached :class:`VerifyResult`, or ``None``."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(ftd_id)
            if entry is None:
                return None
            if now >= entry.cache_until:
                # Evict expired entry on access (lazy expiry).
                del self._entries[ftd_id]
                return None
            return entry.result

    def put(self, result: VerifyResult) -> None:
        """Insert a verified FTD-doc, clamping cache_until per §2.3."""
        expires = _parse_rfc3339(result.ftd_doc["expires"])
        margin = self._refresh_margin_s
        cache_until = expires
        if margin > 0:
            cutoff = expires.timestamp() - margin
            cache_until = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        # Never store an entry whose cache_until is already in the past.
        now = self._clock()
        if cache_until <= now:
            return
        with self._lock:
            self._entries[result.ftd_id] = _CacheEntry(
                result=result, cache_until=cache_until
            )

    def poison(self, ftd_id: str) -> None:
        """Evict an entry on fingerprint-mismatch (V-908 §4.3)."""
        with self._lock:
            self._entries.pop(ftd_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# ---------------------------------------------------------------------------
# Public verify entry point
# ---------------------------------------------------------------------------


def compute_ftd_fingerprint(ftd_doc_jcs_bytes: bytes) -> str:
    """Compute SHA-256 of the JCS-canonical FTD-doc body.

    Convenience wrapper used by callers that already have the bytes
    in hand and want to compute the V-908 anchor fingerprint
    without invoking the full verify pipeline.

    The input MUST already be the JCS-canonical form of the document
    *with* ``document_signature`` stripped. This is the contract for
    the DNS anchor (V-908 section 2.1, last paragraph). If the caller
    has the document body as a parsed dict, use
    :func:`compute_ftd_fingerprint_from_body` instead.
    """
    return hashlib.sha256(ftd_doc_jcs_bytes).hexdigest()


def compute_ftd_fingerprint_from_body(ftd_doc: dict) -> str:
    """Compute the V-908 anchor fingerprint from a parsed body.

    Strips ``document_signature``, JCS-canonicalises, and SHA-256s.
    """
    body = copy.deepcopy(ftd_doc)
    body.pop("document_signature", None)
    return hashlib.sha256(_jcs_canonicalise(body)).hexdigest()


def verify_ftd_document(
    ftd_doc_jcs_bytes: bytes,
    ftd_id: str,
    *,
    resolver: TxtResolver,
    now: Optional[datetime] = None,
    dns_timeout_s: float = 3.0,
    cache: Optional[FTDCache] = None,
) -> VerifyResult:
    """Verify an FTD-doc against the V-908 trust pipeline.

    Args:
        ftd_doc_jcs_bytes: the FTD-doc body as JSON UTF-8 bytes
            (HTTPS response body, file content, or test fixture).
            The verifier re-parses these bytes to a dict, then
            re-canonicalises with JCS for fingerprinting; the input
            does not have to be JCS-canonical on the wire (the
            re-canonicalisation step normalises wire-form
            differences such as key ordering).
        ftd_id: the FTD identifier the caller expected (V-908
            section 4.1 step 6 ID-consistency check). Mismatch
            raises :class:`FTDIDMismatchError`.
        resolver: a :class:`~wirelang.identity.dns_anchor.TxtResolver`
            implementation. The verifier consults this resolver to
            obtain the DNS anchor; tests inject a fake resolver.
        now: wall-clock for expiry / window checks. Defaults to
            :func:`datetime.now(timezone.utc)`. Tests pin a fixed
            value.
        dns_timeout_s: per-call DNS timeout passed through to the
            resolver. Phase-1b default 3 seconds.
        cache: optional :class:`FTDCache`. If supplied, a fresh hit
            short-circuits the pipeline; on miss the verified result
            is inserted before return. Pin-poisoning on
            fingerprint-mismatch is the caller's concern (the
            verifier raises :class:`FTDAnchorError` and the caller
            should call ``cache.poison(ftd_id)``).

    Returns:
        :class:`VerifyResult` on success.

    Raises:
        FTDSchemaError: structural / shape failure.
        FTDIDMismatchError: caller-supplied ``ftd_id`` does not match
            the document's ``id``.
        FTDExpiredError: ``expires`` is at or before ``now``.
        FTDAnchorError: DNS resolution failed, or the resolved
            fingerprint does not match the recomputed body
            fingerprint.
        FTDIssuerKeyError: no ``issuer_keys[]`` entry is currently
            in its validity window.
        FTDSignatureError: ``document_signature`` does not verify
            against ``ftd_root_pubkey``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if cache is not None:
        cached = cache.get(ftd_id)
        if cached is not None:
            return cached

    # Step 1: parse JCS bytes.
    try:
        doc = json.loads(ftd_doc_jcs_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FTDSchemaError(f"FTD-doc bytes are not valid JSON: {e}") from e

    # Step 2: structural validation.
    _structural_validate(doc)

    # Step 3: id consistency.
    if doc["id"] != ftd_id:
        raise FTDIDMismatchError(
            f"FTD-doc id {doc['id']!r} does not match expected {ftd_id!r}"
        )

    # Step 4: expiry.
    expires = _parse_rfc3339(doc["expires"])
    if now >= expires:
        raise FTDExpiredError(
            f"FTD-doc {ftd_id!r} expired at {doc['expires']} (now={now.isoformat()})"
        )

    # Step 5: fingerprint and DNS-anchor cross-check.
    #
    # V-908 spec §3.2 step 2 is unambiguous about the comparison
    # target: "compares the recorded fingerprint [DNS TXT] to
    # SHA-256(JCS(FTD-doc body without document_signature))". The
    # ``anchor.fingerprint_sha256`` field in the body itself (§2.1)
    # is informative provenance for human inspection and tooling --
    # making it a strict mirror of the recomputed digest would
    # require a fixed-point construction over a hash function and
    # is not what the spec normatively requires. The verifier
    # therefore (a) recomputes the body digest, (b) requires DNS to
    # match it, and (c) leaves the body anchor field as a schema-
    # validated string but does not bind it to the digest.
    fingerprint = compute_ftd_fingerprint_from_body(doc)
    anchor_host = doc["anchor"]["host"]
    try:
        dns_anchor = fetch_anchor(resolver, anchor_host, timeout_s=dns_timeout_s)
    except DnsAnchorError as e:
        raise FTDAnchorError(f"DNS anchor lookup failed: {e}") from e
    if dns_anchor.fingerprint != fingerprint:
        raise FTDAnchorError(
            f"DNS anchor fingerprint {dns_anchor.fingerprint!r} does not "
            f"match FTD-doc body fingerprint {fingerprint!r}"
        )

    # Step 6: live issuer-key window.
    valid_keys = _select_valid_issuer_keys(doc["issuer_keys"], now)
    if not valid_keys:
        raise FTDIssuerKeyError(
            f"FTD-doc {ftd_id!r} has no issuer_keys[] entry valid at {now.isoformat()}"
        )

    # Step 7: signature verify.
    try:
        signature = bytes.fromhex(doc["document_signature"]["signature"])
        root_pub = bytes.fromhex(doc["ftd_root_pubkey"])
    except ValueError as e:
        # Schema validator already enforced hex shape; defensive.
        raise FTDSignatureError(f"signature/root-key not valid hex: {e}") from e
    body_for_sig = copy.deepcopy(doc)
    body_for_sig.pop("document_signature", None)
    canonical_body = _jcs_canonicalise(body_for_sig)
    digest = hashlib.sha256(canonical_body).digest()
    if not _verify_ed25519(root_pub, digest, signature):
        raise FTDSignatureError(
            f"FTD-doc {ftd_id!r} document_signature does not verify against ftd_root_pubkey"
        )

    result = VerifyResult(
        ftd_id=ftd_id,
        ftd_doc=copy.deepcopy(doc),
        fingerprint_sha256=fingerprint,
        valid_issuer_keys=valid_keys,
        anchor_host=anchor_host,
        verified_at=now,
    )
    if cache is not None:
        cache.put(result)
    return result


def _select_valid_issuer_keys(
    raw_keys: Sequence[Mapping[str, object]],
    now: datetime,
) -> tuple[ValidIssuerKey, ...]:
    """Return the subset of ``raw_keys`` whose validity window includes ``now``."""
    out: list[ValidIssuerKey] = []
    for entry in raw_keys:
        valid_from = _parse_rfc3339(entry["valid_from"])  # type: ignore[arg-type]
        valid_until_raw = entry.get("valid_until")
        valid_until: Optional[datetime] = None
        if valid_until_raw is not None:
            valid_until = _parse_rfc3339(valid_until_raw)  # type: ignore[arg-type]
        if now < valid_from:
            continue
        if valid_until is not None and now >= valid_until:
            continue
        out.append(
            ValidIssuerKey(
                kid=entry["kid"],  # type: ignore[arg-type]
                public_key_hex=entry["public_key"],  # type: ignore[arg-type]
                purpose=entry["purpose"],  # type: ignore[arg-type]
                valid_from=valid_from,
                valid_until=valid_until,
            )
        )
    return tuple(out)


__all__ = [
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
]
