# SPDX-License-Identifier: BUSL-1.1
"""Tests for the persona-state backing trait (spec §3.7.5)."""

from __future__ import annotations

import pytest

from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBacking,
    PersonaStateBackingError,
    PersonaStateSnapshot,
    snapshot_payload_sha256,
    snapshot_to_jcs_bytes,
)


def _snap(offset_seed: int = 0, h: str = "0" * 64) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash=f"sha256:{h}",
        audit_trace_offset=offset_seed,
        capability_token_ids=("tok-1", "tok-2"),
        snapshot_at_utc=f"2026-05-15T{offset_seed:02d}:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )


# -------------------- envelope canonicalisation --------------------


def test_jcs_bytes_byte_stable():
    s1 = _snap()
    s2 = _snap()
    assert snapshot_to_jcs_bytes(s1) == snapshot_to_jcs_bytes(s2)


def test_jcs_bytes_changes_on_field_change():
    s1 = _snap(0)
    s2 = _snap(1)
    assert snapshot_to_jcs_bytes(s1) != snapshot_to_jcs_bytes(s2)


def test_jcs_keys_alphabetical():
    bytes_ = snapshot_to_jcs_bytes(_snap())
    text = bytes_.decode("utf-8")
    # Quick alphabetical-order check on the top-level keys.
    keys_in_order = [
        "audit_trace_offset",
        "capability_token_ids",
        "persona_hash",
        "snapshot_at_utc",
        "workspace_state_hash",
    ]
    positions = [text.index(f'"{k}"') for k in keys_in_order]
    assert positions == sorted(positions)


def test_payload_sha256_prefix_and_length():
    h = snapshot_payload_sha256(_snap())
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


# -------------------- in-memory backing --------------------


def test_inmemory_snapshot_assigns_monotonic_offsets():
    b = InMemoryPersonaStateBacking()
    off1 = b.snapshot("tomas", _snap(0))
    off2 = b.snapshot("tomas", _snap(1))
    assert off1 == 1
    assert off2 == 2


def test_inmemory_idempotent_on_byte_equal_snapshot():
    b = InMemoryPersonaStateBacking()
    s = _snap(0)
    off1 = b.snapshot("tomas", s)
    off2 = b.snapshot("tomas", s)
    assert off1 == off2  # byte-equal -> same offset, no new write


def test_inmemory_restore_latest_returns_last_snapshot():
    b = InMemoryPersonaStateBacking()
    s1 = _snap(0)
    s2 = _snap(1)
    b.snapshot("tomas", s1)
    b.snapshot("tomas", s2)
    restored = b.restore_latest("tomas")
    assert restored is not None
    assert snapshot_to_jcs_bytes(restored) == snapshot_to_jcs_bytes(s2)


def test_inmemory_restore_latest_none_on_cold_start():
    b = InMemoryPersonaStateBacking()
    assert b.restore_latest("tomas") is None


def test_inmemory_list_snapshots_oldest_first():
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    b.snapshot("tomas", _snap(1))
    b.snapshot("tomas", _snap(2))
    offsets = b.list_snapshots("tomas")
    assert offsets == [1, 2, 3]


def test_inmemory_atomic_swap_first_pin_accepts():
    b = InMemoryPersonaStateBacking()
    off = b.snapshot("tomas", _snap(0))
    # First pin: from_offset is ignored, must point to an existing offset.
    b.atomic_swap_pinned_offset("tomas", from_offset=0, to_offset=off)


def test_inmemory_atomic_swap_rejects_mismatched_from():
    b = InMemoryPersonaStateBacking()
    off1 = b.snapshot("tomas", _snap(0))
    off2 = b.snapshot("tomas", _snap(1))
    b.atomic_swap_pinned_offset("tomas", from_offset=0, to_offset=off1)
    with pytest.raises(PersonaStateBackingError):
        b.atomic_swap_pinned_offset(
            "tomas", from_offset=999, to_offset=off2
        )


def test_inmemory_atomic_swap_rejects_unknown_target_offset():
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    with pytest.raises(PersonaStateBackingError):
        b.atomic_swap_pinned_offset(
            "tomas", from_offset=0, to_offset=9999
        )


def test_inmemory_cross_persona_isolation():
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    b.snapshot("aisha", _snap(0))
    assert b.list_snapshots("tomas") == [1]
    assert b.list_snapshots("aisha") == [1]
    assert b.restore_latest("tomas") is not None
    assert b.restore_latest("aisha") is not None


# -------------------- trait surface --------------------


def test_abstract_trait_raises_not_implemented():
    t = PersonaStateBacking()
    with pytest.raises(NotImplementedError):
        t.snapshot("tomas", _snap())
    with pytest.raises(NotImplementedError):
        t.restore_latest("tomas")
    with pytest.raises(NotImplementedError):
        t.list_snapshots("tomas")
    with pytest.raises(NotImplementedError):
        t.atomic_swap_pinned_offset("tomas", 0, 1)
