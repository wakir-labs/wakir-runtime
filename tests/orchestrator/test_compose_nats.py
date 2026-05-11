# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic tests for ``compose/nats.yaml`` — the Phase-1b Sprint-2
# Box-3 substrate file. These tests are pure compose-parse + invariant
# assertions; no container engine, no network, no live NATS.
#
# Test plan (hermetic):
#   1. compose-parse: the file is valid YAML and has the expected
#      top-level shape (``services``, ``volumes``, ``networks``).
#   2. nats-service-definition: the ``nats`` service points at the
#      pinned image tag, runs JetStream, exposes ports loopback-only,
#      mounts the named JetStream volume, and has a health probe.
#   3. image-pin form: the image tag is one of {tag-only,
#      digest-pinned}; both are valid Box-3 forms.
#   4. bucket-init alignment: the four documented Phase-1 bucket
#      names from ``scripts/init-nats-buckets.py`` are referenced
#      explicitly somewhere in the compose-file commentary, so a
#      future operator who reads only the compose file knows what
#      buckets the substrate is sized for.
#   5. hardening: cap_drop ALL, no-new-privileges, restart-policy
#      present.
#   6. health-check probe shape (CMD-SHELL + JetStream HTTP endpoint).

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - pyyaml is a dev-dep
    pytest.skip("pyyaml not installed", allow_module_level=True)


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose" / "nats.yaml"
INIT_SCRIPT = REPO_ROOT / "scripts" / "init-nats-buckets.py"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    """Parse ``compose/nats.yaml`` once per test module."""
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), "compose/nats.yaml top-level must be a mapping"
    return doc


@pytest.fixture(scope="module")
def compose_text() -> str:
    """Raw text of the compose file for commentary-grep tests."""
    return COMPOSE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def init_script_module():
    """Load the bucket initialiser module by file path.

    The script's filename is hyphenated (``init-nats-buckets.py``) so a
    plain ``import`` is not possible. Mirrors the loader pattern used
    by ``test_init_nats_buckets.py``.
    """
    module_name = "_init_nats_buckets_for_compose_test"
    spec = importlib.util.spec_from_file_location(module_name, INIT_SCRIPT)
    assert spec and spec.loader, "failed to build spec for init-nats-buckets.py"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------
# 1 — compose-parse
# ---------------------------------------------------------------------


def test_compose_file_is_present_and_parses(compose_doc: dict) -> None:
    # If the parse fixture succeeded we are already past the YAML check;
    # this test is the explicit invariant for future readers.
    assert "services" in compose_doc, "compose file must declare services"
    assert "volumes" in compose_doc, "compose file must declare a named volume"
    assert "networks" in compose_doc, "compose file must declare a network"


def test_compose_has_a_single_phase1_service_named_nats(compose_doc: dict) -> None:
    services = compose_doc["services"]
    assert isinstance(services, dict)
    assert list(services.keys()) == ["nats"], (
        "Phase-1 substrate must expose exactly one service ('nats'); "
        "additional services belong in their own compose unit."
    )


# ---------------------------------------------------------------------
# 2 + 3 — nats service-definition + image-pin form
# ---------------------------------------------------------------------


def test_nats_service_uses_documented_image_tag(compose_doc: dict) -> None:
    image = compose_doc["services"]["nats"]["image"]
    # Two valid Box-3 forms:
    #   * tag-only:      ``nats:2.11-alpine``
    #   * digest-pinned: ``nats:2.11-alpine@sha256:<64-hex>``
    tag_only = image == "nats:2.11-alpine"
    digest_pin = re.fullmatch(r"nats:2\.11-alpine@sha256:[0-9a-f]{64}", image)
    assert tag_only or digest_pin, (
        f"image pin must be 'nats:2.11-alpine' (tag-only) or a "
        f"digest-pinned form 'nats:2.11-alpine@sha256:<64-hex>'; got: {image!r}"
    )


def test_nats_service_runs_jetstream(compose_doc: dict) -> None:
    cmd = compose_doc["services"]["nats"]["command"]
    assert isinstance(cmd, list)
    assert "--jetstream" in cmd, "JetStream must be enabled on the server"
    # Persistence directory must be inside the volume mount.
    store_dir_args = [arg for arg in cmd if arg.startswith("--store_dir=")]
    assert len(store_dir_args) == 1, "exactly one --store_dir argument expected"
    assert store_dir_args[0] == "--store_dir=/data/jetstream"


def test_nats_ports_are_loopback_only(compose_doc: dict) -> None:
    ports = compose_doc["services"]["nats"]["ports"]
    assert isinstance(ports, list) and ports, "ports list must be non-empty"
    for entry in ports:
        assert isinstance(entry, str)
        # Phase-1 invariant: every port mapping binds to 127.0.0.1.
        assert entry.startswith("127.0.0.1:"), (
            f"Phase-1 substrate must publish loopback-only; got: {entry!r}"
        )
    published = {entry.split(":")[1] for entry in ports}
    assert "4222" in published, "client port (4222) must be published"
    assert "8222" in published, "monitoring port (8222) must be published"


def test_nats_volume_mount_uses_named_volume(compose_doc: dict) -> None:
    volumes = compose_doc["services"]["nats"]["volumes"]
    assert volumes, "JetStream persistence requires a volume mount"
    # Format: ``<name>:<mountpoint>`` — short form is fine for Phase-1.
    expected = "jetstream_data:/data/jetstream"
    assert expected in volumes, (
        f"expected mount {expected!r} (matches --store_dir); got {volumes!r}"
    )
    # And the named volume exists at top-level.
    top_volumes = compose_doc.get("volumes", {})
    assert "jetstream_data" in top_volumes


# ---------------------------------------------------------------------
# 4 — bucket-init alignment
# ---------------------------------------------------------------------


def test_compose_commentary_references_all_phase_1_buckets(
    compose_text: str, init_script_module
) -> None:
    """Each documented bucket name must appear at least once in the
    compose file (in commentary). This catches drift between the
    initialiser inventory and the substrate-substrate sizing notes.
    """
    bucket_names = {spec.name for spec in init_script_module.PHASE_1_BUCKETS}
    assert bucket_names == {
        "wakir-schemas",
        "wakir-aip-cache",
        "wakir-ftd-cache",
        "wakir-ftd-poisoned",
        "wakir-schema-registry-entries",
        "wakir-federation-routes",
    }, "Phase-1 inventory drift — update test or initialiser"
    for name in bucket_names:
        assert name in compose_text, (
            f"compose/nats.yaml commentary should reference bucket {name!r} "
            f"so an operator reading only the compose file knows the substrate "
            f"sizing intent"
        )


# ---------------------------------------------------------------------
# 5 — hardening
# ---------------------------------------------------------------------


def test_nats_service_has_hardened_defaults(compose_doc: dict) -> None:
    svc = compose_doc["services"]["nats"]
    assert svc.get("cap_drop") == ["ALL"], "cap_drop ALL is mandatory Phase-1 hardening"
    sec_opt = svc.get("security_opt", [])
    assert "no-new-privileges:true" in sec_opt, (
        "no-new-privileges must be set"
    )
    assert svc.get("restart") == "unless-stopped", (
        "Phase-1 NATS must auto-restart on crash but not on operator-stop"
    )


# ---------------------------------------------------------------------
# 6 — health probe
# ---------------------------------------------------------------------


def test_nats_service_health_probe_hits_jetstream_endpoint(compose_doc: dict) -> None:
    health = compose_doc["services"]["nats"]["healthcheck"]
    assert isinstance(health, dict)
    test_cmd = health["test"]
    assert isinstance(test_cmd, list) and test_cmd[0] == "CMD-SHELL"
    probe = test_cmd[1]
    # The probe must hit the JetStream introspection endpoint, not just
    # the bare ``/`` of port 8222 — a JetStream-disabled NATS would
    # still answer on ``/`` and that would be a false-positive green.
    assert "/jsz" in probe, (
        "health probe must hit /jsz (JetStream introspection), not /"
    )
    assert health.get("interval"), "health interval must be set"
    assert health.get("retries"), "health retries must be set"
    assert health.get("timeout"), "health timeout must be set"
