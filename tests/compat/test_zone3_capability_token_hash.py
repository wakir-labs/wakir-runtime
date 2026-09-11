# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-Review Zone 3 pin: ``capability_token_hash`` on the proof path.

Finding (protocol W4, Reza §6.5): the leaf-hash primitive and the
aggregator's B1 shape check accept ``capability_token_hash: ""``
(pilot-phase sentinel written by ``wat.anchor.bridge_audit_writer``),
while the canonical manifest schema ``wakir-wat-manifest-v1.json``
requires ``^[0-9a-f]{64}$`` for every ``events[]`` / ``leaves[]``
entry. A manifest holding a non-capability pilot event is therefore
schema-invalid today.

Decision (ADR-0072 W4, runtime side): **the schema is right.** A hash
field inside an anchored manifest is a fixed-width digest; the
pilot-phase empty string becomes the all-zero digest (``"0" * 64``,
which ``scripts/demo-proof.sh`` already emits). The leaf primitive
stays permissive (it hashes whatever JCS tuple it is given; the empty
string remains covered by ``tests/fixtures/jcs-leaf-vectors``). The
producer change (``bridge_audit_writer`` sentinel, cross-lang fixtures,
Rust twin) alters pilot leaf hashes and is a tracked follow-up of
PR #526 — until it lands, this module pins the *current* state so that
whichever side moves first has to update the pin consciously.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
agg = pytest.importorskip("wat.merkle.aggregator")
agg_cli = pytest.importorskip("wat.cmd.aggregator_cli")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO_ROOT / "wirelang" / "schemas" / "wakir-wat-manifest-v1.json").read_text(encoding="utf-8"))
ZERO_SENTINEL = "0" * 64


def _event(cap: str) -> dict:
    return {
        "event_id": "a" * 32,
        "time": "2026-05-17T12:00:00Z",
        "payload_hash": "1" * 64,
        "capability_token_hash": cap,
    }


def _manifest(cap: str) -> dict:
    return agg_cli._build_manifest_object(hour_slot="2026-05-17T12", events=[_event(cap)], build_time="2026-09-11T00:00:00Z")


def _errors(instance) -> list[str]:
    validator = jsonschema.validators.validator_for(SCHEMA)(SCHEMA)
    return [e.message for e in validator.iter_errors(instance)]


def test_schema_requires_64_hex_capability_token_hash():
    pattern = SCHEMA["properties"]["events"]["items"]["properties"]["capability_token_hash"]["pattern"]
    assert pattern == "^[0-9a-f]{64}$"


def test_manifest_with_zero_sentinel_is_schema_valid():
    assert _errors(_manifest(ZERO_SENTINEL)) == []


def test_manifest_with_empty_sentinel_is_schema_invalid_today():
    """Pinned inconsistency: flips to valid only if the protocol schema is
    loosened (not the chosen direction) — then this test must be revisited."""
    errors = _errors(_manifest(""))
    assert errors, "schema now accepts an empty capability_token_hash; Zone-3 decision was the opposite"
    assert any("does not match" in e for e in errors)


def test_leaf_primitive_still_accepts_empty_string():
    """The hash primitive is not where the rule lives; jcs-leaf-vectors/vector-3 covers the empty tuple."""
    digest = agg.compute_leaf_hash(event_id="e", time="2026-05-17T12:00:00Z", payload_hash="1" * 64, capability_token_hash="")
    assert len(digest) == 32
    assert digest != agg.compute_leaf_hash(event_id="e", time="2026-05-17T12:00:00Z", payload_hash="1" * 64, capability_token_hash=ZERO_SENTINEL)


def test_aggregator_shape_check_still_accepts_empty_string_today():
    """Producer side of the pin: once bridge_audit_writer emits the zero
    sentinel, tighten ``_validate_events`` to the schema pattern and flip
    this assertion to ``pytest.raises(agg_cli.ValidationError)``."""
    assert agg_cli._validate_events([_event("")]) == [_event("")]


def test_bridge_audit_writer_still_emits_empty_sentinel_today():
    """Documents the producer that has to change (follow-up of PR #526)."""
    writer = pytest.importorskip("wat.anchor.bridge_audit_writer")
    record = writer._leaf_record if hasattr(writer, "_leaf_record") else None
    src = (REPO_ROOT / "wat" / "anchor" / "bridge_audit_writer.py").read_text(encoding="utf-8")
    assert 'capability_token_hash="",' in src, (
        "bridge_audit_writer no longer emits the empty sentinel — good: now tighten "
        "aggregator_cli._validate_events and update this Zone-3 pin module"
    )
    del record


def test_proof_path_vectors_use_only_64_hex():
    vector_dir = REPO_ROOT / "tests" / "fixtures" / "proof-path-vectors"
    vectors = sorted(vector_dir.glob("vector-*.json"))
    assert vectors, "runtime mirror of the protocol proof-path vectors is missing"
    for path in vectors:
        vec = json.loads(path.read_text(encoding="utf-8"))
        for leaf in vec["leaves"]:
            assert len(leaf["capability_token_hash"]) == 64, f"{path.name}: {leaf['event_id']}"
            assert len(leaf["payload_hash"]) == 64
