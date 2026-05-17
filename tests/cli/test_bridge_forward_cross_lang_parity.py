# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine bridge-forward
``ForwardFrame`` JCS canonicalisation surface (Tag-25 Mini-Welle).

The Python module under test
(:mod:`wirelang.cli.bridge_forward_canonical`) is Apache-2.0; this
test file is Apache-2.0 so downstream re-implementers can re-use the
same fixture vectors and the cross-lang contract. The Rust sibling
crate (``wirelang-rust/crates/persona-engine-bridge-forward``) is
Apache-2.0 and consumes the same authoritative
``tests/fixtures/bridge-forward-cross-lang/fixtures.json`` file.

Test taxonomy (12+ numbered cases; pytest parametrisation lifts the
total assertion count above 20)
-------------------------------------------------------------------

- T01 -- Constants pin: :data:`BRIDGE_FORWARD_FRAME_SCHEMA`,
  :data:`AGENT_TASK_ASSIGNED_SCHEMA`, :data:`HASH_PREFIX`,
  :data:`SHA256_HEX_LEN` and the size-limit constants match the
  documented Rust ``pub const`` items.
- T02 -- Empty-payload (f01) byte-pin via :func:`build_forward_frame`
  on hand-rolled :class:`ForwardFrameInput` (no fixture-file dep).
- T03 -- Fixture file structure pin: ``schema_version`` matches the
  forward-frame schema string, exactly 5 vectors present, names +
  input/expected key sets match the documented contract.
- T04 -- Cross-lang fixture per-vector pin (parametrised over the
  five fixtures): byte-for-byte parity with the JSON fixture file's
  pinned ``frame_jcs_bytes_b64`` / ``frame_jcs_bytes_len`` /
  ``frame_sha256_hex`` / ``frame_hash_prefixed`` / ``expected_subject``
  values. This is the core byte-parity test.
- T05 -- Subject regex parity: every fixture's ``expected_subject``
  matches the layer-0-transport regex and re-derives identically via
  :func:`build_subject`.
- T06 -- Inner envelope wire-shape: every emitted envelope dict has
  exactly the ten canonical keys (alphabetical), the constant
  ``schema`` / ``event_kind`` values, and a ``prompt_sha256``
  field that matches ``hashlib.sha256(prompt_payload.encode())``.
- T07 -- Frame wire-shape: ``to_wire_dict()`` returns exactly three
  alphabetical top-level keys (``envelope``, ``schema``, ``subject``).
- T08 -- Determinism: building the same fixture twice produces
  byte-identical canonical output and identical prefixed hashes.
- T09 -- :func:`serialize_and_hash` returns the same pair as the
  individual helpers (no double-canonicalisation drift).
- T10 -- :func:`build_subject` rejection set: bad env values,
  bad-shape persona slugs.
- T11 -- :func:`validate_forward_frame` accepts at the boundary
  (64-octet auftrag_id) and rejects one byte over.
- T12 -- :func:`validate_forward_frame` rejects an oversized
  prompt_payload (one byte over :data:`MAX_PROMPT_PAYLOAD_BYTES`).
- T13 -- The pre-existing :mod:`wirelang.cli.bridge_forward` CLI is
  NOT touched: the canonical sibling re-exports the same
  ``AuftragEnvelope`` class object (identity check) and the same
  ``MAX_*`` size constants (value pin).
- T14 -- Fixture file path resolves from the repo-root tests dir
  (parity with the Rust ``CARGO_MANIFEST_DIR`` walker).

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``serialize_forward_frame`` and Python
   :func:`serialize_forward_frame`).
2. Re-derive the fixture vectors using the helpers exposed by the
   Python module.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T04) fires on both sides -- that is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.cli.bridge_forward_canonical import (
    AGENT_TASK_ASSIGNED_SCHEMA,
    BRIDGE_FORWARD_FRAME_SCHEMA,
    HASH_PREFIX,
    MAX_AUFTRAG_ID_OCTETS,
    MAX_METADATA_BYTES,
    MAX_PROMPT_PAYLOAD_BYTES,
    SHA256_HEX_LEN,
    AuftragEnvelope,
    EnvelopeFormatError,
    ForwardFrame,
    ForwardFrameInput,
    SizeLimitError,
    build_forward_frame,
    build_subject,
    envelope_to_jcs_bytes,
    forward_frame_hash_prefixed,
    forward_frame_sha256_hex,
    serialize_and_hash,
    serialize_forward_frame,
    validate_envelope,
    validate_forward_frame,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "bridge-forward-cross-lang"
    / "fixtures.json"
)


@pytest.fixture(scope="module")
def fixtures_doc() -> Dict[str, Any]:
    """Load the authoritative cross-lang fixture file."""
    with _FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _fixture_names_in_order() -> List[str]:
    return [
        "f01-empty-payload",
        "f02-single-record",
        "f03-multi-record-batch",
        "f04-error-frame",
        "f05-large-payload",
    ]


def _input_from_fixture(fx: Dict[str, Any]) -> ForwardFrameInput:
    inp = fx["input"]
    return ForwardFrameInput(
        env=inp["env"],
        persona_slug=inp["persona_slug"],
        auftrag_id=inp["auftrag_id"],
        ts_utc=inp["ts_utc"],
        prompt_payload=inp["prompt_payload"],
        org_id=inp["org_id"],
        source=inp["source"],
        metadata=dict(inp["metadata"]),
    )


def _find_fixture(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    for fx in doc["fixtures"]:
        if fx["name"] == name:
            return fx
    raise KeyError(f"fixture {name!r} not in fixture file")


# ---------------------------------------------------------------------
# T01 -- Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_pin():
    assert BRIDGE_FORWARD_FRAME_SCHEMA == "wakir.bridge.forward-frame/1"
    assert AGENT_TASK_ASSIGNED_SCHEMA == "wakir.agent.task-assigned/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64
    assert MAX_PROMPT_PAYLOAD_BYTES == 256 * 1024
    assert MAX_AUFTRAG_ID_OCTETS == 64
    assert MAX_METADATA_BYTES == 8 * 1024


# ---------------------------------------------------------------------
# T02 -- Empty-payload (f01) byte-pin via hand-rolled input
# ---------------------------------------------------------------------


def test_t02_empty_payload_explicit_byte_pin():
    """Re-derive the f01 vector independently of the fixture file."""
    inp = ForwardFrameInput(
        env="dev",
        persona_slug="tomas",
        auftrag_id="empty-1",
        ts_utc="2026-05-17T00:00:00Z",
        prompt_payload="",
    )
    frame = build_forward_frame(inp)
    canonical, prefixed = serialize_and_hash(frame)
    hex_only = forward_frame_sha256_hex(frame)
    assert frame.subject == "wakir.dev.agent.agent.task.assigned.tomas"
    assert len(canonical) == 422, "f01 canonical bytes length pinned"
    assert (
        hex_only
        == "f21370daf9ff92f52a2d56e29869fa922220907e03fd44467b6c3bedf43fc24c"
    )
    assert (
        prefixed
        == "sha256:f21370daf9ff92f52a2d56e29869fa922220907e03fd44467b6c3bedf43fc24c"
    )


# ---------------------------------------------------------------------
# T03 -- Fixture file structure pin
# ---------------------------------------------------------------------


def test_t03_fixture_file_structure_pin(fixtures_doc):
    assert fixtures_doc["schema_version"] == BRIDGE_FORWARD_FRAME_SCHEMA
    assert isinstance(fixtures_doc["fixtures"], list)
    names = [fx["name"] for fx in fixtures_doc["fixtures"]]
    assert names == _fixture_names_in_order()
    for fx in fixtures_doc["fixtures"]:
        assert "comment" in fx
        assert "expected_subject" in fx
        assert "input" in fx
        for k in (
            "env",
            "persona_slug",
            "auftrag_id",
            "ts_utc",
            "prompt_payload",
            "org_id",
            "source",
            "metadata",
        ):
            assert k in fx["input"], f"fixture {fx['name']} input missing {k}"
        for k in (
            "frame_jcs_bytes_b64",
            "frame_jcs_bytes_len",
            "frame_sha256_hex",
            "frame_hash_prefixed",
        ):
            assert k in fx["expected"], f"fixture {fx['name']} expected missing {k}"


# ---------------------------------------------------------------------
# T04 -- Cross-lang fixture per-vector pin (parametrised)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", _fixture_names_in_order())
def test_t04_per_fixture_byte_level_pin(fixtures_doc, fixture_name):
    fx = _find_fixture(fixtures_doc, fixture_name)
    inp = _input_from_fixture(fx)
    frame = build_forward_frame(inp)

    canonical = serialize_forward_frame(frame)
    hex_only = forward_frame_sha256_hex(frame)
    prefixed = forward_frame_hash_prefixed(frame)

    exp = fx["expected"]
    exp_bytes = base64.b64decode(exp["frame_jcs_bytes_b64"])
    exp_len = int(exp["frame_jcs_bytes_len"])
    exp_sha = exp["frame_sha256_hex"]
    exp_pref = exp["frame_hash_prefixed"]

    # Subject parity.
    assert frame.subject == fx["expected_subject"], (
        f"{fixture_name}: subject drifted vs fixture-pinned value"
    )
    # Length parity.
    assert len(canonical) == exp_len, (
        f"{fixture_name}: canonical-bytes length {len(canonical)} drifted vs pin {exp_len}"
    )
    # Bytes parity (the load-bearing check).
    assert canonical == exp_bytes, f"{fixture_name}: canonical-bytes drifted vs pin"
    # Hash parity.
    assert hex_only == exp_sha, f"{fixture_name}: bare-hex SHA-256 drifted vs pin"
    assert prefixed == exp_pref, f"{fixture_name}: prefixed SHA-256 drifted vs pin"

    # Sanity: prefixed-hash shape.
    assert prefixed.startswith(HASH_PREFIX)
    assert len(prefixed) == len(HASH_PREFIX) + SHA256_HEX_LEN


# ---------------------------------------------------------------------
# T05 -- Subject regex parity across all fixtures
# ---------------------------------------------------------------------


def test_t05_subject_regex_parity_across_fixtures(fixtures_doc):
    import re

    schema_pattern = re.compile(
        r"^wakir\.(dev|staging|prod)\."
        r"[a-z][a-z0-9_-]*\."
        r"[a-z][a-z0-9_.-]*"
        r"(\.[a-zA-Z0-9_.-]+)?$"
    )
    for fx in fixtures_doc["fixtures"]:
        subject = fx["expected_subject"]
        assert schema_pattern.match(subject), (
            f"{fx['name']}: subject {subject!r} fails layer-0 regex"
        )
        # Re-derive via build_subject; pin parity.
        derived = build_subject(fx["input"]["env"], fx["input"]["persona_slug"])
        assert derived == subject, (
            f"{fx['name']}: build_subject derived {derived!r} != pin {subject!r}"
        )


# ---------------------------------------------------------------------
# T06 -- Inner envelope wire-shape (ten alphabetical canonical keys)
# ---------------------------------------------------------------------


def test_t06_inner_envelope_wire_shape_and_prompt_sha256():
    env = AuftragEnvelope(
        org_id="acme",
        persona_id="tomas",
        auftrag_id="x",
        ts_utc="2026-05-17T00:00:00Z",
        source="mira-sandbox",
        prompt_payload="hello",
    )
    d = env.to_dict()
    # The dict carries the constant schema + event_kind.
    assert d["schema"] == AGENT_TASK_ASSIGNED_SCHEMA
    assert d["event_kind"] == "agent.task.assigned"
    # All ten canonical keys present (alphabetical).
    assert sorted(d.keys()) == [
        "auftrag_id",
        "event_kind",
        "metadata",
        "org_id",
        "persona_id",
        "prompt_payload",
        "prompt_sha256",
        "schema",
        "source",
        "ts_utc",
    ]
    # prompt_sha256 matches direct hashlib digest.
    expected_hash = f"sha256:{hashlib.sha256(b'hello').hexdigest()}"
    assert d["prompt_sha256"] == expected_hash
    # JCS canonicalisation produces a sort_keys-sorted serialisation.
    canonical = envelope_to_jcs_bytes(d)
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed == d


# ---------------------------------------------------------------------
# T07 -- ForwardFrame wire-shape (three alphabetical top-level keys)
# ---------------------------------------------------------------------


def test_t07_frame_wire_shape_has_three_alphabetical_keys():
    inp = ForwardFrameInput(
        env="dev",
        persona_slug="reza",
        auftrag_id="x",
        ts_utc="2026-05-17T00:00:00Z",
        prompt_payload="hi",
    )
    frame = build_forward_frame(inp)
    d = frame.to_wire_dict()
    assert sorted(d.keys()) == ["envelope", "schema", "subject"]
    assert d["schema"] == BRIDGE_FORWARD_FRAME_SCHEMA
    assert d["subject"] == "wakir.dev.agent.agent.task.assigned.reza"


# ---------------------------------------------------------------------
# T08 -- Determinism across repeats
# ---------------------------------------------------------------------


def test_t08_determinism_across_repeats(fixtures_doc):
    for fx in fixtures_doc["fixtures"]:
        inp = _input_from_fixture(fx)
        f1 = build_forward_frame(inp)
        f2 = build_forward_frame(inp)
        b1 = serialize_forward_frame(f1)
        b2 = serialize_forward_frame(f2)
        assert b1 == b2, f"{fx['name']}: determinism breach (bytes)"
        h1 = forward_frame_hash_prefixed(f1)
        h2 = forward_frame_hash_prefixed(f2)
        assert h1 == h2, f"{fx['name']}: determinism breach (hash)"


# ---------------------------------------------------------------------
# T09 -- serialize_and_hash matches individual helpers
# ---------------------------------------------------------------------


def test_t09_serialize_and_hash_matches_individual_helpers(fixtures_doc):
    for fx in fixtures_doc["fixtures"]:
        inp = _input_from_fixture(fx)
        frame = build_forward_frame(inp)
        a_bytes = serialize_forward_frame(frame)
        a_hash = forward_frame_hash_prefixed(frame)
        b_bytes, b_hash = serialize_and_hash(frame)
        assert a_bytes == b_bytes, f"{fx['name']}: serialize_and_hash bytes drift"
        assert a_hash == b_hash, f"{fx['name']}: serialize_and_hash hash drift"


# ---------------------------------------------------------------------
# T10 -- build_subject rejection set
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,persona,reason",
    [
        ("production", "tomas", "bad-env"),
        ("test", "tomas", "bad-env"),
        ("DEV", "tomas", "bad-env (case-strict)"),
        ("dev", "Tomas", "bad-slug (uppercase)"),
        ("dev", "1tomas", "bad-slug (leading digit)"),
        ("dev", "to.mas", "bad-slug (dot)"),
        ("dev", "", "bad-slug (empty)"),
        ("dev", "-tomas", "bad-slug (leading dash)"),
    ],
)
def test_t10_build_subject_rejection_set(env, persona, reason):
    with pytest.raises(EnvelopeFormatError):
        build_subject(env, persona)


# ---------------------------------------------------------------------
# T11 -- validate_forward_frame: auftrag_id boundary + over-cap
# ---------------------------------------------------------------------


def test_t11_validate_forward_frame_auftrag_id_boundary_and_over(fixtures_doc):
    # f04 carries a 64-octet auftrag_id (exactly at the boundary).
    fx = _find_fixture(fixtures_doc, "f04-error-frame")
    inp = _input_from_fixture(fx)
    assert len(inp.auftrag_id.encode("utf-8")) == MAX_AUFTRAG_ID_OCTETS
    frame = build_forward_frame(inp)
    # Must NOT raise at the boundary.
    validate_forward_frame(frame)

    # One byte over -> rejection.
    over = ForwardFrameInput(
        env=inp.env,
        persona_slug=inp.persona_slug,
        auftrag_id=inp.auftrag_id + "z",
        ts_utc=inp.ts_utc,
        prompt_payload=inp.prompt_payload,
        org_id=inp.org_id,
        source=inp.source,
        metadata=dict(inp.metadata),
    )
    over_frame = build_forward_frame(over)
    with pytest.raises(SizeLimitError):
        validate_forward_frame(over_frame)


# ---------------------------------------------------------------------
# T12 -- validate_forward_frame: oversized prompt_payload
# ---------------------------------------------------------------------


def test_t12_validate_forward_frame_oversized_prompt_payload():
    inp = ForwardFrameInput(
        env="dev",
        persona_slug="kai",
        auftrag_id="oversize-prompt",
        ts_utc="2026-05-17T00:00:00Z",
        prompt_payload="x" * (MAX_PROMPT_PAYLOAD_BYTES + 1),
    )
    frame = build_forward_frame(inp)
    with pytest.raises(SizeLimitError):
        validate_forward_frame(frame)

    # Boundary case: exactly MAX_PROMPT_PAYLOAD_BYTES must NOT raise.
    inp_at = ForwardFrameInput(
        env="dev",
        persona_slug="kai",
        auftrag_id="boundary-prompt",
        ts_utc="2026-05-17T00:00:00Z",
        prompt_payload="x" * MAX_PROMPT_PAYLOAD_BYTES,
    )
    frame_at = build_forward_frame(inp_at)
    validate_forward_frame(frame_at)  # must not raise


# ---------------------------------------------------------------------
# T13 -- Sibling module does NOT shadow the pre-existing CLI
# ---------------------------------------------------------------------


def test_t13_sibling_module_does_not_shadow_existing_cli():
    """The Tag-25 sibling re-exports the same class object / constants
    from the Sprint-10 Tag-6 module without touching that module."""
    from wirelang.cli import bridge_forward as legacy

    # Identity-preserving re-export of the AuftragEnvelope class.
    assert AuftragEnvelope is legacy.AuftragEnvelope
    # Identity-preserving re-export of the error classes.
    assert EnvelopeFormatError is legacy.EnvelopeFormatError
    assert SizeLimitError is legacy.SizeLimitError
    # Value-pin of the size constants.
    assert MAX_PROMPT_PAYLOAD_BYTES == legacy.MAX_PROMPT_PAYLOAD_BYTES
    assert MAX_AUFTRAG_ID_OCTETS == legacy.MAX_AUFTRAG_ID_OCTETS
    assert MAX_METADATA_BYTES == legacy.MAX_METADATA_BYTES
    # Value-pin of the schema constant.
    assert AGENT_TASK_ASSIGNED_SCHEMA == legacy.AGENT_TASK_ASSIGNED_SCHEMA
    # build_subject / envelope_to_jcs_bytes / validate_envelope are
    # the same callables.
    assert build_subject is legacy.build_subject
    assert envelope_to_jcs_bytes is legacy.envelope_to_jcs_bytes
    assert validate_envelope is legacy.validate_envelope


# ---------------------------------------------------------------------
# T14 -- Fixture file path resolution
# ---------------------------------------------------------------------


def test_t14_fixture_file_path_resolves_to_repo_root():
    """The fixture file path must exist and be the repo-root file
    that the Rust ``CARGO_MANIFEST_DIR`` walker also resolves."""
    assert _FIXTURE_PATH.exists(), f"fixture file missing: {_FIXTURE_PATH}"
    # Path shape: <repo>/tests/fixtures/bridge-forward-cross-lang/fixtures.json
    parts = list(_FIXTURE_PATH.parts)
    tail = parts[-3:]
    assert tail == ["fixtures", "bridge-forward-cross-lang", "fixtures.json"]


# ---------------------------------------------------------------------
# T15 -- Forward-frame canonical bytes round-trip through json.loads
#        to a sort_keys-sorted dict.
# ---------------------------------------------------------------------


def test_t15_canonical_bytes_roundtrip_json_loads(fixtures_doc):
    fx = _find_fixture(fixtures_doc, "f02-single-record")
    inp = _input_from_fixture(fx)
    frame = build_forward_frame(inp)
    canonical = serialize_forward_frame(frame)
    parsed = json.loads(canonical.decode("utf-8"))
    assert parsed["schema"] == BRIDGE_FORWARD_FRAME_SCHEMA
    assert parsed["subject"] == fx["expected_subject"]
    assert parsed["envelope"]["schema"] == AGENT_TASK_ASSIGNED_SCHEMA
    assert parsed["envelope"]["event_kind"] == "agent.task.assigned"
    # The inner envelope carries the SHA-256 of the prompt-payload.
    expected_prompt_hash = (
        f"sha256:{hashlib.sha256(inp.prompt_payload.encode('utf-8')).hexdigest()}"
    )
    assert parsed["envelope"]["prompt_sha256"] == expected_prompt_hash
