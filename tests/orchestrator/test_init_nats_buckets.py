# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/init-nats-buckets.py``.

The script targets a live NATS-JetStream cluster, but we do not stand
one up here. Instead we drive the ``plan_and_apply`` planner against a
small in-memory mock that mirrors the subset of the
``nats.js.JetStreamContext`` API surface the script depends on.

Coverage:

1. Plan against an empty cluster: all seven buckets get ``created``.
2. Re-run after a successful create: all seven become ``unchanged``.
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
8. (Sprint-4 Tag-5) The 6th bucket ``wakir-federation-routes`` is
   present in ``PHASE_1_BUCKETS`` and its config mirrors the
   Wirelang-side ``BUCKET_CONFIG`` constant byte-precisely so the
   V-908 federation-route registry consumer
   (``wirelang.federation.route_registry_nats_kv_backend``) and the
   orchestrator init driver agree on a single inventory entry,
   closing the Sprint-2 Tag-7 Z-B inventory-drift open follow-up.
9. (Sprint-5 Tag-2) The 7th bucket ``wakir-capability-policies`` is
   present in ``PHASE_1_BUCKETS`` in reservation-form (no live
   Phase-1b / Phase-2 consumer) with audit-friendly defaults
   (history=10, max_value_size=4 KiB, unbounded TTL) mirroring the
   small-marker shape of ``wakir-ftd-poisoned``. The Reza-owned
   Wirelang-side encoder/decoder module commits a ``BUCKET_CONFIG``
   constant in a follow-up; the byte-mirror anchor lands at that
   point. Pre-commit reservation is intentional: the Phase-3 operator
   bring-up procedure collapses into the routine
   ``init-nats-buckets.py`` pass without an out-of-band ``nats kv
   add`` step.

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


def test_phase_1_inventory_is_the_documented_seven_buckets(mod):
    """Phase-1 inventory contract (Sprint-5 Tag-2 onward).

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
        "wakir-federation-routes",
        "wakir-capability-policies",
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
        "created": 7,
        "unchanged": 0,
        "drift": 0,
        "would_create": 0,
        "total": 7,
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


# ---------------------------------------------------------------------
# Sprint-4 Tag-5: 6th-bucket-paired-update tests (wakir-federation-routes)
# ---------------------------------------------------------------------
#
# These tests anchor the contract that the new 6th bucket
# ``wakir-federation-routes`` is registered with the documented config
# (mirrors the Wirelang-side ``BUCKET_CONFIG`` constant byte-precisely)
# and that the create/select/idempotency paths of the planner cover it.
# Unlike the 5th bucket, the 6th bucket HAS a live Phase-1b consumer:
# ``wirelang.federation.route_registry_nats_kv_backend.NatsKvRouteRegistry``
# (Sprint-2 Tag-4 backend + Sprint-2 Tag-6 watch-stream layer). The
# operator bring-up procedure previously created this bucket out of
# band per Runbook §6.5; Sprint-4 Tag-5 promotes it into the routine
# ``init-nats-buckets.py`` pass.
#
# Auftrags-Quota: "4-6 hermetic Tests". This file adds 5 tests (T-Tag5-
# 01..05) anchoring slot, mirror, create-call shape, selector path,
# and idempotency. The live-gated parity probe lives in
# ``test_check_nats_kv_health.py``.


def test_t_tag5_01_wakir_federation_routes_is_the_sixth_bucket_in_documented_order(mod):
    """The 6th bucket entry exists with the documented Phase-1b config
    (history=5, ttl unbounded, 4 KiB max_value_size, file storage,
    replicas=1) byte-aligned with the Wirelang-side ``BUCKET_CONFIG``.

    Order matters: the documented inventory ordering is preserved
    across tooling output (runbook, JSON report, drift report); pin
    the 6th-slot placement here so a re-ordering surfaces as a
    contract change.
    """
    sixth = mod.PHASE_1_BUCKETS[5]
    assert sixth.name == "wakir-federation-routes"
    assert sixth.history == 5
    assert sixth.ttl_seconds == 0
    assert sixth.max_value_size == 4_096
    assert sixth.storage == "file"
    assert sixth.replicas == 1
    assert "V-908" in sixth.description
    assert "Phase-1b" in sixth.description


def test_t_tag5_02_sixth_bucket_config_mirrors_wirelang_consumer_bucket_config(mod):
    """The 6th bucket's config is byte-aligned with the Wirelang-side
    consumer's ``BUCKET_CONFIG`` constant on the drift-relevant fields
    (history, ttl_seconds, max_value_size, storage, replicas).

    This is the dual-anchor parity contract: a drift between the
    orchestrator-side init script and the Wirelang-side consumer is a
    regression that would force the operator to run an out-of-band
    ``nats kv add`` step. The Sprint-2 Tag-7 Z-B Schluss-Marker called
    out exactly this gap; Sprint-4 Tag-5 closes it.

    We import the Wirelang module lazily so this test does not depend
    on import-time side effects of the consumer-side codec; if the
    consumer module ever moves, the import-failure path here is a
    loud regression signal.
    """
    from wirelang.federation.route_registry_nats_kv_backend import (  # type: ignore
        BUCKET_CONFIG,
        BUCKET_NAME,
    )

    sixth = next(
        s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-federation-routes"
    )
    assert sixth.name == BUCKET_NAME, (
        "Wirelang BUCKET_NAME constant drifted from PHASE_1_BUCKETS slot 5"
    )
    assert sixth.history == BUCKET_CONFIG["history"]
    assert sixth.ttl_seconds == BUCKET_CONFIG["ttl_seconds"]
    assert sixth.max_value_size == BUCKET_CONFIG["max_value_size"]
    assert sixth.storage == BUCKET_CONFIG["storage"]
    assert sixth.replicas == BUCKET_CONFIG["replicas"]
    # Description: orchestrator side mirrors the Wirelang module's
    # documented description string verbatim so the operator log line
    # is identical regardless of which side created the bucket.
    assert sixth.description == BUCKET_CONFIG["description"]


def test_t_tag5_03_sixth_bucket_create_on_empty_cluster_carries_documented_kv_config(
    mod, event_loop
):
    """An empty-cluster planner pass emits a single ``create_key_value``
    call for the 6th bucket with the documented kwargs.

    The Wirelang-side consumer reads the live bucket on construction;
    if the orchestrator created the bucket with the wrong
    ``max_value_size`` the consumer would fail to put entries larger
    than the limit. This test guards the create-call shape so the
    contract surfaces in the hermetic suite before it can hit a live
    cluster.
    """
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )

    sixth_actions = [
        a for a in actions if a.name == "wakir-federation-routes"
    ]
    assert len(sixth_actions) == 1
    assert sixth_actions[0].status == "created"

    sixth_calls = [
        c for c in js.create_calls
        if c["bucket"] == "wakir-federation-routes"
    ]
    assert len(sixth_calls) == 1
    call = sixth_calls[0]
    assert call["history"] == 5
    assert call["ttl"] == 0
    assert call["max_value_size"] == 4_096
    assert call["storage"] == "file"
    assert call["replicas"] == 1
    assert "V-908" in call["description"]


def test_t_tag5_04_bucket_filter_can_select_sixth_bucket(mod, event_loop):
    """``--bucket wakir-federation-routes`` selects only the 6th bucket.

    Operationally useful: an operator can re-run the init script
    against a cluster that already has the five pre-Tag-5 Phase-1
    buckets to backfill only the new 6th bucket without churning the
    others. This is the no-downtime upgrade path for a cluster that
    came up before Sprint-4 Tag-5 landed (and was using the §6.5
    hand-creation fallback for the V-908 bucket).
    """
    js = _MockJetStream()
    selected = mod._select_specs(["wakir-federation-routes"])
    assert [s.name for s in selected] == ["wakir-federation-routes"]

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, selected, dry_run=False)
    )
    assert len(actions) == 1
    assert actions[0].name == "wakir-federation-routes"
    assert actions[0].status == "created"
    assert set(js.buckets) == {"wakir-federation-routes"}


def test_t_tag5_05_sixth_bucket_idempotent_replay_marks_unchanged(
    mod, event_loop
):
    """Re-running the init script after the 6th bucket exists is a
    no-op.

    Idempotency contract for the full six-bucket layout: operators
    can re-run ``init-nats-buckets.py`` on a cluster that already has
    the complete inventory without side effects. The 6th bucket gets
    the same idempotency guarantee as the five pre-Tag-5 buckets.
    """
    js = _MockJetStream()
    # First pass: populate all six.
    event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    js.create_calls.clear()

    # Second pass: should be a no-op for the 6th bucket specifically.
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    sixth_action = next(
        a for a in actions if a.name == "wakir-federation-routes"
    )
    assert sixth_action.status == "unchanged"
    assert js.create_calls == [], (
        "idempotent replay must not re-create the 6th bucket"
    )


# ---------------------------------------------------------------------
# Sprint-5 Tag-2: 7th-bucket-paired-update tests (wakir-capability-policies)
# ---------------------------------------------------------------------
#
# These tests anchor the contract that the new 7th bucket
# ``wakir-capability-policies`` is registered with the documented
# Phase-3-reserved config, and that the create/select/idempotency paths
# of the planner cover it. The bucket has NO Phase-1b / Phase-2
# consumer; the operator bring-up only needs to know that the cluster
# has the bucket layout ready for the Phase-3 capability-policy-
# persistence promotion that the Wirelang-side track (Reza-owned per
# Persona-Matrix §2) will commit a ``BUCKET_CONFIG`` constant for.
# Until that lands, this is reservation-form (analogous to the Sprint-4
# Tag-4 5th-bucket pattern, not the Tag-5 6th-bucket cross-import-
# mirror pattern).
#
# Cross-reference: Sprint-5 Tag-1 Reza outbox §6 lists
# ``wakir-capability-policies`` as the Phase-3 capability-policy
# persistence slot; Mira-Strategie-Hand 2026-05-11 promoted the Kai-
# side bucket-inventory-add to Sprint-5 Tag-2 as the paired update with
# the Wirelang-side Sprint-5 Tag-2 capability-policy persistence track.
#
# Auftrags-Quota analogous to Tag-4 / Tag-5: 5 hermetic tests anchoring
# slot, mirror-shape, create-call shape, selector path, and idempotency.
# The live-gated parity probe lives in
# ``test_check_nats_kv_health.py``. No cross-import-mirror anchor yet —
# the Wirelang-side ``BUCKET_CONFIG`` constant is owned by Reza and not
# yet exported. The follow-up byte-mirror anchor lands once the
# Reza-side encoder/decoder module commits.


def test_t_tag2_01_wakir_capability_policies_is_the_seventh_bucket_in_documented_order(mod):
    """The 7th bucket entry exists with the documented Phase-3-reserved
    config (history=10, ttl unbounded, 4 KiB max_value_size, file
    storage, replicas=1).

    The config mirrors ``wakir-ftd-poisoned`` on the small-marker
    fields (max_value_size=4 KiB, ttl unbounded) so that a serialised
    capability-policy entry fits comfortably. The history depth is
    intentionally raised to 10 for rotation-audit retention (a
    capability-policy rotation should leave a trail; analogous to the
    poison-list marker bucket which also uses history=10). Order
    matters: the documented inventory ordering is preserved across
    tooling output (runbook, JSON report, drift report), so this test
    pins the 7th-slot placement.
    """
    seventh = mod.PHASE_1_BUCKETS[6]
    assert seventh.name == "wakir-capability-policies"
    assert seventh.history == 10
    assert seventh.ttl_seconds == 0
    assert seventh.max_value_size == 4_096
    assert seventh.storage == "file"
    assert seventh.replicas == 1
    assert "Phase-3" in seventh.description
    assert "capability-policy" in seventh.description.lower()


def test_t_tag2_02_seventh_bucket_config_mirrors_wakir_ftd_poisoned_small_marker_shape(mod):
    """The 7th bucket's config is byte-aligned with
    ``wakir-ftd-poisoned`` on the fields that establish the
    audit-marker shape: history, ttl_seconds, max_value_size, storage,
    replicas.

    Description is intentionally **different** (capability-policy
    persistence vs poison-list marker intent). Name is intentionally
    different (the whole point of the 7th bucket is to separate the
    capability-policy surface from the FTD poison-list surface). The
    Reza-owned Wirelang-side ``BUCKET_CONFIG`` constant, when it
    commits, will be the authoritative byte-mirror anchor; until then
    this in-tree mirror against ``wakir-ftd-poisoned`` guards the
    reservation-form shape.
    """
    poisoned = next(
        s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-ftd-poisoned"
    )
    seventh = next(
        s for s in mod.PHASE_1_BUCKETS
        if s.name == "wakir-capability-policies"
    )
    assert seventh.history == poisoned.history
    assert seventh.ttl_seconds == poisoned.ttl_seconds
    assert seventh.max_value_size == poisoned.max_value_size
    assert seventh.storage == poisoned.storage
    assert seventh.replicas == poisoned.replicas
    # Names and descriptions diverge by design.
    assert seventh.name != poisoned.name
    assert seventh.description != poisoned.description


def test_t_tag2_03_seventh_bucket_create_on_empty_cluster_carries_documented_kv_config(
    mod, event_loop
):
    """An empty-cluster planner pass emits a single ``create_key_value``
    call for the 7th bucket with the documented kwargs.

    A future Phase-3 capability-policy persistence consumer (Reza-
    side) will read the live bucket on construction; if the
    orchestrator created the bucket with the wrong ``max_value_size``
    the consumer would fail to put policy entries larger than the
    limit, and if the wrong ``history`` it would lose rotation-audit
    depth. This test guards the create-call shape so the contract
    surfaces in the hermetic suite before it can hit a live cluster.
    """
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )

    seventh_actions = [
        a for a in actions if a.name == "wakir-capability-policies"
    ]
    assert len(seventh_actions) == 1
    assert seventh_actions[0].status == "created"

    seventh_calls = [
        c for c in js.create_calls
        if c["bucket"] == "wakir-capability-policies"
    ]
    assert len(seventh_calls) == 1
    call = seventh_calls[0]
    assert call["history"] == 10
    assert call["ttl"] == 0
    assert call["max_value_size"] == 4_096
    assert call["storage"] == "file"
    assert call["replicas"] == 1
    assert "Phase-3" in call["description"]


def test_t_tag2_04_bucket_filter_can_select_seventh_bucket(mod, event_loop):
    """``--bucket wakir-capability-policies`` selects only the 7th
    bucket.

    Operationally useful: an operator can re-run the init script
    against a cluster that already has the six pre-Tag-2 Phase-1
    buckets to backfill only the new 7th bucket without churning the
    others. This is the no-downtime upgrade path for a cluster that
    came up before Sprint-5 Tag-2 landed.
    """
    js = _MockJetStream()
    selected = mod._select_specs(["wakir-capability-policies"])
    assert [s.name for s in selected] == ["wakir-capability-policies"]

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, selected, dry_run=False)
    )
    assert len(actions) == 1
    assert actions[0].name == "wakir-capability-policies"
    assert actions[0].status == "created"
    assert set(js.buckets) == {"wakir-capability-policies"}


def test_t_tag2_05_seventh_bucket_idempotent_replay_marks_unchanged(
    mod, event_loop
):
    """Re-running the init script after the 7th bucket exists is a
    no-op.

    Idempotency contract for the full seven-bucket layout: operators
    can re-run ``init-nats-buckets.py`` on a cluster that already has
    the complete inventory without side effects. The 7th bucket gets
    the same idempotency guarantee as the six pre-Tag-2 buckets.
    """
    js = _MockJetStream()
    # First pass: populate all seven.
    event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    js.create_calls.clear()

    # Second pass: should be a no-op for the 7th bucket specifically.
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=False)
    )
    seventh_action = next(
        a for a in actions if a.name == "wakir-capability-policies"
    )
    assert seventh_action.status == "unchanged"
    assert js.create_calls == [], (
        "idempotent replay must not re-create the 7th bucket"
    )
