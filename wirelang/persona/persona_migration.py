# SPDX-License-Identifier: Apache-2.0
"""Self-migration converter for persona-definitions (ADR-0036, V-907).

Phase-1b Sprint-2 Tag-1 implementation (S2-T1-01).

Public API
==========

- :func:`migrate_persona` — multi-step migration chain over a
  persona-definition dict / raw markdown / file-path.
- :class:`PersonaMigrationError` — chain not resolvable.
- :class:`PersonaMigrationDeterminismError` — output drifts from a
  caller-supplied post-migration pin.
- :data:`PERSONA_SCHEMA_VERSION_LATEST` — the engine's current
  hash-input schema version (``"persona-v1"``).
- :data:`PERSONA_SCHEMA_VERSION_LIST` — ordered tuple of all
  schema-versions known to this build.

Format posture
==============

Engine-default mock canonical subset per Default-Lock A-1+A-2+A-3
(ratified 2026-05-07 ~10:00 CEST by ceo-slot via the engine-side
inbox decision file for Phase-0 default-lock answer A-1/A-2/A-3):

- **A-1:** mock canonical subset is the input shape (Tag-2 baseline).
- **A-2:** semver-major-only, additiv-only, linear chain — every
  step is an additive transition; field removal is forbidden.
- **A-3:** front-matter is in-hash, markdown body is out-of-hash;
  the converter operates on the canonical subset only.

Determinism guarantee (V-907 pin-pillar)
========================================

The converter is byte-deterministic by construction (Tag-4-Skizze §2.2
Regel B1). Every ``MigrationStep.apply`` writes default values
*explicitly* in code rather than via JSON-Schema default inference,
which neutralises the D-2 risk class. The resulting canonical-subset
dict, fed to ``compute_persona_hash_from_canonical``, must reproduce
the pre-frozen V-907 pin of the equivalent native v_{n+1} fixture.

Out-of-scope (Phase-1b Sprint-2 Tag-1)
======================================

- **Markdown-body migration:** body is out-of-hash; if a future format
  pulls body fragments into the canonical subset, the body-reader will
  be added to ``persona_canonical_form``, not here.
- **Branching DAG (Phase-2):** linear chain only. The 32-step safety
  guard in :func:`_resolve_chain` is a cycle-detection backstop, not
  a feature.
- **Migration-audit-trail in WAT-leaf (Phase-2 P2-01):** Cross-Review
  Zone K, wat-eng owns; persona-engine emits the pre/post hash pair on
  request, but no WAT-frame is produced from this module.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Final

from wirelang.persona._internal.migration_steps import (
    REGISTERED_STEPS,
    MigrationStep,
)
from wirelang.persona.persona_canonical_form import (
    PersonaFrontmatterMalformedError,
    PersonaFrontmatterMissingError,
    SUPPORTED_SCHEMA_VERSION,
    parse_frontmatter,
    split_frontmatter,
)
from wirelang.persona.persona_hash import (
    PersonaHashMismatchError,
    compute_persona_hash_from_canonical,
)


PERSONA_SCHEMA_VERSION_LATEST: Final[str] = SUPPORTED_SCHEMA_VERSION
#: Ordered tuple of all schema-versions known to this build.
#:
#: Phase-1b Sprint-3 Tag-3 appends ``persona-v2`` as the converter's
#: registered next major (``V1ToV2Step``). ``PERSONA_SCHEMA_VERSION_LATEST``
#: deliberately stays at ``persona-v1`` until HR-slot ratifies the
#: persona-v2 content (ADR-0029-Annex) or the T-B Default-Lock window
#: lifts the engine-default-mock — neither has happened on Tag-3, so a
#: bare ``migrate_persona(definition)`` call still targets v1 by default.
PERSONA_SCHEMA_VERSION_LIST: Final[tuple[str, ...]] = (
    "persona-v0",
    "persona-v1",
    "persona-v2",
)

#: Safety guard against cycles in the step registry. The Phase-1b
#: linear-chain assumption (Tag-4-Skizze §3.1) means a real chain
#: never exceeds ``len(REGISTERED_STEPS)``; anything larger indicates
#: a bug in step registration.
_MAX_CHAIN_LENGTH: Final[int] = 32


class PersonaMigrationError(ValueError):
    """A migration chain from source to target cannot be resolved.

    Causes include: unknown source version, unknown target version,
    no registered step from the current chain head, or a chain that
    exceeds the cycle-detection guard.
    """


class PersonaMigrationDeterminismError(RuntimeError):
    """The converter's post-migration hash drifts from the caller pin.

    Raised by :func:`migrate_persona` when
    ``expected_post_migration_hash`` is supplied and does not match
    the freshly-computed hash of the output canonical subset.
    """


def _find_step_by_source(source_version: str) -> MigrationStep | None:
    for step in REGISTERED_STEPS:
        if step.source_version == source_version:
            return step
    return None


def _resolve_chain(
    source_version: str,
    target_version: str,
) -> list[MigrationStep]:
    """Resolve the linear chain from ``source_version`` to ``target_version``.

    Returns an empty list when source and target match (no-op migration).
    Raises :class:`PersonaMigrationError` on unknown versions, unreachable
    targets, or chains longer than :data:`_MAX_CHAIN_LENGTH`.
    """
    if source_version not in PERSONA_SCHEMA_VERSION_LIST:
        raise PersonaMigrationError(
            f"unknown source schema_version={source_version!r}; "
            f"known versions: {PERSONA_SCHEMA_VERSION_LIST}"
        )
    if target_version not in PERSONA_SCHEMA_VERSION_LIST:
        raise PersonaMigrationError(
            f"unknown target schema_version={target_version!r}; "
            f"known versions: {PERSONA_SCHEMA_VERSION_LIST}"
        )
    if source_version == target_version:
        return []

    chain: list[MigrationStep] = []
    cur = source_version
    while cur != target_version:
        next_step = _find_step_by_source(cur)
        if next_step is None:
            raise PersonaMigrationError(
                f"no migration step registered from {cur!r} "
                f"towards {target_version!r}"
            )
        chain.append(next_step)
        cur = next_step.target_version
        if len(chain) > _MAX_CHAIN_LENGTH:
            raise PersonaMigrationError(
                f"migration chain length exceeded {_MAX_CHAIN_LENGTH} "
                "steps; suspect a cycle in REGISTERED_STEPS"
            )
    return chain


def _coerce_to_dict(
    definition: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Normalise the public-API input into a front-matter dict.

    Accepts:

    - ``dict``: already-parsed front-matter (used by tests and
      in-memory pipelines). Returned as a deep copy to avoid mutating
      caller state.
    - ``Path``: filesystem path to a persona markdown file.
    - ``str``: raw markdown text (heuristic — strings starting with
      ``---`` are treated as raw markdown; everything else is rejected
      to keep the call-site explicit).

    Defensive posture (Sprint-2 Tag-2 S2-T1-03):
    Front-matter parse failures from
    :mod:`wirelang.persona.persona_canonical_form` (missing fence,
    malformed YAML, non-mapping) are re-wrapped as
    :class:`PersonaMigrationError` so call-sites only need to import
    one converter-error class. The original exception is chained via
    ``__cause__`` for forensic inspection.
    """
    if isinstance(definition, dict):
        return copy.deepcopy(definition)
    if isinstance(definition, Path):
        try:
            text = definition.read_text(encoding="utf-8")
            fm, _body = split_frontmatter(text)
            return parse_frontmatter(fm)
        except (
            PersonaFrontmatterMissingError,
            PersonaFrontmatterMalformedError,
        ) as exc:
            raise PersonaMigrationError(
                f"persona-definition at {definition} is irreparable: {exc}"
            ) from exc
    if isinstance(definition, str):
        if not definition.startswith("---"):
            raise PersonaMigrationError(
                "raw-markdown input must start with a '---' YAML "
                "front-matter fence; pass a Path or a dict otherwise"
            )
        try:
            fm, _body = split_frontmatter(definition)
            return parse_frontmatter(fm)
        except (
            PersonaFrontmatterMissingError,
            PersonaFrontmatterMalformedError,
        ) as exc:
            raise PersonaMigrationError(
                f"raw-markdown persona-definition is irreparable: {exc}"
            ) from exc
    raise TypeError(
        "migrate_persona expects dict | str | Path, got "
        f"{type(definition).__name__}"
    )


def migrate_persona(
    definition: dict[str, Any] | str | Path,
    *,
    target_schema_version: str = PERSONA_SCHEMA_VERSION_LATEST,
    expected_post_migration_hash: str | None = None,
) -> dict[str, Any]:
    """Run the registered migration chain on ``definition``.

    Args:
        definition: a front-matter dict, raw markdown text starting
            with a ``---`` fence, or a filesystem :class:`~pathlib.Path`.
        target_schema_version: chain target. Defaults to the engine's
            current hash-input schema version
            (:data:`PERSONA_SCHEMA_VERSION_LATEST`).
        expected_post_migration_hash: optional pin in either bare
            64-hex form or full ``"sha256:<64hex>"`` form. When
            supplied, the post-migration canonical-subset dict is
            re-hashed and compared; a mismatch raises
            :class:`PersonaMigrationDeterminismError`.

    Returns:
        The migrated canonical-subset dict, ready to be passed to
        :func:`wirelang.persona.compute_persona_hash_from_canonical`.

    Raises:
        PersonaMigrationError: when the chain cannot be resolved
            (unknown source, unknown target, no path, suspected cycle,
            invalid raw-markdown shape, missing/malformed front-matter,
            or non-string ``schema_version``). Front-matter parse
            failures from
            :mod:`wirelang.persona.persona_canonical_form` are
            re-wrapped here with ``__cause__`` chained.
        PersonaMigrationDeterminismError: when the optional post-pin
            disagrees with the freshly-computed hash.
        TypeError: when ``definition`` is not ``dict | str | Path``.
        FileNotFoundError: when a :class:`~pathlib.Path` input does
            not exist on disk.
    """
    fm_dict = _coerce_to_dict(definition)

    source_version = fm_dict.get("schema_version")
    if source_version is None:
        raise PersonaMigrationError(
            "persona front-matter has no schema_version key; "
            "cannot resolve migration source"
        )
    if not isinstance(source_version, str):
        raise PersonaMigrationError(
            f"persona schema_version must be a string, got "
            f"{type(source_version).__name__}"
        )

    chain = _resolve_chain(source_version, target_schema_version)

    cur = fm_dict
    for step in chain:
        cur = step.apply(cur)

    if expected_post_migration_hash is not None:
        try:
            compute_persona_hash_from_canonical(
                _project_canonical_subset(cur),
                expected_jcs_sha256=expected_post_migration_hash,
            )
        except PersonaHashMismatchError as exc:
            raise PersonaMigrationDeterminismError(
                f"post-migration hash drift: {exc}"
            ) from exc

    return cur


def _project_canonical_subset(fm_dict: dict[str, Any]) -> dict[str, Any]:
    """Project the migrated front-matter onto the V-907 canonical subset.

    Equivalent in shape to
    :func:`wirelang.persona.persona_canonical_form.extract_canonical_subset`,
    but operates on a dict that has already passed through the
    migration chain (so ``schema_version`` is guaranteed equal to
    :data:`PERSONA_SCHEMA_VERSION_LATEST`).

    Kept private to this module to avoid exposing a second public
    canonicaliser; the test suite uses
    :func:`wirelang.persona.compute_persona_hash_from_canonical`
    on the migrated dict directly.
    """
    from wirelang.persona.persona_canonical_form import (
        extract_canonical_subset,
    )
    return extract_canonical_subset(fm_dict)
