# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the WAT manifest-v2 verifier-stub.

The module under test (``wat/verify/manifest_v2.py``, BSL 1.1) is
the cross-module integrity checker that complements the schema-only
smoke tests. These tests build *real* manifests with consistent
SHA-256 leaves, real Merkle trees, and real ordered-Merkle
``caprefs_root`` values, then exercise both happy-path and a
deliberate set of negative cases.

Tests are Apache 2.0 so external re-implementers can use them as
black-box conformance vectors against their own verifiers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

from wat.merkle.aggregator import build_merkle_tree, compute_leaf_hash
from wat.verify.manifest_v2 import (
    ManifestV2Result,
    OtsAnchorCheck,
    RealManifestResult,
    main as verifier_main,
    verify_manifest_v2_file,
    verify_real_manifest_file,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_event(idx: int, *, capref_hash_hex: str = "") -> Dict[str, str]:
    """Return one B1-tuple event dict with deterministic fields."""
    return {
        "event_id": f"evt-{idx}",
        "time": f"2026-05-26T17:00:0{idx}Z",
        "payload_hash": hashlib.sha256(f"payload-{idx}".encode()).hexdigest(),
        "capability_token_hash": capref_hash_hex,
    }


def _build_v1_manifest(events: Sequence[Dict[str, str]]) -> Dict:
    """Construct a v1-shaped manifest with consistent leaves + root.

    The result validates against the v2-aware schema (since v2 is
    additive over v1) and passes integrity. Used as the baseline
    happy-path fixture and as the starting point for negative cases.
    """
    leaves_bytes = [
        compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        for ev in events
    ]
    root, levels = build_merkle_tree(leaves_bytes)
    enriched_events = [
        {**ev, "leaf": leaves_bytes[i].hex()} for i, ev in enumerate(events)
    ]
    return {
        "version": "wat-manifest/1.0",
        "hour_slot": "2026-05-26T17",
        "merkle_root": root.hex(),
        "event_count": len(events),
        "events": enriched_events,
        "leaves": [leaf.hex() for leaf in leaves_bytes],
        "tree_levels": [[node.hex() for node in level] for level in levels],
        "build_time": "2026-05-26T17:00:00Z",
    }


def _ordered_caprefs_root(caprefs_full: Sequence[str]) -> str:
    """Return the ordered-Merkle hex root over caprefs_full sha256:..."""
    leaves = [bytes.fromhex(ref[len("sha256:"):]) for ref in caprefs_full]
    root, _levels = build_merkle_tree(leaves)
    return root.hex()


def _build_v2_manifest(
    events: Sequence[Dict[str, str]],
    multi_cap: Dict[str, List[str]],
) -> Dict:
    """Construct a v2-shaped manifest with consistent multi-cap sidecar.

    ``multi_cap`` maps event_id -> list of ``"sha256:<hex>"`` caprefs.
    Each event so listed must already exist in ``events``.
    """
    base = _build_v1_manifest(events)
    base["version"] = "wat-manifest/2.0"

    multi_cap_events = {}
    distinct = set()
    max_caps = 0
    for ev_id, caprefs in multi_cap.items():
        assert any(ev["event_id"] == ev_id for ev in events), (
            f"event_id {ev_id} not in events fixture"
        )
        multi_cap_events[ev_id] = {
            "caprefs_full": list(caprefs),
            "caprefs_root": _ordered_caprefs_root(caprefs),
        }
        max_caps = max(max_caps, len(caprefs))
        distinct.update(caprefs)

    base["multi_cap_events"] = multi_cap_events
    base["multi_cap_summary"] = {
        "events_with_multi_cap": len(multi_cap_events),
        "max_caprefs_in_any_event": max_caps,
        "distinct_capability_token_hashes_in_hour": len(distinct),
    }
    return base


def _write_manifest(tmp_path: Path, manifest: Dict, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


# Sample sha256:-prefixed capability-token hashes (placeholder digests
# of distinct salts so the tests do not collide).
_CAPREF_1 = "sha256:" + hashlib.sha256(b"capref-1").hexdigest()
_CAPREF_2 = "sha256:" + hashlib.sha256(b"capref-2").hexdigest()
_CAPREF_3 = "sha256:" + hashlib.sha256(b"capref-3").hexdigest()


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


def test_v1_minimal_manifest_validates_and_is_consistent(tmp_path: Path) -> None:
    """A real v1 manifest with one event passes schema + integrity."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert result.ok, result.failure_reason
    assert result.version == "wat-manifest/1.0"
    assert result.schema_ok
    assert result.integrity_ok
    assert result.multi_cap_root_status == ""


def test_v2_manifest_multi_event_passes_strict_default(tmp_path: Path) -> None:
    """v2 with two multi-cap events validates in strict (default) mode.

    Strict mode is the default since Sprint-2 Tag-4 (OQ-1 ratified
    ordered-Merkle 2026-05-07 by wirelang-engineering Cross-Review-
    Zone-2). The reference verifier recomputes ``caprefs_root`` over
    ``caprefs_full`` using the ordered convention and reports
    ``verified``. See docs/wat-manifest-v2-spec.md §8 verifier-
    posture matrix.
    """
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v2_manifest(
        events,
        multi_cap={
            "evt-1": [_CAPREF_1, _CAPREF_2],
            "evt-2": [_CAPREF_1, _CAPREF_2, _CAPREF_3],
        },
    )
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert result.ok, result.failure_reason
    assert result.version == "wat-manifest/2.0"
    assert result.multi_cap_root_status == "verified"


def test_v2_manifest_lenient_mode_explicit_off_reports_deferred(
    tmp_path: Path,
) -> None:
    """The lenient escape hatch remains available for downstream verifiers.

    Third-party verifiers that have not yet adopted the locked
    ordering can opt out of the strict recompute by passing
    ``strict_multi_cap_root=False``; the result then carries
    ``multi_cap_root_status="deferred"`` (the pre-OQ-1-ratification
    semantics).
    """
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v2_manifest(
        events,
        multi_cap={
            "evt-1": [_CAPREF_1, _CAPREF_2],
            "evt-2": [_CAPREF_1, _CAPREF_2, _CAPREF_3],
        },
    )
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path, strict_multi_cap_root=False)

    assert result.ok, result.failure_reason
    assert result.multi_cap_root_status == "deferred"


def test_v2_manifest_strict_mode_recomputes_caprefs_root(tmp_path: Path) -> None:
    """Strict mode recomputes caprefs_root and accepts a correct one."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path, strict_multi_cap_root=True)

    assert result.ok, result.failure_reason
    assert result.multi_cap_root_status == "verified"


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_schema_failure_v1_with_multi_cap_keys_rejected(tmp_path: Path) -> None:
    """A v1 manifest carrying multi_cap_events fails at schema layer.

    This is the producer-bug guard duplicated from the schema-smoke
    suite; here we verify the stub propagates it as a schema-phase
    failure with the right reason prefix.
    """
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    manifest["multi_cap_events"] = {
        "evt-1": {
            "caprefs_full": [_CAPREF_1, _CAPREF_2],
            "caprefs_root": "f" * 64,
        }
    }
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert not result.ok
    assert result.schema_ok is False
    assert result.failure_reason.startswith("schema:")


def test_integrity_failure_merkle_root_mismatch(tmp_path: Path) -> None:
    """Tampering with merkle_root after build is caught by rebuild."""
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v1_manifest(events)
    # Flip a few hex chars in the recorded root; schema still accepts
    # the result (it is still 64 lowercase-hex), but the rebuild from
    # leaves no longer matches.
    bad_root = "0" * 64
    manifest["merkle_root"] = bad_root
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert not result.ok
    assert result.schema_ok is True
    assert result.integrity_ok is False
    assert "merkle_root mismatch" in result.failure_reason


def test_integrity_failure_event_count_drift(tmp_path: Path) -> None:
    """``event_count`` lying about ``len(events)`` is caught."""
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v1_manifest(events)
    manifest["event_count"] = 99  # lie
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert not result.ok
    assert "event_count drift" in result.failure_reason


def test_integrity_failure_summary_count_drift(tmp_path: Path) -> None:
    """multi_cap_summary count contradicts multi_cap_events sidecar."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    # Schema accepts any positive integer; only the cross-check
    # against the actual sidecar size catches this.
    manifest["multi_cap_summary"]["events_with_multi_cap"] = 5
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert not result.ok
    assert result.schema_ok is True
    assert "events_with_multi_cap drift" in result.failure_reason


def test_integrity_failure_multi_cap_event_id_not_in_events(tmp_path: Path) -> None:
    """multi_cap_events keys must intersect events[].event_id."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    # Re-key the sidecar to a non-existent event_id; keep summary
    # counts consistent so we exercise the *cross-reference* check
    # specifically.
    entry = manifest["multi_cap_events"].pop("evt-1")
    manifest["multi_cap_events"]["evt-99"] = entry
    path = _write_manifest(tmp_path, manifest)

    result = verify_manifest_v2_file(path)

    assert not result.ok
    assert "not present in events[]" in result.failure_reason


def test_strict_mode_multi_cap_root_mismatch_detected(tmp_path: Path) -> None:
    """A tampered ``caprefs_root`` is caught in strict mode (default).

    Lenient mode (explicit ``strict_multi_cap_root=False``, escape
    hatch for third-party verifiers) skips the recompute and accepts
    the manifest with ``deferred`` status.
    """
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    # Flip caprefs_root to a syntactically valid but wrong hash.
    manifest["multi_cap_events"]["evt-1"]["caprefs_root"] = "1" * 64
    path = _write_manifest(tmp_path, manifest)

    # Lenient (explicit opt-out): passes (deferred). Escape hatch for
    # downstream verifiers that have not yet adopted the locked ordering.
    lenient = verify_manifest_v2_file(path, strict_multi_cap_root=False)
    assert lenient.ok
    assert lenient.multi_cap_root_status == "deferred"

    # Strict (default since Sprint-2 Tag-4): fails.
    strict = verify_manifest_v2_file(path)
    assert not strict.ok
    assert strict.multi_cap_root_status == "mismatch"
    assert strict.failure_reason.startswith("multi_cap_root:")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def test_cli_main_returns_zero_on_valid_v2_manifest(tmp_path: Path, capsys) -> None:
    """End-to-end: ``python -m wat.verify.manifest_v2`` exit-code 0."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main([str(path)])

    out = capsys.readouterr().out
    assert rc == 0, out
    assert "integrity_ok:    True" in out


def test_cli_main_returns_one_on_tampered_manifest(tmp_path: Path, capsys) -> None:
    """Non-zero exit on integrity failure, with diagnostic on stdout."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    manifest["merkle_root"] = "0" * 64  # forced mismatch
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main([str(path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "merkle_root mismatch" in out


# ---------------------------------------------------------------------------
# JSON output mode (Sprint-2 Tag-2 — frontend-cross-review pickup)
# ---------------------------------------------------------------------------


def test_as_dict_returns_pinned_schema_keys() -> None:
    """``ManifestV2Result.as_dict`` exposes the documented JSON schema.

    Pins the exact set of keys consumers (notably the frontend
    ``VerifierResultCard`` aggregation layer) can rely on across
    additive future revisions of the verifier.
    """
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status="deferred",
        failure_reason="",
    )

    payload = result.as_dict()

    assert payload == {
        "schema_version": "wakir-verify-manifest-v2/0",
        "manifest_path": "/tmp/x.json",
        "manifest_version": "wat-manifest/2.0",
        "ok": True,
        "schema_ok": True,
        "integrity_ok": True,
        "multi_cap_root_status": "deferred",
        "failure_reason": "",
    }


def test_cli_output_json_emits_single_line_object_on_success(
    tmp_path: Path, capsys
) -> None:
    """``--output json`` emits a JSON object on stdout, exit-code 0.

    Default-strict-mode (Sprint-2 Tag-4 onwards) reports
    ``multi_cap_root_status="verified"`` for a clean v2 manifest
    whose ``caprefs_root`` is the ordered-Merkle hash of
    ``caprefs_full``.
    """
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main([str(path), "--output", "json"])

    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["schema_ok"] is True
    assert payload["integrity_ok"] is True
    assert payload["manifest_version"] == "wat-manifest/2.0"
    assert payload["multi_cap_root_status"] == "verified"
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    # Single-line: exactly one trailing newline from print, no embedded newlines.
    assert "\n" not in out


def test_cli_output_json_no_strict_flag_emits_deferred_status(
    tmp_path: Path, capsys
) -> None:
    """``--no-strict-multi-cap-root`` emits the lenient ``deferred`` posture.

    Escape hatch for third-party verifiers that have not yet adopted
    the OQ-1-ratified ordered-Merkle convention; preserved as a CLI
    flag since Sprint-2 Tag-4 default-flip.
    """
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main(
        [str(path), "--output", "json", "--no-strict-multi-cap-root"]
    )

    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert payload["multi_cap_root_status"] == "deferred"


def test_cli_output_json_on_tampered_manifest_carries_failure_reason(
    tmp_path: Path, capsys
) -> None:
    """JSON output mirrors the human-mode failure_reason field."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    manifest["merkle_root"] = "0" * 64  # forced mismatch
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main([str(path), "--output", "json"])

    out = capsys.readouterr().out.strip()
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["integrity_ok"] is False
    assert "merkle_root mismatch" in payload["failure_reason"]
    assert payload["failure_reason"].startswith("integrity:")


def test_cli_output_json_strict_mode_reports_verified_status(
    tmp_path: Path, capsys
) -> None:
    """Strict-mode + clean v2 manifest -> ``multi_cap_root_status="verified"``."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main(
        [str(path), "--output", "json", "--strict-multi-cap-root"]
    )

    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert payload["multi_cap_root_status"] == "verified"


def test_cli_output_json_keys_are_sorted(tmp_path: Path, capsys) -> None:
    """Stable byte-output for downstream diffing / snapshot tests."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    path = _write_manifest(tmp_path, manifest)

    verifier_main([str(path), "--output", "json"])

    out = capsys.readouterr().out.strip()
    # Verify the bytes are key-sorted JSON (sort_keys=True at print site).
    payload = json.loads(out)
    assert out == json.dumps(payload, sort_keys=True)


# ---------------------------------------------------------------------------
# Audit-trail-entry export contract (Sprint-2 Tag-3 — paired-update with
# frontend AuditTrailEntry consumer)
# ---------------------------------------------------------------------------


_PINNED_AUDIT_TRAIL_ENTRY_KEYS = frozenset(
    {
        "kind",
        "schema_version",
        "identity",
        "manifest_version",
        "manifest_path",
        "hour_slot",
        "event_count",
        "anchor_root_hex",
        "branches",
        "ok",
        "failure_reason",
    }
)


def test_as_audit_trail_entry_returns_pinned_eleven_keys() -> None:
    """The entry exposes exactly the documented eleven keys, always."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status="deferred",
        failure_reason="",
    )

    entry = result.as_audit_trail_entry()

    assert set(entry.keys()) == _PINNED_AUDIT_TRAIL_ENTRY_KEYS


def test_as_audit_trail_entry_kind_is_pinned_string() -> None:
    """``kind`` is the string literal ``"wat-tv-pin-pack"`` for every result."""
    for ok_state in (True, False):
        result = ManifestV2Result(
            manifest_path="/tmp/x.json",
            version="wat-manifest/2.0",
            schema_ok=ok_state,
            integrity_ok=ok_state,
        )
        entry = result.as_audit_trail_entry()
        assert entry["kind"] == "wat-tv-pin-pack"


def test_as_audit_trail_entry_schema_version_matches_as_dict() -> None:
    """``schema_version`` is the same string as the ``--output json`` mode."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/1.0",
        schema_ok=True,
        integrity_ok=True,
    )

    assert (
        result.as_audit_trail_entry()["schema_version"]
        == result.as_dict()["schema_version"]
    )


def test_as_audit_trail_entry_verdict_verified_on_clean_strict() -> None:
    """v2-strict-clean -> verdict == "verified", detail mentions all phases."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status="verified",
    )

    entry = result.as_audit_trail_entry()
    assert entry["ok"] is True
    assert entry["branches"] == [
        {
            "label": "manifest-validity",
            "verdict": "verified",
            "detail": "schema + integrity + multi_cap_root",
        }
    ]


def test_as_audit_trail_entry_verdict_pending_on_lenient_deferred() -> None:
    """v2-lenient-deferred -> verdict == "pending" (OQ-1 honesty)."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status="deferred",
    )

    entry = result.as_audit_trail_entry()
    assert entry["ok"] is True
    assert entry["branches"][0]["verdict"] == "pending"
    assert "OQ-1" in entry["branches"][0]["detail"]


def test_as_audit_trail_entry_verdict_rejected_carries_failure_reason() -> None:
    """A failed result puts the failure_reason into the branch detail."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=False,
        multi_cap_root_status="",
        failure_reason="integrity: merkle_root mismatch: rebuilt aaaa from leaves[]",
    )

    entry = result.as_audit_trail_entry()
    assert entry["ok"] is False
    branch = entry["branches"][0]
    assert branch["verdict"] == "rejected"
    assert branch["detail"] == result.failure_reason
    assert entry["failure_reason"] == result.failure_reason


def test_as_audit_trail_entry_identity_prefers_hour_slot() -> None:
    """``identity`` is hour-slot-derived when available, else manifest_path."""
    base = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
    )

    with_slot = base.as_audit_trail_entry(hour_slot="2026-05-26T17")
    without_slot = base.as_audit_trail_entry()

    assert with_slot["identity"] == "wat-hour 2026-05-26T17"
    assert without_slot["identity"] == "/tmp/x.json"


def test_as_audit_trail_entry_anchor_root_hex_validated() -> None:
    """``anchor_root_hex`` rejects non-canonical input early."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
    )

    # Empty is fine.
    entry = result.as_audit_trail_entry(anchor_root_hex="")
    assert entry["anchor_root_hex"] == ""

    # 64 lowercase-hex is fine.
    entry = result.as_audit_trail_entry(anchor_root_hex="a" * 64)
    assert entry["anchor_root_hex"] == "a" * 64

    # Anything else raises — the wire format must match the schema.
    with pytest.raises(ValueError):
        result.as_audit_trail_entry(anchor_root_hex="A" * 64)  # uppercase
    with pytest.raises(ValueError):
        result.as_audit_trail_entry(anchor_root_hex="a" * 63)  # short
    with pytest.raises(ValueError):
        result.as_audit_trail_entry(anchor_root_hex="sha256:" + "a" * 64)


def test_as_audit_trail_entry_field_types_are_stable() -> None:
    """Per-field type contract holds across ok and failure paths.

    Field-by-field type pin (downstream snapshot-test tauglich):
    no ``None`` values, every list is a list, every int an int,
    every string a str.
    """
    samples = [
        ManifestV2Result(
            manifest_path="/tmp/a.json",
            version="wat-manifest/2.0",
            schema_ok=True,
            integrity_ok=True,
            multi_cap_root_status="verified",
        ),
        ManifestV2Result(
            manifest_path="/tmp/b.json",
            version="wat-manifest/1.0",
            schema_ok=False,
            integrity_ok=False,
            multi_cap_root_status="",
            failure_reason="schema: /events: missing",
        ),
    ]

    expected_types = {
        "kind": str,
        "schema_version": str,
        "identity": str,
        "manifest_version": str,
        "manifest_path": str,
        "hour_slot": str,
        "event_count": int,
        "anchor_root_hex": str,
        "branches": list,
        "ok": bool,
        "failure_reason": str,
    }

    for result in samples:
        entry = result.as_audit_trail_entry()
        for key, expected_type in expected_types.items():
            assert key in entry, f"missing key {key!r}"
            assert isinstance(entry[key], expected_type), (
                f"field {key!r} is {type(entry[key]).__name__}, "
                f"expected {expected_type.__name__}"
            )
            # No None anywhere.
            assert entry[key] is not None, f"field {key!r} is None"


def test_as_audit_trail_entry_dump_roundtrip_is_byte_stable() -> None:
    """sort_keys + ensure_ascii=False produce a canonical wire-form.

    Two dumps of the same result must produce identical bytes; a
    re-parse-then-redump must produce the same bytes again. This is
    the snapshot-test / content-hash tauglich determinism guarantee.
    """
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
        multi_cap_root_status="deferred",
    )
    entry = result.as_audit_trail_entry(
        hour_slot="2026-05-26T17",
        anchor_root_hex="a" * 64,
        event_count=4,
    )

    bytes_1 = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    bytes_2 = json.dumps(entry, sort_keys=True, ensure_ascii=False)
    assert bytes_1 == bytes_2

    reparsed = json.loads(bytes_1)
    bytes_3 = json.dumps(reparsed, sort_keys=True, ensure_ascii=False)
    assert bytes_1 == bytes_3


def test_as_audit_trail_entry_event_count_defaults_to_minus_one() -> None:
    """Missing event_count renders as -1, never as None or absent key."""
    result = ManifestV2Result(
        manifest_path="/tmp/x.json",
        version="wat-manifest/2.0",
        schema_ok=True,
        integrity_ok=True,
    )

    default_entry = result.as_audit_trail_entry()
    assert default_entry["event_count"] == -1

    populated_entry = result.as_audit_trail_entry(event_count=7)
    assert populated_entry["event_count"] == 7


def test_cli_output_audit_trail_entry_emits_eleven_field_object(
    tmp_path: Path, capsys
) -> None:
    """End-to-end: ``--output audit-trail-entry`` emits the pinned shape."""
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main([str(path), "--output", "audit-trail-entry"])

    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert set(payload.keys()) == _PINNED_AUDIT_TRAIL_ENTRY_KEYS
    assert payload["kind"] == "wat-tv-pin-pack"
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    assert payload["hour_slot"] == "2026-05-26T17"
    assert payload["event_count"] == 2
    assert payload["anchor_root_hex"] == manifest["merkle_root"]
    assert payload["identity"] == "wat-hour 2026-05-26T17"
    # Strict default since Sprint-2 Tag-4 (OQ-1 ratified ordered-Merkle):
    # verdict is "verified" for a clean v2 manifest whose caprefs_root is
    # the ordered hash of caprefs_full.
    assert payload["branches"][0]["verdict"] == "verified"
    # No embedded newlines: single-line wire format.
    assert "\n" not in out


def test_cli_output_audit_trail_entry_lenient_mode_yields_pending_verdict(
    tmp_path: Path, capsys
) -> None:
    """``--no-strict-multi-cap-root`` keeps the lenient ``pending`` verdict.

    Lenient escape hatch for third-party verifiers — the pre-OQ-1-
    ratification ``deferred`` semantics maps to ``verdict="pending"``
    in the audit-trail-entry shape (honesty bucket).
    """
    events = [
        _make_event(1, capref_hash_hex="a" * 64),
        _make_event(2, capref_hash_hex="b" * 64),
    ]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    path = _write_manifest(tmp_path, manifest)

    rc = verifier_main(
        [str(path), "--output", "audit-trail-entry", "--no-strict-multi-cap-root"]
    )

    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    assert payload["branches"][0]["verdict"] == "pending"


def test_cli_output_audit_trail_entry_keys_are_sorted(tmp_path: Path, capsys) -> None:
    """CLI byte-output is key-sorted (downstream snapshot-test tauglich)."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v1_manifest(events)
    path = _write_manifest(tmp_path, manifest)

    verifier_main([str(path), "--output", "audit-trail-entry"])

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    # ensure_ascii=False matches the Python-side dump in main()
    assert out == json.dumps(payload, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Sprint-2 Tag-5: Real-manifest mode + OTS-pin-anchor side-files
# ---------------------------------------------------------------------------
#
# These tests exercise the verifier against the on-disk wire-form the
# real aggregator emits today (``wakir-wat-manifest/v1`` with
# ``leaf_hash`` field name and full leaves objects). They build a
# hermetic real-manifest in-memory, write it to a tmp_path with
# sibling ``root.bin`` / ``root.bin.ots`` files, and assert the
# verifier accepts it. Negative cases cover field-validation,
# integrity-rebuild, and OTS-anchor side-file failure modes.


_OTS_MAGIC = b"\x00OpenTimestamps\x00"


def _build_real_v1_manifest(
    events: Sequence[Dict[str, str]],
    *,
    hour_slot: str = "2026-05-26T17",
    anchor_height: int | None = None,
) -> Dict:
    """Build a wakir-wat-manifest/v1 wire-form manifest.

    Mirrors the on-disk shape emitted by ``wat/aggregator.py`` for
    real TV-2 / TV-3 hours: ``leaf_hash`` field on each event, leaves
    are full objects (not hex strings), ``prev_hour_root`` defaults
    to None.
    """
    leaves_bytes = [
        compute_leaf_hash(
            event_id=ev["event_id"],
            time=ev["time"],
            payload_hash=ev["payload_hash"],
            capability_token_hash=ev["capability_token_hash"],
        )
        for ev in events
    ]
    root, levels = build_merkle_tree(leaves_bytes)
    enriched = []
    leaves_obj = []
    for i, ev in enumerate(events):
        e = dict(ev)
        e["leaf_hash"] = leaves_bytes[i].hex()
        enriched.append(e)
        leaves_obj.append(dict(e))
    out: Dict = {
        "version": "wakir-wat-manifest/v1",
        "hour_slot": hour_slot,
        "merkle_root": root.hex(),
        "event_count": len(events),
        "events": enriched,
        "leaves": leaves_obj,
        "tree_levels": [[node.hex() for node in level] for level in levels],
        "build_time": "2026-05-26T17:25:39Z",
        "prev_hour_root": None,
    }
    if anchor_height is not None:
        out["anchor_height"] = anchor_height
    return out


def _write_real_manifest_with_ots(
    tmp_path: Path,
    manifest: Dict,
    *,
    write_root_bin: bool = True,
    write_ots: bool = True,
    ots_magic: bytes = _OTS_MAGIC,
) -> Path:
    """Write manifest.json + root.bin + root.bin.ots to tmp_path.

    Returns the manifest path. Set ``write_root_bin`` / ``write_ots``
    False to simulate missing-side-file failure modes; pass a custom
    ``ots_magic`` to simulate a corrupt OTS header.
    """
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    if write_root_bin:
        (tmp_path / "root.bin").write_bytes(bytes.fromhex(manifest["merkle_root"]))
    if write_ots:
        # Magic header + a couple of trailing bytes so the file is
        # plausibly proof-shaped (we only check the magic).
        (tmp_path / "root.bin.ots").write_bytes(ots_magic + b"\x01\x02\x03")
    return mpath


def test_real_manifest_v1_happy_path_with_ots_anchor(tmp_path: Path) -> None:
    """Real v1 manifest + matching root.bin + valid OTS-magic passes."""
    events = [_make_event(i, capref_hash_hex="a" * 64) for i in (0, 1)]
    manifest = _build_real_v1_manifest(events, anchor_height=900_000)
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    result = verify_real_manifest_file(mpath, check_ots_anchor=True)

    assert result.ok
    assert result.fields_ok and result.integrity_ok
    assert result.version == "wakir-wat-manifest/v1"
    assert result.ots_anchor.ok
    assert result.ots_anchor.root_bin_matches_manifest
    assert result.ots_anchor.ots_magic_ok
    assert result.failure_reason == ""


def test_real_manifest_v1_against_published_fixture() -> None:
    """The in-repo TV-3 fixture validates end-to-end including OTS-magic.

    The fixture under ``tests/fixtures/wat-real-manifest/`` is a
    verbatim copy of a real TV-3 archive hour (``.runtime/wat-tv3-
    archive/20260507T072538Z/2026-05-26T17/``) — manifest.json +
    root.bin + root.bin.ots. Pinning verification against this
    fixture catches regressions in either the verifier or the real-
    aggregator emit-shape.
    """
    fixture_dir = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "wat-real-manifest"
    )
    mpath = fixture_dir / "manifest.json"
    assert mpath.exists(), f"fixture missing: {mpath}"
    assert (fixture_dir / "root.bin").exists()
    assert (fixture_dir / "root.bin.ots").exists()

    result = verify_real_manifest_file(mpath, check_ots_anchor=True)

    assert result.ok, result.failure_reason
    assert result.version == "wakir-wat-manifest/v1"
    assert result.ots_anchor.ok


def test_real_manifest_field_validation_rejects_unknown_version(
    tmp_path: Path,
) -> None:
    """Unknown ``version`` field yields a /version pointer-style diagnostic."""
    events = [_make_event(i, capref_hash_hex="b" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    manifest["version"] = "wakir-wat-manifest/vX"
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert not result.ok
    assert not result.fields_ok
    assert result.failure_reason.startswith("fields: field /version:")


def test_real_manifest_field_validation_rejects_missing_required(
    tmp_path: Path,
) -> None:
    """Missing ``hour_slot`` yields a /hour_slot pointer-style diagnostic."""
    events = [_make_event(i, capref_hash_hex="c" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    del manifest["hour_slot"]
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert not result.ok
    assert not result.fields_ok
    assert "field /hour_slot" in result.failure_reason
    assert result.failure_reason.startswith("fields:")


def test_real_manifest_field_validation_rejects_negative_anchor_height(
    tmp_path: Path,
) -> None:
    """Optional ``anchor_height`` must be a positive int when present."""
    events = [_make_event(i, capref_hash_hex="d" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events, anchor_height=-1)
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert not result.ok
    assert not result.fields_ok
    assert "anchor_height" in result.failure_reason


def test_real_manifest_merkle_rebuild_catches_root_drift(tmp_path: Path) -> None:
    """Tampering with ``merkle_root`` after build is caught by integrity rebuild."""
    events = [_make_event(i, capref_hash_hex="e" * 64) for i in (0, 1, 2)]
    manifest = _build_real_v1_manifest(events)
    # Tamper with merkle_root: flip the last hex char.
    original = manifest["merkle_root"]
    flipped = original[:-1] + ("0" if original[-1] != "0" else "1")
    manifest["merkle_root"] = flipped
    mpath = _write_real_manifest_with_ots(tmp_path, manifest, write_root_bin=False)

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert not result.ok
    assert result.fields_ok
    assert not result.integrity_ok
    assert "merkle_root mismatch" in result.failure_reason


def test_real_manifest_ots_check_detects_missing_root_bin(tmp_path: Path) -> None:
    """OTS-anchor sub-check: missing root.bin yields a clear diagnostic."""
    events = [_make_event(i, capref_hash_hex="f" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    mpath = _write_real_manifest_with_ots(
        tmp_path, manifest, write_root_bin=False, write_ots=True
    )

    result = verify_real_manifest_file(mpath, check_ots_anchor=True)

    assert not result.ok
    assert result.fields_ok and result.integrity_ok
    assert result.ots_anchor.checked
    assert not result.ots_anchor.root_bin_present
    assert "root.bin not found" in result.failure_reason


def test_real_manifest_ots_check_detects_root_bin_mismatch(tmp_path: Path) -> None:
    """OTS-anchor sub-check: root.bin content not matching manifest fails."""
    events = [_make_event(i, capref_hash_hex="9" * 64) for i in (0, 1)]
    manifest = _build_real_v1_manifest(events)
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)
    # Overwrite root.bin with 32 wrong bytes
    (tmp_path / "root.bin").write_bytes(b"\x00" * 32)

    result = verify_real_manifest_file(mpath, check_ots_anchor=True)

    assert not result.ok
    assert result.ots_anchor.root_bin_present
    assert not result.ots_anchor.root_bin_matches_manifest
    assert "root.bin hex" in result.failure_reason
    assert "does not match" in result.failure_reason


def test_real_manifest_ots_check_detects_corrupt_ots_magic(tmp_path: Path) -> None:
    """OTS-anchor sub-check: wrong magic bytes in root.bin.ots fails."""
    events = [_make_event(i, capref_hash_hex="8" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    mpath = _write_real_manifest_with_ots(
        tmp_path, manifest, ots_magic=b"NOT-AN-OTS-FILE\x00"
    )

    result = verify_real_manifest_file(mpath, check_ots_anchor=True)

    assert not result.ok
    assert result.ots_anchor.root_bin_present
    assert result.ots_anchor.root_bin_matches_manifest
    assert result.ots_anchor.ots_present
    assert not result.ots_anchor.ots_magic_ok
    assert "OpenTimestamps magic" in result.failure_reason


def test_real_manifest_no_check_ots_anchor_skips_side_files(tmp_path: Path) -> None:
    """``check_ots_anchor=False`` skips the side-file check entirely."""
    events = [_make_event(i, capref_hash_hex="7" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    # Write only the manifest, no root.bin / .ots. Should still pass.
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert result.ok
    assert not result.ots_anchor.checked
    assert result.ots_anchor.ok  # vacuously True when not checked


def test_real_manifest_cli_real_flag_against_fixture(capsys) -> None:
    """CLI ``--real-manifest`` emits human output for the in-repo fixture."""
    fixture_dir = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "wat-real-manifest"
    )
    rc = verifier_main([str(fixture_dir / "manifest.json"), "--real-manifest"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "version:         wakir-wat-manifest/v1" in out
    assert "fields_ok:       True" in out
    assert "integrity_ok:    True" in out
    assert "ots_root_bin:    True" in out
    assert "ots_magic_ok:    True" in out


def test_real_manifest_cli_json_output_is_canonical(tmp_path: Path, capsys) -> None:
    """CLI ``--real-manifest --output json`` is sorted single-line JSON."""
    events = [_make_event(i, capref_hash_hex="6" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    rc = verifier_main(
        [str(mpath), "--real-manifest", "--output", "json"]
    )
    out = capsys.readouterr().out.strip()
    assert rc == 0
    # No newlines inside; sorted keys.
    assert "\n" not in out
    payload = json.loads(out)
    assert out == json.dumps(payload, sort_keys=True)
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    assert payload["ok"] is True
    assert payload["ots_anchor_ok"] is True


def test_real_manifest_no_check_ots_cli_flag_skips_side_files(
    tmp_path: Path, capsys
) -> None:
    """CLI ``--no-check-ots-anchor`` makes side-file absence non-fatal."""
    events = [_make_event(i, capref_hash_hex="5" * 64) for i in (0,)]
    manifest = _build_real_v1_manifest(events)
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    rc = verifier_main(
        [str(mpath), "--real-manifest", "--no-check-ots-anchor"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "ots_root_bin" not in out  # not displayed when not checked


def test_real_manifest_with_multi_cap_uses_strict_default(tmp_path: Path) -> None:
    """Real manifest carrying multi-cap sidecar runs strict-mode by default.

    Future v2 producer-code will emit ``multi_cap_events`` /
    ``multi_cap_summary``. The same Sprint-2 Tag-4 strict default
    governs the recompute on the real-manifest path.
    """
    events = [_make_event(i, capref_hash_hex="a" * 64) for i in (0, 1)]
    manifest = _build_real_v1_manifest(events)
    # Bolt on a multi-cap sidecar with a deliberately wrong caprefs_root.
    manifest["multi_cap_events"] = {
        "evt-0": {
            "caprefs_full": [
                "sha256:" + ("a" * 64),
                "sha256:" + ("b" * 64),
            ],
            "caprefs_root": "0" * 64,  # wrong
        }
    }
    manifest["multi_cap_summary"] = {
        "events_with_multi_cap": 1,
        "max_caprefs_in_any_event": 2,
        "distinct_capability_token_hashes_in_hour": 2,
    }
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    result = verify_real_manifest_file(mpath, check_ots_anchor=False)

    assert not result.ok
    assert result.multi_cap_root_status == "mismatch"
    assert "multi_cap_root" in result.failure_reason

    # Same input under lenient mode passes the multi-cap subcheck.
    lenient = verify_real_manifest_file(
        mpath, check_ots_anchor=False, strict_multi_cap_root=False
    )
    assert lenient.fields_ok and lenient.integrity_ok
    assert lenient.multi_cap_root_status == "deferred"


def test_real_manifest_audit_trail_entry_bridges_to_v2_shape(
    tmp_path: Path, capsys
) -> None:
    """``--real-manifest --output audit-trail-entry`` emits the eleven-field shape."""
    events = [_make_event(i, capref_hash_hex="3" * 64) for i in (0, 1)]
    manifest = _build_real_v1_manifest(events)
    mpath = _write_real_manifest_with_ots(tmp_path, manifest)

    rc = verifier_main(
        [str(mpath), "--real-manifest", "--output", "audit-trail-entry"]
    )
    out = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(out)
    # Same eleven keys as the v2-spec audit-trail-entry contract.
    assert set(payload.keys()) == {
        "kind",
        "schema_version",
        "identity",
        "manifest_version",
        "manifest_path",
        "hour_slot",
        "event_count",
        "anchor_root_hex",
        "branches",
        "ok",
        "failure_reason",
    }
    assert payload["kind"] == "wat-tv-pin-pack"
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    assert payload["manifest_version"] == "wakir-wat-manifest/v1"
    assert payload["event_count"] == 2
    assert payload["ok"] is True
    assert payload["branches"][0]["verdict"] == "verified"
