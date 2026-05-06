# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the wirelang.builder frame-builder helper.

The builder is a convenience for tests and integration glue. The tests
verify (a) that the produced dicts validate against the Layer-1 JSON
Schema, (b) that defaults are sensible, and (c) that the helper does
not surface clear names or other Brand-Guide §9 violations on the
default code path.
"""

from __future__ import annotations

import hashlib

import pytest

from wirelang.builder import (
    FrameBuilder,
    build_layer_1_frame,
    capability_token_hash_ref,
)


# ---------- capability_token_hash_ref -----------------------------------------


def test_capability_token_hash_ref_format():
    ref = capability_token_hash_ref(b"some-canonical-token-bytes")
    assert ref.startswith("sha256:")
    assert len(ref) == len("sha256:") + 64
    expected = hashlib.sha256(b"some-canonical-token-bytes").hexdigest()
    assert ref == f"sha256:{expected}"


# ---------- build_layer_1_frame: schema validity ------------------------------


def test_build_layer_1_frame_validates_against_layer_1_schema(layer_1_validator):
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZA",
        payload={"action": "read.balance", "wallet": "wakir-treasury-eoa-phase-1"},
        time="2026-05-06T11:35:00Z",
        agentid="treasury-agent-001",
    )
    # schema requires the eight mandatories; builder fills them.
    assert layer_1_validator.is_valid(frame), list(layer_1_validator.iter_errors(frame))
    assert frame["wirelangversion"] == "0.2.0"


def test_build_layer_1_frame_with_capability_refs_validates(layer_1_validator):
    capref = capability_token_hash_ref(b"token-bytes-x")
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.submit",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZB",
        capability_token_hashes=[capref],
        time="2026-05-06T11:35:00Z",
    )
    assert layer_1_validator.is_valid(frame), list(layer_1_validator.iter_errors(frame))
    assert frame["caprefs"] == [capref]


def test_build_layer_1_frame_meta_event_classified_correctly():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:hr-agent",
        event_type="wakir.meta.capability.issued",
        actorrole="org-designer",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZC",
        payload={"target": "treasury-agent"},
        time="2026-05-06T11:35:00Z",
    )
    envelope = frame["data"]["wirelang_layer_2_envelope"]
    assert envelope["frame_class"] == "meta-event"


def test_build_layer_1_frame_domain_event_classified_correctly():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZD",
        payload={"x": 1},
        time="2026-05-06T11:35:00Z",
    )
    envelope = frame["data"]["wirelang_layer_2_envelope"]
    assert envelope["frame_class"] == "domain-event"


def test_build_layer_1_frame_skip_envelope_yields_raw_payload():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZE",
        payload={"flag": True},
        embed_layer_2_envelope=False,
    )
    assert frame["data"] == {"flag": True}


# ---------- FrameBuilder fluent surface ---------------------------------------


def test_frame_builder_default_chain_validates(layer_1_validator):
    frame = (
        FrameBuilder()
        .with_payload({"action": "read.balance"})
        .with_event_id("01HK4P8X3W2N5Q9V0R6T7S8YZF")
        .build()
    )
    assert layer_1_validator.is_valid(frame), list(layer_1_validator.iter_errors(frame))


def test_frame_builder_capability_chain_threads_into_caprefs():
    frame = (
        FrameBuilder()
        .with_capability(b"token-1")
        .with_capability(b"token-2")
        .build()
    )
    assert frame["caprefs"] == [
        capability_token_hash_ref(b"token-1"),
        capability_token_hash_ref(b"token-2"),
    ]


def test_frame_builder_brand_guide_no_clear_names_in_defaults():
    """The default builder surface MUST NOT emit any clear personal names.

    Defaults use role-strings (treasury-agent, treasury-operator). This
    test asserts the principle by constructing a frame with all defaults
    and inspecting the result for the role-string pattern.
    """
    frame = FrameBuilder().with_event_id("01HK4P8X3W2N5Q9V0R6T7S8YZG").build()
    assert frame["actorrole"] == "treasury-operator"
    assert "wakir.dev" in frame["source"]
    # No first-name-style tokens at default surfaces.
    for value in (frame["source"], frame["actorrole"], frame.get("agentid", "")):
        assert "@" not in str(value)
        assert " " not in str(value)


# ---------- error-shape sanity ------------------------------------------------


def test_build_layer_1_frame_omits_optional_attributes_when_unset():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZH",
    )
    for absent in (
        "agentid",
        "personapin",
        "personahash",
        "attestationref",
        "imagedigest",
        "dataschemaref",
        "caprefs",
        "time",
    ):
        assert absent not in frame, f"unexpected default for {absent}"


def test_build_layer_1_frame_schema_id_defaults_to_event_type():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZI",
    )
    assert frame["schemaid"] == "wakir.treasury.read"


def test_build_layer_1_frame_schema_id_explicit_override():
    frame = build_layer_1_frame(
        persona_did="did:web:wakir.dev:treasury-agent",
        event_type="wakir.treasury.read",
        schema_id="wakir.treasury.read.alias",
        actorrole="treasury-operator",
        event_id="01HK4P8X3W2N5Q9V0R6T7S8YZJ",
    )
    assert frame["schemaid"] == "wakir.treasury.read.alias"
