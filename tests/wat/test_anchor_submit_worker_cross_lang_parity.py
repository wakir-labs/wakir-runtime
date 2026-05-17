# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine anchor-submit-worker.

The Python module under test
(:mod:`wirelang.persona_engine.anchor_submit_worker`) is BUSL-1.1; the
tests themselves are Apache-2.0 so downstream re-implementers can
re-use the same vectors.

Test taxonomy
-------------

- T01 — Constants pin: rate / retry defaults + env-var names + decision
  schema constant match the Rust crate's ``pub const`` items.
- T02 — Spec invariants hold (mirror of Rust ``assert_spec_invariants``).
- T03 — Happy-path single-tick success: decision record carries
  ``kind="success"``, the writeback fires, the queue empties, the
  transport is called exactly once.
- T04 — Throttle-no-side-effects: only one transport outcome scripted;
  the second tick must be throttled WITHOUT calling the transport
  (the scripted-transport raises on extra calls — silent invariant).
- T05 — Idle-on-empty-queue: an empty worker returns
  ``SubmitResultKind.IDLE`` with empty event_id and zero numeric fields.
- T06 — Permanent-error dead-letters immediately and does not consume
  retry budget (``retry_count == 0``).
- T07 — Full-jitter backoff is upper-bound-bounded and the bound
  doubles per attempt; the 1s-cap variant pins to ``[1,2,4,8,8,8]``.
- T08 — Decision record JCS wire-shape: top-level keys are lex-ordered;
  unused fields default to ``0`` / ``""``.
- T09 — Decision record hash is stable across two builds of the same
  fixture replay (determinism sentinel).
- T10 — Cross-lang fixture structure: schema_version, fixture count,
  per-fixture key set match the documented file shape.
- T11 — Cross-lang fixture per-vector pin (parametrised over the five
  fixtures): byte-for-byte parity with the JSON fixture file's pinned
  ledger entries (this is the core decision-record byte-parity test).
- T12 — Cross-lang fixture sweep: each fixture's transport_calls,
  writeback_calls, dead_letter_snapshot, queue_len_final match the
  replay output exactly.
- T13 — Coverage completeness: every ``SubmitResultKind`` appears as
  at least one ledger entry across the five fixtures.
- T14 — RFC-3339 formatter pins known epochs (cross-lang with the
  Rust crate's ``format_rfc3339_secs``).
- T15 — Config from-env happy path, falls back on garbage,
  uses defaults when unset (matches Rust ``from_env_with``).
- T16 — Token-bucket refill semantics: refills only after a full
  window has elapsed; clock-going-backwards is a no-op.
- T17 — Throttle re-queues at the FRONT (the throttled envelope must
  be served first on the next eligible tick).
- T18 — DeterministicRng clamping: values exceeding upper_inclusive
  clamp to upper_inclusive; upper_inclusive==0 always returns 0;
  empty sequence raises.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``persona-engine-anchor-submit-worker`` and
   Python ``anchor_submit_worker.py``).
2. Re-derive the fixture vectors by running
   ``scripts/derive-anchor-submit-worker-fixtures.py`` from the
   repo root.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, T11 + T12 fire on both sides
which is the intended boundary detector.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.anchor_submit_worker import (
    AnchorSubmitWorker,
    DEFAULT_MAX_RETRY,
    DEFAULT_RATE_REQUESTS,
    DEFAULT_RATE_WINDOW_SECS,
    DEFAULT_RETRY_BASE_DELAY_SECS,
    DEFAULT_RETRY_MAX_DELAY_SECS,
    DECISION_RECORD_SCHEMA,
    DeadLetterRecord,
    DeterministicRng,
    ENV_MAX_RETRY,
    ENV_SUBMIT_RATE,
    InMemoryDeadLetterStore,
    KIND_DEAD,
    KIND_IDLE,
    KIND_RETRYING,
    KIND_SUCCESS,
    KIND_THROTTLED,
    ManualClock,
    NoopWriteBackSink,
    RecordingWriteBackSink,
    ScriptedTransport,
    SubmitResult,
    SubmitResultKind,
    SubmitWorkerConfig,
    SubmitWorkerError,
    TransportOutcome,
    TransportOutcomeKind,
    _TokenBucket,
    assert_spec_invariants,
    decision_record_hash,
    format_rfc3339_secs,
    serialize_decision_record,
    sha256_hex,
)


# ---------------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------------


def _fixture_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    # here = <repo>/tests/wat/test_anchor_submit_worker_cross_lang_parity.py
    # repo_root = parents[2]
    repo_root = here.parents[2]
    return (
        repo_root
        / "tests"
        / "fixtures"
        / "anchor-submit-worker-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    with _fixture_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Helpers — replay a fixture deterministically.
# ---------------------------------------------------------------------------


def _outcome_from_dict(d: Dict[str, Any]) -> TransportOutcome:
    kind = d["kind"]
    err = d.get("error", "")
    if kind == "accepted":
        return TransportOutcome.accepted()
    if kind == "retriable":
        return TransportOutcome.retriable(err)
    if kind == "permanent":
        return TransportOutcome.permanent(err)
    raise AssertionError(f"unknown transport outcome kind: {kind!r}")


def _replay_fixture(fx: Dict[str, Any]) -> Dict[str, Any]:
    inp = fx["input"]
    cfg_in = inp["config"]
    cfg = SubmitWorkerConfig(
        rate_requests=int(cfg_in["rate_requests"]),
        rate_window_secs=int(cfg_in["rate_window_secs"]),
        max_retry=int(cfg_in["max_retry"]),
        retry_base_delay_secs=int(cfg_in["retry_base_delay_secs"]),
        retry_max_delay_secs=int(cfg_in["retry_max_delay_secs"]),
    )
    transport = ScriptedTransport([_outcome_from_dict(d) for d in inp["transport_script"]])
    clock = ManualClock(int(inp["clock_start_secs"]))
    rng = DeterministicRng(list(inp["rng_sequence"]))
    dl = InMemoryDeadLetterStore()
    wb = RecordingWriteBackSink()
    worker = AnchorSubmitWorker(
        config=cfg,
        transport=transport,
        dead_letter=dl,
        writeback=wb,
        clock=clock,
        rng=rng,
    )
    for env in inp["enqueues"]:
        worker.enqueue(env)
    ledger: List[Dict[str, Any]] = []
    for step in inp["tick_program"]:
        op = step["op"]
        if op == "tick":
            r = worker.tick()
            canonical = serialize_decision_record(r)
            ledger.append(
                {
                    "decision_record": r.to_decision_record(),
                    "decision_jcs_b64": base64.b64encode(canonical).decode("ascii"),
                    "decision_jcs_len": len(canonical),
                    "decision_hash_prefixed": decision_record_hash(r),
                }
            )
        elif op == "advance_clock":
            clock.advance(int(step["by_secs"]))
        elif op == "enqueue":
            worker.enqueue(step["envelope"])
        else:
            raise AssertionError(f"unknown op: {op!r}")
    return {
        "ledger": ledger,
        "transport_calls": transport.calls,
        "transport_seen": transport.seen,
        "writeback_calls": wb.calls,
        "dead_letter_snapshot": [r.to_wire_dict() for r in dl.snapshot()],
        "queue_len_final": worker.queue_len(),
    }


# ---------------------------------------------------------------------------
# T01 — Constants pin
# ---------------------------------------------------------------------------


def test_t01_constants_match_rust_sibling_pin() -> None:
    assert DEFAULT_RATE_REQUESTS == 1
    assert DEFAULT_RATE_WINDOW_SECS == 30
    assert DEFAULT_MAX_RETRY == 5
    assert DEFAULT_RETRY_BASE_DELAY_SECS == 1
    assert DEFAULT_RETRY_MAX_DELAY_SECS == 300
    assert ENV_SUBMIT_RATE == "WAKIR_ANCHOR_SUBMIT_RATE"
    assert ENV_MAX_RETRY == "WAKIR_ANCHOR_MAX_RETRY"
    assert DECISION_RECORD_SCHEMA == "wakir.wat.anchor-submit-decision/1"
    assert KIND_SUCCESS == "success"
    assert KIND_THROTTLED == "throttled"
    assert KIND_RETRYING == "retrying"
    assert KIND_DEAD == "dead"
    assert KIND_IDLE == "idle"


# ---------------------------------------------------------------------------
# T02 — Spec invariants
# ---------------------------------------------------------------------------


def test_t02_spec_invariants_hold() -> None:
    # Must not raise.
    assert_spec_invariants()


# ---------------------------------------------------------------------------
# T03 — Happy-path single-tick success
# ---------------------------------------------------------------------------


def test_t03_success_fast_path_single_tick() -> None:
    cfg = SubmitWorkerConfig()
    transport = ScriptedTransport([TransportOutcome.accepted()])
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    dl = InMemoryDeadLetterStore()
    wb = RecordingWriteBackSink()
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, dead_letter=dl, writeback=wb, clock=clock, rng=rng
    )
    w.enqueue({"event_id": "happy", "persona_id": "reza"})

    r = w.tick()
    assert r.kind == SubmitResultKind.SUCCESS
    assert r.event_id == "happy"
    assert transport.calls == 1
    assert wb.calls == ["happy"]
    assert dl.snapshot() == []
    assert w.queue_len() == 0


# ---------------------------------------------------------------------------
# T04 — Throttle-no-side-effects (transport script-exhausted guard)
# ---------------------------------------------------------------------------


def test_t04_throttle_does_not_call_transport() -> None:
    cfg = SubmitWorkerConfig(
        rate_requests=1,
        rate_window_secs=60,
        max_retry=5,
        retry_base_delay_secs=1,
        retry_max_delay_secs=300,
    )
    # Only ONE outcome scripted. If throttle accidentally calls
    # the transport, ScriptedTransport raises (loud failure).
    transport = ScriptedTransport([TransportOutcome.accepted()])
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, clock=clock, rng=rng,
    )
    w.enqueue({"event_id": "a", "persona_id": "reza"})
    w.enqueue({"event_id": "b", "persona_id": "reza"})

    r1 = w.tick()
    assert r1.kind == SubmitResultKind.SUCCESS
    r2 = w.tick()
    assert r2.kind == SubmitResultKind.THROTTLED
    assert r2.event_id == "b"
    assert transport.calls == 1
    # Throttled envelope stays queued.
    assert w.queue_len() == 1


# ---------------------------------------------------------------------------
# T05 — Idle when queue empty
# ---------------------------------------------------------------------------


def test_t05_idle_when_queue_empty() -> None:
    cfg = SubmitWorkerConfig()
    transport = ScriptedTransport([])
    clock = ManualClock(42)
    rng = DeterministicRng([0])
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, clock=clock, rng=rng,
    )
    r = w.tick()
    assert r.kind == SubmitResultKind.IDLE
    assert r.event_id == ""
    assert r.attempt == 0
    assert r.next_delay_secs == 0
    assert r.terminal_error == ""
    assert transport.calls == 0


# ---------------------------------------------------------------------------
# T06 — Permanent error dead-letters immediately, retry budget untouched
# ---------------------------------------------------------------------------


def test_t06_permanent_error_dead_letters_immediately() -> None:
    cfg = SubmitWorkerConfig(rate_requests=100, rate_window_secs=1)
    transport = ScriptedTransport([TransportOutcome.permanent("malformed")])
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    dl = InMemoryDeadLetterStore()
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, dead_letter=dl, clock=clock, rng=rng,
    )
    w.enqueue({"event_id": "perm", "persona_id": "selin"})
    r = w.tick()
    assert r.kind == SubmitResultKind.DEAD
    assert r.terminal_error == "malformed"
    snap = dl.snapshot()
    assert len(snap) == 1
    # Permanent path -> retry_count never incremented.
    assert snap[0].retry_count == 0
    assert snap[0].persona_id == "selin"


# ---------------------------------------------------------------------------
# T07 — Full-jitter backoff upper-bound doubles per attempt (capped)
# ---------------------------------------------------------------------------


def test_t07_backoff_upper_bound_doubles_per_attempt_with_cap() -> None:
    cfg = SubmitWorkerConfig(
        rate_requests=100,
        rate_window_secs=1,
        max_retry=6,
        retry_base_delay_secs=1,
        retry_max_delay_secs=8,
    )
    transport = ScriptedTransport(
        [TransportOutcome.retriable("e") for _ in range(6)]
    )
    clock = ManualClock(0)
    rng = DeterministicRng([999_999])  # always returns upper bound
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, clock=clock, rng=rng,
    )
    w.enqueue({"event_id": "bo", "persona_id": "reza"})

    delays: List[int] = []
    for _ in range(6):
        r = w.tick()
        assert r.kind == SubmitResultKind.RETRYING
        delays.append(r.next_delay_secs)
        clock.advance(r.next_delay_secs + 1)

    assert delays == [1, 2, 4, 8, 8, 8]


# ---------------------------------------------------------------------------
# T08 — Decision record wire-shape (lex-ordered, complete key set)
# ---------------------------------------------------------------------------


def test_t08_decision_record_wire_shape_is_lex_ordered_with_complete_keys() -> None:
    expected_keys = ["attempt", "event_id", "kind", "next_delay_secs", "terminal_error"]
    for r in (
        SubmitResult.success("x"),
        SubmitResult.throttled("x"),
        SubmitResult.retrying("x", attempt=2, next_delay_secs=4),
        SubmitResult.dead("x", terminal_error="oops", attempt=5),
        SubmitResult.idle(),
    ):
        d = r.to_decision_record()
        assert list(d.keys()) == expected_keys
        canonical = serialize_decision_record(r)
        reparsed = json.loads(canonical.decode("utf-8"))
        assert list(reparsed.keys()) == expected_keys


# ---------------------------------------------------------------------------
# T09 — Decision record hash is stable across two builds
# ---------------------------------------------------------------------------


def test_t09_decision_record_hash_is_stable() -> None:
    a = SubmitResult.retrying("eid", attempt=3, next_delay_secs=4)
    b = SubmitResult.retrying("eid", attempt=3, next_delay_secs=4)
    assert decision_record_hash(a) == decision_record_hash(b)
    assert serialize_decision_record(a) == serialize_decision_record(b)


# ---------------------------------------------------------------------------
# T10 — Cross-lang fixture file structure
# ---------------------------------------------------------------------------


def test_t10_cross_lang_fixture_file_structure() -> None:
    fx = _load_fixtures()
    assert fx["schema_version"] == DECISION_RECORD_SCHEMA
    fixtures = fx["fixtures"]
    assert len(fixtures) == 5
    names = [f["name"] for f in fixtures]
    assert names == [
        "f01-success-fast-path",
        "f02-throttled-rate-limit",
        "f03-retry-backoff-success",
        "f04-retry-exhausted-dead-letter",
        "f05-idle-empty-queue",
    ]
    for f in fixtures:
        assert set(f.keys()) >= {"name", "doc", "input", "expected"}
        inp = f["input"]
        assert set(inp.keys()) >= {
            "config",
            "rng_sequence",
            "clock_start_secs",
            "enqueues",
            "transport_script",
            "tick_program",
        }
        exp = f["expected"]
        assert set(exp.keys()) >= {
            "ledger",
            "transport_calls",
            "transport_seen",
            "writeback_calls",
            "dead_letter_snapshot",
            "queue_len_final",
        }


# ---------------------------------------------------------------------------
# T11 — Per-vector cross-lang pin (the core byte-parity test)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "f01-success-fast-path",
        "f02-throttled-rate-limit",
        "f03-retry-backoff-success",
        "f04-retry-exhausted-dead-letter",
        "f05-idle-empty-queue",
    ],
)
def test_t11_per_vector_ledger_byte_parity(fixture_name: str) -> None:
    fx = _load_fixtures()
    by_name = {f["name"]: f for f in fx["fixtures"]}
    target = by_name[fixture_name]
    derived = _replay_fixture(target)
    expected_ledger = target["expected"]["ledger"]
    assert len(derived["ledger"]) == len(expected_ledger), (
        f"ledger length mismatch for {fixture_name}: "
        f"derived={len(derived['ledger'])} expected={len(expected_ledger)}"
    )
    for i, (got, want) in enumerate(zip(derived["ledger"], expected_ledger)):
        assert got["decision_record"] == want["decision_record"], (
            f"{fixture_name} entry #{i} decision_record mismatch:\n"
            f"  got={got['decision_record']}\n"
            f"  want={want['decision_record']}"
        )
        assert got["decision_jcs_b64"] == want["decision_jcs_b64"], (
            f"{fixture_name} entry #{i} JCS bytes mismatch (b64)"
        )
        assert got["decision_jcs_len"] == want["decision_jcs_len"]
        assert got["decision_hash_prefixed"] == want["decision_hash_prefixed"], (
            f"{fixture_name} entry #{i} hash mismatch"
        )


# ---------------------------------------------------------------------------
# T12 — Cross-lang sweep of side-effect counters
# ---------------------------------------------------------------------------


def test_t12_cross_lang_sweep_of_side_effect_counters() -> None:
    fx = _load_fixtures()
    for f in fx["fixtures"]:
        derived = _replay_fixture(f)
        exp = f["expected"]
        assert derived["transport_calls"] == exp["transport_calls"], (
            f"{f['name']} transport_calls drift"
        )
        assert derived["transport_seen"] == exp["transport_seen"], (
            f"{f['name']} transport_seen drift"
        )
        assert derived["writeback_calls"] == exp["writeback_calls"], (
            f"{f['name']} writeback_calls drift"
        )
        assert derived["dead_letter_snapshot"] == exp["dead_letter_snapshot"], (
            f"{f['name']} dead_letter_snapshot drift"
        )
        assert derived["queue_len_final"] == exp["queue_len_final"], (
            f"{f['name']} queue_len_final drift"
        )


# ---------------------------------------------------------------------------
# T13 — Coverage completeness: all five kinds appear across the fixtures
# ---------------------------------------------------------------------------


def test_t13_fixture_coverage_spans_all_five_kinds() -> None:
    fx = _load_fixtures()
    kinds_seen = set()
    for f in fx["fixtures"]:
        for entry in f["expected"]["ledger"]:
            kinds_seen.add(entry["decision_record"]["kind"])
    assert kinds_seen == {
        KIND_SUCCESS,
        KIND_THROTTLED,
        KIND_RETRYING,
        KIND_DEAD,
        KIND_IDLE,
    }


# ---------------------------------------------------------------------------
# T14 — RFC-3339 formatter pins
# ---------------------------------------------------------------------------


def test_t14_format_rfc3339_pins_known_epochs() -> None:
    assert format_rfc3339_secs(0) == "1970-01-01T00:00:00Z"
    assert format_rfc3339_secs(1_700_000_000) == "2023-11-14T22:13:20Z"
    # Pinned date for f04 (dead-letter occurs at clock_start+0,
    # because RNG=0 keeps backoff zero throughout).
    assert format_rfc3339_secs(1_700_000_500) == "2023-11-14T22:21:40Z"


# ---------------------------------------------------------------------------
# T15 — Config from-env semantics
# ---------------------------------------------------------------------------


def test_t15_config_from_env_uses_defaults_when_unset() -> None:
    cfg = SubmitWorkerConfig.from_env_with(lambda k: None)
    assert cfg == SubmitWorkerConfig()


def test_t15_config_from_env_picks_up_known_keys() -> None:
    def getenv(k: str):
        return {ENV_SUBMIT_RATE: "3/15", ENV_MAX_RETRY: "7"}.get(k)
    cfg = SubmitWorkerConfig.from_env_with(getenv)
    assert cfg.rate_requests == 3
    assert cfg.rate_window_secs == 15
    assert cfg.max_retry == 7


def test_t15_config_from_env_falls_back_on_malformed() -> None:
    def getenv(k: str):
        return {ENV_SUBMIT_RATE: "not-a-rate", ENV_MAX_RETRY: "negative"}.get(k)
    cfg = SubmitWorkerConfig.from_env_with(getenv)
    # Malformed values are ignored -> defaults restored.
    assert cfg == SubmitWorkerConfig()


# ---------------------------------------------------------------------------
# T16 — Token-bucket refill semantics
# ---------------------------------------------------------------------------


def test_t16_token_bucket_refill_semantics() -> None:
    b = _TokenBucket(1, 30)
    assert b.try_consume(0) is True
    assert b.try_consume(15) is False  # within window
    assert b.try_consume(30) is True   # full window elapsed
    # Clock-going-backwards is treated as no-time-passed.
    assert b.try_consume(5) is False


# ---------------------------------------------------------------------------
# T17 — Throttle re-queues at the FRONT
# ---------------------------------------------------------------------------


def test_t17_throttled_envelope_serves_first_on_next_eligible_tick() -> None:
    cfg = SubmitWorkerConfig(
        rate_requests=1,
        rate_window_secs=60,
        max_retry=5,
        retry_base_delay_secs=1,
        retry_max_delay_secs=300,
    )
    transport = ScriptedTransport(
        [TransportOutcome.accepted(), TransportOutcome.accepted()]
    )
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    w = AnchorSubmitWorker(
        config=cfg, transport=transport, clock=clock, rng=rng,
    )
    w.enqueue({"event_id": "first", "persona_id": "reza"})
    w.enqueue({"event_id": "second", "persona_id": "reza"})

    r1 = w.tick()
    assert r1.kind == SubmitResultKind.SUCCESS
    assert r1.event_id == "first"

    r2 = w.tick()
    assert r2.kind == SubmitResultKind.THROTTLED
    assert r2.event_id == "second"

    clock.advance(60)
    r3 = w.tick()
    assert r3.kind == SubmitResultKind.SUCCESS
    assert r3.event_id == "second", (
        "the throttled envelope must be served first on the next eligible tick"
    )


# ---------------------------------------------------------------------------
# T18 — DeterministicRng clamping + zero-upper + empty-sequence
# ---------------------------------------------------------------------------


def test_t18_deterministic_rng_clamping_and_edge_cases() -> None:
    r = DeterministicRng([999])
    assert r.gen_range_secs(10) == 10  # clamped to upper
    r2 = DeterministicRng([42])
    assert r2.gen_range_secs(0) == 0  # zero-upper short-circuits
    with pytest.raises(SubmitWorkerError):
        DeterministicRng([])  # empty-sequence is a programming error


# ---------------------------------------------------------------------------
# Extra — wire-shape determinism through the JSON parser
# ---------------------------------------------------------------------------


def test_decision_record_b64_is_canonical_jcs_form_per_fixture() -> None:
    """Per-entry: b64-decoded bytes match serialize_decision_record(SubmitResult)."""

    fx = _load_fixtures()
    for f in fx["fixtures"]:
        for entry in f["expected"]["ledger"]:
            decoded = base64.b64decode(entry["decision_jcs_b64"])
            assert len(decoded) == entry["decision_jcs_len"]
            # The decoded bytes parse to a dict whose JSON-canonical
            # re-encoding equals the bytes themselves (idempotent JCS).
            d = json.loads(decoded.decode("utf-8"))
            re_canonical = json.dumps(
                d, separators=(",", ":"), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            assert re_canonical == decoded
