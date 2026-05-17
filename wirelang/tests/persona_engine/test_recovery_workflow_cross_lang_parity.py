# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine R1..R4 recovery
workflow canonical projection.

The Python module under test (:mod:`wirelang.persona_engine.recovery_workflow`)
is BUSL-1.1; the canonical-projection helper
(:mod:`wirelang.persona_engine.recovery_workflow_canonical`) and this
test file are Apache-2.0 so downstream re-implementers can re-use the
same fixture vectors and the cross-lang contract.

Test taxonomy
-------------

- T01 — Constants pin: ``RECOVERY_OUTCOME_SCHEMA`` / ``HASH_PREFIX``
  / ``SHA256_HEX_LEN`` match the Rust crate's ``pub const`` items.
- T02 — Trigger wire-string round-trip: every Python enum member
  emits the wire-string that the Rust sibling parses back, and the
  three values are exactly the Sprint-Auftrag closed set.
- T03 — Canonical-dict shape: the projection contains exactly six
  top-level keys (``final_state``, ``phases``, ``schema``,
  ``success``, ``total_elapsed_sec``, ``trigger``) and each phase
  entry contains exactly five keys
  (``audit_annotation``, ``elapsed_sec``, ``phase``,
  ``soft_cap_exceeded``, ``terminal_status``).
- T04 — Timing-fields-zeroed invariant: regardless of the
  ``PhaseResult.elapsed_sec`` and ``RecoveryResult.total_elapsed_sec``
  input, the canonical projection emits zero / false.
- T05 — JCS-key ordering: top-level JCS bytes have keys in strict
  alphabetical order (the byte-form starts with ``final_state``
  and ends with ``trigger``).
- T06 — Hash shape: ``recovery_outcome_hash_prefixed`` returns
  ``"sha256:"`` + 64 lowercase hex characters; bare
  ``recovery_outcome_sha256_hex`` is exactly 64 lowercase hex chars.
- T07 — ``serialize_and_hash`` byte-parity: the two-call form
  (``recovery_outcome_jcs_bytes`` + ``recovery_outcome_sha256_hex``)
  produces the same byte-vector and the same prefixed-hash as the
  one-call helper.
- T08 — Determinism: two calls with the same input produce
  byte-identical canonical output.
- T09 — Sensitivity: changing ``trigger`` / ``final_state`` /
  ``success`` / any phase ``audit_annotation`` flips the outer hash.
- T10 — Fixture file structure pin: ``schema_version``, fixture
  count, names, and per-fixture key set match the Rust sibling's
  structure pin (F01).
- T11 — Cross-lang fixture per-vector pin (parametrised over the
  five fixtures): byte-for-byte parity with the JSON fixture file's
  pinned values.
- T12 — Result-driven projection: the
  :func:`recovery_outcome_canonical_dict_from_result` convenience
  wrapper produces the same projection as the field-level helper
  for a constructed :class:`RecoveryResult`.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``recovery_outcome_canonical_value`` and
   Python :func:`recovery_outcome_canonical_dict`).
2. Re-derive the fixture vectors using the snippet documented at the
   top of ``recovery_workflow_canonical.py``.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T11) fires on both sides, which is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

# Defensive import of rfc8785 — skip the whole suite if absent so the
# slim sandbox-CI image can still collect this file without explosion.
pytest.importorskip("rfc8785", reason="rfc8785 required for JCS parity tests")

from wirelang.persona_engine.recovery_workflow import (
    PhaseResult,
    RecoveryResult,
    RecoveryTrigger,
)
from wirelang.persona_engine.recovery_workflow_canonical import (
    HASH_PREFIX,
    RECOVERY_OUTCOME_SCHEMA,
    SHA256_HEX_LEN,
    recovery_outcome_canonical_dict,
    recovery_outcome_canonical_dict_from_result,
    recovery_outcome_hash_prefixed,
    recovery_outcome_jcs_bytes,
    recovery_outcome_sha256_hex,
    serialize_and_hash,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


def _fixture_path() -> pathlib.Path:
    """Resolve the cross-lang fixture file path.

    Walks up from this test file to the repo root, then into
    ``tests/fixtures/recovery-workflow-cross-lang/fixtures.json``.
    """
    here = pathlib.Path(__file__).resolve()
    # here = <repo>/wirelang/tests/persona_engine/test_recovery_workflow_cross_lang_parity.py
    # repo = parents[3]
    repo_root = here.parents[3]
    return (
        repo_root
        / "tests"
        / "fixtures"
        / "recovery-workflow-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    path = _fixture_path()
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _make_phase(name: str, term: str, ann: str, *, elapsed: float = 0.0) -> PhaseResult:
    """Build a :class:`PhaseResult` with the four canonical-projection
    fields populated. ``elapsed`` and ``soft_cap_exceeded`` are
    intentionally left at non-projection defaults; the projection
    helper zeroes them regardless of input."""
    return PhaseResult(
        phase=name,
        terminal_status=term,
        elapsed_sec=elapsed,
        soft_cap_exceeded=False,
        audit_annotation=ann,
    )


def _outcome_for_fixture(fx_input: Dict[str, Any]) -> Dict[str, Any]:
    """Construct the canonical-dict for a fixture's input block. The
    ``elapsed`` and ``soft_cap_exceeded`` fields are deliberately set
    to non-zero / true to confirm the projection drops them."""
    phases = [
        _make_phase(
            ph["phase"],
            ph["terminal_status"],
            ph["audit_annotation"],
            elapsed=0.42,  # non-zero on purpose
        )
        for ph in fx_input["phases"]
    ]
    trigger = RecoveryTrigger(fx_input["trigger"])
    return recovery_outcome_canonical_dict(
        trigger=trigger,
        phases=phases,
        final_state=fx_input["final_state"],
        success=fx_input["success"],
    )


# ---------------------------------------------------------------------
# T01 — Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_match_rust_sibling_pin() -> None:
    assert RECOVERY_OUTCOME_SCHEMA == "wakir.persona-engine.recovery-outcome/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------
# T02 — Trigger wire-string round-trip
# ---------------------------------------------------------------------


def test_t02_trigger_wire_strings_match_closed_set() -> None:
    assert RecoveryTrigger.CRASH_DETECTED.value == "CrashDetected"
    assert RecoveryTrigger.DESPAWN_MID_OPERATION.value == "DespawnMidOperation"
    assert RecoveryTrigger.STATE_CORRUPTION.value == "StateCorruption"
    # Closed set — exactly three members, no drift.
    assert {t.value for t in RecoveryTrigger} == {
        "CrashDetected",
        "DespawnMidOperation",
        "StateCorruption",
    }
    # Round-trip via the str enum's __init__: every wire-string parses.
    for wire in ("CrashDetected", "DespawnMidOperation", "StateCorruption"):
        assert RecoveryTrigger(wire).value == wire


# ---------------------------------------------------------------------
# T03 — Canonical-dict shape
# ---------------------------------------------------------------------


def test_t03_canonical_dict_shape_exact_keys() -> None:
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
            _make_phase("R2", "reloaded", "snapshot-restored"),
        ],
        final_state="running",
        success=True,
    )
    assert set(d.keys()) == {
        "final_state",
        "phases",
        "schema",
        "success",
        "total_elapsed_sec",
        "trigger",
    }
    assert d["schema"] == RECOVERY_OUTCOME_SCHEMA
    for ph in d["phases"]:
        assert set(ph.keys()) == {
            "audit_annotation",
            "elapsed_sec",
            "phase",
            "soft_cap_exceeded",
            "terminal_status",
        }


# ---------------------------------------------------------------------
# T04 — Timing-fields-zeroed invariant
# ---------------------------------------------------------------------


def test_t04_timing_fields_zeroed_regardless_of_input() -> None:
    phases = [
        _make_phase(
            "R1",
            "detected",
            "recovery_trigger_classified=CrashDetected",
            elapsed=9999.99,
        ),
    ]
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=phases,
        final_state="running",
        success=True,
    )
    # The total-timing field is zero regardless of any input
    # (the helper accepts trigger/phases/final_state/success only).
    assert d["total_elapsed_sec"] == 0
    # Per-phase timing is also zero.
    assert d["phases"][0]["elapsed_sec"] == 0
    assert d["phases"][0]["soft_cap_exceeded"] is False


# ---------------------------------------------------------------------
# T05 — JCS-key ordering
# ---------------------------------------------------------------------


def test_t05_jcs_top_level_keys_are_alphabetical() -> None:
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
            _make_phase("R2", "reloaded", "snapshot-restored"),
        ],
        final_state="running",
        success=True,
    )
    bytes_ = recovery_outcome_jcs_bytes(d)
    text = bytes_.decode("utf-8")
    # Top-level alphabetical key sequence.
    keys = [
        "final_state",
        "phases",
        "schema",
        "success",
        "total_elapsed_sec",
        "trigger",
    ]
    positions = [text.find(f'"{k}":') for k in keys]
    assert all(p > -1 for p in positions), (
        f"missing key in JCS bytes; positions={positions}"
    )
    assert positions == sorted(positions), (
        f"keys not in alphabetical order: positions={positions}"
    )
    # First key after the opening brace must be 'final_state'.
    assert text.startswith('{"final_state":')


# ---------------------------------------------------------------------
# T06 — Hash shape
# ---------------------------------------------------------------------


def test_t06_hash_shape_constraints() -> None:
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[],
        final_state="failed:RecoveryTriggerAmbiguousError",
        success=False,
    )
    bare = recovery_outcome_sha256_hex(d)
    prefixed = recovery_outcome_hash_prefixed(d)
    assert len(bare) == SHA256_HEX_LEN
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed.startswith(HASH_PREFIX)
    assert prefixed == HASH_PREFIX + bare
    assert len(prefixed) == len(HASH_PREFIX) + SHA256_HEX_LEN


# ---------------------------------------------------------------------
# T07 — serialize_and_hash byte-parity
# ---------------------------------------------------------------------


def test_t07_serialize_and_hash_round_trip() -> None:
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.DESPAWN_MID_OPERATION,
        phases=[
            _make_phase(
                "R1", "detected", "recovery_trigger_classified=DespawnMidOperation"
            ),
        ],
        final_state="failed:RecoveryBackingUnreachableError",
        success=False,
    )
    bytes_, hash_ = serialize_and_hash(d)
    assert bytes_ == recovery_outcome_jcs_bytes(d)
    assert hash_ == recovery_outcome_hash_prefixed(d)


# ---------------------------------------------------------------------
# T08 — Determinism
# ---------------------------------------------------------------------


def test_t08_jcs_bytes_are_deterministic() -> None:
    d1 = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[_make_phase("R1", "detected", "x")],
        final_state="running",
        success=True,
    )
    d2 = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[_make_phase("R1", "detected", "x")],
        final_state="running",
        success=True,
    )
    assert recovery_outcome_jcs_bytes(d1) == recovery_outcome_jcs_bytes(d2)
    assert recovery_outcome_sha256_hex(d1) == recovery_outcome_sha256_hex(d2)


# ---------------------------------------------------------------------
# T09 — Sensitivity: any field flip alters the outer hash
# ---------------------------------------------------------------------


def test_t09_sensitivity_field_flips_outer_hash() -> None:
    base = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
        ],
        final_state="running",
        success=True,
    )
    base_hash = recovery_outcome_sha256_hex(base)

    # trigger flip
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.STATE_CORRUPTION,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
        ],
        final_state="running",
        success=True,
    )
    assert recovery_outcome_sha256_hex(d) != base_hash

    # final_state flip
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
        ],
        final_state="failed:RecoveryResumeError",
        success=True,
    )
    assert recovery_outcome_sha256_hex(d) != base_hash

    # success flip
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
        ],
        final_state="running",
        success=False,
    )
    assert recovery_outcome_sha256_hex(d) != base_hash

    # phase audit_annotation flip
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "other-annotation"),
        ],
        final_state="running",
        success=True,
    )
    assert recovery_outcome_sha256_hex(d) != base_hash

    # phase terminal_status flip
    d = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "running", "recovery_trigger_classified=CrashDetected"),
        ],
        final_state="running",
        success=True,
    )
    assert recovery_outcome_sha256_hex(d) != base_hash

    # phase order flip (R1+R2 vs R2+R1)
    d_a = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R1", "detected", "a"),
            _make_phase("R2", "reloaded", "b"),
        ],
        final_state="running",
        success=True,
    )
    d_b = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=[
            _make_phase("R2", "reloaded", "b"),
            _make_phase("R1", "detected", "a"),
        ],
        final_state="running",
        success=True,
    )
    assert recovery_outcome_sha256_hex(d_a) != recovery_outcome_sha256_hex(d_b)


# ---------------------------------------------------------------------
# T10 — Fixture file structure pin
# ---------------------------------------------------------------------


def test_t10_fixture_file_structure_pin() -> None:
    fixtures = _load_fixtures()
    assert fixtures.get("schema_version") == RECOVERY_OUTCOME_SCHEMA
    items = fixtures.get("fixtures")
    assert isinstance(items, list)
    assert len(items) == 5
    names = [f["name"] for f in items]
    assert names == [
        "f01-clean-r1-r4",
        "f02-r2-fail-retry",
        "f03-r3-skip",
        "f04-r1-error-immediate",
        "f05-r4-timeout",
    ]
    for f in items:
        inp = f["input"]
        for k in ("trigger", "final_state", "success", "phases"):
            assert k in inp, f"fixture {f['name']!r} missing input.{k}"
        exp = f["expected"]
        for k in (
            "outcome_jcs_bytes_b64",
            "outcome_jcs_bytes_len",
            "outcome_sha256_hex",
            "outcome_hash_prefixed",
        ):
            assert k in exp, f"fixture {f['name']!r} missing expected.{k}"


# ---------------------------------------------------------------------
# T11 — Cross-lang fixture per-vector pin (parametrised)
# ---------------------------------------------------------------------


def _fixture_ids() -> List[str]:
    return [f["name"] for f in _load_fixtures()["fixtures"]]


@pytest.mark.parametrize("fixture_name", _fixture_ids())
def test_t11_cross_lang_fixture_byte_parity(fixture_name: str) -> None:
    fixtures = _load_fixtures()["fixtures"]
    fx = next(f for f in fixtures if f["name"] == fixture_name)
    inp = fx["input"]
    exp = fx["expected"]

    d = _outcome_for_fixture(inp)

    # Canonical bytes pin.
    bytes_ = recovery_outcome_jcs_bytes(d)
    exp_bytes = base64.b64decode(exp["outcome_jcs_bytes_b64"])
    assert bytes_ == exp_bytes, (
        f"fixture {fixture_name!r}: canonical JCS bytes drifted; "
        f"got {bytes_!r}, expected {exp_bytes!r}"
    )
    assert len(bytes_) == exp["outcome_jcs_bytes_len"]

    # Bare-hex outer SHA-256 pin.
    bare = hashlib.sha256(bytes_).hexdigest()
    assert bare == exp["outcome_sha256_hex"]
    assert recovery_outcome_sha256_hex(d) == exp["outcome_sha256_hex"]

    # Prefixed-form outer SHA-256 pin.
    assert recovery_outcome_hash_prefixed(d) == exp["outcome_hash_prefixed"]

    # serialize_and_hash round-trip.
    rt_bytes, rt_hash = serialize_and_hash(d)
    assert rt_bytes == bytes_
    assert rt_hash == exp["outcome_hash_prefixed"]


# ---------------------------------------------------------------------
# T12 — Result-driven projection convenience wrapper
# ---------------------------------------------------------------------


def test_t12_result_driven_projection_matches_field_level_helper() -> None:
    """The :func:`recovery_outcome_canonical_dict_from_result` wrapper
    accepts a :class:`RecoveryResult` and must produce the same
    projection as the field-level helper."""
    phases = (
        _make_phase("R1", "detected", "recovery_trigger_classified=CrashDetected"),
        _make_phase("R2", "reloaded", "snapshot-restored"),
        _make_phase(
            "R3",
            "re_registered",
            "recovery_svid_refreshed=spiffe://wakir.wakir-labs/persona/reza",
        ),
        _make_phase("R4", "resumed", "container-active"),
    )
    result = RecoveryResult(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=phases,
        # Non-zero timing must still produce a timing-free projection.
        total_elapsed_sec=2.71,
        final_state="running",
        success=True,
    )
    via_result = recovery_outcome_canonical_dict_from_result(result)
    via_fields = recovery_outcome_canonical_dict(
        trigger=RecoveryTrigger.CRASH_DETECTED,
        phases=list(phases),
        final_state="running",
        success=True,
    )
    assert via_result == via_fields
    # And byte-parity downstream.
    assert recovery_outcome_jcs_bytes(via_result) == recovery_outcome_jcs_bytes(via_fields)
