# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-Audit-Writer × WAT-Anchor-Pipeline integration tests.

Phase-2 Sprint-9 Tag-3 (Tomás) — WAT-Production-Hardening.

What Sprint-9 Tag-1 added (PR #19)
----------------------------------

The Doppel-Audit-Trail-Bridge (``wat.anchor.bridge_audit_writer``)
writes every persona-activity event to BOTH the WAT spool AND the
Pre-Framework ``activity-log.md`` atomically. The Tag-1 test surface
proved:

  * Per-call atomicity (rollback on either side's failure).
  * Pre-Framework-Linecount EQUALS WAT-Marker-Anzahl over a 1000-
    event 24h mock-trace.

What this Tag-3 module adds
---------------------------

The integration shape neither Tag-1 nor the existing aggregator/anchor
test suites cover: a bridge-written WAT spool gets aggregated by the
production aggregator into a Merkle root, and the root is anchored
through the (mocked) OTS pipeline. The chain:

  bridge_audit_writer.write_bridge_audit
      -> WAT spool jsonl file (per-persona, per-hour)
      -> wat.cmd.aggregator_cli.build_command
      -> Merkle manifest with merkle_root
      -> wat.anchor.ots_anchor.anchor_root (OTS mocked)
      -> AnchorReceipt

Hardening value: a regression in the LeafRecord schema (e.g. the
bridge adds a 10th field, the aggregator does not read it) would
break the chain. So would a hour-slot-derivation drift between the
bridge and the aggregator. So would a JSONL-line-encoding drift.

This module exercises the chain end-to-end so that the Sprint-9
Tag-1 substrate stays composable with the Phase-1b/2 anchor pipeline
that has been the WAT contract since Sprint-4.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from wat.anchor import ots_anchor
from wat.anchor.bridge_audit_writer import (
    STATUS_OK,
    count_activity_log_lines_for_persona,
    count_wat_markers,
    write_bridge_audit,
)
from wat.anchor.ots_anchor import anchor_root
from wat.cmd.aggregator_cli import build_command


def _completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ots"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _make_stamp_side_effect():
    """Side-effect for ``ots stamp`` — writes a placeholder receipt."""

    def _side(cmd, **kwargs):  # noqa: ARG001
        file_arg = Path(cmd[-1])
        calendars: List[str] = []
        for i, token in enumerate(cmd):
            if token == "--calendar" and i + 1 < len(cmd):
                calendars.append(cmd[i + 1])
        lines = [f"Submitting to remote calendar {url}" for url in calendars]
        if file_arg.exists():
            (file_arg.parent / (file_arg.name + ".ots")).write_bytes(
                b"\xfd" + b"\x00" * 31
            )
        return _completed(stdout="\n".join(lines) + "\n")

    return _side


@pytest.fixture(autouse=True)
def _ots_resolvable() -> None:
    with mock.patch.object(
        ots_anchor.shutil,
        "which",
        return_value="/usr/bin/ots",
    ):
        yield


def _bridge_write_one(
    *,
    spool_root: Path,
    activity_log: Path,
    persona_id: str,
    idx: int,
    action_type: str,
    hour: str,
) -> Dict[str, Any]:
    """Write one event via the bridge and return the canonical leaf dict."""
    minute_offset = idx % 60
    event_time = f"{hour}:{minute_offset:02d}:00Z"
    payload_hash = hashlib.sha256(
        f"{persona_id}-{idx}".encode("utf-8")
    ).hexdigest()
    result = write_bridge_audit(
        persona_id=persona_id,
        action_type=action_type,
        payload_hash=payload_hash,
        metadata={"ref": f"sprint-9-tag-3-integration-{idx}"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time=event_time,
    )
    assert result.status == STATUS_OK, (
        f"bridge write failed: {result.status} / {result.error}"
    )
    return {
        "event_time": event_time,
        "payload_hash": payload_hash,
        "result": result,
    }


def _spool_to_aggregator_input(
    spool_dir: Path,
    out_path: Path,
) -> int:
    """Read all jsonl files in a persona spool dir and emit the
    aggregator-compatible 4-field event lines.

    The aggregator's ``_read_events`` accepts the bridge's 9-field
    LeafRecord directly because it tolerates extra keys per the v1
    additive consensus marker. We re-emit anyway to keep the test
    explicit about which fields the aggregator consumes.
    """
    count = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        for entry in sorted(spool_dir.iterdir()):
            if not entry.name.endswith(".jsonl"):
                continue
            with entry.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    out.write(
                        json.dumps(
                            {
                                "event_id": record["event_id"],
                                "time": record["time"],
                                "payload_hash": record["payload_hash"],
                                "capability_token_hash": record[
                                    "capability_token_hash"
                                ],
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    count += 1
    return count


def test_bridge_writes_compose_with_aggregator_and_anchor(tmp_path: Path) -> None:
    """Full chain: bridge -> spool -> aggregator -> anchor.

    Asserts:
      * Each bridge write produces one WAT-spool marker AND one
        activity-log line (Tag-1 invariant, re-pinned here).
      * The aggregator consumes the spool and emits a 64-hex
        Merkle root.
      * The anchor pipeline accepts the root (via mocked OTS) and
        produces a receipt file.
    """
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text(
        "# AI-Corp Activity Log (test fixture)\n\n",
        encoding="utf-8",
    )

    # Write 6 bridge events for two personas in the same hour.
    hour = "2026-05-13T13"
    written: List[Dict[str, Any]] = []
    for i in range(3):
        written.append(
            _bridge_write_one(
                spool_root=spool_root,
                activity_log=activity_log,
                persona_id="tomas",
                idx=i,
                action_type="pr-open",
                hour=hour,
            )
        )
    for i in range(3):
        written.append(
            _bridge_write_one(
                spool_root=spool_root,
                activity_log=activity_log,
                persona_id="reza",
                idx=i + 10,
                action_type="adr-vote",
                hour=hour,
            )
        )

    # ---- (1) Bridge-side invariants (Tag-1 re-pin) ----
    assert count_wat_markers(spool_root, "tomas") == 3
    assert count_wat_markers(spool_root, "reza") == 3
    assert count_activity_log_lines_for_persona(activity_log, "tomas") == 3
    assert count_activity_log_lines_for_persona(activity_log, "reza") == 3

    # ---- (2) Aggregator consumes the tomas-side spool ----
    aggregator_input = tmp_path / "aggregator-input-tomas.jsonl"
    leaf_count = _spool_to_aggregator_input(
        spool_root / "tomas",
        aggregator_input,
    )
    assert leaf_count == 3

    manifest_path = tmp_path / "manifest-tomas.json"
    manifest = build_command(
        hour=hour,
        input_events=aggregator_input,
        output_manifest=manifest_path,
    )
    assert manifest["event_count"] == 3
    assert isinstance(manifest["merkle_root"], str)
    assert len(manifest["merkle_root"]) == 64
    int(manifest["merkle_root"], 16)  # hex

    # ---- (3) Anchor the root through mocked OTS ----
    anchor_dir = tmp_path / "anchor-tomas"
    stamp_side = _make_stamp_side_effect()
    with mock.patch.object(ots_anchor.subprocess, "run", side_effect=stamp_side):
        receipt = anchor_root(
            merkle_root=bytes.fromhex(manifest["merkle_root"]),
            calendars=[
                "https://alice.test",
                "https://bob.test",
                "https://finney.test",
                "https://catallaxy.test",
            ],
            min_calendars=2,
            target_dir=anchor_dir,
        )

    assert receipt.merkle_root == bytes.fromhex(manifest["merkle_root"])
    assert receipt.receipt_path.exists()
    assert len(receipt.successful_calendars()) == 4


def test_bridge_partial_failure_does_not_corrupt_aggregator_input(
    tmp_path: Path,
) -> None:
    """A rolled-back bridge call MUST NOT leave bytes in the spool that
    a subsequent aggregator run would consume.

    The bridge truncates the WAT-side append on a Pre-Framework
    failure (Tag-1 atomicity). This test proves the truncation leaves
    the spool BYTE-IDENTICAL to its pre-call state — the aggregator
    must see exactly the events that the bridge reported OK on.
    """
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("# log\n", encoding="utf-8")

    hour = "2026-05-13T14"
    # Three successful writes.
    for i in range(3):
        _bridge_write_one(
            spool_root=spool_root,
            activity_log=activity_log,
            persona_id="tomas",
            idx=i,
            action_type="commit",
            hour=hour,
        )

    spool_dir = spool_root / "tomas"
    pre_failure_bytes: Dict[str, bytes] = {
        entry.name: entry.read_bytes() for entry in spool_dir.iterdir()
    }

    # Inject a Pre-Framework failure — the bridge must roll back the
    # WAT-side append.
    result = write_bridge_audit(
        persona_id="tomas",
        action_type="will-fail",
        payload_hash=hashlib.sha256(b"will-fail").hexdigest(),
        metadata={"ref": "rollback-victim"},
        spool_root=spool_root,
        activity_log_path=activity_log,
        event_time=f"{hour}:55:00Z",
        _fail_pre_framework=True,
    )
    assert result.status == "pre-framework-failed"

    post_failure_bytes: Dict[str, bytes] = {
        entry.name: entry.read_bytes() for entry in spool_dir.iterdir()
    }
    assert pre_failure_bytes == post_failure_bytes, (
        "WAT-side rollback was not byte-clean — aggregator would see a "
        "phantom event the bridge claimed had failed"
    )

    # The aggregator now sees exactly 3 events, not 4.
    aggregator_input = tmp_path / "aggregator-input-rb.jsonl"
    leaf_count = _spool_to_aggregator_input(spool_dir, aggregator_input)
    assert leaf_count == 3

    manifest_path = tmp_path / "manifest-rb.json"
    manifest = build_command(
        hour=hour,
        input_events=aggregator_input,
        output_manifest=manifest_path,
    )
    assert manifest["event_count"] == 3
