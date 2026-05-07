# SPDX-License-Identifier: Apache-2.0
"""Self-migration converter test pack (Phase-1b Sprint-2 Tag-1, S2-T1-02).

Coverage map (Tag-4-Skizze §3.4 edge-cases + V-907 pin-stability)
================================================================

1. **Happy-path v0 -> v1:** the v8 fixture migrates and the resulting
   canonical-subset dict hashes to ``PERSONA_HASH_PIN_V8_MIGRATED_TO_V1``
   (== ``PERSONA_HASH_PIN_V9``). This is the determinism anchor.
2. **No-op identity migration:** ``source == target`` returns the
   canonical subset unchanged (empty chain).
3. **Unknown target rejection:** a non-registered target version
   raises ``PersonaMigrationError``.
4. **Unknown source rejection:** a definition declaring a foreign
   ``schema_version`` raises ``PersonaMigrationError``.
5. **Caller-pin drift:** an incorrect ``expected_post_migration_hash``
   raises ``PersonaMigrationDeterminismError``.
6. **Run-to-run determinism:** running the converter twice on the
   same input yields byte-identical canonical-subset dicts.

Each test is hermetic — no network, no shared mutable state. Fixtures
are file-system reads from ``wirelang/tests/fixtures/persona_definitions/``,
created in Sprint-1 Tag-2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wirelang.persona import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PersonaMigrationDeterminismError,
    PersonaMigrationError,
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


def _fixture(name: str) -> Path:
    return FIXTURE_DIR / name


def test_v0_to_v1_migration_reproduces_v9_pin():
    """Determinism anchor: v8 -> v1 reproduces the v9 hex pin."""
    migrated = migrate_persona(
        _fixture("v8-persona-pre-framework.md"),
        target_schema_version=PERSONA_SCHEMA_VERSION_LATEST,
    )
    assert migrated["schema_version"] == "persona-v1"

    actual = compute_persona_hash_from_canonical(migrated)
    assert actual == PERSONA_HASH_PIN_V8_MIGRATED_TO_V1
    # Confirm the alias holds at runtime as the constants module documents.
    assert PERSONA_HASH_PIN_V8_MIGRATED_TO_V1 == PERSONA_HASH_PIN_V9


def test_no_op_migration_when_source_equals_target():
    """source == target produces the unchanged canonical subset."""
    v9_dict = migrate_persona(
        _fixture("v9-persona-framework-native.md"),
        target_schema_version="persona-v1",
    )
    # Same shape as a fresh canonical-subset extraction.
    assert v9_dict["schema_version"] == "persona-v1"
    # And the hash matches the v9 pin (== the v8-migrated pin).
    actual = compute_persona_hash_from_canonical(v9_dict)
    assert actual == PERSONA_HASH_PIN_V9


def test_unknown_target_version_raises():
    """A target outside ``PERSONA_SCHEMA_VERSION_LIST`` is rejected."""
    with pytest.raises(PersonaMigrationError, match="unknown target"):
        migrate_persona(
            _fixture("v8-persona-pre-framework.md"),
            target_schema_version="persona-v99",
        )


def test_unknown_source_version_raises():
    """A definition declaring an unregistered source is rejected."""
    foreign = {
        "name": "foreign-agent",
        "description": "fixture-free unit test",
        "tools": ["Read"],
        "schema_version": "persona-vX",
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
    with pytest.raises(PersonaMigrationError, match="unknown source"):
        migrate_persona(foreign, target_schema_version="persona-v1")


def test_caller_pin_drift_raises_determinism_error():
    """A wrong ``expected_post_migration_hash`` surfaces as drift."""
    bogus_pin = "sha256:" + ("0" * 64)
    with pytest.raises(PersonaMigrationDeterminismError, match="drift"):
        migrate_persona(
            _fixture("v8-persona-pre-framework.md"),
            target_schema_version="persona-v1",
            expected_post_migration_hash=bogus_pin,
        )


def test_migration_is_run_to_run_deterministic():
    """Running the converter twice yields byte-identical output dicts."""
    src = _fixture("v8-persona-pre-framework.md")
    out_a = migrate_persona(src, target_schema_version="persona-v1")
    out_b = migrate_persona(src, target_schema_version="persona-v1")
    assert out_a == out_b
    # And their hashes match (byte-determinism through JCS).
    h_a = compute_persona_hash_from_canonical(out_a)
    h_b = compute_persona_hash_from_canonical(out_b)
    assert h_a == h_b == PERSONA_HASH_PIN_V8_MIGRATED_TO_V1
