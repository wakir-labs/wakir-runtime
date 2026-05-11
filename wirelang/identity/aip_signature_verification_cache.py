# SPDX-License-Identifier: Apache-2.0
"""Phase-2 Sprint-4 Tag-5 AIP-document signature-verification cache tier.

This module ships a stateful caching tier on top of the Sprint-4 Tag-1
AIP-document signing primitive (:func:`wirelang.identity.verify_aip_signature`).
The Tag-1 verifier is pure and stateless; production verifier paths
that re-validate the same ``(document, signature, public_key)`` triple
multiple times pay the JCS-canonicalisation + SHA-256 + Ed25519
signature cost on every call. The Sprint-4 Tag-5 cache tier short-
circuits that cost while preserving byte-equal outcomes (a cache hit
is indistinguishable from a fresh verify).

Phase-2 Sprint-4 Tag-5 boundary
-------------------------------

This module deliberately does NOT:

* Replace :func:`wirelang.identity.verify_aip_signature`. The cache is
  a *thin composition layer*; the underlying verifier remains the
  single source of truth for cryptographic correctness. On cache
  miss the cache calls the verifier verbatim and records the result.
* Cache transport-fetch outputs. :class:`AipFetchResult` byte-anchors
  (``jcs_sha256_hex``) are produced by the Sprint-4 Tag-4
  ``aip_document_transport_fetch`` layer; the V-908
  ``HTTPSAipResolverCache`` lives one layer up for the federation
  pipeline and caches *documents*, not signature-verify outcomes.
* Persist across process boundaries. The cache is an in-process,
  bounded LRU with TTL-based invalidation. Distributed-cache
  contracts (Redis / NATS-KV / etc.) are Phase-3 slots.
* Mutate :func:`wirelang.identity.sign_aip_document` or the underlying
  AIP-document signing primitive in any way. Tag-5 is read-side only.

Cache-key construction
----------------------

The cache key is constructed from the byte-deterministic inputs to a
:func:`verify_aip_signature` call:

1. ``jcs_sha256_hex`` of the AIP-document body (with the
   ``document_signature`` slot removed before JCS-canonicalisation —
   identical to the Sprint-4 Tag-4 ``_jcs_anchor_hex`` recomputation).
2. The signature ``alg`` (currently ``"Ed25519"``; future-proof
   for additional curves).
3. The signature ``kid`` string (binds the key-identifier into the
   key; a key-rotation that re-uses the same ``signature`` value but
   under a new ``kid`` is a different cache entry).
4. The signature ``signature`` hex (128-char lower-case for
   Ed25519).
5. The verifier's ``pub_key`` bytes (the 32-byte raw Ed25519 public
   key, in hex). The cache binds the verify outcome to the *exact*
   public-key bytes the caller supplied; a different public-key
   value (even for the "same" ``kid``) is a different cache entry.

The 5-tuple is hashed via SHA-256 into a fixed-length cache key. The
SHA-256 indirection keeps the cache-key memory cost bounded
regardless of the AIP-document size (the document is hashed via JCS
upstream of the cache; the cache only sees the digest).

Negative caching
----------------

Both ``True`` and ``False`` verify outcomes are cached. A bad
signature (verify returns ``False``) is just as memoisable as a good
signature — the cryptographic primitive is deterministic on
``(payload, key, signature)`` regardless of outcome. This is
important for production fleets that see retries against
known-bad inputs (e.g. expired key rotations); caching the negative
outcome prevents N-times re-verification of the same bad input.

Structural failures (the verifier raises ``ValueError`` on a malformed
signature block, wrong algorithm, or wrong key length) are NOT
cached. The cache propagates the exception verbatim and does not
record the failed call. This keeps the cache contract clean:
"cache stores Boolean verify outcomes; structural failures bubble
through unchanged".

TTL semantics
-------------

Each cache entry has a monotonic-clock insertion timestamp. The
default TTL is 300 seconds (5 minutes); callers can override on
construction. The TTL bounds staleness for two production scenarios:

1. **Key rotation**: an AIP document's ``public_keys`` entry has a
   ``validuntil`` window. A cached verify outcome (positive or
   negative) past that window may no longer reflect current trust
   policy; the TTL forces re-verification with the latest
   document-state at most every ``ttl_seconds`` seconds.
2. **Document mutation**: an AIP document may be re-published with a
   new ``document_signature`` slot at the same identifier. The cache
   key includes ``jcs_sha256_hex`` so a re-publication is a different
   cache key; the TTL is a defence-in-depth bound for the unlikely
   case where the same JCS-anchor reappears with mutated semantics.

The clock is injectable for deterministic test contracts. Production
callers use ``time.monotonic``; tests inject a controllable callable.

LRU eviction
------------

The cache is bounded by ``max_entries`` (default 256). On insertion
into a full cache, the least-recently-inserted entry is evicted. The
order is insertion-order — a cache *hit* does NOT promote the entry
in the LRU order (this matches the V-908 ``HTTPSAipResolverCache``
semantics for byte-consistency across the Identity-Substrate cache
tiers). If callers want hit-promotion semantics they should
construct a separate cache tier; the Tag-5 default keeps the
contract minimal.

Cross-Review-Zone-1 (Identity-Substrate) — non-touched
------------------------------------------------------

The Sprint-4 Tag-5 cache tier touches NONE of the four
Z-1-K-Sprint-4 consensus points:

* Z-1-K-Sprint-4-1 (kid-Resolver-Shape) — non-touched; the cache
  composes ``verify_aip_signature`` directly with an explicit
  ``pub_key`` argument supplied by the caller. The kid-resolver
  (§5.9) feeds the public key to the caller, who then composes the
  cache; the cache does not import ``kid_resolver`` or invoke it.
* Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) — non-touched; the cache
  re-uses the ``aip_signing._jcs_canonicalize`` resolver-indirection
  byte-identical (the cache-key construction re-uses the Tag-4
  ``_jcs_anchor_hex`` helper to compute the body digest, which in
  turn delegates to ``aip_signing._jcs_canonicalize``).
* Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) — non-touched; the cache
  is curve-agnostic by construction (the ``alg`` field is included
  in the cache key but the cache does not enforce a curve choice).
* Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) — non-touched;
  the cache does NOT make a policy decision. It memoises the
  Boolean outcome of the verifier; the caller's STRICT-mode policy
  (Sprint-4 Tag-1 ``VerifyMode.STRICT``) is upstream and unchanged.

See ``wirelang/specs/schema-registry-spec.md`` §5.11 for the
operational contract and §6.8 for the test inventory.
"""

from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .aip_signing import _jcs_canonicalize, verify_aip_signature


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


#: Default LRU bound. Sized for an order of ~64 active personas with
#: ~4 distinct kid/signature pairs each (Phase-2 production fleet
#: rough upper bound). 256 entries at ~96 bytes per entry (digest +
#: timestamp + bool overhead) is ~25 KB — well below memory-pressure
#: thresholds for any realistic deployment.
DEFAULT_MAX_ENTRIES: int = 256

#: Default TTL window in seconds. 5 minutes balances key-rotation
#: responsiveness against re-verify cost; production callers can
#: override on construction.
DEFAULT_TTL_SECONDS: float = 300.0


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CacheEntry:
    """A single cache entry: outcome plus insertion timestamp."""

    outcome: bool
    inserted_at: float


@dataclass
class CacheStats:
    """Counters describing cache behaviour over its lifetime.

    Attributes:
        hits: number of cache lookups that returned a memoised outcome.
        misses: number of cache lookups that fell through to a fresh
            ``verify_aip_signature`` call.
        evictions: number of entries removed by LRU pressure (full
            cache, oldest entry kicked).
        expired: number of entries removed due to TTL expiry on a
            lookup (an expired entry counts as a miss AND increments
            ``expired``; the two counters are independent dimensions).
        size: current number of entries in the cache. Updated live;
            not historical.
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expired: int = 0
    size: int = 0


# ---------------------------------------------------------------------------
# Cache-key construction
# ---------------------------------------------------------------------------


def _jcs_body_digest_hex(aip_doc: dict) -> str:
    """Compute SHA-256(JCS(body without document_signature)) hex.

    Byte-identical to :func:`wirelang.identity.aip_document_transport_fetch._jcs_anchor_hex`
    in shape and output; reimplemented locally to avoid an
    import-time dependency between the two modules (the Tag-4 module
    is the transport-fetch layer; the Tag-5 module is the verify
    cache; they are siblings, not a stack).

    The ``document_signature`` slot is removed from a deep copy so
    the caller's body is not mutated. The JCS canonicaliser is the
    resolver-indirected one shared with ``aip_signing``
    (``rfc8785`` when present, ``_jcs_pure`` fallback otherwise).
    """
    body = copy.deepcopy(aip_doc)
    body.pop("document_signature", None)
    canonical = _jcs_canonicalize(body)
    return hashlib.sha256(canonical).hexdigest()


def _build_cache_key(
    aip_doc: dict,
    signature_block: dict,
    pub_key: bytes,
) -> str:
    """Construct the SHA-256 cache key for a verify call.

    The 5-tuple
    ``(body_jcs_sha256_hex, alg, kid, signature_hex, pub_key_hex)``
    is serialised into a single byte string with explicit ``\\x00``
    separators (no JSON, no canonicalisation cost — the inputs are
    already canonicalised individually) and hashed via SHA-256 into
    a fixed-length 64-hex-char cache key.

    Raises:
        KeyError: signature_block is missing ``alg``, ``kid`` or
            ``signature``. The caller's
            :func:`verify_aip_signature` will also raise
            ``ValueError`` on the same input; this guard is
            defence-in-depth so the cache itself produces a clean
            error rather than an opaque hash collision.
    """
    if "alg" not in signature_block:
        raise KeyError("signature_block missing alg")
    if "kid" not in signature_block:
        raise KeyError("signature_block missing kid")
    if "signature" not in signature_block:
        raise KeyError("signature_block missing signature")

    body_digest = _jcs_body_digest_hex(aip_doc)
    alg = signature_block["alg"]
    kid = signature_block["kid"]
    sig_hex = signature_block["signature"]
    pub_hex = pub_key.hex()

    payload = b"\x00".join(
        [
            body_digest.encode("ascii"),
            alg.encode("utf-8"),
            kid.encode("utf-8"),
            sig_hex.encode("ascii"),
            pub_hex.encode("ascii"),
        ]
    )
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class AipSignatureVerificationCache:
    """Bounded LRU cache with TTL-based invalidation for AIP-doc verifies.

    Construction is hermetic-clean: the ``clock`` parameter accepts a
    callable returning a monotonic float (defaulting to
    ``time.monotonic``); tests inject a controllable clock so TTL
    semantics are deterministic.

    Cache semantics:

    * **Hits return the memoised Boolean unchanged.** A hit does not
      re-invoke :func:`verify_aip_signature`. The contract is
      "cache hit is byte-equal to a fresh verify" — production
      callers can rely on hit/miss being a pure performance
      optimisation, not a behavioural difference.
    * **TTL expiry on lookup**: when a hit is found but
      ``now - entry.inserted_at >= ttl_seconds``, the entry is
      removed and the lookup falls through to a fresh verify. The
      ``expired`` counter is incremented; the ``hits`` counter is
      NOT.
    * **LRU eviction on insertion**: if the cache is at
      ``max_entries`` capacity, the oldest entry (by insertion
      order) is removed. A cache *hit* does NOT promote the entry;
      LRU is by insertion-order, identical to the V-908
      ``HTTPSAipResolverCache`` semantics.
    * **Negative caching**: a ``False`` verify outcome is cached
      the same way as ``True``. Production fleets that see retries
      against known-bad inputs (expired key rotations, replayed
      malicious signatures, etc.) benefit from the negative cache.
    * **Structural failures are NOT cached**: when
      :func:`verify_aip_signature` raises ``ValueError`` (malformed
      signature block, wrong algorithm, wrong key length), the
      exception propagates verbatim and no cache entry is written.

    Attributes are private; the public surface is the methods below
    plus :attr:`stats` (read-only view of the counters).
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError(
                f"max_entries must be > 0; got {max_entries}"
            )
        if ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be > 0; got {ttl_seconds}"
            )
        self._max_entries = int(max_entries)
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: dict[str, _CacheEntry] = {}
        self._order: list[str] = []
        self._stats = CacheStats()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stats(self) -> CacheStats:
        """Return a snapshot of the cache counters (defensive copy).

        The returned :class:`CacheStats` is a fresh dataclass; mutating
        it does NOT affect the live cache counters. ``size`` is the
        live entry count at call time.
        """
        return CacheStats(
            hits=self._stats.hits,
            misses=self._stats.misses,
            evictions=self._stats.evictions,
            expired=self._stats.expired,
            size=len(self._entries),
        )

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        aip_doc: dict,
        signature_block: dict,
        pub_key: bytes,
    ) -> bool:
        """Verify with caching.

        Args:
            aip_doc: the AIP-document body. ``document_signature``
                slot is stripped before JCS canonicalisation (the
                caller's body is not mutated).
            signature_block: the signature dict ``{alg, kid,
                signature}`` to validate.
            pub_key: the 32-byte raw Ed25519 public key (the caller
                normally obtains this via the kid-resolver, §5.9).

        Returns:
            ``True`` iff the signature is cryptographically valid.

        Raises:
            ValueError: when the underlying
                :func:`verify_aip_signature` raises a structural
                error (malformed signature block, wrong algorithm,
                wrong key length). Structural failures are NOT
                cached.
            KeyError: when the cache-key construction cannot find
                ``alg`` / ``kid`` / ``signature`` on the
                ``signature_block``. The underlying verifier would
                also raise ``ValueError`` here; the cache surfaces a
                ``KeyError`` from its own key-construction layer to
                distinguish the two failure modes for callers.
        """
        key = _build_cache_key(aip_doc, signature_block, pub_key)
        now = self._clock()

        # Lookup path.
        entry = self._entries.get(key)
        if entry is not None:
            age = now - entry.inserted_at
            if age < self._ttl_seconds:
                self._stats.hits += 1
                return entry.outcome
            # Expired: drop and fall through to miss.
            self._remove(key)
            self._stats.expired += 1

        # Miss path: call the verifier, then memoise.
        outcome = verify_aip_signature(aip_doc, signature_block, pub_key)
        self._stats.misses += 1
        self._insert(key, _CacheEntry(outcome=outcome, inserted_at=now))
        return outcome

    def clear(self) -> None:
        """Drop all cached entries.

        Resets the cache contents but NOT the lifetime counters
        (``hits`` / ``misses`` / ``evictions`` / ``expired`` are
        cumulative across the lifetime of the cache instance and
        survive :meth:`clear`; the ``size`` field on
        :attr:`stats` is live and naturally drops to zero).
        """
        self._entries.clear()
        self._order.clear()

    def evict_expired(self) -> int:
        """Remove all entries whose TTL has elapsed at the current clock.

        This is an out-of-band hygiene pass; the lookup path also
        evicts expired entries on hit. Useful for production
        callers that want a periodic sweep (e.g. on a timer) to
        keep the live size bounded by the freshness window rather
        than the LRU bound.

        Returns:
            Count of entries removed.
        """
        now = self._clock()
        threshold = now - self._ttl_seconds
        # Walk a snapshot of order; mutate through _remove which
        # rewrites both maps.
        to_remove = [
            key
            for key in list(self._order)
            if (entry := self._entries.get(key)) is not None
            and entry.inserted_at <= threshold
        ]
        for key in to_remove:
            self._remove(key)
            self._stats.expired += 1
        return len(to_remove)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _insert(self, key: str, entry: _CacheEntry) -> None:
        """Insert ``entry`` at ``key``, evicting the oldest if at capacity.

        ``key`` is expected to be absent from the cache when this is
        called; the verify path does a get-first then insert-on-miss,
        so the at-capacity logic always reflects a new entry going
        in.
        """
        if len(self._entries) >= self._max_entries:
            oldest = self._order.pop(0)
            self._entries.pop(oldest, None)
            self._stats.evictions += 1
        self._entries[key] = entry
        self._order.append(key)

    def _remove(self, key: str) -> None:
        self._entries.pop(key, None)
        try:
            self._order.remove(key)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Convenience: bound a one-off verify to a caller-supplied cache
# ---------------------------------------------------------------------------


def cached_verify_aip_signature(
    aip_doc: dict,
    signature_block: dict,
    pub_key: bytes,
    *,
    cache: AipSignatureVerificationCache,
) -> bool:
    """Convenience wrapper: route a single verify through a cache.

    Equivalent to ``cache.verify(...)``. Provided as a free function
    so callers that want to keep the cache object out of their
    type-signatures (e.g. helper utilities that take a *function*
    parameter) can hand around this wrapper instead. The cache
    parameter is keyword-only to keep the call shape symmetric with
    :func:`wirelang.identity.verify_aip_signature`.
    """
    return cache.verify(aip_doc, signature_block, pub_key)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "AipSignatureVerificationCache",
    "CacheStats",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_SECONDS",
    "cached_verify_aip_signature",
]
