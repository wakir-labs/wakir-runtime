# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic image-pin syntax invariants for the Phase-2 Sprint-8 Tag-4
Cosign-Digest-Pin-Resolution path.

The Federation substrate pins the SPIRE-Server and SPIRE-Agent images
across four files (two compose files + two quadlet templates). The
sandbox-boundary policy (``feedback_sandbox_host_trennung.md``)
forbids calling ``cosign verify`` against GHCR from the test surface,
so the live digest is resolved Operator-Hand. This test asserts the
SYNTAX invariants:

  * Every spire-server image-reference uses the form
    ``ghcr.io/spiffe/spire-server:<TAG>@sha256:<DIGEST>`` where
    ``<TAG>`` is the pinned semver tag and ``<DIGEST>`` is EITHER
    the placeholder token ``DIGEST_PENDING_TOMAS_REVIEW`` OR a
    canonical 64-hex sha256 digest.

  * Same for spire-agent.

  * All four files use the SAME tag literal (server-agent version
    parity invariant — upstream releases the pair together).

  * All four files use the SAME digest state — either all four
    carry the placeholder (pre-resolution) or all four carry a real
    digest (post-resolution). A half-resolved state (e.g. server
    pinned, agent placeholder) is flagged.

  * The IMAGE_PINS.md index file exists and references all four
    target files.

These are invariants on the REPO STATE, not on the upstream image
contents. The hermetic test surface catches drift on pin form; the
Operator-Hand verification catches drift on the upstream digest.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
FED_DIR = REPO_ROOT / "infra" / "spire" / "federation"
AGENT_DIR = REPO_ROOT / "infra" / "spire" / "agent"


# Files that pin the federation images.
SERVER_PIN_FILES = [
    FED_DIR / "compose" / "spire-federation.yaml",
    FED_DIR / "quadlet" / "wakir-spire-server-federation.container",
]
AGENT_PIN_FILES = [
    AGENT_DIR / "compose" / "spire-agent-federation.yaml",
    AGENT_DIR / "quadlet" / "wakir-spire-agent-federation.container",
]
ALL_PIN_FILES = SERVER_PIN_FILES + AGENT_PIN_FILES
IMAGE_PINS_MD = FED_DIR / "IMAGE_PINS.md"


# Image-reference regex: ghcr.io/spiffe/spire-{server,agent}:<TAG>@sha256:<DIGEST>
# where DIGEST is either the placeholder or a 64-hex string.
PLACEHOLDER = "DIGEST_PENDING_TOMAS_REVIEW"
_DIGEST_RE = rf"(?:{PLACEHOLDER}|[a-f0-9]{{64}})"
_SERVER_PIN_RE = re.compile(
    rf"ghcr\.io/spiffe/spire-server:(?P<tag>[^@\s\"']+)"
    rf"@sha256:(?P<digest>{_DIGEST_RE})"
)
_AGENT_PIN_RE = re.compile(
    rf"ghcr\.io/spiffe/spire-agent:(?P<tag>[^@\s\"']+)"
    rf"@sha256:(?P<digest>{_DIGEST_RE})"
)


def _read(path: Path) -> str:
    assert path.exists(), f"pinned-image source file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_server_pin_files_exist() -> None:
    for p in SERVER_PIN_FILES:
        assert p.exists(), f"missing server pin file: {p}"


def test_agent_pin_files_exist() -> None:
    for p in AGENT_PIN_FILES:
        assert p.exists(), f"missing agent pin file: {p}"


def test_server_pin_uses_canonical_form() -> None:
    """Every spire-server image reference MUST match
    ``ghcr.io/spiffe/spire-server:<tag>@sha256:<digest>``."""
    for path in SERVER_PIN_FILES:
        text = _read(path)
        # There must be at least one match in each file.
        matches = list(_SERVER_PIN_RE.finditer(text))
        assert matches, (
            f"{path}: no canonical server image-pin found; "
            f"expected form ghcr.io/spiffe/spire-server:<tag>@sha256:<digest>"
        )


def test_agent_pin_uses_canonical_form() -> None:
    """Every spire-agent image reference MUST match
    ``ghcr.io/spiffe/spire-agent:<tag>@sha256:<digest>``."""
    for path in AGENT_PIN_FILES:
        text = _read(path)
        matches = list(_AGENT_PIN_RE.finditer(text))
        assert matches, (
            f"{path}: no canonical agent image-pin found; "
            f"expected form ghcr.io/spiffe/spire-agent:<tag>@sha256:<digest>"
        )


def test_server_agent_tag_version_parity() -> None:
    """The SPIRE-Server and SPIRE-Agent images MUST be pinned to the
    SAME version tag (upstream releases the pair together)."""
    server_tags: set[str] = set()
    agent_tags: set[str] = set()
    for path in SERVER_PIN_FILES:
        text = _read(path)
        for m in _SERVER_PIN_RE.finditer(text):
            server_tags.add(m.group("tag"))
    for path in AGENT_PIN_FILES:
        text = _read(path)
        for m in _AGENT_PIN_RE.finditer(text):
            agent_tags.add(m.group("tag"))

    assert len(server_tags) == 1, (
        f"multiple distinct server tags pinned: {server_tags}; "
        "all server pins must use the same tag"
    )
    assert len(agent_tags) == 1, (
        f"multiple distinct agent tags pinned: {agent_tags}; "
        "all agent pins must use the same tag"
    )
    assert server_tags == agent_tags, (
        f"server tag {server_tags} != agent tag {agent_tags}; "
        "version-parity invariant breach"
    )


def test_digest_resolution_state_consistent() -> None:
    """All four pin files MUST share the SAME digest-resolution state:
    either all placeholders (pre-resolution) or all real digests
    (post-resolution). A half-resolved state is flagged."""
    states: dict[str, str] = {}  # path-str -> "placeholder" | "resolved"
    for path in ALL_PIN_FILES:
        text = _read(path)
        per_file_states: set[str] = set()
        # Combine server + agent matches in a single sweep — same file
        # could carry both in principle (although Tag-4 splits them).
        for regex in (_SERVER_PIN_RE, _AGENT_PIN_RE):
            for m in regex.finditer(text):
                digest = m.group("digest")
                if digest == PLACEHOLDER:
                    per_file_states.add("placeholder")
                else:
                    per_file_states.add("resolved")
        if not per_file_states:
            continue
        # Within a single file, MIXED is forbidden.
        assert len(per_file_states) == 1, (
            f"{path}: mixed placeholder/resolved digests; "
            "resolution must be applied atomically per file"
        )
        states[str(path)] = next(iter(per_file_states))

    # Across the four files, MIXED is also forbidden.
    unique_states = set(states.values())
    assert len(unique_states) <= 1, (
        "half-resolved digest state across pin files: "
        f"{states}; resolution must be applied atomically across "
        "server + agent pins (see IMAGE_PINS.md §2.3)"
    )


def test_image_pins_md_present_and_references_all_pin_files() -> None:
    """The IMAGE_PINS.md index file MUST exist and reference each of
    the four pinned files by filename."""
    assert IMAGE_PINS_MD.exists(), f"missing: {IMAGE_PINS_MD}"
    text = IMAGE_PINS_MD.read_text(encoding="utf-8")
    for path in ALL_PIN_FILES:
        assert path.name in text, (
            f"IMAGE_PINS.md does not reference {path.name}; "
            "the resolution recipe must list all four target files"
        )


def test_image_pins_md_documents_cosign_verify() -> None:
    """The index MUST document the ``cosign verify`` invocation so an
    operator can reproduce the Operator-Hand resolution path."""
    text = IMAGE_PINS_MD.read_text(encoding="utf-8")
    assert "cosign verify" in text
    assert "ghcr.io/spiffe/spire-server" in text
    assert "ghcr.io/spiffe/spire-agent" in text
    assert "certificate-oidc-issuer" in text


def test_image_pins_md_documents_sandbox_boundary() -> None:
    """The index MUST cite the sandbox-vs-host policy that gates this
    workflow."""
    text = IMAGE_PINS_MD.read_text(encoding="utf-8")
    assert "feedback_sandbox_host_trennung" in text or "Operator-Hand" in text


def test_pinned_tag_matches_documented_baseline() -> None:
    """The documented pin tag (Tag-4 baseline) is 1.14.6 per Tag-2 +
    Tag-3 acceptance. This test catches accidental tag-drift."""
    expected_tag = "1.14.6"
    for path in SERVER_PIN_FILES:
        text = _read(path)
        for m in _SERVER_PIN_RE.finditer(text):
            assert m.group("tag") == expected_tag, (
                f"{path}: server pin tag {m.group('tag')!r} != "
                f"expected baseline {expected_tag!r}"
            )
    for path in AGENT_PIN_FILES:
        text = _read(path)
        for m in _AGENT_PIN_RE.finditer(text):
            assert m.group("tag") == expected_tag, (
                f"{path}: agent pin tag {m.group('tag')!r} != "
                f"expected baseline {expected_tag!r}"
            )
