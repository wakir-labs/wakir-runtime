# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-definition front-matter-parser canonical-trace helpers.

This module is the **Python sibling** of the Rust crate
``persona-engine-frontmatter-parser`` (PR #142, merged 2026-05-17).
Where the Rust crate provides a strongly-typed ``PersonaDef`` parser
surface above ``persona-canonical-form-yaml``, this module provides the
canonical-trace surface that pairs with it byte-paritätisch — both
sides emit a JCS-canonical ``FrontmatterParseTrace`` per parse outcome
so the Phase-3a 3-way-triangle (Doppelbetrieb-Vergleich) can diff
Python-side and Rust-side persona-front-matter-parser traces
byte-for-byte without round-tripping through any other substrate.

Why a sibling module?
---------------------

The existing :mod:`wirelang.persona.persona_canonical_form` provides
the byte-level primitives (``split_frontmatter``, ``parse_frontmatter``,
``extract_canonical_subset``, ``canonical_jcs_bytes``) but does NOT
emit a structured parse-outcome trace. The Rust crate's typed
``PersonaDef`` API and its error variants are the surface we need to
cross-anchor against — split-success/failure, YAML-parse-error,
canonical-subset shape error, etc. — and a per-call structured trace
is the right shape for the 3-way triangle.

Keeping the helpers in a separate Apache-2.0 module preserves the
Sprint-10 Doppelbetrieb-Konsistenz contract (the existing
``persona_canonical_form.py`` byte-output does not change) and
matches the sibling-pattern Reza used for
``wirelang.persona_engine.lifecycle_state_machine_canonical``
(Tag-21 sibling of ``persona-engine-fsm``).

Schema
------

The canonical-trace carries exactly seven top-level fields
(alphabetically sorted in the canonical form):

- ``accepted_status`` — One of ``"ok"``, ``"missing_fence"``,
  ``"malformed"``, ``"yaml_parse_error"``, ``"invalid_shape"``.
  ``"ok"`` is set when the markdown text parses through to a
  byte-identical canonical-subset projection.
- ``canonical_subset_jcs_sha256_hex`` — SHA-256 hex of the JCS bytes
  of the canonical subset. Empty string ``""`` when the parse did
  not reach the canonical-subset projection (any non-``ok`` status).
- ``error_class`` — Error class name when non-``ok``. One of
  ``"PersonaFrontmatterMissingError"``,
  ``"PersonaFrontmatterMalformedError"``,
  ``"YamlParseError"``, ``"InvalidShape"``. Empty string ``""`` on
  ``ok``. (Schema-symmetric: always present, never omitted, to keep
  the JCS-canonical key-set stable across success and failure.)
- ``persona_name`` — ``frontmatter["name"]`` projected to string.
  Empty string when not reachable.
- ``persona_slug`` — ``frontmatter["persona_slug"]`` projected to
  string. Empty string when absent or not reachable.
- ``schema_version`` — ``frontmatter["schema_version"]`` projected
  to string. Empty string when not reachable.
- ``tools_count`` — Length of the normalised tools-list. ``0`` when
  not reachable.

Serialisation
-------------

The canonical bytes are produced by ``rfc8785.dumps`` (RFC 8785 JCS).
The outer trace hash is ``"sha256:" + hex(SHA-256(canonical_bytes))``.

This is the same serialisation discipline used by every other Phase-3a
cross-lang canonical-trace module — JCS-canonical bytes, SHA-256, hex,
prefixed with the schema id ``"sha256:"``. Rust pendant uses
``serde_jcs::to_vec`` + ``sha2::Sha256``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/frontmatter-parser-cross-lang/fixtures.json`` is the
byte-level cross-lang pin: both
``wirelang/tests/persona/test_frontmatter_parser_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-frontmatter-parser/tests/cross_lang_fixture_test.rs``
(Rust) consume the same vectors. Any drift on either side fails both
suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                      <-> Rust pendant
    ----------------------------------------------------------------------
    build_frontmatter_trace(md_text) -> FrontmatterParseTrace
                                                       <-> build_frontmatter_trace
    serialize_frontmatter_trace(trace) -> bytes        <-> serialize_trace
    frontmatter_trace_sha256_hex(trace) -> str         <-> trace_sha256_hex
    frontmatter_trace_hash_prefixed(trace) -> str      <-> trace_hash_prefixed
    FrontmatterParseTrace (dataclass)                  <-> FrontmatterParseTrace
    FRONTMATTER_TRACE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                                   <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a — Rust-Crate-Bundle + Phase-3a
  Python-sync.
- ADR-0065 — Phase-3c cutover Python-default zu Rust-default.
- ADR-0066 — Phase-3c-Beschleunigung Option A+.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

from wirelang.persona.persona_canonical_form import (
    ACCEPTED_SCHEMA_VERSIONS,
    CANONICAL_IDENTITY_PINNED_KEYS,
    CANONICAL_TOP_LEVEL_KEYS,
    PersonaCanonicalFormDependencyMissingError,
    PersonaFrontmatterMalformedError,
    PersonaFrontmatterMissingError,
    canonical_jcs_bytes,
    extract_canonical_subset,
    parse_frontmatter,
    split_frontmatter,
)

# ---------------------------------------------------------------------------
# Optional-dependency resolver (same posture as persona_canonical_form).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False

try:  # pragma: no cover - production path always has PyYAML
    import yaml as _yaml_lib  # noqa: F401  (re-export only via parent module)

    _HAS_YAML = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _HAS_YAML = False


#: JCS-canonical schema id for the frontmatter-parse trace wire form.
#: Cross-lang anchor — must match the Rust constant of the same name.
FRONTMATTER_TRACE_SCHEMA: Final[str] = (
    "wakir.persona-engine.frontmatter-parser-canonical/1"
)

#: Outer-hash prefix. Cross-lang anchor.
HASH_PREFIX: Final[str] = "sha256:"

#: Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
SHA256_HEX_LEN: Final[int] = 64

#: Accepted-status wire-string values. Frozen across Rust/Python.
STATUS_OK: Final[str] = "ok"
STATUS_MISSING_FENCE: Final[str] = "missing_fence"
STATUS_MALFORMED: Final[str] = "malformed"
STATUS_YAML_PARSE_ERROR: Final[str] = "yaml_parse_error"
STATUS_INVALID_SHAPE: Final[str] = "invalid_shape"

ACCEPTED_STATUS_VALUES: Final[tuple[str, ...]] = (
    STATUS_OK,
    STATUS_MISSING_FENCE,
    STATUS_MALFORMED,
    STATUS_YAML_PARSE_ERROR,
    STATUS_INVALID_SHAPE,
)

#: Error-class wire-string values. Frozen across Rust/Python. Empty
#: string is reserved for the success path (``status == "ok"``).
ERROR_CLASS_MISSING: Final[str] = "PersonaFrontmatterMissingError"
ERROR_CLASS_MALFORMED: Final[str] = "PersonaFrontmatterMalformedError"
ERROR_CLASS_YAML: Final[str] = "YamlParseError"
ERROR_CLASS_INVALID_SHAPE: Final[str] = "InvalidShape"


# ---------------------------------------------------------------------------
# Trace dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontmatterParseTrace:
    """Canonical-trace projection of a persona-front-matter parse outcome.

    Fields are ordered to match the alphabetical JCS sort the wire form
    uses; the dataclass itself is otherwise an opaque record.
    """

    accepted_status: str
    canonical_subset_jcs_sha256_hex: str
    error_class: str
    persona_name: str
    persona_slug: str
    schema_version: str
    tools_count: int

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project this trace onto a JSON-compatible dict, ready for JCS.

        Keys are inserted in alphabetical order to document the wire
        contract; JCS will re-sort them lexicographically anyway, so
        the insertion order has no effect on the resulting bytes.
        """
        return {
            "accepted_status": self.accepted_status,
            "canonical_subset_jcs_sha256_hex": self.canonical_subset_jcs_sha256_hex,
            "error_class": self.error_class,
            "persona_name": self.persona_name,
            "persona_slug": self.persona_slug,
            "schema": FRONTMATTER_TRACE_SCHEMA,
            "schema_version": self.schema_version,
            "tools_count": int(self.tools_count),
        }


# ---------------------------------------------------------------------------
# Trace-build helpers.
# ---------------------------------------------------------------------------


def _normalise_tools_count(tools_raw: Any) -> int:
    """Return the normalised tools-count (matches ``extract_canonical_subset``)."""
    if isinstance(tools_raw, list):
        return len(tools_raw)
    if isinstance(tools_raw, str):
        return len([t.strip() for t in tools_raw.split(",") if t.strip()])
    return 0


def _safe_str(value: Any) -> str:
    """Project a value to ``str`` or empty-string. Mirrors Rust ``.unwrap_or_default()``."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def build_frontmatter_trace(md_text: str) -> FrontmatterParseTrace:
    """Build a canonical parse-outcome trace from persona markdown text.

    The function is **infallible** at the trace-build layer: every
    parse outcome (success, missing fence, malformed YAML, invalid
    shape) is captured as a structured trace with the appropriate
    ``accepted_status`` and ``error_class`` populated. This is the
    cross-lang contract — both Rust and Python must always return a
    trace, never raise, so the fixture vectors can pin error paths
    just as easily as success paths.

    The ``canonical_subset_jcs_sha256_hex`` field is populated only
    when ``accepted_status == "ok"``; otherwise it is the empty
    string ``""`` (NOT a SHA-256 of empty input).
    """
    # Step 1 — split_frontmatter.
    try:
        fm_yaml, _body = split_frontmatter(md_text)
    except PersonaFrontmatterMissingError as e:
        return FrontmatterParseTrace(
            accepted_status=STATUS_MISSING_FENCE,
            canonical_subset_jcs_sha256_hex="",
            error_class=ERROR_CLASS_MISSING,
            persona_name="",
            persona_slug="",
            schema_version="",
            tools_count=0,
        )

    # Step 2 — parse_frontmatter.
    try:
        fm_dict = parse_frontmatter(fm_yaml)
    except PersonaFrontmatterMalformedError as e:
        return FrontmatterParseTrace(
            accepted_status=STATUS_MALFORMED,
            canonical_subset_jcs_sha256_hex="",
            error_class=ERROR_CLASS_MALFORMED,
            persona_name="",
            persona_slug="",
            schema_version="",
            tools_count=0,
        )
    except PersonaCanonicalFormDependencyMissingError:
        # YAML dep missing — re-raise so callers can surface env errors.
        raise
    except Exception as e:
        # PyYAML raises yaml.YAMLError on syntactic errors.
        return FrontmatterParseTrace(
            accepted_status=STATUS_YAML_PARSE_ERROR,
            canonical_subset_jcs_sha256_hex="",
            error_class=ERROR_CLASS_YAML,
            persona_name="",
            persona_slug="",
            schema_version="",
            tools_count=0,
        )

    # Step 3 — extract_canonical_subset. Capture name/slug/version up-front
    # so they end up in the trace even on shape-error paths (forward-
    # compat: callers see "we got this far" intermediate state).
    persona_name = _safe_str(fm_dict.get("name"))
    persona_slug = _safe_str(fm_dict.get("persona_slug"))
    schema_version = _safe_str(fm_dict.get("schema_version"))
    tools_count = _normalise_tools_count(fm_dict.get("tools"))

    try:
        canonical_subset = extract_canonical_subset(fm_dict)
    except (KeyError, ValueError):
        return FrontmatterParseTrace(
            accepted_status=STATUS_INVALID_SHAPE,
            canonical_subset_jcs_sha256_hex="",
            error_class=ERROR_CLASS_INVALID_SHAPE,
            persona_name=persona_name,
            persona_slug=persona_slug,
            schema_version=schema_version,
            tools_count=tools_count,
        )

    # Step 4 — canonical JCS bytes + SHA-256 hex.
    jcs_bytes = canonical_jcs_bytes(canonical_subset)
    canonical_sha = hashlib.sha256(jcs_bytes).hexdigest()

    return FrontmatterParseTrace(
        accepted_status=STATUS_OK,
        canonical_subset_jcs_sha256_hex=canonical_sha,
        error_class="",
        persona_name=persona_name,
        persona_slug=persona_slug,
        schema_version=schema_version,
        tools_count=tools_count,
    )


# ---------------------------------------------------------------------------
# Trace serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_frontmatter_trace(trace: FrontmatterParseTrace) -> bytes:
    """Serialise a trace to its JCS-canonical UTF-8 bytes.

    Raises:
        PersonaCanonicalFormDependencyMissingError: if ``rfc8785`` is
            not installed in this environment.
    """
    if not _HAS_RFC8785:
        raise PersonaCanonicalFormDependencyMissingError("rfc8785")
    return _rfc8785_lib.dumps(trace.to_canonical_dict())


def frontmatter_trace_sha256_hex(trace: FrontmatterParseTrace) -> str:
    """SHA-256 hex of the JCS bytes of ``trace``."""
    return hashlib.sha256(serialize_frontmatter_trace(trace)).hexdigest()


def frontmatter_trace_hash_prefixed(trace: FrontmatterParseTrace) -> str:
    """Prefixed outer hash: ``"sha256:" + frontmatter_trace_sha256_hex``."""
    return HASH_PREFIX + frontmatter_trace_sha256_hex(trace)


# ---------------------------------------------------------------------------
# Re-exports for downstream importers that want one-stop access.
# ---------------------------------------------------------------------------

__all__ = [
    "ACCEPTED_SCHEMA_VERSIONS",
    "ACCEPTED_STATUS_VALUES",
    "CANONICAL_IDENTITY_PINNED_KEYS",
    "CANONICAL_TOP_LEVEL_KEYS",
    "ERROR_CLASS_INVALID_SHAPE",
    "ERROR_CLASS_MALFORMED",
    "ERROR_CLASS_MISSING",
    "ERROR_CLASS_YAML",
    "FRONTMATTER_TRACE_SCHEMA",
    "FrontmatterParseTrace",
    "HASH_PREFIX",
    "SHA256_HEX_LEN",
    "STATUS_INVALID_SHAPE",
    "STATUS_MALFORMED",
    "STATUS_MISSING_FENCE",
    "STATUS_OK",
    "STATUS_YAML_PARSE_ERROR",
    "build_frontmatter_trace",
    "frontmatter_trace_hash_prefixed",
    "frontmatter_trace_sha256_hex",
    "serialize_frontmatter_trace",
]
