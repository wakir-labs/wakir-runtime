# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the persona-state family of
``bin/nats-kv-bucket-provision`` (Sprint-Pengine-7 Tag-5 OI-PILOT-2).

The persona-state family is a Selin-owned-domain per-persona-per-org
bucket family added in Sprint-Pengine-7 Tag-5. Unlike the marker-stack
and sequence-ledger families (one bucket per ``org_id``), the
persona-state family carries one bucket per ``(org_id, persona_id)``
pair. The driver consumes the combined ``"<org_id>-<persona_id>"``
token via a separate ``persona_state_pairs`` iteration that does NOT
participate in the per-org fan-out shape.

Coverage axes (T-PERSONA-STATE-01..09):

1. Persona-state family is registered in :data:`BUCKET_FAMILIES`
   when the Selin-side module is importable.
2. Family cross-reference invariant: the registered family's
   ``bucket_config`` is the Selin-side ``BUCKET_CONFIG`` constant
   (single source of truth, no re-encoding).
3. ``plan_and_apply`` with ``persona_state_pairs`` only (empty
   ``org_ids``) emits one ``created`` action per pair.
4. Combined org-iteration + persona-state-pair iteration: actions
   from both streams accumulate in the same report, in the
   documented order (org-iteration first, persona-state-pair
   iteration second).
5. Idempotent replay of persona-state pairs marks every bucket
   ``unchanged``; ``create_key_value`` is not invoked.
6. Dry-run of persona-state pairs emits ``would_create`` actions
   with no cluster mutation.
7. Malformed persona-state-pair token (e.g. missing ``-`` separator)
   yields ONE error action under the persona-state family.
8. The 64 KiB ``max_value_size`` ceiling is honoured (proves the
   per-family config is propagated correctly; persona-state is
   bigger than marker-stack and sequence-ledger).
9. The CLI ``--persona-state-pair`` flag collects via the same
   roster-file shape as ``--orgs-file``; the ``_collect_persona_state_pairs``
   helper de-duplicates first-occurrence-wins.

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
from typing import Any, Mapping

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
# Mock JetStream (shared shape with Tag-1 / Multi-Family tests)
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
# T-PERSONA-STATE-01 — family registered when module present
# ---------------------------------------------------------------------------


def test_persona_state_family_is_registered_when_module_present(mod):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip(
            "wirelang.persona.persona_state_kv not present on this tip"
        )
    family_ids = [f.family_id for f in mod.BUCKET_FAMILIES]
    assert "persona-state" in family_ids
    # Registry order: persona-state comes after marker-stack and
    # sequence-ledger; the family is the LAST registered entry by
    # the Tag-5 contract.
    assert family_ids[-1] == "persona-state"


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-02 — cross-reference invariant
# ---------------------------------------------------------------------------


def test_persona_state_family_re_exports_canonical_constants(mod):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip(
            "wirelang.persona.persona_state_kv* not present on this tip"
        )
    # Post-Sprint-Pengine-7-Tag-5 B-5 disentanglement: the provisioner
    # driver imports the constants-only shim
    # ``wirelang.persona.persona_state_kv_constants`` FIRST and
    # falls back to the full ``wirelang.persona.persona_state_kv``
    # only when the shim is absent. The identity-comparison axis
    # therefore checks the shim names on the happy path, with a
    # full-module fallback when the shim is intentionally absent on
    # a non-bundle deployment. Byte-equality between shim and full
    # module is enforced by
    # ``wirelang/tests/test_persona_state_kv_constants_parity.py``.
    try:
        from wirelang.persona.persona_state_kv_constants import (
            BUCKET_CONFIG as _SHIM_BUCKET_CONFIG,
            BUCKET_NAME_PREFIX as _SHIM_BUCKET_NAME_PREFIX,
            bucket_name_for_org as _shim_bucket_name_for_org,
        )
        canonical_config = _SHIM_BUCKET_CONFIG
        canonical_prefix = _SHIM_BUCKET_NAME_PREFIX
        canonical_fn = _shim_bucket_name_for_org
    except ImportError:
        from wirelang.persona.persona_state_kv import (
            BUCKET_CONFIG as canonical_config,
            BUCKET_NAME_PREFIX as canonical_prefix,
            bucket_name_for_org as canonical_fn,
        )

    assert mod.PERSONA_STATE_BUCKET_CONFIG is canonical_config
    assert mod.PERSONA_STATE_BUCKET_NAME_PREFIX is canonical_prefix

    ps_fam = next(
        f for f in mod.BUCKET_FAMILIES if f.family_id == "persona-state"
    )
    assert ps_fam.bucket_config is canonical_config
    assert ps_fam.bucket_name_for_org is canonical_fn
    # spec_for_org for a combined token carries the Selin-side
    # BUCKET_CONFIG byte-precisely.
    spec = mod.spec_for_org("acme-tomas", family=ps_fam)
    assert spec["bucket"] == "wakir-persona-state-acme-tomas"
    assert spec["history"] == int(canonical_config["history"])
    assert spec["max_value_size"] == int(canonical_config["max_value_size"])
    assert spec["description"] == str(canonical_config["description"])


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-03 — pairs-only iteration (empty org_ids)
# ---------------------------------------------------------------------------


def test_persona_state_pairs_only_iteration_creates_one_bucket_per_pair(
    mod, event_loop
):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            [],  # no per-org input
            dry_run=False,
            persona_state_pairs=["acme-tomas", "orbit-aisha"],
        )
    )
    assert len(actions) == 2
    assert all(a.family == "persona-state" for a in actions)
    assert all(a.status == "created" for a in actions)
    by_token = {a.org_id: a for a in actions}
    assert by_token["acme-tomas"].bucket == "wakir-persona-state-acme-tomas"
    assert by_token["orbit-aisha"].bucket == "wakir-persona-state-orbit-aisha"
    # Confirm the per-family max_value_size is the persona-state
    # 64 KiB ceiling (proves config plumbing).
    for call in js.create_calls:
        assert call["max_value_size"] == 65_536


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-04 — combined org-iteration + pair-iteration order
# ---------------------------------------------------------------------------


def test_combined_org_and_pair_iteration_preserves_documented_order(
    mod, event_loop
):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            ["acme"],
            dry_run=False,
            persona_state_pairs=["acme-tomas"],
        )
    )
    # 1 org × N per-org families + 1 pair = at least 2 actions.
    # Per-org families come first (registry order), persona-state-
    # pair actions appended at the end.
    persona_state_actions = [a for a in actions if a.family == "persona-state"]
    non_persona_actions = [a for a in actions if a.family != "persona-state"]
    # All non-persona actions come BEFORE all persona-state actions
    # (documented stable order).
    last_non_persona_idx = max(
        (i for i, a in enumerate(actions) if a.family != "persona-state"),
        default=-1,
    )
    first_persona_idx = min(
        (i for i, a in enumerate(actions) if a.family == "persona-state"),
        default=len(actions),
    )
    assert last_non_persona_idx < first_persona_idx
    # The persona-state action under "acme-tomas" is exactly one entry.
    assert len(persona_state_actions) == 1
    assert persona_state_actions[0].bucket == (
        "wakir-persona-state-acme-tomas"
    )


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-05 — idempotent pair-iteration replay
# ---------------------------------------------------------------------------


def test_idempotent_persona_state_pair_replay_marks_buckets_unchanged(
    mod, event_loop
):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    js = _MockJetStream()
    event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            [],
            dry_run=False,
            persona_state_pairs=["acme-tomas"],
        )
    )
    js.create_calls.clear()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            [],
            dry_run=False,
            persona_state_pairs=["acme-tomas"],
        )
    )
    assert len(actions) == 1
    assert actions[0].status == "unchanged"
    assert actions[0].family == "persona-state"
    assert js.create_calls == [], (
        "idempotent replay of persona-state pair must not call "
        "create_key_value"
    )


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-06 — dry-run yields would_create + no mutation
# ---------------------------------------------------------------------------


def test_dry_run_persona_state_pair_emits_would_create_no_mutation(
    mod, event_loop
):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            [],
            dry_run=True,
            persona_state_pairs=["acme-tomas", "orbit-aisha"],
        )
    )
    assert len(actions) == 2
    assert all(a.status == "would_create" for a in actions)
    assert all(a.family == "persona-state" for a in actions)
    assert js.buckets == {}
    assert js.create_calls == []


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-07 — malformed pair token yields one error action
# ---------------------------------------------------------------------------


def test_malformed_persona_state_pair_token_yields_one_error_action(
    mod, event_loop
):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    js = _MockJetStream()
    actions = event_loop.run_until_complete(
        mod.plan_and_apply(
            js,
            [],
            dry_run=False,
            # Missing '-' separator → bucket_name_for_org rejects.
            persona_state_pairs=["nopair"],
        )
    )
    assert len(actions) == 1
    assert actions[0].status == "error"
    assert actions[0].family == "persona-state"
    assert actions[0].bucket == ""
    assert "must contain" in actions[0].detail or "invalid" in actions[0].detail


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-08 — max_value_size ceiling propagation
# ---------------------------------------------------------------------------


def test_persona_state_bucket_config_carries_64kib_max_value_size(mod):
    if not mod._HAS_PERSONA_STATE_FAMILY:
        pytest.skip("persona-state family absent")
    # The 64 KiB ceiling is documented as the per-bucket envelope
    # ceiling for the spawn-session state-pack envelope. The
    # marker-stack family carries 32 KiB; the sequence-ledger
    # family carries 4 KiB; the persona-state family carries 64
    # KiB. The three families MUST remain distinct on this axis.
    assert mod.PERSONA_STATE_BUCKET_CONFIG["max_value_size"] == 65_536
    if mod._HAS_SEQUENCE_LEDGER_FAMILY:
        assert (
            mod.PERSONA_STATE_BUCKET_CONFIG["max_value_size"]
            > mod.SEQUENCE_LEDGER_BUCKET_CONFIG["max_value_size"]
        )
    assert (
        mod.PERSONA_STATE_BUCKET_CONFIG["max_value_size"]
        > mod.MARKER_STACK_BUCKET_CONFIG["max_value_size"]
    )


# ---------------------------------------------------------------------------
# T-PERSONA-STATE-09 — collector helper + roster-file dedupe
# ---------------------------------------------------------------------------


def test_collect_persona_state_pairs_de_duplicates_first_occurrence_wins(
    mod, tmp_path
):
    roster = tmp_path / "personas.roster"
    roster.write_text(
        "# leading comment\n"
        "acme-tomas\n"
        "orbit-aisha\n"
        "acme-tomas  # duplicate ignored\n"
        "\n",
        encoding="utf-8",
    )
    flag_pairs = ["orbit-aisha", "acme-fred"]
    out = mod._collect_persona_state_pairs(flag_pairs, roster)
    # File entries first, in order; flag entries appended; duplicates
    # dropped (first occurrence wins).
    assert out == ["acme-tomas", "orbit-aisha", "acme-fred"]


def test_collect_persona_state_pairs_returns_empty_list_when_nothing_provided(
    mod,
):
    assert mod._collect_persona_state_pairs(None, None) == []
    assert mod._collect_persona_state_pairs([], None) == []
