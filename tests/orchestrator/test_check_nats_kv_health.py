# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/check-nats-kv-health.py``.

The script targets a live NATS-JetStream cluster plus an HTTP
``/jsz`` endpoint, but neither is brought up here. Instead we drive
the ``inspect_buckets`` planner against a small in-memory mock that
mirrors the subset of the ``nats.js.JetStreamContext`` API the script
depends on, and we drive ``probe_jsz`` against an injected stub
``urlopen`` callable.

Coverage:

1. Empty cluster: every documented bucket reports ``missing``.
2. Fully-populated cluster: every bucket reports ``ok``.
3. Drift on one bucket: precise ``{want, got}`` diff in the report.
4. ``/jsz`` HTTP 200: probe reports ``ok``; non-2xx and exception
   paths both report ``unreachable``.
5. Exit-code matrix: ``ok``/``missing``/``drift``/error/unreachable
   each map to the documented exit code.
6. Dry-run: emits a plan-only report and never raises (no I/O).
7. JSON output shape: stable summary block, idempotent ``to_json``.
8. Cross-tool inventory parity with ``init-nats-buckets.py``.

A separate ``CheckNatsKvHealthLiveSmokeTests`` class is gated on
``WAKIR_NATS_LIVE=1`` and runs against a Box-3 compose stack.

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
from pathlib import Path
from typing import Any, Mapping, Optional

import pytest


# ---------------------------------------------------------------------
# Module loader (hyphenated filename; same pattern as
# tests/orchestrator/test_init_nats_buckets.py).
# ---------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check-nats-kv-health.py"
_MODULE_NAME = "check_nats_kv_health"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, str(_SCRIPT)
    )
    assert spec is not None and spec.loader is not None, "loader unavailable"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_INIT_SCRIPT = _REPO_ROOT / "scripts" / "init-nats-buckets.py"
_INIT_MODULE_NAME = "init_nats_buckets"


def _load_init_module():
    spec = importlib.util.spec_from_file_location(
        _INIT_MODULE_NAME, str(_INIT_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_INIT_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def init_mod():
    return _load_init_module()


# ---------------------------------------------------------------------
# Mock JetStream + KV surface (mirrors test_init_nats_buckets.py)
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


class _MockBucketNotFound(Exception):
    """Mimics ``nats.js.errors.BucketNotFoundError`` by class-name match."""


@dataclass
class _MockJetStream:
    """In-memory replacement for ``nats.js.JetStreamContext``."""

    buckets: dict = field(default_factory=dict)

    async def key_value(self, *, bucket: str):
        if bucket not in self.buckets:
            raise _MockBucketNotFound(bucket)
        return self.buckets[bucket]


def _seed_bucket(js: _MockJetStream, spec) -> None:
    js.buckets[spec.name] = _MockKv(
        name=spec.name,
        status_payload=_MockKvStatus(
            history=spec.history,
            ttl=spec.ttl_seconds,
            max_value_size=spec.max_value_size,
            storage=spec.storage,
            replicas=spec.replicas,
        ),
    )


# ---------------------------------------------------------------------
# Stubbed urlopen for probe_jsz (no network)
# ---------------------------------------------------------------------


@dataclass
class _StubResponse:
    status: int
    body: bytes = b""

    def read(self, _n: int = -1) -> bytes:
        return self.body

    def close(self) -> None:
        pass


def _make_urlopen_stub(*, status: int):
    def _stub(_url: str, timeout: float = 0):  # noqa: ARG001
        return _StubResponse(status=status, body=b"{}")

    return _stub


def _make_failing_urlopen_stub(exc: Exception):
    def _stub(_url: str, timeout: float = 0):  # noqa: ARG001
        raise exc

    return _stub


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
# Hermetic tests
# ---------------------------------------------------------------------


def test_inspect_against_empty_cluster_reports_all_missing(mod, event_loop):
    js = _MockJetStream()
    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )

    assert [c.status for c in checks] == ["missing"] * len(mod.PHASE_1_BUCKETS)
    assert {c.name for c in checks} == {
        spec.name for spec in mod.PHASE_1_BUCKETS
    }
    # The detail string must point operators at the init script.
    for c in checks:
        assert "init-nats-buckets" in c.detail


def test_inspect_against_fully_populated_cluster_reports_all_ok(mod, event_loop):
    js = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js, spec)

    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )

    assert all(c.status == "ok" for c in checks), [
        (c.name, c.status, c.detail, c.drift) for c in checks
    ]
    assert {c.name for c in checks} == {
        spec.name for spec in mod.PHASE_1_BUCKETS
    }


def test_drift_is_reported_with_precise_diff(mod, event_loop):
    js = _MockJetStream()
    spec = next(s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-schemas")
    # Seed with drifted history (1 instead of 5).
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

    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, [spec])
    )

    assert len(checks) == 1
    c = checks[0]
    assert c.status == "drift"
    assert c.drift == {"history": {"want": 5, "got": 1}}


def test_drift_and_missing_can_coexist_per_bucket(mod, event_loop):
    js = _MockJetStream()
    aip = next(s for s in mod.PHASE_1_BUCKETS if s.name == "wakir-aip-cache")
    # Seed with drifted ttl (3601 vs 3600); leave the other three absent.
    js.buckets[aip.name] = _MockKv(
        name=aip.name,
        status_payload=_MockKvStatus(
            history=aip.history,
            ttl=aip.ttl_seconds + 1,
            max_value_size=aip.max_value_size,
            storage=aip.storage,
            replicas=aip.replicas,
        ),
    )

    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )
    by_name = {c.name: c for c in checks}
    assert by_name["wakir-aip-cache"].status == "drift"
    assert by_name["wakir-aip-cache"].drift == {
        "ttl": {"want": 3600, "got": 3601}
    }
    for name in ("wakir-schemas", "wakir-ftd-cache", "wakir-ftd-poisoned"):
        assert by_name[name].status == "missing"


def test_probe_jsz_ok_on_2xx(mod):
    probe = mod.probe_jsz(
        "http://127.0.0.1:8222/jsz",
        timeout_s=0.1,
        urlopen=_make_urlopen_stub(status=200),
    )
    assert probe.status == "ok"
    assert probe.http_status == 200


def test_probe_jsz_unreachable_on_non_2xx(mod):
    probe = mod.probe_jsz(
        "http://127.0.0.1:8222/jsz",
        timeout_s=0.1,
        urlopen=_make_urlopen_stub(status=503),
    )
    assert probe.status == "unreachable"
    assert probe.http_status == 503
    assert "503" in probe.detail


def test_probe_jsz_unreachable_on_exception(mod):
    probe = mod.probe_jsz(
        "http://127.0.0.1:8222/jsz",
        timeout_s=0.1,
        urlopen=_make_failing_urlopen_stub(ConnectionRefusedError("boom")),
    )
    assert probe.status == "unreachable"
    assert probe.http_status is None
    assert "ConnectionRefusedError" in probe.detail


def test_exit_code_zero_on_clean_state(mod, event_loop):
    js = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js, spec)
    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )
    report = mod.HealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        dry_run=False,
        jsz=mod.JszProbe(status="ok", detail="2xx", http_status=200),
        checks=checks,
    )
    assert mod._exit_code_for(report) == 0


def test_exit_code_two_on_drift_or_missing(mod, event_loop):
    js = _MockJetStream()  # nothing seeded → all missing
    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )
    report = mod.HealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        dry_run=False,
        jsz=mod.JszProbe(status="ok", detail="2xx", http_status=200),
        checks=checks,
    )
    assert mod._exit_code_for(report) == 2


def test_exit_code_one_on_unreachable_jsz_dominates_drift(mod, event_loop):
    js = _MockJetStream()  # all missing
    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )
    report = mod.HealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        dry_run=False,
        jsz=mod.JszProbe(
            status="unreachable", detail="conn refused", http_status=None
        ),
        checks=checks,
    )
    # Exit 1 dominates: a connectivity issue invalidates the drift
    # signal because we may not have a complete view.
    assert mod._exit_code_for(report) == 1


def test_exit_code_one_on_per_bucket_error(mod):
    report = mod.HealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        dry_run=False,
        jsz=mod.JszProbe(status="ok", detail="2xx", http_status=200),
        checks=[
            mod.BucketCheck(
                name="wakir-schemas",
                status="error",
                detail="repr(some-exception)",
            )
        ],
    )
    assert mod._exit_code_for(report) == 1


def test_dry_run_report_has_no_side_effects_and_returns_zero(mod):
    report = mod._render_dry_run_report(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        skip_jsz=False,
        specs=mod.PHASE_1_BUCKETS,
    )
    assert report.dry_run is True
    assert report.jsz.status == "skipped"
    assert all(c.status == "ok" for c in report.checks)
    assert mod._exit_code_for(report) == 0


def test_report_to_json_has_stable_shape_and_summary(mod, event_loop):
    js = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js, spec)
    checks = event_loop.run_until_complete(
        mod.inspect_buckets(js, mod.PHASE_1_BUCKETS)
    )
    report = mod.HealthReport(
        servers="nats://127.0.0.1:4222",
        jsz_url="http://127.0.0.1:8222/jsz",
        dry_run=False,
        jsz=mod.JszProbe(status="ok", detail="2xx", http_status=200),
        checks=checks,
    )
    payload = json.loads(report.to_json())

    assert payload["servers"] == "nats://127.0.0.1:4222"
    assert payload["jsz_url"] == "http://127.0.0.1:8222/jsz"
    assert payload["dry_run"] is False
    assert payload["jsz"] == {
        "status": "ok",
        "detail": "2xx",
        "http_status": 200,
    }
    assert payload["summary"] == {
        "ok": 4,
        "missing": 0,
        "drift": 0,
        "error": 0,
        "total": 4,
    }
    assert {a["name"] for a in payload["checks"]} == {
        spec.name for spec in mod.PHASE_1_BUCKETS
    }
    # Calling to_json twice must produce identical bytes (idempotent
    # serialisation; cron-monitor consumers depend on this).
    assert report.to_json() == report.to_json()


def test_unknown_bucket_selector_raises_value_error(mod):
    with pytest.raises(ValueError) as excinfo:
        mod._select_specs(["wakir-schemas", "wakir-bogus"])
    msg = str(excinfo.value)
    assert "wakir-bogus" in msg
    assert "wakir-schemas" in msg


def test_phase_1_inventory_is_the_documented_four_buckets(mod):
    names = [spec.name for spec in mod.PHASE_1_BUCKETS]
    assert names == [
        "wakir-schemas",
        "wakir-aip-cache",
        "wakir-ftd-cache",
        "wakir-ftd-poisoned",
    ]


def test_inventory_matches_init_nats_buckets(mod, init_mod):
    """The two scripts must agree on the documented Phase-1 inventory.

    A drift between them is a regression: an operator running the init
    script and then the health check would see fabricated drift signals.
    The fields compared are exactly those used by the drift detector.
    """
    health_by_name = {s.name: s for s in mod.PHASE_1_BUCKETS}
    init_by_name = {s.name: s for s in init_mod.PHASE_1_BUCKETS}
    assert set(health_by_name) == set(init_by_name)
    for name, h in health_by_name.items():
        i = init_by_name[name]
        assert h.history == i.history, name
        assert h.ttl_seconds == i.ttl_seconds, name
        assert h.max_value_size == i.max_value_size, name
        assert h.storage == i.storage, name
        assert h.replicas == i.replicas, name


# ---------------------------------------------------------------------
# Live smoke tests (gated on WAKIR_NATS_LIVE=1)
# ---------------------------------------------------------------------


_LIVE_FLAG = os.environ.get("WAKIR_NATS_LIVE") == "1"
_LIVE_REASON = (
    "WAKIR_NATS_LIVE!=1; live smoke tests require the Box-3 compose "
    "stack and nats-py installed. See docs/orchestrator-nats-kv-"
    "phase-1-runbook.md §5.1."
)


@unittest.skipUnless(_LIVE_FLAG, _LIVE_REASON)
class CheckNatsKvHealthLiveSmokeTests(unittest.TestCase):
    """Live smoke tests against a real Phase-1b NATS-JetStream cluster.

    Pre-conditions (enforced by ``setUpClass``):

    * ``WAKIR_NATS_LIVE=1`` in the environment.
    * ``nats-py`` importable.
    * NATS reachable at ``WAKIR_NATS_URL`` (default
      ``nats://127.0.0.1:4222``).
    * ``/jsz`` reachable at ``WAKIR_NATS_JSZ_URL`` (default
      ``http://127.0.0.1:8222/jsz``).
    * Buckets pre-created by ``scripts/init-nats-buckets.py``.

    These tests exercise the read-only path end-to-end. They never
    write to the cluster.
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import nats  # noqa: F401
        except ImportError:
            raise unittest.SkipTest(
                "nats-py not installed; cannot run live smoke."
            )
        cls.servers = os.environ.get(
            "WAKIR_NATS_URL", "nats://127.0.0.1:4222"
        )
        cls.jsz_url = os.environ.get(
            "WAKIR_NATS_JSZ_URL", "http://127.0.0.1:8222/jsz"
        )
        cls.token = os.environ.get("WAKIR_NATS_TOKEN") or None
        cls.mod = _load_module()

    def test_smoke_jsz_ok(self) -> None:
        probe = self.mod.probe_jsz(self.jsz_url, timeout_s=3.0)
        self.assertEqual(probe.status, "ok", msg=probe.detail)

    def test_smoke_inspect_against_live_cluster(self) -> None:
        async def _run():
            import nats  # type: ignore

            nc = await nats.connect(self.servers, token=self.token)
            try:
                js = nc.jetstream()
                return await self.mod.inspect_buckets(
                    js, self.mod.PHASE_1_BUCKETS
                )
            finally:
                await nc.drain()

        checks = asyncio.run(_run())
        # We do not assert "ok" — the live cluster may be a stale
        # tear-down or in mid-bring-up. We DO assert the shape:
        # exactly four checks, names match the inventory, no errors.
        self.assertEqual(len(checks), 4)
        self.assertEqual(
            {c.name for c in checks},
            {s.name for s in self.mod.PHASE_1_BUCKETS},
        )
        for c in checks:
            self.assertNotEqual(c.status, "error", msg=(c.name, c.detail))


if __name__ == "__main__":
    unittest.main()
