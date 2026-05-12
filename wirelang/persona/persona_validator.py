# SPDX-License-Identifier: Apache-2.0
"""Persona-definition read-only validator (Phase-1b Sprint-6 Tag-1).

Public API
==========

- :func:`validate_persona` — read a persona-definition (dict / Markdown
  text / Path) and return a :class:`PersonaValidationReport`. Does NOT
  raise on validation failure: the report carries ``is_valid`` plus a
  structured ``errors`` list. The only exceptions that escape are
  :class:`FileNotFoundError` for a missing path and pure bugs.
- :class:`PersonaValidationReport` — frozen dataclass with
  ``to_canonical_dict()`` for byte-stable JCS-/JSON-serialisation
  (Phase-1c cross-lang parity anchor against the Rust
  ``persona-validator`` crate).
- :data:`PERSONA_VALIDATION_REPORT_SCHEMA_VERSION` —
  ``"persona-validation-v1"``.

Posture (ADR-0036, Default-Lock A-1+A-2+A-3 conform)
====================================================

The validator is a pure read-only function. It mirrors the validation
side of :func:`wirelang.persona.persona_canonical_form.read_canonical_subset`
plus :func:`wirelang.persona.persona_canonical_form.extract_canonical_subset`,
but **classifies** errors into a structured report instead of raising
on the first failure. The classification is closed-set: every error
maps to one of seven ``ValidationErrorCode`` variants. The caller can
then drive UX / CI / batch-validation pipelines without try/except
ladders.

Why a separate crate / module?
------------------------------

- :mod:`persona_hash` raises on the first parser failure (caller-pin
  pattern); a CI pipeline that wants to *report* multiple validation
  issues on a batch of persona files cannot use it directly.
- :mod:`persona_migration` validates only inputs the converter can
  handle (and does so by raising); operators want a pre-flight check
  that distinguishes "format issue" from "wrong schema_version".
- The report is byte-stable JSON — the same canonical-subset boundary
  the persona-hash leans on, applied to the validator output. This
  makes Rust↔Python byte-parity a load-bearing test anchor.

Out-of-scope (Phase-1b Sprint-6)
================================

- **No body inspection.** The Markdown body after the closing ``---``
  fence is never read. Mirrors Default-Lock A-3 (body out-of-hash).
- **No migration.** Use :func:`migrate_persona` to actually rewrite a
  persona to the latest schema; the validator only flags the issue.
- **No hash computation.** Use :func:`compute_persona_hash` for that.
  The validator reports schema_version + parser status; it does not
  rehash.
- **No JSON-Schema validation.** The validator covers the seven
  structural checks already encoded in
  :mod:`wirelang.persona.persona_canonical_form`. Full JSON-Schema
  conformance (``wirelang/schemas/persona-v1.json``) stays in
  :mod:`wirelang.tests.test_persona_hash`. Phase-1c follow-up may add
  a ``check_json_schema=True`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping

from wirelang.persona.persona_canonical_form import (
    ACCEPTED_SCHEMA_VERSIONS,
    CANONICAL_IDENTITY_PINNED_KEYS,
    CANONICAL_TOP_LEVEL_KEYS,
    PersonaFrontmatterMalformedError,
    PersonaFrontmatterMissingError,
    parse_frontmatter,
    split_frontmatter,
)
from wirelang.persona.persona_migration import PERSONA_SCHEMA_VERSION_LIST


PERSONA_VALIDATION_REPORT_SCHEMA_VERSION: Final[str] = "persona-validation-v1"


# Closed-set error-code enum. The string values are byte-stable and
# part of the cross-lang parity contract: the Rust pendant must emit
# exactly these strings.
VALIDATION_ERROR_CODES: Final[tuple[str, ...]] = (
    "frontmatter-missing",
    "frontmatter-malformed",
    "missing-top-level-key",
    "identity-pinned-not-mapping",
    "identity-pinned-missing-key",
    "schema-version-unsupported",
    "tools-wrong-type",
)


@dataclass(frozen=True)
class ValidationError:
    """A single validation-failure record.

    Fields are deliberately minimal and byte-stable: ``code`` is one of
    :data:`VALIDATION_ERROR_CODES`, ``message`` is a short human-readable
    string that mirrors the Python exception's ``str()`` message, and
    ``detail`` is an optional supplementary string (e.g. the offending
    schema_version value, the missing key name).
    """

    code: str
    message: str
    detail: str = ""

    def to_canonical_dict(self) -> dict[str, str]:
        """Project this error onto the cross-lang canonical dict shape.

        Keys appear in lexicographic order to match RFC 8785 JCS, even
        though JCS resorts them anyway — having the Python dict already
        sorted makes the intermediate inspection match the JCS bytes.
        """
        return {
            "code": self.code,
            "detail": self.detail,
            "message": self.message,
        }


@dataclass(frozen=True)
class PersonaValidationReport:
    """Structured validation outcome (cross-lang parity anchor).

    ``is_valid`` is the boolean summary; ``errors`` carries the
    structured list. ``schema_version`` is the **declared** version
    from the front-matter, or ``""`` if no front-matter could be
    parsed. ``schema_supported`` is true iff the declared version is
    in :data:`ACCEPTED_SCHEMA_VERSIONS`; false for ``persona-v0``
    (the REJECTED self-migration source) and any unknown string.
    """

    is_valid: bool
    schema_version: str
    schema_supported: bool
    errors: tuple[ValidationError, ...]
    report_schema_version: str = PERSONA_VALIDATION_REPORT_SCHEMA_VERSION

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project the report onto a JCS-stable canonical dict.

        The returned dict is the cross-lang parity anchor: feeding it
        through :func:`rfc8785.dumps` (or the Rust ``serde_jcs::to_vec``)
        must produce byte-identical UTF-8 bytes in both languages for
        the same persona input. The Rust pendant
        ``persona_validator::ValidationReport::to_canonical_value`` must
        emit the same structure.
        """
        return {
            "errors": [e.to_canonical_dict() for e in self.errors],
            "is_valid": self.is_valid,
            "report_schema_version": self.report_schema_version,
            "schema_supported": self.schema_supported,
            "schema_version": self.schema_version,
        }


def _validate_canonical_mapping(
    frontmatter: Mapping[str, Any],
) -> tuple[list[ValidationError], str, bool]:
    """Walk a parsed front-matter mapping and collect structural errors.

    Returns the error list, the declared ``schema_version`` (or ``""``
    if missing), and ``schema_supported``.
    """
    errors: list[ValidationError] = []

    missing_top = [k for k in CANONICAL_TOP_LEVEL_KEYS if k not in frontmatter]
    for key in missing_top:
        errors.append(
            ValidationError(
                code="missing-top-level-key",
                message=f"persona front-matter missing required key: {key}",
                detail=key,
            )
        )

    schema_version_raw: Any = frontmatter.get("schema_version", "")
    schema_version = (
        str(schema_version_raw) if schema_version_raw is not None else ""
    )
    schema_supported = schema_version in ACCEPTED_SCHEMA_VERSIONS

    if "schema_version" in frontmatter and not schema_supported:
        # Distinguish "known-but-unsupported" (persona-v0, in the
        # PERSONA_SCHEMA_VERSION_LIST registry, needs migration) from
        # "unknown" — both surface as the same error code but the
        # detail string carries the offending value verbatim.
        errors.append(
            ValidationError(
                code="schema-version-unsupported",
                message=(
                    f"persona schema_version={schema_version!r} is not "
                    f"supported; expected one of "
                    f"{list(ACCEPTED_SCHEMA_VERSIONS)!r}"
                ),
                detail=schema_version,
            )
        )

    if "tools" in frontmatter:
        tools_raw = frontmatter["tools"]
        if not isinstance(tools_raw, (list, str)):
            errors.append(
                ValidationError(
                    code="tools-wrong-type",
                    message=(
                        "persona tools must be a list or a comma-separated "
                        f"string, got {type(tools_raw).__name__}"
                    ),
                    detail=type(tools_raw).__name__,
                )
            )

    if "identity_pinned" in frontmatter:
        ip_raw = frontmatter["identity_pinned"]
        if not isinstance(ip_raw, Mapping):
            errors.append(
                ValidationError(
                    code="identity-pinned-not-mapping",
                    message=(
                        "persona identity_pinned must be a mapping, "
                        f"got {type(ip_raw).__name__}"
                    ),
                    detail=type(ip_raw).__name__,
                )
            )
        else:
            missing_ip = [
                k for k in CANONICAL_IDENTITY_PINNED_KEYS if k not in ip_raw
            ]
            for key in missing_ip:
                errors.append(
                    ValidationError(
                        code="identity-pinned-missing-key",
                        message=(
                            f"persona identity_pinned missing required key: "
                            f"{key}"
                        ),
                        detail=key,
                    )
                )

    return errors, schema_version, schema_supported


def _empty_report(error: ValidationError) -> PersonaValidationReport:
    """Build a report for a pre-mapping failure (frontmatter parse)."""
    return PersonaValidationReport(
        is_valid=False,
        schema_version="",
        schema_supported=False,
        errors=(error,),
    )


def validate_persona(
    input_: Mapping[str, Any] | str | Path,
) -> PersonaValidationReport:
    """Validate a persona definition without migrating or hashing.

    Args:
        input_: one of

            - A ``Mapping`` already shaped like the front-matter dict
              (skips file IO and YAML parsing).
            - A Markdown text string with ``---`` front-matter fences
              (calls :func:`split_frontmatter` +
              :func:`parse_frontmatter`).
            - A :class:`Path` (or path-like ``str`` that exists on disk).
              The string-vs-path heuristic is the same as
              :func:`migrate_persona`'s: ``isinstance(input_, Path)``
              forces the Path branch, anything else that contains a
              newline is treated as Markdown text, otherwise the string
              is tried as a path.

    Returns:
        :class:`PersonaValidationReport`. Never raises on validation
        failure; only ``FileNotFoundError`` (Path input that does not
        exist) and pure bugs propagate.
    """
    # 1) Resolve to a parsed frontmatter mapping.
    fm_mapping: Mapping[str, Any]
    if isinstance(input_, Mapping):
        fm_mapping = input_
    else:
        # str / Path branch — collapse to a Markdown text string.
        if isinstance(input_, Path):
            markdown_text = input_.read_text(encoding="utf-8")
        else:
            # str input. Heuristic mirrors ``migrate_persona``:
            # - If the string contains a newline, treat it as inline
            #   Markdown text (the by-far most common case for inline
            #   fixtures in tests).
            # - Otherwise, attempt to treat it as a path; if the path
            #   does not exist, fall back to treating the string as
            #   Markdown text (which will then surface a
            #   ``frontmatter-missing`` error). This avoids accidental
            #   ``FileNotFoundError`` on validator-error short strings.
            if "\n" in input_:
                markdown_text = input_
            else:
                candidate_path = Path(input_)
                if candidate_path.exists():
                    markdown_text = candidate_path.read_text(encoding="utf-8")
                else:
                    markdown_text = input_

        try:
            fm_yaml, _body = split_frontmatter(markdown_text)
        except PersonaFrontmatterMissingError as exc:
            return _empty_report(
                ValidationError(
                    code="frontmatter-missing",
                    message=str(exc),
                )
            )

        try:
            fm_mapping = parse_frontmatter(fm_yaml)
        except PersonaFrontmatterMalformedError as exc:
            return _empty_report(
                ValidationError(
                    code="frontmatter-malformed",
                    message=str(exc),
                )
            )

    # 2) Walk the mapping and collect structural errors.
    errors, schema_version, schema_supported = _validate_canonical_mapping(
        fm_mapping
    )

    return PersonaValidationReport(
        is_valid=not errors,
        schema_version=schema_version,
        schema_supported=schema_supported,
        errors=tuple(errors),
    )


# Re-export for downstream test-suite import.
__all__ = [
    "PERSONA_VALIDATION_REPORT_SCHEMA_VERSION",
    "PersonaValidationReport",
    "VALIDATION_ERROR_CODES",
    "ValidationError",
    "validate_persona",
]


# Silence unused-import warning: PERSONA_SCHEMA_VERSION_LIST is imported
# for symbol-availability documentation (Phase-1c Rust pendant references
# the same list for its known-versions enum) even though this module
# does not branch on it directly.
_KNOWN_SCHEMA_VERSIONS_REGISTRY: Final[tuple[str, ...]] = (
    PERSONA_SCHEMA_VERSION_LIST
)
