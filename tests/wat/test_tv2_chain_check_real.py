# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-2 — multi-hour chain-check integration test against real OTS calendars.

This is the runnable mirror of ``docs/wat-tv2-test-plan.md``. It
exercises:

1. multi-hour synthetic event generation (``H`` consecutive hour
   slots, 5 events per hour, deterministic shape),
2. the production aggregator (``python -m wat.cmd.aggregator_cli``)
   wiring each subsequent hour to the previous via the
   ``--prev-hour-root`` flag,
3. the production OTS anchor wrapper
   (``python -m wat.cmd.anchor_cli stamp``) submitting one stamp
   per hour to the four default public calendars,
4. the production verify CLI (``python -m wat.verify.cli``) with
   ``--chain-check`` walking each hour back to its predecessor,
5. a negative-path sub-check that rewrites a single
   ``prev_hour_root`` field after the chain is built and confirms
   the verifier surfaces ``chain-mismatch`` with exit code 4.

The test is gated on ``OTS_INTEGRATION_TEST=1`` so default CI never
touches the public OTS calendars. One full TV-2 run = ``H`` calendar
submissions (default H=4 -> 16 calendar requests across the four
default calendars, one stamp per hour). Set ``WAT_TV2_HOURS`` to
override H within the supported range [4, 6].
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

# Fixed window per docs/wat-tv2-test-plan.md sec.1 — the chain
# anchors at 2026-05-27T00 and walks forward H hours.
TV2_BASE_DATE: str = "2026-05-27"
TV2_EVENT_COUNT_PER_HOUR: int = 5
TV2_CAP_TOKENS: tuple[str, ...] = (
    "tv2-cap-0",
    "tv2-cap-1",
    "tv2-cap-2",
)

# Polite-cadence delay between consecutive hour-stamps so the four
# public calendars never see a bursty stream.
INTER_HOUR_SLEEP_S: float = 2.0

# Python subprocess timeouts. The stamp call dominates wall time
# (network round-trip to four calendars); 120s is well above the
# p95 budget from docs/wat-tv1-test-plan.md sec.3.
SUBPROCESS_TIMEOUT_S: int = 120

# Supported chain length. The plan parametrises [4, 6]; values
# outside that range are rejected so a typo does not accidentally
# burn calendar budget.
TV2_MIN_HOURS: int = 4
TV2_MAX_HOURS: int = 6


# ---------------------------------------------------------------------------
# Skip logic — same gate as the rest of the integration suite.
# ---------------------------------------------------------------------------


def _integration_enabled() -> bool:
    raw = os.environ.get("OTS_INTEGRATION_TEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason=(
        "OTS_INTEGRATION_TEST is not set; skipping TV-2 chain-check "
        "test. Export OTS_INTEGRATION_TEST=1 to run it."
    ),
)


def _require_ots_binary() -> None:
    if shutil.which("ots") is None:
        pytest.skip("ots CLI not found on PATH; run scripts/setup.sh.")


def _resolve_chain_length() -> int:
    raw = os.environ.get("WAT_TV2_HOURS", "").strip()
    if not raw:
        return TV2_MIN_HOURS
    try:
        h = int(raw)
    except ValueError:
        pytest.skip(f"WAT_TV2_HOURS={raw!r} not an integer; skipping TV-2.")
    if h < TV2_MIN_HOURS or h > TV2_MAX_HOURS:
        pytest.skip(
            f"WAT_TV2_HOURS={h} outside supported range "
            f"[{TV2_MIN_HOURS}, {TV2_MAX_HOURS}]; skipping TV-2 by policy."
        )
    return h


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------


def _hex_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _hour_slot(h: int) -> str:
    return f"{TV2_BASE_DATE}T{h:02d}"


def _generate_tv2_hour_events(h: int) -> List[Dict[str, str]]:
    """Generate the deterministic 5-event spool for hour-index ``h``.

    Per docs/wat-tv2-test-plan.md sec.1: events are spaced 10 minutes
    apart inside the hour, payload hashes are computed from a stable
    seed, and capability tokens rotate over three identities.
    """
    events: List[Dict[str, str]] = []
    for i in range(TV2_EVENT_COUNT_PER_HOUR):
        cap_seed = TV2_CAP_TOKENS[i % len(TV2_CAP_TOKENS)]
        events.append(
            {
                "event_id": f"evt-tv2-{h:02d}-{i:04d}",
                "time": (
                    f"{TV2_BASE_DATE}T{h:02d}:{i * 10:02d}:00.000Z"
                ),
                "payload_hash": _hex_sha256(f"tv2-h{h}-payload-{i}"),
                "capability_token_hash": _hex_sha256(cap_seed),
            }
        )
    return events


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Aggregator + anchor helpers
# ---------------------------------------------------------------------------


def _build_hour_manifest(
    *,
    hour_slot: str,
    spool_path: Path,
    manifest_path: Path,
    prev_hour_root: str | None,
) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "wat.cmd.aggregator_cli",
        "build",
        "--hour",
        hour_slot,
        "--input-events",
        str(spool_path),
        "--output-manifest",
        str(manifest_path),
    ]
    if prev_hour_root is not None:
        cmd.extend(["--prev-hour-root", prev_hour_root])
    proc = subprocess.run(  # noqa: S603 — explicit args, no shell.
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (
        f"aggregator build failed for {hour_slot}: rc={proc.returncode} "
        f"stderr={proc.stderr}"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _stamp_hour(*, root_hex: str, out_dir: Path) -> None:
    proc = subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.cmd.anchor_cli",
            "stamp",
            root_hex,
            "--out",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, (
        f"anchor stamp failed for root={root_hex[:16]}...: "
        f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}"
    )
    assert (out_dir / "root.bin.ots").exists(), (
        f"expected receipt at {out_dir / 'root.bin.ots'} but none written"
    )


def _verify_with_chain_check(
    *,
    event_id: str,
    archive_dir: Path,
) -> int:
    """Run the verify CLI and return its raw exit code.

    Returns the exit code so the caller can distinguish 0/3/4/1 per
    docs/wat-tv2-test-plan.md sec.4.
    """
    proc = subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.verify.cli",
            event_id,
            "--archive-dir",
            str(archive_dir),
            "--chain-check",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    return proc.returncode


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_tv2_chain_check_real(tmp_path: Path) -> None:
    """Run the TV-2 multi-hour chain-check vector end to end."""
    _require_ots_binary()
    chain_length = _resolve_chain_length()

    archive_root = tmp_path / "archive"
    archive_root.mkdir()

    # Track per-hour Merkle roots to wire prev_hour_root forward and
    # to assert the chain links match byte-for-byte (A3).
    merkle_roots: List[str] = []
    manifests: List[Dict[str, Any]] = []

    # 1. Build + stamp the chain hour by hour.
    for h in range(chain_length):
        slot = _hour_slot(h)
        spool_path = tmp_path / f"tv2-h{h:02d}.jsonl"
        events = _generate_tv2_hour_events(h)
        _write_jsonl(spool_path, events)

        hour_dir = archive_root / slot
        manifest_path = hour_dir / "manifest.json"
        prev_root = merkle_roots[-1] if merkle_roots else None

        manifest = _build_hour_manifest(
            hour_slot=slot,
            spool_path=spool_path,
            manifest_path=manifest_path,
            prev_hour_root=prev_root,
        )
        manifests.append(manifest)
        merkle_roots.append(manifest["merkle_root"])

        # A2: shape of every manifest in the chain.
        assert manifest["version"] == "wakir-wat-manifest/v1", (
            f"hour {slot}: version != v1 -> {manifest['version']!r}"
        )
        assert manifest["event_count"] == TV2_EVENT_COUNT_PER_HOUR
        assert len(manifest["tree_levels"]) >= 3, (
            f"hour {slot}: tree_levels too shallow "
            f"({len(manifest['tree_levels'])} < 3)"
        )
        assert len(manifest["merkle_root"]) == 64

        # Stamp this hour's root on the four default calendars.
        _stamp_hour(root_hex=manifest["merkle_root"], out_dir=hour_dir)

        if h + 1 < chain_length:
            time.sleep(INTER_HOUR_SLEEP_S)

    # A3: prev_hour_root chain links match byte-for-byte.
    assert manifests[0]["prev_hour_root"] is None, (
        "hour 0 must be cold-start (prev_hour_root=null)"
    )
    for h in range(1, chain_length):
        assert manifests[h]["prev_hour_root"] == merkle_roots[h - 1], (
            f"hour {h} prev_hour_root drift: "
            f"manifest={manifests[h]['prev_hour_root']!r} "
            f"expected={merkle_roots[h - 1]!r}"
        )

    # 2. A4: verify a sample event from each non-cold hour with
    # --chain-check. Exit 0 (chain-verified) or 3 (pending) is OK;
    # 1 or 4 is a hard fail in the positive path.
    for h in range(1, chain_length):
        slot = _hour_slot(h)
        sample_event_id = manifests[h]["events"][0]["event_id"]
        rc = _verify_with_chain_check(
            event_id=sample_event_id, archive_dir=archive_root
        )
        assert rc in {0, 3}, (
            f"hour {slot}: verify --chain-check exit={rc} for "
            f"event={sample_event_id} (positive-path expects 0 or 3)"
        )

    # 3. A5: negative-path sub-check. Rewrite hour 2's
    # prev_hour_root to all-ff and confirm the verifier surfaces
    # chain-mismatch (exit 4). The OTS receipt is untouched, so the
    # underlying proof is still valid — only the chain-check surface
    # should fail.
    if chain_length >= 3:
        target_h = 2
        target_slot = _hour_slot(target_h)
        target_manifest_path = archive_root / target_slot / "manifest.json"
        tampered = json.loads(
            target_manifest_path.read_text(encoding="utf-8")
        )
        tampered["prev_hour_root"] = "ff" * 32
        target_manifest_path.write_text(
            json.dumps(tampered, indent=2) + "\n", encoding="utf-8"
        )

        sample_event_id = manifests[target_h]["events"][0]["event_id"]
        rc = _verify_with_chain_check(
            event_id=sample_event_id, archive_dir=archive_root
        )
        assert rc == 4, (
            f"negative-path: verify --chain-check on tampered hour "
            f"{target_slot} expected exit=4 (chain-mismatch), got {rc}"
        )
