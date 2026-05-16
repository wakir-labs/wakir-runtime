# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the ``wat anchor-receipt`` CLI.

The implementation under test (``wat/cli.py``) is BSL-1.1; these
tests are Apache-2.0 so downstream re-implementers can reuse the
contract vectors.

Contract surface
----------------

PR #116 §5 (Cross-Review-Pflicht für on-VM-CLI) calls out
``wat anchor-receipt`` as a Phase-2 Observability helper. The JSON
schema is fixed at five keys:

    ots_receipt_path, bitcoin_block_height, verifier_state,
    anchor_root_hex, wat_manifest_path

These tests pin both the schema and the state-machine that maps
filesystem artefacts to ``verifier_state``.

Hermetic strategy
-----------------

No subprocess calls. The CLI is invoked via :func:`wat.cli.main`
with ``--no-info-probe`` so the ``ots info`` shell-out path is
short-circuited; ``build_anchor_receipt`` is exercised directly
with ``info_probe=False`` for the same reason. The
``receipt-status.json`` sidecar carries the block-height in the
finalized fixture.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from wat import cli as wat_cli
from wat.cli import (
    AnchorReceiptReport,
    MANIFEST_FILENAME,
    RECEIPT_FILENAME,
    RECEIPT_STATUS_FILENAME,
    VALID_VERIFIER_STATES,
    build_anchor_receipt,
    main as wat_main,
    resolve_latest_hour,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_ROOT_HEX = (
    "deadbeef" * 8  # 32 bytes -> 64 hex chars
)
_OTHER_ROOT_HEX = (
    "cafef00d" * 8
)


def _write_manifest(hour_dir: Path, *, root_hex: str = _ROOT_HEX) -> Path:
    """Write a minimal valid ``manifest.json`` and return its path."""
    hour_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "hour_slot": hour_dir.name,
        "merkle_root": root_hex,
        "event_count": 1,
        "events": [
            {
                "event_id": "evt-test-0001",
                "time": f"{hour_dir.name}:00:00Z",
                "payload_hash": "0" * 64,
                "capability_token_hash": "0" * 64,
            }
        ],
    }
    path = hour_dir / MANIFEST_FILENAME
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_receipt(hour_dir: Path) -> Path:
    """Write a placeholder OTS receipt blob; returns its path."""
    hour_dir.mkdir(parents=True, exist_ok=True)
    path = hour_dir / RECEIPT_FILENAME
    # OTS receipt is binary; the CLI only checks existence, not contents.
    path.write_bytes(b"\x00\x4f\x54\x53receipt-fixture")
    return path


def _write_status_sidecar(
    hour_dir: Path,
    *,
    state: str,
    block_height: int | None,
) -> Path:
    """Write the optional ``receipt-status.json`` sidecar."""
    hour_dir.mkdir(parents=True, exist_ok=True)
    blob: dict[str, Any] = {
        "verifier_state": state,
        "bitcoin_block_height": block_height,
    }
    path = hour_dir / RECEIPT_STATUS_FILENAME
    path.write_text(json.dumps(blob), encoding="utf-8")
    return path


def _capture_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    out = capsys.readouterr().out.strip()
    assert out, "expected JSON output on stdout"
    return json.loads(out)


# ---------------------------------------------------------------------------
# 1. Schema invariant
# ---------------------------------------------------------------------------


def test_anchor_receipt_json_schema_pins_five_keys(tmp_path: Path) -> None:
    """JSON output exposes exactly the PR #116 §5 contract keys."""
    archive = tmp_path / "archive"
    hour = "2026-05-16T14"
    hour_dir = archive / hour
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    _write_status_sidecar(hour_dir, state="finalized", block_height=901234)

    report = build_anchor_receipt(hour_dir, info_probe=False)
    json_blob = report.to_json_dict()
    assert set(json_blob.keys()) == {
        "ots_receipt_path",
        "bitcoin_block_height",
        "verifier_state",
        "anchor_root_hex",
        "wat_manifest_path",
    }


# ---------------------------------------------------------------------------
# 2. Finalized happy-path via sidecar
# ---------------------------------------------------------------------------


def test_anchor_receipt_finalized_via_sidecar(tmp_path: Path) -> None:
    """Sidecar with finalized state populates all five fields correctly."""
    archive = tmp_path / "archive"
    hour = "2026-05-16T14"
    hour_dir = archive / hour
    manifest_path = _write_manifest(hour_dir)
    receipt_path = _write_receipt(hour_dir)
    _write_status_sidecar(hour_dir, state="finalized", block_height=842105)

    report = build_anchor_receipt(hour_dir, info_probe=False)

    assert report.verifier_state == "finalized"
    assert report.bitcoin_block_height == 842105
    assert report.anchor_root_hex == _ROOT_HEX
    assert report.ots_receipt_path == str(receipt_path)
    assert report.wat_manifest_path == str(manifest_path)


# ---------------------------------------------------------------------------
# 3. Pending state: receipt exists, no sidecar, no probe
# ---------------------------------------------------------------------------


def test_anchor_receipt_pending_when_no_sidecar(tmp_path: Path) -> None:
    """Receipt without sidecar and probe disabled -> pending, height None."""
    archive = tmp_path / "archive"
    hour_dir = archive / "2026-05-16T15"
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    # Deliberately no sidecar.

    report = build_anchor_receipt(hour_dir, info_probe=False)
    assert report.verifier_state == "pending"
    assert report.bitcoin_block_height is None
    assert report.anchor_root_hex == _ROOT_HEX
    assert report.ots_receipt_path != ""
    assert report.wat_manifest_path != ""


# ---------------------------------------------------------------------------
# 4. Failed state: no receipt file at all
# ---------------------------------------------------------------------------


def test_anchor_receipt_failed_when_receipt_missing(tmp_path: Path) -> None:
    """Manifest without an OTS receipt yields ``failed`` and empty path."""
    archive = tmp_path / "archive"
    hour_dir = archive / "2026-05-16T16"
    manifest_path = _write_manifest(hour_dir)
    # Intentionally no root.bin.ots.

    report = build_anchor_receipt(hour_dir, info_probe=False)
    assert report.verifier_state == "failed"
    assert report.bitcoin_block_height is None
    assert report.ots_receipt_path == ""
    # Manifest path still surfaced for diagnostics.
    assert report.wat_manifest_path == str(manifest_path)
    assert report.anchor_root_hex == _ROOT_HEX


# ---------------------------------------------------------------------------
# 5. Defensive consistency: finalized declared but no height -> pending
# ---------------------------------------------------------------------------


def test_anchor_receipt_finalized_without_height_downgrades_to_pending(
    tmp_path: Path,
) -> None:
    """A sidecar that says ``finalized`` but has null height is treated as
    inconsistent and downgraded to ``pending`` rather than published.

    This guards against an upgrade-driver bug silently flipping state
    without recording the actual block height; the contract is that
    a ``finalized`` report must always carry an integer height.
    """
    archive = tmp_path / "archive"
    hour_dir = archive / "2026-05-16T17"
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    _write_status_sidecar(hour_dir, state="finalized", block_height=None)

    report = build_anchor_receipt(hour_dir, info_probe=False)
    assert report.verifier_state == "pending"
    assert report.bitcoin_block_height is None


# ---------------------------------------------------------------------------
# 6. CLI dispatch: --hour --json --no-info-probe
# ---------------------------------------------------------------------------


def test_cli_anchor_receipt_hour_json_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``wat anchor-receipt --hour ... --json`` emits JSON and exit 0
    when the hour is finalized."""
    archive = tmp_path / "archive"
    hour = "2026-05-16T18"
    hour_dir = archive / hour
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    _write_status_sidecar(hour_dir, state="finalized", block_height=842500)

    rc = wat_main(
        [
            "anchor-receipt",
            "--hour",
            hour,
            "--archive-dir",
            str(archive),
            "--json",
            "--no-info-probe",
        ]
    )
    assert rc == 0
    blob = _capture_json(capsys)
    assert blob["verifier_state"] == "finalized"
    assert blob["bitcoin_block_height"] == 842500
    assert blob["anchor_root_hex"] == _ROOT_HEX


# ---------------------------------------------------------------------------
# 7. CLI dispatch: --latest picks lexicographically greatest hour
# ---------------------------------------------------------------------------


def test_cli_anchor_receipt_latest_picks_max_hour(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With multiple hour slots present, ``--latest`` returns the most
    recent one and ignores stray non-hour-shaped directories."""
    archive = tmp_path / "archive"

    older = archive / "2026-05-16T11"
    newer = archive / "2026-05-16T19"
    _write_manifest(older, root_hex=_OTHER_ROOT_HEX)
    _write_receipt(older)
    _write_status_sidecar(older, state="finalized", block_height=842000)

    _write_manifest(newer)
    _write_receipt(newer)
    _write_status_sidecar(newer, state="finalized", block_height=842999)

    # Stray non-hour directory must not shadow the latest hour.
    (archive / "_pending").mkdir()
    (archive / "_pending" / "scratch.bin").write_bytes(b"junk")

    latest_slot = resolve_latest_hour(archive)
    assert latest_slot == "2026-05-16T19"

    rc = wat_main(
        [
            "anchor-receipt",
            "--latest",
            "--archive-dir",
            str(archive),
            "--no-info-probe",
        ]
    )
    assert rc == 0
    blob = _capture_json(capsys)
    assert blob["bitcoin_block_height"] == 842999
    assert blob["anchor_root_hex"] == _ROOT_HEX
    assert "2026-05-16T19" in blob["wat_manifest_path"]


# ---------------------------------------------------------------------------
# 8. CLI dispatch: --summary multi-line output, pending exit-code 3
# ---------------------------------------------------------------------------


def test_cli_anchor_receipt_summary_pending_exits_three(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--summary`` produces multi-line human output and exit-code 3
    when the hour is still pending."""
    archive = tmp_path / "archive"
    hour = "2026-05-16T20"
    hour_dir = archive / hour
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    # No sidecar -> pending.

    rc = wat_main(
        [
            "anchor-receipt",
            "--hour",
            hour,
            "--archive-dir",
            str(archive),
            "--summary",
            "--no-info-probe",
        ]
    )
    assert rc == 3
    out = capsys.readouterr().out
    assert "state:" in out
    assert "pending" in out
    assert hour in out
    # JSON markers must not bleed into summary output.
    assert "{" not in out
    assert "}" not in out


# ---------------------------------------------------------------------------
# 9. CLI dispatch: invalid hour format rejected with input-error code
# ---------------------------------------------------------------------------


def test_cli_anchor_receipt_invalid_hour_format_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed hour slots are rejected without filesystem access."""
    archive = tmp_path / "archive"
    archive.mkdir()

    rc = wat_main(
        [
            "anchor-receipt",
            "--hour",
            "2026-5-16T14",  # missing zero-padding
            "--archive-dir",
            str(archive),
            "--no-info-probe",
        ]
    )
    assert rc == 64
    err = capsys.readouterr().err
    assert "YYYY-MM-DDTHH" in err


# ---------------------------------------------------------------------------
# 10. Info-probe path uses subprocess; failure -> pending
# ---------------------------------------------------------------------------


def test_anchor_receipt_info_probe_finalizes_via_subprocess(
    tmp_path: Path,
) -> None:
    """When the sidecar is absent but ``ots info`` returns a Bitcoin
    block-height line, the report finalizes via the subprocess path.

    Both ``shutil.which('ots')`` and ``subprocess.run`` are
    monkey-patched so the test stays hermetic (no real ``ots``
    binary, no network).
    """
    archive = tmp_path / "archive"
    hour_dir = archive / "2026-05-16T21"
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)
    # No sidecar.

    ots_info_output = (
        "File hash: a8b3...\n"
        "Bitcoin block 842777 attests existence as of 2026-05-15 ...\n"
    )

    def _fake_run(cmd, **_kwargs):  # noqa: ARG001 — fixture
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=ots_info_output,
            stderr="",
        )

    with mock.patch.object(wat_cli.shutil, "which", return_value="/usr/bin/ots"):
        with mock.patch.object(wat_cli.subprocess, "run", side_effect=_fake_run):
            report = build_anchor_receipt(hour_dir, info_probe=True)

    assert report.verifier_state == "finalized"
    assert report.bitcoin_block_height == 842777


# ---------------------------------------------------------------------------
# 11. Sidecar contract: invalid verifier_state is ignored, not crashed on
# ---------------------------------------------------------------------------


def test_anchor_receipt_rejects_unknown_sidecar_state(tmp_path: Path) -> None:
    """A sidecar whose ``verifier_state`` is not in the allowed set is
    treated as missing rather than propagated. This is the guard that
    keeps a typo in the upgrade-driver from leaking through the
    operator-facing JSON contract."""
    archive = tmp_path / "archive"
    hour_dir = archive / "2026-05-16T22"
    _write_manifest(hour_dir)
    _write_receipt(hour_dir)

    # Bogus state value.
    (hour_dir / RECEIPT_STATUS_FILENAME).write_text(
        json.dumps(
            {"verifier_state": "anchored", "bitcoin_block_height": 1}
        ),
        encoding="utf-8",
    )

    report = build_anchor_receipt(hour_dir, info_probe=False)
    # Falls back to pending (receipt exists, no probe).
    assert report.verifier_state == "pending"
    assert report.bitcoin_block_height is None
    # And confirm the allow-list still contains exactly the documented
    # states -- a regression to this constant would silently widen the
    # contract.
    assert set(VALID_VERIFIER_STATES) == {"finalized", "pending", "failed"}


# ---------------------------------------------------------------------------
# 12. Dataclass invariant: AnchorReceiptReport is frozen
# ---------------------------------------------------------------------------


def test_anchor_receipt_report_is_frozen() -> None:
    """``AnchorReceiptReport`` must be immutable so callers cannot
    mutate a returned report and re-serialise an inconsistent JSON."""
    report = AnchorReceiptReport(
        ots_receipt_path="/dev/null",
        bitcoin_block_height=1,
        verifier_state="finalized",
        anchor_root_hex=_ROOT_HEX,
        wat_manifest_path="/dev/null",
    )
    with pytest.raises(dataclasses_frozen_exc()):
        report.verifier_state = "pending"  # type: ignore[misc]


def dataclasses_frozen_exc() -> type[BaseException]:
    """Return the exception type raised when assigning to a frozen
    dataclass. Pinned in one helper so test_anchor_receipt_report_is_frozen
    stays readable.
    """
    import dataclasses

    return dataclasses.FrozenInstanceError
