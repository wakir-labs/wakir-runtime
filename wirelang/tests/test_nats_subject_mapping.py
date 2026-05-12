# SPDX-License-Identifier: Apache-2.0
"""Determinism and rule-conformance tests for
:mod:`wirelang.nats.subject_mapping` (Phase-1b Sprint-2 Tag-1, S2-Item I-1).

Test-IDs map to the determinism invariants T-NSM-01..T-NSM-10 documented
in ``specs/nats-subject-mapping-v1.md`` §10. Six negative-control tests
cover §10.1.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest

from wirelang.nats import (
    SubjectV1,
    SubjectFormatError,
    build_subject,
    parse_subject,
    roundtrip,
    validate_stream_pattern,
    validate_consumer_filter,
    schema_for_subject,
    persona_slug,
    tv_anchor,
    federation_host_slug,
    RESERVED_DOMAINS,
    RESERVED_EVENT_TYPES,
)
from wirelang.nats.subject_mapping import SCHEMA_SUBJECT_REGEX


WIRELANG_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = WIRELANG_ROOT / "schemas" / "layer-0-transport.json"


# ---------------------------------------------------------------------------
# Determinism invariants T-NSM-01..10
# ---------------------------------------------------------------------------


def test_nsm_01_build_byte_deterministic():
    """T-NSM-01: build_subject is byte-deterministic across repeats."""
    out_a = build_subject("prod", "aip", "aip.document.published", "reza")
    out_b = build_subject("prod", "aip", "aip.document.published", "reza")
    assert out_a == out_b
    assert out_a == "wakir.prod.aip.aip.document.published.reza"
    # exact byte form
    assert out_a.encode("utf-8") == b"wakir.prod.aip.aip.document.published.reza"


def test_nsm_02_parse_roundtrip():
    """T-NSM-02: roundtrip(s) == s for every canonical subject."""
    canonical_subjects = [
        "wakir.dev.agent.task.assigned",
        "wakir.prod.wat.audit.anchor.created",
        "wakir.staging.aip.aip.document.published",
        "wakir.prod.aip.aip.document.published.reza",
        "wakir.prod.cap.cap.token.issued.mira",
        "wakir.dev.cap.cap.token.sealed.tomas",
        "wakir.dev.federation.federation.ftd.published.wakir-example-com",
    ]
    for s in canonical_subjects:
        assert roundtrip(s) == s, f"roundtrip mismatch for {s!r}"


def test_nsm_03_reserved_event_types_roundtrip():
    """T-NSM-03: every reserved domain × event_type combination
    parses and rebuilds byte-identically (with a representative
    persona-slug sub_id where applicable)."""
    for domain, event_types in RESERVED_EVENT_TYPES.items():
        if not event_types:
            continue
        for et in event_types:
            # without sub_id
            s = build_subject("prod", domain, et)
            assert roundtrip(s) == s
            # with persona-slug sub_id (where the §6.2 anchor applies)
            s2 = build_subject("prod", domain, et, "reza")
            parsed = parse_subject(s2)
            assert parsed.env == "prod"
            assert parsed.domain == domain
            assert parsed.event_type == et
            assert parsed.sub_id == "reza"
            assert roundtrip(s2) == s2


def test_nsm_04_persona_anchor_extract():
    """T-NSM-04: persona-slug sub_ids round-trip and are extractable."""
    for slug in ("reza", "tomas", "mira", "kai", "selin", "aisha", "henrik", "priya"):
        s = build_subject("prod", "aip", "aip.document.published", slug)
        parsed = parse_subject(s)
        assert persona_slug(parsed.sub_id) == slug
        assert tv_anchor(parsed.sub_id) is None


def test_nsm_05_tv_anchor_extract():
    """T-NSM-05: TV-W anchors round-trip and extract."""
    cases = [
        ("tv.w.1", (1, None)),
        ("tv.w.2.issued", (2, "issued")),
        ("tv.w.3.replay", (3, "replay")),
    ]
    for sub_id, expected in cases:
        s = build_subject("dev", "cap", "cap.token.issued", sub_id)
        parsed = parse_subject(s)
        assert parsed.sub_id == sub_id
        assert tv_anchor(parsed.sub_id) == expected
        assert persona_slug(parsed.sub_id) is None
        assert roundtrip(s) == s


def test_nsm_06_federation_host_slug_idempotent():
    """T-NSM-06: federation host-slug normalisation is idempotent."""
    cases = [
        ("wakir.dev", "wakir-dev"),
        ("example.com", "example-com"),
        ("wakir.example.com", "wakir-example-com"),
        ("wakir-dev", "wakir-dev"),  # already-normalised input
        ("a-b-c", "a-b-c"),
    ]
    for fqdn, expected in cases:
        slug_1 = federation_host_slug(fqdn)
        slug_2 = federation_host_slug(slug_1)
        assert slug_1 == expected
        assert slug_2 == slug_1, f"not idempotent for {fqdn!r}"


def test_nsm_07_stream_pattern_cross_env_rejected():
    """T-NSM-07: cross-env stream pattern is rejected (W2)."""
    with pytest.raises(SubjectFormatError, match=r"W2"):
        validate_stream_pattern("wakir.*.aip.>")
    with pytest.raises(SubjectFormatError, match=r"W2"):
        validate_stream_pattern("wakir.>")
    # Positive control
    validate_stream_pattern("wakir.prod.aip.>")
    validate_stream_pattern("wakir.dev.cap.>")


def test_nsm_08_consumer_filter_ambiguous_rejected():
    """T-NSM-08: consumer filter `wakir.<env>.<domain>.*.<...>` rejected
    as ambiguous against reverse-DNS event_types (W6)."""
    with pytest.raises(SubjectFormatError, match=r"W6"):
        validate_consumer_filter("wakir.prod.cap.*.tomas")
    # Positive controls — `>` after domain is canonical
    validate_consumer_filter("wakir.prod.cap.>")
    validate_consumer_filter("wakir.prod.aip.aip.document.published.*")


def test_nsm_09_schema_for_subject_advisory():
    """T-NSM-09: schema_for_subject returns the §8 inventory hint."""
    cases = [
        ("wakir.prod.aip.aip.document.published.reza",
         "https://wakir.dev/wirelang/schema/aip-document/0.1.0"),
        ("wakir.prod.cap.cap.token.issued.mira",
         "https://wakir.dev/wirelang/schema/layer-3-capability-token/0.1.0"),
        ("wakir.dev.federation.federation.ftd.published.wakir-example-com",
         "https://wakir.dev/wirelang/schema/federation-trust-document/0.1.0"),
        ("wakir.prod.agent.agent.task.assigned",
         "https://wakir.dev/wirelang/schema/layer-2-semantic/0.1.0"),
        ("wakir.prod.wat.wat.audit.anchor.created", None),  # Tomás-owner
    ]
    for subject, expected in cases:
        assert schema_for_subject(subject) == expected, f"{subject!r}"


def test_nsm_10_schema_regex_compatibility():
    """T-NSM-10: every build_subject output matches the on-disk schema regex.

    The mirror constant SCHEMA_SUBJECT_REGEX MUST match the on-disk
    schema regex byte-for-byte. This locks the module to the schema
    registry.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    on_disk_pattern = schema["properties"]["subject"]["properties"]["pattern"]["pattern"]
    assert SCHEMA_SUBJECT_REGEX.pattern == on_disk_pattern, (
        f"mirror regex out of sync with schema: "
        f"mirror={SCHEMA_SUBJECT_REGEX.pattern!r} on_disk={on_disk_pattern!r}"
    )

    # Generate representative subjects across the reserved space
    representative_subjects = []
    for domain, event_types in RESERVED_EVENT_TYPES.items():
        for et in event_types:
            representative_subjects.append(build_subject("prod", domain, et))
            representative_subjects.append(build_subject("prod", domain, et, "reza"))

    on_disk_re = re.compile(on_disk_pattern)
    for s in representative_subjects:
        assert on_disk_re.match(s), f"schema regex rejected {s!r}"


# ---------------------------------------------------------------------------
# Negative-control tests (§10.1)
# ---------------------------------------------------------------------------


def test_negative_uppercase_env_rejected():
    """§10.1: uppercase env rejected (R1)."""
    with pytest.raises(SubjectFormatError, match=r"R1"):
        build_subject("PROD", "aip", "aip.document.published")


def test_negative_missing_wakir_literal_rejected():
    """§10.1: missing 'wakir' literal rejected at parse (R2)."""
    with pytest.raises(SubjectFormatError, match=r"R0"):
        parse_subject("corp.prod.aip.aip.document.published")


def test_negative_empty_sub_id_rejected():
    """§10.1: empty sub_id rejected (R4)."""
    with pytest.raises(SubjectFormatError, match=r"R4"):
        build_subject("prod", "aip", "aip.document.published", "")


def test_negative_oversize_sub_id_rejected():
    """§10.1: sub_id > 64 octets rejected (R4)."""
    long_slug = "a" * 65
    with pytest.raises(SubjectFormatError, match=r"R4"):
        build_subject("prod", "aip", "aip.document.published", long_slug)


def test_negative_unknown_domain_soft_warns_and_accepts():
    """§10.1: unknown domain → soft warn + accept (R5 spirit, v1)."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        s = build_subject("prod", "foobar", "x.y.z")
        assert s == "wakir.prod.foobar.x.y.z"
        assert any("foobar" in str(item.message) for item in w), (
            f"expected forward-compat warning for unknown domain, got {w!r}"
        )


def test_negative_cross_env_stream_pattern_rejected():
    """§10.1: cross-env stream pattern `wakir.*.>` rejected (W2)."""
    with pytest.raises(SubjectFormatError, match=r"W2"):
        validate_stream_pattern("wakir.*.>")


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_subject_v1_to_string_matches_build():
    """SubjectV1.to_string() agrees with build_subject."""
    sv = SubjectV1(env="prod", domain="cap", event_type="cap.token.issued",
                   sub_id="reza")
    assert sv.to_string() == "wakir.prod.cap.cap.token.issued.reza"
    assert sv.to_string() == build_subject(sv.env, sv.domain, sv.event_type, sv.sub_id)


def test_no_sub_id_event_types_with_dots():
    """Reverse-DNS event_types without sub_id parse cleanly (multi-dot)."""
    s = "wakir.prod.aip.aip.document.published"
    parsed = parse_subject(s)
    assert parsed.env == "prod"
    assert parsed.domain == "aip"
    assert parsed.event_type == "aip.document.published"
    assert parsed.sub_id is None
    assert roundtrip(s) == s


def test_persona_slug_extracts_only_known_form():
    """persona_slug returns None for non-persona-slug forms."""
    assert persona_slug("Reza") is None  # uppercase
    assert persona_slug("0reza") is None  # starts with digit
    assert persona_slug("a" * 32) is None  # too long
    assert persona_slug("reza_dev") == "reza_dev"
    assert persona_slug(None) is None


def test_tv_anchor_extracts_only_known_form():
    """tv_anchor returns None for non-TV forms."""
    assert tv_anchor("reza") is None
    assert tv_anchor("tv.w") is None  # missing n
    assert tv_anchor("tv.w.abc") is None  # n must be int
    assert tv_anchor("tv.w.2") == (2, None)
    assert tv_anchor("tv.w.3.replay") == (3, "replay")
    assert tv_anchor(None) is None


def test_federation_host_slug_rejects_invalid_input():
    """federation_host_slug raises on invalid input."""
    with pytest.raises(SubjectFormatError, match=r"R6"):
        federation_host_slug("")
    with pytest.raises(SubjectFormatError, match=r"R6"):
        federation_host_slug("Wakir Labs")  # whitespace, uppercase
    with pytest.raises(SubjectFormatError, match=r"R6"):
        federation_host_slug("foo_bar")  # underscore not in [a-z0-9-]
