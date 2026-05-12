# SPDX-License-Identifier: Apache-2.0
"""V-907 persona-hash primitive (Phase-1b Sprint-1 Tag-2 skeleton).

Public API
==========

- :func:`compute_persona_hash` — read a persona-definition file
  (markdown + YAML front-matter), extract the canonical subset,
  compute ``"sha256:" + sha256(JCS(canonical_subset))``.
- :func:`compute_persona_hash_from_canonical` — same hash function
  but takes an already-extracted canonical-subset dict (used by the
  test suite and by future in-memory pipelines).
- :data:`PERSONA_HASH_PREFIX` — ``"sha256:"``.
- :data:`PERSONA_HASH_HEX_LENGTH` — ``64``.
- :data:`PERSONA_EMPTY_REF_SENTINEL` — ``""`` (V-908 federation stub).

The body (markdown after the front-matter fence) is **out-of-hash**:
narrative edits to Werdegang/Arbeitsstil/Stärken sections do not move
the hash. Front-matter and ``identity_pinned``-block edits do.

WAT-bridge contract (Cross-Review Zone K, wat-eng-slot, K-1+K-2 pending)
-----------------------------------------------------------------------

Downstream WAT-frame producers will populate ``persona_refs[0]`` with
the string returned by this function (full ``"sha256:<64hex>"`` form).
The bridge helper that *extracts* the persona-hash from a WAT-frame
will mirror :func:`wat.ingestion.wirelang_bridge.extract_capability_token_hash`
byte-for-byte and return the empty-string sentinel for the V-908
federation case (no persona reference). That mirror lives in the WAT
tree and is owned by the wat-eng slot; this module is the engine-side
source of truth for the **format** of the value.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

import rfc8785

from wirelang.persona.persona_canonical_form import (
    PersonaFrontmatterMalformedError,
    PersonaFrontmatterMissingError,
    read_canonical_subset,
)


PERSONA_HASH_PREFIX: Final[str] = "sha256:"
PERSONA_HASH_HEX_LENGTH: Final[int] = 64
PERSONA_HASH_FULL_LENGTH: Final[int] = (
    len(PERSONA_HASH_PREFIX) + PERSONA_HASH_HEX_LENGTH
)

#: Empty-string sentinel for the V-908 federation case (a frame
#: that does not pin a persona reference). Mirrors the
#: ``aip_document_refs[0]`` and ``capability_token_refs[0]`` empty
#: behaviour in the WAT-bridge.
PERSONA_EMPTY_REF_SENTINEL: Final[str] = ""


class PersonaDefinitionInvalidError(ValueError):
    """Persona definition cannot be parsed into the canonical subset.

    Wraps :class:`PersonaFrontmatterMissingError`,
    :class:`PersonaFrontmatterMalformedError`, and the schema-shape
    errors raised by
    :func:`wirelang.persona.persona_canonical_form.extract_canonical_subset`.
    """


class PersonaSchemaUnsupportedError(ValueError):
    """Persona declares a ``schema_version`` this build does not understand.

    Phase-1b accepts only ``persona-v1``; older or future schemas must
    pass through the self-migration converter (ADR-0036) before they
    can be hashed.
    """


class PersonaHashMismatchError(AssertionError):
    """Computed persona-hash differs from the caller-supplied pin.

    Raised by :func:`compute_persona_hash` when ``expected_jcs_sha256``
    is supplied and does not match the freshly-computed value. The
    caller-pin pattern mirrors the AIP-document resolver
    (identity-eng-slot, Tag-21 spec anchor).
    """


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def compute_persona_hash_from_canonical(
    canonical_subset: dict[str, Any],
    *,
    expected_jcs_sha256: str | None = None,
) -> str:
    """Compute ``"sha256:<64hex>"`` over JCS-canonical-JSON of the subset.

    Args:
        canonical_subset: dict produced by
            :func:`wirelang.persona.persona_canonical_form.extract_canonical_subset`
            (or an equivalent hand-built dict). Must be JSON-serialisable;
            JCS (RFC 8785) does the lexicographic key sorting and
            number-canonicalisation.
        expected_jcs_sha256: optional caller-pin. May be supplied as
            either the bare 64-char hex tail, or the full
            ``"sha256:<64hex>"`` form. If set, raises
            :class:`PersonaHashMismatchError` on drift.

    Returns:
        ``"sha256:<64-char-hex>"``.

    Raises:
        PersonaHashMismatchError: when ``expected_jcs_sha256`` is set
            and disagrees with the computed value.
    """
    jcs_bytes = rfc8785.dumps(canonical_subset)
    hex_tail = _sha256_hex(jcs_bytes)
    full = PERSONA_HASH_PREFIX + hex_tail

    if expected_jcs_sha256 is not None:
        # Accept either form for caller convenience.
        if expected_jcs_sha256.startswith(PERSONA_HASH_PREFIX):
            expected_full = expected_jcs_sha256
            expected_hex = expected_jcs_sha256[len(PERSONA_HASH_PREFIX):]
        else:
            expected_full = PERSONA_HASH_PREFIX + expected_jcs_sha256
            expected_hex = expected_jcs_sha256
        if expected_hex != hex_tail:
            raise PersonaHashMismatchError(
                f"persona-hash drift: expected {expected_full}, "
                f"computed {full}"
            )

    return full


def compute_persona_hash(
    persona_definition_path: str | Path,
    *,
    expected_jcs_sha256: str | None = None,
) -> str:
    """Read a persona-definition file and return its ``"sha256:<64hex>"``.

    Args:
        persona_definition_path: filesystem path to a persona markdown
            file with YAML front-matter (mock-format ``persona-v1``).
        expected_jcs_sha256: optional caller-pin (see
            :func:`compute_persona_hash_from_canonical`).

    Returns:
        ``"sha256:<64-char-hex>"``.

    Raises:
        PersonaDefinitionInvalidError: when the file cannot be parsed
            into the canonical subset (missing front-matter fence,
            malformed YAML, missing required keys, malformed
            ``identity_pinned`` block).
        PersonaSchemaUnsupportedError: when ``schema_version`` is not
            ``persona-v1``.
        PersonaHashMismatchError: when ``expected_jcs_sha256`` drifts.
        FileNotFoundError: when the path does not exist.
    """
    path = Path(persona_definition_path)
    text = path.read_text(encoding="utf-8")
    try:
        canonical = read_canonical_subset(text)
    except (
        PersonaFrontmatterMissingError,
        PersonaFrontmatterMalformedError,
        KeyError,
    ) as exc:
        raise PersonaDefinitionInvalidError(str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if "schema_version" in msg:
            raise PersonaSchemaUnsupportedError(msg) from exc
        raise PersonaDefinitionInvalidError(msg) from exc

    return compute_persona_hash_from_canonical(
        canonical, expected_jcs_sha256=expected_jcs_sha256
    )
