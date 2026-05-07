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
    main as verifier_main,
    verify_manifest_v2_file,
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


def test_v2_manifest_multi_event_passes_lenient_default(tmp_path: Path) -> None:
    """v2 with two multi-cap events validates in lenient (default) mode.

    Lenient mode skips the caprefs_root recompute and reports
    ``deferred`` status — that is the OQ-1-pending posture per
    docs/wat-manifest-v2-spec.md §8.
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
    """A tampered ``caprefs_root`` is caught only in strict mode."""
    events = [_make_event(1, capref_hash_hex="a" * 64)]
    manifest = _build_v2_manifest(
        events,
        multi_cap={"evt-1": [_CAPREF_1, _CAPREF_2]},
    )
    # Flip caprefs_root to a syntactically valid but wrong hash.
    manifest["multi_cap_events"]["evt-1"]["caprefs_root"] = "1" * 64
    path = _write_manifest(tmp_path, manifest)

    # Lenient: passes (deferred). This is the explicit OQ-1 trade-off.
    lenient = verify_manifest_v2_file(path)
    assert lenient.ok
    assert lenient.multi_cap_root_status == "deferred"

    # Strict: fails.
    strict = verify_manifest_v2_file(path, strict_multi_cap_root=True)
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
    """``--output json`` emits a JSON object on stdout, exit-code 0."""
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
    assert payload["multi_cap_root_status"] == "deferred"
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"
    # Single-line: exactly one trailing newline from print, no embedded newlines.
    assert "\n" not in out


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
