# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``infra/spire/federation/proxmox/resolve-image-pins.sh``.

Phase-2 — the Operator-Hand Pilot-VM resolver MUST
match the wakir-provisioner placeholder regardless of which ``:<tag>``
the Quadlet currently carries.

Anlass: Live-Bring-up-2-Bilanz 2026-05-14, Bug 3. The BSL-Bulk-Edit-
wave (PR #37, e5067b4) rotated the bucket-init Quadlet pin from
``ghcr.io/wakir-labs/wakir-provisioner:0.1.0@sha256:DIGEST_PENDING_TOMAS_REVIEW``
to ``:0.1.2``. The resolver previously hard-coded the
``:0.1.0`` prefix and silently skipped the substitution; the Pilot-VM
crashed at bucket-init unit start with ``invalid reference format``.

Coverage axes:

* ``--help`` exits 0 and documents the ``--wakir-provisioner-
  version`` flag.
* Bash syntax is clean.
* Resolver substitutes a ``:0.1.0`` placeholder (legacy form).
* Resolver substitutes a ``:0.1.2`` placeholder (form). This is
  the concrete regression Bug 3 exposes.
* Resolver substitutes a ``:0.99.99-rc1`` placeholder (future-form;
  tolerates arbitrary tags).
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
    # addition.
    assert "--wakir-provisioner-version" in rc.stdout, (
        "resolver --help must document the "
        "--wakir-provisioner-version flag"
    )
    # The pre-flag stays documented.
    assert "--wakir-provisioner-digest" in rc.stdout


# ----------------------------------------------------------------------
# Tag-tolerant substitution — the core of.
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
    the digest-pinning work."""
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
    invariant; must not regress it."""
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


# ----------------------------------------------------------------------
# Bug-33 substance-fix: --provisioner-only mode.
#
# Skip-cosign-verify mode in wakir-pilot-bootstrap.sh step 5 must be
# able to call the resolver with ONLY --wakir-provisioner-digest +
# --provisioner-only (no spire-server / spire-agent / python digests).
# The prior bootstrap-call shape aborted at validate_digest with
# ``ERROR: --spire-server-digest is required``; M-3 Live-Trial
# (2026-05-15 15:00 CEST) confirmed the failure.
# ----------------------------------------------------------------------


def test_resolver_help_documents_provisioner_only_flag() -> None:
    rc = subprocess.run(
        ["bash", str(RESOLVER), "--help"],
        check=False, capture_output=True, text=True,
    )
    assert rc.returncode == 0
    assert "--provisioner-only" in rc.stdout, (
        "resolver --help must document the Bug-33 "
        "--provisioner-only flag"
    )


def test_provisioner_only_requires_wakir_provisioner_digest(
    tmp_path: Path,
) -> None:
    """--provisioner-only WITHOUT --wakir-provisioner-digest MUST
    abort with exit 1 + a clear error message."""
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    cmd = [
        "bash", str(RESOLVER),
        "--provisioner-only",
        "--root", str(root),
        "--apply",
    ]
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "wakir-provisioner-digest" in proc.stderr


def test_provisioner_only_substitutes_provisioner_pin_only(
    tmp_path: Path,
) -> None:
    """--provisioner-only with --wakir-provisioner-digest substitutes
    the bucket-init Quadlet placeholder and leaves the SPIRE+python
    placeholders untouched (skip-cosign-verify mode keeps them at
    tag-only references; the substitution is hard no-op for them)."""
    root = tmp_path / "root"
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW",
    )
    cmd = [
        "bash", str(RESOLVER),
        "--provisioner-only",
        "--wakir-provisioner-digest", SHA256_D,
        "--root", str(root),
        "--apply",
    ]
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"resolver --provisioner-only failed: stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}"
    )
    # Bucket-init Quadlet got the real digest.
    bucket_init = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert (
        f"ghcr.io/wakir-labs/wakir-provisioner:0.1.2@{SHA256_D}"
        in bucket_init
    )
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in bucket_init
    # SPIRE-Server / Agent / Containerfile placeholders are UNTOUCHED.
    server_quadlet = (
        root / "quadlet" / "wakir-spire-server.container"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" in server_quadlet
    agent_quadlet = (
        root / "quadlet" / "wakir-spire-agent.container"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" in agent_quadlet
    python_containerfile = (
        root / "infra/spire/federation/provisioner/Containerfile"
    ).read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" in python_containerfile


def test_provisioner_only_dry_run_does_not_mutate(tmp_path: Path) -> None:
    """--provisioner-only without --apply is a dry-run."""
    root = tmp_path / "root"
    image_line = (
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    )
    _build_skeleton(root, image_line)
    before = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    cmd = [
        "bash", str(RESOLVER),
        "--provisioner-only",
        "--wakir-provisioner-digest", SHA256_D,
        "--root", str(root),
    ]
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    after = (
        root / "quadlet" / "wakir-nats-kv-bucket-init.container"
    ).read_text()
    assert before == after, "dry-run mutated file"


# ----------------------------------------------------------------------
# A concrete pin is something to check, not something to skip.
#
# Added 2026-09-21, after the live bring-up on wakir-pilot died at
# bootstrap step 7 with ``manifest unknown``. The Quadlet carried a
# concrete wakir-provisioner digest that the registry never served. The
# resolver had just resolved the correct one, saw no DIGEST_PENDING
# placeholder in the file, printed ``note: no placeholder; skip`` and
# handed it through. The failure surfaced two steps later, inside
# podman, four months after the pin was written.
# ----------------------------------------------------------------------

_LIVE_DIGEST = "sha256:" + "a1" * 32
_STALE_DIGEST = "sha256:" + "b2" * 32


def _skeleton_with_concrete_provisioner_pin(root: Path, digest: str) -> None:
    _build_skeleton(
        root,
        "Image=ghcr.io/wakir-labs/wakir-provisioner:0.1.4@" + digest,
    )


def _run_with_provisioner_digest(
    root: Path, digest: str, *, extra: list[str] | None = None
) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        str(RESOLVER),
        "--spire-server-digest", SHA256_A,
        "--spire-agent-digest", SHA256_B,
        "--python-digest", SHA256_C,
        "--wakir-provisioner-digest", digest,
        "--root", str(root),
        "--apply",
    ]
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def test_stale_concrete_pin_fails_loudly(tmp_path: Path) -> None:
    """The pin in the file disagrees with the digest the tag resolves
    to. This is the wakir-pilot case, and it must stop the resolver."""
    _skeleton_with_concrete_provisioner_pin(tmp_path, _STALE_DIGEST)
    proc = _run_with_provisioner_digest(tmp_path, _LIVE_DIGEST)
    assert proc.returncode != 0, (
        "a stale concrete pin exited 0; that is the defect this test "
        f"exists for.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    combined = proc.stdout + proc.stderr
    assert _STALE_DIGEST in combined and _LIVE_DIGEST in combined, (
        "the error must name BOTH digests -- an operator who only sees "
        "'pin mismatch' has to go find them by hand"
    )


def test_matching_concrete_pin_passes(tmp_path: Path) -> None:
    """Negative control. Without this, a check that always fails would
    pass the test above and nobody would notice."""
    _skeleton_with_concrete_provisioner_pin(tmp_path, _LIVE_DIGEST)
    proc = _run_with_provisioner_digest(tmp_path, _LIVE_DIGEST)
    assert proc.returncode == 0, (
        "a pin that already matches the live digest must not fail.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def test_synthetic_digests_flag_suppresses_the_check_but_says_so(
    tmp_path: Path,
) -> None:
    """The hermetic e2e-container lane stubs skopeo and therefore hands
    the resolver a fictional digest. It may opt out -- loudly."""
    _skeleton_with_concrete_provisioner_pin(tmp_path, _STALE_DIGEST)
    proc = _run_with_provisioner_digest(
        tmp_path, _LIVE_DIGEST, extra=["--synthetic-digests"]
    )
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "--synthetic-digests" in combined and "NOT checking" in combined, (
        "the opt-out must announce itself; a quiet opt-out is how a "
        "check stops running without anyone deciding that it should"
    )


def test_only_the_hermetic_lane_declares_its_digests_synthetic() -> None:
    """Guards the escape hatch. If a shipped script, workflow or runbook
    ever sets this, the check is off on a path that pulls real images."""
    offenders = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix not in {".sh", ".yml", ".yaml", ".md", ".py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "WAKIR_SYNTHETIC_DIGESTS" not in text:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        # The resolver/bootstrap implement the flag; the e2e lane and
        # this test are its only declared users.
        allowed = (
            rel == "infra/spire/federation/wakir-pilot-bootstrap.sh"
            or rel == "tests/infra/test_pilot_bringup_e2e_container.py"
            or rel == "tests/orchestrator/test_proxmox_resolve_image_pins.py"
        )
        if not allowed:
            offenders.append(rel)
    assert not offenders, (
        "WAKIR_SYNTHETIC_DIGESTS appears outside the hermetic lane: "
        f"{offenders}. Declaring digests synthetic turns off the "
        "concrete-pin check; on a path that really pulls images that "
        "is how wakir-pilot ended up pinned to a manifest that did "
        "not exist."
    )
