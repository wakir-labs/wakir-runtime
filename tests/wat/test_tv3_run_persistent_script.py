# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for ``scripts/wat-tv3-run-persistent.sh``.

The driver is bash and orchestrates a behavioural probe against the
backfill daemon (``wat.anchor.backfill.process_pending_queue``).
Unlike the TV-1/TV-2 drivers, TV-3 does not stamp anything against
public OTS calendars by default — its surface under test is the
soft-window-breach detection logic with deterministically aged
mtimes.

These tests are hermetic: they shadow the aggregator CLI with a
bash mock that writes a stub manifest, and they keep the backfill
probe entirely real (it imports ``wat.anchor.backfill`` and runs
against the synthetic archive). The probe is forced to return a
non-finalised result by re-binding ``upgrade_pending`` inside the
bash heredoc; no public calendar is touched.

Coverage clusters (per Tag-18 mandate):

* deterministic spool generation (1 event, byte-stable);
* submit-cadence pacing via the daily budget file;
* resume path via ``WAT_TV3_RESUME_FROM`` + ``.state.json``;
* missing-state-file recovery (full fresh-run behaviour);
* prev_hour_root semantics (cold-start, single-slot, prev=null).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wat-tv3-run-persistent.sh"


# ---------------------------------------------------------------------------
# Static guards.
# ---------------------------------------------------------------------------


def test_tv3_script_bash_syntax_is_valid() -> None:
    """``bash -n`` must parse the script clean.

    Catches heredoc and arithmetic block typos that would otherwise
    only surface on a live behavioural-probe run.
    """
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_tv3_script_is_executable() -> None:
    """The driver must be marked executable for operator one-liners."""
    mode = SCRIPT.stat().st_mode
    assert mode & 0o111, f"{SCRIPT} should be executable"


# ---------------------------------------------------------------------------
# Mock infrastructure.
#
# The bash driver shells out to ``python3 -m wat.cmd.aggregator_cli``
# to build the manifest, and to ``python3 -m wat.cmd.anchor_cli`` to
# stamp (only when LIVE_STAMP=1). The behavioural probe at step 5 is
# a pure ``python3 -`` heredoc that imports ``wat.anchor.backfill``
# directly — we let that one fall through to the real interpreter.
#
# The mock python3 dispatches on argv:
#
#   * ``-m wat.cmd.aggregator_cli build``: write a stub manifest.json
#     with a deterministic merkle_root derived from the hour slot.
#   * ``-m wat.cmd.anchor_cli stamp``:     write a placeholder
#                                           root.bin.ots in --out dir.
#   * ``-`` and ``-c``:                     fall through to real python.
# ---------------------------------------------------------------------------


def _write_mock_bin(mock_dir: Path, real_python: str) -> None:
    mock_dir.mkdir(parents=True, exist_ok=True)

    ots_shim = mock_dir / "ots"
    ots_shim.write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    ots_shim.chmod(0o755)

    python_shim = mock_dir / "python3"
    python_shim.write_text(
        f"""#!/usr/bin/env bash
REAL_PYTHON={real_python}

# Pass-through for ``python3 -`` (probe + helper heredocs).
if [[ "$1" == "-" ]]; then
    exec "$REAL_PYTHON" "$@"
fi

# Pass-through for ``python3 -c ...`` (inline JSON readers).
if [[ "$1" == "-c" ]]; then
    exec "$REAL_PYTHON" "$@"
fi

# Aggregator: parse args, write stub manifest with a deterministic
# merkle_root derived from the hour slot.
if [[ "$1" == "-m" && "$2" == "wat.cmd.aggregator_cli" ]]; then
    HOUR=""
    OUT_MANIFEST=""
    INPUT_EVENTS=""
    PREV=""
    shift 2
    shift  # subcommand (build)
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --hour)             HOUR="$2"; shift 2 ;;
            --output-manifest)  OUT_MANIFEST="$2"; shift 2 ;;
            --input-events)     INPUT_EVENTS="$2"; shift 2 ;;
            --prev-hour-root)   PREV="$2"; shift 2 ;;
            *)                  shift ;;
        esac
    done
    ROOT=$(printf '%s' "$HOUR" | "$REAL_PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())')
    if [[ -n "$PREV" ]]; then
        printf '{{"version":"wakir-wat-manifest/v1","hour":"%s","merkle_root":"%s","prev_hour_root":"%s","event_count":1,"tree_levels":1}}\\n' \\
            "$HOUR" "$ROOT" "$PREV" > "$OUT_MANIFEST"
    else
        printf '{{"version":"wakir-wat-manifest/v1","hour":"%s","merkle_root":"%s","prev_hour_root":null,"event_count":1,"tree_levels":1}}\\n' \\
            "$HOUR" "$ROOT" > "$OUT_MANIFEST"
    fi
    exit 0
fi

# Anchor: write a placeholder root.bin.ots in --out dir. The
# placeholder is sized to clear the driver's >=700-byte
# persistence sanity check (Tag-25 defect-fix); a real OTS
# pending receipt for a 4-calendar submit measures 800-900 bytes
# in production, so 1024 bytes of deterministic filler matches
# that floor while staying byte-stable across runs.
if [[ "$1" == "-m" && "$2" == "wat.cmd.anchor_cli" ]]; then
    OUT_DIR=""
    shift 2
    shift  # subcommand (stamp)
    shift  # merkle_root positional
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --out) OUT_DIR="$2"; shift 2 ;;
            *)     shift ;;
        esac
    done
    "$REAL_PYTHON" -c "import sys; open(sys.argv[1],'wb').write(b'STUB_OTS_RECEIPT_' + b'\\x00' * 1007)" "$OUT_DIR/root.bin.ots"
    exit 0
fi

# Default fall-through.
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)


def _run_driver(
    mock_bin: Path,
    archive_root: Path | None,
    *,
    env_overrides: dict[str, str] | None = None,
    args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    real_python = subprocess.run(
        ["which", "python3"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _write_mock_bin(mock_bin, real_python)

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:/usr/bin:/bin"
    # Keep PYTHONPATH so the real-python fall-through can import
    # wat.anchor.backfill from the source tree.
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    )
    if env_overrides:
        env.update(env_overrides)

    cmd = ["bash", str(SCRIPT)]
    if args is not None:
        cmd.extend(args)
    elif archive_root is not None:
        cmd.append(str(archive_root))

    return subprocess.run(
        cmd, capture_output=True, text=True, env=env, check=False
    )


# ---------------------------------------------------------------------------
# Cluster 1: deterministic spool generation.
# ---------------------------------------------------------------------------


def test_tv3_default_run_writes_one_event_spool(tmp_path: Path) -> None:
    """End-to-end shape check on the default config.

    Verifies:
    - exit 0,
    - hour-directory present (default 2026-05-26T17),
    - tv3.jsonl has exactly 1 event,
    - manifest.prev_hour_root is null (cold-start),
    - backfill-probe.json captures one breached receipt,
    - summary.txt is written and lists the synthetic root.
    """
    archive = tmp_path / "tv3-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(mock_bin, archive)

    assert result.returncode == 0, (
        f"expected exit 0; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    slot_dir = archive / "2026-05-26T17"
    assert (slot_dir / "tv3.jsonl").exists()
    assert (slot_dir / "manifest.json").exists()
    assert (slot_dir / "root.bin.ots").exists()
    assert (slot_dir / "backfill-probe.json").exists()

    spool = (slot_dir / "tv3.jsonl").read_text().splitlines()
    assert len(spool) == 1, f"expected 1 event, got {len(spool)}"

    manifest = json.loads((slot_dir / "manifest.json").read_text())
    assert manifest["prev_hour_root"] is None, "cold-start must be prev=null"

    probe = json.loads((slot_dir / "backfill-probe.json").read_text())
    assert len(probe["results"]) == 1
    assert probe["results"][0]["soft_window_breached"] is True
    assert probe["results"][0]["age_days"] >= 7.0

    summary = (archive / "summary.txt").read_text().strip()
    assert "hour=2026-05-26T17" in summary
    assert "probe_rc=0" in summary


def test_tv3_event_payload_is_deterministic(tmp_path: Path) -> None:
    """Two runs with the same config produce byte-identical spools.

    The spool is the byte-stable input to the aggregator; drift here
    would surface as a different Merkle root downstream.
    """
    mock_bin = tmp_path / "mock-bin"
    archive_a = tmp_path / "run-a"
    archive_b = tmp_path / "run-b"

    rc_a = _run_driver(mock_bin, archive_a).returncode
    rc_b = _run_driver(mock_bin, archive_b).returncode
    assert rc_a == 0 and rc_b == 0

    a = (archive_a / "2026-05-26T17" / "tv3.jsonl").read_bytes()
    b = (archive_b / "2026-05-26T17" / "tv3.jsonl").read_bytes()
    assert a == b, "spool drift between identical runs"


def test_tv3_invalid_hour_base_is_rejected(tmp_path: Path) -> None:
    """``WAT_TV3_HOUR_BASE`` must match the YYYY-MM-DDTHH shape."""
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={"WAT_TV3_HOUR_BASE": "not-a-date"},
    )

    assert result.returncode == 1
    assert "WAT_TV3_HOUR_BASE=not-a-date" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Cluster 2: submit-cadence pacing (daily budget).
# ---------------------------------------------------------------------------


def test_tv3_live_stamp_off_by_default_skips_budget(tmp_path: Path) -> None:
    """Default LIVE_STAMP=0: budget file is never touched."""
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    result = _run_driver(mock_bin, archive)
    assert result.returncode == 0
    summary = (archive / "summary.txt").read_text()
    assert "stamp_rc=skipped" in summary


def test_tv3_live_stamp_within_budget_succeeds(tmp_path: Path) -> None:
    """LIVE_STAMP=1 with budget=4 and used=0 stamps OK and bumps the budget.

    Test isolation: ``WAT_TV3_BUDGET_FILE`` is pointed at a tmp_path
    location so concurrent / pre-existing repo-root budget state
    cannot poison the assertion. Driver supports the override since
    Tag-20 (2026-05-07).
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    budget_file = tmp_path / "isolated-budget.json"

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={
            "WAT_TV3_LIVE_STAMP": "1",
            "WAT_TV3_BUDGET_FILE": str(budget_file),
        },
    )
    assert result.returncode == 0, (
        f"unexpected rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "[budget]" in combined
    assert "OK" in combined
    # The isolated budget file should now hold today's count = 1.
    assert budget_file.exists(), "budget file was not created at the override path"
    parsed = json.loads(budget_file.read_text())
    assert sum(parsed.values()) == 1, (
        f"expected budget file to record one submit; got {parsed}"
    )


def test_tv3_live_stamp_budget_breach_returns_exit_6(tmp_path: Path) -> None:
    """Pre-populating the budget file at the day's limit forces exit 6.

    Test isolation: budget file lives at ``WAT_TV3_BUDGET_FILE``
    (tmp_path), pre-filled at the cap for the next 30 UTC days so
    whichever date the script reads, the cap is breached. No repo-
    root mutation, no concurrent-test interference.
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    budget_path = tmp_path / "isolated-budget.json"

    import datetime as dt

    today = dt.datetime.now(tz=dt.timezone.utc).date()
    prefill = {
        (today + dt.timedelta(days=i)).isoformat(): 4 for i in range(30)
    }
    budget_path.write_text(json.dumps(prefill, sort_keys=True))

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={
            "WAT_TV3_LIVE_STAMP": "1",
            "WAT_TV3_DAILY_SUBMIT_BUDGET": "4",
            "WAT_TV3_BUDGET_FILE": str(budget_path),
        },
    )

    assert result.returncode == 6, (
        f"expected exit 6 (budget breach); got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "REFUSE" in (result.stdout + result.stderr) or "budget" in (
        result.stdout + result.stderr
    )


# ---------------------------------------------------------------------------
# Cluster 3: resume path.
# ---------------------------------------------------------------------------


def test_tv3_resume_skips_completed_steps(tmp_path: Path) -> None:
    """A second invocation with WAT_TV3_RESUME_FROM reuses prior state.

    We run the driver once to completion, capture mtimes of the
    spool/manifest files, then re-run pointing at the same archive
    and assert the files were NOT regenerated (mtime unchanged).
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    rc1 = _run_driver(mock_bin, archive).returncode
    assert rc1 == 0

    spool = archive / "2026-05-26T17" / "tv3.jsonl"
    manifest = archive / "2026-05-26T17" / "manifest.json"
    spool_mtime_before = spool.stat().st_mtime
    manifest_mtime_before = manifest.stat().st_mtime

    rc2 = _run_driver(
        mock_bin,
        archive_root=None,
        env_overrides={"WAT_TV3_RESUME_FROM": str(archive)},
    ).returncode
    assert rc2 == 0

    assert spool.stat().st_mtime == spool_mtime_before, "spool was regenerated"
    assert manifest.stat().st_mtime == manifest_mtime_before, (
        "manifest was rebuilt"
    )


def test_tv3_resume_logs_skip_messages(tmp_path: Path) -> None:
    """The resume run logs ``skipping (resume)`` for each completed step."""
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    rc1 = _run_driver(mock_bin, archive).returncode
    assert rc1 == 0

    result2 = _run_driver(
        mock_bin,
        archive_root=None,
        env_overrides={"WAT_TV3_RESUME_FROM": str(archive)},
    )
    assert result2.returncode == 0
    out = result2.stdout + result2.stderr
    assert "spool already done" in out
    assert "manifest already built" in out
    assert "receipt already placed" in out
    assert "receipt already aged" in out


# ---------------------------------------------------------------------------
# Cluster 4: missing-state-file recovery.
# ---------------------------------------------------------------------------


def test_tv3_missing_state_file_treated_as_fresh_run(tmp_path: Path) -> None:
    """Without a ``.state.json``, all six steps execute from scratch."""
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    result = _run_driver(mock_bin, archive)
    assert result.returncode == 0
    out = result.stdout + result.stderr
    assert "step 1/6: generating synthetic 1-event spool" in out
    assert "step 2/6: building manifest" in out
    assert "step 4/6: aging receipt mtime" in out
    # State file should now exist with five steps recorded
    # (probe is recorded only on success).
    state = json.loads((archive / ".state.json").read_text())
    assert "spool" in state["steps_done"]
    assert "manifest" in state["steps_done"]
    assert "receipt" in state["steps_done"]
    assert "aged" in state["steps_done"]
    assert "probe" in state["steps_done"]


def test_tv3_corrupt_state_file_returns_exit_5(tmp_path: Path) -> None:
    """A malformed ``.state.json`` aborts the resume with exit 5."""
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    archive.mkdir()
    (archive / ".state.json").write_text("{not valid json")

    result = _run_driver(
        mock_bin,
        archive_root=None,
        env_overrides={"WAT_TV3_RESUME_FROM": str(archive)},
    )
    assert result.returncode == 5
    assert "malformed" in (result.stdout + result.stderr)


def test_tv3_resume_from_missing_dir_returns_exit_5(tmp_path: Path) -> None:
    """``WAT_TV3_RESUME_FROM=<missing>`` aborts cleanly with exit 5."""
    mock_bin = tmp_path / "mock-bin"
    missing = tmp_path / "nonexistent-archive"

    result = _run_driver(
        mock_bin,
        archive_root=None,
        env_overrides={"WAT_TV3_RESUME_FROM": str(missing)},
    )
    assert result.returncode == 5
    assert "does not exist" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# Cluster 5: prev_hour_root semantics (TV-3 is single-slot, prev=null).
# ---------------------------------------------------------------------------


def test_tv3_manifest_prev_hour_root_is_null(tmp_path: Path) -> None:
    """TV-3 is by definition single-slot: prev_hour_root must be null.

    This pins the contract that TV-3 does NOT thread a prior root —
    if a future refactor accidentally wires a prev root in, the
    behavioural-probe age math would still work, but the gated
    pytest's manifest cross-check would drift. Pin it here so the
    drift surfaces in script tests.
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"

    rc = _run_driver(mock_bin, archive).returncode
    assert rc == 0

    manifest = json.loads(
        (archive / "2026-05-26T17" / "manifest.json").read_text()
    )
    assert manifest["prev_hour_root"] is None


# ---------------------------------------------------------------------------
# Cluster 6: live-stamp receipt persistence (Tag-25 defect-fix).
#
# Background: in Phase-1b Tag-22 + Tag-24 we discovered that the
# step-3 synthetic marker (``SYNTHETIC_TV3_OTS_RECEIPT``, 25 bytes)
# was still on disk at the path ``ots stamp`` would write the real
# pending receipt to, and ``ots stamp`` does NOT overwrite an
# existing ``root.bin.ots``. The real receipt was silently dropped
# and the archived audit-trail file was the 25-byte synthetic
# marker — which fails downstream ``ots info`` cross-checks.
#
# The driver fix unlinks ``root.bin.ots`` before the live stamp and
# adds a >=700-byte sanity check after it. These two tests pin both
# halves of that contract.
# ---------------------------------------------------------------------------


def test_tv3_live_stamp_receipt_is_not_synthetic_marker(tmp_path: Path) -> None:
    """After a successful live-stamp run, the receipt file must not
    be the 25-byte synthetic marker from step 3.

    Regression for the Tag-22/Tag-24 defect: the synthetic marker
    text ``SYNTHETIC_TV3_OTS_RECEIPT`` may not appear at the head of
    ``root.bin.ots`` after step 6 has run.
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    budget_file = tmp_path / "isolated-budget.json"

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={
            "WAT_TV3_LIVE_STAMP": "1",
            "WAT_TV3_BUDGET_FILE": str(budget_file),
        },
    )
    assert result.returncode == 0, (
        f"unexpected rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )

    receipt = archive / "2026-05-26T17" / "root.bin.ots"
    assert receipt.exists(), "receipt file must exist after live stamp"

    payload = receipt.read_bytes()
    assert b"SYNTHETIC_TV3_OTS_RECEIPT" not in payload[:64], (
        "step-3 synthetic marker still present at head of root.bin.ots — "
        "step 6 did not unlink it before stamping"
    )


def test_tv3_live_stamp_receipt_size_clears_floor(tmp_path: Path) -> None:
    """After a successful live-stamp run, the receipt file must be
    at least 700 bytes — the conservative floor below which we
    treat the file as a failed persistence (synthetic marker still
    present, or partial write).

    Tag-25 sanity-check pinning: the driver must enforce this and
    exit 7 when the floor is missed; the happy-path mock writes
    1024 bytes so the assertion holds positively.
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    budget_file = tmp_path / "isolated-budget.json"

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={
            "WAT_TV3_LIVE_STAMP": "1",
            "WAT_TV3_BUDGET_FILE": str(budget_file),
        },
    )
    assert result.returncode == 0, (
        f"unexpected rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )

    receipt = archive / "2026-05-26T17" / "root.bin.ots"
    size = receipt.stat().st_size
    assert size >= 700, (
        f"receipt at {receipt} is {size} bytes (<700); persistence broken"
    )

    log = (archive / "run.log").read_text()
    assert "receipt persisted" in log, (
        "driver did not log the persistence sanity-check confirmation"
    )


def test_tv3_live_stamp_undersized_receipt_returns_exit_7(tmp_path: Path) -> None:
    """If the stamp produces a too-small receipt (e.g. a stamper bug
    leaves the 25-byte marker in place), the driver must exit 7.

    We model this by overriding the python shim so the anchor_cli
    branch writes only 16 bytes — well below the 700-byte floor.
    """
    mock_bin = tmp_path / "mock-bin"
    archive = tmp_path / "tv3-archive"
    budget_file = tmp_path / "isolated-budget.json"

    real_python = subprocess.run(
        ["which", "python3"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _write_mock_bin(mock_bin, real_python)

    # Patch the anchor_cli shim to write a 16-byte stub (below floor).
    python_shim = mock_bin / "python3"
    text = python_shim.read_text()
    text = text.replace(
        "b'STUB_OTS_RECEIPT_' + b'\\x00' * 1007",
        "b'TOO_SMALL_RECEIPT'",
    )
    python_shim.write_text(text)
    python_shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:/usr/bin:/bin"
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    )
    env["WAT_TV3_LIVE_STAMP"] = "1"
    env["WAT_TV3_BUDGET_FILE"] = str(budget_file)

    result = subprocess.run(
        ["bash", str(SCRIPT), str(archive)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 7, (
        f"expected exit 7 (persistence broken); got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "persistence broken" in combined or "<700" in combined
