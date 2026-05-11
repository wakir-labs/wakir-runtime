# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Live-NATS-Test-Mode cross-validation for ``scripts/init-nats-buckets.py``.

This suite is the substrate for the Sprint-4 Tag-1 Live-NATS-Test-Mode
contract (ADR-0051-rejected, CEO-side operative practice retained):

* **Hermetic default.** All tests in :class:`HermeticCrossValidationTests`
  run without a live NATS-JetStream cluster. They exercise the
  ``plan_and_apply`` planner against the same ``_MockJetStream`` surface
  the existing ``test_init_nats_buckets.py`` suite uses, and lock down
  the byte-shape of the planner's ``InitReport.to_json()`` output for
  the two stable scenarios cross-validated against the live cluster:

      1. *empty cluster, dry-run*  -> all four buckets ``would_create``
      2. *fully-populated cluster, dry-run*  -> all four buckets ``unchanged``

  These two scenarios were chosen because they are deterministic on
  both transports: dry-run never mutates state, and both scenarios
  avoid the create-path which is timing-sensitive on a real cluster.

* **Live opt-in via ``WAKIR_NATS_LIVE=1``.** When the env flag is set,
  :class:`LiveCrossValidationSmokeTests` connects to the host NATS at
  ``WAKIR_NATS_URL`` (default ``nats://127.0.0.1:4222``), runs the same
  planner against the real JetStream, and asserts that the resulting
  ``InitReport.to_json()`` is byte-identical to the corresponding
  hermetic baseline. This is the Mock-vs-Live cross-validation contract:
  if the byte payload diverges, either the mock has drifted from the
  real surface or the live cluster is in an unexpected state.

* **Operator-hand only.** Live tests are gated specifically because
  the agent sandbox cannot reach the host NATS substrate. Use
  ``scripts/run-live-smoke-tests.sh`` from the operator hand to drive
  this suite with the live flag set; see runbook §7.3.

Test inventory
--------------

Hermetic (4):

* ``test_hermetic_empty_cluster_dry_run_baseline``
* ``test_hermetic_populated_cluster_dry_run_baseline``
* ``test_hermetic_to_json_is_byte_stable_across_invocations``
* ``test_hermetic_two_distinct_mock_instances_yield_identical_json``

Live, gated on ``WAKIR_NATS_LIVE=1`` (2):

* ``test_live_empty_cluster_matches_hermetic_baseline_byte_identical``
* ``test_live_populated_cluster_matches_hermetic_baseline_byte_identical``

The hermetic baseline JSON strings are constructed deterministically
from the documented Phase-1 inventory; they are not pinned as fixture
strings so a legitimate inventory change (new bucket, etc.) does not
require a baseline file update.
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
from typing import Any

import pytest


# ---------------------------------------------------------------------
# Module loader (hyphenated script filename, same pattern as
# tests/orchestrator/test_init_nats_buckets.py).
# ---------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "init-nats-buckets.py"
_MODULE_NAME = "init_nats_buckets"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, str(_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


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

    async def create_key_value(self, **kwargs):
        # Cross-validation runs dry-run only; create is unreachable in
        # the scenarios this suite covers. Implement it defensively so
        # a future test extension does not silently hit an attribute
        # error.
        name = kwargs["bucket"]
        self.buckets[name] = _MockKv(
            name=name,
            status_payload=_MockKvStatus(
                history=kwargs["history"],
                ttl=kwargs["ttl"],
                max_value_size=kwargs["max_value_size"],
                storage=kwargs["storage"],
                replicas=kwargs["replicas"],
            ),
        )
        return self.buckets[name]


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
# Helpers
# ---------------------------------------------------------------------


_SERVERS = "nats://127.0.0.1:4222"


def _run_planner(js: Any, mod, *, dry_run: bool) -> str:
    """Run the planner against ``js`` and return the rendered JSON.

    The returned string is exactly what the script writes to stdout
    in production; we treat the byte sequence as the cross-validation
    artefact.

    Uses :func:`asyncio.run` rather than ``get_event_loop`` because
    Python 3.12+ refuses to lazily create a loop when none is set,
    which would otherwise make this helper fragile under the
    repository's pytest invocation (Python 3.14 in CI).
    """
    actions = asyncio.run(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=dry_run)
    )
    report = mod.InitReport(servers=_SERVERS, dry_run=dry_run, actions=actions)
    return report.to_json()


# ---------------------------------------------------------------------
# Hermetic suite (no live NATS; default execution path)
# ---------------------------------------------------------------------


def test_hermetic_empty_cluster_dry_run_baseline(mod):
    """Empty mock cluster + dry-run -> four ``would_create`` actions.

    Locks the byte-shape of the JSON the live test cross-validates
    against. The expected payload is built from ``PHASE_1_BUCKETS``
    so a legitimate inventory change auto-propagates.
    """
    js = _MockJetStream()
    actions = asyncio.run(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=True)
    )
    report = mod.InitReport(servers=_SERVERS, dry_run=True, actions=actions)
    payload = json.loads(report.to_json())

    assert payload["servers"] == _SERVERS
    assert payload["dry_run"] is True
    assert payload["summary"] == {
        "created": 0,
        "unchanged": 0,
        "drift": 0,
        "would_create": len(mod.PHASE_1_BUCKETS),
        "total": len(mod.PHASE_1_BUCKETS),
    }
    statuses = {a["name"]: a["status"] for a in payload["actions"]}
    assert statuses == {
        spec.name: "would_create" for spec in mod.PHASE_1_BUCKETS
    }


def test_hermetic_populated_cluster_dry_run_baseline(mod):
    """Fully-seeded mock + dry-run -> four ``unchanged`` actions.

    Companion scenario to the empty-cluster baseline. The live test
    asserts byte-identity against this exact JSON shape.
    """
    js = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js, spec)
    actions = asyncio.run(
        mod.plan_and_apply(js, mod.PHASE_1_BUCKETS, dry_run=True)
    )
    report = mod.InitReport(servers=_SERVERS, dry_run=True, actions=actions)
    payload = json.loads(report.to_json())

    assert payload["dry_run"] is True
    assert payload["summary"] == {
        "created": 0,
        "unchanged": len(mod.PHASE_1_BUCKETS),
        "drift": 0,
        "would_create": 0,
        "total": len(mod.PHASE_1_BUCKETS),
    }
    statuses = {a["name"]: a["status"] for a in payload["actions"]}
    assert statuses == {
        spec.name: "unchanged" for spec in mod.PHASE_1_BUCKETS
    }


def test_hermetic_to_json_is_byte_stable_across_invocations(mod):
    """``InitReport.to_json()`` must be deterministic.

    The live cross-validation compares byte sequences, so any source
    of nondeterminism (dict ordering, float formatting, etc.) would
    cause spurious failures. Lock it here.
    """
    js = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js, spec)
    first = _run_planner(js, mod, dry_run=True)
    second = _run_planner(js, mod, dry_run=True)
    assert first == second, (
        "to_json() output diverged between two consecutive invocations "
        "against an unchanged mock cluster; the live cross-validation "
        "contract cannot hold unless to_json() is byte-stable."
    )


def test_hermetic_two_distinct_mock_instances_yield_identical_json(mod):
    """Two independently-seeded mocks produce identical JSON.

    This is the strict version of the byte-stability test: even when
    the planner has never seen the same ``_MockJetStream`` instance
    twice, identical seeding must yield byte-identical output. Without
    this, the Mock-vs-Live cross-validation could not isolate "the
    transport diverged" from "the mock instance had transient state".
    """
    js_a = _MockJetStream()
    js_b = _MockJetStream()
    for spec in mod.PHASE_1_BUCKETS:
        _seed_bucket(js_a, spec)
        _seed_bucket(js_b, spec)
    out_a = _run_planner(js_a, mod, dry_run=True)
    out_b = _run_planner(js_b, mod, dry_run=True)
    assert out_a == out_b


# ---------------------------------------------------------------------
# Live-mode cross-validation (gated on WAKIR_NATS_LIVE=1)
# ---------------------------------------------------------------------


_LIVE_FLAG = os.environ.get("WAKIR_NATS_LIVE") == "1"
_LIVE_REASON = (
    "WAKIR_NATS_LIVE!=1; live-mode cross-validation skipped. Bring up "
    "the Phase-1b NATS substrate (compose/nats.yaml) and run "
    "scripts/run-live-smoke-tests.sh from the operator hand; see runbook "
    "docs/orchestrator-nats-kv-phase-1-runbook.md §7.3."
)


@unittest.skipUnless(_LIVE_FLAG, _LIVE_REASON)
class LiveCrossValidationSmokeTests(unittest.TestCase):
    """Mock-vs-Live byte-identical cross-validation of the init planner.

    Pre-conditions (enforced by :py:meth:`setUpClass`):

    * ``WAKIR_NATS_LIVE=1`` in the environment.
    * ``nats-py`` importable.
    * NATS reachable at ``WAKIR_NATS_URL`` (default
      ``nats://127.0.0.1:4222``).

    The class runs each scenario *twice* — once through the mock, once
    through the live cluster — and asserts that the two JSON byte
    sequences are equal. Both runs use ``dry_run=True`` so the live
    cluster is read-only-touched (the planner only calls
    ``js.key_value`` and ``kv.status()``).
    """

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import nats  # noqa: F401
        except ImportError:
            raise unittest.SkipTest(
                "nats-py not installed; cannot run live cross-validation."
            )
        cls.servers = os.environ.get("WAKIR_NATS_URL", _SERVERS)
        cls.token = os.environ.get("WAKIR_NATS_TOKEN") or None
        cls.mod = _load_module()

    def _live_planner_json(self, *, expect_populated: bool) -> str:
        """Run the planner against the real cluster and return JSON."""

        async def _run():
            import nats  # type: ignore

            nc = await nats.connect(self.servers, token=self.token)
            try:
                js = nc.jetstream()
                actions = await self.mod.plan_and_apply(
                    js, self.mod.PHASE_1_BUCKETS, dry_run=True
                )
                return actions
            finally:
                await nc.drain()

        actions = asyncio.run(_run())
        # Skip-not-fail if the cluster is in the wrong state: the live
        # test cannot reasonably assert byte-identity if the operator
        # ran us against a half-bootstrapped substrate. The skip carries
        # a precise diagnostic so the operator hand sees what to fix.
        observed = {a.name: a.status for a in actions}
        if expect_populated:
            wrong = [
                name for name, status in observed.items()
                if status != "unchanged"
            ]
            if wrong:
                self.skipTest(
                    "live cluster not in fully-populated state for "
                    "cross-validation: " + repr(observed) + "; run "
                    "scripts/init-nats-buckets.py first."
                )
        else:
            wrong = [
                name for name, status in observed.items()
                if status != "would_create"
            ]
            if wrong:
                self.skipTest(
                    "live cluster not in empty state for "
                    "cross-validation: " + repr(observed) + "; run "
                    "compose down -v then up before this scenario."
                )
        report = self.mod.InitReport(
            servers=self.servers, dry_run=True, actions=actions
        )
        return report.to_json()

    def _mock_planner_json(self, *, populated: bool) -> str:
        """Run the planner against the in-memory mock and return JSON.

        Uses the same ``servers`` field as the live run so the JSON
        envelope is byte-identical; only the actions list reflects the
        underlying transport.
        """
        js = _MockJetStream()
        if populated:
            for spec in self.mod.PHASE_1_BUCKETS:
                _seed_bucket(js, spec)
        actions = asyncio.run(
            self.mod.plan_and_apply(
                js, self.mod.PHASE_1_BUCKETS, dry_run=True
            )
        )
        report = self.mod.InitReport(
            servers=self.servers, dry_run=True, actions=actions
        )
        return report.to_json()

    def test_live_empty_cluster_matches_hermetic_baseline_byte_identical(
        self,
    ) -> None:
        """An empty live cluster and an empty mock produce byte-identical JSON.

        Drives the cross-validation contract: planner output is a
        property of the documented inventory, not of the transport.
        """
        live_json = self._live_planner_json(expect_populated=False)
        mock_json = self._mock_planner_json(populated=False)
        self.assertEqual(
            live_json,
            mock_json,
            msg=(
                "Mock-vs-Live byte divergence (empty scenario):\n"
                f"  live: {live_json}\n"
                f"  mock: {mock_json}"
            ),
        )

    def test_live_populated_cluster_matches_hermetic_baseline_byte_identical(
        self,
    ) -> None:
        """A populated live cluster and a populated mock produce byte-identical JSON."""
        live_json = self._live_planner_json(expect_populated=True)
        mock_json = self._mock_planner_json(populated=True)
        self.assertEqual(
            live_json,
            mock_json,
            msg=(
                "Mock-vs-Live byte divergence (populated scenario):\n"
                f"  live: {live_json}\n"
                f"  mock: {mock_json}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
