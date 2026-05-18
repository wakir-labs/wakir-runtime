# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine migrate-version
canonical-trace (Tag-38 Phase-3a Python-sync, 15. Modul — closes
the Phase-3a-Foundation sweep).

This file is the Python half of the cross-lang fixture pin pair.  The
Rust half lives at
``wirelang-rust/crates/persona-engine-migrate-version/tests/cross_lang_fixture_test.rs``
and consumes the same authoritative fixture file at
``tests/fixtures/migrate-version-cross-lang/fixtures.json``.

Test taxonomy
-------------

- T01 — Constants pin: ``MIGRATE_VERSION_DECISION_TRACE_SCHEMA`` /
  ``HASH_PREFIX`` / ``SHA256_HEX_LEN`` match the Rust crate's
  ``pub const`` items.
- T02 — Accepted-status enum pin: the two wire-strings (``"ok"``
  and ``"rejected"``) match byte-for-byte (drift sentinel).
- T03 — Failure-mode enum pin: the three wire-strings plus the
  empty-string success sentinel match byte-for-byte.
- T04 — KNOWN_ENGINE_VERSIONS triple-anchor: Python sibling and
  Rust crate carry the exact same closed set as the live
  :mod:`migrate_version` module (three-place edit invariant).
- T05 — Determinism: two trace builds of the same input produce
  byte-identical canonical output.
- T06 — Wire-shape key order: top-level JCS keys are in
  alphabetical order (the cross-lang contract); 11 keys expected.
- T07 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase
  hex``; bare hex is exactly 64 lowercase hex characters.
- T08 — Cross-lang fixture file structure: schema_version, fixture
  count (6), and per-fixture key set match the Rust sibling's
  structure pin.
- T09 — Cross-lang fixture per-vector pin (parametrised over all
  six fixtures): byte-for-byte parity with the JSON fixture
  file's pinned values.  This is the core trace-hash byte-parity
  test.
- T10 — Decision-order pin: when ``from_version`` is not in
  KNOWN_ENGINE_VERSIONS AND ``to_version`` is also unknown, the
  failure_mode is ``UnknownFromVersion`` (the from-check fires
  first).  The contract is documented in
  :func:`build_migrate_version_decision_trace`.
- T11 — Major-bump-required field is meaningful only when BOTH
  versions parse cleanly; on parse-failure it is ``False``
  (schema-symmetric default).
- T12 — Pre-flight infallibility: every input combination produces
  a structured trace, never an exception (cross-lang contract).
- T13 — Live-module anchor: KNOWN_ENGINE_VERSIONS in the canonical
  sibling matches KNOWN_ENGINE_VERSIONS in
  :mod:`wirelang.persona_engine.migrate_version` byte-for-byte.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-migrate-version``
   canonical module surface and Python
   ``migrate_version_canonical.py``).
2. Re-derive the fixture vectors via
   ``python3 scripts/derive-migrate-version-fixtures.py > \
        tests/fixtures/migrate-version-cross-lang/fixtures.json``.
3. Update both Python and Rust test suites in the same PR.

Major-bump-disallowed branch — structural unreachability
--------------------------------------------------------

The ``MajorVersionBumpDisallowed`` failure mode is currently
structurally unreachable from the closed KNOWN_ENGINE_VERSIONS
set (all entries share major ``0``).  The wire-string constant is
nonetheless pinned in T03; an integration test would activate it
only after a major version is added to the closed set (a
coordinated three-place edit per :data:`KNOWN_ENGINE_VERSIONS`
docstring).  This is the same posture the live :class:`Migrate
VersionWorkflow.__init__` carries — the error class is defined
and tested in unit tests but not exercised by any production
inputs today.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pytest

# Cross-lang parity needs rfc8785 to serialise the canonical-trace.
# The shadow-CI lane runs without it (see
# `wirelang/persona/persona_canonical_form.py` resolver docstring);
# skip the entire suite on that lane via the same `importorskip`
# pattern already established in the sibling cross-lang test suites
# (Tag-34..Tag-37).
pytest.importorskip("rfc8785")

from wirelang.persona_engine.migrate_version import (
    KNOWN_ENGINE_VERSIONS as LIVE_KNOWN_ENGINE_VERSIONS,
)
from wirelang.persona_engine.migrate_version_canonical import (
    ACCEPTED_STATUS_VALUES,
    FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
    FAILURE_MODE_UNKNOWN_FROM_VERSION,
    FAILURE_MODE_UNKNOWN_TO_VERSION,
    FAILURE_MODE_VALUES,
    HASH_PREFIX,
    KNOWN_ENGINE_VERSIONS,
    MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
    MigrateVersionDecisionTrace,
    SHA256_HEX_LEN,
    STATUS_OK,
    STATUS_REJECTED,
    build_migrate_version_decision_trace,
    migrate_version_decision_trace_hash_prefixed,
    migrate_version_decision_trace_sha256_hex,
    serialize_migrate_version_decision_trace,
)


# ---------------------------------------------------------------------------
# Fixture file resolver.
# ---------------------------------------------------------------------------

#: Hops from this file to the repo root.  Same pattern as every
#: other Phase-3a cross-lang Python suite.
_HOPS_TO_REPO_ROOT = 4


def _fixtures_path() -> pathlib.Path:
    """Resolve the cross-lang fixture file relative to this test file."""
    p = pathlib.Path(__file__).resolve()
    for _ in range(_HOPS_TO_REPO_ROOT):
        p = p.parent
    return p / "tests" / "fixtures" / "migrate-version-cross-lang" / "fixtures.json"


@pytest.fixture(scope="module")
def fixtures_json() -> dict:
    with _fixtures_path().open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# T01 — Constants pin.
# ---------------------------------------------------------------------------


def test_t01_schema_constants_pin():
    """Cross-lang anchor: schema id is the byte-pin contract."""
    assert MIGRATE_VERSION_DECISION_TRACE_SCHEMA == (
        "wakir.persona-engine.migrate-version-canonical/1"
    )
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------------
# T02 — Accepted-status enum pin.
# ---------------------------------------------------------------------------


def test_t02_accepted_status_wire_strings():
    assert STATUS_OK == "ok"
    assert STATUS_REJECTED == "rejected"
    assert set(ACCEPTED_STATUS_VALUES) == {"ok", "rejected"}
    assert len(ACCEPTED_STATUS_VALUES) == 2


# ---------------------------------------------------------------------------
# T03 — Failure-mode enum pin.
# ---------------------------------------------------------------------------


def test_t03_failure_mode_wire_strings():
    assert FAILURE_MODE_UNKNOWN_FROM_VERSION == "UnknownFromVersion"
    assert FAILURE_MODE_UNKNOWN_TO_VERSION == "UnknownToVersion"
    assert FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED == (
        "MajorVersionBumpDisallowed"
    )
    assert set(FAILURE_MODE_VALUES) == {
        "",
        "UnknownFromVersion",
        "UnknownToVersion",
        "MajorVersionBumpDisallowed",
    }
    assert len(FAILURE_MODE_VALUES) == 4


# ---------------------------------------------------------------------------
# T04 — KNOWN_ENGINE_VERSIONS triple-anchor (canonical sibling).
# ---------------------------------------------------------------------------


def test_t04_known_engine_versions_pin():
    """The closed-set tuple is the byte-pin contract."""
    assert KNOWN_ENGINE_VERSIONS == (
        "0.2.0-pilot",
        "0.3.0-pilot",
        "0.4.0-pilot",
    )
    assert len(KNOWN_ENGINE_VERSIONS) == 3


# ---------------------------------------------------------------------------
# T05 — Determinism.
# ---------------------------------------------------------------------------


def test_t05_determinism_repeated_build():
    """Repeated builds produce byte-identical output (no nondeterminism)."""
    t1 = build_migrate_version_decision_trace(
        "0.3.0-pilot", "0.4.0-pilot"
    )
    t2 = build_migrate_version_decision_trace(
        "0.3.0-pilot", "0.4.0-pilot"
    )
    assert t1 == t2
    assert serialize_migrate_version_decision_trace(t1) == (
        serialize_migrate_version_decision_trace(t2)
    )
    assert migrate_version_decision_trace_sha256_hex(t1) == (
        migrate_version_decision_trace_sha256_hex(t2)
    )


# ---------------------------------------------------------------------------
# T06 — Wire-shape key order.
# ---------------------------------------------------------------------------


def test_t06_wire_shape_key_order_eleven_keys():
    """Top-level keys are alphabetically sorted; exactly 11 keys."""
    trace = build_migrate_version_decision_trace(
        "0.3.0-pilot", "0.4.0-pilot"
    )
    canonical_bytes = serialize_migrate_version_decision_trace(trace)
    # JCS guarantees alphabetic sort; we re-decode and verify keys.
    decoded = json.loads(canonical_bytes.decode("utf-8"))
    keys = list(decoded.keys())
    expected = [
        "accepted_status",
        "allow_major_bump",
        "failure_mode",
        "from_major",
        "from_minor",
        "from_version",
        "major_bump_required",
        "schema",
        "to_major",
        "to_minor",
        "to_version",
    ]
    assert keys == expected
    assert len(keys) == 11


# ---------------------------------------------------------------------------
# T07 — Hash shape.
# ---------------------------------------------------------------------------


def test_t07_hash_shape_prefixed_and_bare():
    trace = build_migrate_version_decision_trace(
        "0.3.0-pilot", "0.4.0-pilot"
    )
    bare = migrate_version_decision_trace_sha256_hex(trace)
    prefixed = migrate_version_decision_trace_hash_prefixed(trace)
    assert len(bare) == SHA256_HEX_LEN
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed.startswith(HASH_PREFIX)
    assert prefixed == HASH_PREFIX + bare
    assert len(prefixed) == len(HASH_PREFIX) + SHA256_HEX_LEN


# ---------------------------------------------------------------------------
# T08 — Cross-lang fixture file structure.
# ---------------------------------------------------------------------------


def test_t08_fixture_file_structure(fixtures_json):
    assert fixtures_json["schema_version"] == (
        MIGRATE_VERSION_DECISION_TRACE_SCHEMA
    )
    assert fixtures_json["known_engine_versions"] == list(
        KNOWN_ENGINE_VERSIONS
    )
    assert len(fixtures_json["fixtures"]) == 6
    expected_keys = {
        "name",
        "comment",
        "input",
        "trace",
        "trace_jcs_bytes_b64",
        "trace_jcs_bytes_len",
        "trace_sha256_hex",
        "trace_hash_prefixed",
    }
    for fx in fixtures_json["fixtures"]:
        assert set(fx.keys()) == expected_keys, (
            f"fixture {fx.get('name')} key set drift: "
            f"{set(fx.keys())} vs {expected_keys}"
        )


# ---------------------------------------------------------------------------
# T09 — Cross-lang per-vector byte-parity pin (parametrised).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_index",
    range(6),
    ids=lambda i: f"fixture-{i:02d}",
)
def test_t09_per_vector_byte_parity(fixtures_json, fixture_index):
    """Each fixture reproduces its pinned JCS bytes / hash byte-for-byte."""
    fx = fixtures_json["fixtures"][fixture_index]
    trace = build_migrate_version_decision_trace(
        fx["input"]["from_version"],
        fx["input"]["to_version"],
        allow_major_bump=fx["input"]["allow_major_bump"],
    )

    # The MigrateVersionDecisionTrace dict-projection equals the
    # pinned trace dict byte-for-byte.
    assert trace.to_canonical_dict() == fx["trace"], (
        f"{fx['name']}: trace dict drift"
    )

    # JCS bytes round-trip.
    jcs_bytes = serialize_migrate_version_decision_trace(trace)
    expected_bytes = base64.b64decode(fx["trace_jcs_bytes_b64"])
    assert jcs_bytes == expected_bytes, (
        f"{fx['name']}: JCS bytes drift"
    )
    assert len(jcs_bytes) == fx["trace_jcs_bytes_len"], (
        f"{fx['name']}: JCS bytes length drift"
    )

    # Hash round-trip.
    assert migrate_version_decision_trace_sha256_hex(trace) == (
        fx["trace_sha256_hex"]
    ), f"{fx['name']}: trace_sha256_hex drift"
    assert migrate_version_decision_trace_hash_prefixed(trace) == (
        fx["trace_hash_prefixed"]
    ), f"{fx['name']}: trace_hash_prefixed drift"


# ---------------------------------------------------------------------------
# T10 — Decision-order pin.
# ---------------------------------------------------------------------------


def test_t10_decision_order_from_before_to():
    """When both versions are unknown, the from-check fires first."""
    trace = build_migrate_version_decision_trace(
        "0.99.0-pilot", "0.98.0-pilot"
    )
    assert trace.accepted_status == STATUS_REJECTED
    assert trace.failure_mode == FAILURE_MODE_UNKNOWN_FROM_VERSION


# ---------------------------------------------------------------------------
# T11 — Major-bump-required schema-symmetric default.
# ---------------------------------------------------------------------------


def test_t11_major_bump_required_false_on_unparseable():
    """Unparseable input -> major_bump_required is False (default)."""
    trace = build_migrate_version_decision_trace(
        "not-a-version", "0.4.0-pilot"
    )
    assert trace.major_bump_required is False
    assert trace.from_major == 0
    assert trace.from_minor == 0


def test_t11_major_bump_required_true_on_cross_major_parsed():
    """Both versions parse, cross-major -> major_bump_required True.

    The trace itself shows ``major_bump_required=True`` even though
    the closed-set check rejects this combination (the closed set
    has only major-0 entries today).  This is operator-readable
    diagnostic data: a future operator who adds ``1.0.0-pilot`` to
    KNOWN_ENGINE_VERSIONS will see the bump-required signal
    immediately.
    """
    # Both parseable but neither (or only one) is in KNOWN today.
    # We hit UnknownFromVersion first, but the major_bump_required
    # diagnostic still echoes the cross-major reality.
    trace = build_migrate_version_decision_trace(
        "1.2.3-pilot", "2.3.4-pilot"
    )
    # Status is rejected (UnknownFromVersion fires first).
    assert trace.accepted_status == STATUS_REJECTED
    assert trace.failure_mode == FAILURE_MODE_UNKNOWN_FROM_VERSION
    # But the diagnostic still reflects cross-major.
    assert trace.major_bump_required is True
    assert trace.from_major == 1
    assert trace.to_major == 2


# ---------------------------------------------------------------------------
# T12 — Pre-flight infallibility.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "from_v,to_v,bump",
    [
        ("0.3.0-pilot", "0.4.0-pilot", False),
        ("0.3.0-pilot", "0.4.0-pilot", True),
        ("0.1.0-pilot", "0.4.0-pilot", False),  # unknown-from
        ("0.3.0-pilot", "0.5.0-pilot", False),  # unknown-to
        ("not-a-version", "0.4.0-pilot", False),  # unparseable-from
        ("0.3.0-pilot", "not-a-version", False),  # unparseable-to
        ("", "", False),  # double-empty
        (
            "longgggggggggggggggggggggg-bogus-tag",
            "0.4.0-pilot",
            False,
        ),  # arbitrary noise
    ],
)
def test_t12_infallibility(from_v, to_v, bump):
    """All inputs produce a structured trace, never an exception."""
    trace = build_migrate_version_decision_trace(
        from_v, to_v, allow_major_bump=bump
    )
    assert isinstance(trace, MigrateVersionDecisionTrace)
    assert trace.accepted_status in ACCEPTED_STATUS_VALUES
    assert trace.failure_mode in FAILURE_MODE_VALUES
    # Hash must compute (deferred to the serialise / hash helpers).
    h = migrate_version_decision_trace_sha256_hex(trace)
    assert len(h) == SHA256_HEX_LEN


# ---------------------------------------------------------------------------
# T13 — Live-module anchor.
# ---------------------------------------------------------------------------


def test_t13_live_module_known_engine_versions_byte_anchor():
    """Canonical sibling KNOWN_ENGINE_VERSIONS matches live module."""
    assert KNOWN_ENGINE_VERSIONS == LIVE_KNOWN_ENGINE_VERSIONS
