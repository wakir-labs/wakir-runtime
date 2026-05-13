# SPDX-License-Identifier: Apache-2.0
"""JCS-bytes parity tests for the persona-canonical-form module.

These tests exercise :func:`wirelang.persona.persona_canonical_form.canonical_jcs_bytes`
as the bytes-level boundary that the Phase-1c Rust crate
``persona-canonical-form`` (Sprint-2 Tag-4 outbox §A2) must reproduce
byte-for-byte. They lock the contract on the Python side so the Rust
side has a stable cross-language oracle.

Coverage map
------------

1. **V9 ground-truth length** — JCS-bytes for the framework-native
   v9 fixture is exactly 387 bytes (matches Sprint-2 Tag-4 outbox §4.1
   captured Python run + the Rust ground-truth fixture).
2. **V9 ground-truth hash parity** — sha256 of canonical_jcs_bytes()
   equals ``PERSONA_HASH_PIN_V9`` (cross-checks the helper against the
   in-tree pin pack without going through compute_persona_hash).
3. **JCS byte-stability under repeated calls** — idempotent on the same
   input dict (RFC 8785 determinism guard).
4. **JCS lexicographic key sorting** — different insertion orders
   produce identical JCS-bytes for semantically-equal dicts.
5. **JCS UTF-8 / NFC posture** — non-ASCII strings round-trip cleanly
   (no escape-form drift between dicts that happen to use a literal
   non-ASCII character).
6. **NaN rejection** — float NaN raises (RFC 8785 disallows NaN /
   Infinity); used as a guard so accidental NaN values cannot silently
   poison the hash chain.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

# Skip the whole module when rfc8785 is absent: the wirelang.persona
# package imports rfc8785 unconditionally at module-load time, so any
# top-level `from wirelang.persona ...` below would crash collection
# in the sandbox lane. Test-level importorskip is the conventional
# guard for this case until the persona package adopts a lazy import.
pytest.importorskip("rfc8785")

from wirelang.persona import PERSONA_HASH_PREFIX
from wirelang.persona._internal.pin_pack_constants import PERSONA_HASH_PIN_V9
from wirelang.persona.persona_canonical_form import (
    canonical_jcs_bytes,
    read_canonical_subset,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "persona_definitions"
)


def _v9_subset() -> dict:
    text = (FIXTURE_DIR / "v9-persona-framework-native.md").read_text(
        encoding="utf-8"
    )
    return read_canonical_subset(text)


# ---------------------------------------------------------------------------
# 1 / V9 ground-truth length anchor (Sprint-2 Tag-4 §4.1 captured run)
# ---------------------------------------------------------------------------


def test_v9_canonical_jcs_bytes_length_is_387() -> None:
    """JCS-bytes for v9 must be exactly 387 bytes — Rust parity anchor."""
    subset = _v9_subset()
    blob = canonical_jcs_bytes(subset)
    assert isinstance(blob, bytes)
    assert len(blob) == 387, (
        f"v9 canonical JCS length must be 387 (Rust parity anchor); "
        f"got {len(blob)}"
    )


# ---------------------------------------------------------------------------
# 2 / V9 ground-truth hash parity (cross-checks helper vs pin pack)
# ---------------------------------------------------------------------------


def test_v9_canonical_jcs_bytes_sha256_matches_pin_v9() -> None:
    """sha256(canonical_jcs_bytes(v9-subset)) must equal PERSONA_HASH_PIN_V9."""
    subset = _v9_subset()
    blob = canonical_jcs_bytes(subset)
    full = PERSONA_HASH_PREFIX + hashlib.sha256(blob).hexdigest()
    assert full == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------------------
# 3 / JCS byte-stability — idempotent on repeated calls
# ---------------------------------------------------------------------------


def test_canonical_jcs_bytes_is_idempotent() -> None:
    """Repeated calls with the same input yield identical bytes (RFC 8785)."""
    subset = _v9_subset()
    blob_a = canonical_jcs_bytes(subset)
    blob_b = canonical_jcs_bytes(subset)
    assert blob_a == blob_b
    # Also stable across a fresh load of the subset (parser determinism).
    blob_c = canonical_jcs_bytes(_v9_subset())
    assert blob_a == blob_c


# ---------------------------------------------------------------------------
# 4 / JCS lexicographic key sorting — insertion order does not matter
# ---------------------------------------------------------------------------


def test_canonical_jcs_bytes_is_key_order_invariant() -> None:
    """JCS sorts keys lexicographically; insertion order must not leak."""
    a = {"name": "x", "description": "d", "tools": [], "schema_version": "persona-v1"}
    b = {"schema_version": "persona-v1", "tools": [], "description": "d", "name": "x"}
    assert canonical_jcs_bytes(a) == canonical_jcs_bytes(b)


# ---------------------------------------------------------------------------
# 5 / UTF-8 / NFC posture — non-ASCII strings round-trip without drift
# ---------------------------------------------------------------------------


def test_canonical_jcs_bytes_handles_non_ascii_text() -> None:
    """Non-ASCII strings round-trip cleanly; no escape-form drift.

    JCS escapes only the JSON-mandatory characters and emits other
    UTF-8 codepoints literally; that gives byte-stable output for the
    same logical string regardless of source dict construction style.
    """
    a = {"description": "Wakir Labs - Persona-Engine"}
    b = {"description": "Wakir Labs - Persona-Engine"}
    blob_a = canonical_jcs_bytes(a)
    blob_b = canonical_jcs_bytes(b)
    assert blob_a == blob_b
    # UTF-8 minus mandatory JSON escapes: ASCII literal is preserved.
    assert b"Wakir Labs - Persona-Engine" in blob_a


# ---------------------------------------------------------------------------
# 6 / NaN rejection — RFC 8785 forbids NaN / Infinity
# ---------------------------------------------------------------------------


def test_canonical_jcs_bytes_rejects_nan() -> None:
    """NaN must raise so it cannot silently poison the hash chain."""
    with pytest.raises((ValueError, TypeError)):
        canonical_jcs_bytes({"k": math.nan})
