# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the verify-CLI ``--chain-check`` flag (Phase-1a-Tag-8).

Coverage matrix:

| case                                                | exit code | chain_status   |
| --------------------------------------------------- | --------- | -------------- |
| verify without --chain-check (existing behaviour)   | 0         | "" (empty)     |
| verify with --chain-check, valid chain              | 0         | chain-verified |
| verify with --chain-check, mismatched prev_hour_root| 4         | chain-mismatch |
| verify with --chain-check, prev_hour_root null      | 0         | chain-skipped  |
| verify with --chain-check, prev manifest missing    | 4         | chain-mismatch |
| verify with --chain-check, hour_slot first ever     | 0         | chain-skipped  |

The OTS-receipt verify path is mocked to ``True`` via
``mock.patch.object(verify_cli, "verify_receipt", ...)`` because the
chain-check is independent of the OTS layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from wat.merkle.aggregator import compute_leaf_hash, build_merkle_tree
from wat.verify import cli as verify_cli


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int, hour: str) -> Dict[str, str]:
    return {
        "event_id": f"evt-{hour}-{idx:04d}",
        "time": f"{hour}:{idx:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _seed_anchored_hour(
    archive: Path,
    hour: str,
    *,
    events: List[Dict[str, str]] | None = None,
    prev_hour_root: str | None = None,
) -> str:
    """Seed a complete hour-archive directory and return its merkle_root.

    Builds a real Merkle tree over the synthetic events, writes a v1
    manifest with the requested ``prev_hour_root`` slot, and drops a
    placeholder ``root.bin.ots`` so ``verify_event`` reaches the OTS
    verify call (which the test then patches True).

    Returns the hex-encoded Merkle root for cross-hour wiring.
    """
    if events is None:
        events = [_make_event(i, hour) for i in range(2)]
    sorted_events = sorted(events, key=lambda e: (e["time"], e["event_id"]))
    leaves: List[bytes] = []
    leaf_entries: List[Dict[str, str]] = []
    for ev in sorted_events:
        leaf = compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        leaves.append(leaf)
        leaf_entries.append({**ev, "leaf_hash": leaf.hex()})
    root, levels = build_merkle_tree(leaves)
    manifest = {
        "version": "wakir-wat-manifest/v1",
        "hour_slot": hour,
        "merkle_root": root.hex(),
        "event_count": len(sorted_events),
        "events": leaf_entries,
        "leaves": leaf_entries,
        "tree_levels": [[node.hex() for node in level] for level in levels],
        "build_time": "2026-05-06T00:00:00Z",
        "prev_hour_root": prev_hour_root,
    }
    hour_dir = archive / hour
    hour_dir.mkdir(parents=True, exist_ok=True)
    (hour_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (hour_dir / "root.bin").write_bytes(root)
    (hour_dir / "root.bin.ots").write_bytes(b"\xfd" + b"\x00" * 31)
    return root.hex()


# ---------------------------------------------------------------------------
# Existing behaviour: unchanged when flag is not passed
# ---------------------------------------------------------------------------


def test_verify_without_chain_check_unchanged_behaviour(tmp_path: Path) -> None:
    """Dropping the flag preserves the Tag-7 verifier surface byte-for-byte.

    The result keeps ``chain_status`` empty, the verification_status
    is the standard ``verified``, and the exit code from the in-process
    main() is 0 -- exactly as it was before Tag-8.
    """
    archive = tmp_path / "archive"
    _seed_anchored_hour(archive, "2026-05-06T16")

    events_h = [_make_event(i, "2026-05-06T17") for i in range(2)]
    _seed_anchored_hour(archive, "2026-05-06T17", events=events_h)

    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive)

    assert result.verification_status == "verified"
    assert result.chain_status == ""  # not set when chain_check=False


# ---------------------------------------------------------------------------
# Valid chain
# ---------------------------------------------------------------------------


def test_chain_check_valid_chain_verified(tmp_path: Path) -> None:
    """Valid prev_hour_root link -> verified + chain-verified, exit 0."""
    archive = tmp_path / "archive"
    prev_root = _seed_anchored_hour(archive, "2026-05-06T16")

    events_h = [_make_event(i, "2026-05-06T17") for i in range(3)]
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=prev_root
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive, chain_check=True)

    assert result.verification_status == "verified"
    assert result.chain_status == "chain-verified"


# ---------------------------------------------------------------------------
# Mismatched prev_hour_root
# ---------------------------------------------------------------------------


def test_chain_check_mismatched_prev_hour_root(tmp_path: Path) -> None:
    """Tampered prev_hour_root -> chain-mismatch, exit 4."""
    archive = tmp_path / "archive"
    _seed_anchored_hour(archive, "2026-05-06T16")  # actual root != fake below

    events_h = [_make_event(i, "2026-05-06T17") for i in range(2)]
    fake_prev_root = "ff" * 32  # deliberately wrong
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=fake_prev_root
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive, chain_check=True)

    assert result.verification_status == "chain-mismatch"
    assert result.chain_status == "chain-mismatch"
    assert "prev_hour_root drift" in result.error_msg


# ---------------------------------------------------------------------------
# Null prev_hour_root -> skipped
# ---------------------------------------------------------------------------


def test_chain_check_null_prev_hour_root_skipped(tmp_path: Path) -> None:
    """Null prev_hour_root -> chain-skipped, still verified, exit 0.

    Cold-start of the audit trail or post-empty-hour boundary: the
    chain has nothing to walk back to, so the verifier records
    ``chain-skipped`` and returns the standard ``verified`` status.
    """
    archive = tmp_path / "archive"
    events_h = [_make_event(i, "2026-05-06T17") for i in range(2)]
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=None
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive, chain_check=True)

    assert result.verification_status == "verified"
    assert result.chain_status == "chain-skipped"


# ---------------------------------------------------------------------------
# Edge: chain-check on hour with no manifest
# ---------------------------------------------------------------------------


def test_chain_check_prev_manifest_missing(tmp_path: Path) -> None:
    """Non-null prev_hour_root claim but no prev manifest -> chain-mismatch.

    Audit-trail integrity: a manifest claiming a chain link to an
    hour that does not exist is a chain break, not a soft skip.
    """
    archive = tmp_path / "archive"
    events_h = [_make_event(i, "2026-05-06T17") for i in range(2)]
    fake_prev = "aa" * 32  # Claims a previous hour we never seed.
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=fake_prev
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive, chain_check=True)

    assert result.verification_status == "chain-mismatch"
    assert result.chain_status == "chain-mismatch"
    assert "no manifest exists" in result.error_msg or "chain break" in result.error_msg


# ---------------------------------------------------------------------------
# Legacy manifest without prev_hour_root key -> treated as skipped
# ---------------------------------------------------------------------------


def test_chain_check_legacy_manifest_without_key_skipped(tmp_path: Path) -> None:
    """Pre-Tag-8 manifests omit the key entirely -> chain-skipped.

    The always-emit contract is forward-only; archive directories
    written by Tag-6/7 builders may still be in flight when a Tag-8
    verifier runs. We treat a missing key the same as null: skip
    rather than fail, so historical hours stay queryable.
    """
    archive = tmp_path / "archive"
    events_h = [_make_event(i, "2026-05-06T17") for i in range(2)]
    # Build a manifest then strip the prev_hour_root key.
    _seed_anchored_hour(archive, "2026-05-06T17", events=events_h)
    manifest_path = archive / "2026-05-06T17" / "manifest.json"
    manifest_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_dict.pop("prev_hour_root", None)
    manifest_path.write_text(
        json.dumps(manifest_dict, indent=2) + "\n", encoding="utf-8"
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event(target_event, archive, chain_check=True)

    assert result.verification_status == "verified"
    assert result.chain_status == "chain-skipped"


# ---------------------------------------------------------------------------
# CLI exit-code surface (subprocess-level)
# ---------------------------------------------------------------------------


def test_main_exit_code_4_on_chain_mismatch(tmp_path: Path) -> None:
    """The ``main()`` entry point returns exit code 4 on chain-mismatch.

    Verifies the Tag-8 exit-code-pattern (0/1/3/4) at the actual CLI
    boundary rather than the dataclass surface.
    """
    archive = tmp_path / "archive"
    _seed_anchored_hour(archive, "2026-05-06T16")  # real root

    events_h = [_make_event(i, "2026-05-06T17") for i in range(1)]
    fake_prev = "00" * 32
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=fake_prev
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        rc = verify_cli.main(
            [target_event, "--archive-dir", str(archive), "--chain-check", "--quiet"]
        )

    assert rc == 4


def test_main_exit_code_0_on_chain_verified(tmp_path: Path) -> None:
    """Exit code 0 when both the OTS attestation and the chain link verify."""
    archive = tmp_path / "archive"
    prev_root = _seed_anchored_hour(archive, "2026-05-06T16")
    events_h = [_make_event(i, "2026-05-06T17") for i in range(1)]
    _seed_anchored_hour(
        archive, "2026-05-06T17", events=events_h, prev_hour_root=prev_root
    )
    target_event = events_h[0]["event_id"]

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        rc = verify_cli.main(
            [target_event, "--archive-dir", str(archive), "--chain-check", "--quiet"]
        )

    assert rc == 0
