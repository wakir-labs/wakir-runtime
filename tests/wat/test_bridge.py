# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Unit tests for the Wirelang -> WAT ingestion bridge.

Coverage:

- L1 frame projection: typical, empty data, no cap, multi-cap.
- compute_payload_hash: spec-§3.3.1 empty-data clause.
- extract_capability_token_hash: prefix-strip, empty sentinel, malformed
  guard, multi-cap first-entry rule.
- LeafRecord -> JSONL dict round-trip.
- Spool writer: append, fsync flag, hour-boundary routing,
  sealed-rename atomicity, idempotent re-seal, late-frame-window
  enforcement, sealed-file re-open verbot, empty-hour skip,
  parallel-write append-mode safety.
- Recovery-drill prefix: ``event_id`` namespace disjointness.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

import pytest

from wat.ingestion import (
    LATE_FRAME_WINDOW_MINUTES,
    SEALED_SUFFIX,
    LeafRecord,
    append_leaf_to_spool,
    compute_payload_hash,
    extract_capability_token_hash,
    hour_slot_for_time,
    project_l1_frame_to_leaf,
    seal_due_hours,
    seal_hour,
)


# ---------------------------------------------------------------------------
# Frame fixtures
# ---------------------------------------------------------------------------


def _typical_frame() -> dict:
    """Frame matching ``vector-2-typical-frame`` in the JCS pack."""
    return {
        "specversion": "1.0",
        "type": "wakir.treasury.read",
        "source": "did:web:wakir.dev:treasury-agent",
        "id": "01HK4P8X3W2N5Q9V0R6T7S8YZ2",
        "time": "2026-05-06T12:01:30Z",
        "schemaid": "wakir.treasury.read",
        "schemaversion": "0.1.0",
        "actorrole": "treasury-operator",
        "agentid": "treasury-agent-001",
        "caprefs": [
            "sha256:deadbeef12345678deadbeef12345678"
            "deadbeef12345678deadbeef12345678"
        ],
        "data": {
            "action": "read.balance",
            "wallet": "wakir-treasury-eoa-phase-1",
            "amount_usd_cents": 12500,
        },
    }


def _no_cap_frame() -> dict:
    """Frame with no capability token (announcement-style)."""
    f = _typical_frame()
    f["id"] = "01HK4P8X3W2N5Q9V0R6T7S8YZ3"
    f["time"] = "2026-05-06T12:02:15Z"
    f["caprefs"] = []
    f["data"] = {"announcement": "hello"}
    return f


def _multi_cap_frame() -> dict:
    """Frame with two capability tokens; first-entry rule applies."""
    f = _typical_frame()
    f["id"] = "01HK4P8X3W2N5Q9V0R6T7S8YZA"
    f["caprefs"] = [
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
    ]
    return f


def _leaf(time: str, event_id: str = "ev-001") -> LeafRecord:
    return LeafRecord(
        event_id=event_id,
        time=time,
        payload_hash="0" * 64,
        capability_token_hash="",
        source="did:web:wakir.dev:test",
        actorrole="test-role",
        agentid="test-agent",
        schemaid="wakir.test",
        schemaversion="0.1.0",
    )


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def test_compute_payload_hash_empty_clause() -> None:
    """Spec §3.3.1: absent / empty ``data`` -> SHA-256 of JCS({})."""
    expected = (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert compute_payload_hash(None) == expected
    assert compute_payload_hash({}) == expected


def test_extract_capability_first_cap_only() -> None:
    """Multi-cap frame projects to ``caprefs[0]`` (Tag-7 sync 2)."""
    h = extract_capability_token_hash(_multi_cap_frame())
    assert h == "a" * 64, "must take first caprefs entry, not lex-min"


def test_extract_capability_empty_returns_sentinel() -> None:
    """Spec §3.4: missing / empty caprefs -> empty-string sentinel."""
    assert extract_capability_token_hash({"caprefs": []}) == ""
    assert extract_capability_token_hash({}) == ""
    assert extract_capability_token_hash({"caprefs": None}) == ""


def test_extract_capability_strips_sha256_prefix() -> None:
    cap = "sha256:" + "1" * 64
    assert extract_capability_token_hash({"caprefs": [cap]}) == "1" * 64


def test_extract_capability_malformed_does_not_crash() -> None:
    """Defensive: a non-string caprefs entry collapses to no-cap."""
    assert extract_capability_token_hash({"caprefs": [123]}) == ""


# ---------------------------------------------------------------------------
# L1 -> LeafRecord projection
# ---------------------------------------------------------------------------


def test_l1_frame_projection_complete() -> None:
    """Round-trip a typical frame and assert every field projects right."""
    leaf = project_l1_frame_to_leaf(_typical_frame())
    assert leaf.event_id == "01HK4P8X3W2N5Q9V0R6T7S8YZ2"
    assert leaf.time == "2026-05-06T12:01:30Z"
    assert leaf.source == "did:web:wakir.dev:treasury-agent"
    assert leaf.actorrole == "treasury-operator"
    assert leaf.agentid == "treasury-agent-001"
    assert leaf.schemaid == "wakir.treasury.read"
    assert leaf.schemaversion == "0.1.0"
    assert leaf.capability_token_hash == "deadbeef12345678" * 4
    # Recompute payload hash and compare against vector-2 expected value.
    assert leaf.payload_hash == (
        "b0b0f6cf24bfc58adbc163c9e1ac3a4c4590b2ee79fae18dec71a1e83eda5718"
    )


def test_l1_frame_projection_no_cap() -> None:
    leaf = project_l1_frame_to_leaf(_no_cap_frame())
    assert leaf.capability_token_hash == ""


def test_multi_cap_ordering_first_cap() -> None:
    """Multi-cap frame: leaf binds the *first* capref (spec §3.4.1)."""
    leaf = project_l1_frame_to_leaf(_multi_cap_frame())
    assert leaf.capability_token_hash == "a" * 64


def test_l1_frame_missing_field_raises() -> None:
    bad = _typical_frame()
    del bad["agentid"]
    with pytest.raises(KeyError):
        project_l1_frame_to_leaf(bad)


def test_l1_frame_empty_data_uses_empty_clause() -> None:
    f = _typical_frame()
    f["data"] = {}
    leaf = project_l1_frame_to_leaf(f)
    assert leaf.payload_hash == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )


def test_l1_frame_absent_data_treated_as_empty() -> None:
    """Spec §3.3.1: absent ``data`` projects identically to ``data: {}``."""
    f = _typical_frame()
    del f["data"]
    leaf = project_l1_frame_to_leaf(f)
    assert leaf.payload_hash == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )


def test_event_id_namespace_disjoint() -> None:
    """Tag-7 sync 3: ``recovery-drill-`` prefix is opaque to projection.

    The bridge does not bless or reject the prefix; ``event_id`` is a
    string field copied verbatim. Namespace disjointness is the
    producer's responsibility (recovery drills prefix; regular Wirelang
    producers emit UUIDv7 only). This test pins the byte-faithful copy
    behaviour so a future change that "normalises" event_id is caught.
    """
    drill_frame = _typical_frame()
    drill_frame["id"] = "recovery-drill-01HK4P8X3W2N5Q9V0R6T7S8YZA"
    leaf = project_l1_frame_to_leaf(drill_frame)
    assert leaf.event_id == "recovery-drill-01HK4P8X3W2N5Q9V0R6T7S8YZA"


# ---------------------------------------------------------------------------
# LeafRecord <-> JSONL
# ---------------------------------------------------------------------------


def test_leaf_record_to_jsonl_dict_has_nine_fields() -> None:
    leaf = _leaf("2026-05-06T12:01:30Z")
    d = leaf.to_jsonl_dict()
    assert set(d.keys()) == {
        "event_id",
        "time",
        "payload_hash",
        "capability_token_hash",
        "source",
        "actorrole",
        "agentid",
        "schemaid",
        "schemaversion",
    }


# ---------------------------------------------------------------------------
# Spool writer
# ---------------------------------------------------------------------------


def test_append_leaf_to_spool_writes_jsonl(tmp_path: Path) -> None:
    leaf = _leaf("2026-05-06T12:00:00Z")
    out = append_leaf_to_spool(leaf, tmp_path)
    assert out.name == "2026-05-06T12.jsonl"
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    decoded = json.loads(lines[0])
    assert decoded["event_id"] == "ev-001"
    assert decoded["time"] == "2026-05-06T12:00:00Z"


def test_append_leaf_routes_by_hour(tmp_path: Path) -> None:
    """Two frames in different UTC hours land in different spool files."""
    h12 = append_leaf_to_spool(_leaf("2026-05-06T12:59:59Z", "ev-12"), tmp_path)
    h13 = append_leaf_to_spool(_leaf("2026-05-06T13:00:01Z", "ev-13"), tmp_path)
    assert h12.name == "2026-05-06T12.jsonl"
    assert h13.name == "2026-05-06T13.jsonl"
    assert h12 != h13


def test_append_leaf_to_sealed_hour_drops(tmp_path: Path) -> None:
    """Late frame after seal raises -- spec §5 forbids re-routing."""
    leaf = _leaf("2026-05-06T12:00:00Z", "ev-on-time")
    append_leaf_to_spool(leaf, tmp_path)
    # Seal with the window relaxed (we are testing the sealed-file
    # guard, not the window enforcement).
    seal_hour(tmp_path, "2026-05-06T12", enforce_window=False)
    late = _leaf("2026-05-06T12:30:00Z", "ev-late")
    with pytest.raises(RuntimeError, match="sealed"):
        append_leaf_to_spool(late, tmp_path)


def test_seal_hour_atomic_rename(tmp_path: Path) -> None:
    leaf = _leaf("2026-05-06T12:00:00Z")
    append_leaf_to_spool(leaf, tmp_path)
    sealed = seal_hour(tmp_path, "2026-05-06T12", enforce_window=False)
    assert sealed is not None
    assert sealed.name == "2026-05-06T12.jsonl" + SEALED_SUFFIX
    assert sealed.exists()
    assert not (tmp_path / "2026-05-06T12.jsonl").exists()


def test_seal_hour_idempotent(tmp_path: Path) -> None:
    """Re-sealing a sealed hour is a no-op returning the existing path."""
    append_leaf_to_spool(_leaf("2026-05-06T12:00:00Z"), tmp_path)
    s1 = seal_hour(tmp_path, "2026-05-06T12", enforce_window=False)
    s2 = seal_hour(tmp_path, "2026-05-06T12", enforce_window=False)
    assert s1 == s2
    assert s1.exists()


def test_seal_hour_empty_returns_none(tmp_path: Path) -> None:
    """Empty hour: no open file, nothing to seal, return None."""
    assert seal_hour(tmp_path, "2026-05-06T12", enforce_window=False) is None


def test_seal_hour_window_enforced(tmp_path: Path) -> None:
    """Window guard: seal before H_end + 5min raises by default."""
    append_leaf_to_spool(_leaf("2026-05-06T12:00:00Z"), tmp_path)
    # Inject a "now" inside the late-frame window.
    inside_window = dt.datetime(
        2026, 5, 6, 13, LATE_FRAME_WINDOW_MINUTES - 1,
        tzinfo=dt.timezone.utc,
    )
    with pytest.raises(RuntimeError, match="late-frame window"):
        seal_hour(tmp_path, "2026-05-06T12", now=inside_window)


def test_seal_hour_window_eligible_at_exact_boundary(tmp_path: Path) -> None:
    """Exact H_end + 5min boundary: sealing is permitted."""
    append_leaf_to_spool(_leaf("2026-05-06T12:00:00Z"), tmp_path)
    boundary = dt.datetime(
        2026, 5, 6, 13, LATE_FRAME_WINDOW_MINUTES, tzinfo=dt.timezone.utc,
    )
    sealed = seal_hour(tmp_path, "2026-05-06T12", now=boundary)
    assert sealed is not None and sealed.exists()


def test_seal_due_hours_picks_eligible(tmp_path: Path) -> None:
    """Driver helper finds every hour past its late-frame window."""
    append_leaf_to_spool(_leaf("2026-05-06T10:00:00Z"), tmp_path)
    append_leaf_to_spool(_leaf("2026-05-06T11:00:00Z"), tmp_path)
    append_leaf_to_spool(_leaf("2026-05-06T12:30:00Z"), tmp_path)
    now = dt.datetime(2026, 5, 6, 12, 10, tzinfo=dt.timezone.utc)
    sealed = seal_due_hours(tmp_path, now=now)
    sealed_names = sorted(p.name for p in sealed)
    # 10:00 hour: H_end=11:00, eligible 11:05 -- past, sealed.
    # 11:00 hour: H_end=12:00, eligible 12:05 -- past, sealed.
    # 12:30 hour: H_end=13:00 -- not yet eligible.
    assert sealed_names == [
        "2026-05-06T10.jsonl.sealed",
        "2026-05-06T11.jsonl.sealed",
    ]
    assert (tmp_path / "2026-05-06T12.jsonl").exists()


def test_append_concurrent_no_byteinterleave(tmp_path: Path) -> None:
    """Concurrent appenders rely on POSIX append-mode atomicity.

    Stress-test: 4 threads each write 50 leaves into the same hour
    file. Every line must round-trip through ``json.loads`` (no byte
    interleave). The ``event_id`` count must be exactly 4*50.
    """

    def writer(thread_id: int) -> None:
        for i in range(50):
            leaf = _leaf(
                "2026-05-06T12:00:00Z",
                event_id=f"t{thread_id}-{i:03d}",
            )
            append_leaf_to_spool(leaf, tmp_path, fsync=False)

    threads = [
        threading.Thread(target=writer, args=(tid,)) for tid in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    spool = tmp_path / "2026-05-06T12.jsonl"
    lines = [
        json.loads(ln) for ln in spool.read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) == 200
    # Every line must have a well-formed event_id of the form ``t{n}-{n:03d}``
    seen_ids = {ln["event_id"] for ln in lines}
    assert len(seen_ids) == 200


def test_hour_slot_for_time_utc_only() -> None:
    assert hour_slot_for_time("2026-05-06T12:01:30Z") == "2026-05-06T12"
    assert hour_slot_for_time("2026-05-06T12:00:00+00:00") == "2026-05-06T12"
    with pytest.raises(ValueError):
        hour_slot_for_time("2026-05-06T12:00:00")  # no tz
    with pytest.raises(ValueError):
        hour_slot_for_time("nope")


def test_append_creates_spool_dir(tmp_path: Path) -> None:
    """Bridge MUST create the spool dir if missing -- driver friendliness."""
    nested = tmp_path / "a" / "b" / "c"
    leaf = _leaf("2026-05-06T12:00:00Z")
    out = append_leaf_to_spool(leaf, nested)
    assert nested.is_dir()
    assert out.exists()


def test_typical_frame_hash_round_trip_against_aggregator() -> None:
    """Bridge -> aggregator hash equivalence (vector-2 expected value).

    End-to-end: project a frame, take the four hash-input fields off
    the resulting LeafRecord, push them through ``compute_leaf_hash``,
    and compare against the recorded ``expected_leaf_hash`` for
    vector-2. This is the consensus-marker A3 invariant.
    """
    from wat.merkle.aggregator import compute_leaf_hash

    leaf = project_l1_frame_to_leaf(_typical_frame())
    digest = compute_leaf_hash(
        event_id=leaf.event_id,
        time=leaf.time,
        payload_hash=leaf.payload_hash,
        capability_token_hash=leaf.capability_token_hash,
    )
    assert digest.hex() == (
        "846a012d3bb8de89d80414c3747cbcc561f938c5a04e52be422dc932e2bbc969"
    )
