# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic image-pin syntax invariants for the python:3.13-slim base
image.

Phase-2 Sprint-9 Tag-1/3 history: the per-org NATS-KV bucket-init
Quadlet (``quadlet/wakir-nats-kv-bucket-init.container``) referenced
``docker.io/library/python:3.13-slim`` directly, and this test
asserted the pin on the Quadlet.

Phase-2 Sprint-9 Tag-4 re-target: the Quadlet now references the
dedicated ``ghcr.io/wakir-labs/wakir-provisioner`` image (Mira-Bug-
Bilanz 2026-05-13, Bug 6 — the slim image does not ship ``nats-py``
nor ``cryptography``). The ``python:3.13-slim`` reference moved to
the ``wakir-provisioner`` Containerfile's ``FROM`` line:
``infra/spire/federation/provisioner/Containerfile``. This test was
updated to target the Containerfile.

Sibling to ``infra/spire/federation/tests/test_image_pin_digest_form.py``
(SPIRE-Server / SPIRE-Agent pins) and to
``tests/infra/test_wakir_provisioner_image_pin_form.py`` (the
published wakir-provisioner image pin). All three share the same
on-disk SYNTAX invariants:

  * The pin uses a canonical ``<image>:<tag>@sha256:<digest>`` form.
  * ``<tag>`` matches the documented Phase-2 baseline
    (``3.13-slim`` for the python base layer).
  * ``<digest>`` is EITHER the placeholder token
    ``DIGEST_PENDING_TOMAS_REVIEW`` OR a canonical 64-hex sha256
    digest.
  * IMAGE_PINS.md references the image, the DockerHub resolver
    recipe, and the referencing file.

Sandbox boundary: this test reads files on disk only — no network,
no cosign / skopeo / crane invocations against ``docker.io``. The
live verification is Operator-Hand per
``feedback_sandbox_host_trennung.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINERFILE = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "provisioner"
    / "Containerfile"
)
IMAGE_PINS_MD = (
    REPO_ROOT / "infra" / "spire" / "federation" / "IMAGE_PINS.md"
)

PLACEHOLDER = "DIGEST_PENDING_TOMAS_REVIEW"
EXPECTED_TAG = "3.13-slim"

_DIGEST_RE = rf"(?:{PLACEHOLDER}|[a-f0-9]{{64}})"
_PYTHON_PIN_RE = re.compile(
    rf"docker\.io/library/python:(?P<tag>[^@\s\"']+)"
    rf"@sha256:(?P<digest>{_DIGEST_RE})"
)


def _read(path: Path) -> str:
    assert path.exists(), f"required pin source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_containerfile_exists() -> None:
    """The wakir-provisioner Containerfile is the new consuming file
    for the python base layer (Sprint-9 Tag-4 re-target)."""
    assert CONTAINERFILE.exists(), (
        f"missing wakir-provisioner Containerfile: {CONTAINERFILE}"
    )


def test_python_pin_uses_canonical_form() -> None:
    """The Containerfile MUST pin
    ``docker.io/library/python:<tag>@sha256:<digest>``.

    A bare-tag reference like ``python:3.13-slim`` (without the
    ``@sha256:`` suffix) silently follows whatever the registry serves
    at pull time — exactly the supply-chain drift the digest-pin is
    meant to close.
    """
    text = _read(CONTAINERFILE)
    matches = list(_PYTHON_PIN_RE.finditer(text))
    assert matches, (
        f"{CONTAINERFILE}: no canonical python image-pin found; "
        f"expected docker.io/library/python:<tag>@sha256:<digest>"
    )


def test_python_pin_tag_matches_baseline() -> None:
    """The pinned tag is ``3.13-slim`` per the Sprint-9 Tag-1 / Tag-4
    baseline. Drift to a different tag (e.g. ``3.13-alpine``) is a
    surface-level decision that must be reflected here AND in
    IMAGE_PINS.md before it lands."""
    text = _read(CONTAINERFILE)
    tags = {m.group("tag") for m in _PYTHON_PIN_RE.finditer(text)}
    assert tags == {EXPECTED_TAG}, (
        f"unexpected python pin tag(s) {tags}; "
        f"expected exactly {{{EXPECTED_TAG!r}}}"
    )


def test_python_pin_digest_is_placeholder_or_real() -> None:
    """The digest slot MUST be either the placeholder token or a real
    64-hex sha256 digest. The regex enforces the alternation but this
    test makes the invariant explicit so a future loosening of the
    regex (e.g. accepting empty digests) breaks the suite."""
    text = _read(CONTAINERFILE)
    digests = [m.group("digest") for m in _PYTHON_PIN_RE.finditer(text)]
    assert digests, "no python digest found in Containerfile"
    for d in digests:
        assert d == PLACEHOLDER or re.fullmatch(r"[a-f0-9]{64}", d), (
            f"non-canonical digest slot: {d!r}; "
            f"must be {PLACEHOLDER} or 64-hex sha256"
        )


def test_image_pins_md_references_python_image() -> None:
    """IMAGE_PINS.md MUST list the python image in its inventory table
    and reference the consuming Containerfile by path."""
    text = _read(IMAGE_PINS_MD)
    assert "docker.io/library/python" in text or "python:3.13-slim" in text, (
        "IMAGE_PINS.md does not mention the python image"
    )
    # Reference the Containerfile by its path component (the table
    # lists it as ``infra/spire/federation/provisioner/Containerfile``).
    assert "provisioner/Containerfile" in text, (
        "IMAGE_PINS.md does not reference the consuming "
        "provisioner Containerfile"
    )


def test_image_pins_md_documents_dockerhub_resolver_recipe() -> None:
    """IMAGE_PINS.md MUST document the skopeo + crane cross-check
    resolver recipe for the python image. The recipe deliberately
    differs from the cosign-verify path used for the SPIRE images
    (Docker Official Images are not Sigstore-signed)."""
    text = _read(IMAGE_PINS_MD)
    assert "skopeo inspect" in text
    assert "crane digest" in text
    # The §2.4 anchor names the DockerHub-specific subsection.
    assert "DockerHub" in text or "docker.io" in text


def test_image_pins_md_flags_drift_alarm_for_python() -> None:
    """The Docker-Official-Image re-push hazard is documented as a
    drift-alarm — the resolver MUST refuse to pin silently if a
    previously-pinned digest changes upstream."""
    text = _read(IMAGE_PINS_MD)
    assert "Drift-alarm" in text or "drift" in text.lower()


def test_quadlet_no_longer_pins_python_directly() -> None:
    """Sprint-9 Tag-4 invariant: the Quadlet
    ``wakir-nats-kv-bucket-init.container`` MUST NOT carry a direct
    ``docker.io/library/python`` image pin on its active ``Image=``
    directive. The Quadlet now references
    ``ghcr.io/wakir-labs/wakir-provisioner``; the python base layer
    is exclusively a Containerfile-level concern.

    A regression that re-adds a direct python pin to the Quadlet
    would re-open the Tag-1 wheel-availability gap that Bug 6
    surfaced on the Pilot-VM bring-up.
    """
    quadlet = (
        REPO_ROOT / "quadlet" / "wakir-nats-kv-bucket-init.container"
    )
    if not quadlet.exists():
        pytest.skip(
            f"quadlet file not present at {quadlet}; nothing to assert"
        )
    text = _read(quadlet)
    # The Quadlet may MENTION python:3.13-slim in comments for
    # historical context (Bug 6 explanation), but the active
    # ``Image=`` directive MUST NOT reference the python registry
    # path directly.
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or not line.startswith("Image="):
            continue
        assert "docker.io/library/python" not in line, (
            f"regression: Quadlet ``Image=`` directive still pins "
            f"python directly: {raw}"
        )
