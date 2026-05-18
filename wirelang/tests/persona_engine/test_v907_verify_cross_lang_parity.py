# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine V-907-verify
canonical-trace (Tag-35 Mini-Welle Phase-3a Python-sync, 12. Modul).

This file is the Python half of the cross-lang fixture pin pair.  The
Rust half lives at
``wirelang-rust/crates/persona-engine-v907-verify/tests/cross_lang_fixture_test.rs``
and consumes the same authoritative fixture file at
``tests/fixtures/v907-verify-cross-lang/fixtures.json``.

Test taxonomy
-------------

- T01 — Constants pin: ``V907_VERIFY_TRACE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` / ``DEFAULT_SCHEMA_VERSION`` match the Rust crate's
  ``pub const`` items.
- T02 — Accepted-status enum pin: the two wire-strings (``"ok"`` and
  ``"compute_error"``) match byte-for-byte (drift sentinel).
- T03 — Determinism: two trace builds of the same markdown input
  produce byte-identical canonical output.
- T04 — Wire-shape key order: top-level JCS keys are in alphabetical
  order (the cross-lang contract); 8 keys expected.
- T05 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase
  hex``; bare hex is exactly 64 lowercase hex characters.
- T06 — Cross-lang fixture file structure: schema_version, fixture
  count (6), and per-fixture key set match the Rust sibling's
  structure pin.
- T07 — Cross-lang fixture per-vector pin (parametrised over all
  six fixtures): byte-for-byte parity with the JSON fixture
  file's pinned values (this is the core trace-hash byte-parity
  test).
- T08 — Pin field on ``ok`` fixtures equals ``compute_v907_pin`` of the
  same input (cross-check against the existing engine-side
  surface in ``v907_verify.py``).
- T09 — Error-path traces carry empty string for pin /
  canonical_subset_jcs_sha256_hex / schema_version /
  optional_keys_present, and default_schema_version_used is False.
- T10 — V-907 pin pack anchor: the f01 fixture's
  ``canonical_subset_jcs_sha256_hex`` equals the historical
  ``SAMPLE_AXIS_A_MIN`` anchor pin
  (``cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39``).

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-v907-verify``
   canonical module surface and Python
   ``v907_verify_canonical.py``).
2. Re-derive the fixture vectors using the inline derivation block
   in the fixture-generation script (see this file's ``__main__``
   for the derivation recipe).
3. Update both Python and Rust test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict

import pytest

# Cross-lang parity needs PyYAML + rfc8785 to build the canonical-trace
# from a markdown input.  The shadow-CI lane runs without either wheel
# (see `wirelang/persona/persona_canonical_form.py` resolver docstring);
# skip the entire suite on that lane via the same `importorskip` pattern
# already established in the Tag-34 sibling test
# (`test_frontmatter_parser_cross_lang_parity.py`).
pytest.importorskip("yaml")
pytest.importorskip("rfc8785")

from wirelang.persona_engine.v907_verify import compute_v907_pin
from wirelang.persona_engine.v907_verify_canonical import (
    ACCEPTED_STATUS_VALUES,
    DEFAULT_SCHEMA_VERSION,
    ERROR_CLASS_COMPUTE,
    HASH_PREFIX,
    SHA256_HEX_LEN,
    STATUS_COMPUTE_ERROR,
    STATUS_OK,
    V907_VERIFY_TRACE_SCHEMA,
    V907VerifyTrace,
    build_v907_verify_trace,
    serialize_v907_verify_trace,
    v907_verify_trace_hash_prefixed,
    v907_verify_trace_sha256_hex,
)


# Historical V-907 pin pack anchor for SAMPLE_AXIS_A_MIN.  This hex is
# also pinned in the Rust crate's smoke test as `PIN_AXIS_A_MIN` (full
# form `"sha256:" + this_hex`).  Tag-35 binds the new canonical-trace
# surface to the same V-907 ground truth.
PERSONA_HASH_PIN_SAMPLE_AXIS_A_MIN = (
    "cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39"
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _fixture_path() -> pathlib.Path:
    return (
        _repo_root()
        / "tests"
        / "fixtures"
        / "v907-verify-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    return json.loads(_fixture_path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# T01 — constants pin.
# ---------------------------------------------------------------------


def test_t01_constants_pin() -> None:
    assert (
        V907_VERIFY_TRACE_SCHEMA
        == "wakir.persona-engine.v907-verify-canonical/1"
    )
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64
    assert DEFAULT_SCHEMA_VERSION == "persona-v1"


# ---------------------------------------------------------------------
# T02 — accepted-status enum pin.
# ---------------------------------------------------------------------


def test_t02_accepted_status_pin() -> None:
    assert STATUS_OK == "ok"
    assert STATUS_COMPUTE_ERROR == "compute_error"
    assert ACCEPTED_STATUS_VALUES == (STATUS_OK, STATUS_COMPUTE_ERROR)
    assert ERROR_CLASS_COMPUTE == "PersonaHashComputeError"


# ---------------------------------------------------------------------
# T03 — determinism: two builds of the same input -> identical bytes.
# ---------------------------------------------------------------------


def test_t03_build_is_deterministic() -> None:
    md = (
        "---\n"
        "name: dup\n"
        "description: determinism check\n"
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  email: dup@example.com\n"
        "domain: dev-engineering\n"
        "---\n"
        "body\n"
    )
    t1 = build_v907_verify_trace(md)
    t2 = build_v907_verify_trace(md)
    assert t1 == t2
    assert serialize_v907_verify_trace(t1) == serialize_v907_verify_trace(t2)
    assert v907_verify_trace_sha256_hex(t1) == v907_verify_trace_sha256_hex(t2)


# ---------------------------------------------------------------------
# T04 — wire-shape key order is alphabetical.
# ---------------------------------------------------------------------


def test_t04_wire_keys_alphabetical() -> None:
    md = (
        "---\n"
        "name: order-check\n"
        "description: alpha-order pin\n"
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  email: order@example.com\n"
        "---\n"
        "body\n"
    )
    trace = build_v907_verify_trace(md)
    jcs = serialize_v907_verify_trace(trace)
    parsed = json.loads(jcs.decode("utf-8"))
    keys = list(parsed.keys())
    assert keys == sorted(keys)
    expected_keys = {
        "accepted_status",
        "canonical_subset_jcs_sha256_hex",
        "default_schema_version_used",
        "error_class",
        "optional_keys_present",
        "pin",
        "schema",
        "schema_version",
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
        "schema_version: persona-v1\n"
        "identity_pinned:\n"
        "  email: x@example.com\n"
        "---\n"
        "body\n"
    )
    trace = build_v907_verify_trace(md)
    bare = v907_verify_trace_sha256_hex(trace)
    prefixed = v907_verify_trace_hash_prefixed(trace)
    assert len(bare) == SHA256_HEX_LEN
    assert bare == bare.lower()
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed == HASH_PREFIX + bare


# ---------------------------------------------------------------------
# T06 — fixture file structure pin.
# ---------------------------------------------------------------------


def test_t06_fixture_file_structure_pin() -> None:
    doc = _load_fixtures()
    assert doc["schema_version"] == V907_VERIFY_TRACE_SCHEMA
    fixtures = doc["fixtures"]
    assert len(fixtures) == 6, "Tag-35 cross-lang vector count is 6 (4 ok + 2 error paths)"
    required_top_keys = {"name", "input_md_b64", "expected"}
    required_expected_keys = {
        "accepted_status",
        "canonical_subset_jcs_sha256_hex",
        "default_schema_version_used",
        "error_class",
        "optional_keys_present",
        "pin",
        "schema_version",
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


@pytest.mark.parametrize("vector_idx", range(6))
def test_t07_per_vector_byte_parity(vector_idx: int) -> None:
    doc = _load_fixtures()
    vec = doc["fixtures"][vector_idx]
    md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
    expected = vec["expected"]

    trace = build_v907_verify_trace(md)

    # Structured fields.
    assert trace.accepted_status == expected["accepted_status"], vec["name"]
    assert (
        trace.canonical_subset_jcs_sha256_hex
        == expected["canonical_subset_jcs_sha256_hex"]
    ), vec["name"]
    assert (
        trace.default_schema_version_used
        == expected["default_schema_version_used"]
    ), vec["name"]
    assert trace.error_class == expected["error_class"], vec["name"]
    assert (
        trace.optional_keys_present == expected["optional_keys_present"]
    ), vec["name"]
    assert trace.pin == expected["pin"], vec["name"]
    assert trace.schema_version == expected["schema_version"], vec["name"]

    # Byte-level.
    jcs_actual = serialize_v907_verify_trace(trace)
    jcs_expected = base64.b64decode(expected["trace_jcs_bytes_b64"])
    assert jcs_actual == jcs_expected, vec["name"]
    assert len(jcs_actual) == expected["trace_jcs_bytes_len"], vec["name"]
    assert (
        v907_verify_trace_sha256_hex(trace) == expected["trace_sha256_hex"]
    ), vec["name"]
    assert (
        v907_verify_trace_hash_prefixed(trace)
        == expected["trace_hash_prefixed"]
    ), vec["name"]


# ---------------------------------------------------------------------
# T08 — pin field cross-checks against existing compute_v907_pin path.
# ---------------------------------------------------------------------


def test_t08_pin_matches_existing_compute_v907_pin_for_ok_fixtures() -> None:
    doc = _load_fixtures()
    ok_count = 0
    for vec in doc["fixtures"]:
        if vec["expected"]["accepted_status"] != STATUS_OK:
            continue
        ok_count += 1
        md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
        direct_pin = compute_v907_pin(md.encode("utf-8"))
        trace_pin = vec["expected"]["pin"]
        assert direct_pin == trace_pin, (
            f"{vec['name']}: trace pin must equal direct compute_v907_pin "
            f"(trace={trace_pin}, direct={direct_pin})"
        )
    assert ok_count >= 4, "expected at least 4 ok-path fixtures"


# ---------------------------------------------------------------------
# T09 — error-path traces have empty pin/canonical/schema_version/keys.
# ---------------------------------------------------------------------


def test_t09_error_paths_have_empty_compute_fields() -> None:
    doc = _load_fixtures()
    error_paths_seen = 0
    for vec in doc["fixtures"]:
        if vec["expected"]["accepted_status"] == STATUS_OK:
            continue
        error_paths_seen += 1
        e = vec["expected"]
        assert e["accepted_status"] == STATUS_COMPUTE_ERROR, vec["name"]
        assert e["error_class"] == ERROR_CLASS_COMPUTE, vec["name"]
        assert e["pin"] == "", vec["name"]
        assert e["canonical_subset_jcs_sha256_hex"] == "", vec["name"]
        assert e["optional_keys_present"] == "", vec["name"]
        assert e["schema_version"] == "", vec["name"]
        assert e["default_schema_version_used"] is False, vec["name"]
        # Rebuild trace from input + verify same.
        md = base64.b64decode(vec["input_md_b64"]).decode("utf-8")
        trace = build_v907_verify_trace(md)
        assert trace.accepted_status == STATUS_COMPUTE_ERROR, vec["name"]
        assert trace.error_class == ERROR_CLASS_COMPUTE, vec["name"]
        assert trace.pin == "", vec["name"]
        assert trace.canonical_subset_jcs_sha256_hex == "", vec["name"]
        assert trace.optional_keys_present == "", vec["name"]
        assert trace.schema_version == "", vec["name"]
        assert trace.default_schema_version_used is False, vec["name"]
    # We expect at least 2 error-path fixtures (f05 + f06).
    assert error_paths_seen >= 2


# ---------------------------------------------------------------------
# T10 — V-907 pin pack anchor: f01 canonical subset SHA + pin lock.
# ---------------------------------------------------------------------


def test_t10_v907_pin_pack_anchor() -> None:
    doc = _load_fixtures()
    f01 = next(
        f for f in doc["fixtures"] if f["name"] == "f01-sample-axis-a-min"
    )
    assert (
        f01["expected"]["canonical_subset_jcs_sha256_hex"]
        == PERSONA_HASH_PIN_SAMPLE_AXIS_A_MIN
    ), (
        "f01 fixture must anchor into the V-907 pin pack "
        "(SAMPLE_AXIS_A_MIN canonical-subset SHA); any change here means "
        "the V-907 hash has drifted, not the trace shape."
    )
    # pin field must equal "sha256:" + the same hex.
    assert (
        f01["expected"]["pin"]
        == f"sha256:{PERSONA_HASH_PIN_SAMPLE_AXIS_A_MIN}"
    )
