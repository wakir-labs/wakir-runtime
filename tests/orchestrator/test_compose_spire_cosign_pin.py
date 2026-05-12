# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-8 Cosign-Digest-Pin acceptance tests (additive to Tag-6 tests).

These tests cover the Tag-8 rebase that brings the Cosign-Digest-Pin
form (Pfad B) onto the Tag-6 SPIRE-Server-Sidecar substrate. They are
*additive* to ``test_compose_spire.py`` (16 Tag-6 invariants); they
DO NOT replace the Tag-6 hermetic-trust-domain (``example.test``)
posture or the Tag-6 networking layout.

What this file asserts that Tag-6 did not:

  * Image-pin form is the Cosign-Digest-Pin shape
    ``tag@sha256:<digest-or-placeholder>`` (Tag-6 also accepted
    tag-only, this file makes the digest-pin form mandatory).
  * The pinned tag is exactly ``1.14.6`` (Tag-6 only required
    ``>= 1.14``; Tag-8 nails the briefing version explicitly so a
    silent floor-bump can't slip through).
  * Container runs read-only-rootfs.
  * Container runs as non-root uid:gid ``1000:1000``.
  * tmpfs mount for ``/run/spire`` is declared.
  * SPIRE-Server gRPC API port is published, but only bound to
    ``127.0.0.1`` on the host (never ``0.0.0.0``).

What this file does NOT assert (deliberately):

  * Trust-domain ``wakir.dev``. Tag-6's hermetic posture pins the
    trust-domain to ``example.test`` (IANA-reserved test TLD) and that
    is the right hermetic-only choice; the Tag-7 worktree had drifted
    to ``wakir.dev`` which is the production literal. Tag-8 keeps the
    hermetic Tag-6 trust-domain. Production-trust-domain switch is a
    Phase-2.4 NATS-JWT-Auth-integration tag, not this rebase.
  * Healthcheck retries == 3 / interval == 30s exact values. Tag-6's
    healthcheck retries == 5 / interval == 10s is the more
    conservative shape for a bootstrap substrate; we keep it.

Hermetic-Status: no podman, no docker, no registry-touch. PyYAML-only
parse, same convention as ``test_compose_spire.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - pyyaml is a dev-dep
    pytest.skip("pyyaml not installed", allow_module_level=True)


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose" / "spire.yaml"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def spire_service(compose_doc: dict) -> dict:
    return compose_doc["services"]["spire-server"]


# ---------------------------------------------------------------------
# Tag-8 image-pin form: Cosign-Digest-Pin (Pfad B)
# ---------------------------------------------------------------------


def test_image_has_cosign_digest_pin_form(spire_service: dict) -> None:
    """Image MUST be ``tag@sha256:<digest-or-placeholder>``.

    Tag-6 accepted tag-only OR digest-pin; Tag-8 makes the digest-pin
    form mandatory. Both real-digest (64 hex) and the documented
    placeholder are acceptable because the Operator-Hand workflow
    fills the canonical digest after ``cosign verify`` + ``skopeo
    inspect``; the test must stay green throughout that workflow.
    """
    image = spire_service["image"]
    _, sep, digest_part = image.partition("@")
    assert sep == "@", (
        f"Tag-8 image-pin must be digest-pinned form 'tag@sha256:<digest>'; "
        f"got: {image!r}"
    )
    assert digest_part.startswith("sha256:"), (
        f"digest part must start with 'sha256:'; got: {digest_part!r}"
    )
    digest_value = digest_part[len("sha256:"):]
    is_real_digest = bool(re.fullmatch(r"[0-9a-f]{64}", digest_value))
    is_placeholder = digest_value == "DIGEST_PENDING_TOMAS_REVIEW"
    assert is_real_digest or is_placeholder, (
        f"digest must be 64-hex sha256 OR the documented placeholder "
        f"'DIGEST_PENDING_TOMAS_REVIEW'; got: {digest_value!r}"
    )


def test_image_is_from_spiffe_org_on_ghcr(spire_service: dict) -> None:
    image = spire_service["image"]
    assert image.startswith("ghcr.io/spiffe/spire-server:"), (
        f"image must come from ghcr.io/spiffe/spire-server; got: {image!r}"
    )


def test_image_has_explicit_version_tag(spire_service: dict) -> None:
    image = spire_service["image"]
    tag_part, sep, _ = image.partition("@")
    assert sep == "@", f"image must be digest-pinned; got: {image!r}"
    m = re.match(r"^ghcr\.io/spiffe/spire-server:(\d+\.\d+\.\d+)$", tag_part)
    assert m is not None, (
        f"tag part must be semver (X.Y.Z) form; got: {tag_part!r}"
    )


def test_pinned_tag_matches_briefing_version(spire_service: dict) -> None:
    """Tag-8 nails the briefing version exactly (Tag-6 was '>= 1.14')."""
    image = spire_service["image"]
    tag_part, _, _ = image.partition("@")
    assert tag_part.endswith(":1.14.6"), (
        f"tag must be exactly 1.14.6 per Sprint-6 box-briefing; got: {tag_part!r}"
    )


# ---------------------------------------------------------------------
# Tag-8 hardening additions on top of Tag-6 cap_drop/no-new-privileges
# ---------------------------------------------------------------------


def test_read_only_root_fs(spire_service: dict) -> None:
    assert spire_service.get("read_only") is True, (
        "Tag-8 hardening: container root filesystem must be read-only"
    )


def test_runs_as_non_root_user(spire_service: dict) -> None:
    user = spire_service.get("user")
    assert user == "1000:1000", (
        f"Tag-8 hardening: container must run as uid:gid 1000:1000; got: {user!r}"
    )


def test_tmpfs_for_run_spire(spire_service: dict) -> None:
    tmpfs = spire_service.get("tmpfs")
    assert tmpfs is not None, (
        "Tag-8 hardening: tmpfs mount for /run/spire must be declared "
        "since the rootfs is read-only"
    )
    entries = tmpfs if isinstance(tmpfs, list) else [tmpfs]
    run_spire = [e for e in entries if "/run/spire" in e]
    assert len(run_spire) == 1, (
        f"tmpfs must contain exactly one /run/spire entry; got: {tmpfs!r}"
    )


# ---------------------------------------------------------------------
# Tag-8 explicit loopback port mapping
# ---------------------------------------------------------------------


def test_api_port_bound_to_localhost_only(spire_service: dict) -> None:
    """The SPIRE-Server gRPC API (8081) must be host-bound on 127.0.0.1.

    The Sprint-6 substrate is single-host and the API must never be
    exposed on 0.0.0.0. Tag-6 had no ports mapping at all; Tag-8 adds
    an explicit loopback mapping so an operator can introspect the
    server from the host without exposing it.
    """
    ports = spire_service.get("ports")
    assert ports is not None, (
        "Tag-8 substrate must declare an explicit ports mapping for the gRPC API"
    )
    api_port_entries = [p for p in ports if "8081" in p]
    assert len(api_port_entries) == 1, (
        f"expected exactly one 8081 port mapping; got: {ports!r}"
    )
    entry = api_port_entries[0]
    assert entry.startswith("127.0.0.1:"), (
        f"API port must be bound to 127.0.0.1 only (never 0.0.0.0); got: {entry!r}"
    )


# ---------------------------------------------------------------------
# Test-count contract (Tag-8 rebase: 16 Tag-6 + 9 Tag-8 = 25 SPIRE-Compose)
# ---------------------------------------------------------------------


def test_tag_8_adds_nine_cosign_pin_tests_on_top_of_tag_6_sixteen() -> None:
    """Pure-contract self-check: this file MUST contribute exactly 9
    tests to the SPIRE-Compose suite. Tag-6's
    ``test_compose_spire.py`` contributes 16 (verified by separate
    collect-only run). Total SPIRE-Compose: 25.

    The 9 Tag-8 additions are:
      * 4 image-pin-form (Cosign-Digest-Pin)
      * 3 hardening (read_only, non-root-user, tmpfs)
      * 1 ports (localhost-only API)
      * 1 contract self-check (this test)
    """
    import inspect
    import sys

    module = sys.modules[__name__]
    test_fns = [
        name for name, obj in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("test_")
    ]
    assert len(test_fns) == 9, (
        f"Tag-8 cosign-pin file must contribute exactly 9 tests; "
        f"got {len(test_fns)}: {test_fns!r}"
    )
