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
    Tag-2 mock canonical subset, not a content extension. Once HR
    ratifies a v2 format with additional ``identity_pinned`` sub-keys,
    a new ``V1ToV2Step`` will be added; v0 inputs will then resolve
    to the chain ``[V0ToV1Step(), V1ToV2Step()]`` automatically.
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


#: The flat, ordered registry of migration steps.
#:
#: Phase-1b Sprint-2 Tag-1 carries exactly one entry. Future schema
#: versions append in linear order (Tag-4-Skizze §3.1 P2-marker:
#: linear-chain-only, no branching DAG in Phase-1b).
REGISTERED_STEPS: Final[tuple[MigrationStep, ...]] = (
    V0ToV1Step(),
)
