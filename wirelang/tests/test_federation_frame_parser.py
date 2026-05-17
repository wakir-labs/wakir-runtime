# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for :mod:`wirelang.federation.federation_frame` — Python pendant
of the Rust crate ``persona-engine-federation-frame-parser`` (Phase-3a
Item 9, PR #148).

Test discovery note
-------------------

The Wakir CI lane (``.github/workflows/tests.yml``) invokes pytest as
``python -m pytest wirelang/`` — so the canonical home for the suite
is here under ``wirelang/tests/``. The Tag-14 Mini-Welle Auftrag
*literal* path was ``tests/federation/test_federation_frame_parser.py``;
a thin re-export module lives at that path and re-exports everything
from this file (so a developer running ``pytest tests/`` from the
repo root also hits the same 17 tests). The auftrag-literal path is
the secondary surface; this file is the primary one.

Test coverage (17 tests; >= 10 required by Auftrag)
---------------------------------------------------

Round-trip per payload kind (4):
  - test_roundtrip_task_assigned_minimal
  - test_roundtrip_task_output
  - test_roundtrip_multi_org_attestation
  - test_roundtrip_spiffe_bundle_sync

Optional-field surface (2):
  - test_roundtrip_with_anchor_ref_and_signature
  - test_signing_payload_bytes_omits_anchor_and_signature

Malformed-frame rejection (3):
  - test_parse_rejects_bad_json
  - test_parse_rejects_bad_utf8
  - test_parse_rejects_payload_data_not_object

Version skew + schema validation (4):
  - test_parse_rejects_unsupported_version
  - test_parse_rejects_unknown_envelope_schema
  - test_parse_rejects_payload_kind_schema_mismatch
  - test_parse_rejects_unknown_payload_kind

Field-shape validators (3):
  - test_parse_rejects_bad_frame_id_shape
  - test_parse_rejects_bad_timestamp_shape
  - test_parse_rejects_empty_runtime_id

Cross-lang byte parity (1, parametrised over 5 fixtures):
  - test_cross_lang_byte_pin_matches_fixture
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from wirelang.federation.federation_frame import (
    ANCHOR_REF_PREFIX,
    FRAME_ENVELOPE_SCHEMA,
    FRAME_ENVELOPE_VERSION,
    FRAME_ID_PREFIX,
    PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION,
    PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC,
    PAYLOAD_SCHEMA_TASK_ASSIGNED,
    PAYLOAD_SCHEMA_TASK_OUTPUT,
    SHA256_HEX_LEN,
    FederationFrame,
    FederationPayload,
    FrameHeader,
    ParseError,
    compute_frame_id,
    parse_frame,
    serialize_frame,
    signing_payload_bytes,
)
from wirelang.identity._jcs_pure import canonicalize as _jcs_canonicalize


# ---------------------------------------------------------------------
# Cross-lang fixture file (the single source of truth for byte pins).
# ---------------------------------------------------------------------

# The fixture file is committed at the auftrag-literal path; we resolve
# it from this test file's location to keep the suite robust against
# the cwd at pytest invocation time.
_REPO_ROOT = Path(__file__).resolve().parents[2]
CROSS_LANG_PIN_FIXTURE_PATH = (
    _REPO_ROOT
    / "tests"
    / "federation"
    / "fixtures"
    / "federation_frame_cross_lang_pins.json"
)


def _load_pin_fixtures() -> list[dict]:
    """Load the cross-lang pin fixture set as a list of fixture dicts."""
    assert CROSS_LANG_PIN_FIXTURE_PATH.exists(), (
        f"Cross-lang pin fixture missing at {CROSS_LANG_PIN_FIXTURE_PATH}. "
        f"This file is the byte-level contract anchor for "
        f"persona-engine-federation-frame-parser (Rust crate) <-> "
        f"wirelang.federation.federation_frame (Python module). It MUST "
        f"exist; if you intentionally regenerated it, see the docstring "
        f"of `federation_frame.py` for the regeneration procedure."
    )
    raw = json.loads(CROSS_LANG_PIN_FIXTURE_PATH.read_text())
    assert raw["fixture_set_version"] == 1, (
        "Cross-lang fixture-set version drift; the Rust cross-lang test "
        "expects fixture_set_version == 1."
    )
    return raw["fixtures"]


def _frame_from_fixture_input(input_obj: dict) -> FederationFrame:
    """Construct a :class:`FederationFrame` from a fixture-file `input` dict."""
    header = FrameHeader(**input_obj["header"])
    payload = FederationPayload(
        kind=input_obj["payload_kind"],
        data=dict(input_obj["payload_data"]),
    )
    return FederationFrame(
        header=header,
        payload=payload,
        anchor_ref=input_obj.get("anchor_ref"),
        signature=input_obj.get("signature"),
    )


# ---------------------------------------------------------------------
# Local fixture builders for the in-suite round-trip tests.
# ---------------------------------------------------------------------


def _header_task_assigned() -> FrameHeader:
    return FrameHeader(
        frame_id=compute_frame_id(b"sprint-tag-14-mini/task-assigned/reza"),
        schema=FRAME_ENVELOPE_SCHEMA,
        source_runtime="mira-sandbox",
        target_runtime="wakir-runtime",
        ts_utc="2026-05-17T08:00:00Z",
        version=FRAME_ENVELOPE_VERSION,
    )


def _payload_task_assigned_data() -> dict:
    return {
        "auftrag_id": "sprint-tag-14-mini",
        "event_kind": "agent.task.assigned",
        "org_id": "acme",
        "persona_id": "reza",
        "prompt_payload": "Build the Python federation-frame parser.",
        "prompt_sha256": f"sha256:{'a' * 64}",
        "source": "mira-sandbox",
        "ts_utc": "2026-05-17T08:00:00Z",
    }


def _payload_task_output_data() -> dict:
    return {
        "auftrag_id": "sprint-tag-14-mini",
        "event_kind": "agent.task.completed",
        "persona_id": "reza",
        "reply_text": "PR opened; CI green.",
        "ts_utc": "2026-05-17T09:00:00Z",
    }


def _payload_multi_org_attestation_data() -> dict:
    return {
        "route_id": "did:web:acme.example.org#federation-route-1",
        "peer_trust_domain": "globex.example.org",
        "peer_audit_anchor_did": "did:web:globex.example.org",
        "peer_wat_anchor_manifest_id": f"wat-manifest:{'1' * 40}",
        "is_mock": False,
    }


def _payload_spiffe_bundle_sync_data() -> dict:
    return {
        "peer_trust_domain": "globex.example.org",
        "peer_trust_bundle_url": "https://globex.example.org/.well-known/spire-bundle",
        "bundle_sha256": f"sha256:{'b' * 64}",
        "freshness_ts_utc": "2026-05-17T07:00:00Z",
    }


# ---------------------------------------------------------------------
# 1..4 — Round-trip per payload kind.
# ---------------------------------------------------------------------


def test_roundtrip_task_assigned_minimal():
    frame = FederationFrame(
        header=_header_task_assigned(),
        payload=FederationPayload.task_assigned(_payload_task_assigned_data()),
    )
    by = serialize_frame(frame)
    parsed = parse_frame(by)
    assert parsed == frame

    # Idempotent: serialise -> parse -> serialise gives identical bytes.
    by2 = serialize_frame(parsed)
    assert by == by2


def test_roundtrip_task_output():
    header = FrameHeader(
        frame_id=compute_frame_id(b"sprint-tag-14-mini/task-output/reza"),
        schema=FRAME_ENVELOPE_SCHEMA,
        source_runtime="wakir-runtime",
        target_runtime="mira-sandbox",
        ts_utc="2026-05-17T09:00:00Z",
        version=FRAME_ENVELOPE_VERSION,
    )
    frame = FederationFrame(
        header=header,
        payload=FederationPayload.task_output(_payload_task_output_data()),
    )
    by = serialize_frame(frame)
    parsed = parse_frame(by)
    assert parsed == frame


def test_roundtrip_multi_org_attestation():
    header = FrameHeader(
        frame_id=compute_frame_id(
            b"sprint-tag-14-mini/multi-org-attestation/acme-x-globex"
        ),
        schema=FRAME_ENVELOPE_SCHEMA,
        source_runtime="acme/wakir-runtime",
        target_runtime="globex/wakir-runtime",
        ts_utc="2026-05-17T08:00:00Z",
        version=FRAME_ENVELOPE_VERSION,
    )
    frame = FederationFrame(
        header=header,
        payload=FederationPayload.multi_org_attestation(
            _payload_multi_org_attestation_data()
        ),
    )
    by = serialize_frame(frame)
    parsed = parse_frame(by)
    assert parsed == frame


def test_roundtrip_spiffe_bundle_sync():
    header = FrameHeader(
        frame_id=compute_frame_id(
            b"sprint-tag-14-mini/spiffe-bundle-sync/globex"
        ),
        schema=FRAME_ENVELOPE_SCHEMA,
        source_runtime="acme/wakir-runtime",
        target_runtime="globex/wakir-runtime",
        ts_utc="2026-05-17T08:00:00Z",
        version=FRAME_ENVELOPE_VERSION,
    )
    frame = FederationFrame(
        header=header,
        payload=FederationPayload.spiffe_bundle_sync(
            _payload_spiffe_bundle_sync_data()
        ),
    )
    by = serialize_frame(frame)
    parsed = parse_frame(by)
    assert parsed == frame


# ---------------------------------------------------------------------
# 5..6 — Optional-field surface.
# ---------------------------------------------------------------------


def test_roundtrip_with_anchor_ref_and_signature():
    frame = FederationFrame(
        header=_header_task_assigned(),
        payload=FederationPayload.task_assigned(_payload_task_assigned_data()),
        anchor_ref=f"{ANCHOR_REF_PREFIX}{'c' * 64}",
        signature="d" * 128,
    )
    by = serialize_frame(frame)
    parsed = parse_frame(by)
    assert parsed == frame

    # JCS key-order: anchor_ref sorts BEFORE header lexically; when
    # present the bytes start with `{"anchor_ref":"wat:` rather than
    # with `{"header":...`. Cross-lang anchor for the Rust crate's
    # equivalent assertion in `tests/federation_frame_parser_smoke_test.rs::
    # cross_lang_fixture_byte_pin_multi_org_attestation`.
    text = by.decode("utf-8")
    assert text.startswith(f'{{"anchor_ref":"{ANCHOR_REF_PREFIX}'), text[:80]


def test_signing_payload_bytes_omits_anchor_and_signature():
    frame_a = FederationFrame(
        header=_header_task_assigned(),
        payload=FederationPayload.task_assigned(_payload_task_assigned_data()),
        anchor_ref=f"{ANCHOR_REF_PREFIX}{'1' * 64}",
        signature="0" * 128,
    )
    frame_b = FederationFrame(
        header=_header_task_assigned(),
        payload=FederationPayload.task_assigned(_payload_task_assigned_data()),
    )
    # The two frames differ only in fields the signer should ignore.
    # The signing bytes MUST be identical.
    sig_a = signing_payload_bytes(frame_a)
    sig_b = signing_payload_bytes(frame_b)
    assert sig_a == sig_b
    text = sig_a.decode("utf-8")
    assert "anchor_ref" not in text
    assert "signature" not in text
    assert '"header":' in text
    assert '"payload":' in text


# ---------------------------------------------------------------------
# 7..9 — Malformed-frame rejection.
# ---------------------------------------------------------------------


def test_parse_rejects_bad_json():
    with pytest.raises(ParseError) as exc:
        parse_frame(b"{not-json}")
    assert exc.value.kind == "BadJson"


def test_parse_rejects_bad_utf8():
    # Lone continuation byte — not valid UTF-8.
    with pytest.raises(ParseError) as exc:
        parse_frame(b"\xff\xfe\xfd not utf-8")
    assert exc.value.kind == "BadUtf8"


def test_parse_rejects_payload_data_not_object():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": "should-be-an-object",
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "PayloadDataNotObject"


# ---------------------------------------------------------------------
# 10..13 — Version skew + schema validation.
# ---------------------------------------------------------------------


def test_parse_rejects_unsupported_version():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": 99,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "UnsupportedVersion"


def test_parse_rejects_unknown_envelope_schema():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": "wakir.federation.frame/9999",
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "UnknownSchema"
    assert exc.value.detail["field"] == "header.schema"


def test_parse_rejects_payload_kind_schema_mismatch():
    # kind=task-assigned but schema=task-output -> mismatch.
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_OUTPUT,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "UnknownSchema"
    assert exc.value.detail["field"] == "payload.schema"


def test_parse_rejects_unknown_payload_kind():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "biscuit-attenuation-broadcast",
            "data": {},
            "schema": "wakir.federation.biscuit-attenuation/1",
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "UnknownPayloadKind"
    assert exc.value.detail["payload_kind"] == "biscuit-attenuation-broadcast"


# ---------------------------------------------------------------------
# 14..16 — Field-shape validators.
# ---------------------------------------------------------------------


def test_parse_rejects_bad_frame_id_shape():
    raw = {
        "header": {
            "frame_id": "not-a-frame-id",
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "BadFrameIdShape"


def test_parse_rejects_bad_timestamp_shape():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "BadTimestampShape"


def test_parse_rejects_empty_runtime_id():
    raw = {
        "header": {
            "frame_id": compute_frame_id(b"any"),
            "schema": FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "",
            "target_runtime": "wakir-runtime",
            "ts_utc": "2026-05-17T08:00:00Z",
            "version": FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind": "task-assigned",
            "data": {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    }
    by = _jcs_canonicalize(raw)
    with pytest.raises(ParseError) as exc:
        parse_frame(by)
    assert exc.value.kind == "BadRuntimeId"
    assert exc.value.detail["field"] == "source_runtime"


# ---------------------------------------------------------------------
# 17 — Cross-lang byte-pin (parametrised over the 5 fixtures).
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture",
    _load_pin_fixtures(),
    ids=lambda f: f["label"],
)
def test_cross_lang_byte_pin_matches_fixture(fixture):
    """Python ``serialize_frame`` output MUST equal the pinned bytes.

    The Rust cross-lang test
    ``wirelang-rust/crates/persona-engine-federation-frame-parser/tests/
    cross_lang_python_sync_test.rs`` runs the equivalent assertion
    against the same fixture file with the Rust ``serialize_frame``.
    Drift in either direction breaks both lanes simultaneously.
    """
    frame = _frame_from_fixture_input(fixture["input"])
    by = serialize_frame(frame)
    text = by.decode("utf-8")
    pin_sha = hashlib.sha256(by).hexdigest()
    assert text == fixture["expected_canonical_utf8"], (
        f"Python serialize_frame byte-drift for {fixture['label']}; "
        f"see fixture file for the pinned bytes."
    )
    assert pin_sha == fixture["expected_canonical_sha256"]
    assert len(by) == fixture["expected_canonical_byte_length"]

    # The round-trip is also identity.
    parsed = parse_frame(by)
    assert parsed == frame


# ---------------------------------------------------------------------
# Bonus invariants.
# ---------------------------------------------------------------------


def test_compute_frame_id_is_deterministic():
    a = compute_frame_id(b"seed-A")
    b = compute_frame_id(b"seed-A")
    c = compute_frame_id(b"seed-B")
    assert a == b
    assert a != c
    assert a.startswith(FRAME_ID_PREFIX)
    assert len(a) == len(FRAME_ID_PREFIX) + SHA256_HEX_LEN


def test_payload_kind_and_schema_are_in_lockstep():
    for ctor, expected_kind, expected_schema in [
        (FederationPayload.task_assigned, "task-assigned", PAYLOAD_SCHEMA_TASK_ASSIGNED),
        (FederationPayload.task_output, "task-output", PAYLOAD_SCHEMA_TASK_OUTPUT),
        (
            FederationPayload.multi_org_attestation,
            "multi-org-attestation",
            PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION,
        ),
        (
            FederationPayload.spiffe_bundle_sync,
            "spiffe-bundle-sync",
            PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC,
        ),
    ]:
        p = ctor({"k": "v"})
        assert p.kind == expected_kind
        assert p.schema == expected_schema
