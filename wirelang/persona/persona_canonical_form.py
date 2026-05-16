# SPDX-License-Identifier: Apache-2.0
"""Persona-definition canonical-form extraction (V-907 mock format).

The persona-hash is computed over the **canonical subset** of a
persona definition, not over the raw markdown body. Phase-1b Sprint-1
mock format (HR-slot decision pending):

- Persona definitions ship as markdown files with a YAML front-matter
  block delimited by ``---`` lines (analogous to Jekyll/Hugo style).
- Front-matter keys covered by the canonical subset:
  ``name``, ``description``, ``tools``, ``schema_version``,
  ``identity_pinned`` (nested object).
- Markdown body **after** the closing ``---`` is *out-of-hash*. The
  body holds free narrative (Werdegang, Arbeitsstil, Stärken,
  Blind Spots) and may evolve without forcing a persona-hash drift.
- Unknown front-matter keys are *ignored* by the canonical extractor
  (forward-compat posture; HR can pull a strict-mode flag in a
  later format revision without an API break).

Canonical-JSON shape (the JCS-input bytes):

.. code-block:: json

    {
      "name": "<role-string>",
      "description": "<text>",
      "tools": ["<tool-1>", "<tool-2>"],
      "schema_version": "persona-v1",
      "identity_pinned": {
        "cross_review_zones": [
          {"zone": "K", "partner": "wat-eng", "trigger": "v-907-impl"}
        ],
        "authority": {
          "push_remote": false,
          "budget_cap_eur_per_month": 10,
          "sub_delegation": false
        },
        "hierarchy": {
          "reports_to": "cto",
          "escalation": "cto"
        }
      }
    }

JCS canonicalisation (RFC 8785) is applied *outside* this module — see
:mod:`wirelang.persona.persona_hash`. This module only produces the
canonical Python ``dict`` that JCS consumes.
"""

from __future__ import annotations

from typing import Any, Final


# ---------------------------------------------------------------------------
# Optional-dependency resolver indirection (Sprint-Stability Tag-2, 2026-05-16)
#
# Before Sprint-Stability Tag-2 this module eagerly imported ``yaml`` and
# ``rfc8785`` at module load. That meant any consumer who ``from
# wirelang.persona.persona_canonical_form import ...`` paid the cost of
# both wheels up-front, even if the consumer only needed the
# :class:`PersonaFrontmatterMissingError` sentinel type or the
# :data:`CANONICAL_TOP_LEVEL_KEYS` constant.
#
# The shadow-lane CI (`sandbox-suite-shadow` in
# ``.github/workflows/tests.yml``) installs only the minimal dep set
# ``pytest + pytest-subtests + cryptography + shamir-mnemonic`` — no
# ``yaml`` and no ``rfc8785``. The eager-import shape therefore exploded
# 55 ``persona_engine/test_*`` tests with a ``ModuleNotFoundError`` that
# the ``v907_verify`` caller swallowed and re-raised as a misleading
# ``PersonaHashComputeError("persona_canonical_form missing")``.
#
# The fix is to defer ``yaml`` / ``rfc8785`` to a try/except resolver at
# module top and surface a clear actionable error from the functions
# that actually need them (``parse_frontmatter`` for YAML,
# ``canonical_jcs_bytes`` for JCS). Consumers that only touch the
# constants or the error-class sentinels can import this module on a
# minimal-deps host without exploding.
#
# This is the same pattern already established for crypto deps:
# - ``wirelang.identity.aip_signing``       (rfc8785 fallback)
# - ``wirelang.schemas.entry_signing``      (rfc8785 fallback)
# - ``wirelang.identity.did_document_signing`` (rfc8785 fallback)
#
# The difference here: there is no pure-Python YAML fallback — PyYAML
# is the only widely-shipped YAML parser. So the contract is "module
# loadable without yaml; YAML parsing fails with a clear error". An
# adopter who wants the V-907 compute path installs the ``[persona]``
# extra, which pulls both wheels.
# ---------------------------------------------------------------------------


try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False

try:  # pragma: no cover - production path always has PyYAML
    import yaml as _yaml_lib

    _HAS_YAML = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _yaml_lib = None  # type: ignore[assignment]
    _HAS_YAML = False


SUPPORTED_SCHEMA_VERSION: Final[str] = "persona-v1"

#: All schema-versions the canonical-subset extractor accepts.
#:
#: Phase-1b Sprint-1 Tag-2 introduced ``persona-v1``. Phase-1b Sprint-3
#: Tag-3 appends ``persona-v2`` (the converter's next-major target via
#: :class:`wirelang.persona._internal.migration_steps.V1ToV2Step`) so
#: that a migrated v2-shape dict can route through
#: :func:`extract_canonical_subset` for post-migration pin verification
#: without a separate v2-only extractor. The canonical-subset *shape*
#: is identical for v1 and v2 (Default-Lock A-2 additiv-only-no-
#: narrowing); only the ``schema_version`` const value changes.
#: Additive optional fields from the persona-v2 schema are **not**
#: included in the canonical subset on Tag-3 — they default to absent
#: in both the lifted v9 input and the projected canonical-subset,
#: which preserves the Tag-1-Sketch §3 pin-symmetry argument.
ACCEPTED_SCHEMA_VERSIONS: Final[tuple[str, ...]] = (
    "persona-v1",
    "persona-v2",
)

#: Front-matter keys preserved in the canonical subset, in *insertion*
#: order. JCS will sort them lexicographically anyway, but listing them
#: explicitly here documents the contract.
CANONICAL_TOP_LEVEL_KEYS: Final[tuple[str, ...]] = (
    "name",
    "description",
    "tools",
    "schema_version",
    "identity_pinned",
)

#: Required keys inside ``identity_pinned``.
CANONICAL_IDENTITY_PINNED_KEYS: Final[tuple[str, ...]] = (
    "cross_review_zones",
    "authority",
    "hierarchy",
)


class PersonaFrontmatterMissingError(ValueError):
    """Raised when no YAML front-matter block can be parsed."""


class PersonaFrontmatterMalformedError(ValueError):
    """Raised when the YAML front-matter is not a mapping."""


class PersonaCanonicalFormDependencyMissingError(ImportError):
    """Raised when an optional dependency required for V-907 compute is
    missing from the environment.

    The V-907 pin-compute path needs two PyPI wheels that are not in
    the ``wakir-runtime`` minimal core set:

    - ``PyYAML``  for axis-A front-matter parsing.
    - ``rfc8785`` for JCS (RFC 8785) canonicalisation of the
      canonical-subset dict before SHA-256.

    Adopters who only consume the constants exposed by this module
    (``CANONICAL_TOP_LEVEL_KEYS``, the error-class sentinels, …) can
    import the module on a minimal-deps host without explosion. The
    moment a function that actually needs the missing wheel is called
    (``parse_frontmatter`` for YAML, :func:`canonical_jcs_bytes` for
    JCS), this exception surfaces with a clear actionable message
    instead of a misleading ``persona_canonical_form missing`` re-
    raise from the engine-side caller.

    Recovery: install the persona-compute extra::

        pip install 'wakir-runtime[persona]'

    which pulls both wheels (see ``pyproject.toml`` ``[persona]``).
    """

    def __init__(self, missing_module: str) -> None:
        self.missing_module = missing_module
        super().__init__(
            f"V-907 persona-compute requires the {missing_module!r} "
            f"package, which is not installed in this environment. "
            f"Install via `pip install 'wakir-runtime[persona]'` to "
            f"pull both 'PyYAML' (axis-A front-matter parsing) and "
            f"'rfc8785' (JCS canonicalisation for SHA-256). The "
            f"persona-canonical-form module itself loads fine on a "
            f"minimal-deps host; this exception only fires from the "
            f"functions that actually need the missing wheel."
        )


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a persona markdown file into ``(frontmatter_yaml, body)``.

    The front-matter block must start at byte 0 with a literal
    ``---`` line and end at the next standalone ``---`` line.
    Anything after the closing fence is the body and is **not**
    returned in the canonical subset.

    Raises:
        PersonaFrontmatterMissingError: if the file does not start
            with ``---`` or has no closing fence.
    """
    if not text.startswith("---"):
        raise PersonaFrontmatterMissingError(
            "persona-definition must open with a '---' YAML front-matter fence"
        )
    # Strip the opening fence (with its trailing newline if present).
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    elif rest.startswith("\r\n"):
        rest = rest[2:]
    # Locate the closing fence: a line containing only "---".
    lines = rest.splitlines(keepends=True)
    fm_lines: list[str] = []
    body_start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        if stripped == "---":
            body_start_idx = idx + 1
            break
        fm_lines.append(line)
    if body_start_idx is None:
        raise PersonaFrontmatterMissingError(
            "persona-definition front-matter has no closing '---' fence"
        )
    frontmatter = "".join(fm_lines)
    body = "".join(lines[body_start_idx:])
    return frontmatter, body


def parse_frontmatter(frontmatter_yaml: str) -> dict[str, Any]:
    """Parse the YAML front-matter into a Python dict.

    Raises:
        PersonaCanonicalFormDependencyMissingError: if ``PyYAML`` is
            not installed in this environment. Install via
            ``pip install 'wakir-runtime[persona]'``.
        PersonaFrontmatterMalformedError: if the YAML is not a mapping
            (e.g. a scalar, list, or empty document).
    """
    if not _HAS_YAML:
        raise PersonaCanonicalFormDependencyMissingError("yaml")
    parsed = _yaml_lib.safe_load(frontmatter_yaml)
    if parsed is None:
        raise PersonaFrontmatterMalformedError(
            "persona-definition front-matter is empty"
        )
    if not isinstance(parsed, dict):
        raise PersonaFrontmatterMalformedError(
            "persona-definition front-matter must be a YAML mapping, "
            f"got {type(parsed).__name__}"
        )
    return parsed


def extract_canonical_subset(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Project a parsed front-matter dict onto the V-907 canonical subset.

    Keys not in :data:`CANONICAL_TOP_LEVEL_KEYS` are dropped. The
    ``identity_pinned`` block is recursively narrowed to its
    canonical sub-keys.

    Returns:
        A plain ``dict`` ready for JCS canonicalisation. Keys appear
        in the order listed in :data:`CANONICAL_TOP_LEVEL_KEYS`; JCS
        will re-sort them lexicographically before hashing, so the
        order has no effect on the resulting hash but is preserved
        for human inspection of the intermediate dict.

    Raises:
        KeyError: if a required top-level key is missing.
        ValueError: if ``schema_version`` is unsupported, or if the
            ``identity_pinned`` block is malformed.
    """
    missing = [k for k in CANONICAL_TOP_LEVEL_KEYS if k not in frontmatter]
    if missing:
        raise KeyError(
            f"persona front-matter missing required keys: {missing}"
        )

    schema_version = frontmatter["schema_version"]
    if schema_version not in ACCEPTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"persona schema_version={schema_version!r} is not supported; "
            f"expected one of {ACCEPTED_SCHEMA_VERSIONS!r}"
        )

    identity_pinned_raw = frontmatter["identity_pinned"]
    if not isinstance(identity_pinned_raw, dict):
        raise ValueError(
            "persona identity_pinned must be a mapping, "
            f"got {type(identity_pinned_raw).__name__}"
        )

    missing_ip = [
        k for k in CANONICAL_IDENTITY_PINNED_KEYS if k not in identity_pinned_raw
    ]
    if missing_ip:
        raise ValueError(
            f"persona identity_pinned missing required keys: {missing_ip}"
        )

    identity_pinned_canon = {
        k: identity_pinned_raw[k] for k in CANONICAL_IDENTITY_PINNED_KEYS
    }

    tools_raw = frontmatter["tools"]
    if isinstance(tools_raw, str):
        # Tolerate a comma-separated string in the source; canonical
        # form is always a list of strings.
        tools_canon = [
            t.strip() for t in tools_raw.split(",") if t.strip()
        ]
    elif isinstance(tools_raw, list):
        tools_canon = [str(t) for t in tools_raw]
    else:
        raise ValueError(
            "persona tools must be a list or a comma-separated string, "
            f"got {type(tools_raw).__name__}"
        )

    canonical = {
        "name": str(frontmatter["name"]),
        "description": str(frontmatter["description"]),
        "tools": tools_canon,
        "schema_version": str(schema_version),
        "identity_pinned": identity_pinned_canon,
    }
    return canonical


def read_canonical_subset(persona_definition_text: str) -> dict[str, Any]:
    """End-to-end helper: markdown text → canonical subset dict.

    Equivalent to::

        fm, _body = split_frontmatter(text)
        return extract_canonical_subset(parse_frontmatter(fm))
    """
    fm, _body = split_frontmatter(persona_definition_text)
    return extract_canonical_subset(parse_frontmatter(fm))


def canonical_jcs_bytes(canonical_subset: dict[str, Any]) -> bytes:
    """Serialise a canonical-subset dict to JCS (RFC 8785) bytes.

    This is the bytes-level boundary that feeds into the SHA-256 step
    in :func:`wirelang.persona.persona_hash.compute_persona_hash_from_canonical`.
    Exposing it directly is the parity-anchor for the Phase-1c Rust
    crate ``persona-canonical-form`` (Sprint-2 Tag-4 outbox §A2):
    Python and Rust must produce **byte-identical** JCS-bytes for the
    same canonical-subset, otherwise the V-907 pin-pack drifts across
    language boundaries.

    Args:
        canonical_subset: dict produced by
            :func:`extract_canonical_subset` (or an equivalent
            hand-built dict). Must be JSON-serialisable; JCS does the
            lexicographic key sorting and number-canonicalisation.

    Returns:
        The JCS-canonical UTF-8 byte string (RFC 8785).

    Raises:
        PersonaCanonicalFormDependencyMissingError: if ``rfc8785`` is
            not installed in this environment. Install via
            ``pip install 'wakir-runtime[persona]'``.
        TypeError, ValueError: surfaced from ``rfc8785.dumps`` for
            non-serialisable inputs (NaN, non-string keys, custom types).
    """
    if not _HAS_RFC8785:
        raise PersonaCanonicalFormDependencyMissingError("rfc8785")
    return _rfc8785_lib.dumps(canonical_subset)
