# SPDX-License-Identifier: Apache-2.0
"""V-907 self-migration step registry (Phase-1b Sprint-2 Tag-1, S2-T1-02).

Each :class:`MigrationStep` captures one schema-version transition
``v_n -> v_{n+1}``. Multi-step chains (``v_n -> v_{n+m}``) are resolved
by composition in :mod:`wirelang.persona.persona_migration`.

Design anchors (Tag-4-Skizze §3.2 + Default-Lock A-1/A-2/A-3 ratified
2026-05-07 ~10:00 CEST):

- **A-1 Mock-Format-baseline:** the V-907 mock canonical subset is the
  hash-input shape; steps operate on canonical-subset dicts, never on
  raw markdown.
- **A-2 semver-major-only, additiv-only, linear-chain:** every step is
  additive on the v-next side. Removing a key in v_{n+1} is forbidden
  (forward-compat regression).
- **A-3 frontmatter-canonical in-hash, body out-of-hash:** body-edits
  are not the converter's concern. Steps operate on the canonical
  subset that JCS will hash.
- **D-2 mitigation:** every default value the step injects is written
  *explicitly* in code, never via JSON-Schema default-inference. This
  guarantees byte-determinism of the output (Tag-4 §2.3).

Registry posture
----------------

:data:`REGISTERED_STEPS` is a flat tuple. The resolver in
:mod:`wirelang.persona.persona_migration` performs an exact-match
lookup on ``source_version`` and walks the chain forward until
``target_version`` is reached. No reflection, no string parsing,
no plugin discovery — auditability over magic.
"""

from __future__ import annotations

import copy
from typing import Any, Final, Protocol, runtime_checkable


@runtime_checkable
class MigrationStep(Protocol):
    """Single-step migration ``v_n -> v_{n+1}``.

    Concrete implementations must be deterministic: ``apply(d)`` called
    twice with byte-identical input must produce byte-identical output
    (the converter relies on this for V-907 pin-stability).
    """

    source_version: str
    target_version: str

    def apply(self, definition_dict: dict[str, Any]) -> dict[str, Any]:
        """Return a new dict at ``target_version`` shape.

        The input dict is **not** mutated; implementations deep-copy
        before editing.
        """
        ...


class V0ToV1Step:
    """``persona-v0 -> persona-v1`` schema-version lift.

    Per Tag-4-Skizze §3.2 R1-R4 and Default-Lock A-1/A-2/A-3:
    the v0 to v1 transition is a schema-version edit only. All
    other top-level keys, the full ``identity_pinned`` block, and
    the markdown body (out-of-hash per A-3) pass through unchanged.

    This is the alignment step from the pre-framework era onto the
    Tag-2 mock canonical subset, not a content extension. With the
    Sprint-3 Tag-3 ``V1ToV2Step`` registered below, v0 inputs resolve
    to the chain ``[V0ToV1Step(), V1ToV2Step()]`` automatically when
    the caller requests ``target_schema_version="persona-v2"``.
    """

    source_version: Final[str] = "persona-v0"
    target_version: Final[str] = "persona-v1"

    def apply(self, definition_dict: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(definition_dict, dict):
            raise TypeError(
                "V0ToV1Step.apply expects a dict, got "
                f"{type(definition_dict).__name__}"
            )
        actual_source = definition_dict.get("schema_version")
        if actual_source != self.source_version:
            raise ValueError(
                "V0ToV1Step.apply expected schema_version="
                f"{self.source_version!r}, got {actual_source!r}"
            )
        out = copy.deepcopy(definition_dict)
        out["schema_version"] = self.target_version
        return out


class V1ToV2Step:
    """``persona-v1 -> persona-v2`` schema-version lift.

    Per Tag-1-Sketch §3 (Phase-1b Sprint-3 Tag-1, V10-Migration-
    Vorbereitung) and Default-Lock A-1/A-2/A-3: the v1 to v2 transition
    is a schema-version edit only. The persona-v2 schema authored at
    Tag-2 (``wirelang/schemas/persona-v2.json``) opens a closed
    allow-list of additive optional fields at the top level
    (``model_pin``, ``spawn_constraints``) and inside
    ``identity_pinned`` (``identity_doc_ref``, ``persona_owner_role``,
    ``governance_revision``), plus three reserved top-level keys
    (``recovery_drill``, ``wat_bridge_overrides``,
    ``container_bridge_spec``). None of those are *injected* by this
    step:

    - **Additive optional fields** default to absent. The
      canonical-subset extractor drops keys outside
      ``CANONICAL_TOP_LEVEL_KEYS`` and outside
      ``CANONICAL_IDENTITY_PINNED_KEYS``, so lifting an unaugmented
      v9-shape input yields a canonical-subset dict that differs from
      the v9 dict only in ``schema_version``.
    - **Reserved fields** (Option D-A pin-stability discipline,
      Tag-1-Sketch §6) hash identically to absent when present-but-
      empty, because the canonical-subset extractor drops empty
      mappings. The Sprint-3 Tag-N reserved-field round-trip pack
      (§4.3) is the canary for this discipline.

    D-2 mitigation (Tag-4-Skizze §2.3): no default-injection in this
    step; every output byte is explicit. The only mutation is the
    ``schema_version`` const flip.

    Pin-pack consequence (Tag-1-Sketch §3): the canonical-subset
    *includes* ``schema_version`` in the JCS bytes, so lifting v1 to v2
    yields a *new* hash. The migrated-v9 pin and the migrated-v8 pin
    (chain ``v0 -> v1 -> v2``) are equal by construction
    (``PERSONA_HASH_PIN_V8_MIGRATED_TO_V2 ==
    PERSONA_HASH_PIN_V9_MIGRATED_TO_V2``) because v8 and v9 share every
    canonical-subset key except ``schema_version`` and the chain's
    endpoint always sets ``schema_version=persona-v2``. This is the
    M-1 (linear-chain) direct-anchor that Sprint-2 flagged as
    currently indirect.
    """

    source_version: Final[str] = "persona-v1"
    target_version: Final[str] = "persona-v2"

    def apply(self, definition_dict: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(definition_dict, dict):
            raise TypeError(
                "V1ToV2Step.apply expects a dict, got "
                f"{type(definition_dict).__name__}"
            )
        actual_source = definition_dict.get("schema_version")
        if actual_source != self.source_version:
            raise ValueError(
                "V1ToV2Step.apply expected schema_version="
                f"{self.source_version!r}, got {actual_source!r}"
            )
        out = copy.deepcopy(definition_dict)
        out["schema_version"] = self.target_version
        return out


#: The flat, ordered registry of migration steps.
#:
#: Phase-1b Sprint-2 Tag-1 introduced :class:`V0ToV1Step`.
#: Phase-1b Sprint-3 Tag-3 appends :class:`V1ToV2Step` (linear-chain
#: extension, Tag-4-Skizze §3.1 P2-marker: linear-chain-only, no
#: branching DAG in Phase-1b). A v0 input resolves through
#: ``[V0ToV1Step(), V1ToV2Step()]`` automatically when the caller
#: requests ``target_schema_version="persona-v2"``.
REGISTERED_STEPS: Final[tuple[MigrationStep, ...]] = (
    V0ToV1Step(),
    V1ToV2Step(),
)
