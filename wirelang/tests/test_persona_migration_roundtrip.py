# SPDX-License-Identifier: Apache-2.0
"""Self-migration cross-version roundtrip test pack (Phase-1b Sprint-2 Tag-2, S2-T1-04).

Coverage map (Sprint-2-Tag-2 auftrag)
=====================================

Phase-1b carries a single registered migration step (``V0ToV1Step``).
Once HR ratifies a v2 format, the chain becomes ``v0 -> v1 -> v2``;
until then the cross-version roundtrip surface is:

- **v0 -> v1 single-step:** byte-equivalent to the v9 fixture pin.
- **v1 -> v1 idempotence:** running the converter on an already-
  latest dict is a no-op (empty chain) and produces the same hash.
- **migrate-twice equivalence:** ``migrate(migrate(v8)) == migrate(v8)``
  — the second call sees ``schema_version=persona-v1`` and short-
  circuits via the empty-chain branch.
- **dict-vs-Path equivalence:** the same logical persona, presented
  as a ``Path`` or as an in-memory ``dict``, hashes identically
  (the public-API input shape does not bleed into the canonical
  subset).
- **all-versions reach LATEST:** every entry in
  ``PERSONA_SCHEMA_VERSION_LIST`` resolves a chain to
  ``PERSONA_SCHEMA_VERSION_LATEST`` without raising — the full
  schema-version surface is reachable.
- **caller-pin form acceptance:** a *correct* pin in either bare-hex
  or full ``sha256:`` form passes the determinism check.

M-3 anchor (Tag-4-Skizze §4.4): migration is **not** required to be
invertible. There is intentionally no ``v1 -> v0`` test in this
pack — adding one would constitute a v_n+1 -> v_n step that violates
A-2 additiv-only-forward-compat. The ``v1 -> v1`` idempotence test
is the legitimate roundtrip that the Phase-1b registry supports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wirelang.persona import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PERSONA_SCHEMA_VERSION_LIST,
    compute_persona_hash_from_canonical,
    migrate_persona,
)
from wirelang.persona._internal.pin_pack_constants import (
    PERSONA_HASH_PIN_V8_MIGRATED_TO_V1,
    PERSONA_HASH_PIN_V9,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "persona_definitions"
)


def _v8_path() -> Path:
    return FIXTURE_DIR / "v8-persona-pre-framework.md"


def _v9_path() -> Path:
    return FIXTURE_DIR / "v9-persona-framework-native.md"


def _v0_dict_aligned_with_v9() -> dict[str, Any]:
    """In-memory v0 dict whose content is byte-equivalent to the v8 file.

    Mirrors the v8 fixture's front-matter exactly so that
    ``migrate(dict)`` and ``migrate(Path)`` must produce equal hashes.
    """
    return {
        "name": "pre-framework-agent",
        "description": (
            "Pre-framework persona fixture for self-migration vector "
            "(v8, schema persona-v0-ish — flagged as unsupported)."
        ),
        "tools": ["Read"],
        "schema_version": "persona-v0",
        "identity_pinned": {
            "cross_review_zones": [],
            "authority": {
                "push_remote": False,
                "budget_cap_eur_per_month": 0,
                "sub_delegation": False,
            },
            "hierarchy": {
                "reports_to": "cto",
                "escalation": "cto",
            },
        },
    }


# ---------------------------------------------------------------
# A. v0 -> v1 single-step pin equivalence (re-anchor of Tag-1)
# ---------------------------------------------------------------

def test_v0_to_v1_single_step_matches_v9_pin():
    """The v8 fixture, after migration, hashes to the v9 pin."""
    out = migrate_persona(_v8_path(), target_schema_version="persona-v1")
    actual = compute_persona_hash_from_canonical(out)
    assert actual == PERSONA_HASH_PIN_V9
    assert actual == PERSONA_HASH_PIN_V8_MIGRATED_TO_V1


# ---------------------------------------------------------------
# B. v1 -> v1 idempotence
# ---------------------------------------------------------------

def test_v1_to_v1_idempotence_via_path():
    """``migrate(v9) -> v1`` is a no-op (empty chain) and pin-stable."""
    out = migrate_persona(_v9_path(), target_schema_version="persona-v1")
    assert out["schema_version"] == "persona-v1"
    actual = compute_persona_hash_from_canonical(out)
    assert actual == PERSONA_HASH_PIN_V9


def test_v1_to_v1_idempotence_via_dict():
    """Same as the path-based idempotence, but with a dict input."""
    # Build a v1 dict by migrating v8 once, then feed the result back in.
    v1_dict = migrate_persona(_v8_path())
    out = migrate_persona(v1_dict, target_schema_version="persona-v1")
    assert out["schema_version"] == "persona-v1"
    h_first = compute_persona_hash_from_canonical(v1_dict)
    h_second = compute_persona_hash_from_canonical(out)
    assert h_first == h_second == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------
# C. migrate-twice equivalence (compose-stability)
# ---------------------------------------------------------------

def test_migrate_twice_is_equivalent_to_migrate_once():
    """``migrate(migrate(v8))`` produces the same hash as ``migrate(v8)``."""
    once = migrate_persona(_v8_path())
    twice = migrate_persona(once)
    h1 = compute_persona_hash_from_canonical(once)
    h2 = compute_persona_hash_from_canonical(twice)
    assert h1 == h2 == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------
# D. dict-vs-Path equivalence at the public API
# ---------------------------------------------------------------

def test_dict_and_path_inputs_produce_equal_hashes():
    """``migrate(Path)`` and ``migrate(dict)`` of equivalent v0 sources
    converge on the same v1 hash — the input shape doesn't leak."""
    out_from_path = migrate_persona(_v8_path())
    out_from_dict = migrate_persona(_v0_dict_aligned_with_v9())
    h_path = compute_persona_hash_from_canonical(out_from_path)
    h_dict = compute_persona_hash_from_canonical(out_from_dict)
    assert h_path == h_dict == PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------
# E. all-versions-reach-LATEST coverage
# ---------------------------------------------------------------

@pytest.mark.parametrize("source_version", PERSONA_SCHEMA_VERSION_LIST)
def test_every_known_source_resolves_to_latest(source_version: str):
    """For each registered schema version, the chain to LATEST resolves.

    For ``source_version == LATEST`` the chain is empty (no-op).
    For any other version the chain is non-empty and the migrated
    dict carries ``schema_version == LATEST``.
    """
    if source_version == "persona-v0":
        path = _v8_path()
    elif source_version == "persona-v1":
        path = _v9_path()
    else:
        pytest.skip(f"no fixture for {source_version}")

    out = migrate_persona(
        path, target_schema_version=PERSONA_SCHEMA_VERSION_LATEST
    )
    assert out["schema_version"] == PERSONA_SCHEMA_VERSION_LATEST


# ---------------------------------------------------------------
# F. caller-pin form acceptance (positive twin of the drift test)
# ---------------------------------------------------------------

def test_correct_caller_pin_full_form_passes():
    """A correct pin in ``sha256:<hex>`` form does not raise."""
    _ = migrate_persona(
        _v8_path(),
        target_schema_version="persona-v1",
        expected_post_migration_hash=PERSONA_HASH_PIN_V9,
    )


def test_correct_caller_pin_bare_hex_form_passes():
    """A correct pin in bare-hex form does not raise."""
    bare_hex = PERSONA_HASH_PIN_V9.removeprefix("sha256:")
    assert len(bare_hex) == 64
    _ = migrate_persona(
        _v8_path(),
        target_schema_version="persona-v1",
        expected_post_migration_hash=bare_hex,
    )
