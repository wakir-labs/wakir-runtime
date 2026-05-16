# SPDX-License-Identifier: Apache-2.0
"""V-907 persona-hash module (Phase-1b Python bootstrap).

This sub-package exposes the persona-hash primitive that anchors a
persona-definition document into the WAT audit-pin pillar set
(third pillar alongside the AIP-document hash and the
capability-token hash).

Protocol-layer consolidation (ADR-0062 Cut-2, 2026-05-16)
---------------------------------------------------------
The Apache-2.0 surface of this package
(``persona_canonical_form``, ``persona_hash``, ``persona_migration``,
``persona_validator``, ``cli``, ``_internal/*``) is also published as
``wakir_protocol.persona`` under the standalone
``wakir-labs/wakir-protocol`` repository.

The BUSL-1.1 substrate (``persona_state_kv``,
``persona_state_kv_constants``, ``recovery_drill_anchor``) is
runtime-internal and stays in this repository; it is NOT mirrored
to ``wakir-protocol``.

External adopters who want only the persona-hash / migration /
validator primitives should depend on ``wakir-protocol`` and import
from ``wakir_protocol.persona`` directly.

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

Lazy-import discipline (Sprint-Pengine-7 Tag-5)
-----------------------------------------------

This package eagerly imports **no submodule that has a top-level
``rfc8785`` or ``cryptography`` dependency**. The crypto-bearing
surfaces (``persona_hash``, ``persona_canonical_form``,
``persona_migration``, ``persona_validator``) are exposed through
:pep:`562` ``__getattr__`` so that importing a sibling submodule
(e.g. ``wirelang.persona.persona_state_kv_constants``, the
constants-only shim for the NATS-KV bucket family) does NOT
transitively load ``rfc8785`` / ``cryptography`` via this
package's ``__init__``.

Background: the Sprint-9 Tag-1 NATS-KV bucket provisioner imports
``wirelang.persona.persona_state_kv_constants`` for its bucket-
naming constants (Sprint-Pengine-7 Tag-5 OI-PILOT-2). On the
production ``wakir-provisioner:0.1.x`` container image (post-
ADR-0059 BSL-1.1 wheel set: ``nats-py`` + ``cryptography``, **no**
``rfc8785``) the prior eager-import shape raised ``ImportError``
during the bucket-family probe, silently dropping the persona-
state family from ``BUCKET_FAMILIES`` and turning the
``--persona-state-pair`` flag into a silent no-op on the pilot VM
(Reza Cross-Review Zone-B B-5). The Tag-5 lazy-import pattern is
parity with the Tag-4 ``wirelang.identity`` disentanglement
(Sprint-9 Tag-4 Bug-6 fix, PEP-562 ``__getattr__``).

This is byte-stable for every existing consumer: the public
attribute-access shape is unchanged, only the eager-load timing
moves. Consumers that read names like ``compute_persona_hash``,
``migrate_persona``, ``validate_persona`` from
``wirelang.persona`` directly continue to work without code
changes; the underlying submodule load happens on first attribute
access via ``__getattr__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


# ---------------------------------------------------------------------------
# Lazy-load registry: public-name → (submodule_basename, attr_name).
#
# Every entry below names a public attribute exposed on
# ``wirelang.persona`` that lives in a submodule with a transitive
# crypto-bearing import (``rfc8785`` via ``persona_canonical_form``).
# The submodule is loaded on first attribute access via PEP-562
# ``__getattr__``; subsequent accesses hit the cached module-level
# binding.
# ---------------------------------------------------------------------------


_LAZY_CRYPTO_ATTRS: dict[str, tuple[str, str]] = {
    # persona_hash
    "PERSONA_EMPTY_REF_SENTINEL": ("persona_hash", "PERSONA_EMPTY_REF_SENTINEL"),
    "PERSONA_HASH_HEX_LENGTH": ("persona_hash", "PERSONA_HASH_HEX_LENGTH"),
    "PERSONA_HASH_PREFIX": ("persona_hash", "PERSONA_HASH_PREFIX"),
    "PersonaDefinitionInvalidError": ("persona_hash", "PersonaDefinitionInvalidError"),
    "PersonaHashMismatchError": ("persona_hash", "PersonaHashMismatchError"),
    "PersonaSchemaUnsupportedError": ("persona_hash", "PersonaSchemaUnsupportedError"),
    "compute_persona_hash": ("persona_hash", "compute_persona_hash"),
    "compute_persona_hash_from_canonical": (
        "persona_hash",
        "compute_persona_hash_from_canonical",
    ),
    # persona_migration
    "PERSONA_SCHEMA_VERSION_LATEST": (
        "persona_migration",
        "PERSONA_SCHEMA_VERSION_LATEST",
    ),
    "PERSONA_SCHEMA_VERSION_LIST": (
        "persona_migration",
        "PERSONA_SCHEMA_VERSION_LIST",
    ),
    "PersonaMigrationDeterminismError": (
        "persona_migration",
        "PersonaMigrationDeterminismError",
    ),
    "PersonaMigrationError": ("persona_migration", "PersonaMigrationError"),
    "migrate_persona": ("persona_migration", "migrate_persona"),
    # persona_validator
    "PERSONA_VALIDATION_REPORT_SCHEMA_VERSION": (
        "persona_validator",
        "PERSONA_VALIDATION_REPORT_SCHEMA_VERSION",
    ),
    "VALIDATION_ERROR_CODES": ("persona_validator", "VALIDATION_ERROR_CODES"),
    "PersonaValidationReport": ("persona_validator", "PersonaValidationReport"),
    "ValidationError": ("persona_validator", "ValidationError"),
    "validate_persona": ("persona_validator", "validate_persona"),
}


def __getattr__(name: str) -> Any:
    """PEP-562 lazy-attribute hook.

    Resolve a crypto-bearing public name by importing the underlying
    submodule on first access and caching the resulting attribute on
    the package module so subsequent accesses skip ``__getattr__``.

    Raises :class:`AttributeError` for unknown names (PEP 562
    contract).
    """
    if name in _LAZY_CRYPTO_ATTRS:
        from importlib import import_module

        submodule_basename, attr_name = _LAZY_CRYPTO_ATTRS[name]
        submodule = import_module(f"wirelang.persona.{submodule_basename}")
        value = getattr(submodule, attr_name)
        globals()[name] = value  # cache on the package module
        return value
    raise AttributeError(f"module 'wirelang.persona' has no attribute {name!r}")


def __dir__() -> list[str]:
    """Surface the lazy names for ``dir(wirelang.persona)`` / IDE
    autocomplete parity with the pre-Tag-5 eager-import shape.
    """
    return sorted(set(globals().keys()) | set(_LAZY_CRYPTO_ATTRS.keys()))


# ---------------------------------------------------------------------------
# Static type-checker support: TYPE_CHECKING block exposes the same
# names as the lazy registry above so mypy / pyright see the public
# API surface without triggering runtime imports.
# ---------------------------------------------------------------------------


if TYPE_CHECKING:  # pragma: no cover - type-checker only
    from wirelang.persona.persona_hash import (  # noqa: F401
        PERSONA_EMPTY_REF_SENTINEL,
        PERSONA_HASH_HEX_LENGTH,
        PERSONA_HASH_PREFIX,
        PersonaDefinitionInvalidError,
        PersonaHashMismatchError,
        PersonaSchemaUnsupportedError,
        compute_persona_hash,
        compute_persona_hash_from_canonical,
    )
    from wirelang.persona.persona_migration import (  # noqa: F401
        PERSONA_SCHEMA_VERSION_LATEST,
        PERSONA_SCHEMA_VERSION_LIST,
        PersonaMigrationDeterminismError,
        PersonaMigrationError,
        migrate_persona,
    )
    from wirelang.persona.persona_validator import (  # noqa: F401
        PERSONA_VALIDATION_REPORT_SCHEMA_VERSION,
        VALIDATION_ERROR_CODES,
        PersonaValidationReport,
        ValidationError,
        validate_persona,
    )


__all__ = [
    "PERSONA_EMPTY_REF_SENTINEL",
    "PERSONA_HASH_HEX_LENGTH",
    "PERSONA_HASH_PREFIX",
    "PERSONA_SCHEMA_VERSION_LATEST",
    "PERSONA_SCHEMA_VERSION_LIST",
    "PERSONA_VALIDATION_REPORT_SCHEMA_VERSION",
    "PersonaDefinitionInvalidError",
    "PersonaHashMismatchError",
    "PersonaMigrationDeterminismError",
    "PersonaMigrationError",
    "PersonaSchemaUnsupportedError",
    "PersonaValidationReport",
    "VALIDATION_ERROR_CODES",
    "ValidationError",
    "compute_persona_hash",
    "compute_persona_hash_from_canonical",
    "migrate_persona",
    "validate_persona",
    "_LAZY_CRYPTO_ATTRS",
]
