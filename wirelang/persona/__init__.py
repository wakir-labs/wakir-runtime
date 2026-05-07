# SPDX-License-Identifier: Apache-2.0
"""V-907 persona-hash module (Phase-1b Python bootstrap).

This sub-package exposes the persona-hash primitive that anchors a
persona-definition document into the WAT audit-pin pillar set
(third pillar alongside the AIP-document hash and the
capability-token hash).

Public API
----------

- :func:`compute_persona_hash` — deterministic JCS-SHA-256 over the
  canonical subset of a persona definition.
- :data:`PERSONA_HASH_PREFIX` — ``"sha256:"``.
- :data:`PERSONA_HASH_HEX_LENGTH` — ``64``.
- :data:`PERSONA_EMPTY_REF_SENTINEL` — ``""`` (V-908 federation stub).

Format posture (Phase-1b Sprint-1 Tag-2)
----------------------------------------

The hash input format is the **mock canonical subset** documented in
``wirelang/specs/persona-hash-spec.md`` §2 — extended YAML
front-matter following ``schema_version: persona-v1``. The HR-slot
governance owner has not yet ratified the final format (ADR-0029
pending as of Phase-1b Sprint-1). The mock subset is engine-default;
an HR override triggers a re-hash sweep of the test-vector pack but
does not change the public API surface.
"""

from wirelang.persona.persona_hash import (
    PERSONA_EMPTY_REF_SENTINEL,
    PERSONA_HASH_HEX_LENGTH,
    PERSONA_HASH_PREFIX,
    PersonaDefinitionInvalidError,
    PersonaHashMismatchError,
    PersonaSchemaUnsupportedError,
    compute_persona_hash,
    compute_persona_hash_from_canonical,
)
from wirelang.persona.persona_migration import (
    PERSONA_SCHEMA_VERSION_LATEST,
    PERSONA_SCHEMA_VERSION_LIST,
    PersonaMigrationDeterminismError,
    PersonaMigrationError,
    migrate_persona,
)

__all__ = [
    "PERSONA_EMPTY_REF_SENTINEL",
    "PERSONA_HASH_HEX_LENGTH",
    "PERSONA_HASH_PREFIX",
    "PERSONA_SCHEMA_VERSION_LATEST",
    "PERSONA_SCHEMA_VERSION_LIST",
    "PersonaDefinitionInvalidError",
    "PersonaHashMismatchError",
    "PersonaMigrationDeterminismError",
    "PersonaMigrationError",
    "PersonaSchemaUnsupportedError",
    "compute_persona_hash",
    "compute_persona_hash_from_canonical",
    "migrate_persona",
]
