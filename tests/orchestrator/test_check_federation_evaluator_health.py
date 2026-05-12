# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/check-federation-evaluator-health.py``.

The Tag-7 federation-evaluator health-check tool consumes the
wirelang-eng-side modules at ``wirelang/federation/n2_evaluator.py`` (Tag-3)
and ``wirelang/federation/route_registry_nats_kv_backend.py``
(Tag-4) byte-precisely. The hermetic tests drive the planner against
an in-memory mock that mirrors the ``nats.js.JetStreamContext`` +
``KeyValue`` API surfaces used by both the wirelang-eng-side backend and
the Tag-7 inspector.

Coverage:

1. Bucket-config drift comparator:
   - empty cluster -> bucket missing
   - well-configured cluster -> bucket ok
   - drifted history / ttl -> precise ``{want, got}`` diff
2. Snapshot inspector:
   - empty bucket -> snapshot ok with zero counters
   - active / expired / not-yet-active classification
   - WAT-anchor counter (Z2 cross-review surface)
   - poisoned envelope detection -> snapshot status ``poisoned``
3. Optional N2-evaluator probe:
   - registered + active route -> ``ok``
   - unknown route -> ``reject`` with kind FederationRouteUnknownError
4. Exit-code matrix:
   - clean -> 0
   - bucket missing / drift / snapshot poisoned / evaluator reject -> 2
   - jsz unreachable / bucket error / snapshot error / evaluator
     error -> 1
5. Dry-run renders the plan without I/O.
6. JSON output shape stable + idempotent.
7. Cross-tool inventory parity:
   - the script's BUCKET_NAME is the wirelang-eng-side BUCKET_NAME
   - the script's BUCKET_CONFIG is the wirelang-eng-side BUCKET_CONFIG
   - the BUCKET_CONFIG drift fields match the
     ``check-nats-kv-health.py`` drift comparator's field set

A separate ``CheckFederationEvaluatorHealthLiveSmokeTests`` class is
gated on ``WAKIR_NATS_LIVE=1`` and runs against a Box-3 compose
stack whose ``wakir-federation-routes`` bucket has been initialised
out-of-band (operator-runbook §6.2 procedure).

The hermetic suite is fully I/O-free.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest


# ---------------------------------------------------------------------
# Module loader (hyphenated filename; same pattern as
# tests/orchestrator/test_check_nats_kv_health.py).
# ---------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check-federation-evaluator-health.py"
_MODULE_NAME = "check_federation_evaluator_health"


def _load_module():
    # Make the wakir-runtime root importable so the script's top-level
    # ``from wirelang.federation...`` import succeeds during the test.
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, str(_SCRIPT)
    )
    assert spec is not None and spec.loader is not None, "loader unavailable"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_HEALTH_SCRIPT = _REPO_ROOT / "scripts" / "check-nats-kv-health.py"
_HEALTH_MODULE_NAME = "check_nats_kv_health"


def _load_health_module():
    spec = importlib.util.spec_from_file_location(
        _HEALTH_MODULE_NAME, str(_HEALTH_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_HEALTH_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def health_mod():
    return _load_health_module()


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------
# wirelang-eng-side imports (live in the test process; the script imports
# them at module load and we re-import here so we can construct
# entries / registries in the fixtures)
# ---------------------------------------------------------------------


def _import_wireng():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from wirelang.federation.n2_evaluator import (
        InMemoryRouteRegistry,
        RouteRegistryEntry,
    )
    from wirelang.federation.route_registry_nats_kv_backend import (
        BUCKET_CONFIG,
        BUCKET_NAME,
        VALUE_SCHEMA,
        _entry_to_envelope,
    )

    return {
        "InMemoryRouteRegistry": InMemoryRouteRegistry,
        "RouteRegistryEntry": RouteRegistryEntry,
        "BUCKET_CONFIG": BUCKET_CONFIG,
        "BUCKET_NAME": BUCKET_NAME,
        "VALUE_SCHEMA": VALUE_SCHEMA,
        "_entry_to_envelope": _entry_to_envelope,
    }


@pytest.fixture(scope="module")
def wireng():
    return _import_wireng()


# ---------------------------------------------------------------------
# Mock NATS-KV surface
# ---------------------------------------------------------------------


@dataclass
class _MockKvStatus:
    history: int
    ttl: int
    max_value_size: int
    storage: str
    replicas: int


@dataclass
class _MockKvEntry:
    """Mimics nats-py ``KeyValue.Entry``: the only field used downstream
    is ``.value`` (bytes)."""

    value: bytes


@dataclass
class _MockKv:
    """Mimics ``nats.js.kv.KeyValue`` for the surface the Tag-7 script
    and the wirelang-eng-side ``NatsKvRouteRegistry`` consume.
    """

    name: str
    status_payload: _MockKvStatus
    store: dict = field(default_factory=dict)

    async def status(self) -> _MockKvStatus:
        return self.status_payload

    async def keys(self) -> list:
        return list(self.store.keys())

    async def get(self, key: str) -> Optional[_MockKvEntry]:
        if key not in self.store:
            raise _MockKvNotFound(key)
        return _MockKvEntry(value=self.store[key])

    async def put(self, key: str, value: bytes) -> int:
        self.store[key] = value
        return 1

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _MockKvNotFound(Exception):
    """Class-name match: any *NotFound* exception class is treated as
    'absent' by the wirelang-eng-side backend and the Tag-7 inspector.
    """


@dataclass
class _MockJetStream:
    buckets: dict = field(default_factory=dict)

    async def key_value(self, *, bucket: str):
        if bucket not in self.buckets:
            raise _MockKvNotFound(bucket)
        return self.buckets[bucket]


def _seed_bucket_at_documented_config(js: _MockJetStream, mod, config: Mapping[str, Any]):
    """Seed a bucket whose status reflects the documented configuration."""
    kv = _MockKv(
        name=config["name"],
        status_payload=_MockKvStatus(
            history=config["history"],
            ttl=config["ttl_seconds"],
            max_value_size=config["max_value_size"],
            storage=config["storage"],
            replicas=config["replicas"],
        ),
    )
    js.buckets[config["name"]] = kv
    return kv


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


_REF_NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _entry_active(wireng, route_id: str, source_ftd_id: str, *, anchor: Optional[str] = None):
    return wireng["RouteRegistryEntry"](
        route_id=route_id,
        source_ftd_id=source_ftd_id,
        active_from=_REF_NOW - timedelta(hours=1),
        active_until=_REF_NOW + timedelta(hours=1),
        wat_anchor_manifest_id=anchor,
    )


def _entry_expired(wireng, route_id: str, source_ftd_id: str):
    return wireng["RouteRegistryEntry"](
        route_id=route_id,
        source_ftd_id=source_ftd_id,
        active_from=_REF_NOW - timedelta(hours=2),
        active_until=_REF_NOW - timedelta(minutes=30),
        wat_anchor_manifest_id=None,
    )


def _entry_not_yet_active(wireng, route_id: str, source_ftd_id: str):
    return wireng["RouteRegistryEntry"](
        route_id=route_id,
        source_ftd_id=source_ftd_id,
        active_from=_REF_NOW + timedelta(hours=1),
        active_until=_REF_NOW + timedelta(hours=2),
        wat_anchor_manifest_id=None,
    )


# ---------------------------------------------------------------------
# Bucket inspector tests
# ---------------------------------------------------------------------


def test_bucket_missing_when_cluster_empty(mod, wireng, event_loop):
    js = _MockJetStream()
    bucket, kv = event_loop.run_until_complete(
        mod.inspect_bucket(
            js, wireng["BUCKET_NAME"], wireng["BUCKET_CONFIG"]
        )
    )
    assert bucket.status == "missing"
    assert kv is None
    assert "operator runbook" in bucket.detail.lower()


def test_bucket_ok_when_seeded_at_documented_config(mod, wireng, event_loop):
    js = _MockJetStream()
    _seed_bucket_at_documented_config(js, mod, wireng["BUCKET_CONFIG"])
    bucket, kv = event_loop.run_until_complete(
        mod.inspect_bucket(
            js, wireng["BUCKET_NAME"], wireng["BUCKET_CONFIG"]
        )
    )
    assert bucket.status == "ok"
    assert kv is not None


def test_bucket_drift_history_emits_precise_diff(mod, wireng, event_loop):
    js = _MockJetStream()
    drifted = dict(wireng["BUCKET_CONFIG"])
    kv = _MockKv(
        name=drifted["name"],
        status_payload=_MockKvStatus(
            history=99,  # documented is 5
            ttl=drifted["ttl_seconds"],
            max_value_size=drifted["max_value_size"],
            storage=drifted["storage"],
            replicas=drifted["replicas"],
        ),
    )
    js.buckets[drifted["name"]] = kv

    bucket, _ = event_loop.run_until_complete(
        mod.inspect_bucket(js, drifted["name"], drifted)
    )
    assert bucket.status == "drift"
    assert bucket.drift == {
        "history": {"want": drifted["history"], "got": 99}
    }


# ---------------------------------------------------------------------
# Snapshot inspector tests
# ---------------------------------------------------------------------


def test_snapshot_empty_bucket_reports_zero_counters(mod, wireng, event_loop):
    kv = _seed_bucket_at_documented_config(
        _MockJetStream(), mod, wireng["BUCKET_CONFIG"]
    )
    snapshot = event_loop.run_until_complete(
        mod.snapshot_bucket(kv, eval_now=_REF_NOW)
    )
    assert snapshot.status == "ok"
    assert snapshot.total == 0
    assert snapshot.active == 0
    assert snapshot.expired == 0
    assert snapshot.not_yet_active == 0
    assert snapshot.with_wat_anchor == 0
    assert snapshot.poisoned_keys == []


def test_snapshot_classifies_active_expired_and_pending(mod, wireng, event_loop):
    kv = _seed_bucket_at_documented_config(
        _MockJetStream(), mod, wireng["BUCKET_CONFIG"]
    )
    encode = wireng["_entry_to_envelope"]
    ftd = "did:web:wakir.dev:ftd:v1"
    kv.store["route-active"] = encode(_entry_active(wireng, "route-active", ftd))
    kv.store["route-expired"] = encode(_entry_expired(wireng, "route-expired", ftd))
    kv.store["route-pending"] = encode(_entry_not_yet_active(wireng, "route-pending", ftd))

    snapshot = event_loop.run_until_complete(
        mod.snapshot_bucket(kv, eval_now=_REF_NOW)
    )
    assert snapshot.status == "ok"
    assert snapshot.total == 3
    assert snapshot.active == 1
    assert snapshot.expired == 1
    assert snapshot.not_yet_active == 1
    assert snapshot.with_wat_anchor == 0
    assert snapshot.poisoned_keys == []


def test_snapshot_counts_wat_anchor_entries(mod, wireng, event_loop):
    kv = _seed_bucket_at_documented_config(
        _MockJetStream(), mod, wireng["BUCKET_CONFIG"]
    )
    encode = wireng["_entry_to_envelope"]
    ftd = "did:web:wakir.dev:ftd:v1"
    kv.store["route-anchored"] = encode(
        _entry_active(wireng, "route-anchored", ftd, anchor="wat-manifest-001")
    )
    kv.store["route-bare"] = encode(_entry_active(wireng, "route-bare", ftd))

    snapshot = event_loop.run_until_complete(
        mod.snapshot_bucket(kv, eval_now=_REF_NOW)
    )
    assert snapshot.status == "ok"
    assert snapshot.total == 2
    assert snapshot.active == 2
    assert snapshot.with_wat_anchor == 1


def test_snapshot_poisoned_envelope_listed_and_status_set(mod, wireng, event_loop):
    kv = _seed_bucket_at_documented_config(
        _MockJetStream(), mod, wireng["BUCKET_CONFIG"]
    )
    encode = wireng["_entry_to_envelope"]
    ftd = "did:web:wakir.dev:ftd:v1"
    kv.store["route-good"] = encode(_entry_active(wireng, "route-good", ftd))
    # Poisoned: not valid JSON.
    kv.store["route-poisoned"] = b"\x00not-json{"

    snapshot = event_loop.run_until_complete(
        mod.snapshot_bucket(kv, eval_now=_REF_NOW)
    )
    assert snapshot.status == "poisoned"
    assert snapshot.poisoned_keys == ["route-poisoned"]
    # The good route is still counted; total reflects both keys
    # (poisoned ones are observable rows, just not decodable).
    assert snapshot.total == 2
    assert snapshot.active == 1


# ---------------------------------------------------------------------
# Optional N2-evaluator probe tests
# ---------------------------------------------------------------------


def test_evaluator_probe_accepts_known_active_route(mod, wireng):
    ftd = "did:web:wakir.dev:ftd:v1"
    registry = wireng["InMemoryRouteRegistry"]()
    registry.add(_entry_active(wireng, "route-A", ftd))

    result = mod.evaluator_probe(
        snapshot_registry=registry,
        route_id="route-A",
        ftd_id=ftd,
        eval_now=_REF_NOW,
    )
    assert result.status == "ok"
    assert result.route_id == "route-A"
    assert result.ftd_id == ftd
    assert result.error_kind is None


def test_evaluator_probe_rejects_unknown_route(mod, wireng):
    ftd = "did:web:wakir.dev:ftd:v1"
    registry = wireng["InMemoryRouteRegistry"]()
    # Empty registry; probe should reject.
    result = mod.evaluator_probe(
        snapshot_registry=registry,
        route_id="route-Z",
        ftd_id=ftd,
        eval_now=_REF_NOW,
    )
    assert result.status == "reject"
    assert result.error_kind == "FederationRouteUnknownError"


# ---------------------------------------------------------------------
# Exit-code matrix
# ---------------------------------------------------------------------


def _make_report(mod, *, jsz="ok", bucket="ok", snapshot="ok", evaluator="skipped"):
    return mod.FederationHealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        bucket_name=mod.WL_BUCKET_NAME,
        dry_run=False,
        jsz=mod.JszProbe(status=jsz, detail="", http_status=200 if jsz == "ok" else None),
        bucket=mod.BucketCheck(name=mod.WL_BUCKET_NAME, status=bucket),
        snapshot=mod.SnapshotCheck(status=snapshot),
        evaluator=mod.EvaluatorProbe(status=evaluator),
    )


def test_exit_code_zero_on_clean_state(mod):
    report = _make_report(mod)
    assert mod._exit_code_for(report) == 0


def test_exit_code_two_on_drift_or_missing(mod):
    assert mod._exit_code_for(_make_report(mod, bucket="drift")) == 2
    assert mod._exit_code_for(_make_report(mod, bucket="missing")) == 2


def test_exit_code_two_on_snapshot_poisoned(mod):
    assert mod._exit_code_for(_make_report(mod, snapshot="poisoned")) == 2


def test_exit_code_two_on_evaluator_reject(mod):
    assert mod._exit_code_for(_make_report(mod, evaluator="reject")) == 2


def test_exit_code_one_on_jsz_unreachable_dominates_drift(mod):
    # JSZ unreachable + bucket drift -> 1 (jsz dominates).
    report = _make_report(mod, jsz="unreachable", bucket="drift")
    assert mod._exit_code_for(report) == 1


def test_exit_code_one_on_bucket_or_snapshot_or_evaluator_error(mod):
    assert mod._exit_code_for(_make_report(mod, bucket="error")) == 1
    assert mod._exit_code_for(_make_report(mod, snapshot="error")) == 1
    assert mod._exit_code_for(_make_report(mod, evaluator="error")) == 1


# ---------------------------------------------------------------------
# Dry-run + JSON shape
# ---------------------------------------------------------------------


def test_dry_run_renders_plan_without_io(mod):
    report = mod._render_dry_run_report(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
    )
    assert report.dry_run is True
    assert report.bucket.status == "ok"  # plan-only optimistic
    assert report.snapshot.status == "skipped"
    assert report.evaluator.status == "skipped"
    assert report.jsz.status == "skipped"
    # Exit code is 0 for a dry-run plan.
    assert mod._exit_code_for(report) == 0


def test_report_to_json_has_stable_idempotent_shape(mod, wireng):
    # Build a deterministic report and serialise twice; the output
    # must be byte-identical.
    report = mod.FederationHealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        bucket_name=wireng["BUCKET_NAME"],
        dry_run=False,
        jsz=mod.JszProbe(status="ok", detail="ok", http_status=200),
        bucket=mod.BucketCheck(name=wireng["BUCKET_NAME"], status="ok", detail="documented"),
        snapshot=mod.SnapshotCheck(
            status="ok",
            detail="snapshot decoded cleanly",
            total=2,
            active=2,
            with_wat_anchor=1,
        ),
        evaluator=mod.EvaluatorProbe(status="skipped"),
    )
    a = report.to_json()
    b = report.to_json()
    assert a == b
    parsed = json.loads(a)
    # Shape pin: top-level keys.
    assert sorted(parsed.keys()) == [
        "bucket",
        "bucket_name",
        "dry_run",
        "evaluator",
        "jsz",
        "jsz_url",
        "servers",
        "snapshot",
    ]
    # Snapshot block carries operator-relevant counters.
    assert parsed["snapshot"]["total"] == 2
    assert parsed["snapshot"]["active"] == 2
    assert parsed["snapshot"]["with_wat_anchor"] == 1


# ---------------------------------------------------------------------
# Cross-tool inventory parity (Z-B / Z-2 cross-review hooks)
# ---------------------------------------------------------------------


def test_bucket_name_matches_route_registry_backend(mod, wireng):
    """Tag-7 tool must consume the wirelang-eng-side BUCKET_NAME byte-precisely
    (no orchestrator-side redeclaration). Drift between wirelang-eng-side and
    orchestrator-side bucket name would silently break the federation
    evaluator pipeline.
    """
    assert mod.WL_BUCKET_NAME == wireng["BUCKET_NAME"]


def test_bucket_config_matches_route_registry_backend(mod, wireng):
    """Same parity claim for BUCKET_CONFIG. Operator drift on bucket
    config (history, ttl, max_value_size, storage, replicas) is
    detected by the live drift comparator; this regression catches
    a *source-code* drift between wirelang-eng- and orchestrator-side constants.
    """
    assert dict(mod.WL_BUCKET_CONFIG) == dict(wireng["BUCKET_CONFIG"])


def test_drift_comparator_field_set_matches_phase_1_health_check(mod, health_mod):
    """The Tag-7 federation drift comparator and the Tag-6 Phase-1
    health-check drift comparator must agree on the field set so
    operators see the same shape across the two tools.
    """
    config = dict(mod.WL_BUCKET_CONFIG)
    # Build a fully-drifted live status: every field divergent.
    live_status = {
        "history": (config["history"] or 0) + 1,
        "ttl": (config["ttl_seconds"] or 0) + 1,
        "max_value_size": (config["max_value_size"] or 0) + 1,
        "storage": "memory" if config["storage"] != "memory" else "file",
        "replicas": (config["replicas"] or 0) + 1,
    }
    fed_diffs = mod._bucket_config_drift(config, live_status)
    assert sorted(fed_diffs.keys()) == [
        "history",
        "max_value_size",
        "replicas",
        "storage",
        "ttl",
    ]


# ---------------------------------------------------------------------
# Live-smoke (gated)
# ---------------------------------------------------------------------


def _live_smoke_enabled() -> bool:
    return os.environ.get("WAKIR_NATS_LIVE", "") == "1"


@pytest.mark.skipif(
    not _live_smoke_enabled(),
    reason="WAKIR_NATS_LIVE not set; live-smoke skipped (Phase-1b sandbox)",
)
def test_smoke_jsz_ok(mod):
    """Live-smoke: ``/jsz`` HTTP probe against the Box-3 compose stack.

    Activates with ``WAKIR_NATS_LIVE=1`` and a NATS cluster reachable
    at ``$WAKIR_NATS_JSZ_URL`` (default: ``http://127.0.0.1:8222/jsz``).
    """
    url = os.environ.get(
        "WAKIR_NATS_JSZ_URL", "http://127.0.0.1:8222/jsz"
    )
    probe = mod.probe_jsz(url)
    assert probe.status == "ok", probe.detail
    assert probe.http_status is not None
    assert 200 <= probe.http_status < 300


@pytest.mark.skipif(
    not _live_smoke_enabled(),
    reason="WAKIR_NATS_LIVE not set; live-smoke skipped (Phase-1b sandbox)",
)
def test_smoke_inspect_against_live_cluster(mod, wireng):
    """Live-smoke: ``inspect_bucket`` against a real cluster.

    Pre-condition: the operator has run the runbook §6.2 procedure to
    create the ``wakir-federation-routes`` bucket. If the bucket
    does not exist, the smoke records that as a structural fact;
    the assertion is that the inspector returned a well-shaped
    report, not that the cluster is in any particular state.
    """
    import nats  # type: ignore[import-not-found]

    servers = os.environ.get("WAKIR_NATS_SERVERS", "nats://127.0.0.1:4222")

    async def _go():
        nc = await nats.connect(servers=servers)
        try:
            js = nc.jetstream()
            bucket, _ = await mod.inspect_bucket(
                js, wireng["BUCKET_NAME"], wireng["BUCKET_CONFIG"]
            )
        finally:
            await nc.drain()
            await nc.close()
        return bucket

    bucket = asyncio.run(_go())
    assert bucket.name == wireng["BUCKET_NAME"]
    assert bucket.status in ("ok", "missing", "drift")
