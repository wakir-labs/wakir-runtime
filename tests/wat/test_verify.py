# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Unit tests for the WAT verification CLI.

The implementation under test is BSL 1.1; the tests are Apache 2.0
so a downstream re-implementer can re-use the vectors against an
independent code base.

Strategy
--------

These tests do not contact real OTS calendars or Bitcoin nodes.
Every call into :mod:`wat.anchor.ots_anchor.verify_receipt` is
patched to return a deterministic boolean. Manifest layouts are
materialised on a per-test ``tmp_path`` so the verifier sees an
honest filesystem rather than mocked ``Path`` objects.

The leaf-hash function is the real one: the proof reconstruction
must produce the same root as the manifest claims, which is the
load-bearing audit invariant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence
from unittest import mock

import pytest

from wat.merkle.aggregator import (
    build_merkle_tree,
    compute_leaf_hash,
    merkle_proof,
    verify_merkle_proof,
)
from wat.verify import cli as verify_cli
from wat.verify.cli import (
    MANIFEST_FILENAME,
    RECEIPT_FILENAME,
    VerificationResult,
    lookup_event_in_hour,
    reconstruct_proof_from_leaves,
    verify_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int) -> Dict[str, str]:
    """Build a synthetic event dict with the four B1 fields."""
    return {
        "event_id": f"evt-{idx:04d}",
        "time": f"2026-05-06T12:{idx:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _write_hour_archive(
    archive_dir: Path,
    hour_slot: str,
    events: Sequence[Dict[str, Any]],
    *,
    write_receipt: bool = True,
    write_root_bin: bool = True,
    block_height: int | None = None,
) -> bytes:
    """Materialise a real per-hour archive directory.

    Returns the manifest's Merkle root bytes so callers can assert
    against it.
    """
    hour_dir = archive_dir / hour_slot
    hour_dir.mkdir(parents=True, exist_ok=True)

    leaves = [
        compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        for ev in events
    ]
    root, _levels = build_merkle_tree(leaves)

    manifest = {
        "hour_slot": hour_slot,
        "merkle_root": root.hex(),
        "event_count": len(events),
        "events": list(events),
        "submission_time": f"{hour_slot}:00:00Z",
    }
    (hour_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    if write_root_bin:
        (hour_dir / "root.bin").write_bytes(root)
    if write_receipt:
        # OTS receipt header byte 0xfd is the standard pending marker;
        # the test never parses it, this just makes the file non-empty.
        (hour_dir / RECEIPT_FILENAME).write_bytes(b"\xfd" + b"\x00" * 31)
    if block_height is not None:
        (hour_dir / "bitcoin_block.txt").write_text(
            f"{block_height}\n",
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------


def test_lookup_event_found(tmp_path: Path) -> None:
    """An event present in the manifest is located and its leaf
    matches the recomputed B1 four-field hash."""
    events = [_make_event(i) for i in range(5)]
    hour_slot = "2026-05-06T12"
    _write_hour_archive(tmp_path, hour_slot, events)

    leaf, all_leaves = lookup_event_in_hour("evt-0002", hour_slot, tmp_path)

    expected_leaf = compute_leaf_hash(
        event_id="evt-0002",
        time=events[2]["time"],
        payload_hash=events[2]["payload_hash"],
        capability_token_hash=events[2]["capability_token_hash"],
    )
    assert leaf == expected_leaf
    assert len(all_leaves) == 5
    assert all_leaves[2] == expected_leaf


def test_lookup_event_not_found_in_hour(tmp_path: Path) -> None:
    """Asking for an event_id that is not in the manifest raises
    LookupError; missing manifest raises FileNotFoundError."""
    events = [_make_event(i) for i in range(3)]
    hour_slot = "2026-05-06T13"
    _write_hour_archive(tmp_path, hour_slot, events)

    with pytest.raises(LookupError, match="not present in hour"):
        lookup_event_in_hour("evt-9999", hour_slot, tmp_path)

    with pytest.raises(FileNotFoundError, match="manifest not found"):
        lookup_event_in_hour("evt-0001", "2026-05-06T99", tmp_path)


def test_reconstruct_proof_first_leaf(tmp_path: Path) -> None:
    """Proof for the first leaf rebuilds to the manifest root."""
    events = [_make_event(i) for i in range(4)]
    hour_slot = "2026-05-06T14"
    root = _write_hour_archive(tmp_path, hour_slot, events)

    leaf, all_leaves = lookup_event_in_hour("evt-0000", hour_slot, tmp_path)
    proof = reconstruct_proof_from_leaves(leaf, all_leaves)

    assert verify_merkle_proof(leaf, proof, root) is True
    # First leaf in a 4-leaf balanced tree has exactly two siblings
    # on the path to the root.
    assert len(proof) == 2


def test_reconstruct_proof_middle_leaf(tmp_path: Path) -> None:
    """Proof for a middle leaf rebuilds to the manifest root."""
    events = [_make_event(i) for i in range(8)]
    hour_slot = "2026-05-06T15"
    root = _write_hour_archive(tmp_path, hour_slot, events)

    leaf, all_leaves = lookup_event_in_hour("evt-0003", hour_slot, tmp_path)
    proof = reconstruct_proof_from_leaves(leaf, all_leaves)

    assert verify_merkle_proof(leaf, proof, root) is True
    # 8 leaves -> 3 levels above the leaf level -> 3 sibling hashes.
    assert len(proof) == 3

    # Negative control: tampering with the leaf must invalidate the proof.
    tampered = bytes((leaf[0] ^ 0xFF,)) + leaf[1:]
    assert verify_merkle_proof(tampered, proof, root) is False


def test_reconstruct_proof_last_leaf_with_duplicate(tmp_path: Path) -> None:
    """Bitcoin-pattern duplication of the trailing leaf at an odd
    level still yields a valid proof for the last leaf."""
    # Five leaves: level 0 has 5 -> duplicate to 6, then 3 -> dup to 4,
    # then 2, then 1. The last leaf is paired with itself at level 0.
    events = [_make_event(i) for i in range(5)]
    hour_slot = "2026-05-06T16"
    root = _write_hour_archive(tmp_path, hour_slot, events)

    leaf, all_leaves = lookup_event_in_hour("evt-0004", hour_slot, tmp_path)
    proof = reconstruct_proof_from_leaves(leaf, all_leaves)

    assert verify_merkle_proof(leaf, proof, root) is True
    # First step's sibling must equal the leaf itself (self-pair).
    assert proof[0][0] == leaf


def test_verify_event_end_to_end_mock_ots(tmp_path: Path) -> None:
    """A full verify_event run against a healthy archive yields a
    'verified' result when OTS verify returns True."""
    events = [_make_event(i) for i in range(6)]
    hour_slot = "2026-05-06T17"
    _write_hour_archive(
        tmp_path,
        hour_slot,
        events,
        block_height=837_421,
    )

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_event("evt-0003", tmp_path)

    assert isinstance(result, VerificationResult)
    assert result.verification_status == "verified"
    assert result.event_id == "evt-0003"
    assert result.hour_slot == hour_slot
    assert result.bitcoin_block_height == 837_421
    assert result.error_msg == ""

    # Pending case: OTS not yet finalised.
    with mock.patch.object(verify_cli, "verify_receipt", return_value=False):
        pending = verify_event("evt-0001", tmp_path)
    assert pending.verification_status == "pending"
    assert pending.merkle_root  # root was located even if OTS pending


def test_verify_event_invalid_archive_dir(tmp_path: Path) -> None:
    """A missing archive root returns a 'failed' result without
    raising — the CLI keeps going so an operator gets a diagnostic."""
    missing = tmp_path / "does-not-exist"
    result = verify_event("evt-anything", missing)

    assert result.verification_status == "failed"
    assert result.event_id == "evt-anything"
    assert "archive directory not found" in result.error_msg
    assert result.merkle_root == ""
    assert result.hour_slot == ""


def test_verify_event_event_not_in_archive(tmp_path: Path) -> None:
    """An event that is in no manifest in the archive returns 'failed'
    with a clear diagnostic and no spurious root."""
    events = [_make_event(i) for i in range(3)]
    _write_hour_archive(tmp_path, "2026-05-06T18", events)
    _write_hour_archive(
        tmp_path,
        "2026-05-06T19",
        [_make_event(i + 100) for i in range(3)],
    )

    result = verify_event("evt-9999", tmp_path)

    assert result.verification_status == "failed"
    assert "not found in any hour manifest" in result.error_msg
    assert result.hour_slot == ""


# ---------------------------------------------------------------------------
# Additional self-motivated tests
# ---------------------------------------------------------------------------


def test_reconstruct_proof_rejects_unknown_leaf(tmp_path: Path) -> None:
    """A leaf that is not in the leaf list raises LookupError."""
    events = [_make_event(i) for i in range(4)]
    hour_slot = "2026-05-06T20"
    _write_hour_archive(tmp_path, hour_slot, events)
    _, all_leaves = lookup_event_in_hour("evt-0000", hour_slot, tmp_path)

    bogus_leaf = b"\xab" * 32
    with pytest.raises(LookupError):
        reconstruct_proof_from_leaves(bogus_leaf, all_leaves)


def test_reconstruct_proof_rejects_wrong_leaf_size() -> None:
    with pytest.raises(ValueError, match="must be 32 bytes"):
        reconstruct_proof_from_leaves(b"too-short", [b"\x00" * 32])


def test_verify_event_corrupt_manifest_root_fails(tmp_path: Path) -> None:
    """If a manifest's stored root does not match the rebuilt-from-events
    root, the CLI flags the hour as failed rather than reporting a fake
    success after running OTS verify."""
    events = [_make_event(i) for i in range(3)]
    hour_slot = "2026-05-06T21"
    _write_hour_archive(tmp_path, hour_slot, events)

    # Tamper with the stored merkle_root after the fact.
    manifest_path = tmp_path / hour_slot / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["merkle_root"] = "00" * 32  # all-zero, definitely wrong
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_event("evt-0001", tmp_path)

    assert result.verification_status == "failed"
    assert "manifest root mismatch" in result.error_msg


def test_main_exit_codes(tmp_path: Path) -> None:
    """The console-script returns 0 for verified, 1 for failed, 3
    for pending — operators script against these codes."""
    events = [_make_event(i) for i in range(2)]
    hour_slot = "2026-05-06T22"
    _write_hour_archive(tmp_path, hour_slot, events)

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        assert verify_cli.main(
            ["evt-0000", "--archive-dir", str(tmp_path), "--quiet"]
        ) == 0

    with mock.patch.object(verify_cli, "verify_receipt", return_value=False):
        assert verify_cli.main(
            ["evt-0000", "--archive-dir", str(tmp_path), "--quiet"]
        ) == 3

    assert verify_cli.main(
        ["evt-not-here", "--archive-dir", str(tmp_path), "--quiet"]
    ) == 1
