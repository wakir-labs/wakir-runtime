# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine state-backing
``PersonaStateSnapshot`` JCS canonicalisation surface.

The Python module under test
(:mod:`wirelang.persona_engine.state_backing`) is BUSL-1.1; this test
file is Apache-2.0 so downstream re-implementers can re-use the same
fixture vectors and the cross-lang contract. The Rust sibling crate
(``wirelang-rust/crates/persona-engine-state-backing``) is Apache-2.0
and consumes the same authoritative
``tests/fixtures/state-backing-cross-lang/fixtures.json`` file.

Test taxonomy
-------------

- T01 — Constants pin: ``STATE_PACK_KEY_PREFIX``, ``OFFSET_KEY_WIDTH``,
  ``PINNED_KEY``, ``NEXT_OFFSET_KEY``, ``LATEST_KEY`` match the Rust
  crate's ``pub const`` items.
- T02 — Offset-key round-trip: ``offset_key`` + ``offset_from_key``
  match the byte-shape pinned in the Rust crate (zero-padded 20-digit
  decimal, ``state-pack/`` prefix).
- T03 — Sentinel-key rejection: ``offset_from_key`` raises
  ``ValueError`` on the three sentinel keys + on foreign prefixes.
- T04 — Snapshot envelope round-trip: ``snapshot_from_jcs_bytes`` is
  the inverse of ``snapshot_to_jcs_bytes`` for all five fields.
- T05 — JCS-key ordering: top-level JCS bytes have keys in strict
  alphabetical order (``audit_trace_offset``,
  ``capability_token_ids``, ``persona_hash``, ``snapshot_at_utc``,
  ``workspace_state_hash``).
- T06 — Hash shape: ``snapshot_payload_sha256`` returns
  ``"sha256:"`` + 64 lowercase hex characters.
- T07 — Determinism: two calls with the same input produce
  byte-identical JCS bytes and the same prefixed hash.
- T08 — Sensitivity: changing any of the five envelope fields flips
  the JCS bytes and the outer hash.
- T09 — Fixture file structure pin: ``schema_version``, fixture
  count, names, and per-fixture key set match the Rust sibling's
  structure pin (F01).
- T10 — Cross-lang fixture per-vector pin (parametrised over the
  five fixtures): byte-for-byte parity with the JSON fixture file's
  pinned values. This is the core byte-parity test.
- T11 — InMemory state-backing 5-fixture replay: snapshotting each
  fixture into the Python ``InMemoryPersonaStateBacking`` and reading
  the state back via ``restore_latest`` is round-trip-stable.
- T12 — InMemory idempotence under fixture vectors: re-snapshotting
  a byte-equal fixture returns the existing offset (no new write).
- T13 — JCS bytes match Rust SHA-256 byte-for-byte (alternate hash
  derivation path: hashlib.sha256 over the round-tripped fixture
  payload).
- T14 — Empty-token-list fixture: the JCS bytes contain the literal
  ``"capability_token_ids":[]`` segment (the empty-array drift
  sentinel — protects against re-sort that would emit ``null``).

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``snapshot_to_jcs_bytes`` and Python
   :func:`snapshot_to_jcs_bytes`).
2. Re-derive the fixture vectors using the derivation snippet at the
   top of :mod:`wirelang.persona_engine.state_backing`.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T10) fires on both sides — that is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    LATEST_KEY,
    NEXT_OFFSET_KEY,
    OFFSET_KEY_WIDTH,
    PINNED_KEY,
    PersonaStateSnapshot,
    STATE_PACK_KEY_PREFIX,
    offset_from_key,
    offset_key,
    snapshot_from_jcs_bytes,
    snapshot_payload_sha256,
    snapshot_to_jcs_bytes,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


def _fixture_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    # here = <repo>/wirelang/tests/persona_engine/<this-file>
    repo_root = here.parents[3]
    return (
        repo_root
        / "tests"
        / "fixtures"
        / "state-backing-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    with _fixture_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _snapshot_from_fixture_input(inp: Dict[str, Any]) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash=inp["persona_hash"],
        audit_trace_offset=int(inp["audit_trace_offset"]),
        capability_token_ids=tuple(inp["capability_token_ids"]),
        snapshot_at_utc=inp["snapshot_at_utc"],
        workspace_state_hash=inp["workspace_state_hash"],
    )


_EXPECTED_SCHEMA_VERSION = "wakir.persona-engine.persona-state-snapshot/1"
_EXPECTED_FIXTURE_NAMES = [
    "f01-empty-state",
    "f02-single-key",
    "f03-multi-key",
    "f04-overwrite-existing",
    "f05-delete-then-get",
]


# ---------------------------------------------------------------------
# T01 — Constants pin (byte-for-byte against the Rust sibling).
# ---------------------------------------------------------------------


def test_t01_constants_match_rust_sibling_pin() -> None:
    assert STATE_PACK_KEY_PREFIX == "state-pack"
    assert OFFSET_KEY_WIDTH == 20
    assert PINNED_KEY == "state-pack/__pinned__"
    assert NEXT_OFFSET_KEY == "state-pack/__next_offset__"
    assert LATEST_KEY == "state-pack/latest"


# ---------------------------------------------------------------------
# T02 — Offset-key byte shape + round-trip.
# ---------------------------------------------------------------------


def test_t02_offset_key_byte_shape_and_round_trip() -> None:
    # Byte shape: state-pack/<20-digit decimal>.
    assert offset_key(0) == "state-pack/00000000000000000000"
    assert offset_key(1) == "state-pack/00000000000000000001"
    assert offset_key(42) == "state-pack/00000000000000000042"
    assert offset_key(10**19) == "state-pack/10000000000000000000"
    # Round-trip.
    for off in [0, 1, 42, 999_999, 2**63 - 1]:
        assert offset_from_key(offset_key(off)) == off
    # Zero-padded keys sort lexicographically == numerically.
    keys = [offset_key(o) for o in [1, 2, 10, 100, 1000]]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------
# T03 — Sentinel-key rejection.
# ---------------------------------------------------------------------


def test_t03_offset_from_key_rejects_sentinel_keys() -> None:
    for sentinel in [PINNED_KEY, NEXT_OFFSET_KEY, LATEST_KEY]:
        with pytest.raises(ValueError):
            offset_from_key(sentinel)
    # Foreign prefix.
    with pytest.raises(ValueError):
        offset_from_key("foreign/0")
    # Prefix-only.
    with pytest.raises(ValueError):
        offset_from_key("state-pack")


# ---------------------------------------------------------------------
# T04 — Snapshot envelope round-trip.
# ---------------------------------------------------------------------


def test_t04_snapshot_envelope_round_trip() -> None:
    snap = PersonaStateSnapshot(
        persona_hash="sha256:" + "a" * 64,
        audit_trace_offset=17,
        capability_token_ids=("tok-x", "tok-y"),
        snapshot_at_utc="2026-05-17T12:00:00Z",
        workspace_state_hash="sha256:" + "b" * 64,
    )
    blob = snapshot_to_jcs_bytes(snap)
    parsed = snapshot_from_jcs_bytes(blob)
    assert parsed == snap


def test_t04b_snapshot_envelope_round_trip_missing_key_rejected() -> None:
    bad = b'{"audit_trace_offset":1,"capability_token_ids":[],"persona_hash":"sha256:0","snapshot_at_utc":"2026-05-17T00:00:00Z"}'
    with pytest.raises(ValueError):
        snapshot_from_jcs_bytes(bad)


# ---------------------------------------------------------------------
# T05 — JCS-key ordering.
# ---------------------------------------------------------------------


def test_t05_wire_shape_top_level_keys_alphabetical() -> None:
    snap = PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=1,
        capability_token_ids=("tok-1",),
        snapshot_at_utc="2026-05-17T00:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )
    text = snapshot_to_jcs_bytes(snap).decode("utf-8")
    keys_alpha = [
        "audit_trace_offset",
        "capability_token_ids",
        "persona_hash",
        "snapshot_at_utc",
        "workspace_state_hash",
    ]
    positions = [text.find(f'"{k}":') for k in keys_alpha]
    assert all(p > -1 for p in positions), (
        f"missing top-level key in JCS output: positions={positions}, text={text}"
    )
    assert positions == sorted(positions), (
        f"top-level keys not alphabetical: positions={positions}"
    )
    # No insignificant whitespace.
    assert ": " not in text
    assert ", " not in text


# ---------------------------------------------------------------------
# T06 — Hash shape.
# ---------------------------------------------------------------------


def test_t06_hash_shape_constraints() -> None:
    snap = PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=1,
        capability_token_ids=("tok-1",),
        snapshot_at_utc="2026-05-17T00:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )
    h = snapshot_payload_sha256(snap)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
    tail = h[len("sha256:") :]
    assert all(c in "0123456789abcdef" for c in tail)


# ---------------------------------------------------------------------
# T07 — Determinism.
# ---------------------------------------------------------------------


def test_t07_serialisation_is_deterministic() -> None:
    snap = PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=1,
        capability_token_ids=("tok-1",),
        snapshot_at_utc="2026-05-17T00:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )
    b1 = snapshot_to_jcs_bytes(snap)
    b2 = snapshot_to_jcs_bytes(snap)
    h1 = snapshot_payload_sha256(snap)
    h2 = snapshot_payload_sha256(snap)
    assert b1 == b2
    assert h1 == h2


# ---------------------------------------------------------------------
# T08 — Sensitivity: any field change flips the hash.
# ---------------------------------------------------------------------


def test_t08_field_sensitivity_changes_outer_hash() -> None:
    base = PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=1,
        capability_token_ids=("tok-1",),
        snapshot_at_utc="2026-05-17T00:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )
    base_h = snapshot_payload_sha256(base)
    variants = [
        # persona_hash differs.
        PersonaStateSnapshot(
            persona_hash="sha256:" + "2" * 64,
            audit_trace_offset=base.audit_trace_offset,
            capability_token_ids=base.capability_token_ids,
            snapshot_at_utc=base.snapshot_at_utc,
            workspace_state_hash=base.workspace_state_hash,
        ),
        # audit_trace_offset differs.
        PersonaStateSnapshot(
            persona_hash=base.persona_hash,
            audit_trace_offset=99,
            capability_token_ids=base.capability_token_ids,
            snapshot_at_utc=base.snapshot_at_utc,
            workspace_state_hash=base.workspace_state_hash,
        ),
        # capability_token_ids differs.
        PersonaStateSnapshot(
            persona_hash=base.persona_hash,
            audit_trace_offset=base.audit_trace_offset,
            capability_token_ids=("tok-x", "tok-y"),
            snapshot_at_utc=base.snapshot_at_utc,
            workspace_state_hash=base.workspace_state_hash,
        ),
        # snapshot_at_utc differs.
        PersonaStateSnapshot(
            persona_hash=base.persona_hash,
            audit_trace_offset=base.audit_trace_offset,
            capability_token_ids=base.capability_token_ids,
            snapshot_at_utc="2099-12-31T23:59:59Z",
            workspace_state_hash=base.workspace_state_hash,
        ),
        # workspace_state_hash differs.
        PersonaStateSnapshot(
            persona_hash=base.persona_hash,
            audit_trace_offset=base.audit_trace_offset,
            capability_token_ids=base.capability_token_ids,
            snapshot_at_utc=base.snapshot_at_utc,
            workspace_state_hash="sha256:" + "2" * 64,
        ),
    ]
    for v in variants:
        assert snapshot_payload_sha256(v) != base_h, (
            f"field-flip did not change the outer hash: {v}"
        )


# ---------------------------------------------------------------------
# T09 — Fixture file structure pin.
# ---------------------------------------------------------------------


def test_t09_fixture_file_structure_matches_rust_sibling_pin() -> None:
    v = _load_fixtures()
    assert v["schema_version"] == _EXPECTED_SCHEMA_VERSION
    fixtures = v["fixtures"]
    assert isinstance(fixtures, list)
    assert len(fixtures) == 5
    names = [fx["name"] for fx in fixtures]
    assert names == _EXPECTED_FIXTURE_NAMES
    for fx in fixtures:
        name = fx["name"]
        inp = fx["input"]
        for k in [
            "persona_hash",
            "audit_trace_offset",
            "capability_token_ids",
            "snapshot_at_utc",
            "workspace_state_hash",
        ]:
            assert k in inp, f"fixture {name!r} missing input.{k}"
        exp = fx["expected"]
        for k in [
            "snapshot_jcs_bytes_b64",
            "snapshot_jcs_bytes_len",
            "snapshot_sha256_hex",
            "snapshot_hash_prefixed",
        ]:
            assert k in exp, f"fixture {name!r} missing expected.{k}"


# ---------------------------------------------------------------------
# T10 — Cross-lang fixture per-vector pin (parametrised).
# ---------------------------------------------------------------------


def _all_fixture_names() -> List[str]:
    return _EXPECTED_FIXTURE_NAMES[:]


@pytest.mark.parametrize("fixture_name", _all_fixture_names())
def test_t10_cross_lang_fixture_byte_parity(fixture_name: str) -> None:
    v = _load_fixtures()
    fixtures = v["fixtures"]
    fx = next(f for f in fixtures if f["name"] == fixture_name)

    snap = _snapshot_from_fixture_input(fx["input"])
    exp = fx["expected"]
    exp_bytes = base64.b64decode(exp["snapshot_jcs_bytes_b64"])
    exp_len = int(exp["snapshot_jcs_bytes_len"])
    exp_sha = exp["snapshot_sha256_hex"]
    exp_prefixed = exp["snapshot_hash_prefixed"]

    bytes_ = snapshot_to_jcs_bytes(snap)
    assert bytes_ == exp_bytes, (
        f"fixture {fixture_name!r}: canonical JCS bytes drifted; "
        f"got {bytes_!r}, expected {exp_bytes!r}"
    )
    assert len(bytes_) == exp_len, (
        f"fixture {fixture_name!r}: byte length drift, "
        f"got {len(bytes_)}, expected {exp_len}"
    )

    bare = hashlib.sha256(bytes_).hexdigest()
    assert bare == exp_sha, (
        f"fixture {fixture_name!r}: bare SHA-256 drift, got {bare}, expected {exp_sha}"
    )

    prefixed = snapshot_payload_sha256(snap)
    assert prefixed == exp_prefixed, (
        f"fixture {fixture_name!r}: prefixed SHA-256 drift, got {prefixed}, expected {exp_prefixed}"
    )
    assert prefixed.startswith("sha256:")


# ---------------------------------------------------------------------
# T11 — InMemoryPersonaStateBacking 5-fixture replay.
# ---------------------------------------------------------------------


def test_t11_inmemory_backing_replays_all_fixtures() -> None:
    v = _load_fixtures()
    backing = InMemoryPersonaStateBacking()
    for fx in v["fixtures"]:
        persona_id = f"persona-{fx['name']}"
        snap = _snapshot_from_fixture_input(fx["input"])
        off = backing.snapshot(persona_id, snap)
        # First write into a fresh persona-id slot lands at offset 1.
        assert off == 1, f"fixture {fx['name']!r}: first snapshot offset != 1: {off}"
        restored = backing.restore_latest(persona_id)
        assert restored is not None, f"fixture {fx['name']!r}: cold-start restore returned None"
        # Byte-for-byte equality on the JCS envelope.
        assert snapshot_to_jcs_bytes(restored) == snapshot_to_jcs_bytes(snap), (
            f"fixture {fx['name']!r}: restore_latest produced drift"
        )


# ---------------------------------------------------------------------
# T12 — InMemory idempotence under fixture vectors.
# ---------------------------------------------------------------------


def test_t12_inmemory_idempotence_under_fixture_vectors() -> None:
    v = _load_fixtures()
    backing = InMemoryPersonaStateBacking()
    for fx in v["fixtures"]:
        persona_id = f"persona-{fx['name']}"
        snap = _snapshot_from_fixture_input(fx["input"])
        off1 = backing.snapshot(persona_id, snap)
        off1_again = backing.snapshot(persona_id, snap)
        assert off1 == off1_again, (
            f"fixture {fx['name']!r}: byte-equal re-snapshot must return existing offset; "
            f"first={off1}, second={off1_again}"
        )
        # Only one offset entry should be present.
        assert backing.list_snapshots(persona_id) == [off1]


# ---------------------------------------------------------------------
# T13 — JCS bytes feed deterministically into hashlib.sha256.
# ---------------------------------------------------------------------


def test_t13_jcs_bytes_match_alternate_sha256_derivation() -> None:
    v = _load_fixtures()
    for fx in v["fixtures"]:
        snap = _snapshot_from_fixture_input(fx["input"])
        bytes_ = snapshot_to_jcs_bytes(snap)
        # Independent sha256 path (mirrors what an external auditor
        # would compute over the canonical bytes).
        alt = "sha256:" + hashlib.sha256(bytes_).hexdigest()
        assert alt == snapshot_payload_sha256(snap), (
            f"fixture {fx['name']!r}: alternate sha256 derivation drifted"
        )
        # And against the fixture-pinned value.
        assert alt == fx["expected"]["snapshot_hash_prefixed"]


# ---------------------------------------------------------------------
# T14 — Empty-token-list drift sentinel.
# ---------------------------------------------------------------------


def test_t14_empty_token_list_emits_empty_array_literal() -> None:
    # The empty-state fixture exercises the empty capability_token_ids
    # path. The JCS bytes MUST contain the literal "[]" — a
    # re-serialisation drift (e.g. ``null`` for empty list) would
    # break the cross-lang byte-parity contract at the f01-empty-state
    # fixture, but the dedicated sentinel test here pinpoints the
    # cause if T10 fires.
    v = _load_fixtures()
    fx = next(f for f in v["fixtures"] if f["name"] == "f01-empty-state")
    snap = _snapshot_from_fixture_input(fx["input"])
    text = snapshot_to_jcs_bytes(snap).decode("utf-8")
    assert '"capability_token_ids":[]' in text, (
        f"empty-list drift: expected literal \"capability_token_ids\":[] in {text!r}"
    )
    # And similarly for the f05-delete-then-get fixture (post-deletion shape).
    fx5 = next(f for f in v["fixtures"] if f["name"] == "f05-delete-then-get")
    snap5 = _snapshot_from_fixture_input(fx5["input"])
    text5 = snapshot_to_jcs_bytes(snap5).decode("utf-8")
    assert '"capability_token_ids":[]' in text5
