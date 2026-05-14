# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``infra/spire/federation/proxmox/resolve-image-pins.sh``.

Phase-2 Sprint-9 Tag-6 — the Operator-Hand Pilot-VM resolver MUST
match the wakir-provisioner placeholder regardless of which ``:<tag>``
the Quadlet currently carries.

Anlass: Live-Bring-up-2-Bilanz 2026-05-14, Bug 3. The BSL-Bulk-Edit-
Welle (PR #37, e5067b4) rotated the bucket-init Quadlet pin from
``ghcr.io/wakir-labs/wakir-provisioner:0.1.0@sha256:DIGEST_PENDING_TOMAS_REVIEW``
to ``:0.1.2``. The resolver previously hard-coded the
``:0.1.0`` prefix and silently skipped the substitution; the Pilot-VM
crashed at bucket-init unit start with ``invalid reference format``.

Coverage axes:

* ``--help`` exits 0 and documents the Tag-6 ``--wakir-provisioner-
  version`` flag.
* Bash syntax is clean.
* Resolver substitutes a ``:0.1.0`` placeholder (legacy form).
* Resolver substitutes a ``:0.1.2`` placeholder (Tag-6 form). This is
  the concrete regression Bug 3 exposes.
* Resolver substitutes a ``:0.99.99-rc1`` placeholder (future-form;
  Tag-6 tolerates arbitrary tags).
* Resolver substitutes a bare-image placeholder (no tag at all).
* ``--wakir-provisioner-version <new-tag>`` rotates the tag in the
  same pass.
* The resolver only mutates the placeholder line; an unrelated digest
  line for the same image-base is untouched.
* SPIRE-Server / Agent / python pins still resolve unchanged (no
  regression to the tag-EXACT codepath).

Sandbox boundary: bash + sed + perl, no podman, no network.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "proxmox"
    / "resolve-image-pins.sh"
)

# Static, syntactically valid sha256 digests for the four pin groups
# the resolver requires.
SHA256_A = "sha256:" + "a" * 64
SHA256_B = "sha256:" + "b" * 64
SHA256_C = "sha256:" + "c" * 64
SHA256_D = "sha256:" + "d" * 64


def _build_skeleton(root: Path, provisioner_quadlet_image_line: str) -> None:
    """Build a minimal --root directory layout matching what the
    resolver expects on a real Pilot-VM."""
    # SPIRE-server quadlets.
    (root / "quadlet").mkdir(parents=True, exist_ok=True)
    (root / "quadlet" / "wakir-spire-server.container").write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-server:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "infra/spire/federation/quadlet").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/federation/quadlet"
        / "wakir-spire-server-federation.container"
    ).write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-server:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )

    # SPIRE-agent quadlets.
    (root / "quadlet" / "wakir-spire-agent.container").write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-agent:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    (root / "infra/spire/agent/quadlet").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/agent/quadlet"
        / "wakir-spire-agent-federation.container"
    ).write_text(
        "[Container]\n"
        "Image=ghcr.io/spiffe/spire-agent:1.14.6"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )

    # Provisioner Containerfile (python base layer).
    (root / "infra/spire/federation/provisioner").mkdir(
        parents=True, exist_ok=True
    )
    (
        root
        / "infra/spire/federation/provisioner"
        / "Containerfile"
    ).write_text(
        "FROM docker.io/library/python:3.13-slim"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )

    # Bucket-init Quadlet (the line under test).
    (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).write_text(
        "[Container]\n"
        f"{provisioner_quadlet_image_line}\n"
    )


def _run_resolver(
    root: Path,
    *,
    apply: bool = True,
    extra: list[str] | None = None,
) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        str(RESOLVER),
        "--spire-server-digest", SHA256_A,
        "--spire-agent-digest", SHA256_B,
        "--python-digest", SHA256_C,
        "--wakir-provisioner-digest", SHA256_D,
        "--root", str(root),
    ]
    if apply:
        cmd.append("--apply")
    if extra:
        cmd.extend(extra)
    return subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )


# ----------------------------------------------------------------------
# Binary invariants.
# ----------------------------------------------------------------------

def test_resolver_script_exists() -> None:
    assert RESOLVER.is_file(), f"missing resolver: {RESOLVER}"


def test_resolver_bash_syntax_clean() -> None:
    rc = subprocess.run(["bash", "-n", str(RESOLVER)], check=False)
    assert rc.returncode == 0


def test_resolver_help_documents_tag_6_version_flag() -> None:
    rc = subprocess.run(
        ["bash", str(RESOLVER), "--help"],
        check=False, capture_output=True, text=True,
    )
    assert rc.returncode == 0
    # Tag-6 addition.
    assert "--wakir-provisioner-version" in rc.stdout, (
        "resolver --help must document the Sprint-9 Tag-6 "
        "--wakir-provisioner-version flag"
    )
    # The pre-Tag-6 flag stays documented.
    assert "--wakir-provisioner-digest" in rc.stdout


# ----------------------------------------------------------------------
# Tag-tolerant substitution — the core of Sprint-9 Tag-6.
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "tag_in_quadlet",
    ["0.1.0", "0.1.2", "0.2.0", "1.0.0-rc1", "2026-05-14"],
)
def test_resolver_substitutes_arbitrary_tag(
    tmp_path: Path, tag_in_quadlet: str
) -> None:
    """The resolver MUST substitute the wakir-provisioner placeholder
    regardless of which ``:<tag>`` the Quadlet pins.

    This is the Bug 3 regression test — Live-Bring-up-2 crashed
    because the Quadlet was on ``:0.1.2`` and the resolver only matched
    ``:0.1.0``.
    """
    root = tmp_path / "root"
    image_line = (
        f"Image=ghcr.io/wakir-labs/wakir-provisioner:{tag_in_quadlet}"
        f"@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    )
    _build_skeleton(root, image_line)

    proc = _run_resolver(root)
    assert proc.returncode == 0, (
        f"resolver failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )

    quadlet = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    # Placeholder gone.
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in quadlet, (
        f"placeholder not substituted for tag {tag_in_quadlet!r}: "
        f"{quadlet!r}"
    )
    # Tag preserved byte-for-byte.
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner:{tag_in_quadlet}"
        f"@{SHA256_D}" in quadlet
    ), (
        f"tag {tag_in_quadlet!r} not preserved or digest wrong: "
        f"{quadlet!r}"
    )


def test_resolver_substitutes_bare_image_no_tag(tmp_path: Path) -> None:
    """The bare-image form (no ``:<tag>``) MUST also resolve. This is
    the edge case where the placeholder lived on the image-base alone
    (pre-BSL-Bulk-Edit shape)."""
    root = tmp_path / "root"
    image_line = (
        "Image=ghcr.io/wakir-labs/wakir-provisioner"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    )
    _build_skeleton(root, image_line)

    proc = _run_resolver(root)
    assert proc.returncode == 0, proc.stderr

    quadlet = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in quadlet
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner@{SHA256_D}" in quadlet
    ), quadlet
    # No invented tag.
    assert "wakir-provisioner:" not in quadlet, (
        f"resolver invented a tag on bare-image form: {quadlet!r}"
    )


def test_resolver_rotates_tag_with_version_flag(tmp_path: Path) -> None:
    """``--wakir-provisioner-version <new>`` MUST rotate the tag in
    the same pass as the digest substitution."""
    root = tmp_path / "root"
    image_line = (
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    )
    _build_skeleton(root, image_line)

    proc = _run_resolver(
        root,
        extra=["--wakir-provisioner-version", "0.2.0"],
    )
    assert proc.returncode == 0, proc.stderr

    quadlet = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in quadlet
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner:0.2.0@{SHA256_D}"
        in quadlet
    ), quadlet
    assert ":0.1.2" not in quadlet, (
        f"old tag :0.1.2 not rotated: {quadlet!r}"
    )


def test_resolver_rejects_malformed_version_flag(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    proc = _run_resolver(
        root,
        extra=["--wakir-provisioner-version", "../not-a-tag"],
    )
    assert proc.returncode != 0, (
        "resolver must reject a malformed --wakir-provisioner-version"
    )


# ----------------------------------------------------------------------
# Non-regression on the tag-EXACT codepath.
# ----------------------------------------------------------------------

def test_resolver_still_substitutes_spire_pins(tmp_path: Path) -> None:
    """SPIRE-Server / SPIRE-Agent / python pins MUST still resolve
    unchanged — they live on the tag-EXACT codepath that pre-dates
    Sprint-9 Tag-6."""
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    proc = _run_resolver(root)
    assert proc.returncode == 0, proc.stderr

    server = (
        root / "quadlet" / "wakir-spire-server.container"
    ).read_text()
    assert (
        f"ghcr.io/spiffe/spire-server:1.14.6@{SHA256_A}" in server
    )
    agent = (
        root / "quadlet" / "wakir-spire-agent.container"
    ).read_text()
    assert (
        f"ghcr.io/spiffe/spire-agent:1.14.6@{SHA256_B}" in agent
    )
    containerfile = (
        root / "infra/spire/federation/provisioner/Containerfile"
    ).read_text()
    assert (
        f"docker.io/library/python:3.13-slim@{SHA256_C}"
        in containerfile
    )


def test_resolver_dry_run_does_not_mutate(tmp_path: Path) -> None:
    """Without --apply, no file mutation. This is the long-standing
    invariant; Sprint-9 Tag-6 must not regress it."""
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    before = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    proc = _run_resolver(root, apply=False)
    assert proc.returncode == 0, proc.stderr
    after = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert before == after, "dry-run mutated file"


# ----------------------------------------------------------------------
# Wakir-provisioner-digest optional + WARN path.
# ----------------------------------------------------------------------

def test_resolver_skips_provisioner_when_digest_omitted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    # Omit --wakir-provisioner-digest. SPIRE + python pins MUST still
    # resolve; the bucket-init placeholder MUST remain untouched.
    cmd = [
        "bash", str(RESOLVER),
        "--spire-server-digest", SHA256_A,
        "--spire-agent-digest", SHA256_B,
        "--python-digest", SHA256_C,
        "--root", str(root),
        "--apply",
    ]
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "WARN" in proc.stdout
    quadlet = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    # Placeholder still present.
    assert "DIGEST_PENDING_TOMAS_REVIEW" in quadlet


# ----------------------------------------------------------------------
# Unrelated digest line under the same image-base is NOT collateral
# damage. (Defensive: documents that the substitution is anchored to
# the placeholder token, not to the image-base alone.)
# ----------------------------------------------------------------------

def test_resolver_does_not_rewrite_already_resolved_digest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    # Append a SECOND already-resolved line under the same image-base
    # but with a real digest. The resolver must leave it alone.
    quadlet_path = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    )
    quadlet_path.write_text(
        quadlet_path.read_text()
        + "# legacy reference (already resolved):\n"
        + "# ghcr.io/wakir-labs/wakir-provisioner:0.0.9"
        + "@sha256:" + "f" * 64 + "\n"
    )
    proc = _run_resolver(root)
    assert proc.returncode == 0, proc.stderr
    quadlet = quadlet_path.read_text()
    # The already-resolved line is byte-identical.
    assert (
        "ghcr.io/wakir-labs/wakir-provisioner:0.0.9@sha256:" + "f" * 64
        in quadlet
    )
    # The placeholder line was substituted with the new digest.
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner:0.1.2@{SHA256_D}"
        in quadlet
    )
