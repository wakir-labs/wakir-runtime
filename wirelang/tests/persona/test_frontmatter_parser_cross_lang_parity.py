# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine frontmatter-parser
canonical-trace (Tag-34 Mini-Welle Phase-3a Python-sync, 11. Modul).

This file is the Python half of the cross-lang fixture pin pair. The
Rust half lives at
``wirelang-rust/crates/persona-engine-frontmatter-parser/tests/cross_lang_fixture_test.rs``
and consumes the same authoritative fixture file at
``tests/fixtures/frontmatter-parser-cross-lang/fixtures.json``.

Test taxonomy
-------------

- T01 — Constants pin: ``FRONTMATTER_TRACE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` match the Rust crate's ``pub const`` items.
- T02 — Accepted-status enum pin: the five wire-strings match
  byte-for-byte (drift sentinel for the status enum).
- T03 — Determinism: two trace builds of the same markdown input
  produce byte-identical canonical output.
- T04 — Wire-shape key order: top-level JCS keys are in alphabetical
  order (the cross-lang contract).
- T05 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase
  hex``; bare hex is exactly 64 lowercase hex characters.
- T06 — Cross-lang fixture file structure: schema_version, fixture
  count, and per-fixture key set match the Rust sibling's
  structure pin.
- T07 — Cross-lang fixture per-vector pin (parametrised over all
  seven fixtures): byte-for-byte parity with the JSON fixture
  file's pinned values (this is the core trace-hash byte-parity
  test).
- T08 — Canonical-subset SHA-256 pin for ``ok`` fixtures: the
  ``canonical_subset_jcs_sha256_hex`` field matches what
  :func:`wirelang.persona.persona_canonical_form.canonical_jcs_bytes`
  + SHA-256 would produce directly (independent re-derivation).
- T09 — Error-path traces carry empty ``canonical_subset_jcs_sha256_hex``:
  the schema-symmetry contract (always emit the key, value is empty
  string on non-``ok`` paths).
- T10 — V-907 pin pack anchor: the f01 fixture's canonical-subset
  SHA-256 equals the historical ``PERSONA_HASH_PIN_V9``
  (``0f298894…e1d793``), binding this trace into the V-907 pin pack.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-frontmatter-parser``
   canonical-trace surface and Python
   ``frontmatter_parser_canonical.py``).
2. Re-derive the fixture vectors using a derivation script that
   loads the seven inputs and emits the expected blocks.
3. Update both Python and Rust test suites in the same PR.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

# Cross-lang parity needs PyYAML + rfc8785 to build the canonical-trace
# from a markdown input. The shadow-CI lane runs without either wheel
# (see `wirelang/persona/persona_canonical_form.py` resolver docstring);
# skip the entire suite on that lane via the same `importorskip` pattern
# already established in `wirelang/tests/test_aip_document_golden.py`
# and `wirelang/tests/test_did_document_golden.py`.
pytest.importorskip("yaml")
pytest.importorskip("rfc8785")

from wirelang.persona.frontmatter_parser_canonical import (
    ACCEPTED_STATUS_VALUES,
    FRONTMATTER_TRACE_SCHEMA,
    HASH_PREFIX,
    SHA256_HEX_LEN,
    STATUS_INVALID_SHAPE,
    STATUS_MALFORMED,
    STATUS_MISSING_FENCE,
    STATUS_OK,
    STATUS_YAML_PARSE_ERROR,
    FrontmatterParseTrace,
    build_frontmatter_trace,
    frontmatter_trace_hash_prefixed,
    frontmatter_trace_sha256_hex,
    serialize_frontmatter_trace,
)
from wirelang.persona.persona_canonical_form import (
    canonical_jcs_bytes,
    extract_canonical_subset,
    parse_frontmatter,
    split_frontmatter,
)


# Historical V-907 pin pack anchor (PERSONA_HASH_PIN_V9). The f01 fixture
# is the v9-persona-framework-native.md ground truth.
PERSONA_HASH_PIN_V9 = (
    "0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793"
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _fixture_path() -> pathlib.Path:
    return (
        _repo_root()
        / "tests"
        / "fixtures"
        / "frontmatter-parser-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    return json.loads(_fixture_path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# T01 — constants pin.
# ---------------------------------------------------------------------


def test_t01_constants_pin() -> None:
    assert (
        FRONTMATTER_TRACE_SCHEMA
        == "wakir.persona-engine.frontmatter-parser-canonical/1"
    )
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------
# T02 — accepted-status enum pin.
# ---------------------------------------------------------------------


def test_t02_accepted_status_pin() -> None:
    assert STATUS_OK == "ok"
    assert STATUS_MISSING_FENCE == "missing_fence"
    assert STATUS_MALFORMED == "malformed"
    assert STATUS_YAML_PARSE_ERROR == "yaml_parse_error"
    assert STATUS_INVALID_SHAPE == "invalid_shape"
    assert ACCEPTED_STATUS_VALUES == (
        STATUS_OK,
        STATUS_MISSING_FENCE,
        STATUS_MALFORMED,
        STATUS_YAML_PARSE_ERROR,
        STATUS_INVALID_SHAPE,
    )


# ---------------------------------------------------------------------
# T03 — determinism: two builds of the same input -> identical bytes.
# ---------------------------------------------------------------------


def test_t03_build_is_deterministic() -> None:
    md = (
        "---\n"
        "name: dup\n"
        "description: determinism check\n"
        "tools: [Read]\n"
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  cross_review_zones: []\n"
        "  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n"
        "  hierarchy: {reports_to: cto, escalation: cto}\n"
        "---\n"
        "body\n"
    )
    t1 = build_frontmatter_trace(md)
    t2 = build_frontmatter_trace(md)
    assert t1 == t2
    assert serialize_frontmatter_trace(t1) == serialize_frontmatter_trace(t2)
    assert frontmatter_trace_sha256_hex(t1) == frontmatter_trace_sha256_hex(t2)


# ---------------------------------------------------------------------
# T04 — wire-shape key order is alphabetical.
# ---------------------------------------------------------------------


def test_t04_wire_keys_alphabetical() -> None:
    md = (
        "---\n"
        "name: order-check\n"
        "description: alpha-order pin\n"
        "tools: [Read]\n"
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  cross_review_zones: []\n"
        "  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n"
        "  hierarchy: {reports_to: cto, escalation: cto}\n"
        "---\n"
        "body\n"
    )
    trace = build_frontmatter_trace(md)
    jcs = serialize_frontmatter_trace(trace)
    # rfc8785 sorts keys. Extract the first byte after each '"' that
    # starts a key, then check alphabetic ordering.
    parsed = json.loads(jcs.decode("utf-8"))
    keys = list(parsed.keys())
    assert keys == sorted(keys)
    expected_keys = {
        "accepted_status",
        "canonical_subset_jcs_sha256_hex",
        "error_class",
        "persona_name",
        "persona_slug",
        "schema",
        "schema_version",
        "tools_count",
    }
    assert set(keys) == expected_keys


# ---------------------------------------------------------------------
# T05 — hash-shape pin.
# ---------------------------------------------------------------------


def test_t05_hash_shape_pin() -> None:
    md = (
        "---\n"
        "name: hash-shape\n"
        "description: pin\n"
        "tools: [Read]\n"
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  cross_review_zones: []\n"
        "  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n"
        "  hierarchy: {reports_to: cto, escalation: cto}\n"
        "---\n"
        "body\n"
    )
    trace = build_frontmatter_trace(md)
    bare = frontmatter_trace_sha256_hex(trace)
    prefixed = frontmatter_trace_hash_prefixed(trace)
    assert len(bare) == SHA256_HEX_LEN
    assert bare == bare.lower()
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed == HASH_PREFIX + bare


# ---------------------------------------------------------------------
# T06 — fixture file structure pin.
# ---------------------------------------------------------------------


def test_t06_fixture_file_structure_pin() -> None:
    doc = _load_fixtures()
    assert doc["schema_version"] == FRONTMATTER_TRACE_SCHEMA
    fixtures = doc["fixtures"]
    assert len(fixtures) == 7, "Tag-34 cross-lang vector count is 7 (3 ok + 4 error paths)"
    required_top_keys = {"name", "input_md_b64", "expected"}
    required_expected_keys = {
        "accepted_status",
        "error_class",
        "persona_name",
        "persona_slug",
        "schema_version",
        "tools_count",
        "canonical_subset_jcs_sha256_hex",
        "trace_jcs_bytes_b64",
        "trace_jcs_bytes_len",
        "trace_sha256_hex",
        "trace_hash_prefixed",
    }
    for f in fixtures:
        assert required_top_keys <= set(f.keys()), f["name"]
        assert required_expected_keys <= set(f["expected"].keys()), f["name"]


# ---------------------------------------------------------------------
# T07 — per-vector byte-parity pin.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("vector_idx", range(7))
def test_t07_per_vector_byte_parity(vector_idx: int) -> None:
    doc = _load_fixtures()
    vec = doc["fixtures"][vector_idx]
    md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
    expected = vec["expected"]

    trace = build_frontmatter_trace(md)

    # Structured fields.
    assert trace.accepted_status == expected["accepted_status"], vec["name"]
    assert trace.error_class == expected["error_class"], vec["name"]
    assert trace.persona_name == expected["persona_name"], vec["name"]
    assert trace.persona_slug == expected["persona_slug"], vec["name"]
    assert trace.schema_version == expected["schema_version"], vec["name"]
    assert trace.tools_count == expected["tools_count"], vec["name"]
    assert (
        trace.canonical_subset_jcs_sha256_hex
        == expected["canonical_subset_jcs_sha256_hex"]
    ), vec["name"]

    # Byte-level.
    jcs_actual = serialize_frontmatter_trace(trace)
    jcs_expected = base64.b64decode(expected["trace_jcs_bytes_b64"])
    assert jcs_actual == jcs_expected, vec["name"]
    assert len(jcs_actual) == expected["trace_jcs_bytes_len"], vec["name"]
    assert (
        frontmatter_trace_sha256_hex(trace) == expected["trace_sha256_hex"]
    ), vec["name"]
    assert (
        frontmatter_trace_hash_prefixed(trace)
        == expected["trace_hash_prefixed"]
    ), vec["name"]


# ---------------------------------------------------------------------
# T08 — canonical_subset_jcs_sha256_hex independently re-derived for OK.
# ---------------------------------------------------------------------


def test_t08_canonical_subset_independent_rederive_ok_fixtures() -> None:
    doc = _load_fixtures()
    for vec in doc["fixtures"]:
        if vec["expected"]["accepted_status"] != "ok":
            continue
        md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
        fm_yaml, _body = split_frontmatter(md)
        fm_dict = parse_frontmatter(fm_yaml)
        canonical = extract_canonical_subset(fm_dict)
        sha = hashlib.sha256(canonical_jcs_bytes(canonical)).hexdigest()
        assert sha == vec["expected"]["canonical_subset_jcs_sha256_hex"], (
            vec["name"]
        )


# ---------------------------------------------------------------------
# T09 — error-path traces have empty canonical_subset_jcs_sha256_hex.
# ---------------------------------------------------------------------


def test_t09_error_paths_have_empty_canonical_sha() -> None:
    doc = _load_fixtures()
    error_paths_seen = 0
    for vec in doc["fixtures"]:
        if vec["expected"]["accepted_status"] == "ok":
            continue
        error_paths_seen += 1
        assert vec["expected"]["canonical_subset_jcs_sha256_hex"] == "", (
            vec["name"]
        )
        # Rebuild trace from input + verify same.
        md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
        trace = build_frontmatter_trace(md)
        assert trace.canonical_subset_jcs_sha256_hex == "", vec["name"]
    # We expect at least 4 error-path fixtures.
    assert error_paths_seen >= 4


# ---------------------------------------------------------------------
# T10 — V-907 pin pack anchor: f01 canonical subset SHA == PERSONA_HASH_PIN_V9.
# ---------------------------------------------------------------------


def test_t10_v907_pin_pack_anchor() -> None:
    doc = _load_fixtures()
    f01 = next(f for f in doc["fixtures"] if f["name"] == "f01-full-v9-persona")
    assert (
        f01["expected"]["canonical_subset_jcs_sha256_hex"]
        == PERSONA_HASH_PIN_V9
    ), (
        "f01 fixture must anchor into the V-907 pin pack (PERSONA_HASH_PIN_V9); "
        "any change here means the V-907 hash has drifted, not the trace shape."
    )
