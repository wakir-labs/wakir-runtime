# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for ``scripts/wat-block-heights-collect.sh``.

The script is bash, not python, but its failure modes matter for the
backfill operator workflow and we want a pytest-runnable regression
gate so the Tag-14 pending-path bug does not creep back in.

Approach: stand up a temporary archive directory with a single fake
``.ots`` receipt and shadow the ``ots`` CLI with a small bash mock on
``PATH``. The mock returns canned ``ots info`` blobs that simulate
either the all-pending state (no ``BitcoinBlockHeaderAttestation``)
or the partially-finalised state (one calendar resolved). We then
assert the script:

1. exits 0 in both states (the original bug had it exit 1 on the
   pending state due to ``set -euo pipefail`` + an empty ``grep``);
2. writes a report file in both states;
3. records the right counts in the report header line and the right
   block heights in the row.

No real OTS calendar traffic; this is hermetic and runs in CI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wat-block-heights-collect.sh"


PENDING_INFO_BLOB = """\
File sha256 hash: 067dcadd6527f0378f319221e6049cd39a4d820d540ab887ff4d24a2b7956c4c
Timestamp:
    verify PendingAttestation('https://alice.btc.calendar.opentimestamps.org')
    verify PendingAttestation('https://bob.btc.calendar.opentimestamps.org')
    verify PendingAttestation('https://btc.calendar.catallaxy.com')
    verify PendingAttestation('https://finney.calendar.eternitywall.com')
"""


FINALISED_INFO_BLOB = """\
File sha256 hash: 067dcadd6527f0378f319221e6049cd39a4d820d540ab887ff4d24a2b7956c4c
Timestamp:
    verify PendingAttestation('https://bob.btc.calendar.opentimestamps.org')
    verify BitcoinBlockHeaderAttestation(948183)
    verify PendingAttestation('https://alice.btc.calendar.opentimestamps.org')
    verify PendingAttestation('https://btc.calendar.catallaxy.com')
    verify PendingAttestation('https://finney.calendar.eternitywall.com')
"""


def _write_mock_ots(mock_dir: Path, info_blob: str, upgrade_exit: int) -> Path:
    """Create a bash ``ots`` shim that emits ``info_blob`` on ``info``.

    ``upgrade`` exits with ``upgrade_exit`` (non-zero models the
    pending-calendar warm-up where the OTS CLI cannot promote the
    receipt yet). Other subcommands fall through to a no-op exit 0.
    """
    mock_dir.mkdir(parents=True, exist_ok=True)
    mock_path = mock_dir / "ots"
    blob_path = mock_dir / "info-blob.txt"
    blob_path.write_text(info_blob, encoding="utf-8")
    # The mock reads the canned blob from disk; that keeps the bash
    # source independent of any escaping we'd otherwise need to do
    # for embedded single quotes / newlines.
    mock_path.write_text(
        "#!/usr/bin/env bash\n"
        f"BLOB_PATH={blob_path!s}\n"
        f"UPGRADE_EXIT={upgrade_exit}\n"
        'case "$1" in\n'
        '  upgrade) exit "$UPGRADE_EXIT" ;;\n'
        '  info)    cat "$BLOB_PATH" ;;\n'
        '  *)       exit 0 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    mock_path.chmod(0o755)
    return mock_path


def _run_script(archive: Path, mock_bin: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the collector with a PATH that picks up the mock first."""
    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(SCRIPT), str(archive)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.fixture
def archive_with_receipt(tmp_path: Path) -> Path:
    """Build a one-hour archive with a placeholder ``root.bin.ots``.

    The mock ``ots`` does not actually look at the file contents — it
    just returns the canned ``info`` blob — so the byte content is
    irrelevant for these tests.
    """
    archive = tmp_path / "wat-archive"
    hour = archive / "2026-05-06T17"
    hour.mkdir(parents=True)
    (hour / "root.bin").write_bytes(b"\x00" * 32)
    (hour / "root.bin.ots").write_bytes(b"\x00")  # placeholder
    return archive


def test_pending_path_exits_zero_and_writes_report(
    archive_with_receipt: Path, tmp_path: Path
) -> None:
    """Tag-14 regression: pending receipts must not kill the script.

    Before the fix, ``set -euo pipefail`` + an empty ``grep`` for
    ``BitcoinBlockHeaderAttestation`` propagated exit 1 out of the
    ``$(...)`` substitution, killing the script before the report
    block ran. We now expect a clean exit 0 with a report on disk.
    """
    mock_bin = tmp_path / "mock-bin"
    _write_mock_ots(mock_bin, PENDING_INFO_BLOB, upgrade_exit=1)

    result = _run_script(archive_with_receipt, mock_bin)

    assert result.returncode == 0, (
        f"expected exit 0 on pending path, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    reports = list((archive_with_receipt / "_reports").glob("block-heights-*.md"))
    assert len(reports) == 1, "expected exactly one report file"
    body = reports[0].read_text(encoding="utf-8")
    assert "finalised 0, still pending 1" in body
    # All four calendars should be listed as pending in the row.
    assert "alice.btc.calendar.opentimestamps.org" in body
    assert "bob.btc.calendar.opentimestamps.org" in body
    assert "catallaxy.com" in body
    assert "finney.calendar.eternitywall.com" in body
    # No bitcoin block height should leak into the row.
    assert "(none)" in body


def test_finalised_path_emits_block_height(
    archive_with_receipt: Path, tmp_path: Path
) -> None:
    """Sanity: finalised path still works after the pending-path fix."""
    mock_bin = tmp_path / "mock-bin"
    _write_mock_ots(mock_bin, FINALISED_INFO_BLOB, upgrade_exit=0)

    result = _run_script(archive_with_receipt, mock_bin)

    assert result.returncode == 0
    reports = list((archive_with_receipt / "_reports").glob("block-heights-*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "finalised 1, still pending 0" in body
    assert "948183" in body


def test_missing_archive_returns_exit_2(tmp_path: Path) -> None:
    """Smoke for the documented exit code table."""
    mock_bin = tmp_path / "mock-bin"
    _write_mock_ots(mock_bin, PENDING_INFO_BLOB, upgrade_exit=0)

    nowhere = tmp_path / "does-not-exist"
    result = _run_script(nowhere, mock_bin)

    assert result.returncode == 2
    assert "does not exist" in (result.stdout + result.stderr)


def test_empty_archive_returns_exit_1(tmp_path: Path) -> None:
    """An archive with no .ots receipts is the documented exit-1 case."""
    if shutil.which("bash") is None:  # pragma: no cover
        pytest.skip("bash not on PATH")
    mock_bin = tmp_path / "mock-bin"
    _write_mock_ots(mock_bin, PENDING_INFO_BLOB, upgrade_exit=0)

    empty = tmp_path / "empty-archive"
    empty.mkdir()
    result = _run_script(empty, mock_bin)

    assert result.returncode == 1
    assert "no .ots receipts found" in (result.stdout + result.stderr)
