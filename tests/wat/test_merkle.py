# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Unit tests for the in-house WAT Merkle aggregator.

The implementation under test is BSL-1.1; the tests themselves are
Apache-2.0 so downstream adopters can re-use the same vectors against
their own re-implementations once the BSL conversion fires.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from wat.merkle.aggregator import (
    DIR_LEFT,
    DIR_RIGHT,
    build_merkle_tree,
    compute_inner_hash,
    compute_leaf_hash,
    leaf_hash,
    merkle_proof,
    root_hash,
    verify_merkle_proof,
)


def _sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _make_leaves(n: int) -> list[bytes]:
    """Deterministic test leaves: SHA-256 of ``b"leaf-<i>"``."""
    return [_sha(f"leaf-{i}".encode()) for i in range(n)]


# ---------------------------------------------------------------------------
# Required-by-task tests
# ---------------------------------------------------------------------------


def test_empty_leaves_raises() -> None:
    with pytest.raises(ValueError):
        build_merkle_tree([])


def test_single_leaf_root() -> None:
    leaves = _make_leaves(1)
    root, levels = build_merkle_tree(leaves)
    assert root == leaves[0]
    assert levels == [leaves]


def test_two_leaves_root() -> None:
    leaves = _make_leaves(2)
    root, levels = build_merkle_tree(leaves)
    expected = _sha(leaves[0] + leaves[1])
    assert root == expected
    assert len(levels) == 2
    assert levels[0] == leaves
    assert levels[1] == [expected]


def test_three_leaves_with_duplicate() -> None:
    """Bitcoin pattern: odd count duplicates the last leaf."""
    leaves = _make_leaves(3)
    root, levels = build_merkle_tree(leaves)
    # Level 0 should be padded to four entries with leaves[2] dup'd.
    assert levels[0] == [leaves[0], leaves[1], leaves[2], leaves[2]]
    h01 = _sha(leaves[0] + leaves[1])
    h22 = _sha(leaves[2] + leaves[2])
    assert levels[1] == [h01, h22]
    assert root == _sha(h01 + h22)


def test_eight_leaves_balanced() -> None:
    leaves = _make_leaves(8)
    root, levels = build_merkle_tree(leaves)
    # No duplication needed: 8 -> 4 -> 2 -> 1.
    assert [len(level) for level in levels] == [8, 4, 2, 1]
    # Spot-check: recompute by hand.
    lvl1 = [_sha(leaves[i] + leaves[i + 1]) for i in range(0, 8, 2)]
    lvl2 = [_sha(lvl1[i] + lvl1[i + 1]) for i in range(0, 4, 2)]
    expected_root = _sha(lvl2[0] + lvl2[1])
    assert root == expected_root


def test_leaf_hash_4_field_canonicalization() -> None:
    """JCS conformance: field order in the source object must not matter."""
    h_a = compute_leaf_hash(
        event_id="evt-001",
        time="2026-05-06T12:00:00Z",
        payload_hash="aa" * 32,
        capability_token_hash="bb" * 32,
    )
    h_b = compute_leaf_hash(
        capability_token_hash="bb" * 32,
        payload_hash="aa" * 32,
        time="2026-05-06T12:00:00Z",
        event_id="evt-001",
    )
    assert h_a == h_b
    # And it must equal a manual JCS computation: keys sorted, no
    # whitespace, UTF-8 encoded.
    manual = json.dumps(
        {
            "capability_token_hash": "bb" * 32,
            "event_id": "evt-001",
            "payload_hash": "aa" * 32,
            "time": "2026-05-06T12:00:00Z",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert h_a == hashlib.sha256(manual).digest()


def test_proof_generation_first_leaf() -> None:
    leaves = _make_leaves(4)
    proof = merkle_proof(leaves, 0)
    # 4-leaf tree: proof has two siblings (sibling at lvl0 is leaves[1],
    # both to the right of the current node).
    assert len(proof) == 2
    assert proof[0][0] == leaves[1]
    assert proof[0][1] == DIR_RIGHT
    assert proof[1][1] == DIR_RIGHT


def test_proof_generation_middle_leaf() -> None:
    leaves = _make_leaves(4)
    proof = merkle_proof(leaves, 1)
    assert len(proof) == 2
    assert proof[0][0] == leaves[0]
    assert proof[0][1] == DIR_LEFT
    assert proof[1][1] == DIR_RIGHT


def test_proof_generation_last_leaf() -> None:
    leaves = _make_leaves(4)
    proof = merkle_proof(leaves, 3)
    assert len(proof) == 2
    assert proof[0][0] == leaves[2]
    assert proof[0][1] == DIR_LEFT
    assert proof[1][1] == DIR_LEFT


def test_proof_verification_valid() -> None:
    leaves = _make_leaves(8)
    root, _ = build_merkle_tree(leaves)
    for idx in range(len(leaves)):
        proof = merkle_proof(leaves, idx)
        assert verify_merkle_proof(leaves[idx], proof, root) is True


def test_proof_verification_invalid_leaf_rejected() -> None:
    leaves = _make_leaves(4)
    root, _ = build_merkle_tree(leaves)
    proof = merkle_proof(leaves, 0)
    bogus_leaf = _sha(b"not-in-tree")
    assert verify_merkle_proof(bogus_leaf, proof, root) is False


def test_proof_verification_invalid_root_rejected() -> None:
    leaves = _make_leaves(4)
    proof = merkle_proof(leaves, 2)
    bogus_root = _sha(b"wrong-root")
    assert verify_merkle_proof(leaves[2], proof, bogus_root) is False


# ---------------------------------------------------------------------------
# Additional self-motivated tests
# ---------------------------------------------------------------------------


def test_compute_inner_hash_rejects_bad_length() -> None:
    with pytest.raises(ValueError):
        compute_inner_hash(b"\x00" * 31, b"\x00" * 32)
    with pytest.raises(ValueError):
        compute_inner_hash(b"\x00" * 32, b"\x00" * 33)


def test_build_merkle_tree_rejects_non_32_byte_leaf() -> None:
    with pytest.raises(ValueError):
        build_merkle_tree([b"\x00" * 32, b"too-short"])


def test_root_hash_matches_build_merkle_tree() -> None:
    leaves = _make_leaves(7)
    root, _ = build_merkle_tree(leaves)
    assert root_hash(leaves) == root


def test_leaf_hash_wrapper_is_plain_sha256() -> None:
    payload = b"already-canonicalised"
    assert leaf_hash(payload) == hashlib.sha256(payload).digest()


def test_merkle_proof_index_out_of_range() -> None:
    leaves = _make_leaves(4)
    with pytest.raises(IndexError):
        merkle_proof(leaves, 4)
    with pytest.raises(IndexError):
        merkle_proof(leaves, -1)


def test_verify_proof_rejects_bad_direction_marker() -> None:
    leaves = _make_leaves(2)
    root, _ = build_merkle_tree(leaves)
    bogus_proof = [(leaves[1], "X")]  # invalid direction
    assert verify_merkle_proof(leaves[0], bogus_proof, root) is False


def test_odd_at_intermediate_level_duplicates() -> None:
    """5 leaves: lvl0 grows to 6 (dup leaves[4]); lvl1 has 3 entries
    which then duplicates again to 4 entries before producing 2."""
    leaves = _make_leaves(5)
    root, levels = build_merkle_tree(leaves)
    assert [len(level) for level in levels] == [6, 4, 2, 1]
    # Walk it manually.
    padded0 = [leaves[0], leaves[1], leaves[2], leaves[3], leaves[4], leaves[4]]
    assert levels[0] == padded0
    lvl1 = [_sha(padded0[i] + padded0[i + 1]) for i in range(0, 6, 2)]
    padded1 = lvl1 + [lvl1[-1]]
    assert levels[1] == padded1
    lvl2 = [_sha(padded1[i] + padded1[i + 1]) for i in range(0, 4, 2)]
    assert levels[2] == lvl2
    assert root == _sha(lvl2[0] + lvl2[1])


def test_proof_round_trip_for_odd_tree() -> None:
    """Inclusion proof must hold even when intermediate padding kicks in."""
    leaves = _make_leaves(5)
    root, _ = build_merkle_tree(leaves)
    for idx in range(len(leaves)):
        proof = merkle_proof(leaves, idx)
        assert verify_merkle_proof(leaves[idx], proof, root) is True
