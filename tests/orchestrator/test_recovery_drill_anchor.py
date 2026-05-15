# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``wirelang.persona.recovery_drill_anchor``
(Sprint-Pengine-7 Tag-5 OI-PILOT-4 + Cross-Pair Reza OI-PEF-11).

Coverage axes (T-ANCHOR-01..12):

1. ``envelope_jcs_bytes`` is byte-deterministic on logically equal
   inputs.
2. ``envelope_payload_hash`` returns 64-char hex.
3. ``schema_matches`` returns False for non-matching schema URIs.
4. ``already_anchored`` recognises a populated ``wat_anchored_at``.
5. ``already_anchored`` returns False on missing / empty values.
6. ``anchor_one_envelope`` schema-rejects a non-matching envelope.
7. ``anchor_one_envelope`` skips an already-anchored envelope.
8. ``anchor_one_envelope`` errors on missing persona_id.
9. ``anchor_one_envelope`` anchors a fresh envelope and writes
   ``wat_anchored_at`` back to KV.
10. ``anchor_one_envelope`` errors when the WAT bridge-writer
    returns a non-ok status.
11. ``anchor_pass`` iterates all recovery-audit keys and produces
    one action per envelope; non-recovery-audit keys are skipped
    when ``keys=None`` (driver enumerates the bucket).
12. ``anchor_pass`` is idempotent: a second pass on the same
    bucket marks every envelope ``skipped``.

All tests are hermetic: no NATS, no WAT spool, no filesystem
mutation outside ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from wirelang.persona import recovery_drill_anchor
    return recovery_drill_anchor


# ---------------------------------------------------------------------------
# Mock JetStream-KV
# ---------------------------------------------------------------------------


@dataclass
class _MockKvEntry:
    value: bytes


@dataclass
class _MockKv:
    entries: dict = field(default_factory=dict)
    put_calls: list = field(default_factory=list)

    async def keys(self):
        return list(self.entries.keys())

    async def get(self, key: str):
        if key not in self.entries:
            raise KeyError(key)
        return _MockKvEntry(value=self.entries[key])

    async def put(self, key: str, value: bytes):
        self.put_calls.append((key, value))
        self.entries[key] = value


@dataclass
class _MockWatResult:
    ok: bool
    wat_spool_path: str = ""
    status: str = "ok"
    error: str = ""


def _make_wat_write(ok: bool = True, error: str = "", spool: str = "/var/lib/wakir/spool/tomas/2026-05-15T12.jsonl"):
    def _fn(*, persona_id, action_type, payload_hash, metadata, event_time):
        return _MockWatResult(
            ok=ok,
            wat_spool_path=spool,
            status="ok" if ok else "wat-failed",
            error=error,
        )
    return _fn


def _make_envelope(
    *,
    schema=None,
    drill_run_id="svid-expired-2026-05-15T04-12-00Z",
    persona_id="tomas",
    org_id="acme",
    outcome="pass",
    drill_class="DRILL_SVID_EXPIRED",
    emitted_at="2026-05-15T04:12:00Z",
    wat_anchored_at=None,
):
    env = {
        "schema": schema if schema is not None else "wakir.persona.recovery-drill-outcome/1",
        "drill_run_id": drill_run_id,
        "drill_class": drill_class,
        "persona_id": persona_id,
        "org_id": org_id,
        "outcome": outcome,
        "emitted_at": emitted_at,
    }
    if wat_anchored_at is not None:
        env["wat_anchored_at"] = wat_anchored_at
    return env


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# T-ANCHOR-01..02 — JCS + payload hash primitives
# ---------------------------------------------------------------------------


def test_envelope_jcs_bytes_is_byte_deterministic_on_logically_equal_inputs(mod):
    a = _make_envelope()
    b = dict(reversed(list(_make_envelope().items())))
    assert mod.envelope_jcs_bytes(a) == mod.envelope_jcs_bytes(b)


def test_envelope_payload_hash_returns_64_char_hex(mod):
    env = _make_envelope()
    h = mod.envelope_payload_hash(env)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# T-ANCHOR-03..05 — schema_matches + already_anchored predicates
# ---------------------------------------------------------------------------


def test_schema_matches_returns_false_for_non_matching_schema(mod):
    env = _make_envelope(schema="wakir.unknown/1")
    assert mod.schema_matches(env) is False


def test_already_anchored_recognises_populated_field(mod):
    env = _make_envelope(wat_anchored_at="2026-05-15T12:00:00Z")
    assert mod.already_anchored(env) is True


def test_already_anchored_returns_false_on_missing_or_empty(mod):
    assert mod.already_anchored(_make_envelope()) is False
    assert mod.already_anchored(_make_envelope(wat_anchored_at="")) is False
    assert mod.already_anchored(_make_envelope(wat_anchored_at="   ")) is False


# ---------------------------------------------------------------------------
# T-ANCHOR-06..10 — anchor_one_envelope state machine
# ---------------------------------------------------------------------------


def test_anchor_one_envelope_schema_rejects_non_matching_envelope(
    mod, event_loop
):
    kv = _MockKv()
    env = _make_envelope(schema="wakir.wrong/1")
    action = event_loop.run_until_complete(
        mod.anchor_one_envelope(
            kv=kv,
            key="recovery-audit/abc",
            envelope=env,
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert action.status == "schema-rejected"
    assert kv.put_calls == []


def test_anchor_one_envelope_skips_already_anchored(mod, event_loop):
    kv = _MockKv()
    env = _make_envelope(wat_anchored_at="2026-05-15T11:45:00Z")
    action = event_loop.run_until_complete(
        mod.anchor_one_envelope(
            kv=kv,
            key="recovery-audit/abc",
            envelope=env,
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert action.status == "skipped"
    assert kv.put_calls == []


def test_anchor_one_envelope_errors_on_missing_persona_id(mod, event_loop):
    kv = _MockKv()
    env = _make_envelope(persona_id="")
    action = event_loop.run_until_complete(
        mod.anchor_one_envelope(
            kv=kv,
            key="recovery-audit/abc",
            envelope=env,
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert action.status == "error"
    assert "persona_id" in action.detail
    assert kv.put_calls == []


def test_anchor_one_envelope_anchors_fresh_envelope_and_writes_back(
    mod, event_loop
):
    kv = _MockKv()
    env = _make_envelope()
    action = event_loop.run_until_complete(
        mod.anchor_one_envelope(
            kv=kv,
            key="recovery-audit/svid-expired-2026-05-15T04-12-00Z",
            envelope=env,
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert action.status == "anchored"
    assert len(kv.put_calls) == 1
    key, value = kv.put_calls[0]
    assert key == "recovery-audit/svid-expired-2026-05-15T04-12-00Z"
    written = json.loads(value.decode("utf-8"))
    assert written["wat_anchored_at"] == "2026-05-15T12:00:00Z"
    assert written["wat_spool_path"] == (
        "/var/lib/wakir/spool/tomas/2026-05-15T12.jsonl"
    )
    # Original fields preserved.
    assert written["drill_run_id"] == env["drill_run_id"]
    assert written["persona_id"] == env["persona_id"]


def test_anchor_one_envelope_errors_when_wat_returns_non_ok(mod, event_loop):
    kv = _MockKv()
    env = _make_envelope()
    action = event_loop.run_until_complete(
        mod.anchor_one_envelope(
            kv=kv,
            key="recovery-audit/abc",
            envelope=env,
            wat_write_fn=_make_wat_write(
                ok=False, error="spool unreachable"
            ),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert action.status == "error"
    assert "non-ok" in action.detail or "wat-failed" in action.detail
    # No KV write-back on WAT failure.
    assert kv.put_calls == []


# ---------------------------------------------------------------------------
# T-ANCHOR-11..12 — anchor_pass iteration + idempotency
# ---------------------------------------------------------------------------


def test_anchor_pass_iterates_recovery_audit_keys_only(mod, event_loop):
    kv = _MockKv()
    env_a = _make_envelope(drill_run_id="run-a")
    env_b = _make_envelope(
        drill_run_id="run-b",
        persona_id="tomas",
    )
    # Seed two recovery-audit envelopes + one unrelated key.
    kv.entries["recovery-audit/run-a"] = json.dumps(env_a).encode("utf-8")
    kv.entries["recovery-audit/run-b"] = json.dumps(env_b).encode("utf-8")
    kv.entries["state-pack/current"] = b'{"unrelated":true}'

    report = event_loop.run_until_complete(
        mod.anchor_pass(
            kv=kv,
            bucket="wakir-persona-state-acme-tomas",
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert report.anchored == 2, [
        (a.key, a.status, a.detail) for a in report.actions
    ]
    assert report.skipped == 0
    assert report.errors == 0
    # Non-recovery-audit keys are NOT in the report.
    assert all(
        a.key.startswith("recovery-audit/") for a in report.actions
    )


def test_anchor_pass_is_idempotent_on_replay(mod, event_loop):
    kv = _MockKv()
    env = _make_envelope()
    kv.entries["recovery-audit/run-x"] = json.dumps(env).encode("utf-8")

    # First pass anchors.
    first = event_loop.run_until_complete(
        mod.anchor_pass(
            kv=kv,
            bucket="wakir-persona-state-acme-tomas",
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    assert first.anchored == 1
    assert first.skipped == 0

    # Second pass: envelope now carries wat_anchored_at →
    # skipped.
    second = event_loop.run_until_complete(
        mod.anchor_pass(
            kv=kv,
            bucket="wakir-persona-state-acme-tomas",
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:15:00Z",
        )
    )
    assert second.anchored == 0
    assert second.skipped == 1
    assert second.errors == 0


# ---------------------------------------------------------------------------
# T-ANCHOR-13 — report.to_json shape
# ---------------------------------------------------------------------------


def test_anchor_report_to_json_carries_summary_block(mod, event_loop):
    kv = _MockKv()
    env = _make_envelope()
    kv.entries["recovery-audit/run-y"] = json.dumps(env).encode("utf-8")

    report = event_loop.run_until_complete(
        mod.anchor_pass(
            kv=kv,
            bucket="wakir-persona-state-acme-tomas",
            wat_write_fn=_make_wat_write(),
            now_rfc3339="2026-05-15T12:00:00Z",
        )
    )
    decoded = json.loads(report.to_json())
    assert decoded["bucket"] == "wakir-persona-state-acme-tomas"
    assert decoded["summary"]["anchored"] == 1
    assert decoded["summary"]["total"] == 1
    assert len(decoded["actions"]) == 1
