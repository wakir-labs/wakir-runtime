# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine federation-resolver
``FederationResolverSnapshot`` JCS canonicalisation surface (Tag-24).

The Python module under test
(:mod:`wirelang.identity.federation_resolver_canonical`) is Apache-2.0;
this test file is Apache-2.0 so downstream re-implementers can re-use
the same fixture vectors and the cross-lang contract. The Rust sibling
crate
(``wirelang-rust/crates/persona-engine-federation-resolver``) is
Apache-2.0 and consumes the same authoritative
``tests/fixtures/federation-resolver-cross-lang/fixtures.json`` file.

Test taxonomy (12 numbered cases; pytest parametrisation lifts the
total assertions count to ~24)
------------------------------------------------------------------

- T01 -- Constants pin: ``FEDERATION_RESOLVER_SCHEMA``,
  ``HASH_PREFIX``, ``SHA256_HEX_LEN``, ``PUBLIC_KEY_HEX_LEN``,
  ``DEFAULT_ALG`` match the documented Rust ``pub const`` items.
- T02 -- Empty-resolver snapshot byte-pin: a fresh
  :class:`InMemoryFederationResolver` snapshots to the fixed empty
  form ``{"entries":[],"schema":"wakir.federation.resolver-snapshot/1"}``.
- T03 -- Entry validation rejects bad inputs (alg, hex length,
  empty strings, valid_from >= valid_until).
- T04 -- Duplicate-triple registration is rejected.
- T05 -- Snapshot is independent of insertion order: registering the
  same five entries in two different orders produces byte-identical
  snapshots (sorting invariant).
- T06 -- JCS-key ordering: top-level keys are ``entries`` then
  ``schema`` (alphabetical); per-entry keys are alphabetical
  (``alg, cluster_id, org_id, public_key_hex, valid_from,
  valid_until``).
- T07 -- Determinism: two snapshot+hash calls on the same resolver
  state return byte-identical payloads and identical prefixed hashes.
- T08 -- Resolution rule when overlapping windows exist: pick the
  entry with the lexicographically-latest ``valid_from`` among
  in-window entries.
- T09 -- Resolution returns ``None`` for an org/cluster pair that
  has no in-window entry (and for an unknown org/cluster pair).
- T10 -- Fixture file structure pin: ``schema_version``, fixture
  count, names, and per-fixture key set match the cross-lang
  contract.
- T11 -- Cross-lang fixture per-vector pin (parametrised over the
  five fixtures): byte-for-byte parity with the JSON fixture file's
  pinned ``snapshot_jcs_bytes_b64`` / ``snapshot_jcs_bytes_len`` /
  ``snapshot_sha256_hex`` / ``snapshot_hash_prefixed`` values. This
  is the core byte-parity test.
- T12 -- Resolution-probe parity: every fixture carries a
  ``resolve_probe`` block; the Python :meth:`resolve` output must
  match the pinned ``expected_match`` (``null`` for f01 / f05;
  exact dict equality for f02 / f03 / f04).

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``serialize_resolver_snapshot`` and
   Python :func:`serialize_resolver_snapshot`).
2. Re-derive the fixture vectors using the derivation snippet at the
   top of :mod:`wirelang.identity.federation_resolver_canonical`.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T11) fires on both sides -- that is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.identity.federation_resolver_canonical import (
    DEFAULT_ALG,
    FEDERATION_RESOLVER_SCHEMA,
    FederationResolverError,
    FederationResolverSnapshot,
    HASH_PREFIX,
    InMemoryFederationResolver,
    OperatorOrgKeyEntry,
    PUBLIC_KEY_HEX_LEN,
    SHA256_HEX_LEN,
    build_entry,
    build_snapshot_from_entries,
    resolver_snapshot_hash_prefixed,
    resolver_snapshot_sha256_hex,
    resolver_snapshot_to_wire_dict,
    serialize_and_hash,
    serialize_resolver_snapshot,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "federation-resolver-cross-lang"
    / "fixtures.json"
)


@pytest.fixture(scope="module")
def fixtures_doc() -> Dict[str, Any]:
    """Load the authoritative cross-lang fixture file."""
    with _FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


_FIXTURE_NAMES = [
    "f01-empty-resolver",
    "f02-single-org-multi-cluster",
    "f03-multi-org-disjoint",
    "f04-key-rotation-history",
    "f05-expired-mapping",
]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _entry_from_dict(d: Dict[str, Any]) -> OperatorOrgKeyEntry:
    return OperatorOrgKeyEntry(
        alg=d["alg"],
        cluster_id=d["cluster_id"],
        org_id=d["org_id"],
        public_key_hex=d["public_key_hex"],
        valid_from=d["valid_from"],
        valid_until=d["valid_until"],
    )


def _resolver_from_fixture(fx: Dict[str, Any]) -> InMemoryFederationResolver:
    r = InMemoryFederationResolver()
    for e_dict in fx["input_entries"]:
        r.register(_entry_from_dict(e_dict))
    return r


# ---------------------------------------------------------------------
# T01 -- Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_pin() -> None:
    assert FEDERATION_RESOLVER_SCHEMA == "wakir.federation.resolver-snapshot/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64
    assert PUBLIC_KEY_HEX_LEN == 64
    assert DEFAULT_ALG == "Ed25519"


# ---------------------------------------------------------------------
# T02 -- Empty-resolver snapshot byte-pin
# ---------------------------------------------------------------------


def test_t02_empty_resolver_snapshot_bytes() -> None:
    r = InMemoryFederationResolver()
    snap = r.snapshot()
    assert isinstance(snap, FederationResolverSnapshot)
    assert snap.entries == []
    assert snap.schema == FEDERATION_RESOLVER_SCHEMA
    bytes_ = serialize_resolver_snapshot(snap)
    assert bytes_ == (
        b'{"entries":[],"schema":"wakir.federation.resolver-snapshot/1"}'
    )
    # Alternate-derivation: SHA-256 over the bytes matches the helper.
    direct_hex = hashlib.sha256(bytes_).hexdigest()
    assert resolver_snapshot_sha256_hex(snap) == direct_hex
    assert resolver_snapshot_hash_prefixed(snap) == "sha256:" + direct_hex


# ---------------------------------------------------------------------
# T03 -- Entry validation rejects bad inputs
# ---------------------------------------------------------------------


def test_t03_validation_rejects_bad_alg() -> None:
    r = InMemoryFederationResolver()
    with pytest.raises(FederationResolverError):
        r.register(
            OperatorOrgKeyEntry(
                alg="RSA-2048",  # not Ed25519
                cluster_id="primary",
                org_id="wakir-labs",
                public_key_hex="a" * 64,
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
            )
        )


def test_t03_validation_rejects_short_pubkey() -> None:
    r = InMemoryFederationResolver()
    with pytest.raises(FederationResolverError):
        r.register(
            OperatorOrgKeyEntry(
                alg="Ed25519",
                cluster_id="primary",
                org_id="wakir-labs",
                public_key_hex="a" * 63,  # one short
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
            )
        )


def test_t03_validation_rejects_upper_hex() -> None:
    r = InMemoryFederationResolver()
    with pytest.raises(FederationResolverError):
        r.register(
            OperatorOrgKeyEntry(
                alg="Ed25519",
                cluster_id="primary",
                org_id="wakir-labs",
                public_key_hex="A" * 64,  # upper-case rejected
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
            )
        )


def test_t03_validation_rejects_inverted_window() -> None:
    r = InMemoryFederationResolver()
    with pytest.raises(FederationResolverError):
        r.register(
            OperatorOrgKeyEntry(
                alg="Ed25519",
                cluster_id="primary",
                org_id="wakir-labs",
                public_key_hex="a" * 64,
                valid_from="2027-01-01T00:00:00Z",
                valid_until="2026-01-01T00:00:00Z",  # before from
            )
        )


def test_t03_validation_rejects_empty_org_or_cluster() -> None:
    r = InMemoryFederationResolver()
    base = build_entry(
        org_id="",
        cluster_id="primary",
        public_key_hex="a" * 64,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
    )
    with pytest.raises(FederationResolverError):
        r.register(base)
    r2 = InMemoryFederationResolver()
    base2 = build_entry(
        org_id="wakir-labs",
        cluster_id="",
        public_key_hex="a" * 64,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
    )
    with pytest.raises(FederationResolverError):
        r2.register(base2)


# ---------------------------------------------------------------------
# T04 -- Duplicate-triple rejection
# ---------------------------------------------------------------------


def test_t04_duplicate_triple_rejected() -> None:
    r = InMemoryFederationResolver()
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    # Same (org_id, cluster_id, valid_from) triple even with a different
    # public_key_hex / valid_until is rejected.
    with pytest.raises(FederationResolverError):
        r.register(
            build_entry(
                org_id="wakir-labs",
                cluster_id="primary",
                public_key_hex="b" * 64,
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-06-01T00:00:00Z",
            )
        )


# ---------------------------------------------------------------------
# T05 -- Snapshot independent of insertion order
# ---------------------------------------------------------------------


def test_t05_snapshot_independent_of_insertion_order() -> None:
    entries = [
        build_entry(
            org_id="org-z",
            cluster_id="cluster-a",
            public_key_hex="1" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        ),
        build_entry(
            org_id="org-a",
            cluster_id="cluster-z",
            public_key_hex="2" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        ),
        build_entry(
            org_id="org-a",
            cluster_id="cluster-a",
            public_key_hex="3" * 64,
            valid_from="2025-01-01T00:00:00Z",
            valid_until="2026-01-01T00:00:00Z",
        ),
        build_entry(
            org_id="org-a",
            cluster_id="cluster-a",
            public_key_hex="4" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        ),
    ]

    r1 = InMemoryFederationResolver()
    for e in entries:
        r1.register(e)

    r2 = InMemoryFederationResolver()
    for e in reversed(entries):
        r2.register(e)

    bytes_1 = serialize_resolver_snapshot(r1.snapshot())
    bytes_2 = serialize_resolver_snapshot(r2.snapshot())
    assert bytes_1 == bytes_2
    assert resolver_snapshot_sha256_hex(r1.snapshot()) == resolver_snapshot_sha256_hex(
        r2.snapshot()
    )


# ---------------------------------------------------------------------
# T06 -- JCS key ordering
# ---------------------------------------------------------------------


def test_t06_jcs_key_ordering() -> None:
    r = InMemoryFederationResolver()
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    payload = serialize_resolver_snapshot(r.snapshot()).decode("utf-8")
    # Top-level: "entries" before "schema" (alphabetical).
    pos_entries = payload.index('"entries"')
    pos_schema = payload.index('"schema"')
    assert pos_entries < pos_schema
    # Per-entry alphabetical: alg, cluster_id, org_id, public_key_hex,
    # valid_from, valid_until.
    pos_alg = payload.index('"alg"')
    pos_cluster_id = payload.index('"cluster_id"')
    pos_org_id = payload.index('"org_id"')
    pos_public_key_hex = payload.index('"public_key_hex"')
    pos_valid_from = payload.index('"valid_from"')
    pos_valid_until = payload.index('"valid_until"')
    assert pos_alg < pos_cluster_id < pos_org_id < pos_public_key_hex < pos_valid_from < pos_valid_until


# ---------------------------------------------------------------------
# T07 -- Determinism
# ---------------------------------------------------------------------


def test_t07_determinism() -> None:
    r = InMemoryFederationResolver()
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    r.register(
        build_entry(
            org_id="callandor",
            cluster_id="backup-eu",
            public_key_hex="b" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    bytes_1, hash_1 = serialize_and_hash(r.snapshot())
    bytes_2, hash_2 = serialize_and_hash(r.snapshot())
    assert bytes_1 == bytes_2
    assert hash_1 == hash_2
    assert hash_1 == HASH_PREFIX + hashlib.sha256(bytes_1).hexdigest()


# ---------------------------------------------------------------------
# T08 -- Resolution rule: pick latest-valid_from among in-window
# ---------------------------------------------------------------------


def test_t08_resolution_picks_latest_valid_from_among_in_window() -> None:
    r = InMemoryFederationResolver()
    # Overlapping rotation window: both entries are in-window at
    # 2026-04-15; the resolver MUST prefer the one with the latest
    # valid_from.
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2026-07-01T00:00:00Z",
        )
    )
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="b" * 64,
            valid_from="2026-04-01T00:00:00Z",
            valid_until="2026-10-01T00:00:00Z",
        )
    )
    match = r.resolve("wakir-labs", "primary", now="2026-04-15T00:00:00Z")
    assert match is not None
    assert match.public_key_hex == "b" * 64
    assert match.valid_from == "2026-04-01T00:00:00Z"


# ---------------------------------------------------------------------
# T09 -- Resolution returns None on miss
# ---------------------------------------------------------------------


def test_t09_resolution_returns_none_on_miss() -> None:
    r = InMemoryFederationResolver()
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    # Unknown org.
    assert r.resolve("unknown-org", "primary", now="2026-06-15T00:00:00Z") is None
    # Unknown cluster (known org).
    assert r.resolve("wakir-labs", "missing-cluster", now="2026-06-15T00:00:00Z") is None
    # Known pair but ``now`` outside any window.
    assert r.resolve("wakir-labs", "primary", now="2025-06-15T00:00:00Z") is None
    assert r.resolve("wakir-labs", "primary", now="2028-06-15T00:00:00Z") is None
    # valid_until is exclusive: ``now == valid_until`` is a miss.
    assert r.resolve("wakir-labs", "primary", now="2027-01-01T00:00:00Z") is None
    # valid_from is inclusive: ``now == valid_from`` is a hit.
    hit = r.resolve("wakir-labs", "primary", now="2026-01-01T00:00:00Z")
    assert hit is not None
    assert hit.public_key_hex == "a" * 64


# ---------------------------------------------------------------------
# T10 -- Fixture file structure pin
# ---------------------------------------------------------------------


def test_t10_fixture_file_structure(fixtures_doc: Dict[str, Any]) -> None:
    assert (
        fixtures_doc["schema_version"]
        == "wakir.federation.resolver-snapshot/1"
    )
    fixtures = fixtures_doc["fixtures"]
    assert len(fixtures) == 5
    names = [f["name"] for f in fixtures]
    assert names == _FIXTURE_NAMES
    for fx in fixtures:
        assert "comment" in fx
        assert "input_entries" in fx
        assert "expected" in fx
        assert "resolve_probe" in fx
        exp = fx["expected"]
        for k in (
            "snapshot_jcs_bytes_b64",
            "snapshot_jcs_bytes_len",
            "snapshot_sha256_hex",
            "snapshot_hash_prefixed",
        ):
            assert k in exp, f"fixture {fx['name']!r} missing expected.{k}"
        for e in fx["input_entries"]:
            for k in (
                "alg",
                "cluster_id",
                "org_id",
                "public_key_hex",
                "valid_from",
                "valid_until",
            ):
                assert k in e, f"fixture {fx['name']!r} entry missing {k}"


# ---------------------------------------------------------------------
# T11 -- Cross-lang fixture per-vector pin (parametrised)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_t11_cross_lang_fixture_byte_parity(
    fixtures_doc: Dict[str, Any], fixture_name: str
) -> None:
    fx = next(f for f in fixtures_doc["fixtures"] if f["name"] == fixture_name)
    r = _resolver_from_fixture(fx)
    snap = r.snapshot()
    bytes_ = serialize_resolver_snapshot(snap)
    exp = fx["expected"]
    exp_bytes = base64.b64decode(exp["snapshot_jcs_bytes_b64"])
    assert bytes_ == exp_bytes, (
        f"fixture {fixture_name!r}: canonical JCS bytes drifted.\n"
        f"got     {bytes_.decode()!r}\n"
        f"expect  {exp_bytes.decode()!r}"
    )
    assert len(bytes_) == exp["snapshot_jcs_bytes_len"]
    assert resolver_snapshot_sha256_hex(snap) == exp["snapshot_sha256_hex"]
    assert resolver_snapshot_hash_prefixed(snap) == exp["snapshot_hash_prefixed"]


# ---------------------------------------------------------------------
# T12 -- Resolution-probe parity (parametrised)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_t12_resolve_probe_parity(
    fixtures_doc: Dict[str, Any], fixture_name: str
) -> None:
    fx = next(f for f in fixtures_doc["fixtures"] if f["name"] == fixture_name)
    r = _resolver_from_fixture(fx)
    probe = fx["resolve_probe"]
    got = r.resolve(
        probe["org_id"],
        probe["cluster_id"],
        now=probe["now_utc"],
    )
    expected = probe["expected_match"]
    if expected is None:
        assert got is None, (
            f"fixture {fixture_name!r}: resolve_probe expected None, got {got!r}"
        )
    else:
        assert got is not None, (
            f"fixture {fixture_name!r}: resolve_probe expected match, got None"
        )
        assert got.alg == expected["alg"]
        assert got.org_id == expected["org_id"]
        assert got.cluster_id == expected["cluster_id"]
        assert got.public_key_hex == expected["public_key_hex"]
        assert got.valid_from == expected["valid_from"]
        assert got.valid_until == expected["valid_until"]


# ---------------------------------------------------------------------
# Bonus -- list_entries returns defensive copy
# ---------------------------------------------------------------------


def test_list_entries_returns_defensive_copy() -> None:
    r = InMemoryFederationResolver()
    r.register(
        build_entry(
            org_id="wakir-labs",
            cluster_id="primary",
            public_key_hex="a" * 64,
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2027-01-01T00:00:00Z",
        )
    )
    list_1 = r.list_entries()
    list_2 = r.list_entries()
    assert list_1 == list_2
    # The two returned lists are distinct objects (defensive copy).
    assert list_1 is not list_2
    list_1.clear()
    list_3 = r.list_entries()
    assert len(list_3) == 1, (
        "mutating the returned list_entries() output must not affect the resolver"
    )


# ---------------------------------------------------------------------
# Bonus -- runtime_checkable Protocol membership
# ---------------------------------------------------------------------


def test_inmemory_resolver_satisfies_protocol() -> None:
    from wirelang.identity.federation_resolver_canonical import FederationResolver

    r = InMemoryFederationResolver()
    # runtime_checkable Protocol: isinstance returns True iff the
    # concrete type has all required attributes.
    assert isinstance(r, FederationResolver)
