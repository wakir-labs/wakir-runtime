# SPDX-License-Identifier: BUSL-1.1
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
  * The BSL-1.1 SPDX identifier is present in the file header
    (AR-Decision 2026-05-13: Apache-2.0 -> BSL 1.1 relicense,
    consistent with the WAT-Pipeline-Server Phase-1a BSL pattern
    per ADR-0034).
  * The image-level OCI licence label MUST be ``BUSL-1.1``.
  * The accompanying ``LICENSE-BSL.md`` MUST exist alongside the
    Containerfile so license-scanners can pick up the canonical
    header next to the source.

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
LICENSE_BSL = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "provisioner"
    / "LICENSE-BSL.md"
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


def test_containerfile_has_spdx_busl_1_1_header() -> None:
    """The Containerfile MUST carry the BUSL-1.1 SPDX identifier in
    the first two lines so license tooling can pick it up without
    parsing the rest of the file.

    AR-Decision 2026-05-13: the provisioner module relicensed from
    Apache-2.0 to BSL 1.1, consistent with the WAT-Pipeline-Server
    Phase-1a BSL pattern (ADR-0034). The canonical SPDX identifier
    is ``BUSL-1.1`` per the SPDX licence list.
    """
    text = _read(CONTAINERFILE)
    head = "\n".join(text.splitlines()[:3])
    assert "SPDX-License-Identifier: BUSL-1.1" in head, (
        "Containerfile is missing the SPDX BUSL-1.1 header"
    )
    # Defensive regression guard: the previous Apache-2.0 header
    # must NOT linger anywhere in the first three lines.
    assert "SPDX-License-Identifier: Apache-2.0" not in head, (
        "Containerfile still carries the stale Apache-2.0 SPDX "
        "header on the first three lines; the AR-Decision "
        "2026-05-13 relicense was incomplete"
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
    # License label MUST be BUSL-1.1 (single source of truth for
    # the image-level licence; per-wheel licences live in the wheels
    # themselves and are reachable via ``pip show <pkg>``).
    # AR-Decision 2026-05-13: Apache-2.0 -> BSL 1.1 relicense.
    assert 'org.opencontainers.image.licenses="BUSL-1.1"' in text, (
        "Containerfile licence label MUST be BUSL-1.1 (AR-Decision "
        "2026-05-13 relicense from Apache-2.0)"
    )
    # Defensive regression guard: the previous Apache-2.0 label must
    # NOT linger.
    assert (
        'org.opencontainers.image.licenses="Apache-2.0"' not in text
    ), (
        "Containerfile still carries the stale Apache-2.0 image "
        "licence label; the AR-Decision 2026-05-13 relicense was "
        "incomplete"
    )


def test_requirements_file_exists() -> None:
    """The Containerfile COPIES requirements.txt — the file MUST
    exist on disk."""
    assert REQUIREMENTS.exists(), (
        f"missing wakir-provisioner requirements file: {REQUIREMENTS}"
    )


def test_license_bsl_file_exists_alongside_containerfile() -> None:
    """The BSL 1.1 canonical header MUST ship as a sibling file to
    the Containerfile so license-scanners can pick it up without
    walking up the repository tree.

    AR-Decision 2026-05-13: the provisioner module carries its own
    BSL header (independent Change Date from the ``wat/`` module's
    BSL header).
    """
    assert LICENSE_BSL.exists(), (
        f"missing canonical BSL 1.1 header alongside the "
        f"Containerfile: {LICENSE_BSL}"
    )
    body = LICENSE_BSL.read_text(encoding="utf-8")
    # The header must name the Licensor, the Licensed Work, the
    # Additional Use Grant, the Change Date, and the Change License
    # — the five mandatory BSL 1.1 fields per the canonical template
    # at https://mariadb.com/bsl11/.
    for field in (
        "Licensor",
        "Licensed Work",
        "Additional Use Grant",
        "Change Date",
        "Change License",
    ):
        assert field in body, (
            f"LICENSE-BSL.md is missing mandatory BSL 1.1 field "
            f"{field!r}"
        )
    # The Change Date MUST be the documented 2030-05-13 (four years
    # after the first BSL-licensed publication of
    # ``wakir-provisioner:0.1.2``).
    assert "2030-05-13" in body, (
        "LICENSE-BSL.md is missing the documented Change Date "
        "2030-05-13"
    )
    # The Change License MUST be Apache-2.0 (the BSL contract:
    # automatic conversion to Apache-2.0 on the Change Date).
    assert "Apache License, Version 2.0" in body, (
        "LICENSE-BSL.md is missing the documented Change License "
        "Apache License, Version 2.0"
    )


def test_containerfile_has_no_active_entrypoint() -> None:
    """Sprint-9 Tag-6 (Bug 6 from Live-Bring-up-2-Bilanz 2026-05-14):
    the image is STRICTLY caller-driven. No baked ``ENTRYPOINT``.

    The v0.1.2 image previously baked ``ENTRYPOINT ["python3"]`` plus
    a default ``CMD ["--version"]``. The bucket-init Quadlet supplied
    its own ``Exec=python3 /opt/wakir/bin/nats-kv-bucket-provision
    ...`` line; the result was the entrypoint+exec concatenation
    ``python3 python3 /opt/wakir/bin/...`` where the second
    ``python3`` was interpreted as a script path relative to
    ``WORKDIR=/opt/wakir-runtime``. The container crashed at unit
    start with ``python3: can't open file
    '/opt/wakir-runtime/python3'``.

    The Tag-6 fix removes both ``ENTRYPOINT`` and ``CMD`` as defence-
    in-depth: the image MUST not silently re-introduce the doubled-
    interpreter bug for any future caller.

    A commented-out ``# ENTRYPOINT`` is fine (it documents intent);
    only an active directive is rejected.
    """
    text = _read(CONTAINERFILE)
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^\s*ENTRYPOINT\b", raw):
            raise AssertionError(
                f"Containerfile carries active ENTRYPOINT directive: "
                f"{raw!r}; Sprint-9 Tag-6 contract forbids baked "
                f"entrypoints for the wakir-provisioner image (the "
                f"caller supplies the interpreter)"
            )


def test_containerfile_has_no_active_cmd() -> None:
    """Sprint-9 Tag-6: companion to the no-ENTRYPOINT invariant. The
    image MUST NOT bake a default ``CMD`` either; the bucket-init
    Quadlet is the canonical caller and is explicit about every
    argument including the interpreter."""
    text = _read(CONTAINERFILE)
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^\s*CMD\b", raw):
            raise AssertionError(
                f"Containerfile carries active CMD directive: "
                f"{raw!r}; Sprint-9 Tag-6 contract forbids baked "
                f"default commands for the wakir-provisioner image"
            )


def test_containerfile_version_label_matches_bsl_relicense_tag() -> None:
    """The image-version label MUST be ``0.1.2`` — the tag bump that
    accompanies the AR-Decision 2026-05-13 BSL relicense.

    The tag bump exists so the BSL-relicensed artefact carries a
    distinct immutable tag from the Apache-2.0 v0.1.1 artefact;
    consumers pulling ``0.1.1`` continue to see the Apache-2.0
    label, consumers pulling ``0.1.2`` see the BSL-1.1 label.
    """
    text = _read(CONTAINERFILE)
    assert (
        'org.opencontainers.image.version="0.1.2"' in text
    ), (
        "Containerfile version label MUST be 0.1.2 (BSL-1.1 "
        "relicense tag)"
    )
