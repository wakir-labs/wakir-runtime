# SPDX-License-Identifier: Apache-2.0
"""``V1ToV2Step`` migration tests (Phase-1b Sprint-3 Tag-3, V10-Migration-Pfad).

Coverage map (Tag-1-Sketch §3 + §4 + §5)
========================================

This pack tests the converter-side V1-to-V2 migration step that the
Tag-1 sketch (``wirelang/specs/persona-schema-v10-migration-vorbereitung.md``)
specified as the Sprint-3 implementation surface. Tag-2 authored the
``persona-v2`` JSON-Schema; Tag-3 lands the converter step itself.

1. **V1-to-V2 happy-path:** ``migrate_persona(v9, target=persona-v2)``
   produces a v2-shape dict that hashes to
   :data:`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`. Determinism anchor.

2. **V1-to-V2 input-unchanged:** the input v9 dict is **not** mutated by
   the migration call (Tag-1-Sketch §3 step rule 2 / Sprint-2 Tag-2
   non-mutation discipline carried forward).

3. **V1-to-V2 source-version-strict:** a dict that already declares
   ``schema_version=persona-v2`` does **not** route through
   ``V1ToV2Step``; the resolver short-circuits with an empty chain
   and returns the input unchanged. Mirrors Sprint-2 Tag-2's
   "no-op identity migration" pattern for the v2 endpoint.

4. **V1-to-V2 run-to-run determinism:** two successive migrations of
   the same v9 fixture produce byte-identical output dicts. Anchor on
   the JCS+SHA-256 byte-determinism through the canonical-subset.

5. **V0-to-V2 multi-step chain (M-1 direct anchor):** the v8 fixture,
   migrated through the chain ``[V0ToV1Step(), V1ToV2Step()]`` to
   ``target=persona-v2``, hashes to
   :data:`PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`, which equals
   :data:`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` by construction. This
   is the Sprint-3 Tag-1 §3.2 multi-step linear-chain direct-anchor
   that the Sprint-2 M-Konsens-Marker companion memo flagged as
   currently indirect (M-1).

6. **V2-to-V1 inverse-not-supported (negative):** requesting a
   ``persona-v2 -> persona-v1`` migration raises
   :class:`PersonaMigrationError`. M-3 non-invertibility anchor still
   holds in v2: forward-only, additiv-only, no inverse step is ever
   registered (Default-Lock A-2). Mirrors the Sprint-2 Tag-2 absence
   of any ``v_n+1 -> v_n`` test.

Each test is hermetic — no network, no shared mutable state. Fixtures
are file-system reads from
``wirelang/tests/fixtures/persona_definitions/``, created in Sprint-1
Tag-2.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

# Skip the whole module when rfc8785 is absent: the wirelang.persona
# package imports rfc8785 unconditionally at module-load time, so any
# top-level `from wirelang.persona ...` below would crash collection
# in the sandbox lane. Test-level importorskip is the conventional
# guard for this case until the persona package adopts a lazy import.
pytest.importorskip("rfc8785")

from wirelang.persona import (
    PersonaMigrationError,
    compute_persona_hash_from_canonical,
    migrate_persona,
)
from wirelang.persona._internal.migration_steps import (
    REGISTERED_STEPS,
    V0ToV1Step,
    V1ToV2Step,
)
from wirelang.persona._internal.pin_pack_constants import (
    PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
    PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
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


# ---------------------------------------------------------------
# 1. Single-step V1-to-V2 happy-path (determinism anchor)
# ---------------------------------------------------------------


def test_v1_to_v2_pin_match() -> None:
    """The v9 fixture, lifted via V1ToV2Step, hashes to the V9->V2 pin."""
    migrated = migrate_persona(
        _v9_path(),
        target_schema_version="persona-v2",
    )
    assert migrated["schema_version"] == "persona-v2"

    actual = compute_persona_hash_from_canonical(migrated)
    assert actual == PERSONA_HASH_PIN_V9_MIGRATED_TO_V2
    # The migrated-V2 pin is intentionally distinct from the V9 pin
    # because the canonical-subset includes schema_version in JCS.
    # Confirming non-equality at runtime is the regression catch.
    from wirelang.persona._internal.pin_pack_constants import (
        PERSONA_HASH_PIN_V9,
    )
    assert actual != PERSONA_HASH_PIN_V9


# ---------------------------------------------------------------
# 2. V1-to-V2 input-unchanged (non-mutation discipline)
# ---------------------------------------------------------------


def test_v1_to_v2_does_not_mutate_input_dict() -> None:
    """The migration call is non-mutating for in-memory dict inputs."""
    # Build a v1-shape dict by lifting v8 once; this gives us a
    # legitimate persona-v1 dict without re-implementing the fixture
    # parser here.
    v1_dict = migrate_persona(_v8_path())
    v1_snapshot = copy.deepcopy(v1_dict)

    _ = migrate_persona(v1_dict, target_schema_version="persona-v2")

    # Caller's dict is unchanged — all keys, all values.
    assert v1_dict == v1_snapshot
    # Specifically schema_version stayed at persona-v1 in the input.
    assert v1_dict["schema_version"] == "persona-v1"


# ---------------------------------------------------------------
# 3. V1-to-V2 source-version-strict (already-target short-circuit)
# ---------------------------------------------------------------


def test_v1_to_v2_target_already_met_is_noop() -> None:
    """A dict already at persona-v2 short-circuits to an empty chain."""
    # Construct a v2-shape dict by migrating v9 forward once.
    v2_dict = migrate_persona(_v9_path(), target_schema_version="persona-v2")
    assert v2_dict["schema_version"] == "persona-v2"

    # Feeding it back into the converter with the same target is a no-op:
    # the resolver sees source == target and returns an empty chain.
    out = migrate_persona(v2_dict, target_schema_version="persona-v2")

    assert out["schema_version"] == "persona-v2"
    # Hash-equivalence: the no-op output produces the same V9-migrated-V2
    # pin as the freshly-migrated v9 dict.
    h_first = compute_persona_hash_from_canonical(v2_dict)
    h_second = compute_persona_hash_from_canonical(out)
    assert h_first == h_second == PERSONA_HASH_PIN_V9_MIGRATED_TO_V2


# ---------------------------------------------------------------
# 4. V1-to-V2 run-to-run determinism
# ---------------------------------------------------------------


def test_v1_to_v2_is_run_to_run_deterministic() -> None:
    """Running the converter twice yields byte-identical output dicts."""
    out_a = migrate_persona(_v9_path(), target_schema_version="persona-v2")
    out_b = migrate_persona(_v9_path(), target_schema_version="persona-v2")
    assert out_a == out_b

    # And their hashes match the pinned value (byte-determinism through JCS).
    h_a = compute_persona_hash_from_canonical(out_a)
    h_b = compute_persona_hash_from_canonical(out_b)
    assert h_a == h_b == PERSONA_HASH_PIN_V9_MIGRATED_TO_V2


# ---------------------------------------------------------------
# 5. Multi-step V0-to-V2 chain (M-1 direct anchor)
# ---------------------------------------------------------------


def test_v0_to_v2_full_chain_pin_match() -> None:
    """v8 -> [V0ToV1Step, V1ToV2Step] -> v2 hashes to the chain pin.

    This is the **M-1 (linear-chain) direct-anchor** from Tag-1-Sketch
    §3.2: a multi-step chain whose endpoints differ in two
    ``schema_version`` lifts. The Sprint-2 M-Konsens-Marker companion
    memo flagged this as currently indirect; Sprint-3 Tag-3 lands the
    direct test vector.
    """
    migrated = migrate_persona(
        _v8_path(),
        target_schema_version="persona-v2",
    )
    assert migrated["schema_version"] == "persona-v2"

    actual = compute_persona_hash_from_canonical(migrated)
    assert actual == PERSONA_HASH_PIN_V8_MIGRATED_TO_V2
    # And the alias holds at runtime as the constants module documents:
    # the chain endpoint is byte-identical to the V9-migrated-V2 endpoint
    # because v8 and v9 share every canonical-subset key except
    # schema_version, and the chain always ends at persona-v2.
    assert (
        PERSONA_HASH_PIN_V8_MIGRATED_TO_V2
        == PERSONA_HASH_PIN_V9_MIGRATED_TO_V2
    )

    # Sanity-anchor the chain-shape: the registered step list contains
    # both lifts in linear order. Replacing this assertion with a
    # registry-introspection helper would be over-engineering for a
    # 2-step chain; an explicit assertion catches accidental re-ordering.
    sources = [step.source_version for step in REGISTERED_STEPS]
    targets = [step.target_version for step in REGISTERED_STEPS]
    assert sources == ["persona-v0", "persona-v1"]
    assert targets == ["persona-v1", "persona-v2"]
    # And the concrete classes are the expected ones (no plugin magic):
    assert isinstance(REGISTERED_STEPS[0], V0ToV1Step)
    assert isinstance(REGISTERED_STEPS[1], V1ToV2Step)


# ---------------------------------------------------------------
# 6. V2-to-V1 inverse-not-supported (negative — M-3 non-invertibility)
# ---------------------------------------------------------------


def test_v2_to_v1_inverse_is_not_supported() -> None:
    """Requesting a backwards migration raises PersonaMigrationError.

    Default-Lock A-2 is forward-only / additiv-only / linear-chain;
    no inverse step is ever registered. The resolver walks forward
    from the source ``schema_version`` looking for a step, finds
    none for ``persona-v2 -> persona-v1`` (because no such step
    exists in REGISTERED_STEPS), and raises before exhausting the
    32-step cycle guard.
    """
    v2_dict = migrate_persona(_v9_path(), target_schema_version="persona-v2")
    assert v2_dict["schema_version"] == "persona-v2"

    with pytest.raises(PersonaMigrationError, match="no migration step"):
        migrate_persona(v2_dict, target_schema_version="persona-v1")
