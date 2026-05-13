# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Containerfile invariants for the wakir-provisioner image
(Phase-2 Sprint-9 Tag-4).

The image scope is documented in
``infra/spire/federation/provisioner/README.md``. This test suite is
the on-disk-syntax gate: it asserts the structural invariants the
build, publish, and operate paths depend on without ever invoking
``podman`` / ``buildah`` / ``docker`` / a network resolver.

Coverage axes:

  * The Containerfile uses a digest-pinned ``FROM`` line referencing
    ``docker.io/library/python:3.13-slim`` (or its placeholder).
  * The image copies a hash-pinned ``requirements.txt`` and installs
    via ``pip install --require-hashes``.
  * The runtime user is non-root (uid 1000, gid 1000) matching the
    consuming Quadlet's ``User=`` / ``Group=`` directives.
  * The Containerfile carries the documented OCI image labels for
    title, description, licenses, and source.
  * The Apache-2.0 SPDX identifier is present in the file header.

Sandbox boundary: this test reads files on disk only — no podman /
buildah / pip invocations, no network. The live build verification
is Operator-Hand per ``feedback_sandbox_host_trennung.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
CONTAINERFILE = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "provisioner"
    / "Containerfile"
)
REQUIREMENTS = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "provisioner"
    / "requirements.txt"
)


PLACEHOLDER = "DIGEST_PENDING_TOMAS_REVIEW"

_FROM_LINE_RE = re.compile(
    r"^FROM\s+docker\.io/library/python:(?P<tag>\S+?)"
    r"@sha256:(?P<digest>\S+)\s*$",
    re.MULTILINE,
)


def _read(path: Path) -> str:
    assert path.exists(), f"required file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_containerfile_exists() -> None:
    assert CONTAINERFILE.exists(), (
        f"missing wakir-provisioner Containerfile: {CONTAINERFILE}"
    )


def test_containerfile_has_spdx_apache_2_0_header() -> None:
    """The Containerfile MUST carry the Apache-2.0 SPDX identifier in
    the first two lines so license tooling can pick it up without
    parsing the rest of the file."""
    text = _read(CONTAINERFILE)
    head = "\n".join(text.splitlines()[:3])
    assert "SPDX-License-Identifier: Apache-2.0" in head, (
        "Containerfile is missing the SPDX Apache-2.0 header"
    )


def test_from_line_pins_python_base_layer() -> None:
    """The ``FROM`` line MUST pin ``docker.io/library/python:3.13-slim``
    by digest. Bare-tag references silently follow registry drift."""
    text = _read(CONTAINERFILE)
    match = _FROM_LINE_RE.search(text)
    assert match, (
        f"{CONTAINERFILE}: no canonical pinned FROM line found; "
        f"expected FROM docker.io/library/python:<tag>@sha256:<digest>"
    )
    assert match.group("tag") == "3.13-slim", (
        f"unexpected base-layer tag: {match.group('tag')!r}; "
        f"expected '3.13-slim'"
    )


def test_from_line_digest_is_placeholder_or_real() -> None:
    """The digest slot MUST be either the placeholder token or a real
    64-hex sha256 digest."""
    text = _read(CONTAINERFILE)
    match = _FROM_LINE_RE.search(text)
    assert match
    digest = match.group("digest")
    assert digest == PLACEHOLDER or re.fullmatch(r"[a-f0-9]{64}", digest), (
        f"non-canonical FROM digest: {digest!r}; "
        f"must be {PLACEHOLDER} or 64-hex sha256"
    )


def test_pip_install_uses_require_hashes() -> None:
    """Build-input supply-chain provenance is enforced via
    ``pip install --require-hashes``. A regression that drops the
    flag silently re-opens the build to unhashed wheel resolution."""
    text = _read(CONTAINERFILE)
    assert "--require-hashes" in text, (
        "Containerfile's pip install line MUST carry --require-hashes "
        "(supply-chain hash-pin enforcement)"
    )


def test_pip_install_consumes_requirements_file() -> None:
    """The ``pip install`` step MUST reference the in-repo
    ``requirements.txt`` so the hash-pinned wheel set is the
    single-source-of-truth."""
    text = _read(CONTAINERFILE)
    assert "/tmp/requirements.txt" in text, (
        "Containerfile must COPY + reference the requirements.txt "
        "file (single source of truth for hash-pinned wheels)"
    )
    assert "requirements.txt" in text


def test_pip_install_disables_cache_and_bytecode() -> None:
    """Image hygiene: ``--no-cache-dir`` keeps the pip wheel cache
    out of the image layer; ``--no-compile`` keeps the ``.pyc``
    byte-compile cache out (reduces image size and avoids the
    write-on-import semantics inside a ``ReadOnly=true`` container)."""
    text = _read(CONTAINERFILE)
    assert "--no-cache-dir" in text, (
        "Containerfile pip install MUST use --no-cache-dir"
    )
    assert "--no-compile" in text, (
        "Containerfile pip install MUST use --no-compile"
    )


def test_runtime_user_is_non_root() -> None:
    """The runtime user MUST be non-root (uid 1000, gid 1000) to
    match the consuming Quadlet's ``User=`` / ``Group=`` posture."""
    text = _read(CONTAINERFILE)
    assert re.search(r"^USER\s+1000:1000\s*$", text, re.MULTILINE), (
        "Containerfile MUST set USER 1000:1000 for runtime parity "
        "with the consuming Quadlet"
    )
    # The user must also be defined (useradd / groupadd).
    assert "groupadd" in text and "useradd" in text, (
        "Containerfile MUST create the wakir 1000:1000 user/group "
        "explicitly so USER 1000:1000 resolves to a real principal"
    )


def test_workdir_is_repo_bind_mount_target() -> None:
    """The ``WORKDIR`` MUST be ``/opt/wakir-runtime`` to match the
    consuming Quadlet's bind-mount layout."""
    text = _read(CONTAINERFILE)
    assert re.search(
        r"^WORKDIR\s+/opt/wakir-runtime\s*$", text, re.MULTILINE
    ), "Containerfile MUST set WORKDIR /opt/wakir-runtime"


def test_oci_labels_carry_provenance_metadata() -> None:
    """The image MUST carry OCI image labels for title, description,
    license, and source so registries / scanners can surface the
    provenance metadata."""
    text = _read(CONTAINERFILE)
    required_labels = (
        "org.opencontainers.image.title",
        "org.opencontainers.image.description",
        "org.opencontainers.image.licenses",
        "org.opencontainers.image.source",
    )
    for label in required_labels:
        assert label in text, (
            f"Containerfile is missing required OCI label {label}"
        )
    # License label MUST be Apache-2.0 (single source of truth for
    # the image-level licence; per-wheel licences live in the wheels
    # themselves).
    assert 'org.opencontainers.image.licenses="Apache-2.0"' in text, (
        "Containerfile licence label MUST be Apache-2.0"
    )


def test_requirements_file_exists() -> None:
    """The Containerfile COPIES requirements.txt — the file MUST
    exist on disk."""
    assert REQUIREMENTS.exists(), (
        f"missing wakir-provisioner requirements file: {REQUIREMENTS}"
    )
