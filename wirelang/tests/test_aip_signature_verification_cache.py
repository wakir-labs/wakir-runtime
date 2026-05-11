# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for ``wirelang.identity.aip_signature_verification_cache``.

Phase-2 Sprint-4 Tag-5. Tests cover the cache hit/miss accounting,
TTL-based invalidation (with an injectable monotonic clock for
determinism), LRU eviction, negative caching (cache stores both
True and False outcomes), cache-key construction (different inputs
produce different keys; identical inputs collide; pub_key bytes are
part of the key; signature_block fields are all part of the key),
end-to-end byte-equality with the underlying
:func:`wirelang.identity.verify_aip_signature`, and structural-failure
propagation (cache does NOT memoise ``ValueError``-raising calls).

All tests are hermetic: no real time, no I/O, no transport, no NATS.
The Ed25519 signing primitive runs in-process via the existing
``cryptography`` dependency.
"""

from __future__ import annotations

import copy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wirelang.identity import (
    AipSignatureVerificationCache,
    CacheStats,
    cached_verify_aip_signature,
    sign_aip_document,
    verify_aip_signature,
)
from wirelang.identity.aip_signature_verification_cache import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_SECONDS,
    _build_cache_key,
    _jcs_body_digest_hex,
)


# ---------------------------------------------------------------------------
# Deterministic clock
# ---------------------------------------------------------------------------


class _FakeClock:
    """Injectable monotonic-style clock for hermetic TTL tests.

    Default ``t=0.0``; tests advance via :meth:`tick` to walk the cache
    through the TTL window deterministically. No wall-clock dependency.
    """

    def __init__(self, t: float = 0.0) -> None:
        self._t = float(t)

    def __call__(self) -> float:
        return self._t

    def tick(self, seconds: float) -> None:
        self._t += float(seconds)


# ---------------------------------------------------------------------------
# Ed25519 test-vector keypair (RFC 8032 test 1)
# ---------------------------------------------------------------------------


_SEED_A: bytes = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
"""RFC 8032 test-vector 1 seed."""

_SEED_B: bytes = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
)
"""RFC 8032 test-vector 2 seed."""


def _keypair(seed: bytes) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import serialization

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
    }


def _signed_pair() -> tuple[dict, dict, bytes]:
    """Return ``(aip_doc, signature_block, pub_key)`` ready to verify."""
    priv, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    sig = sign_aip_document(doc, priv)
    # Attach the signature to the document so the verify path sees it
    # as a "real" AIP document (signature slot is stripped before JCS
    # canonicalisation by the verifier).
    full = dict(doc)
    full["document_signature"] = sig
    return full, sig, pub


# ===========================================================================
# T-AIP-SVC-01 — Construction and defaults
# ===========================================================================


def test_T_AIP_SVC_01_construction_defaults() -> None:
    """Default construction yields the documented defaults; bad args raise."""
    cache = AipSignatureVerificationCache()
    assert cache.max_entries == DEFAULT_MAX_ENTRIES == 256
    assert cache.ttl_seconds == DEFAULT_TTL_SECONDS == 300.0
    assert len(cache) == 0
    stats = cache.stats
    assert stats.hits == 0
    assert stats.misses == 0
    assert stats.evictions == 0
    assert stats.expired == 0
    assert stats.size == 0

    # Overrides honoured.
    cache2 = AipSignatureVerificationCache(max_entries=8, ttl_seconds=60.0)
    assert cache2.max_entries == 8
    assert cache2.ttl_seconds == 60.0

    # Bad-arg-grid.
    with pytest.raises(ValueError, match="max_entries must be > 0"):
        AipSignatureVerificationCache(max_entries=0)
    with pytest.raises(ValueError, match="max_entries must be > 0"):
        AipSignatureVerificationCache(max_entries=-3)
    with pytest.raises(ValueError, match="ttl_seconds must be > 0"):
        AipSignatureVerificationCache(ttl_seconds=0)
    with pytest.raises(ValueError, match="ttl_seconds must be > 0"):
        AipSignatureVerificationCache(ttl_seconds=-1.5)


# ===========================================================================
# T-AIP-SVC-02 — Cache hit on second verify; outcome byte-equal to fresh
# ===========================================================================


def test_T_AIP_SVC_02_hit_on_second_verify() -> None:
    """A repeat call returns the memoised outcome and increments hits."""
    doc, sig, pub = _signed_pair()
    clock = _FakeClock(t=1000.0)
    cache = AipSignatureVerificationCache(clock=clock)

    # First call: miss.
    out1 = cache.verify(doc, sig, pub)
    stats1 = cache.stats
    assert out1 is True
    assert stats1.misses == 1
    assert stats1.hits == 0
    assert stats1.size == 1

    # Second call (no time advance): hit.
    out2 = cache.verify(doc, sig, pub)
    stats2 = cache.stats
    assert out2 is True
    assert stats2.misses == 1  # unchanged
    assert stats2.hits == 1
    assert stats2.size == 1

    # And the cached outcome is byte-equal to a fresh verify call.
    fresh = verify_aip_signature(doc, sig, pub)
    assert out2 is fresh


# ===========================================================================
# T-AIP-SVC-03 — TTL-based invalidation
# ===========================================================================


def test_T_AIP_SVC_03_ttl_invalidation() -> None:
    """An entry past ``ttl_seconds`` is dropped on lookup; counters split."""
    doc, sig, pub = _signed_pair()
    clock = _FakeClock(t=0.0)
    cache = AipSignatureVerificationCache(ttl_seconds=10.0, clock=clock)

    cache.verify(doc, sig, pub)  # miss, inserts at t=0
    assert cache.stats.size == 1

    # Walk to just before TTL; still a hit.
    clock.tick(9.999)
    cache.verify(doc, sig, pub)
    s1 = cache.stats
    assert s1.hits == 1
    assert s1.expired == 0
    assert s1.size == 1

    # Step past TTL: a new lookup is a miss-via-expiry; expired counter
    # increments AND misses increments. hits does NOT increment.
    clock.tick(0.002)  # now 10.001 elapsed since insertion
    cache.verify(doc, sig, pub)
    s2 = cache.stats
    assert s2.hits == 1  # unchanged
    assert s2.misses == 2
    assert s2.expired == 1
    # Cache now has one entry (the freshly re-inserted one at
    # t=10.001), not two.
    assert s2.size == 1


# ===========================================================================
# T-AIP-SVC-04 — LRU eviction in insertion order
# ===========================================================================


def test_T_AIP_SVC_04_lru_eviction() -> None:
    """At-capacity insert evicts oldest by insertion order, not recency."""
    # Three distinct (doc, sig, pub) triples to force three keys.
    triples = []
    for seed_hex in (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
    ):
        priv, pub = _keypair(bytes.fromhex(seed_hex))
        doc = _aip_doc(pub, persona_id=f"agent-{seed_hex[:6]}")
        sig = sign_aip_document(doc, priv)
        full = dict(doc)
        full["document_signature"] = sig
        triples.append((full, sig, pub))

    cache = AipSignatureVerificationCache(max_entries=2)

    # Insert two distinct keys; size hits 2, no evictions yet.
    cache.verify(*triples[0])
    cache.verify(*triples[1])
    assert cache.stats.size == 2
    assert cache.stats.evictions == 0

    # A HIT on triples[0] does NOT promote it: insertion-order LRU.
    cache.verify(*triples[0])
    assert cache.stats.hits == 1
    assert cache.stats.size == 2

    # Insert a third key: oldest (triples[0]) is evicted.
    cache.verify(*triples[2])
    assert cache.stats.size == 2
    assert cache.stats.evictions == 1

    # Re-verify triples[0]: it MUST be a miss (it was evicted, not
    # promoted).
    cache.verify(*triples[0])
    assert cache.stats.evictions == 2  # triples[1] now evicted in turn
    # triples[1] re-verify: also a miss (it was evicted just now).
    cache.verify(*triples[1])
    assert cache.stats.evictions == 3


# ===========================================================================
# T-AIP-SVC-05 — Negative caching: False outcomes are memoised
# ===========================================================================


def test_T_AIP_SVC_05_negative_caching() -> None:
    """A False verify outcome is cached identically to a True outcome."""
    priv_a, pub_a = _keypair(_SEED_A)
    priv_b, pub_b = _keypair(_SEED_B)

    doc = _aip_doc(pub_a)
    # Sign with priv_a but verify against pub_b: outcome is False.
    sig = sign_aip_document(doc, priv_a)
    full = dict(doc)
    full["document_signature"] = sig

    clock = _FakeClock()
    cache = AipSignatureVerificationCache(clock=clock)

    # First call: miss, outcome False (wrong public key).
    out1 = cache.verify(full, sig, pub_b)
    assert out1 is False
    assert cache.stats.misses == 1

    # Second call: hit, still False, no re-verify cost.
    out2 = cache.verify(full, sig, pub_b)
    assert out2 is False
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1  # unchanged

    # And the cached negative outcome is byte-equal to a fresh verify.
    assert out2 is verify_aip_signature(full, sig, pub_b)


# ===========================================================================
# T-AIP-SVC-06 — Cache-key construction: distinct inputs distinct keys
# ===========================================================================


def test_T_AIP_SVC_06_cache_key_distinct_inputs() -> None:
    """All five components of the cache key alter the resulting hash."""
    priv_a, pub_a = _keypair(_SEED_A)
    priv_b, pub_b = _keypair(_SEED_B)

    doc1 = _aip_doc(pub_a)
    doc2 = _aip_doc(pub_a, persona_id="other-agent")  # different body
    sig1 = sign_aip_document(doc1, priv_a)
    sig2 = sign_aip_document(doc1, priv_b)  # different signature value

    # Baseline key.
    k0 = _build_cache_key(doc1, sig1, pub_a)

    # (1) Different body → different key.
    k_body = _build_cache_key(doc2, sig1, pub_a)
    assert k_body != k0

    # (2) Different alg → different key. (Hand-build a non-Ed25519 alg
    # for the cache-key probe; the underlying verifier would reject
    # it, but the cache-key fn does NOT call the verifier.)
    sig_alt_alg = dict(sig1)
    sig_alt_alg["alg"] = "Ed448"
    k_alg = _build_cache_key(doc1, sig_alt_alg, pub_a)
    assert k_alg != k0

    # (3) Different kid → different key.
    sig_alt_kid = dict(sig1)
    sig_alt_kid["kid"] = "biscuit-root-2"
    k_kid = _build_cache_key(doc1, sig_alt_kid, pub_a)
    assert k_kid != k0

    # (4) Different signature hex → different key.
    k_sig = _build_cache_key(doc1, sig2, pub_a)
    assert k_sig != k0

    # (5) Different pub_key bytes → different key.
    k_pub = _build_cache_key(doc1, sig1, pub_b)
    assert k_pub != k0

    # And reflexivity: the same inputs produce the same key (this is
    # the whole point — without this the cache cannot hit).
    k0_again = _build_cache_key(doc1, sig1, pub_a)
    assert k0_again == k0


# ===========================================================================
# T-AIP-SVC-07 — Cache-key construction: malformed signature_block
# ===========================================================================


def test_T_AIP_SVC_07_cache_key_missing_fields() -> None:
    """Missing fields in signature_block raise KeyError from the key fn."""
    _, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    sig = {"alg": "Ed25519", "kid": "k", "signature": "00" * 64}

    # All three fields are required.
    for missing in ("alg", "kid", "signature"):
        broken = dict(sig)
        broken.pop(missing)
        with pytest.raises(KeyError, match=f"missing {missing}"):
            _build_cache_key(doc, broken, pub)


# ===========================================================================
# T-AIP-SVC-08 — Structural failures are NOT cached
# ===========================================================================


def test_T_AIP_SVC_08_structural_failure_not_cached() -> None:
    """A ValueError from the underlying verifier bubbles; no entry stored.

    The cache contract: structural failures (malformed signature
    block, wrong algorithm, wrong key length) propagate verbatim and
    do NOT produce a cache entry. The next call repeats the same
    failure (deterministic), but the cache size and miss counter
    reflect the fact that no entry was memoised.
    """
    priv, pub = _keypair(_SEED_A)
    doc = _aip_doc(pub)
    bad_sig = {
        "alg": "Ed448",  # wrong algorithm → ValueError from verify
        "kid": "biscuit-root-1",
        "signature": "00" * 64,
    }

    cache = AipSignatureVerificationCache()

    # First attempt raises.
    with pytest.raises(ValueError):
        cache.verify(doc, bad_sig, pub)
    assert cache.stats.size == 0
    assert cache.stats.misses == 0
    assert cache.stats.hits == 0

    # Second attempt also raises — no memoisation of structural
    # failure happened.
    with pytest.raises(ValueError):
        cache.verify(doc, bad_sig, pub)
    assert cache.stats.size == 0
    assert cache.stats.misses == 0
    assert cache.stats.hits == 0


# ===========================================================================
# T-AIP-SVC-09 — evict_expired() bulk sweep
# ===========================================================================


def test_T_AIP_SVC_09_evict_expired_sweep() -> None:
    """``evict_expired()`` drops all entries beyond the TTL window."""
    triples = []
    for seed_hex in (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
    ):
        priv, pub = _keypair(bytes.fromhex(seed_hex))
        doc = _aip_doc(pub, persona_id=f"agent-{seed_hex[:6]}")
        sig = sign_aip_document(doc, priv)
        full = dict(doc)
        full["document_signature"] = sig
        triples.append((full, sig, pub))

    clock = _FakeClock(t=0.0)
    cache = AipSignatureVerificationCache(ttl_seconds=10.0, clock=clock)

    # Insert two entries at t=0.
    cache.verify(*triples[0])
    cache.verify(*triples[1])
    assert cache.stats.size == 2

    # Within TTL: sweep is a no-op.
    clock.tick(9.0)
    removed = cache.evict_expired()
    assert removed == 0
    assert cache.stats.size == 2
    assert cache.stats.expired == 0

    # Past TTL: sweep removes both. The expired counter rises by 2.
    clock.tick(1.5)  # t=10.5 > 10.0
    removed = cache.evict_expired()
    assert removed == 2
    assert cache.stats.size == 0
    assert cache.stats.expired == 2


# ===========================================================================
# T-AIP-SVC-10 — Document-signature slot is stripped before key digest
# ===========================================================================


def test_T_AIP_SVC_10_document_signature_stripped() -> None:
    """``document_signature`` mutation on the doc does NOT change the key.

    The cache key uses ``SHA-256(JCS(body without document_signature))``
    (the same byte-anchor the Sprint-4 Tag-4 transport-fetch layer
    publishes). Re-publishing the document with a *different*
    ``document_signature`` slot but byte-equal everything else MUST
    produce the same cache key (the verify outcome is bound to the
    body, not to whatever signature was attached to the body at fetch
    time).

    This is the cache-key correctness probe for the Tag-5 ↔ Tag-4
    byte-identity claim.
    """
    priv, pub = _keypair(_SEED_A)
    doc1 = _aip_doc(pub)
    doc1["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "aa" * 64,
    }
    doc2 = copy.deepcopy(doc1)
    doc2["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "bb" * 64,  # different attached-signature
    }
    # Same independent verify-signature-block (not the same as
    # ``document_signature``; the verify-sig is what the cache caller
    # passes; the doc's attached document_signature is just metadata
    # stripped before JCS).
    sig = sign_aip_document(doc1, priv)

    k1 = _build_cache_key(doc1, sig, pub)
    k2 = _build_cache_key(doc2, sig, pub)
    assert k1 == k2

    # And the digest helper itself is also byte-equal.
    d1 = _jcs_body_digest_hex(doc1)
    d2 = _jcs_body_digest_hex(doc2)
    assert d1 == d2


# ===========================================================================
# T-AIP-SVC-11 — clear() drops entries; counters survive
# ===========================================================================


def test_T_AIP_SVC_11_clear_preserves_counters() -> None:
    """``clear()`` empties the cache without resetting lifetime counters."""
    doc, sig, pub = _signed_pair()
    clock = _FakeClock()
    cache = AipSignatureVerificationCache(clock=clock)

    cache.verify(doc, sig, pub)  # miss
    cache.verify(doc, sig, pub)  # hit
    assert cache.stats.misses == 1
    assert cache.stats.hits == 1
    assert cache.stats.size == 1

    cache.clear()
    s = cache.stats
    # Size drops but lifetime counters survive.
    assert s.size == 0
    assert s.misses == 1
    assert s.hits == 1

    # After clear, the same inputs are a miss again (the cache is empty).
    cache.verify(doc, sig, pub)
    s2 = cache.stats
    assert s2.misses == 2  # one more miss
    assert s2.hits == 1  # unchanged
    assert s2.size == 1


# ===========================================================================
# T-AIP-SVC-12 — cached_verify_aip_signature() free function
# ===========================================================================


def test_T_AIP_SVC_12_free_function_routes_through_cache() -> None:
    """The free-function wrapper routes through the supplied cache.

    Two identical calls via ``cached_verify_aip_signature(cache=...)``
    produce a miss followed by a hit on the same cache; the function
    is byte-equivalent to ``cache.verify(...)``.
    """
    doc, sig, pub = _signed_pair()
    clock = _FakeClock()
    cache = AipSignatureVerificationCache(clock=clock)

    out1 = cached_verify_aip_signature(doc, sig, pub, cache=cache)
    out2 = cached_verify_aip_signature(doc, sig, pub, cache=cache)
    assert out1 is True
    assert out2 is True
    # First call miss, second call hit.
    assert cache.stats.misses == 1
    assert cache.stats.hits == 1

    # Free-function outcome is byte-equal to the method-form outcome.
    out3 = cache.verify(doc, sig, pub)
    assert out3 is True
    assert cache.stats.hits == 2

    # And byte-equal to a fresh, uncached verify.
    assert verify_aip_signature(doc, sig, pub) is True

    # Cache-Stats snapshot is a defensive copy — mutating it does NOT
    # mutate the live cache.
    snap: CacheStats = cache.stats
    snap.hits = 999
    snap.misses = 999
    assert cache.stats.hits == 2  # unchanged
    assert cache.stats.misses == 1  # unchanged
