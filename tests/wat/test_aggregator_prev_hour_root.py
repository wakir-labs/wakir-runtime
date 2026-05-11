# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the ``--prev-hour-root`` CLI flag and ``wat-hourly.sh``
discovery logic introduced in Phase-1a-Tag-8.

Coverage matrix (consensus marker A5, manifest-spec
"prev_hour_root reservation"):

| case                                            | expected manifest value |
| ----------------------------------------------- | ----------------------- |
| build without ``--prev-hour-root``              | ``null``                |
| build with ``--prev-hour-root <hex>``           | ``<hex>``               |
| empty hour without flag                         | ``null``                |
| empty hour with ``--prev-hour-root <hex>``      | ``<hex>`` (forwarded)   |
| wat-hourly.sh: second hour reads first hour     | first-hour root         |
| wat-hourly.sh: first hour, no prev manifest     | ``null``                |
| wat-hourly.sh: gap (H-1 absent, H-2 present)    | ``null`` (no walk-back) |

The shell-driver tests run the actual ``scripts/wat-hourly.sh`` via
subprocess against tmp-path archives so the discovery logic is on the
hot path. The OTS-anchor step is short-circuited by feeding the driver
empty spools (the merkle-root-null path skips the anchor call).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WAT_HOURLY_SH = REPO_ROOT / "scripts" / "wat-hourly.sh"


def _make_event(idx: int, hour: str = "2026-05-06T17") -> Dict[str, str]:
    """Synthetic event with the four B1-consensus fields, hour-bound time."""
    return {
        "event_id": f"evt-{idx:04d}",
        "time": f"{hour}:{idx:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _write_jsonl(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _run_build(
    *,
    hour: str,
    input_events: Path,
    output_manifest: Path,
    prev_hour_root: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``wakir-merkle build`` as a real subprocess."""
    args = [
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
    ]
    if prev_hour_root is not None:
        args.extend(["--prev-hour-root", prev_hour_root])
    return subprocess.run(  # noqa: S603 — explicit args, no shell.
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


# ---------------------------------------------------------------------------
# Aggregator-CLI flag tests
# ---------------------------------------------------------------------------


def test_build_without_flag_emits_null_prev_hour_root(tmp_path: Path) -> None:
    """Default invocation produces ``"prev_hour_root": null``.

    Manifest-spec v1 says the field is always emitted with ``null``
    default. Previously the writer omitted the key entirely; Tag-8
    flips that to "always present" so v2 verifiers and chain-walkers
    can rely on the field being there.
    """
    events = [_make_event(i) for i in range(3)]
    spool = tmp_path / "spool.jsonl"
    manifest_path = tmp_path / "manifest.json"
    _write_jsonl(spool, events)

    result = _run_build(
        hour="2026-05-06T17",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "prev_hour_root" in manifest, "field must always be present in v1"
    assert manifest["prev_hour_root"] is None


def test_build_with_flag_emits_hex_value(tmp_path: Path) -> None:
    """``--prev-hour-root <hex>`` round-trips byte-for-byte into the manifest."""
    expected_hex = "ab" * 32  # 64-char hex placeholder.
    events = [_make_event(i) for i in range(3)]
    spool = tmp_path / "spool.jsonl"
    manifest_path = tmp_path / "manifest.json"
    _write_jsonl(spool, events)

    result = _run_build(
        hour="2026-05-06T17",
        input_events=spool,
        output_manifest=manifest_path,
        prev_hour_root=expected_hex,
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["prev_hour_root"] == expected_hex


def test_empty_hour_without_flag_emits_null(tmp_path: Path) -> None:
    """Empty hour also gets ``"prev_hour_root": null`` by default."""
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
    assert manifest["prev_hour_root"] is None


def test_empty_hour_with_flag_forwards_value(tmp_path: Path) -> None:
    """Empty hour MAY forward prev_hour_root through (operator choice)."""
    forwarded = "cd" * 32
    spool = tmp_path / "empty.jsonl"
    spool.touch()
    manifest_path = tmp_path / "empty-manifest.json"

    result = _run_build(
        hour="2026-05-06T19",
        input_events=spool,
        output_manifest=manifest_path,
        prev_hour_root=forwarded,
    )
    assert result.returncode == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["merkle_root"] is None
    assert manifest["prev_hour_root"] == forwarded


# ---------------------------------------------------------------------------
# wat-hourly.sh discovery tests
# ---------------------------------------------------------------------------


def _aggregator_cli_invocable() -> bool:
    """Can the test driver invoke the aggregator CLI in *some* way?

    Returns True when EITHER (a) the ``wakir-merkle`` console-script
    is on ``PATH`` (the editable install is active in this venv), OR
    (b) the ``wat.cmd.aggregator_cli`` module is importable in the
    current Python and ``wat-hourly.sh`` can therefore fall back to
    ``python -m wat.cmd.aggregator_cli``. The shell driver was
    hardened to take the fallback path in Sprint-5-Tag-4 (OI-9
    environment-state-fix), so the only environment in which these
    tests cannot run is one where the package source tree is not on
    the Python module path at all — a true install-missing
    environment, not the much more common "venv without editable
    install" environment that container-engineering Sprint-5-Tag-3
    surfaced as a skip-statt-pass drift.

    Anchor for the skip-message: when this returns False the operator
    needs to run ``bash scripts/setup.sh`` (or ``pip install -e .``
    from the repository root) to make the WAT package importable.
    """
    if shutil.which("wakir-merkle") is not None:
        return True
    # Importability check: cheaper than launching a subprocess and
    # gives a deterministic answer about whether ``python -m
    # wat.cmd.aggregator_cli`` will resolve when ``wat-hourly.sh``
    # takes the fallback branch.
    try:
        import wat.cmd.aggregator_cli  # noqa: F401 — existence probe.
    except ImportError:
        return False
    return True


_AGGREGATOR_UNAVAILABLE_REASON = (
    "wat.cmd.aggregator_cli is not importable AND wakir-merkle is "
    "not on PATH; run 'bash scripts/setup.sh' or 'pip install -e .' "
    "from the repository root to activate the editable install "
    "(environment-state anchor — this is not a test-source "
    "regression and not a code-bug; cf. container-engineering "
    "Sprint-5-Tag-3 open-item OI-9)"
)


@pytest.fixture
def hourly_env(tmp_path: Path) -> Dict[str, str]:
    """Set up tmp-path spool/archive and merge into the test env.

    The real ``wat-hourly.sh`` reads ``WAKIR_EVENT_SPOOL``,
    ``WAKIR_RECEIPT_ARCHIVE`` and optionally ``WAKIR_HOUR_OVERRIDE``.
    We let it run end-to-end without an OTS call by feeding it empty
    sealed spools (which short-circuit before ``wakir-anchor stamp``).
    """
    env = os.environ.copy()
    spool_dir = tmp_path / "spool"
    archive_dir = tmp_path / "archive"
    spool_dir.mkdir()
    archive_dir.mkdir()
    env["WAKIR_EVENT_SPOOL"] = str(spool_dir)
    env["WAKIR_RECEIPT_ARCHIVE"] = str(archive_dir)
    env["WAKIR_MIN_CALENDARS"] = "1"
    return env


def _seed_hour_manifest(
    archive: Path,
    hour: str,
    *,
    merkle_root: str | None,
    prev_hour_root: str | None = None,
) -> None:
    """Drop a synthetic manifest into ``<archive>/<hour>/manifest.json``.

    Used to simulate "the previous hour was already anchored" so the
    Tag-8 driver's discovery can pick the root up.
    """
    hour_dir = archive / hour
    hour_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "wakir-wat-manifest/v1",
        "hour_slot": hour,
        "merkle_root": merkle_root,
        "event_count": 0 if merkle_root is None else 1,
        "events": [],
        "leaves": [],
        "tree_levels": [],
        "build_time": "2026-05-06T00:00:00Z",
        "prev_hour_root": prev_hour_root,
    }
    (hour_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


@pytest.mark.skipif(
    not _aggregator_cli_invocable(),
    reason=_AGGREGATOR_UNAVAILABLE_REASON,
)
def test_hourly_driver_picks_up_prev_hour_root(
    tmp_path: Path,
    hourly_env: Dict[str, str],
) -> None:
    """``wat-hourly.sh`` extracts the prev-hour root and forwards it.

    Seed an H-1 manifest with a known root, run the driver for H, and
    assert the H-manifest's ``prev_hour_root`` matches.
    """
    archive = Path(hourly_env["WAKIR_RECEIPT_ARCHIVE"])
    spool = Path(hourly_env["WAKIR_EVENT_SPOOL"])

    expected_prev = "11" * 32
    _seed_hour_manifest(archive, "2026-05-06T16", merkle_root=expected_prev)

    # Seed H spool with two real events so the build path runs.
    h_events = [_make_event(i, hour="2026-05-06T17") for i in range(2)]
    sealed = spool / "2026-05-06T17.jsonl.sealed"
    _write_jsonl(sealed, h_events)

    env = dict(hourly_env)
    env["WAKIR_HOUR_OVERRIDE"] = "2026-05-06T17"

    result = subprocess.run(  # noqa: S603
        ["bash", str(WAT_HOURLY_SH)],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # The driver may exit non-zero at the anchor step (no real OTS
    # binary on CI); we only care about the manifest the build step
    # produced before that.
    h_manifest_path = archive / "2026-05-06T17" / "manifest.json"
    assert h_manifest_path.exists(), (
        f"build step did not produce a manifest; stderr={result.stderr}"
    )
    manifest = json.loads(h_manifest_path.read_text(encoding="utf-8"))
    assert manifest["prev_hour_root"] == expected_prev


@pytest.mark.skipif(
    not _aggregator_cli_invocable(),
    reason=_AGGREGATOR_UNAVAILABLE_REASON,
)
def test_hourly_driver_first_hour_emits_null(
    tmp_path: Path,
    hourly_env: Dict[str, str],
) -> None:
    """First hour (no H-1 manifest) emits ``prev_hour_root: null``.

    Edge case: cold-start of the audit trail. The driver finds no
    previous-hour manifest and falls through to the null default.
    """
    archive = Path(hourly_env["WAKIR_RECEIPT_ARCHIVE"])
    spool = Path(hourly_env["WAKIR_EVENT_SPOOL"])

    h_events = [_make_event(i, hour="2026-05-06T17") for i in range(2)]
    sealed = spool / "2026-05-06T17.jsonl.sealed"
    _write_jsonl(sealed, h_events)

    env = dict(hourly_env)
    env["WAKIR_HOUR_OVERRIDE"] = "2026-05-06T17"

    subprocess.run(  # noqa: S603
        ["bash", str(WAT_HOURLY_SH)],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    h_manifest_path = archive / "2026-05-06T17" / "manifest.json"
    assert h_manifest_path.exists()
    manifest = json.loads(h_manifest_path.read_text(encoding="utf-8"))
    assert manifest["prev_hour_root"] is None


@pytest.mark.skipif(
    not _aggregator_cli_invocable(),
    reason=_AGGREGATOR_UNAVAILABLE_REASON,
)
def test_hourly_driver_gap_emits_null(
    tmp_path: Path,
    hourly_env: Dict[str, str],
) -> None:
    """Gap between hours (H-1 absent, H-2 present) emits ``null``.

    Default Tag-8 decision: a gap is itself an audit signal; the
    driver does NOT walk back further than one hour. The chain breaks
    at the gap, the v2 verifier flags it as a chain boundary, and an
    operator investigates whether the missing hour was empty,
    backfill-pending, or genuinely lost.
    """
    archive = Path(hourly_env["WAKIR_RECEIPT_ARCHIVE"])
    spool = Path(hourly_env["WAKIR_EVENT_SPOOL"])

    # H-2 has a manifest but H-1 does not.
    _seed_hour_manifest(archive, "2026-05-06T15", merkle_root="22" * 32)

    h_events = [_make_event(i, hour="2026-05-06T17") for i in range(1)]
    sealed = spool / "2026-05-06T17.jsonl.sealed"
    _write_jsonl(sealed, h_events)

    env = dict(hourly_env)
    env["WAKIR_HOUR_OVERRIDE"] = "2026-05-06T17"

    subprocess.run(  # noqa: S603
        ["bash", str(WAT_HOURLY_SH)],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    h_manifest_path = archive / "2026-05-06T17" / "manifest.json"
    assert h_manifest_path.exists()
    manifest = json.loads(h_manifest_path.read_text(encoding="utf-8"))
    # Driver did not walk back across the gap.
    assert manifest["prev_hour_root"] is None
