# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic tests for ``scripts/verify-image-digest.sh`` (Phase-2
# Sprint-4 Tag-3, Cross-Review Zone-C digest-pin upgrade).
#
# Test plan (hermetic — no network, no container engine, no cosign):
#
#   1. Repo-compose default-mode parses cleanly and reports digest-pin.
#   2. Tag-only synthetic compose fixture passes in default (warn) mode
#      and exit-2 fails under ``--strict``.
#   3. Malformed image-pin (no tag, no digest) exits 1.
#   4. Wrong digest-format (shorter than 64 hex) exits 1.
#   5. ``--expected-digest`` mismatch exits 1; match exits 0.
#   6. ``--expected-tag`` mismatch exits 1.
#
# All tests synthesise tiny compose fixtures in tmpdir and pass them
# via ``--compose-file``. The repo-default test pulls the real
# ``compose/nats.yaml`` to assert that the script and the file are in
# agreement on the digest-pin form post-Sprint-4-Tag-3.
#
# The script's network-touching modes (``--with-registry`` and
# ``--with-cosign``) are deliberately NOT exercised here. They are
# documented operator-hand modes; a future build-host CI smoke can
# pick them up.

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-image-digest.sh"
COMPOSE_FILE = REPO_ROOT / "compose" / "nats.yaml"

# Real (Sprint-4-Tag-3) digest for nats:2.11-alpine, manifest-list form
# (multi-arch-stable). Resolved 2026-05-11 via Docker Hub public
# registry API. The same value is hard-coded in compose/nats.yaml and
# in this test file deliberately, so a drift in either surface is
# caught by ``test_verify_image_digest_repo_compose_passes_default``.
EXPECTED_DIGEST = (
    "e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00"
)
EXPECTED_TAG = "nats:2.11-alpine"


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    """Helper: run the script in --json mode by default."""
    cmd = ["bash", str(SCRIPT), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        **kw,
    )


def _compose_fixture(tmp_path: Path, image_line: str) -> Path:
    """Write a minimal compose-file fixture with a custom image line.

    The script's pure-bash YAML extractor only needs the
    ``services: / nats: / image: ...`` shape; the rest of the file
    is irrelevant for the digest-form gate.
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


# ---------------------------------------------------------------------
# 1 — repo compose default-mode
# ---------------------------------------------------------------------


def test_verify_image_digest_repo_compose_passes_default() -> None:
    """The real ``compose/nats.yaml`` post-Tag-3 must be digest-pinned
    and the script must report exit 0.

    This is the contract anchor between the script and the file: if
    either drifts, this test fires.
    """
    assert SCRIPT.is_file(), "verify-image-digest.sh missing"
    assert COMPOSE_FILE.is_file(), "compose/nats.yaml missing"

    proc = _run(["--json"])
    assert proc.returncode == 0, (
        f"expected exit 0, got {proc.returncode}; stderr={proc.stderr!r}"
    )
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["form"] == "digest-pin"
    assert summary["tag"] == EXPECTED_TAG
    assert summary["digest"] == EXPECTED_DIGEST
    assert summary["registry_status"] == "skipped"
    assert summary["cosign_status"] == "skipped"


# ---------------------------------------------------------------------
# 2 — tag-only fixture: default passes (warn), --strict exits 2
# ---------------------------------------------------------------------


def test_verify_image_digest_tag_only_passes_in_default_mode(tmp_path: Path) -> None:
    compose = _compose_fixture(tmp_path, "nats:2.11-alpine")
    # NOTE: invoke without --json so the human-readable WARN appears
    # on stderr; the JSON summary still goes to stdout because the
    # script unconditionally emits the final ``cat <<EOF`` block.
    proc = _run(["--compose-file", str(compose)])
    assert proc.returncode == 0
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["form"] == "tag-only"
    assert summary["digest"] == ""
    # The default mode warns but does not fail.
    assert "WARN" in proc.stderr or "tag-only" in proc.stderr.lower()


def test_verify_image_digest_tag_only_fails_strict(tmp_path: Path) -> None:
    compose = _compose_fixture(tmp_path, "nats:2.11-alpine")
    proc = _run(["--compose-file", str(compose), "--strict", "--json"])
    assert proc.returncode == 2, (
        f"expected exit 2 (tag-only under --strict), got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------
# 3 — malformed image-pin
# ---------------------------------------------------------------------


def test_verify_image_digest_malformed_pin_exits_1(tmp_path: Path) -> None:
    """An image-pin without a tag (e.g. ``nats``) is not a valid
    Phase-1b substrate pin; the script must exit 1.
    """
    compose = _compose_fixture(tmp_path, "nats")
    proc = _run(["--compose-file", str(compose), "--json"])
    assert proc.returncode == 1


def test_verify_image_digest_short_digest_exits_1(tmp_path: Path) -> None:
    """A digest with fewer than 64 hex chars must not be accepted."""
    short_digest = "a" * 32  # half-length, definitely not a sha256
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{short_digest}"
    )
    proc = _run(["--compose-file", str(compose), "--json"])
    # The regex requires {64} hex; a shorter string falls into the
    # tag-only branch (no @) — but the @-presence means it's not
    # tag-only either, so the script rejects with exit 1.
    assert proc.returncode == 1


# ---------------------------------------------------------------------
# 4 — --expected-digest contract
# ---------------------------------------------------------------------


def test_verify_image_digest_expected_digest_match(tmp_path: Path) -> None:
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{EXPECTED_DIGEST}"
    )
    proc = _run(
        [
            "--compose-file",
            str(compose),
            "--expected-digest",
            EXPECTED_DIGEST,
            "--json",
        ]
    )
    assert proc.returncode == 0


def test_verify_image_digest_expected_digest_mismatch_exits_1(tmp_path: Path) -> None:
    wrong_digest = "f" * 64
    compose = _compose_fixture(
        tmp_path, f"{EXPECTED_TAG}@sha256:{EXPECTED_DIGEST}"
    )
    proc = _run(
        [
            "--compose-file",
            str(compose),
            "--expected-digest",
            wrong_digest,
            "--json",
        ]
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------
# 5 — --expected-tag contract
# ---------------------------------------------------------------------


def test_verify_image_digest_expected_tag_mismatch_exits_1(tmp_path: Path) -> None:
    """A compose file pinning a different tag (say ``nats:2.10-alpine``)
    must be rejected when ``--expected-tag`` is set to ``2.11-alpine``.
    """
    compose = _compose_fixture(
        tmp_path, f"nats:2.10-alpine@sha256:{EXPECTED_DIGEST}"
    )
    proc = _run(
        [
            "--compose-file",
            str(compose),
            "--expected-tag",
            "nats:2.11-alpine",
            "--json",
        ]
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------
# 6 — script invariants
# ---------------------------------------------------------------------


def test_verify_image_digest_script_is_executable() -> None:
    """The script must be executable so an operator can invoke it
    directly without prefixing ``bash``."""
    assert os.access(SCRIPT, os.X_OK), (
        "scripts/verify-image-digest.sh must have the executable bit set"
    )


def test_verify_image_digest_script_passes_bash_n() -> None:
    """``bash -n`` must accept the script (syntax check)."""
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert proc.returncode == 0, f"bash -n failed: {proc.stderr!r}"
