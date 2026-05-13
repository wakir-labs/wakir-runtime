# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic image-pin syntax invariants for the
``ghcr.io/wakir-labs/wakir-provisioner`` image referenced from the
Phase-2 Sprint-9 Tag-4 per-org NATS-KV bucket-init Quadlet.

Sibling to ``tests/infra/test_python_image_pin_form.py`` (the python
base layer pin asserted on the Containerfile) and to
``infra/spire/federation/tests/test_image_pin_digest_form.py`` (the
SPIRE-Server / SPIRE-Agent pins). All three share the same on-disk
SYNTAX invariants; this file targets the published-image surface:

  * The Quadlet pins
    ``ghcr.io/wakir-labs/wakir-provisioner:<tag>@sha256:<digest>``.
  * ``<tag>`` matches the documented Sprint-9 Tag-4 baseline
    (``0.1.0``).
  * ``<digest>`` is EITHER the placeholder token
    ``DIGEST_PENDING_TOMAS_REVIEW`` OR a canonical 64-hex sha256
    digest.
  * IMAGE_PINS.md lists the image in its inventory table and
    documents the GHCR-Sigstore resolver recipe.

Sandbox boundary: this test reads files on disk only — no network,
no cosign / skopeo / crane invocations against ``ghcr.io``. Live
verification is Operator-Hand per
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
EXPECTED_TAG = "0.1.0"
EXPECTED_IMAGE_PATH = "ghcr.io/wakir-labs/wakir-provisioner"

_DIGEST_RE = rf"(?:{PLACEHOLDER}|[a-f0-9]{{64}})"
_PROVISIONER_PIN_RE = re.compile(
    rf"ghcr\.io/wakir-labs/wakir-provisioner:(?P<tag>[^@\s\"']+)"
    rf"@sha256:(?P<digest>{_DIGEST_RE})"
)


def _read(path: Path) -> str:
    assert path.exists(), f"required pin source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_quadlet_file_exists() -> None:
    assert QUADLET_FILE.exists(), (
        f"missing per-org NATS-KV bucket-init quadlet: {QUADLET_FILE}"
    )


def test_provisioner_pin_uses_canonical_form() -> None:
    """The Quadlet MUST pin
    ``ghcr.io/wakir-labs/wakir-provisioner:<tag>@sha256:<digest>``.

    A bare-tag reference like ``ghcr.io/wakir-labs/wakir-provisioner:0.1.0``
    (without the ``@sha256:`` suffix) silently follows whatever the
    registry serves at pull time — exactly the supply-chain drift the
    digest-pin is meant to close.
    """
    text = _read(QUADLET_FILE)
    matches = list(_PROVISIONER_PIN_RE.finditer(text))
    assert matches, (
        f"{QUADLET_FILE}: no canonical wakir-provisioner image-pin "
        f"found; expected "
        f"ghcr.io/wakir-labs/wakir-provisioner:<tag>@sha256:<digest>"
    )


def test_provisioner_pin_tag_matches_baseline() -> None:
    """The pinned tag is ``0.1.0`` per the Sprint-9 Tag-4 baseline.
    Drift to a different tag must be reflected here AND in
    IMAGE_PINS.md before it lands."""
    text = _read(QUADLET_FILE)
    tags = {m.group("tag") for m in _PROVISIONER_PIN_RE.finditer(text)}
    assert tags == {EXPECTED_TAG}, (
        f"unexpected wakir-provisioner pin tag(s) {tags}; "
        f"expected exactly {{{EXPECTED_TAG!r}}}"
    )


def test_provisioner_pin_digest_is_placeholder_or_real() -> None:
    """The digest slot MUST be either the placeholder token or a real
    64-hex sha256 digest."""
    text = _read(QUADLET_FILE)
    digests = [
        m.group("digest") for m in _PROVISIONER_PIN_RE.finditer(text)
    ]
    assert digests, "no wakir-provisioner digest found in quadlet"
    for d in digests:
        assert d == PLACEHOLDER or re.fullmatch(r"[a-f0-9]{64}", d), (
            f"non-canonical digest slot: {d!r}; "
            f"must be {PLACEHOLDER} or 64-hex sha256"
        )


def test_image_pins_md_references_wakir_provisioner() -> None:
    """IMAGE_PINS.md MUST list the wakir-provisioner image in its
    inventory table and reference the consuming Quadlet file by
    name."""
    text = _read(IMAGE_PINS_MD)
    assert EXPECTED_IMAGE_PATH in text, (
        f"IMAGE_PINS.md does not mention {EXPECTED_IMAGE_PATH}"
    )
    assert QUADLET_FILE.name in text, (
        f"IMAGE_PINS.md does not reference the consuming quadlet "
        f"file {QUADLET_FILE.name}"
    )


def test_image_pins_md_documents_sigstore_resolver_recipe() -> None:
    """IMAGE_PINS.md MUST document the Sigstore-keyless resolver
    recipe for the wakir-provisioner image. The recipe mirrors the
    SPIRE-server / agent path but pins the OIDC identity to the
    wakir-labs build workflow."""
    text = _read(IMAGE_PINS_MD)
    assert "cosign verify" in text
    # The §2.5 anchor names the wakir-provisioner-specific
    # subsection and the OIDC issuer.
    assert "wakir-provisioner" in text
    assert "token.actions.githubusercontent.com" in text


def test_quadlet_active_image_is_wakir_provisioner() -> None:
    """The active ``Image=`` directive in the Quadlet MUST reference
    the wakir-provisioner image, not the python base layer.

    A regression that re-points the ``Image=`` directive at
    ``docker.io/library/python`` (or any other image that does not
    carry the four runtime wheels the provisioner needs) re-opens
    the Tag-1 wheel-availability gap that Bug 6 exposed on the
    Pilot-VM bring-up.
    """
    text = _read(QUADLET_FILE)
    active_image_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or not line.startswith("Image="):
            continue
        active_image_lines.append(line)
    assert active_image_lines, (
        f"no active Image= directive found in {QUADLET_FILE}"
    )
    for line in active_image_lines:
        assert EXPECTED_IMAGE_PATH in line, (
            f"active Image= directive does not reference "
            f"{EXPECTED_IMAGE_PATH}: {line}"
        )
