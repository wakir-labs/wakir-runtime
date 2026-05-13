# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``bin/nats-kv-bucket-provision`` (Phase-2
Sprint-9 Tag-1 per-org marker-stack-event bucket provisioner).

The provisioner targets a live NATS-JetStream cluster; we do not
stand one up here. The hermetic surface drives ``plan_and_apply``
against an in-memory mock JetStream context that mirrors the subset
of the ``nats.js.JetStreamContext`` API the provisioner depends on.

Tag-2 multi-family registry note
--------------------------------

Sprint-9 Tag-2 promoted the driver to a multi-family registry that
provisions every registered :class:`BucketFamily` per ``org_id``.
The Tag-1 coverage axes below pin ``families=[marker-stack]`` on
every call to assert the historical single-family semantics
byte-precisely. The new Tag-2 coverage axes (T-MULTIFAM-01..NN in
``test_nats_kv_bucket_provision_multi_family.py``) exercise the
multi-family fan-out shape independently.

Coverage axes (8 tests):

1. Empty cluster + two orgs ``acme`` / ``orbit`` → both bucketise
   ``created``; bucket names follow the Wirelang-side
   ``BUCKET_NAME_PREFIX`` invariant; create-call kwargs match
   :data:`wirelang.federation.marker_stack_kv.BUCKET_CONFIG`.
2. Re-run after a successful create is a no-op (``unchanged``);
   ``create_key_value`` is not invoked a second time.
3. ``--dry-run`` against an empty cluster reports ``would_create``
   for each org and does not mutate the mock cluster state.
4. Drift detection: a bucket whose live ``history`` field differs
   from the Wirelang-side ``BUCKET_CONFIG`` is reported as
   ``drift`` with a precise field-level diff payload; no mutation.
5. Malformed ``org_id`` (whitespace, slash, empty) produces an
   ``error`` action without touching the cluster.
6. Duplicate ``org_id`` inputs collapse to a single bucket
   (idempotent input semantics).
7. ``parse_orgs_file`` accepts blank lines, ``#``-comments, and
   trailing whitespace; raises ``FileNotFoundError`` for an absent
   path.
8. Cross-reference invariants: the provisioner imports
   ``BUCKET_CONFIG``, ``BUCKET_NAME_PREFIX``, and
   ``bucket_name_for_org`` from
   :mod:`wirelang.federation.marker_stack_kv`. A consumer rename
   on the Wirelang-side would break this test before it can ship
   a broken driver to ops.

These tests are hermetic: no I/O, no NATS, no filesystem mutation
outside ``tmp_path``.
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
# Module loader: bin/nats_kv_bucket_provision.py is the import target.
# We add the repo root to sys.path so ``from bin import nats_kv_bucket_
# provision`` resolves without an editable install. The CLI shim
# (bin/nats-kv-bucket-provision, no .py) is loaded via importlib in
# the cross-reference invariant test only.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BIN_PY = _REPO_ROOT / "bin" / "nats_kv_bucket_provision.py"
_MODULE_NAME = "nats_kv_bucket_provision"


def _load_module():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, str(_BIN_PY))
    assert spec is not None and spec.loader is not None, "loader unavailable"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture
def marker_stack_family(mod):
    """Pin to the marker-stack family for Tag-1 single-family
    semantics. Sprint-9 Tag-2 promoted the planner to a multi-
    family registry; the Tag-1 axes below pre-date that and assert
    the marker-stack family behaviour in isolation.
    """
    for fam in mod.BUCKET_FAMILIES:
        if fam.family_id == "marker-stack":
            return fam
    raise AssertionError(
        "marker-stack family is not registered; refusing to run Tag-1 "
        "single-family hermetic tests against a multi-family driver"
    )


# ---------------------------------------------------------------------------
# Mock JetStream + KV surface (mirrors test_init_nats_buckets.py shape)
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


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# 1. Empty cluster + two orgs → both bucketise "created"
# ---------------------------------------------------------------------------


def test_empty_cluster_creates_per_org_buckets_with_canonical_config(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=False, families=[marker_stack_family],
        )
    )

    assert [a.status for a in actions] == ["created", "created"], actions
    assert [a.org_id for a in actions] == ["acme", "orbit"]
    # Bucket names follow Wirelang-side prefix invariant.
    assert actions[0].bucket == f"{mod.MARKER_STACK_BUCKET_NAME_PREFIX}acme"
    assert actions[1].bucket == f"{mod.MARKER_STACK_BUCKET_NAME_PREFIX}orbit"

    # Every create call mirrored BUCKET_CONFIG byte-precisely.
    cfg = mod.MARKER_STACK_BUCKET_CONFIG
    for call in js.create_calls:
        assert call["history"] == int(cfg["history"])
        assert call["ttl"] == int(cfg["ttl_seconds"])
        assert call["max_value_size"] == int(cfg["max_value_size"])
        assert call["storage"] == str(cfg["storage"])
        assert call["replicas"] == int(cfg["replicas"])
        assert call["description"] == str(cfg["description"])


# ---------------------------------------------------------------------------
# 2. Idempotent replay
# ---------------------------------------------------------------------------


def test_idempotent_replay_marks_buckets_unchanged(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=False, families=[marker_stack_family],
        )
    )
    js.create_calls.clear()

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=False, families=[marker_stack_family],
        )
    )
    assert all(a.status == "unchanged" for a in actions), [
        (a.org_id, a.status, a.detail, a.drift) for a in actions
    ]
    assert js.create_calls == [], (
        "idempotent replay must not call create_key_value"
    )


# ---------------------------------------------------------------------------
# 3. --dry-run does not mutate
# ---------------------------------------------------------------------------


def test_dry_run_reports_would_create_and_does_not_mutate(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "orbit"],
            dry_run=True, families=[marker_stack_family],
        )
    )

    assert [a.status for a in actions] == ["would_create", "would_create"]
    assert js.buckets == {}, "dry-run must not mutate the cluster"
    assert js.create_calls == [], "dry-run must not call create_key_value"


# ---------------------------------------------------------------------------
# 4. Drift detection
# ---------------------------------------------------------------------------


def test_drift_is_reported_with_precise_diff(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    cfg = mod.MARKER_STACK_BUCKET_CONFIG
    bucket = mod.bucket_name_for_org("acme")
    # Pre-seed with a DRIFTED config: history=99 instead of cfg["history"]=1.
    drifted_history = 99
    assert drifted_history != int(cfg["history"]), (
        "test fixture invariant: drift value must not match canonical config"
    )
    js.buckets[bucket] = _MockKv(
        name=bucket,
        status_payload=_MockKvStatus(
            history=drifted_history,
            ttl=int(cfg["ttl_seconds"]),
            max_value_size=int(cfg["max_value_size"]),
            storage=str(cfg["storage"]),
            replicas=int(cfg["replicas"]),
        ),
    )

    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme"], dry_run=False, families=[marker_stack_family]
        )
    )
    assert len(actions) == 1
    action = actions[0]
    assert action.status == "drift", action
    assert action.drift == {
        "history": {"want": int(cfg["history"]), "got": drifted_history}
    }
    # Drift must never trigger a mutation.
    assert js.create_calls == []


# ---------------------------------------------------------------------------
# 5. Malformed org_id surfaces as error action
# ---------------------------------------------------------------------------


def test_malformed_org_id_surfaces_as_error_action(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    # "" empty, " " whitespace, "with/slash" slash, "with space" space.
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            ["valid-acme", "with/slash", "with space", "valid-orbit"],
            dry_run=False,
            families=[marker_stack_family],
        )
    )
    # Two valid orgs become "created", two malformed orgs become "error".
    by_org = {a.org_id: a for a in actions}
    assert by_org["valid-acme"].status == "created"
    assert by_org["valid-orbit"].status == "created"
    assert by_org["with/slash"].status == "error"
    assert by_org["with space"].status == "error"
    # Errored orgs MUST NOT carry a bucket name (the bucket-name
    # derivation failed before any cluster touch).
    assert by_org["with/slash"].bucket == ""
    assert by_org["with space"].bucket == ""
    # Only the two valid orgs hit create_key_value.
    assert len(js.create_calls) == 2


# ---------------------------------------------------------------------------
# 6. Duplicate org_id input collapses
# ---------------------------------------------------------------------------


def test_duplicate_org_id_input_collapses_to_single_bucket(
    mod, event_loop, marker_stack_family
):
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js, ["acme", "acme", "orbit", "acme"],
            dry_run=False, families=[marker_stack_family],
        )
    )
    # Three distinct planner decisions become two distinct actions.
    assert len(actions) == 2
    assert {a.org_id for a in actions} == {"acme", "orbit"}
    assert [a.status for a in actions] == ["created", "created"]
    assert len(js.create_calls) == 2


# ---------------------------------------------------------------------------
# 7. parse_orgs_file: comments, blanks, missing file
# ---------------------------------------------------------------------------


def test_parse_orgs_file_handles_comments_blanks_and_missing(mod, tmp_path):
    roster = tmp_path / "orgs.txt"
    roster.write_text(
        "\n".join(
            [
                "# Roster of onboarded orgs",
                "",
                "acme",
                "   orbit   ",
                "# trailing comment",
                "acme",  # duplicate
                "tertio  # inline comment",
                "",
            ]
        ),
        encoding="utf-8",
    )
    parsed = mod.parse_orgs_file(roster)
    assert parsed == ["acme", "orbit", "tertio"]

    # Missing file path raises FileNotFoundError, surfaced cleanly.
    with pytest.raises(FileNotFoundError):
        mod.parse_orgs_file(tmp_path / "absent.txt")

    # _collect_org_ids merges file + flags, file first.
    merged = mod._collect_org_ids(["zulu", "acme"], roster)
    assert merged == ["acme", "orbit", "tertio", "zulu"]

    # No orgs at all raises ValueError.
    with pytest.raises(ValueError):
        mod._collect_org_ids(None, None)


# ---------------------------------------------------------------------------
# 8. Cross-reference invariant: re-exported Wirelang-side constants
# ---------------------------------------------------------------------------


def test_module_re_exports_canonical_wirelang_constants(mod):
    # The provisioner MUST single-source the Wirelang-side constants.
    # A consumer rename in marker_stack_kv would break either this
    # import or the spec_for_org bucket name.
    from wirelang.federation.marker_stack_kv import (
        BUCKET_CONFIG,
        BUCKET_NAME_PREFIX,
        bucket_name_for_org,
    )

    assert mod.MARKER_STACK_BUCKET_CONFIG is BUCKET_CONFIG
    assert mod.MARKER_STACK_BUCKET_NAME_PREFIX is BUCKET_NAME_PREFIX
    assert mod.bucket_name_for_org is bucket_name_for_org

    # spec_for_org produces nats-py-shaped kwargs with the correct
    # bucket name derivation; no field re-encoding (the ttl_seconds →
    # ttl rename is the only intentional remapping).
    spec = mod.spec_for_org("acme")
    assert spec["bucket"] == bucket_name_for_org("acme")
    assert spec["history"] == int(BUCKET_CONFIG["history"])
    assert spec["ttl"] == int(BUCKET_CONFIG["ttl_seconds"])
    assert spec["max_value_size"] == int(BUCKET_CONFIG["max_value_size"])
    assert spec["storage"] == str(BUCKET_CONFIG["storage"])
    assert spec["replicas"] == int(BUCKET_CONFIG["replicas"])
    assert spec["description"] == str(BUCKET_CONFIG["description"])

    # bucket_name_for_org REJECTS malformed identifiers — the
    # canonical validation surface lives on the Wirelang side.
    with pytest.raises(ValueError):
        mod.spec_for_org("with/slash")
    with pytest.raises(ValueError):
        mod.spec_for_org("")
