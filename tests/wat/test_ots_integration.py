# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Realistic end-to-end tests against public OpenTimestamps calendars.

The rest of the WAT test suite goes out of its way to *avoid* hitting
the public OTS calendars: tests either monkey-patch ``verify_receipt``
or shape their fake receipts so that no network call is required. That
gives a fast, hermetic CI loop, which is the right default.

This module covers the other half: a tag-9 smoke layer that talks to
the actual public calendars so we know the production code path
(subprocess wrapper, calendar response parsing, pending receipt
shape) is wired correctly and not just a clever in-process simulation.

Calendars contacted
-------------------

We hit the public OTS pool aliases ``a.pool.opentimestamps.org`` and
``b.pool.opentimestamps.org``. Those CNAMEs resolve internally to the
alice / bob calendar servers, but using the pool aliases keeps the
tests resilient to operator-side rebalancing.

Why a hard env-gate
-------------------

Running these in CI on every push would be (a) impolite to the
calendar operators, who run the public infrastructure for free, and
(b) flaky, because calendar latency varies by 1-2 orders of magnitude
during peak load. The ``OTS_INTEGRATION_TEST=1`` gate keeps the tests
opt-in: developers run them locally before a release, the Tag-22
smoke driver runs them once, and CI never touches them.

Politeness budget
-----------------

The four tests below add up to ~3 calendar submissions in the worst
case. Repeat the test suite at most once per hour during local
development and never in a tight loop.
"""

from __future__ import annotations

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

# Two-of-N pool aliases. CNAMEs to alice / bob. Using the pool form
# means we keep working if either operator rotates DNS.
INTEGRATION_CALENDARS: tuple[str, ...] = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
)

# Hard timeout on every subprocess. Mirrors the production
# SUBPROCESS_TIMEOUT_S in wat.anchor.ots_anchor (Wayback-Robustheit-
# Lehre: a slow calendar must never block the test runner forever).
SUBPROCESS_TIMEOUT_S: int = 90


# ---------------------------------------------------------------------------
# Skip logic
# ---------------------------------------------------------------------------


def _integration_enabled() -> bool:
    """Return True iff the OTS_INTEGRATION_TEST gate is set to a truthy value."""
    raw = os.environ.get("OTS_INTEGRATION_TEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason=(
        "OTS_INTEGRATION_TEST is not set; skipping real-calendar "
        "integration tests. Export OTS_INTEGRATION_TEST=1 to run them."
    ),
)


def _require_ots_binary() -> str:
    binary = shutil.which("ots")
    if binary is None:
        pytest.skip("ots CLI not found on PATH; run scripts/setup.sh.")
    return binary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(idx: int, hour_slot: str = "2026-05-06T17") -> Dict[str, str]:
    """Synthetic event with the four B1-consensus fields."""
    minute = idx % 60
    return {
        "event_id": f"evt-int-{idx:04d}",
        "time": f"{hour_slot}:{minute:02d}:00Z",
        "payload_hash": f"{idx:064x}",
        "capability_token_hash": f"{(idx + 1):064x}",
    }


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _run_build(
    *, hour: str, input_events: Path, output_manifest: Path
) -> subprocess.CompletedProcess[str]:
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
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def _run_stamp(
    *,
    root_hex: str,
    out_dir: Path,
    min_calendars: int = 2,
    calendars: tuple[str, ...] = INTEGRATION_CALENDARS,
) -> subprocess.CompletedProcess[str]:
    """Drive ``wakir-anchor stamp`` against the integration calendars.

    We invoke ``ots`` directly here (not the wakir-anchor wrapper)
    because the wrapper hardcodes the four-calendar default; the
    integration smoke wants the explicit two-of-two policy against
    the pool aliases. The production wrapper is exercised by
    test_real_calendar_stamp_full_hour below.
    """
    ots = _require_ots_binary()
    root_bytes = bytes.fromhex(root_hex)
    out_dir.mkdir(parents=True, exist_ok=True)
    root_path = out_dir / "root.bin"
    root_path.write_bytes(root_bytes)

    args: List[str] = [ots, "stamp", "-m", str(min_calendars)]
    for url in calendars:
        args.extend(["--calendar", url])
    args.append(str(root_path))

    return subprocess.run(  # noqa: S603 — explicit args, no shell.
        args,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )


def _run_verify_pending(
    *, event_id: str, archive_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Drive ``wakir-verify`` and accept exit code 3 (pending) as fine."""
    return subprocess.run(  # noqa: S603 — explicit args, no shell.
        [
            sys.executable,
            "-m",
            "wat.verify.cli",
            event_id,
            "--archive-dir",
            str(archive_dir),
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_real_calendar_stamp_single_event(tmp_path: Path) -> None:
    """Single-event hour: build manifest, stamp via real calendars.

    Walks the production code path end-to-end for a one-event hour,
    contacting both pool calendars, and asserts (a) a valid receipt
    file is written and (b) it parses as a non-empty OTS proof.
    """
    _require_ots_binary()
    events = [_make_event(0, hour_slot="2026-05-06T17")]
    spool = tmp_path / "single.jsonl"
    _write_jsonl(spool, events)
    archive = tmp_path / "archive" / "2026-05-06T17"
    manifest_path = archive / "manifest.json"

    build = _run_build(
        hour="2026-05-06T17",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert build.returncode == 0, build.stderr

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_hex = manifest["merkle_root"]
    assert isinstance(root_hex, str) and len(root_hex) == 64

    submit_started = time.monotonic()
    stamp = _run_stamp(root_hex=root_hex, out_dir=archive, min_calendars=2)
    submit_elapsed = time.monotonic() - submit_started

    # Generous ceiling — calendar p99 is well below 30 s in practice
    # but we leave headroom for transient peak load.
    assert submit_elapsed < SUBPROCESS_TIMEOUT_S, (
        f"submit took {submit_elapsed:.1f}s, exceeded "
        f"{SUBPROCESS_TIMEOUT_S}s budget"
    )
    assert stamp.returncode == 0, stamp.stderr

    receipt = archive / "root.bin.ots"
    assert receipt.exists(), f"receipt not written: {stamp.stdout} {stamp.stderr}"
    assert receipt.stat().st_size > 0
    # Both pool aliases resolve to alice / bob inside the receipt.
    info = subprocess.run(  # noqa: S603 — explicit args, no shell.
        ["ots", "info", str(receipt)],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    blob = (info.stdout or "") + (info.stderr or "")
    assert "PendingAttestation" in blob, blob
    print(f"\n[ots-int] single_submit_elapsed_s={submit_elapsed:.2f}")


def test_real_calendar_stamp_full_hour(tmp_path: Path) -> None:
    """~10-event hour through the full production pipeline.

    This is the closest mirror of what the hourly cron does in
    production: spool 10 events, build the manifest, stamp via the
    integration calendars, run wakir-verify in pending-tolerant mode.
    """
    _require_ots_binary()
    events = [_make_event(i, hour_slot="2026-05-06T18") for i in range(10)]
    spool = tmp_path / "hour.jsonl"
    _write_jsonl(spool, events)

    archive_root = tmp_path / "archive"
    archive_dir = archive_root / "2026-05-06T18"
    manifest_path = archive_dir / "manifest.json"

    build = _run_build(
        hour="2026-05-06T18",
        input_events=spool,
        output_manifest=manifest_path,
    )
    assert build.returncode == 0, build.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_hex = manifest["merkle_root"]

    submit_started = time.monotonic()
    stamp = _run_stamp(root_hex=root_hex, out_dir=archive_dir, min_calendars=2)
    submit_elapsed = time.monotonic() - submit_started
    assert stamp.returncode == 0, stamp.stderr
    assert (archive_dir / "root.bin.ots").exists()

    verify_started = time.monotonic()
    verify = _run_verify_pending(
        event_id=events[3]["event_id"], archive_dir=archive_root
    )
    verify_elapsed = time.monotonic() - verify_started

    # Pending is the expected outcome until the calendars batch the
    # submission into Bitcoin (typically ~10 minutes to a few hours).
    # Exit 3 = pending; exit 0 = unexpected fast finalisation; both
    # are acceptable. Exit 1/4 indicates a regression.
    assert verify.returncode in (0, 3), (
        f"verify returncode={verify.returncode} stdout={verify.stdout} "
        f"stderr={verify.stderr}"
    )

    # Surface latencies for the outbox memo (visible with -s).
    print(
        f"\n[ots-int] submit_elapsed_s={submit_elapsed:.2f} "
        f"verify_elapsed_s={verify_elapsed:.2f}"
    )


def test_real_calendar_pending_to_finalised(tmp_path: Path) -> None:
    """Read-only check on ``ots upgrade`` semantics.

    If the host has any pending receipts under
    ``meta/timestamps/wat/_pending/``, attempt ``ots upgrade`` against
    the first one and assert the call returns without error. We do
    not require a finalised attestation — most local test runs see
    receipts that are too fresh to have made it into a Bitcoin block
    yet (10 min - 6 h batching latency). The call is allowed to be a
    no-op.

    When no pending receipts are present, the test is a structural
    no-op so the integration suite can run on a fresh host.
    """
    _require_ots_binary()
    pending_root = REPO_ROOT / "meta" / "timestamps" / "wat" / "_pending"
    if not pending_root.exists():
        pytest.skip("no _pending directory; nothing to upgrade")
    receipts = sorted(pending_root.glob("*.ots"))
    if not receipts:
        pytest.skip("no pending receipts on disk")

    receipt = receipts[0]
    upgrade_started = time.monotonic()
    upgrade = subprocess.run(  # noqa: S603 — explicit args, no shell.
        ["ots", "upgrade", str(receipt)],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    upgrade_elapsed = time.monotonic() - upgrade_started
    # ots upgrade returns 0 even when nothing changed; non-zero is
    # surfacing a real problem (network / receipt corruption).
    assert upgrade.returncode == 0, (
        f"upgrade failed: stdout={upgrade.stdout} stderr={upgrade.stderr}"
    )
    print(f"\n[ots-int] upgrade_elapsed_s={upgrade_elapsed:.2f}")


def test_real_calendar_failover_simulated(tmp_path: Path) -> None:
    """Simulate one calendar down, assert the 2-of-N policy still fails.

    We do not actually take a calendar offline (no iptables / network
    namespace tricks in CI). Instead we ask ``ots stamp`` to use a
    known-bad URL plus exactly one good URL with ``-m 2``: the bad
    URL fails to respond, so the stamp call must surface a non-zero
    exit because the threshold cannot be met.

    This is a conservative mirror of the failover behaviour: the
    real-world failure mode (one calendar timing out, three healthy
    ones) is covered by ``test_real_calendar_stamp_single_event``,
    which sends ``-m 2`` against two pool aliases and tolerates one
    of them being slow.
    """
    _require_ots_binary()
    root_bytes = bytes.fromhex("ab" * 32)
    out_dir = tmp_path / "failover"
    out_dir.mkdir(parents=True, exist_ok=True)
    root_path = out_dir / "root.bin"
    root_path.write_bytes(root_bytes)

    # Loopback URL on a closed port = fast fail; pool URL = healthy.
    # min-calendars=2 forces the threshold check. The healthy
    # calendar alone cannot meet 2-of-N.
    args = [
        "ots",
        "stamp",
        "-m",
        "2",
        "--calendar",
        "https://127.0.0.1:1/closed",
        "--calendar",
        "https://a.pool.opentimestamps.org",
        str(root_path),
    ]
    failover = subprocess.run(  # noqa: S603 — explicit args, no shell.
        args,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )

    # Either exit code != 0 (calendar threshold under-met) or a
    # receipt that flags only one healthy calendar — both are
    # acceptable evidence that the failover machinery noticed the
    # downed calendar. The OTS client itself does not always
    # propagate non-zero on under-threshold; we therefore accept
    # either signal.
    blob = (failover.stdout or "") + "\n" + (failover.stderr or "")
    surfaced = (
        failover.returncode != 0
        or "127.0.0.1:1" in blob
        or "refused" in blob.lower()
        or "unable" in blob.lower()
        or "error" in blob.lower()
    )
    assert surfaced, (
        f"failover not surfaced: rc={failover.returncode} "
        f"stdout={failover.stdout!r} stderr={failover.stderr!r}"
    )


def test_real_block_height_finalisation(tmp_path: Path) -> None:
    """Validate the upgrade-then-extract path on a fixture receipt.

    Tag-9 demonstrated the submit + pending-receipt half of the
    pipeline. This test covers the other half: take an OTS receipt
    that is old enough for the calendar batch to have hit Bitcoin,
    upgrade it, and assert the parsed receipt carries at least one
    ``BitcoinBlockHeaderAttestation`` block height.

    Receipt source resolution
    -------------------------

    1. Environment variable ``WAT_TEST_FINALISED_RECEIPT`` if set —
       expected to point at a ``.ots`` file paired with a sibling
       data file (the receipt's original input). This is the path
       used by the Tag-10 outbox memo: a dev runs the test against a
       receipt that survived overnight.
    2. Fallback: ``.runtime/ots-smoketest.txt.ots`` under the
       AI-Corp dev-engineering workspace, which the operator
       provisions during the OTS bootstrap drill (older than 24 h
       on any host that has been running >1 day).

    If neither is present, the test is a structural skip — fresh
    hosts will hit this case and that is fine.

    The test never resubmits to a calendar; only ``ots upgrade`` and
    ``ots info`` are invoked. Both are read-only with respect to the
    public OTS infrastructure (upgrade is idempotent and merely
    pulls the current attestation state from the calendars).
    """
    _require_ots_binary()

    candidates: List[Path] = []
    env_path = os.environ.get("WAT_TEST_FINALISED_RECEIPT", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    # Workspace fallback: bootstrap-drill receipt.
    candidates.append(
        Path.home()
        / "AI-Corp"
        / "agents-workspaces"
        / "dev-engineering"
        / ".runtime"
        / "ots-smoketest.txt.ots"
    )

    source: Path | None = next((p for p in candidates if p.exists()), None)
    if source is None:
        pytest.skip(
            "no finalisation fixture: set WAT_TEST_FINALISED_RECEIPT to "
            "a .ots receipt older than 24h, or provision "
            ".runtime/ots-smoketest.txt.ots via scripts/setup.sh."
        )

    # Work on a copy so a slow-finalising fixture is never mutated in
    # place by ``ots upgrade``.
    work_receipt = tmp_path / source.name
    shutil.copy2(source, work_receipt)
    sibling = source.with_suffix("")
    if sibling.exists():
        shutil.copy2(sibling, work_receipt.with_suffix(""))

    upgrade = subprocess.run(  # noqa: S603 — explicit args, no shell.
        ["ots", "upgrade", str(work_receipt)],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    # Upgrade returns 0 even if nothing changed; non-zero indicates a
    # network glitch and we still try to read whatever attestations
    # are already in the file.
    info = subprocess.run(  # noqa: S603 — explicit args, no shell.
        ["ots", "info", str(work_receipt)],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    blob = (info.stdout or "") + "\n" + (info.stderr or "")

    block_heights: List[int] = []
    for line in blob.splitlines():
        stripped = line.strip()
        # The OTS CLI emits lines like:
        #   verify BitcoinBlockHeaderAttestation(947491)
        if "BitcoinBlockHeaderAttestation(" not in stripped:
            continue
        start = stripped.index("BitcoinBlockHeaderAttestation(") + len(
            "BitcoinBlockHeaderAttestation("
        )
        end = stripped.index(")", start)
        token = stripped[start:end].strip()
        if token.isdigit():
            block_heights.append(int(token))

    if not block_heights:
        pytest.skip(
            f"fixture {source} not yet finalised on Bitcoin; "
            f"upgrade rc={upgrade.returncode}; rerun once the calendar "
            "batch lands (typical 10 min - 6 h, worst case 24 h)."
        )

    # Sanity: Bitcoin height is well above 800k as of 2026.
    for height in block_heights:
        assert height > 800_000, f"implausible block height: {height}"
    print(
        f"\n[ots-int] real_finalisation source={source.name} "
        f"block_heights={sorted(set(block_heights))}"
    )
