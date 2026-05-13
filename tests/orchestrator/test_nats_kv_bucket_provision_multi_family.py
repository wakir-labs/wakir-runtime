# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the multi-family registry surface of
``bin/nats-kv-bucket-provision`` (Phase-2 Sprint-9 Tag-2 paired-
update on Reza-Sprint-9 Tag-2 durable
:class:`SequenceNumberLedger` per-org bucket family).

Sprint-9 Tag-1 shipped the driver with one per-org family
(``wakir-marker-stack-{org_id}``). Sprint-9 Tag-2 promoted the
driver to a small registry of per-org families and added a
defensive import for the
``wirelang.federation.sequence_number_ledger_kv`` ledger family
(Reza-PR #25). These tests assert the multi-family fan-out shape
**without** depending on the real Wirelang-side module being
present — every test synthesises a fixture
:class:`BucketFamily` so the surface contract is byte-precise even
on a baseline tip that does not (yet) carry the Tag-2 Wirelang
module.

Coverage axes (T-MULTIFAM-01..08):

1. **One org × two synthetic families** → two ``created`` actions,
   one per family, in stable registry order.
2. **Idempotent multi-family replay** → all actions ``unchanged``,
   ``create_key_value`` not invoked.
3. **Dry-run multi-family** → all actions ``would_create`` per
   family; no cluster mutation.
4. **Per-family drift detection** → drifted bucket in family-A is
   reported with ``family=`` tag; family-B in same org_id is
   unaffected.
5. **Malformed org_id short-circuits family loop** → ONE error
   action per org (Tag-1-shape invariant), not N error actions.
6. **JSON payload carries the ``family`` field** in every action
   record; report-shape invariant.
7. **Real-family contract** (skipped if Reza-Tag-2 absent): when
   the Wirelang-side ``sequence_number_ledger_kv`` module is
   importable, :data:`BUCKET_FAMILIES` carries the
   ``"sequence-ledger"`` family with the canonical Reza-Tag-2
   prefix.
8. **Cross-reference invariant for the ledger family** (skipped if
   absent): ``family.bucket_config is`` the Wirelang-side
   ``BUCKET_CONFIG`` constant; no re-encoding.

These tests are hermetic: no I/O, no NATS, no filesystem mutation.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (same shape as test_nats_kv_bucket_provision.py)
# ---------------------------------------------------------------------------

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
# Mock JetStream + KV surface (shared shape with Tag-1 tests)
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
    """Mimics ``nats.js.errors.BucketNotFoundError``."""


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
        if bucket in self.buckets:
            raise RuntimeError(f"bucket already exists: {bucket}")
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


# ---------------------------------------------------------------------------
# Synthetic-family fixtures (independent of Reza-Tag-2 module presence)
# ---------------------------------------------------------------------------


_FAM_A_PREFIX = "wakir-fixture-family-a-"
_FAM_B_PREFIX = "wakir-fixture-family-b-"

# Same permitted-character regex as marker_stack_kv / sequence_number_ledger_kv
import re as _re

_ORG_ID_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")


def _fixture_bucket_name_for_org_factory(prefix: str):
    def _derive(org_id: str) -> str:
        if not isinstance(org_id, str) or not org_id:
            raise ValueError(
                f"org_id must be a non-empty string, got {org_id!r}"
            )
        if not _ORG_ID_RE.match(org_id):
            raise ValueError(
                f"org_id {org_id!r} does not match permitted-character "
                f"pattern {_ORG_ID_RE.pattern!r}"
            )
        return f"{prefix}{org_id}"

    return _derive


_FAM_A_CONFIG: Mapping[str, Any] = {
    "description": "Fixture-family A (history=1, max=32 KiB)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 32_768,
    "storage": "file",
    "replicas": 1,
}

_FAM_B_CONFIG: Mapping[str, Any] = {
    "description": "Fixture-family B (history=1, max=4 KiB)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 4_096,
    "storage": "file",
    "replicas": 1,
}


@pytest.fixture
def synthetic_families(mod):
    """Return a deterministic two-element family list spelling out
    the marker-stack-shape (32 KiB envelope) and the sequence-
    ledger-shape (4 KiB envelope). These fixtures are
    Wirelang-side-module-independent so the Tag-2 hermetic
    contracts pass on baseline tips that do not yet carry the
    Reza-Tag-2 module.
    """
    return [
        mod.BucketFamily(
            family_id="fixture-family-a",
            bucket_name_prefix=_FAM_A_PREFIX,
            bucket_config=_FAM_A_CONFIG,
            bucket_name_for_org=_fixture_bucket_name_for_org_factory(
                _FAM_A_PREFIX
            ),
        ),
        mod.BucketFamily(
            family_id="fixture-family-b",
            bucket_name_prefix=_FAM_B_PREFIX,
            bucket_config=_FAM_B_CONFIG,
            bucket_name_for_org=_fixture_bucket_name_for_org_factory(
                _FAM_B_PREFIX
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# T-MULTIFAM-01 — one org × two families → two actions in registry order
# ---------------------------------------------------------------------------


def test_one_org_two_families_emits_two_created_actions_in_registry_order(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme"], dry_run=False, families=synthetic_families
        )
    )

    assert len(actions) == 2, actions
    assert [a.family for a in actions] == [
        "fixture-family-a",
        "fixture-family-b",
    ]
    assert [a.status for a in actions] == ["created", "created"]
    assert actions[0].bucket == f"{_FAM_A_PREFIX}acme"
    assert actions[1].bucket == f"{_FAM_B_PREFIX}acme"

    # Per-family max_value_size byte-precision: family-A 32 KiB,
    # family-B 4 KiB (proving the per-family config is honoured).
    by_family = {c["bucket"]: c for c in js.create_calls}
    assert by_family[f"{_FAM_A_PREFIX}acme"]["max_value_size"] == 32_768
    assert by_family[f"{_FAM_B_PREFIX}acme"]["max_value_size"] == 4_096


# ---------------------------------------------------------------------------
# T-MULTIFAM-02 — idempotent multi-family replay
# ---------------------------------------------------------------------------


def test_idempotent_multi_family_replay_marks_every_bucket_unchanged(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=False, families=synthetic_families,
        )
    )
    js.create_calls.clear()

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=False, families=synthetic_families,
        )
    )

    # 2 orgs × 2 families = 4 actions, all "unchanged".
    assert len(actions) == 4
    assert all(a.status == "unchanged" for a in actions), [
        (a.org_id, a.family, a.status, a.drift) for a in actions
    ]
    assert js.create_calls == [], (
        "idempotent multi-family replay must not call create_key_value"
    )


# ---------------------------------------------------------------------------
# T-MULTIFAM-03 — dry-run across all families
# ---------------------------------------------------------------------------


def test_dry_run_multi_family_emits_would_create_per_family_no_mutation(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=True, families=synthetic_families,
        )
    )

    # 2 orgs × 2 families = 4 would_create actions.
    assert len(actions) == 4
    assert all(a.status == "would_create" for a in actions), [
        (a.org_id, a.family, a.status) for a in actions
    ]
    # Family pairing is stable: org-major, family-minor.
    assert [(a.org_id, a.family) for a in actions] == [
        ("acme", "fixture-family-a"),
        ("acme", "fixture-family-b"),
        ("orbit", "fixture-family-a"),
        ("orbit", "fixture-family-b"),
    ]
    assert js.buckets == {}, "dry-run must not mutate the cluster"
    assert js.create_calls == [], "dry-run must not call create_key_value"


# ---------------------------------------------------------------------------
# T-MULTIFAM-04 — per-family drift detection
# ---------------------------------------------------------------------------


def test_per_family_drift_detection_isolates_to_drifted_family(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    # Pre-seed family-A bucket for acme with DRIFTED max_value_size,
    # family-B bucket for acme at canonical config.
    fam_a = synthetic_families[0]
    fam_b = synthetic_families[1]
    bucket_a = fam_a.bucket_name_for_org("acme")
    bucket_b = fam_b.bucket_name_for_org("acme")

    js.buckets[bucket_a] = _MockKv(
        name=bucket_a,
        status_payload=_MockKvStatus(
            history=int(fam_a.bucket_config["history"]),
            ttl=int(fam_a.bucket_config["ttl_seconds"]),
            max_value_size=999_999,  # DRIFTED
            storage=str(fam_a.bucket_config["storage"]),
            replicas=int(fam_a.bucket_config["replicas"]),
        ),
    )
    js.buckets[bucket_b] = _MockKv(
        name=bucket_b,
        status_payload=_MockKvStatus(
            history=int(fam_b.bucket_config["history"]),
            ttl=int(fam_b.bucket_config["ttl_seconds"]),
            max_value_size=int(fam_b.bucket_config["max_value_size"]),
            storage=str(fam_b.bucket_config["storage"]),
            replicas=int(fam_b.bucket_config["replicas"]),
        ),
    )

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme"], dry_run=False, families=synthetic_families
        )
    )

    assert len(actions) == 2
    by_family = {a.family: a for a in actions}
    assert by_family["fixture-family-a"].status == "drift"
    assert by_family["fixture-family-a"].drift == {
        "max_value_size": {
            "want": int(fam_a.bucket_config["max_value_size"]),
            "got": 999_999,
        }
    }
    # Family-B at canonical config → "unchanged" (drift isolation
    # is per-family, not per-org-id).
    assert by_family["fixture-family-b"].status == "unchanged"
    # Drift must never trigger a mutation.
    assert js.create_calls == []


# ---------------------------------------------------------------------------
# T-MULTIFAM-05 — malformed org_id short-circuits the family loop
# ---------------------------------------------------------------------------


def test_malformed_org_id_short_circuits_family_loop_one_error_per_org(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            ["valid-acme", "with/slash", "with space"],
            dry_run=False,
            families=synthetic_families,
        )
    )

    # Two malformed orgs → ONE error action each (not N=2 per
    # family). Tag-1-shape invariant preserved.
    by_org_family = [(a.org_id, a.family, a.status) for a in actions]
    # Valid org gets one action per family (= 2 created actions).
    valid_actions = [a for a in actions if a.org_id == "valid-acme"]
    assert len(valid_actions) == 2
    assert all(a.status == "created" for a in valid_actions)
    # Malformed orgs get exactly one error action each.
    slash_actions = [a for a in actions if a.org_id == "with/slash"]
    space_actions = [a for a in actions if a.org_id == "with space"]
    assert len(slash_actions) == 1
    assert len(space_actions) == 1
    assert slash_actions[0].status == "error"
    assert space_actions[0].status == "error"
    # Errored orgs do NOT carry a bucket name AND have empty family
    # field (the family loop did not run for them).
    assert slash_actions[0].bucket == ""
    assert slash_actions[0].family == ""
    assert space_actions[0].bucket == ""
    assert space_actions[0].family == ""


# ---------------------------------------------------------------------------
# T-MULTIFAM-06 — JSON report payload carries the family field
# ---------------------------------------------------------------------------


def test_json_report_carries_family_field_in_every_action_record(
    mod, event_loop, synthetic_families
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme"], dry_run=False, families=synthetic_families
        )
    )
    report = mod.ProvisionReport(
        servers="nats://localhost:4222", dry_run=False, actions=actions
    )
    payload = json.loads(report.to_json())

    assert "actions" in payload
    assert len(payload["actions"]) == 2
    for record in payload["actions"]:
        assert "family" in record, record
        assert record["family"] in {
            "fixture-family-a",
            "fixture-family-b",
        }
    # Summary block byte-shape unchanged from Tag-1.
    assert payload["summary"]["created"] == 2
    assert payload["summary"]["total"] == 2


# ---------------------------------------------------------------------------
# T-MULTIFAM-07 — real-family contract (skipped if Reza-Tag-2 absent)
# ---------------------------------------------------------------------------


def test_real_sequence_ledger_family_is_registered_when_module_present(mod):
    if not mod._HAS_SEQUENCE_LEDGER_FAMILY:
        pytest.skip(
            "wirelang.federation.sequence_number_ledger_kv not present on "
            "this tip; the multi-family registry stays at marker-stack only"
        )
    family_ids = [f.family_id for f in mod.BUCKET_FAMILIES]
    assert "marker-stack" in family_ids
    assert "sequence-ledger" in family_ids
    # Registry order: marker-stack first, sequence-ledger second.
    assert family_ids.index("marker-stack") < family_ids.index(
        "sequence-ledger"
    )
    # Canonical Reza-Tag-2 prefix.
    seq_fam = next(
        f for f in mod.BUCKET_FAMILIES if f.family_id == "sequence-ledger"
    )
    assert seq_fam.bucket_name_prefix == (
        "wakir-caveat-override-export-sequence-"
    )


# ---------------------------------------------------------------------------
# T-MULTIFAM-08 — cross-reference invariant: ledger family is single-source
# ---------------------------------------------------------------------------


def test_sequence_ledger_family_re_exports_canonical_wirelang_constants(mod):
    if not mod._HAS_SEQUENCE_LEDGER_FAMILY:
        pytest.skip(
            "wirelang.federation.sequence_number_ledger_kv not present"
        )
    from wirelang.federation.sequence_number_ledger_kv import (
        BUCKET_CONFIG,
        BUCKET_NAME_PREFIX,
        bucket_name_for_org,
    )

    assert mod.SEQUENCE_LEDGER_BUCKET_CONFIG is BUCKET_CONFIG
    assert mod.SEQUENCE_LEDGER_BUCKET_NAME_PREFIX is BUCKET_NAME_PREFIX

    seq_fam = next(
        f for f in mod.BUCKET_FAMILIES if f.family_id == "sequence-ledger"
    )
    assert seq_fam.bucket_config is BUCKET_CONFIG
    assert seq_fam.bucket_name_for_org is bucket_name_for_org
    # spec_for_org for the sequence-ledger family carries the
    # Reza-side BUCKET_CONFIG byte-precisely.
    spec = mod.spec_for_org("acme", family=seq_fam)
    assert spec["bucket"] == bucket_name_for_org("acme")
    assert spec["history"] == int(BUCKET_CONFIG["history"])
    assert spec["max_value_size"] == int(BUCKET_CONFIG["max_value_size"])
    assert spec["description"] == str(BUCKET_CONFIG["description"])
