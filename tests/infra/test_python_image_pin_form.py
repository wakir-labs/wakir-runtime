# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic image-pin syntax invariants for the python:3.13-slim base
image used by the Phase-2 Sprint-9 Tag-1 per-org NATS-KV bucket-init
Quadlet.

Sibling to ``infra/spire/federation/tests/test_image_pin_digest_form.py``
which covers the SPIRE-Server / SPIRE-Agent image pins. The
python-base image lives on DockerHub (not GHCR / Sigstore), so the
live-resolution path is different (skopeo + crane only, no
``cosign verify``) — but the on-disk SYNTAX invariants are identical:

  * The pin uses the canonical
    ``docker.io/library/python:<tag>@sha256:<digest>`` form.
  * ``<tag>`` matches the documented Phase-2 baseline (``3.13-slim``).
  * ``<digest>`` is EITHER the placeholder token
    ``DIGEST_PENDING_TOMAS_REVIEW`` OR a canonical 64-hex sha256
    digest.
  * The IMAGE_PINS.md index file references the python image, the
    DockerHub resolver recipe, and the referencing Quadlet file.

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
QUADLET_FILE = REPO_ROOT / "quadlet" / "wakir-nats-kv-bucket-init.container"
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


def test_quadlet_file_exists() -> None:
    assert QUADLET_FILE.exists(), (
        f"missing per-org NATS-KV bucket-init quadlet: {QUADLET_FILE}"
    )


def test_python_pin_uses_canonical_form() -> None:
    """The quadlet MUST pin ``docker.io/library/python:<tag>@sha256:<digest>``.

    A bare-tag reference like ``python:3.13-slim`` (without the
    ``@sha256:`` suffix) silently follows whatever the registry serves
    at pull time — exactly the supply-chain drift the digest-pin is
    meant to close.
    """
    text = _read(QUADLET_FILE)
    matches = list(_PYTHON_PIN_RE.finditer(text))
    assert matches, (
        f"{QUADLET_FILE}: no canonical python image-pin found; "
        f"expected docker.io/library/python:<tag>@sha256:<digest>"
    )


def test_python_pin_tag_matches_baseline() -> None:
    """The pinned tag is ``3.13-slim`` per the Sprint-9 Tag-1 ADR-0048
    baseline. Drift to a different tag (e.g. ``3.13-alpine``) is a
    surface-level decision that must be reflected here AND in
    IMAGE_PINS.md before it lands."""
    text = _read(QUADLET_FILE)
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
    text = _read(QUADLET_FILE)
    digests = [m.group("digest") for m in _PYTHON_PIN_RE.finditer(text)]
    assert digests, "no python digest found in quadlet"
    for d in digests:
        assert d == PLACEHOLDER or re.fullmatch(r"[a-f0-9]{64}", d), (
            f"non-canonical digest slot: {d!r}; "
            f"must be {PLACEHOLDER} or 64-hex sha256"
        )


def test_image_pins_md_references_python_image() -> None:
    """IMAGE_PINS.md MUST list the python image in its inventory table
    and reference the consuming quadlet file by name."""
    text = _read(IMAGE_PINS_MD)
    assert "docker.io/library/python" in text or "python:3.13-slim" in text, (
        "IMAGE_PINS.md does not mention the python image"
    )
    assert QUADLET_FILE.name in text, (
        f"IMAGE_PINS.md does not reference the consuming quadlet "
        f"file {QUADLET_FILE.name}"
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
