# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Federation-Resolver canonical-snapshot helpers (Tag-24 Mini-Welle).

This module is the **Python authority** for the
``FederationResolver`` Protocol surface and the
``InMemoryFederationResolver`` reference implementation. A Rust
sibling crate (``wirelang-rust/crates/persona-engine-federation-
resolver``) implements the same surface byte-for-byte; the two
sides are pinned by the cross-lang fixture file
``tests/fixtures/federation-resolver-cross-lang/fixtures.json``.

Phase-3a Item 9 (federation-frame parser) shipped a typed frame
parser without an associated **higher-layer resolver** that maps
the wire-shape org / cluster identifiers to operator-org public
keys. This module supplies that resolver. The Federation-Frame-
Parser (Rust PR #148, Python PR #157) consumes one
``FederationFrame.header.source_runtime`` string per frame; the
resolver's job is to take an ``org_id`` (and the matching
``cluster_id``) and return the operator-org's Ed25519 public key
that signs frames coming from that org/cluster pair, accounting
for key-rotation history and overlapping validity windows.

Why a sibling module?
---------------------

The Phase-1b ``federation_resolver.py`` module is the V-908
AIP-doc resolver: cross-org AIP-document fetch with FTD
cross-check. The Tag-24 surface is **orthogonal**: a low-level
org-id -> cluster-id -> operator-org-public-key registry, used
downstream by frame-signature verifiers, the WAT-anchor pipeline
(per-frame operator attestation), and the Phase-2 ``peer_org``
predicate evaluator.

Keeping the helpers in a separate Apache-2.0 module preserves the
Tag-21 / Tag-23 sibling-pattern Reza established for
``lifecycle_state_machine_canonical`` and the persona-engine
``state_backing`` parity surface. The pre-existing
``federation_resolver.py`` (V-908 AIP-doc resolver) is **NOT**
touched by this module.

Schema
------

The canonical snapshot carries exactly two top-level fields
(alphabetical):

- ``entries`` -- Ordered list of :class:`OperatorOrgKeyEntry`
  projections. Each entry is a six-key object (alphabetical):

    - ``alg`` (string; constant ``"Ed25519"`` for Phase-3a)
    - ``cluster_id`` (string)
    - ``org_id`` (string)
    - ``public_key_hex`` (string; 64-char lower-case hex)
    - ``valid_from`` (RFC-3339 second-precision UTC string)
    - ``valid_until`` (RFC-3339 second-precision UTC string)

  Entries are sorted lexicographically by
  ``(org_id, cluster_id, valid_from)`` so the snapshot byte-form
  is independent of insertion order.

- ``schema`` -- Schema identifier; constant
  ``"wakir.federation.resolver-snapshot/1"``.

Serialisation
-------------

The canonical bytes are produced by ``json.dumps`` with
``sort_keys=True``, ``separators=(",", ":")``,
``ensure_ascii=False``, UTF-8-encoded. The outer snapshot hash is
``"sha256:" + hex(SHA-256(canonical_bytes))``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/federation-resolver-cross-lang/fixtures.json``
is the byte-level cross-lang pin. Both
``tests/identity/test_federation_resolver_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-federation-resolver/tests/
federation_resolver_cross_lang_fixture_test.rs`` (Rust) consume
the same vectors. Any drift on either side fails both suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python                                          <-> Rust
    -------------------------------------------------------------------------
    FederationResolver (Protocol)                   <-> FederationResolver (trait)
    InMemoryFederationResolver                      <-> InMemoryFederationResolver
    OperatorOrgKeyEntry (dataclass)                 <-> OperatorOrgKeyEntry (struct)
    FederationResolverSnapshot (dataclass)          <-> FederationResolverSnapshot (struct)
    serialize_resolver_snapshot(snap) -> bytes      <-> serialize_resolver_snapshot
    resolver_snapshot_sha256_hex(snap) -> str       <-> resolver_snapshot_sha256_hex
    resolver_snapshot_hash_prefixed(snap) -> str    <-> resolver_snapshot_hash_prefixed
    FEDERATION_RESOLVER_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN / DEFAULT_ALG                  <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item 9 (federation-frame
  parser; this module's downstream consumer).
- Reza PR #148 (Sprint-Federation-Frame-Parser-Rust) -- Rust
  ``persona-engine-federation-frame-parser`` crate (frame parser
  authority).
- Reza PR #157 (Sprint-Federation-Frame-Python-Sync) -- Python
  ``wirelang/federation/federation_frame.py`` sibling.
- Reza PR #176 (Tag-20)   -- recovery-workflow canonical
  projection reference (multi-record snapshot shape).
- Reza PR #177 (Tag-21)   -- lifecycle-FSM canonical-trace
  reference (sibling-module + cross-lang fixture pattern).
- Reza PR #183 (Tag-23)   -- state-backing cross-lang parity
  reference (InMemory* + 5-fixture file pattern).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple, runtime_checkable


#: Schema identifier emitted on every federation-resolver canonical
#: snapshot. The version suffix ``/1`` is bumped only when a wire-
#: shape change is intentional. Both Python and Rust pin this exact
#: byte string.
FEDERATION_RESOLVER_SCHEMA = "wakir.federation.resolver-snapshot/1"

#: Prefix used by the prefixed-form snapshot hash.
HASH_PREFIX = "sha256:"

#: Length of a bare-hex SHA-256 digest (no prefix).
SHA256_HEX_LEN = 64

#: Length of a bare-hex Ed25519 public key (32 bytes -> 64 hex chars).
PUBLIC_KEY_HEX_LEN = 64

#: Default algorithm. Phase-3a frame signing is Ed25519-only; the
#: ``alg`` field is carried explicitly on every entry to keep the
#: wire-shape extensible without re-versioning the schema.
DEFAULT_ALG = "Ed25519"


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------


class FederationResolverError(ValueError):
    """Raised when caller-supplied input fails Tag-24 shape pre-
    conditions (malformed entries, duplicate (org, cluster, valid_from)
    triples, unknown algorithm, etc.).
    """


# ---------------------------------------------------------------------
# Dataclass surface
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class OperatorOrgKeyEntry:
    """One operator-org public key registration.

    Field order matches the JCS-canonical key order (alphabetical).
    All six fields are required.

    Attributes:
        alg: Algorithm wire-string. Phase-3a accepts ``"Ed25519"``.
        cluster_id: Cluster identifier within the operator-org.
            Wire-string; e.g. ``"primary"``, ``"backup-eu"``.
        org_id: Operator-org identifier. Wire-string.
        public_key_hex: 64-char lower-case hex of the Ed25519 public
            key (32 bytes). Validated for length + lower-case-hex on
            registration via :meth:`InMemoryFederationResolver.register`.
        valid_from: RFC-3339 second-precision UTC start of the
            key-validity window (inclusive).
        valid_until: RFC-3339 second-precision UTC end of the
            key-validity window (exclusive). MUST be lexically greater
            than ``valid_from``.
    """

    alg: str
    cluster_id: str
    org_id: str
    public_key_hex: str
    valid_from: str
    valid_until: str


@dataclass(frozen=True)
class FederationResolverSnapshot:
    """JCS-canonical wire-shape of a resolver's full entry set.

    Two top-level fields (alphabetical): ``entries`` (sorted) and
    ``schema``. The snapshot is the cross-lang-pinned byte form;
    drift on either Python or Rust side breaks both fixture-test
    suites.
    """

    entries: List[OperatorOrgKeyEntry] = field(default_factory=list)
    schema: str = FEDERATION_RESOLVER_SCHEMA


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------


def _is_lower_hex(s: str, expected_len: int) -> bool:
    """Return True iff ``s`` is exactly ``expected_len`` lower-case
    hex characters."""
    if len(s) != expected_len:
        return False
    for ch in s:
        if not (("0" <= ch <= "9") or ("a" <= ch <= "f")):
            return False
    return True


def _validate_entry(entry: OperatorOrgKeyEntry) -> None:
    """Raise :class:`FederationResolverError` if ``entry`` violates
    Tag-24 shape pre-conditions.

    Checks:

    - ``alg`` is non-empty and equal to :data:`DEFAULT_ALG`
      (Phase-3a is Ed25519-only).
    - ``cluster_id`` / ``org_id`` are non-empty strings.
    - ``public_key_hex`` is 64 lower-case hex characters.
    - ``valid_from`` < ``valid_until`` (lexical string compare; the
      RFC-3339 second-precision UTC format makes the lexical order
      equivalent to chronological order).
    """
    if not isinstance(entry.alg, str) or not entry.alg:
        raise FederationResolverError(
            f"alg must be a non-empty string; got {entry.alg!r}"
        )
    if entry.alg != DEFAULT_ALG:
        raise FederationResolverError(
            f"alg must equal {DEFAULT_ALG!r}; got {entry.alg!r}"
        )
    if not isinstance(entry.cluster_id, str) or not entry.cluster_id:
        raise FederationResolverError(
            f"cluster_id must be a non-empty string; got {entry.cluster_id!r}"
        )
    if not isinstance(entry.org_id, str) or not entry.org_id:
        raise FederationResolverError(
            f"org_id must be a non-empty string; got {entry.org_id!r}"
        )
    if not isinstance(entry.public_key_hex, str) or not _is_lower_hex(
        entry.public_key_hex, PUBLIC_KEY_HEX_LEN
    ):
        raise FederationResolverError(
            f"public_key_hex must be {PUBLIC_KEY_HEX_LEN} lower-case hex chars; "
            f"got {entry.public_key_hex!r}"
        )
    if not isinstance(entry.valid_from, str) or not entry.valid_from:
        raise FederationResolverError(
            f"valid_from must be a non-empty string; got {entry.valid_from!r}"
        )
    if not isinstance(entry.valid_until, str) or not entry.valid_until:
        raise FederationResolverError(
            f"valid_until must be a non-empty string; got {entry.valid_until!r}"
        )
    if entry.valid_from >= entry.valid_until:
        raise FederationResolverError(
            f"valid_from {entry.valid_from!r} must be lexically less than "
            f"valid_until {entry.valid_until!r}"
        )


# ---------------------------------------------------------------------
# FederationResolver Protocol (duck-typing boundary; sandbox-friendly)
# ---------------------------------------------------------------------


@runtime_checkable
class FederationResolver(Protocol):
    """Minimal shape every federation-resolver implementation honours.

    The Phase-3a in-memory reference implementation
    :class:`InMemoryFederationResolver` satisfies this Protocol. A
    future production implementation backed by NATS-KV, a SQL store,
    or a remote registry MAY substitute as long as the four methods
    below match the byte-shape contract documented here.
    """

    def resolve(
        self, org_id: str, cluster_id: str, *, now: str
    ) -> Optional[OperatorOrgKeyEntry]:
        """Return the entry currently valid at ``now`` for the given
        ``(org_id, cluster_id)`` pair, or ``None`` if no entry is
        currently valid.

        "Currently valid" means ``valid_from <= now < valid_until``
        (lexical compare, since RFC-3339 second-precision UTC strings
        are total-ordered lexically). When multiple entries overlap
        (key rotation with windowed overlap), the implementation
        SHOULD return the entry with the latest ``valid_from`` to
        prefer newer keys; the in-memory reference picks the entry
        with the highest ``valid_from`` among in-window entries.
        """
        ...

    def list_entries(self) -> List[OperatorOrgKeyEntry]:
        """Return all registered entries (any state), sorted
        lexicographically by ``(org_id, cluster_id, valid_from)``.

        The returned list is a defensive copy: callers may mutate it
        without affecting the resolver state. Implementations MUST
        NOT include the resolver's mutable storage by reference.
        """
        ...

    def snapshot(self) -> FederationResolverSnapshot:
        """Return a :class:`FederationResolverSnapshot` of the current
        entry set. The snapshot's ``entries`` list MUST be sorted
        lexicographically by ``(org_id, cluster_id, valid_from)``.
        """
        ...


# ---------------------------------------------------------------------
# InMemoryFederationResolver -- reference implementation
# ---------------------------------------------------------------------


class InMemoryFederationResolver:
    """In-memory reference implementation of
    :class:`FederationResolver`.

    Stores entries in insertion order in a plain list; resolution
    walks the list to gather all entries matching
    ``(org_id, cluster_id)`` whose validity window contains ``now``
    and picks the one with the latest ``valid_from``.

    Duplicate triples ``(org_id, cluster_id, valid_from)`` are
    rejected on registration with
    :class:`FederationResolverError`. Overlapping windows for the
    same ``(org_id, cluster_id)`` pair are explicitly allowed
    (Phase-3a key-rotation use-case).

    The class is intentionally **NOT** thread-safe. The Phase-3a
    consumer (frame-signature verifier) runs in a single-threaded
    async loop; a future production backing (NATS-KV) would
    serialise mutations via the KV's CAS surface.
    """

    def __init__(self, entries: Iterable[OperatorOrgKeyEntry] = ()) -> None:
        self._entries: List[OperatorOrgKeyEntry] = []
        # Keys (`(org_id, cluster_id, valid_from)`) of already-
        # registered entries, used for duplicate detection.
        self._seen: set = set()
        for e in entries:
            self.register(e)

    # -- mutators ------------------------------------------------------

    def register(self, entry: OperatorOrgKeyEntry) -> None:
        """Register a new entry.

        Raises :class:`FederationResolverError` on shape violation or
        on a duplicate ``(org_id, cluster_id, valid_from)`` triple.
        """
        _validate_entry(entry)
        triple = (entry.org_id, entry.cluster_id, entry.valid_from)
        if triple in self._seen:
            raise FederationResolverError(
                f"duplicate (org_id, cluster_id, valid_from) triple: {triple!r}"
            )
        self._seen.add(triple)
        self._entries.append(entry)

    # -- Protocol methods ---------------------------------------------

    def resolve(
        self, org_id: str, cluster_id: str, *, now: str
    ) -> Optional[OperatorOrgKeyEntry]:
        """Return the currently-valid entry for ``(org_id, cluster_id)``
        at ``now``, or ``None``.

        Selection rule when multiple entries are in-window: pick the
        one with the lexicographically-latest ``valid_from``. This
        biases toward freshly-rotated keys during the overlap window.
        """
        best: Optional[OperatorOrgKeyEntry] = None
        for e in self._entries:
            if e.org_id != org_id or e.cluster_id != cluster_id:
                continue
            if e.valid_from <= now < e.valid_until:
                if best is None or e.valid_from > best.valid_from:
                    best = e
        return best

    def list_entries(self) -> List[OperatorOrgKeyEntry]:
        """Return all registered entries, sorted lexicographically by
        ``(org_id, cluster_id, valid_from)``. Defensive copy.
        """
        return sorted(
            self._entries,
            key=lambda e: (e.org_id, e.cluster_id, e.valid_from),
        )

    def snapshot(self) -> FederationResolverSnapshot:
        """Return a sorted-entry-list snapshot for cross-lang pinning."""
        return FederationResolverSnapshot(
            entries=self.list_entries(),
            schema=FEDERATION_RESOLVER_SCHEMA,
        )


# ---------------------------------------------------------------------
# Wire-shape (JCS-canonical) projection helpers
# ---------------------------------------------------------------------


def _entry_to_wire_dict(entry: OperatorOrgKeyEntry) -> Dict[str, Any]:
    """Project a single :class:`OperatorOrgKeyEntry` onto the
    canonical-wire dict shape (six keys, alphabetical via
    ``sort_keys=True`` at serialisation time).
    """
    return {
        "alg": entry.alg,
        "cluster_id": entry.cluster_id,
        "org_id": entry.org_id,
        "public_key_hex": entry.public_key_hex,
        "valid_from": entry.valid_from,
        "valid_until": entry.valid_until,
    }


def resolver_snapshot_to_wire_dict(
    snap: FederationResolverSnapshot,
) -> Dict[str, Any]:
    """Project a :class:`FederationResolverSnapshot` onto a JSON-
    compatible dict.

    The returned dict's keys are NOT pre-sorted; the canonical-bytes
    producer (:func:`serialize_resolver_snapshot`) uses
    ``sort_keys=True`` to enforce JCS-canonical alphabetical key
    order. ``entries`` MUST already be sorted by the caller (or by
    :meth:`InMemoryFederationResolver.snapshot`); the entries-list
    order is the wire-form's authoritative order.
    """
    return {
        "entries": [_entry_to_wire_dict(e) for e in snap.entries],
        "schema": snap.schema,
    }


def serialize_resolver_snapshot(snap: FederationResolverSnapshot) -> bytes:
    """Return the JCS-canonical UTF-8 bytes of a resolver snapshot.

    Byte-form is deterministic, sorted-key, no-whitespace JSON. The
    Rust pendant ``persona-engine-federation-resolver::
    serialize_resolver_snapshot`` emits the same bytes for the same
    logical input.
    """
    obj = resolver_snapshot_to_wire_dict(snap)
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    """Return the lower-case hex digest of SHA-256 over ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def resolver_snapshot_sha256_hex(snap: FederationResolverSnapshot) -> str:
    """Return the bare lower-case hex SHA-256 of the canonical bytes."""
    return sha256_hex(serialize_resolver_snapshot(snap))


def resolver_snapshot_hash_prefixed(snap: FederationResolverSnapshot) -> str:
    """Return ``"sha256:" + resolver_snapshot_sha256_hex(snap)``."""
    return HASH_PREFIX + resolver_snapshot_sha256_hex(snap)


def serialize_and_hash(
    snap: FederationResolverSnapshot,
) -> Tuple[bytes, str]:
    """One-shot helper: return ``(canonical_bytes, prefixed_hash)``.

    Equivalent to calling :func:`serialize_resolver_snapshot` and
    :func:`resolver_snapshot_hash_prefixed` individually but only
    serialises once.
    """
    payload = serialize_resolver_snapshot(snap)
    return payload, HASH_PREFIX + sha256_hex(payload)


# ---------------------------------------------------------------------
# Convenience constructors (cross-lang-parity helpers)
# ---------------------------------------------------------------------


def build_entry(
    *,
    org_id: str,
    cluster_id: str,
    public_key_hex: str,
    valid_from: str,
    valid_until: str,
    alg: str = DEFAULT_ALG,
) -> OperatorOrgKeyEntry:
    """Construct an :class:`OperatorOrgKeyEntry` with the default
    algorithm pin. Validation is deferred to
    :meth:`InMemoryFederationResolver.register`; the entry-builder
    itself never raises.
    """
    return OperatorOrgKeyEntry(
        alg=alg,
        cluster_id=cluster_id,
        org_id=org_id,
        public_key_hex=public_key_hex,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def build_snapshot_from_entries(
    entries: Sequence[OperatorOrgKeyEntry],
) -> FederationResolverSnapshot:
    """Build a sorted-entry-list snapshot from a flat sequence.

    Useful in tests / fixture builders that want to derive a
    snapshot without spinning up an
    :class:`InMemoryFederationResolver`. The entries are sorted
    lexicographically by ``(org_id, cluster_id, valid_from)`` so the
    canonical bytes are stable regardless of input order.
    """
    sorted_entries = sorted(
        entries, key=lambda e: (e.org_id, e.cluster_id, e.valid_from)
    )
    return FederationResolverSnapshot(
        entries=list(sorted_entries),
        schema=FEDERATION_RESOLVER_SCHEMA,
    )


__all__ = [
    "DEFAULT_ALG",
    "FEDERATION_RESOLVER_SCHEMA",
    "FederationResolver",
    "FederationResolverError",
    "FederationResolverSnapshot",
    "HASH_PREFIX",
    "InMemoryFederationResolver",
    "OperatorOrgKeyEntry",
    "PUBLIC_KEY_HEX_LEN",
    "SHA256_HEX_LEN",
    "build_entry",
    "build_snapshot_from_entries",
    "resolver_snapshot_hash_prefixed",
    "resolver_snapshot_sha256_hex",
    "resolver_snapshot_to_wire_dict",
    "serialize_and_hash",
    "serialize_resolver_snapshot",
    "sha256_hex",
]
