# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-Review Zone 3 pin: ``capability_token_hash`` on the proof path.

Finding (protocol W4, the protocol zone §6.5): the leaf-hash primitive and the
aggregator's B1 shape check accept ``capability_token_hash: ""``
(pilot-phase sentinel written by ``wat.anchor.bridge_audit_writer``),
while the canonical manifest schema ``wakir-wat-manifest-v1.json``
requires ``^[0-9a-f]{64}$`` for every ``events[]`` / ``leaves[]``
entry. A manifest holding a non-capability pilot event is therefore
schema-invalid today.

Decision (ADR-0072 W4, runtime side): **the schema is right.** A hash
field inside an anchored manifest is a fixed-width digest; the
pilot-phase empty string becomes the all-zero digest (``"0" * 64``).
The leaf primitive stays permissive (it hashes whatever JCS tuple it
is given; the empty string remains covered by
``tests/fixtures/jcs-leaf-vectors``).

**The follow-up has landed** (2026-09-14, finding R5 of the external
re-review). Both halves moved in one change:

- Producer: ``wat.anchor.bridge_audit_writer`` no longer hardcodes the
  empty string. It takes a ``capability_token_hash`` argument and
  defaults to :data:`~wat.anchor.bridge_audit_writer.NO_CAPABILITY_DIGEST`
  (``"0" * 64``).
- Consumer: ``wat.cmd.aggregator_cli._validate_events`` enforces the
  schema's ``^[0-9a-f]{64}$`` on the digest fields, so a manifest that
  could not be published can no longer be built.

What made this visible: the demo used to hide the mismatch. The writer
emitted ``""`` into the spool, and step 3 of ``scripts/demo-proof.sh``
replaced it with the envelope's ``"0" * 64`` before hashing — the
manifest satisfied the schema while describing a tuple the spool never
held. With that repair removed, ``cross-repo-compat.yml`` went red and
named this exact pin.

This module now pins the *post*-follow-up state.
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


def test_aggregator_shape_check_rejects_the_empty_string():
    """Consumer half of the follow-up: the aggregator refuses to build a
    manifest the schema would reject, and says so with the event index."""
    with pytest.raises(agg_cli.ValidationError) as excinfo:
        agg_cli._validate_events([_event("")])
    assert "capability_token_hash" in str(excinfo.value)
    assert "^[0-9a-f]{64}$" in str(excinfo.value)


def test_aggregator_shape_check_accepts_the_zero_digest():
    """Positive control for the tightened check."""
    assert agg_cli._validate_events([_event(ZERO_SENTINEL)]) == [_event(ZERO_SENTINEL)]


@pytest.mark.parametrize("bad", ["0" * 63, "0" * 65, "G" * 64, "0" * 63 + "A", ""])
def test_aggregator_shape_check_rejects_non_hex64_capability(bad: str):
    with pytest.raises(agg_cli.ValidationError):
        agg_cli._validate_events([_event(bad)])


def test_bridge_audit_writer_defaults_to_the_zero_digest():
    """Producer half of the follow-up.

    Asserted against the module's behaviour, not against a source-code
    substring, so a refactor that keeps the contract does not fail
    here.
    """
    writer = pytest.importorskip("wat.anchor.bridge_audit_writer")
    assert writer.NO_CAPABILITY_DIGEST == ZERO_SENTINEL
    leaf = writer._build_leaf_record(
        persona_id="demo",
        action_type="demo-proof",
        event_time="2026-05-17T12:00:00Z",
        payload_hash="1" * 64,
        metadata={},
    )
    assert leaf.capability_token_hash == ZERO_SENTINEL
    assert _errors(_manifest(leaf.capability_token_hash)) == []


def test_bridge_audit_writer_forwards_a_real_capability_digest():
    """The other half of the producer defect: the writer used to have no
    way to record the capability it was auditing at all."""
    writer = pytest.importorskip("wat.anchor.bridge_audit_writer")
    leaf = writer._build_leaf_record(
        persona_id="demo",
        action_type="demo-proof",
        event_time="2026-05-17T12:00:00Z",
        payload_hash="1" * 64,
        metadata={},
        capability_token_hash="a" * 64,
    )
    assert leaf.capability_token_hash == "a" * 64


def test_proof_path_vectors_use_only_64_hex():
    vector_dir = REPO_ROOT / "tests" / "fixtures" / "proof-path-vectors"
    vectors = sorted(vector_dir.glob("vector-*.json"))
    assert vectors, "runtime mirror of the protocol proof-path vectors is missing"
    for path in vectors:
        vec = json.loads(path.read_text(encoding="utf-8"))
        for leaf in vec["leaves"]:
            assert len(leaf["capability_token_hash"]) == 64, f"{path.name}: {leaf['event_id']}"
            assert len(leaf["payload_hash"]) == 64
