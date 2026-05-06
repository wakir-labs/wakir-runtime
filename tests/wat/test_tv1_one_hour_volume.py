# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-1 — 100-event one-hour volume test against the production pipeline.

This is the runnable mirror of ``docs/wat-tv1-test-plan.md``. It
exercises:

1. synthetic event generation (100 events, fixed hour slot, varied
   capability_token_hash and agent_did fan-out),
2. the production aggregator (``python -m wat.cmd.aggregator_cli``),
3. the ``(time, event_id)`` sort contract from the spool spec sec.4,
4. the production OTS anchor wrapper (``python -m wat.cmd.anchor_cli``),
5. ``wakir-verify`` against a sample of events from the produced
   manifest in pending-tolerant mode (exit 0 or 3).

The test is gated on ``OTS_INTEGRATION_TEST=1`` so CI never touches
the public OTS calendars. One full TV-1 run = 1 calendar submission;
re-running on the same hour slot is harmless (the calendars dedupe
identical roots) but should not be done in tight loops as a courtesy
to the operators.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Fixed slot per docs/wat-tv1-test-plan.md sec.1 — keeps the synthetic
# event stream deterministic across runs so manifest hashes are
# reproducible offline.
TV1_HOUR_SLOT: str = "2026-05-26T17"
TV1_EVENT_COUNT: int = 100
TV1_CAP_TOKENS: tuple[str, ...] = (
    "tv1-cap-A",
    "tv1-cap-B",
    "tv1-cap-C",
    "tv1-cap-D",
    "tv1-cap-E",
)
TV1_AGENT_DIDS: tuple[str, ...] = (
    "did:wakir:tv1-agent-1",
    "did:wakir:tv1-agent-2",
    "did:wakir:tv1-agent-3",
)

SUBPROCESS_TIMEOUT_S: int = 120

# Performance budgets per docs/wat-tv1-test-plan.md sec.3. These are
# soft assertions — we record the elapsed time but only fail on
# pathological values (10x the p95 budget) so single-host noise does
# not trigger spurious test failures.
BUDGET_BUILD_HARD_S: float = 50.0   # 10x the p95 budget of 5s
BUDGET_STAMP_HARD_S: float = 300.0  # 10x the p95 budget of 30s


# ---------------------------------------------------------------------------
# Skip logic — same gate as the rest of the integration suite.
# ---------------------------------------------------------------------------


def _integration_enabled() -> bool:
    raw = os.environ.get("OTS_INTEGRATION_TEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason=(
        "OTS_INTEGRATION_TEST is not set; skipping TV-1 volume test. "
        "Export OTS_INTEGRATION_TEST=1 to run it."
    ),
)


def _require_ots_binary() -> None:
    if shutil.which("ots") is None:
        pytest.skip("ots CLI not found on PATH; run scripts/setup.sh.")


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------


def _hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _generate_tv1_events() -> List[Dict[str, str]]:
    """Generate the deterministic 100-event TV-1 spool.

    Per docs/wat-tv1-test-plan.md sec.1: events span the full hour
    via index-derived (minute, second), payload hashes are computed
    from a stable seed, capability tokens rotate over five
    identities, agent DIDs rotate over three. Sort order at
    generation time is intentionally NOT (time, event_id) so the
    aggregator's sort step has something to do.
    """
    events: List[Dict[str, str]] = []
    for i in range(TV1_EVENT_COUNT):
        minute = (i * 7) % 60   # *7 % 60 is a coprime stride => varied
        second = (i * 13) % 60
        millis = (i * 37) % 1000
        cap_seed = TV1_CAP_TOKENS[i % len(TV1_CAP_TOKENS)]
        did_seed = TV1_AGENT_DIDS[i % len(TV1_AGENT_DIDS)]
        events.append(
            {
                "event_id": f"evt-tv1-{i:04d}",
                "time": (
                    f"{TV1_HOUR_SLOT}:{minute:02d}:{second:02d}"
                    f".{millis:03d}Z"
                ),
                "payload_hash": _hex_sha256(f"tv1-payload-{i}"),
                "capability_token_hash": _hex_sha256(cap_seed),
                "agent_did": did_seed,
            }
        )
    # Deliberately reverse the natural index order so the spool
    # arrives "out of order" and the aggregator must sort it.
    events.reverse()
    return events


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_tv1_one_hour_volume(tmp_path: Path) -> None:
    """Run the TV-1 100-event volume vector end to end."""
    _require_ots_binary()

    # 1. Generate spool, write it to disk.
    events = _generate_tv1_events()
    assert len(events) == TV1_EVENT_COUNT
    spool_path = tmp_path / "tv1.jsonl"
    _write_jsonl(spool_path, events)

    archive_root = tmp_path / "archive"
    hour_dir = archive_root / TV1_HOUR_SLOT
    manifest_path = hour_dir / "manifest.json"

    # 2. Build the manifest via the production aggregator CLI.
    build_started = time.monotonic()
    build = subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.cmd.aggregator_cli",
            "build",
            "--hour",
            TV1_HOUR_SLOT,
            "--input-events",
            str(spool_path),
            "--output-manifest",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    build_elapsed = time.monotonic() - build_started
    assert build.returncode == 0, build.stderr
    assert build_elapsed < BUDGET_BUILD_HARD_S, (
        f"build elapsed {build_elapsed:.2f}s exceeds hard ceiling "
        f"{BUDGET_BUILD_HARD_S}s"
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 3. Acceptance A2: shape of the manifest.
    assert manifest["event_count"] == TV1_EVENT_COUNT
    # tree_levels is a list of levels; ceil(log2(100)) = 7 -> 8 entries
    # counting the leaf level.
    assert len(manifest["tree_levels"]) >= 7, (
        f"tree_levels too shallow: {len(manifest['tree_levels'])}"
    )
    assert len(manifest["merkle_root"]) == 64

    # 4. Sortierungs-Verifikation: events in the manifest must be in
    # (time, event_id) order. Re-compute the expected order from the
    # generator and compare.
    expected_order = [
        ev["event_id"]
        for ev in sorted(events, key=lambda e: (e["time"], e["event_id"]))
    ]
    actual_order = [entry["event_id"] for entry in manifest["events"]]
    assert actual_order == expected_order, (
        "aggregator sort drift: manifest is not in (time, event_id) order"
    )

    # 5. Stamp via the production wrapper. Uses the four default
    # calendars and -m 2 policy.
    root_hex = manifest["merkle_root"]
    stamp_started = time.monotonic()
    stamp = subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.cmd.anchor_cli",
            "stamp",
            root_hex,
            "--out",
            str(hour_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    stamp_elapsed = time.monotonic() - stamp_started
    assert stamp.returncode == 0, (
        f"stamp failed rc={stamp.returncode} stdout={stamp.stdout} "
        f"stderr={stamp.stderr}"
    )
    assert stamp_elapsed < BUDGET_STAMP_HARD_S, (
        f"stamp elapsed {stamp_elapsed:.2f}s exceeds hard ceiling "
        f"{BUDGET_STAMP_HARD_S}s"
    )
    assert (hour_dir / "root.bin.ots").exists()

    # 6. Acceptance A3: verify a sample of 5 events from the manifest.
    # All five MUST be in {0, 3} (finalised or pending). Anything
    # else (1 = bad proof, 4 = chain mismatch) is a hard fail.
    sample_indices = [0, 25, 50, 75, 99]
    sampled_event_ids = [manifest["events"][i]["event_id"] for i in sample_indices]
    verify_codes: List[int] = []
    for event_id in sampled_event_ids:
        verify = subprocess.run(  # noqa: S603 — explicit args, no shell.
            [
                sys.executable,
                "-m",
                "wat.verify.cli",
                event_id,
                "--archive-dir",
                str(archive_root),
                "--quiet",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
            check=False,
        )
        verify_codes.append(verify.returncode)
        assert verify.returncode in (0, 3), (
            f"verify {event_id} rc={verify.returncode} "
            f"stdout={verify.stdout} stderr={verify.stderr}"
        )

    # Surface latencies for the outbox memo (visible with -s).
    print(
        f"\n[tv1] event_count={TV1_EVENT_COUNT} "
        f"build_elapsed_s={build_elapsed:.2f} "
        f"stamp_elapsed_s={stamp_elapsed:.2f} "
        f"verify_rcs={verify_codes}"
    )
