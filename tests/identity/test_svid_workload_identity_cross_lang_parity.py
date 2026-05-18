# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine SVID-workload-
identity ``SvidWorkloadIdentitySnapshot`` JCS canonicalisation
surface (Tag-33 Mini-Welle, Henrik F-6).

The Python module under test
(:mod:`wirelang.identity.svid_workload_identity_canonical`) is
Apache-2.0; this test file is Apache-2.0 so downstream re-implementers
can re-use the same fixture vectors and the cross-lang contract.
The future Rust sibling crate slot at
``wirelang-rust/crates/persona-engine-svid-workload-identity``
(currently a Tag-29 probe skeleton) is Apache-2.0 and is reserved to
consume the same authoritative
``tests/fixtures/svid-workload-cross-lang/fixtures.json`` once the
Sprint-Pengine-12 snapshot-encoder lands. Until then this test file
is the Authority-Pin: the Python authority drives the canonical
bytes and the fixture vectors freeze them.

Test taxonomy (12 numbered cases; pytest parametrisation lifts the
total assertion count to ~24)
------------------------------------------------------------------

- T01 -- Constants pin: ``SVID_WORKLOAD_IDENTITY_SCHEMA``,
  ``HASH_PREFIX``, ``SHA256_HEX_LEN``, ``BIND_STATE_PREFIX``,
  ``BIND_STATE_LEN``, ``SPIFFE_ID_TEMPLATE`` match the documented
  Rust ``pub const`` items (parity table in the authority module
  docstring).
- T02 -- Empty-registry snapshot byte-pin: a fresh
  :class:`InMemorySvidWorkloadRegistry` snapshots to the fixed
  empty form ``{"bindings":[],"schema":"wakir.identity.svid-
  workload-cross-lang/1"}``.
- T03 -- Binding validation rejects bad inputs (bind_state_sha256
  shape, empty strings, non-bool expired, non-spiffe spiffe_id).
- T04 -- Duplicate-triple replay rejection: same
  ``(org_id, persona_id, not_after_utc)`` with a *different*
  ``bind_state_sha256`` is rejected (key-rotation replay signal).
  Same triple with the *same* bind_state_sha256 is idempotent.
- T05 -- Snapshot is independent of insertion order: registering
  the fixture's input_bindings in two different orders produces
  byte-identical snapshots (sorting invariant).
- T06 -- JCS-key ordering: top-level keys are ``bindings`` then
  ``schema`` (alphabetical); per-binding keys are alphabetical
  (``bind_state_sha256, expired, not_after_utc, org_id,
  persona_id, spiffe_id``).
- T07 -- Determinism: two snapshot+hash calls on the same registry
  state return byte-identical payloads and identical prefixed
  hashes.
- T08 -- Resolution rule when multiple bindings exist for the same
  ``(org_id, persona_id)``: pick the lexicographically-latest
  ``not_after_utc`` strictly greater than ``now_utc``.
- T09 -- Resolution returns ``None`` for an ``(org_id, persona_id)``
  pair with no in-window binding (and for an unknown pair).
- T10 -- Fixture file structure pin: ``schema_version``,
  ``fixed_now_utc``, fixture count, names, and per-fixture key set
  match the cross-lang contract.
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

1. Update both sides (future Rust ``serialize_snapshot`` and Python
   :func:`serialize_snapshot`).
2. Re-derive the fixture vectors using the derivation snippet
   referenced at the top of :mod:`wirelang.identity.svid_workload_identity_canonical`.
3. Update both Python and (once shipped) Rust test suites in the
   same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T11) fires on the Python side -- that is the intended boundary
detector. The Rust pendant slot will join the boundary detection
once Sprint-Pengine-12 ships the snapshot encoder.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.identity.svid_workload_identity_canonical import (
    BIND_STATE_LEN,
    BIND_STATE_PREFIX,
    HASH_PREFIX,
    InMemorySvidWorkloadRegistry,
    SHA256_HEX_LEN,
    SPIFFE_ID_TEMPLATE,
    SVID_WORKLOAD_IDENTITY_SCHEMA,
    SvidWorkloadBinding,
    SvidWorkloadIdentityError,
    SvidWorkloadIdentitySnapshot,
    build_binding,
    build_snapshot_from_bindings,
    serialize_and_hash,
    serialize_snapshot,
    snapshot_hash_prefixed,
    snapshot_sha256_hex,
    snapshot_to_wire_dict,
    spiffe_id_matches_template,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "svid-workload-cross-lang"
    / "fixtures.json"
)


@pytest.fixture(scope="module")
def fixtures_doc() -> Dict[str, Any]:
    """Load the authoritative cross-lang fixture file."""
    with _FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


_FIXTURE_NAMES = [
    "f01-empty-identity-set",
    "f02-single-org-single-spiffe",
    "f03-multi-org-cross-mapping",
    "f04-key-rotation-svid-replay",
    "f05-expired-svid-rejection",
]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _binding_from_dict(d: Dict[str, Any]) -> SvidWorkloadBinding:
    return SvidWorkloadBinding(
        bind_state_sha256=d["bind_state_sha256"],
        expired=d["expired"],
        not_after_utc=d["not_after_utc"],
        org_id=d["org_id"],
        persona_id=d["persona_id"],
        spiffe_id=d["spiffe_id"],
    )


def _registry_from_fixture(fx: Dict[str, Any]) -> InMemorySvidWorkloadRegistry:
    r = InMemorySvidWorkloadRegistry()
    for b_dict in fx["input_bindings"]:
        r.register(_binding_from_dict(b_dict))
    return r


# ---------------------------------------------------------------------
# T01 -- Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_pin() -> None:
    assert SVID_WORKLOAD_IDENTITY_SCHEMA == "wakir.identity.svid-workload-cross-lang/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64
    assert BIND_STATE_PREFIX == "sha256:"
    assert BIND_STATE_LEN == 71  # len("sha256:") + 64
    assert SPIFFE_ID_TEMPLATE == "spiffe://wakir.{org_id}/persona/{persona_id}"


# ---------------------------------------------------------------------
# T02 -- Empty-registry snapshot byte-pin
# ---------------------------------------------------------------------


def test_t02_empty_registry_snapshot_bytes() -> None:
    r = InMemorySvidWorkloadRegistry()
    snap = r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z")
    assert isinstance(snap, SvidWorkloadIdentitySnapshot)
    assert snap.bindings == []
    assert snap.schema == SVID_WORKLOAD_IDENTITY_SCHEMA
    canon = serialize_snapshot(snap)
    assert canon == (
        b'{"bindings":[],"schema":"wakir.identity.svid-workload-cross-lang/1"}'
    )
    # Alternate-derivation: SHA-256 over the bytes matches the helper.
    direct_hex = hashlib.sha256(canon).hexdigest()
    assert snapshot_sha256_hex(snap) == direct_hex
    assert snapshot_hash_prefixed(snap) == "sha256:" + direct_hex


# ---------------------------------------------------------------------
# T03 -- Binding validation
# ---------------------------------------------------------------------


def test_t03_validation_rejects_bad_bind_state_shape() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="md5:" + "a" * 64,  # wrong prefix
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="mira",
                spiffe_id="spiffe://wakir.wakir-labs/persona/mira",
            )
        )


def test_t03_validation_rejects_short_bind_state_hex() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "a" * 63,  # one short
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="mira",
                spiffe_id="spiffe://wakir.wakir-labs/persona/mira",
            )
        )


def test_t03_validation_rejects_upper_hex() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "A" * 64,  # upper-case rejected
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="mira",
                spiffe_id="spiffe://wakir.wakir-labs/persona/mira",
            )
        )


def test_t03_validation_rejects_empty_org_or_persona() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "a" * 64,
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="",
                persona_id="mira",
                spiffe_id="spiffe://wakir.wakir-labs/persona/mira",
            )
        )
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "a" * 64,
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="",
                spiffe_id="spiffe://wakir.wakir-labs/persona/",
            )
        )


def test_t03_validation_rejects_non_spiffe_id() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "a" * 64,
                expired=False,
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="mira",
                spiffe_id="https://wakir.wakir-labs/persona/mira",  # not spiffe://
            )
        )


def test_t03_validation_rejects_non_bool_expired() -> None:
    r = InMemorySvidWorkloadRegistry()
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            SvidWorkloadBinding(
                bind_state_sha256="sha256:" + "a" * 64,
                expired="false",  # type: ignore[arg-type]
                not_after_utc="2026-06-18T00:00:00Z",
                org_id="wakir-labs",
                persona_id="mira",
                spiffe_id="spiffe://wakir.wakir-labs/persona/mira",
            )
        )


# ---------------------------------------------------------------------
# T04 -- Duplicate-triple replay rejection
# ---------------------------------------------------------------------


def test_t04_duplicate_triple_replay_rejected() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="mira",
            not_after_utc="2026-06-18T00:00:00Z",
            bind_state_sha256="sha256:" + "a" * 64,
        )
    )
    # Same (org_id, persona_id, not_after_utc) triple but DIFFERENT
    # bind_state_sha256 -> key-rotation replay signal -> rejected.
    with pytest.raises(SvidWorkloadIdentityError):
        r.register(
            build_binding(
                org_id="wakir-labs",
                persona_id="mira",
                not_after_utc="2026-06-18T00:00:00Z",
                bind_state_sha256="sha256:" + "b" * 64,
            )
        )


def test_t04_duplicate_triple_idempotent_on_full_match() -> None:
    r = InMemorySvidWorkloadRegistry()
    binding = build_binding(
        org_id="wakir-labs",
        persona_id="mira",
        not_after_utc="2026-06-18T00:00:00Z",
        bind_state_sha256="sha256:" + "a" * 64,
    )
    r.register(binding)
    # Same full payload -> idempotent no-op.
    r.register(binding)
    snap = r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z")
    assert len(snap.bindings) == 1


# ---------------------------------------------------------------------
# T05 -- Snapshot independent of insertion order
# ---------------------------------------------------------------------


def test_t05_snapshot_independent_of_insertion_order(
    fixtures_doc: Dict[str, Any],
) -> None:
    # Use the f04 fixture (three rotation bindings) -- non-trivial case.
    fx = next(
        f for f in fixtures_doc["fixtures"] if f["name"] == "f04-key-rotation-svid-replay"
    )
    fixed_now = fixtures_doc["fixed_now_utc"]
    bindings = [_binding_from_dict(b) for b in fx["input_bindings"]]

    r1 = InMemorySvidWorkloadRegistry()
    for b in bindings:
        r1.register(b)

    r2 = InMemorySvidWorkloadRegistry()
    for b in reversed(bindings):
        r2.register(b)

    canon_1 = serialize_snapshot(r1.snapshot(fixed_now_utc=fixed_now))
    canon_2 = serialize_snapshot(r2.snapshot(fixed_now_utc=fixed_now))
    assert canon_1 == canon_2
    assert snapshot_sha256_hex(
        r1.snapshot(fixed_now_utc=fixed_now)
    ) == snapshot_sha256_hex(r2.snapshot(fixed_now_utc=fixed_now))


# ---------------------------------------------------------------------
# T06 -- JCS key ordering
# ---------------------------------------------------------------------


def test_t06_jcs_key_ordering() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="mira",
            not_after_utc="2026-06-18T00:00:00Z",
            bind_state_sha256="sha256:" + "a" * 64,
        )
    )
    payload = serialize_snapshot(
        r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z")
    ).decode("utf-8")
    # Top-level: "bindings" before "schema" (alphabetical).
    pos_bindings = payload.index('"bindings"')
    pos_schema = payload.index('"schema"')
    assert pos_bindings < pos_schema
    # Per-binding alphabetical: bind_state_sha256, expired, not_after_utc,
    # org_id, persona_id, spiffe_id.
    pos_bind = payload.index('"bind_state_sha256"')
    pos_expired = payload.index('"expired"')
    pos_not_after = payload.index('"not_after_utc"')
    pos_org = payload.index('"org_id"')
    pos_persona = payload.index('"persona_id"')
    pos_spiffe = payload.index('"spiffe_id"')
    assert (
        pos_bind
        < pos_expired
        < pos_not_after
        < pos_org
        < pos_persona
        < pos_spiffe
    )


# ---------------------------------------------------------------------
# T07 -- Determinism
# ---------------------------------------------------------------------


def test_t07_determinism() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="mira",
            not_after_utc="2026-06-18T00:00:00Z",
            bind_state_sha256="sha256:" + "a" * 64,
        )
    )
    canon1, bare1, prefixed1 = serialize_and_hash(
        r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z")
    )
    canon2, bare2, prefixed2 = serialize_and_hash(
        r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z")
    )
    assert canon1 == canon2
    assert bare1 == bare2
    assert prefixed1 == prefixed2


# ---------------------------------------------------------------------
# T08 -- Resolution rule (freshest in-window wins)
# ---------------------------------------------------------------------


def test_t08_resolve_picks_freshest_in_window() -> None:
    r = InMemorySvidWorkloadRegistry()
    # Two bindings for the same (org, persona) -- second has later not_after.
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="tomas",
            not_after_utc="2026-05-25T00:00:00Z",
            bind_state_sha256="sha256:" + "1" * 64,
        )
    )
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="tomas",
            not_after_utc="2026-07-25T00:00:00Z",
            bind_state_sha256="sha256:" + "3" * 64,
        )
    )
    out = r.resolve("wakir-labs", "tomas", "2026-05-18T00:00:00Z")
    assert out is not None
    assert out.not_after_utc == "2026-07-25T00:00:00Z"
    assert out.bind_state_sha256 == "sha256:" + "3" * 64


# ---------------------------------------------------------------------
# T09 -- Resolution returns None for unknown / expired
# ---------------------------------------------------------------------


def test_t09_resolve_returns_none_for_unknown_pair() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="mira",
            not_after_utc="2026-06-18T00:00:00Z",
            bind_state_sha256="sha256:" + "a" * 64,
        )
    )
    assert r.resolve("unknown-org", "mira", "2026-05-18T00:00:00Z") is None
    assert r.resolve("wakir-labs", "unknown-persona", "2026-05-18T00:00:00Z") is None


def test_t09_resolve_returns_none_for_expired() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="aisha",
            not_after_utc="2026-01-01T00:00:00Z",
            bind_state_sha256="sha256:" + "9" * 64,
            expired=True,
        )
    )
    # now_utc is after not_after_utc -> no in-window binding.
    assert r.resolve("wakir-labs", "aisha", "2026-05-18T00:00:00Z") is None


# ---------------------------------------------------------------------
# T10 -- Fixture file structure pin
# ---------------------------------------------------------------------


def test_t10_fixture_file_structure(fixtures_doc: Dict[str, Any]) -> None:
    assert fixtures_doc["schema_version"] == SVID_WORKLOAD_IDENTITY_SCHEMA
    assert fixtures_doc["fixed_now_utc"] == "2026-05-18T00:00:00Z"
    fxs = fixtures_doc["fixtures"]
    assert len(fxs) == 5
    assert [f["name"] for f in fxs] == _FIXTURE_NAMES
    for fx in fxs:
        assert set(fx.keys()) >= {
            "name",
            "comment",
            "input_bindings",
            "expected",
            "resolve_probe",
        }
        assert set(fx["expected"].keys()) == {
            "snapshot_jcs_bytes_b64",
            "snapshot_jcs_bytes_len",
            "snapshot_sha256_hex",
            "snapshot_hash_prefixed",
        }
        assert set(fx["resolve_probe"].keys()) >= {
            "org_id",
            "persona_id",
            "now_utc",
            "expected_match",
        }


# ---------------------------------------------------------------------
# T11 -- Cross-lang fixture per-vector byte-pin
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_t11_fixture_byte_pin(
    fixtures_doc: Dict[str, Any], fixture_name: str
) -> None:
    fx = next(f for f in fixtures_doc["fixtures"] if f["name"] == fixture_name)
    fixed_now = fixtures_doc["fixed_now_utc"]
    bindings = [_binding_from_dict(b) for b in fx["input_bindings"]]
    snap = build_snapshot_from_bindings(bindings, fixed_now_utc=fixed_now)
    canonical, bare_hex, prefixed_hash = serialize_and_hash(snap)
    exp = fx["expected"]
    assert (
        base64.b64encode(canonical).decode("ascii")
        == exp["snapshot_jcs_bytes_b64"]
    ), f"{fixture_name}: snapshot_jcs_bytes_b64 mismatch"
    assert len(canonical) == exp["snapshot_jcs_bytes_len"], (
        f"{fixture_name}: snapshot_jcs_bytes_len mismatch "
        f"({len(canonical)} != {exp['snapshot_jcs_bytes_len']})"
    )
    assert bare_hex == exp["snapshot_sha256_hex"], (
        f"{fixture_name}: snapshot_sha256_hex mismatch"
    )
    assert prefixed_hash == exp["snapshot_hash_prefixed"], (
        f"{fixture_name}: snapshot_hash_prefixed mismatch"
    )


# ---------------------------------------------------------------------
# T12 -- Resolution-probe parity
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", _FIXTURE_NAMES)
def test_t12_resolve_probe_parity(
    fixtures_doc: Dict[str, Any], fixture_name: str
) -> None:
    fx = next(f for f in fixtures_doc["fixtures"] if f["name"] == fixture_name)
    r = _registry_from_fixture(fx)
    probe = fx["resolve_probe"]
    out = r.resolve(probe["org_id"], probe["persona_id"], probe["now_utc"])
    expected = probe["expected_match"]
    if expected is None:
        assert out is None, (
            f"{fixture_name}: expected None match; got {out!r}"
        )
    else:
        assert out is not None, (
            f"{fixture_name}: expected match {expected!r}; got None"
        )
        # Compare projection (the resolve return materialises expired=False
        # in-window by construction).
        assert out.bind_state_sha256 == expected["bind_state_sha256"]
        assert out.expired == expected["expired"]
        assert out.not_after_utc == expected["not_after_utc"]
        assert out.org_id == expected["org_id"]
        assert out.persona_id == expected["persona_id"]
        assert out.spiffe_id == expected["spiffe_id"]


# ---------------------------------------------------------------------
# Extra: spiffe_id template-matches helper
# ---------------------------------------------------------------------


def test_spiffe_id_matches_template_helper() -> None:
    b_match = build_binding(
        org_id="wakir-labs",
        persona_id="mira",
        not_after_utc="2026-06-18T00:00:00Z",
        bind_state_sha256="sha256:" + "a" * 64,
    )
    assert spiffe_id_matches_template(b_match) is True
    b_drift = SvidWorkloadBinding(
        bind_state_sha256="sha256:" + "a" * 64,
        expired=False,
        not_after_utc="2026-06-18T00:00:00Z",
        org_id="wakir-labs",
        persona_id="mira",
        spiffe_id="spiffe://wakir.wakir-labs/persona/MIRA",  # case drift
    )
    assert spiffe_id_matches_template(b_drift) is False


# ---------------------------------------------------------------------
# Extra: wire-dict projection sanity
# ---------------------------------------------------------------------


def test_snapshot_to_wire_dict_projection() -> None:
    r = InMemorySvidWorkloadRegistry()
    r.register(
        build_binding(
            org_id="wakir-labs",
            persona_id="mira",
            not_after_utc="2026-06-18T00:00:00Z",
            bind_state_sha256="sha256:" + "a" * 64,
        )
    )
    wire = snapshot_to_wire_dict(r.snapshot(fixed_now_utc="2026-05-18T00:00:00Z"))
    assert list(wire.keys()) == ["bindings", "schema"]
    assert wire["schema"] == SVID_WORKLOAD_IDENTITY_SCHEMA
    assert len(wire["bindings"]) == 1
    b = wire["bindings"][0]
    assert list(b.keys()) == [
        "bind_state_sha256",
        "expired",
        "not_after_utc",
        "org_id",
        "persona_id",
        "spiffe_id",
    ]
