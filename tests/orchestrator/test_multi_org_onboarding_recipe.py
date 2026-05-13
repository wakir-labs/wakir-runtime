# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Multi-Org-Onboarding-Recipe substrate
(Phase-2 Sprint-9 Tag-2).

The recipe itself is an Operator-Hand markdown document
(`infra/spire/federation/MULTI_ORG_ONBOARDING_RECIPE.md`); these
tests assert the **infrastructure invariants** the recipe depends
on:

1. Recipe file exists at the documented path and references the
   Single-Org-Pilot Recipe + companion artefacts.
2. Quadlet templates for both sides carry the ``<SIDE>``
   placeholder so the recipe's sed-substitution sequence works.
3. Per-side configs for ``wakir.test`` and ``partner.test`` are
   both present in the repo.
4. Multi-org input (two orgs, two families) produces 4 bucket
   actions in stable org-major/family-minor order.
5. Onboarded-orgs roster parsing accepts the multi-org shape
   (``acme`` + ``partner`` + comments + blanks).
6. Onboarded-orgs roster MERGED with CLI flags yields the union
   in file-first order (the recipe's append-and-rerun pattern).
7. Cross-Trust-Domain literal allow-list: the recipe's
   ``partner.test`` and ``wakir.test`` trust-domains are both
   admissible via the marker-stack family's permitted-character
   regex.

These tests are hermetic: no I/O, no NATS, no filesystem mutation
outside ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BIN_PY = _REPO_ROOT / "bin" / "nats_kv_bucket_provision.py"
_MODULE_NAME = "nats_kv_bucket_provision"


def _load_module():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, str(_BIN_PY))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# Mock JetStream (shared shape; trimmed copy)
# ---------------------------------------------------------------------------


@dataclass
class _MockKvStatus:
    history: int
    ttl: int
    max_value_size: int
    storage: str
    replicas: int


@dataclass
class _MockKv:
    name: str
    status_payload: _MockKvStatus

    async def status(self) -> _MockKvStatus:
        return self.status_payload


class _MockBucketNotFound(Exception):
    pass


@dataclass
class _MockJetStream:
    buckets: dict = field(default_factory=dict)
    create_calls: list = field(default_factory=list)

    async def key_value(self, *, bucket: str):
        if bucket not in self.buckets:
            raise _MockBucketNotFound(bucket)
        return self.buckets[bucket]

    async def create_key_value(self, **kwargs: Any):
        bucket = kwargs["bucket"]
        self.create_calls.append(dict(kwargs))
        self.buckets[bucket] = _MockKv(
            name=bucket,
            status_payload=_MockKvStatus(
                history=int(kwargs.get("history", 1)),
                ttl=int(kwargs.get("ttl", 0)),
                max_value_size=int(kwargs.get("max_value_size", 0)),
                storage=str(kwargs.get("storage", "file")),
                replicas=int(kwargs.get("replicas", 1)),
            ),
        )
        return self.buckets[bucket]


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Same synthetic families as the multi-family test module (kept
# inline so the test can run independently).

import re as _re

_ORG_ID_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")
_FAM_A_PREFIX = "wakir-fixture-recipe-a-"
_FAM_B_PREFIX = "wakir-fixture-recipe-b-"


def _make_derive(prefix: str):
    def _derive(org_id: str) -> str:
        if not isinstance(org_id, str) or not org_id:
            raise ValueError(f"org_id empty: {org_id!r}")
        if not _ORG_ID_RE.match(org_id):
            raise ValueError(f"org_id malformed: {org_id!r}")
        return f"{prefix}{org_id}"

    return _derive


@pytest.fixture
def two_synthetic_families(mod):
    return [
        mod.BucketFamily(
            family_id="recipe-fixture-a",
            bucket_name_prefix=_FAM_A_PREFIX,
            bucket_config={
                "description": "Recipe fixture family A",
                "history": 1,
                "ttl_seconds": 0,
                "max_value_size": 32_768,
                "storage": "file",
                "replicas": 1,
            },
            bucket_name_for_org=_make_derive(_FAM_A_PREFIX),
        ),
        mod.BucketFamily(
            family_id="recipe-fixture-b",
            bucket_name_prefix=_FAM_B_PREFIX,
            bucket_config={
                "description": "Recipe fixture family B",
                "history": 1,
                "ttl_seconds": 0,
                "max_value_size": 4_096,
                "storage": "file",
                "replicas": 1,
            },
            bucket_name_for_org=_make_derive(_FAM_B_PREFIX),
        ),
    ]


# ---------------------------------------------------------------------------
# T-MULTIORG-01 — recipe file present + references companions
# ---------------------------------------------------------------------------


def test_multi_org_onboarding_recipe_exists_and_references_companions():
    recipe = (
        _REPO_ROOT
        / "infra"
        / "spire"
        / "federation"
        / "MULTI_ORG_ONBOARDING_RECIPE.md"
    )
    assert recipe.exists(), f"recipe missing at {recipe}"
    text = recipe.read_text(encoding="utf-8")
    # Companion artefact references the recipe MUST carry to be
    # operator-usable.
    assert "PROXMOX_BRING_UP_RECIPE.md" in text, (
        "recipe must reference the Single-Org-Pilot recipe"
    )
    assert "proxmox-bundle-v1.0.tar.gz" in text, (
        "recipe must reference the deterministic bundle tarball"
    )
    assert "spire-fed-bundle" in text, (
        "recipe must reference the bundle-export/import CLI"
    )
    # Multi-org-specific structural anchors.
    assert "partner.test" in text
    assert "wakir.test" in text
    # Multi-family bucket provisioning is the Zone-B paired-update
    # subject; recipe must call it out.
    assert "wakir-marker-stack-" in text
    assert "wakir-caveat-override-export-sequence-" in text


# ---------------------------------------------------------------------------
# T-MULTIORG-02 — Quadlet template <SIDE> placeholders are present
# ---------------------------------------------------------------------------


def test_quadlet_templates_carry_side_placeholder():
    server_quadlet = (
        _REPO_ROOT
        / "infra"
        / "spire"
        / "federation"
        / "quadlet"
        / "wakir-spire-server-federation.container"
    )
    agent_quadlet = (
        _REPO_ROOT
        / "infra"
        / "spire"
        / "agent"
        / "quadlet"
        / "wakir-spire-agent-federation.container"
    )

    assert server_quadlet.exists()
    assert agent_quadlet.exists()

    server_text = server_quadlet.read_text(encoding="utf-8")
    agent_text = agent_quadlet.read_text(encoding="utf-8")

    # The Multi-Org recipe's sed-substitution sequence depends on
    # these literal placeholders.
    assert "<SIDE>" in server_text, (
        "wakir-spire-server-federation.container must carry "
        "<SIDE> placeholder for multi-org sed-substitution"
    )
    assert "<HOST_BUNDLE_PORT>" in server_text
    assert "<HOST_GRPC_PORT>" in server_text
    assert "<SIDE>" in agent_text
    assert "<TRUST_DOMAIN>" in agent_text
    assert "<SERVER_DNS>" in agent_text


# ---------------------------------------------------------------------------
# T-MULTIORG-03 — per-side configs both present
# ---------------------------------------------------------------------------


def test_per_side_configs_for_wakir_and_partner_present():
    federation_root = _REPO_ROOT / "infra" / "spire" / "federation"
    wakir_conf = federation_root / "config" / "spire-server-wakir.conf"
    partner_conf = federation_root / "config" / "spire-server-partner.conf"
    assert wakir_conf.exists(), (
        f"wakir.test side config missing at {wakir_conf}"
    )
    assert partner_conf.exists(), (
        f"partner.test side config missing at {partner_conf}"
    )
    # Cross-check the trust-domain literal on each side.
    assert "wakir.test" in wakir_conf.read_text(encoding="utf-8")
    assert "partner.test" in partner_conf.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# T-MULTIORG-04 — multi-org × multi-family fan-out
# ---------------------------------------------------------------------------


def test_two_orgs_two_families_produces_four_actions_in_stable_order(
    mod, event_loop, two_synthetic_families
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            ["acme", "partner"],
            dry_run=False,
            families=two_synthetic_families,
        )
    )

    assert len(actions) == 4
    # Stable order: org-major (input order), family-minor (registry
    # order).
    assert [(a.org_id, a.family) for a in actions] == [
        ("acme", "recipe-fixture-a"),
        ("acme", "recipe-fixture-b"),
        ("partner", "recipe-fixture-a"),
        ("partner", "recipe-fixture-b"),
    ]
    assert [a.status for a in actions] == [
        "created",
        "created",
        "created",
        "created",
    ]
    # Bucket names follow per-family prefix.
    assert actions[0].bucket == f"{_FAM_A_PREFIX}acme"
    assert actions[2].bucket == f"{_FAM_A_PREFIX}partner"
    # Per-family max_value_size byte-precision (32 KiB vs 4 KiB).
    by_bucket = {c["bucket"]: c for c in js.create_calls}
    assert by_bucket[f"{_FAM_A_PREFIX}acme"]["max_value_size"] == 32_768
    assert by_bucket[f"{_FAM_B_PREFIX}acme"]["max_value_size"] == 4_096
    assert by_bucket[f"{_FAM_A_PREFIX}partner"]["max_value_size"] == 32_768
    assert by_bucket[f"{_FAM_B_PREFIX}partner"]["max_value_size"] == 4_096


# ---------------------------------------------------------------------------
# T-MULTIORG-05 — roster parser accepts the multi-org shape
# ---------------------------------------------------------------------------


def test_onboarded_orgs_roster_with_multi_org_shape(mod, tmp_path):
    roster = tmp_path / "onboarded-orgs"
    roster.write_text(
        "\n".join(
            [
                "# Roster of onboarded orgs (multi-org pilot)",
                "",
                "acme",
                "partner   ",
                "# partner.test is the second trust-domain",
                "",
                "tertio",  # future org
            ]
        ),
        encoding="utf-8",
    )
    parsed = mod.parse_orgs_file(roster)
    assert parsed == ["acme", "partner", "tertio"]


# ---------------------------------------------------------------------------
# T-MULTIORG-06 — append-and-rerun pattern merges file + CLI flags
# ---------------------------------------------------------------------------


def test_append_and_rerun_pattern_merges_file_and_flags(mod, tmp_path):
    """Recipe §3.3 documents the append-and-rerun pattern:
    operator appends ``partner`` to the roster file and re-runs
    the unit. ``_collect_org_ids`` is the merge surface for this
    pattern (file first, flags second, first-occurrence-wins
    de-dup).
    """
    roster = tmp_path / "onboarded-orgs"
    roster.write_text("acme\npartner\n", encoding="utf-8")
    # Operator may also pass CLI --org flags (e.g. for a one-off
    # provisioning before persisting the roster).
    merged = mod._collect_org_ids(["acme", "tertio"], roster)
    assert merged == ["acme", "partner", "tertio"]


# ---------------------------------------------------------------------------
# T-MULTIORG-07 — trust-domain literal is permitted-character-compatible
# ---------------------------------------------------------------------------


def test_partner_test_and_wakir_test_are_permitted_org_ids(mod):
    """The marker-stack family validator (re-used by the
    multi-family registry) admits both ``partner.test`` and
    ``wakir.test`` literals via its permitted-character regex.
    This is the substrate invariant the Multi-Org recipe depends
    on: the recipe must be able to enrol both trust-domain names
    as org_ids if the operator chooses to pin them as-is in the
    roster.
    """
    # Both literal trust-domain strings parse as legitimate
    # bucket-name suffixes — the marker-stack regex admits the
    # ``.`` separator.
    bucket_partner = mod.bucket_name_for_org("partner.test")
    bucket_wakir = mod.bucket_name_for_org("wakir.test")
    assert bucket_partner == "wakir-marker-stack-partner.test"
    assert bucket_wakir == "wakir-marker-stack-wakir.test"
