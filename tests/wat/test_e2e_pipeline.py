# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""End-to-end pipeline tests for the WAT hourly anchor flow.

These tests stitch together the three console scripts that form the
hourly contract:

- ``wakir-merkle build`` (BSL 1.1, ``wat.cmd.aggregator_cli``)
- ``wakir-anchor stamp`` (BSL 1.1, ``wat.cmd.anchor_cli``) — invoked
  via a monkey-patched in-process call rather than a real subprocess
  so the test suite never reaches an OTS calendar
- ``wakir-verify`` (BSL 1.1, ``wat.verify.cli``)

Apache-2.0 license posture mirrors ``test_merkle.py`` and
``test_verify.py``: the implementations under test are BSL 1.1 but
the tests are Apache-2.0 so downstream re-implementers can re-use
the vectors against an independent code base.

The build CLI is exercised as a real subprocess (``python -m
wat.cmd.aggregator_cli``) so the argparse plumbing, exit codes and
file I/O are all on the hot path. The anchor stamp call is
monkey-patched at the function-level inside the verify run because
hitting public OTS calendars from CI is a recipe for flaky tests
and rate-limiting.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

from wat.merkle.aggregator import build_merkle_tree, compute_leaf_hash
from wat.verify import cli as verify_cli


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int) -> Dict[str, str]:
    """Synthetic event with the four B1-consensus fields."""
    return {
        "event_id": f"evt-{idx:04d}",
        "time": f"2026-05-06T17:{idx:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Materialise a JSONL spool. Empty list yields a zero-byte file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _run_build(
    *,
    hour: str,
    input_events: Path,
    output_manifest: Path,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m wat.cmd.aggregator_cli build ...`` as a subprocess.

    Real subprocess (not in-process call) so the argparse surface,
    exit codes and stderr formatting are all exercised exactly the
    way the production cron will hit them.
    """
    return subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.cmd.aggregator_cli",
            "build",
            "--hour",
            hour,
            "--input-events",
            str(input_events),
            "--output-manifest",
            str(output_manifest),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


# ---------------------------------------------------------------------------
# Required-by-task tests
# ---------------------------------------------------------------------------


def test_build_writes_valid_manifest(tmp_path: Path) -> None:
    """Schema-conformant manifest is written for a non-empty hour.

    Asserts the v1 contract documented in ``docs/wat-manifest-spec.md``:
    version, hour_slot, merkle_root (hex, 64 chars), event_count,
    events / leaves with leaf_hash, tree_levels, build_time.
    """
    events = [_make_event(i) for i in range(5)]
    spool = tmp_path / "spool.jsonl"
    manifest_path = tmp_path / "manifest.json"
    _write_jsonl(spool, events)

    result = _run_build(
        hour="2026-05-06T17",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 0, (
        f"build exited {result.returncode}; stderr={result.stderr}"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == "wakir-wat-manifest/v1"
    assert manifest["hour_slot"] == "2026-05-06T17"
    assert manifest["event_count"] == 5
    assert len(manifest["events"]) == 5
    assert len(manifest["leaves"]) == 5
    # ``events`` and ``leaves`` carry the same payload by spec.
    assert manifest["events"] == manifest["leaves"]
    assert isinstance(manifest["merkle_root"], str)
    assert len(manifest["merkle_root"]) == 64
    int(manifest["merkle_root"], 16)  # raises if not hex
    assert manifest["merkle_root"] == manifest["merkle_root"].lower()
    assert manifest["build_time"].endswith("Z")
    # tree_levels[-1] is the single-element root list.
    assert len(manifest["tree_levels"]) >= 1
    assert manifest["tree_levels"][-1] == [manifest["merkle_root"]]
    # Every event entry carries the four B1 fields plus leaf_hash.
    for entry in manifest["events"]:
        for field in ("event_id", "time", "payload_hash", "capability_token_hash", "leaf_hash"):
            assert field in entry, f"event entry missing {field}"
        assert len(entry["leaf_hash"]) == 64
        recomputed = compute_leaf_hash(
            event_id=entry["event_id"],
            time=entry["time"],
            payload_hash=entry["payload_hash"],
            capability_token_hash=entry["capability_token_hash"],
        )
        assert entry["leaf_hash"] == recomputed.hex()


def test_build_empty_input_skips_anchor(tmp_path: Path) -> None:
    """Empty hour yields a manifest with merkle_root null and no anchor.

    Two cases exercised: a zero-byte spool (the cron's ``test -s``
    short-circuits this in production but the CLI is the safety net)
    and a spool consisting only of blank lines (operator-edited file).
    """
    spool = tmp_path / "empty.jsonl"
    spool.touch()
    manifest_path = tmp_path / "empty-manifest.json"

    result = _run_build(
        hour="2026-05-06T18",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["merkle_root"] is None
    assert manifest["event_count"] == 0
    assert manifest["events"] == []
    assert manifest["leaves"] == []
    assert manifest["tree_levels"] == []
    assert manifest["version"] == "wakir-wat-manifest/v1"

    # Whitespace-only spool -> same outcome.
    blank = tmp_path / "blank.jsonl"
    blank.write_text("\n\n   \n", encoding="utf-8")
    blank_manifest = tmp_path / "blank-manifest.json"
    result_blank = _run_build(
        hour="2026-05-06T19",
        input_events=blank,
        output_manifest=blank_manifest,
    )
    assert result_blank.returncode == 0
    blank_data = json.loads(blank_manifest.read_text(encoding="utf-8"))
    assert blank_data["merkle_root"] is None
    assert blank_data["event_count"] == 0


def test_verify_reads_build_output(tmp_path: Path) -> None:
    """Round-trip: build a manifest, then verify an event in it.

    The OTS receipt is faked (a non-empty placeholder file) and
    ``verify_receipt`` is monkey-patched to return True so the
    Bitcoin attestation step does not reach a real calendar.
    """
    events = [_make_event(i) for i in range(8)]
    archive = tmp_path / "archive"
    hour_slot = "2026-05-06T20"
    hour_dir = archive / hour_slot
    spool = tmp_path / "spool.jsonl"
    manifest_path = hour_dir / "manifest.json"

    _write_jsonl(spool, events)

    result = _run_build(
        hour=hour_slot,
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 0

    # Materialise the OTS-side artefacts the verifier expects: root.bin
    # plus a non-empty placeholder receipt file. The actual byte
    # content of the receipt is irrelevant because verify_receipt is
    # patched.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_bytes = bytes.fromhex(manifest["merkle_root"])
    (hour_dir / "root.bin").write_bytes(root_bytes)
    (hour_dir / "root.bin.ots").write_bytes(b"\xfd" + b"\x00" * 31)

    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        verify_result = verify_cli.verify_event("evt-0003", archive)

    assert verify_result.verification_status == "verified"
    assert verify_result.event_id == "evt-0003"
    assert verify_result.hour_slot == hour_slot
    assert verify_result.merkle_root == manifest["merkle_root"]


def test_build_event_sorting_deterministic(tmp_path: Path) -> None:
    """Two spools with identical events but different order yield the
    same Merkle root.

    Sorting at build time is the deterministic-Merkle-root contract;
    if it ever regresses, two operators replaying the same hour will
    anchor different roots and downstream proofs will fail.
    """
    events = [_make_event(i) for i in range(7)]

    spool_a = tmp_path / "a.jsonl"
    spool_b = tmp_path / "b.jsonl"
    _write_jsonl(spool_a, events)
    _write_jsonl(spool_b, list(reversed(events)))

    manifest_a = tmp_path / "manifest-a.json"
    manifest_b = tmp_path / "manifest-b.json"
    assert _run_build(
        hour="2026-05-06T21", input_events=spool_a, output_manifest=manifest_a
    ).returncode == 0
    assert _run_build(
        hour="2026-05-06T21", input_events=spool_b, output_manifest=manifest_b
    ).returncode == 0

    data_a = json.loads(manifest_a.read_text(encoding="utf-8"))
    data_b = json.loads(manifest_b.read_text(encoding="utf-8"))
    assert data_a["merkle_root"] == data_b["merkle_root"]
    # Event entries land in the same canonical (sorted-by-event_id) order.
    assert [e["event_id"] for e in data_a["events"]] == [
        e["event_id"] for e in data_b["events"]
    ]

    # Independent re-derivation: hash the manifest's leaf entries with
    # the public leaf-hash function and rebuild the tree; compare to
    # the manifest-claimed root.
    leaves = [
        compute_leaf_hash(
            event_id=e["event_id"],
            time=e["time"],
            payload_hash=e["payload_hash"],
            capability_token_hash=e["capability_token_hash"],
        )
        for e in data_a["events"]
    ]
    rebuilt_root, _levels = build_merkle_tree(leaves)
    assert rebuilt_root.hex() == data_a["merkle_root"]


def test_build_validates_4_field_input(tmp_path: Path) -> None:
    """An input event missing a B1 field is rejected with exit code 2.

    Both the missing-field case and the wrong-type case should
    surface as ``ValidationError`` (exit code 2) with a clear stderr
    message naming the offending event index and field.
    """
    # Missing capability_token_hash on event[1].
    events: List[Dict[str, Any]] = [
        _make_event(0),
        {
            "event_id": "evt-0001",
            "time": "2026-05-06T22:01:00Z",
            "payload_hash": "ab" * 32,
            # capability_token_hash deliberately missing
        },
    ]
    spool = tmp_path / "spool.jsonl"
    _write_jsonl(spool, events)
    manifest_path = tmp_path / "manifest.json"

    result = _run_build(
        hour="2026-05-06T22",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 2
    assert "capability_token_hash" in result.stderr
    assert "event[1]" in result.stderr or "missing" in result.stderr
    # No manifest written on validation failure.
    assert not manifest_path.exists()

    # Wrong-type case: payload_hash is an int rather than a string.
    bad_type_events = [
        {
            "event_id": "evt-0000",
            "time": "2026-05-06T23:00:00Z",
            "payload_hash": 12345,  # not a string
            "capability_token_hash": "00" * 32,
        }
    ]
    spool_type = tmp_path / "type.jsonl"
    _write_jsonl(spool_type, bad_type_events)
    manifest_type = tmp_path / "manifest-type.json"

    result_type = _run_build(
        hour="2026-05-06T23",
        input_events=spool_type,
        output_manifest=manifest_type,
    )
    assert result_type.returncode == 2
    assert "payload_hash" in result_type.stderr


# ---------------------------------------------------------------------------
# Optional: full build -> stamp -> verify round-trip with OTS mocked.
# ---------------------------------------------------------------------------


def test_build_with_anchor_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full build -> stamp -> verify round-trip with OTS subprocesses faked.

    The anchor module shells out to the ``ots`` CLI; this test fakes
    that subprocess at the ``wat.anchor.ots_anchor._run_ots`` boundary
    so the round-trip exercises the real glue code without any
    network call. The verify step then patches ``verify_receipt`` to
    return True (the OTS-CLI-output parsing is covered by anchor tests).
    """
    events = [_make_event(i) for i in range(4)]
    archive = tmp_path / "archive"
    hour_slot = "2026-05-06T15"
    hour_dir = archive / hour_slot
    spool = tmp_path / "spool.jsonl"
    manifest_path = hour_dir / "manifest.json"

    _write_jsonl(spool, events)

    # 1. build via real subprocess.
    build_result = _run_build(
        hour=hour_slot,
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert build_result.returncode == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_hex = manifest["merkle_root"]
    assert root_hex is not None

    # 2. stamp via in-process call with OTS subprocess faked.
    from wat.anchor import ots_anchor
    from wat.cmd import anchor_cli

    class FakeProc:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run_ots(args, **kwargs):  # type: ignore[no-untyped-def]
        # Simulate ``ots stamp`` by writing the .ots receipt next to
        # the root file. The args list ends with the path to the
        # source file; everything before it is calendar config.
        if args[0] == "stamp":
            source_path = Path(args[-1])
            (source_path.parent / (source_path.name + ".ots")).write_bytes(
                b"\xfd" + b"\x00" * 31
            )
            stdout_lines = ["Submitting to remote calendar " + url for url in (
                "https://alice.btc.calendar.opentimestamps.org",
                "https://bob.btc.calendar.opentimestamps.org",
                "https://finney.calendar.eternitywall.com",
                "https://btc.calendar.catallaxy.com",
            )]
            return FakeProc(returncode=0, stdout="\n".join(stdout_lines))
        return FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(ots_anchor, "_run_ots", fake_run_ots)
    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", lambda: "/usr/bin/false")

    rc = anchor_cli.main(
        ["stamp", root_hex, "--out", str(hour_dir), "--min-calendars", "2"]
    )
    assert rc == 0
    assert (hour_dir / "root.bin").exists()
    assert (hour_dir / "root.bin.ots").exists()

    # 3. verify with verify_receipt mocked True.
    with mock.patch.object(verify_cli, "verify_receipt", return_value=True):
        result = verify_cli.verify_event("evt-0002", archive)
    assert result.verification_status == "verified"
    assert result.merkle_root == root_hex
    assert result.hour_slot == hour_slot


# ---------------------------------------------------------------------------
# Defensive coverage
# ---------------------------------------------------------------------------


def test_build_rejects_malformed_jsonl(tmp_path: Path) -> None:
    """A spool with one un-parseable line surfaces line number in stderr."""
    spool = tmp_path / "broken.jsonl"
    spool.write_text(
        json.dumps(_make_event(0)) + "\n"
        + "{not valid json\n"
        + json.dumps(_make_event(2)) + "\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "out.json"

    result = _run_build(
        hour="2026-05-06T14",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 2
    assert "invalid JSON" in result.stderr
    assert ":2:" in result.stderr


def test_build_missing_input_file_returns_2(tmp_path: Path) -> None:
    """A non-existent input path is a validation error, not a crash."""
    result = _run_build(
        hour="2026-05-06T13",
        input_events=tmp_path / "does-not-exist.jsonl",
        output_manifest=tmp_path / "out.json",
    )
    assert result.returncode == 2
    assert "input file not found" in result.stderr
