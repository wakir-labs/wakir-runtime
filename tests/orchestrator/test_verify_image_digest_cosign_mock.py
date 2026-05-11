# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic Mock-cosign-binary coverage for the ``--with-cosign``
# codepath in ``scripts/verify-image-digest.sh`` (Phase-2 Sprint-6
# Tag-4, cosign-sign-activation-skizze sibling artefact).
#
# Test plan (hermetic — no network, no real cosign, no container
# engine):
#
#   1. ``--with-cosign`` on a digest-pinned compose with a mock cosign
#      that exits 0 -> script exits 0, JSON summary
#      ``cosign_status: ok``.
#   2. ``--with-cosign`` on a digest-pinned compose with a mock cosign
#      that exits 1 -> script exits 1, JSON not emitted (script bails
#      with FAIL before the summary block).
#   3. ``--with-cosign`` with NO cosign on PATH at all -> script exits
#      1 with FAIL "cosign on PATH" diagnostic.
#   4. ``--with-cosign`` on a tag-only compose -> script exits 1 with
#      FAIL "digest-pinned image form" diagnostic; mock cosign is
#      never invoked.
#
# All four cases are hermetic. The mock-cosign-binary is a tiny shell
# script in ``tmp_path / "bin" / "cosign"`` that the test PATH-shims
# in front of any real cosign that may or may not be on the build-
# host's PATH. Exit code and stderr message are configured via env
# vars passed to ``subprocess.run``.
#
# Reference: ``docs/cosign-synadia-sign-activation-skizze.md`` §5.

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-image-digest.sh"
COMPOSE_FILE = REPO_ROOT / "compose" / "nats.yaml"

# Match the digest pinned in compose/nats.yaml so the digest-pin
# gate accepts the fixture. The actual digest value does not matter
# for the mock-binary path: the script never asks cosign about the
# digest content, it only invokes ``cosign verify <tag>@sha256:<d>``
# and reads the exit code.
EXPECTED_DIGEST = (
    "e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00"
)
EXPECTED_TAG = "nats:2.11-alpine"


def _compose_fixture(tmp_path: Path, image_line: str) -> Path:
    """Write a minimal compose fixture (mirrors test_verify_image_digest.py).

    Kept duplicated rather than imported to keep this test file
    self-contained for the Mock-cosign sibling-artefact scope.
    """
    body = (
        "services:\n"
        "  nats:\n"
        f"    image: {image_line}\n"
        "    container_name: wakir-nats\n"
    )
    path = tmp_path / "nats.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _mock_cosign(tmp_path: Path, exit_code: int, stderr_msg: str = "") -> Path:
    """Write a tiny mock cosign binary in ``tmp_path / "bin" / "cosign"``.

    The mock writes its argv to stdout (so the test can confirm the
    expected invocation form), optionally writes ``stderr_msg`` to
    stderr, and exits with ``exit_code``.

    Returns the ``bin`` directory path for PATH-prepending.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    cosign_path = bin_dir / "cosign"
    # Use a heredoc-free body: the mock is invoked with ``cosign
    # verify <ref>`` and we only need to echo argv and exit.
    body = (
        "#!/usr/bin/env bash\n"
        f"echo \"mock-cosign argv: $*\"\n"
    )
    if stderr_msg:
        # Single-quote-escape the message for the heredoc-free shell.
        safe_msg = stderr_msg.replace("'", "'\\''")
        body += f"echo '{safe_msg}' >&2\n"
    body += f"exit {exit_code}\n"
    cosign_path.write_text(body, encoding="utf-8")
    cosign_path.chmod(cosign_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_with_path(
    args: list[str],
    *,
    extra_path_dir: Path | None,
    drop_real_cosign: bool = False,
) -> subprocess.CompletedProcess:
    """Run the script with a controlled PATH.

    If ``extra_path_dir`` is set, it is prepended to PATH. If
    ``drop_real_cosign`` is set, PATH is replaced with a minimal
    prefix that does NOT include any directory where a real cosign
    binary might live; this lets test #3 verify the "binary-missing"
    diagnostic regardless of the build-host's PATH.
    """
    env = os.environ.copy()
    if drop_real_cosign:
        # Minimal PATH containing only the tmpdir bin (if provided)
        # plus a system-essentials prefix; deliberately omit
        # /usr/local/bin where cosign might be installed.
        essentials = "/usr/bin:/bin"
        if extra_path_dir is not None:
            env["PATH"] = f"{extra_path_dir}:{essentials}"
        else:
            env["PATH"] = essentials
    else:
        if extra_path_dir is not None:
            env["PATH"] = f"{extra_path_dir}{os.pathsep}{env.get('PATH', '')}"
    cmd = ["bash", str(SCRIPT), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------
# 1 — --with-cosign on digest-pinned compose, mock cosign passes
# ---------------------------------------------------------------------


def test_with_cosign_mock_pass_exits_0(tmp_path: Path) -> None:
    """Mock cosign returns 0; the script must surface
    ``cosign_status: ok`` in the JSON summary and exit 0.
    """
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{EXPECTED_DIGEST}"
    )
    bin_dir = _mock_cosign(tmp_path, exit_code=0)

    proc = _run_with_path(
        [
            "--compose-file",
            str(compose),
            "--with-cosign",
            "--json",
        ],
        extra_path_dir=bin_dir,
    )

    assert proc.returncode == 0, (
        f"expected exit 0 (mock-cosign pass), got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    # The script emits exactly one JSON line on stdout.
    summary_line = proc.stdout.strip().splitlines()[-1]
    summary = json.loads(summary_line)
    assert summary["form"] == "digest-pin"
    assert summary["cosign_status"] == "ok"
    assert summary["tag"] == EXPECTED_TAG
    assert summary["digest"] == EXPECTED_DIGEST


# ---------------------------------------------------------------------
# 2 — --with-cosign on digest-pinned compose, mock cosign fails
# ---------------------------------------------------------------------


def test_with_cosign_mock_fail_exits_1(tmp_path: Path) -> None:
    """Mock cosign returns 1; the script must exit 1 and surface the
    FAIL diagnostic on stderr.

    The script bails with ``fail "cosign verify failed ..."`` and
    ``exit 1`` BEFORE the JSON summary block, so no JSON is emitted
    on stdout in the failure path.
    """
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{EXPECTED_DIGEST}"
    )
    bin_dir = _mock_cosign(
        tmp_path,
        exit_code=1,
        stderr_msg="error: no matching signatures",
    )

    proc = _run_with_path(
        [
            "--compose-file",
            str(compose),
            "--with-cosign",
        ],
        extra_path_dir=bin_dir,
    )

    assert proc.returncode == 1, (
        f"expected exit 1 (mock-cosign fail), got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    # FAIL marker present on stderr.
    assert "FAIL" in proc.stderr
    assert "cosign verify failed" in proc.stderr
    # Mock's own stderr line passed through.
    assert "no matching signatures" in proc.stderr
    # No JSON summary emitted in failure path (script exits before
    # the summary block).
    assert "cosign_status" not in proc.stdout


# ---------------------------------------------------------------------
# 3 — --with-cosign with NO cosign on PATH
# ---------------------------------------------------------------------


def test_with_cosign_binary_missing_exits_1(tmp_path: Path) -> None:
    """No cosign binary anywhere on PATH; the script must exit 1
    with a FAIL diagnostic that mentions cosign and PATH.
    """
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{EXPECTED_DIGEST}"
    )

    proc = _run_with_path(
        [
            "--compose-file",
            str(compose),
            "--with-cosign",
        ],
        extra_path_dir=None,
        drop_real_cosign=True,
    )

    assert proc.returncode == 1, (
        f"expected exit 1 (cosign missing), got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "FAIL" in proc.stderr
    # The script's exact phrasing: "cosign on PATH".
    assert "cosign" in proc.stderr.lower()
    assert "path" in proc.stderr.lower()
    # No JSON summary in failure path.
    assert "cosign_status" not in proc.stdout


# ---------------------------------------------------------------------
# 4 — --with-cosign on tag-only compose (digest-pin gate)
# ---------------------------------------------------------------------


def test_with_cosign_tag_only_compose_exits_1(tmp_path: Path) -> None:
    """``--with-cosign`` requires a digest-pinned image form. On a
    tag-only compose the script must exit 1 with a FAIL diagnostic;
    the mock cosign binary is provided but should never be invoked.

    The diagnostic check confirms the form-gate fires BEFORE the
    cosign invocation, so the script does not waste a network probe
    on a malformed pin.
    """
    compose = _compose_fixture(tmp_path, "nats:2.11-alpine")
    bin_dir = _mock_cosign(tmp_path, exit_code=0)

    proc = _run_with_path(
        [
            "--compose-file",
            str(compose),
            "--with-cosign",
        ],
        extra_path_dir=bin_dir,
    )

    assert proc.returncode == 1, (
        f"expected exit 1 (tag-only + --with-cosign), got {proc.returncode}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "FAIL" in proc.stderr
    # Diagnostic identifies the form-gate as the blocker.
    assert "digest-pinned" in proc.stderr.lower() or "digest-pin" in proc.stderr.lower()
    # No JSON summary in failure path.
    assert "cosign_status" not in proc.stdout


# ---------------------------------------------------------------------
# 5 — Mock-binary self-invariants (sanity: harness itself works)
# ---------------------------------------------------------------------


def test_mock_cosign_harness_self_check_pass(tmp_path: Path) -> None:
    """Direct invocation of the mock cosign binary returns the
    configured exit code and echoes argv. This guards against a
    silently broken harness in case the four scenarios above start
    asserting false-positively.
    """
    bin_dir = _mock_cosign(tmp_path, exit_code=0)
    proc = subprocess.run(
        [str(bin_dir / "cosign"), "verify", "fake-image@sha256:abc"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert proc.returncode == 0
    assert "mock-cosign argv:" in proc.stdout
    assert "verify" in proc.stdout
    assert "fake-image@sha256:abc" in proc.stdout


def test_mock_cosign_harness_self_check_fail(tmp_path: Path) -> None:
    """Mock with exit-code 1 and a stderr message produces those
    exact byproducts.
    """
    bin_dir = _mock_cosign(
        tmp_path, exit_code=1, stderr_msg="mock-error: forced-fail"
    )
    proc = subprocess.run(
        [str(bin_dir / "cosign"), "verify", "x"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert proc.returncode == 1
    assert "forced-fail" in proc.stderr
