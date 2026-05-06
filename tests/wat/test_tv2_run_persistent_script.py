# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for ``scripts/wat-tv2-run-persistent.sh``.

The driver is bash and orchestrates a multi-hour live-stamp loop, but
the inner logic that this test exercises is purely deterministic:

* hour-slot expansion (``HOUR_BASE`` + ``WAT_TV2_HOURS`` -> N slots,
  refusing cross-midnight rolls);
* spool generation (5 events per hour, byte-stable against the
  embedded Python heredoc);
* `WAT_TV2_HOURS` validation (refuse values outside ``{4, 5, 6}``);
* bash -n syntax sanity (a static check guarding the heredocs and
  arithmetic blocks).

The tests do **not** invoke the aggregator or anchor pipelines — for
those the gated pytest ``test_tv2_chain_check_real.py`` is the
binding fixture. These tests guard the script's *own* logic against
regressions, in the same spirit as
``test_block_heights_collect_script.py`` for TV-1's harvest leg.

Strategy: shadow ``python3``, ``ots``, ``wc``, ``date`` etc. with
small bash mocks on PATH where needed. We do not need a real
aggregator — we only need the spool generation and hour-expansion
phases to run, and we abort the script early via a stub ``python3``
that exits 0 and writes a synthetic ``manifest.json`` so the
arithmetic and prev_hour_root threading can be observed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "wat-tv2-run-persistent.sh"


def test_script_bash_syntax_is_valid() -> None:
    """Static guard: ``bash -n`` must parse the script clean.

    Catches heredoc and arithmetic block typos that would otherwise
    only surface on a live calendar-talking run.
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


def test_script_is_executable() -> None:
    """The driver must be marked executable for operator one-liners."""
    mode = SCRIPT.stat().st_mode
    assert mode & 0o111, f"{SCRIPT} should be executable"


# ---------------------------------------------------------------------------
# Mock infrastructure for partial-execution tests.
#
# We let the bash driver run all the way through hour-slot expansion
# and spool generation, but we intercept python3 invocations so that
# the aggregator/anchor pipelines are not actually called. The mock
# python3:
#
#   * for ``-m wat.cmd.aggregator_cli build``: writes a stub
#     manifest.json with a deterministic merkle_root derived from the
#     hour slot;
#   * for ``-m wat.cmd.anchor_cli stamp``:   writes a placeholder
#     root.bin.ots so the file-existence check passes;
#   * for ``-m wat.verify.cli``:              exits 3 (pending);
#   * for the inline heredoc (``python3 -``): falls through to the
#     real interpreter — these are the spool generators and the
#     small JSON readers, which we want to keep real;
#   * for ``-c "import json,sys; ..."``:      same fall-through.
#
# The shim is written in bash and selects on argv. Falling through to
# the real interpreter is achieved by re-exec'ing with ``exec``
# against the host python3 (located via env var the test sets).
# ---------------------------------------------------------------------------


def _write_mock_bin(mock_dir: Path, real_python: str) -> None:
    mock_dir.mkdir(parents=True, exist_ok=True)

    # ots — only ``info`` and ``upgrade`` are touched by the verify-CLI
    # leg (and the verify-CLI leg runs through python3, not directly).
    # The driver itself only checks ``command -v ots``.
    ots_shim = mock_dir / "ots"
    ots_shim.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        '  upgrade) exit 0 ;;\n'
        '  info)    echo "File sha256 hash: 00" ;;\n'
        '  *)       exit 0 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    ots_shim.chmod(0o755)

    # python3 — the interesting shim. Selects on argv to either
    # short-circuit aggregator/anchor invocations with file-writes or
    # fall through to the real interpreter for spool generation +
    # JSON reads.
    python_shim = mock_dir / "python3"
    python_shim.write_text(
        f"""#!/usr/bin/env bash
REAL_PYTHON={real_python}

# Pass-through for ``python3 -`` (the spool-generator heredoc).
if [[ "$1" == "-" ]]; then
    exec "$REAL_PYTHON" "$@"
fi

# Pass-through for ``python3 -c ...`` (the inline JSON readers).
if [[ "$1" == "-c" ]]; then
    exec "$REAL_PYTHON" "$@"
fi

# Aggregator: parse args manually and write a stub manifest.
if [[ "$1" == "-m" && "$2" == "wat.cmd.aggregator_cli" ]]; then
    HOUR=""
    OUT_MANIFEST=""
    INPUT_EVENTS=""
    PREV=""
    shift 2  # drop -m and module name
    shift    # drop subcommand (build)
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --hour)             HOUR="$2"; shift 2 ;;
            --output-manifest)  OUT_MANIFEST="$2"; shift 2 ;;
            --input-events)     INPUT_EVENTS="$2"; shift 2 ;;
            --prev-hour-root)   PREV="$2"; shift 2 ;;
            *)                  shift ;;
        esac
    done
    # Derive a stable 64-char hex root from the hour slot via openssl.
    ROOT=$(printf '%s' "$HOUR" | "$REAL_PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())')
    if [[ -n "$PREV" ]]; then
        printf '{{"version":"wakir-wat-manifest/v1","hour":"%s","merkle_root":"%s","prev_hour_root":"%s","event_count":5,"tree_levels":3}}\\n' \\
            "$HOUR" "$ROOT" "$PREV" > "$OUT_MANIFEST"
    else
        printf '{{"version":"wakir-wat-manifest/v1","hour":"%s","merkle_root":"%s","prev_hour_root":null,"event_count":5,"tree_levels":3}}\\n' \\
            "$HOUR" "$ROOT" > "$OUT_MANIFEST"
    fi
    exit 0
fi

# Anchor: write a placeholder root.bin.ots in --out dir.
if [[ "$1" == "-m" && "$2" == "wat.cmd.anchor_cli" ]]; then
    OUT_DIR=""
    shift 2  # drop -m and module
    shift    # drop subcommand (stamp)
    shift    # drop merkle_root positional
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --out) OUT_DIR="$2"; shift 2 ;;
            *)     shift ;;
        esac
    done
    printf 'STUB_OTS_RECEIPT' > "$OUT_DIR/root.bin.ots"
    exit 0
fi

# Verifier: exit 3 (pending) — the driver tolerates this.
if [[ "$1" == "-m" && "$2" == "wat.verify.cli" ]]; then
    exit 3
fi

# Default fall-through.
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)


def _run_driver(
    mock_bin: Path,
    archive_root: Path,
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
    env["WAT_TV2_INTER_HOUR_SLEEP"] = "0"  # tests never sleep
    if env_overrides:
        env.update(env_overrides)

    cmd = ["bash", str(SCRIPT)]
    if args is not None:
        cmd.extend(args)
    else:
        cmd.append(str(archive_root))

    return subprocess.run(
        cmd, capture_output=True, text=True, env=env, check=False
    )


def test_default_h4_run_writes_four_hours_with_chain(tmp_path: Path) -> None:
    """End-to-end shape check on the default H=4 config.

    Verifies:
    - exit 0,
    - 4 hour-directories present (2026-05-27T00..03),
    - each hour has tv2.jsonl with exactly 5 events,
    - manifest.prev_hour_root = previous merkle_root for hours 1..3,
    - hour 0 manifest carries prev_hour_root == null,
    - summary.txt is written and lists all 4 roots.
    """
    archive = tmp_path / "tv2-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(mock_bin, archive)

    assert result.returncode == 0, (
        f"expected exit 0; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    expected_slots = [
        "2026-05-27T00",
        "2026-05-27T01",
        "2026-05-27T02",
        "2026-05-27T03",
    ]
    for slot in expected_slots:
        spool = archive / slot / "tv2.jsonl"
        manifest = archive / slot / "manifest.json"
        receipt = archive / slot / "root.bin.ots"
        assert spool.exists(), f"missing spool for {slot}"
        assert manifest.exists(), f"missing manifest for {slot}"
        assert receipt.exists(), f"missing receipt for {slot}"
        events = spool.read_text().splitlines()
        assert len(events) == 5, f"hour {slot}: expected 5 events, got {len(events)}"

    # Hour 0 prev_hour_root must be None; hours 1..3 must thread.
    m0 = json.loads((archive / expected_slots[0] / "manifest.json").read_text())
    assert m0["prev_hour_root"] is None
    prev_root = m0["merkle_root"]
    for slot in expected_slots[1:]:
        m = json.loads((archive / slot / "manifest.json").read_text())
        assert m["prev_hour_root"] == prev_root, (
            f"chain break at {slot}: prev_hour_root={m['prev_hour_root']} "
            f"expected={prev_root}"
        )
        prev_root = m["merkle_root"]

    summary = (archive / "summary.txt").read_text().strip()
    assert "hours=4" in summary
    assert "hour_base=2026-05-27T00" in summary
    # Each of the four roots should appear in the comma-joined roots= field.
    for slot in expected_slots:
        slot_root = json.loads(
            (archive / slot / "manifest.json").read_text()
        )["merkle_root"]
        assert slot_root in summary, f"summary missing root for {slot}"


def test_h6_stretch_expands_six_hours(tmp_path: Path) -> None:
    """``WAT_TV2_HOURS=6`` produces a 6-hour chain."""
    archive = tmp_path / "tv2-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(
        mock_bin, archive, env_overrides={"WAT_TV2_HOURS": "6"}
    )

    assert result.returncode == 0
    expected_slots = [f"2026-05-27T{h:02d}" for h in range(6)]
    for slot in expected_slots:
        assert (archive / slot / "manifest.json").exists()


def test_h7_is_rejected_with_validation_error(tmp_path: Path) -> None:
    """``WAT_TV2_HOURS=7`` is outside ``{4,5,6}`` and must error out."""
    archive = tmp_path / "tv2-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(
        mock_bin, archive, env_overrides={"WAT_TV2_HOURS": "7"}
    )

    assert result.returncode == 1
    assert "WAT_TV2_HOURS=7 not in {4,5,6}" in (result.stdout + result.stderr)


def test_h3_is_rejected_with_validation_error(tmp_path: Path) -> None:
    """Below-range values are also rejected (not just above 6)."""
    archive = tmp_path / "tv2-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(
        mock_bin, archive, env_overrides={"WAT_TV2_HOURS": "3"}
    )

    assert result.returncode == 1


def test_cross_midnight_is_refused(tmp_path: Path) -> None:
    """``HOUR_BASE=...T22`` with ``H=4`` would require hour 25; refuse it."""
    archive = tmp_path / "tv2-archive"
    mock_bin = tmp_path / "mock-bin"

    result = _run_driver(
        mock_bin,
        archive,
        env_overrides={
            "WAT_TV2_HOUR_BASE": "2026-05-27T22",
            "WAT_TV2_HOURS": "4",
        },
    )

    assert result.returncode == 1
    assert "cross-midnight not supported" in (result.stdout + result.stderr)


def test_event_payload_is_deterministic(tmp_path: Path) -> None:
    """Two runs with the same config produce byte-identical spools.

    This is the regression guard against drift between the embedded
    Python heredoc and the gated pytest's event generator. If the
    spool changes shape, the Merkle roots change and TV-2's offline
    hash-consistency assertion in ``test_tv2_chain_check_real.py``
    will break.
    """
    archive_a = tmp_path / "run-a"
    archive_b = tmp_path / "run-b"
    mock_bin = tmp_path / "mock-bin"

    rc_a = _run_driver(mock_bin, archive_a).returncode
    rc_b = _run_driver(mock_bin, archive_b).returncode
    assert rc_a == 0 and rc_b == 0

    for slot in [f"2026-05-27T{h:02d}" for h in range(4)]:
        a = (archive_a / slot / "tv2.jsonl").read_bytes()
        b = (archive_b / slot / "tv2.jsonl").read_bytes()
        assert a == b, f"spool drift detected at {slot}"


def test_missing_ots_binary_returns_exit_3(tmp_path: Path) -> None:
    """Documented exit code 3 when ``ots`` is missing."""
    archive = tmp_path / "tv2-archive"
    # Empty mock dir, no ``ots`` shim -> command -v ots fails.
    real_python = subprocess.run(
        ["which", "python3"], capture_output=True, text=True, check=True
    ).stdout.strip()
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    # We do install python3 because the driver invokes it before the
    # ots check (header logging path), but no ots.
    py = mock_bin / "python3"
    py.write_text(f"#!/usr/bin/env bash\nexec {real_python} \"$@\"\n", encoding="utf-8")
    py.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}:/usr/bin:/bin"
    result = subprocess.run(
        ["bash", str(SCRIPT), str(archive)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 3
    assert "ots CLI not on PATH" in (result.stdout + result.stderr)
