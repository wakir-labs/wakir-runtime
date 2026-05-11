# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/init-nats-buckets.py``.

The script targets a live NATS-JetStream cluster, but we do not stand
one up here. Instead we drive the ``plan_and_apply`` planner against a
small in-memory mock that mirrors the subset of the
``nats.js.JetStreamContext`` API surface the script depends on.

Coverage:

1. Plan against an empty cluster: all five buckets get ``created``.
2. Re-run after a successful create: all five become ``unchanged``.
3. ``--dry-run`` against an empty cluster reports ``would_create`` and
   does not mutate the mock state.
4. Drift detection: a bucket whose live history differs from the spec
   is reported as ``drift`` with a precise diff payload.
5. Bucket selection by name: ``--bucket wakir-schemas`` only touches
   that one bucket and leaves the others alone.
6. Unknown bucket selector raises a clean ``ValueError``.
7. (Sprint-4 Tag-4) The 5th bucket ``wakir-schema-registry-entries``
   is present in ``PHASE_1_BUCKETS`` and its config mirrors the
   ``wakir-schemas`` cache bucket so the Phase-2 schema-registry
   storage migration is a value-copy without a config-drift step.

The tests are hermetic (no I/O, no NATS, no filesystem).
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


# ---------------------------------------------------------------------
# Module loader: the script lives under scripts/init-nats-buckets.py and
# has a hyphen in the filename, so we cannot use a regular import. We
# load it via importlib for the test suite. Python 3.14's dataclasses
# implementation walks ``sys.modules[cls.__module__]`` during certain
# annotation-resolution paths, so we register the loaded module under
# its qualified name before executing it.
# ---------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "init-nats-buckets.py"
_MODULE_NAME = "init_nats_buckets"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, str(_SCRIPT)
    )
    assert spec is not None and spec.loader is not None, "loader unavailable"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ---------------------------------------------------------------------
# Mock JetStream + KV surface
# ---------------------------------------------------------------------


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


@dataclass
class _MockJetStream:
    """In-memory replacement for ``nats.js.JetStreamContext``.

    The real surface is async; this mock follows the same await shape so
    ``plan_and_apply`` can be exercised verbatim.
    """

    buckets: dict = field(default_factory=dict)
    create_calls: list = field(default_factory=list)

    async def key_value(self, *, bucket: str):
        if bucket not in self.buckets:
            raise _MockBucketNotFound(bucket)
        return self.buckets[bucket]

    async def create_key_value(self, **kwargs: Any):
        # Real nats-py raises if the bucket already exists; we mirror that.
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


class _MockBucketNotFound(Exception):
    """Mimics ``nats.js.errors.BucketNotFoundError`` by class-name match."""


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


def test_create_on_empty_cluster_creates_all_phase_1_buckets(mod, event_loop):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )

    assert [a.status for a in actions] == ["created"] * len(mod.PHASE_1_BUCKETS)
    created_names = {call["bucket"] for call in js.create_calls}
    assert created_names == {spec.name for spec in mod.PHASE_1_BUCKETS}

    # Every create call carried the documented configuration.
    by_name = {call["bucket"]: call for call in js.create_calls}
    for spec in mod.PHASE_1_BUCKETS:
        call = by_name[spec.name]
        assert call["history"] == spec.history
        assert call["ttl"] == spec.ttl_seconds
        assert call["max_value_size"] == spec.max_value_size
        assert call["storage"] == spec.storage
        assert call["replicas"] == spec.replicas


def test_idempotent_replay_marks_existing_buckets_unchanged(mod, event_loop):
    js = _MockJetStream()
    # First pass: populate.
    event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    js.create_calls.clear()

    # Second pass: should be a no-op.
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    assert all(a.status == "unchanged" for a in actions), [
        (a.name, a.status, a.detail, a.drift) for a in actions
    ]
    assert js.create_calls == [], "idempotent replay must not call create_key_value"


def test_dry_run_against_empty_cluster_reports_would_create_and_does_not_mutate(
    mod, event_loop
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=True)
    )

    assert [a.status for a in actions] == ["would_create"] * len(mod.PHASE_1_BUCKETS)
    assert js.buckets == {}, "dry-run must not mutate the cluster"
    assert js.create_calls == [], "dry-run must not call create_key_value"


def test_drift_is_reported_with_precise_diff_and_no_mutation(mod, event_loop):
    js = _MockJetStream()
    spec = next(s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-schemas")
    # Pre-seed with a *drifted* configuration: history is 1 instead of 5.
    js.buckets[spec.name] = _MockKv(
        name=spec.name,
        status_payload=_MockKvStatus(
            history=1,
            ttl=spec.ttl_seconds,
            max_value_size=spec.max_value_size,
            storage=spec.storage,
            replicas=spec.replicas,
        ),
    )

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, [spec], dry_run=False)
    )

    assert len(actions) == 1
    action = actions[0]
    assert action.status == "drift", (action.status, action.detail, action.drift)
    assert action.drift == {"history": {"want": 5, "got": 1}}
    # Drift must never trigger a mutation.
    assert js.create_calls == []


def test_bucket_filter_only_touches_named_bucket(mod, event_loop):
    js = _MockJetStream()
    selected = mod._select_specs(["wakir-schemas"])
    assert [s.name for s in selected] == ["wakir-schemas"]

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, selected, dry_run=False)
    )
    assert len(actions) == 1
    assert actions[0].name == "wakir-schemas"
    assert actions[0].status == "created"
    assert set(js.buckets) == {"wakir-schemas"}


def test_unknown_bucket_selector_raises_value_error_with_known_set(mod):
    with pytest.raises(ValueError) as excinfo:
        mod._select_specs(["wakir-schemas", "wakir-bogus"])
    msg = str(excinfo.value)
    assert "wakir-bogus" in msg
    assert "wakir-schemas" in msg  # listed under "known"


def test_phase_1_inventory_is_the_documented_five_buckets(mod):
    """Phase-1 inventory contract (Sprint-4 Tag-4 onward).

    Order matters: the documented order is preserved across tooling
    (runbook, init script JSON output, drift reports). A re-ordering
    of the inventory is a contract change that needs an ADR.
    """
    names = [spec.name for spec in mod.PHASE_1_BUCKETS]
    assert names == [
        "wakir-schemas",
        "wakir-aip-cache",
        "wakir-ftd-cache",
        "wakir-ftd-poisoned",
        "wakir-schema-registry-entries",
    ]


def test_report_to_json_has_stable_shape_and_summary(mod, event_loop):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    report = mod.InitReport(
        servers="nats://127.0.0.1:4222",
        dry_run=False,
        actions=actions,
    )
    payload = json.loads(report.to_json())

    assert payload["servers"] == "nats://127.0.0.1:4222"
    assert payload["dry_run"] is False
    assert payload["summary"] == {
        "created": 5,
        "unchanged": 0,
        "drift": 0,
        "would_create": 0,
        "total": 5,
    }
    assert {a["name"] for a in payload["actions"]} == {
        spec.name for spec in mod.PHASE_1_BUCKETS
    }


def test_exit_code_zero_on_clean_create(mod, event_loop):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    report = mod.InitReport(
        servers="nats://127.0.0.1:4222",
        dry_run=False,
        actions=actions,
    )
    assert mod._exit_code_for(report) == 0


def test_exit_code_two_on_drift(mod, event_loop):
    js = _MockJetStream()
    spec = next(s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-aip-cache")
    js.buckets[spec.name] = _MockKv(
        name=spec.name,
        status_payload=_MockKvStatus(
            history=spec.history,
            ttl=spec.ttl_seconds + 1,  # drifted ttl
            max_value_size=spec.max_value_size,
            storage=spec.storage,
            replicas=spec.replicas,
        ),
    )
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, [spec], dry_run=False)
    )
    report = mod.InitReport(
        servers="nats://127.0.0.1:4222",
        dry_run=False,
        actions=actions,
    )
    assert mod._exit_code_for(report) == 2


# ---------------------------------------------------------------------
# Sprint-4 Tag-4: 5th-bucket-paired-update tests
# ---------------------------------------------------------------------
#
# These tests anchor the contract that the new 5th bucket
# ``wakir-schema-registry-entries`` is registered with the documented
# Phase-2-reserved config, and that the create/select/idempotency paths
# of the planner cover it. The bucket has no Phase-1b consumer; the
# operator bring-up only needs to know that the cluster has the bucket
# layout ready for the Phase-2 schema-registry-storage migration that
# the Wirelang-side track owns.
#
# Auftrags-Quota: "4-6 hermetic Tests". This file adds 5 tests (T-Tag4-
# 01..05) plus a registry-entries-config mirror anchor. Live-gated
# parity-test lives in ``test_check_nats_kv_health.py`` (single live
# probe; gated by ``WAKIR_NATS_LIVE``).


def test_t_tag4_01_wakir_schema_registry_entries_is_the_fifth_bucket_in_documented_order(mod):
    """The 5th bucket entry exists with the documented Phase-2-reserved
    config (history=5, ttl unbounded, 256 KiB max_value_size).

    The config mirrors ``wakir-schemas`` so that the Phase-2 migration
    off the cache bucket onto the storage bucket is a value-copy
    without any config-drift step. Order matters: the documented
    inventory ordering is preserved across tooling output (runbook,
    JSON report, drift report), so this test pins the 5th-slot
    placement.
    """
    fifth = mod.PHASE_1_BUCKETS[4]
    assert fifth.name == "wakir-schema-registry-entries"
    assert fifth.history == 5
    assert fifth.ttl_seconds == 0
    assert fifth.max_value_size == 262_144  # 256 KiB
    assert fifth.storage == "file"
    assert fifth.replicas == 1
    assert "Phase-2" in fifth.description
    assert "wakir-schemas" in fifth.description  # cross-reference to cache


def test_t_tag4_02_fifth_bucket_config_mirrors_wakir_schemas_cache(mod):
    """The 5th bucket's config is byte-aligned with the 1st (cache)
    bucket on the fields that affect the schema-registry value-copy
    migration: history, ttl_seconds, max_value_size, storage, replicas.

    Description is intentionally **different** (cache vs storage
    intent). Name is intentionally different (the whole point of the
    5th bucket is to separate the surfaces).
    """
    first = next(s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-schemas")
    fifth = next(
        s for s in mod.PHASE_1_BUCKETS
        if s.name == "wakir-schema-registry-entries"
    )
    assert fifth.history == first.history
    assert fifth.ttl_seconds == first.ttl_seconds
    assert fifth.max_value_size == first.max_value_size
    assert fifth.storage == first.storage
    assert fifth.replicas == first.replicas
    # Names and descriptions diverge by design.
    assert fifth.name != first.name
    assert fifth.description != first.description


def test_t_tag4_03_fifth_bucket_create_on_empty_cluster_carries_documented_kv_config(
    mod, event_loop
):
    """An empty-cluster run materialises the 5th bucket with the exact
    kwargs the Phase-2 storage migration will expect.

    The Wirelang-side consumer for Phase-2 will read the live bucket;
    if the orchestrator created it with the wrong ``max_value_size``
    or ``history``, the Phase-2 migration would either silently
    truncate schema bodies (max_value_size too small) or fail to retain
    the version-history depth that the consumer-side codec expects.
    This test guards the create-call shape.
    """
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )

    fifth_actions = [
        a for a in actions if a.name == "wakir-schema-registry-entries"
    ]
    assert len(fifth_actions) == 1
    assert fifth_actions[0].status == "created"

    fifth_calls = [
        c for c in js.create_calls
        if c["bucket"] == "wakir-schema-registry-entries"
    ]
    assert len(fifth_calls) == 1
    call = fifth_calls[0]
    assert call["history"] == 5
    assert call["ttl"] == 0
    assert call["max_value_size"] == 262_144
    assert call["storage"] == "file"
    assert call["replicas"] == 1
    assert "Phase-2" in call["description"]


def test_t_tag4_04_bucket_filter_can_select_fifth_bucket(mod, event_loop):
    """``--bucket wakir-schema-registry-entries`` selects only the 5th
    bucket.

    Operationally useful: an operator can re-run the init script
    against a cluster that already has the four pre-Tag-4 Phase-1
    buckets to backfill only the new 5th bucket without churning the
    others. This is the no-downtime upgrade path for a cluster that
    came up before Sprint-4 Tag-4 landed.
    """
    js = _MockJetStream()
    selected = mod._select_specs(["wakir-schema-registry-entries"])
    assert [s.name for s in selected] == ["wakir-schema-registry-entries"]

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, selected, dry_run=False)
    )
    assert len(actions) == 1
    assert actions[0].name == "wakir-schema-registry-entries"
    assert actions[0].status == "created"
    assert set(js.buckets) == {"wakir-schema-registry-entries"}


def test_t_tag4_05_fifth_bucket_idempotent_replay_marks_unchanged(
    mod, event_loop
):
    """Re-running the init script after the 5th bucket exists is a
    no-op.

    Idempotency contract for the full five-bucket layout: operators
    can re-run ``init-nats-buckets.py`` on a cluster that already has
    the complete inventory without side effects. The 5th bucket gets
    the same idempotency guarantee as the four pre-Tag-4 buckets.
    """
    js = _MockJetStream()
    # First pass: populate all five.
    event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    js.create_calls.clear()

    # Second pass: should be a no-op for the 5th bucket specifically.
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    fifth_action = next(
        a for a in actions if a.name == "wakir-schema-registry-entries"
    )
    assert fifth_action.status == "unchanged"
    assert js.create_calls == [], (
        "idempotent replay must not re-create the 5th bucket"
    )
