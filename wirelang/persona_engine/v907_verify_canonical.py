# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""V-907 engine-side verify canonical-trace helpers.

This module is the **Python sibling** of the Rust crate
``persona-engine-v907-verify`` (PR #120 + Tag-26 mini-welle, expanded
to a cross-lang canonical-trace surface in Tag-35).  Where the Rust
crate provides a typed ``PersonaDef`` + ``compute_v907_pin`` +
``verify_v907_pin`` surface above the JCS-canonical subset, this
module provides the canonical-trace surface that pairs with it
byte-paritätisch — both sides emit a JCS-canonical ``V907VerifyTrace``
per compute outcome so the Phase-3a 3-way-triangle (Doppelbetrieb-
Vergleich) can diff Python-side and Rust-side engine-V-907-verify
traces byte-for-byte without round-tripping through any other
substrate.

Why a sibling module?
---------------------

The existing :mod:`wirelang.persona_engine.v907_verify` provides the
spawn-time verify gate (``compute_v907_pin`` + ``verify_v907_pin``)
but does NOT emit a structured trace.  The Rust crate's typed
``VerifyResult`` API and its error variants (``PersonaHashError::Compute``
and ``PersonaHashError::Drift``) are the surface we need to cross-anchor
against — compute-success, compute-error, drift on verify — and a
per-call structured trace is the right shape for the 3-way triangle.

Keeping the helpers in a separate Apache-2.0 module preserves the
existing ``v907_verify.py`` BUSL surface unchanged (spec §5 anchor,
no licence change) and matches the sibling-pattern Reza used for
``wirelang.persona.frontmatter_parser_canonical`` (Tag-34 sibling
of ``persona-engine-frontmatter-parser``).

Schema
------

The canonical-trace carries exactly eight top-level fields
(alphabetically sorted in the canonical form):

- ``accepted_status`` — One of ``"ok"``, ``"compute_error"``.
  ``"ok"`` is set when the markdown text computed through to a
  byte-identical V-907 pin.
- ``canonical_subset_jcs_sha256_hex`` — SHA-256 hex of the JCS bytes
  of the engine-side canonical subset that was hashed for the pin.
  Empty string ``""`` when ``accepted_status != "ok"``.
- ``default_schema_version_used`` — ``True`` iff the engine had to
  inject the ``persona-v1`` default because the front-matter omitted
  the ``schema_version`` key (mirrors Python ``v907_verify.py`` lines
  ~161-167 and Rust ``DEFAULT_SCHEMA_VERSION``).  ``False`` otherwise
  and on ``compute_error`` (no canonical subset was reached).
- ``error_class`` — Error class name when non-``ok``.  Currently
  ``"PersonaHashComputeError"`` for any compute-side failure; the
  ``PersonaHashDriftError`` path lives in the verify-time wrapper
  (:func:`verify_v907_pin`) and is NOT part of the canonical-trace
  surface (drift is a *verify outcome*, not a *compute outcome*, and
  the trace fixes the compute side only).  Empty string ``""`` on
  ``ok``.  (Schema-symmetric: always present, never omitted, to keep
  the JCS-canonical key-set stable across success and failure.)
- ``optional_keys_present`` — Comma-joined alphabetically-sorted list
  of recognised optional V-907 keys (``identity_pinned``,
  ``capabilities``, ``domain``, ``reports_to``) that were lifted
  into the canonical subset.  Empty string on ``compute_error``.
  Lower-case-only, comma-separated, no spaces.  Examples:
  ``"identity_pinned"``, ``"domain,identity_pinned"``,
  ``"capabilities,domain,identity_pinned,reports_to"``.
- ``pin`` — The freshly-computed pin (``"sha256:<64hex>"``) on ``ok``.
  Empty string ``""`` on ``compute_error``.
- ``schema`` — Constant schema id ``"wakir.persona-engine.v907-verify-canonical/1"``.
- ``schema_version`` — The effective ``schema_version`` after any
  defaulting (``"persona-v1"`` if the front-matter omitted the key,
  otherwise the front-matter value verbatim).  Empty string on
  ``compute_error``.

Serialisation
-------------

The canonical bytes are produced by ``rfc8785.dumps`` (RFC 8785 JCS).
The outer trace hash is ``"sha256:" + hex(SHA-256(canonical_bytes))``.

This is the same serialisation discipline used by every other Phase-3a
cross-lang canonical-trace module — JCS-canonical bytes, SHA-256, hex,
prefixed with the schema id ``"sha256:"``.  Rust pendant uses
``serde_jcs::to_vec`` + ``sha2::Sha256``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/v907-verify-cross-lang/fixtures.json`` is the
byte-level cross-lang pin: both
``wirelang/tests/persona_engine/test_v907_verify_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-v907-verify/tests/cross_lang_fixture_test.rs``
(Rust) consume the same vectors.  Any drift on either side fails both
suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                       <-> Rust pendant
    ----------------------------------------------------------------------
    build_v907_verify_trace(md_text) -> V907VerifyTrace <-> build_v907_verify_trace
    serialize_v907_verify_trace(trace) -> bytes         <-> serialize_trace
    v907_verify_trace_sha256_hex(trace) -> str          <-> trace_sha256_hex
    v907_verify_trace_hash_prefixed(trace) -> str       <-> trace_hash_prefixed
    V907VerifyTrace (dataclass)                         <-> V907VerifyTrace
    V907_VERIFY_TRACE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                                    <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a — Rust-Crate-Bundle Item 3 (v907-verify).
- ADR-0065 — Phase-3c cutover Python-default zu Rust-default (V-907 is
  the direct gate that this trace anchors).
- ADR-0066 — Phase-3c-Beschleunigung Option A+.

V-907 pin pack anchor (Tag-34 sibling pattern)
----------------------------------------------

The ``f01-sample-axis-a-min`` fixture's ``pin`` field is the historical
SAMPLE_AXIS_A_MIN anchor pin
``sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39``
(captured 2026-05-16 via local Python compute and pinned in the Rust
crate's ``tests/v907_verify_smoke_test.rs`` as ``PIN_AXIS_A_MIN``).
This binds the new canonical-trace surface to the same V-907 ground
truth the Rust smoke tests already consume.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

# ---------------------------------------------------------------------------
# Optional-dependency resolver (same posture as frontmatter_parser_canonical).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False


#: JCS-canonical schema id for the V-907 engine-verify trace wire form.
#: Cross-lang anchor — must match the Rust constant of the same name.
V907_VERIFY_TRACE_SCHEMA: Final[str] = (
    "wakir.persona-engine.v907-verify-canonical/1"
)

#: Outer-hash prefix.  Cross-lang anchor.
HASH_PREFIX: Final[str] = "sha256:"

#: Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
SHA256_HEX_LEN: Final[int] = 64

#: Engine-side default ``schema_version`` injected when the axis-A
#: front-matter omits the key.  Mirrors Rust ``DEFAULT_SCHEMA_VERSION``
#: and Python ``v907_verify.py`` lines ~161-167.
DEFAULT_SCHEMA_VERSION: Final[str] = "persona-v1"

#: Recognised optional V-907 keys lifted from the front-matter into
#: the engine-side canonical subset.  Order matches Python
#: ``v907_verify.py`` line ~175 (``for key in (...)``) and Rust
#: ``ENGINE_OPTIONAL_KEYS``.  Iterated in declaration order; the
#: ``optional_keys_present`` trace field is alphabetically sorted for
#: stable cross-lang wire output regardless of front-matter order.
ENGINE_OPTIONAL_KEYS: Final[tuple[str, ...]] = (
    "identity_pinned",
    "capabilities",
    "domain",
    "reports_to",
)

#: Accepted-status wire-string values.  Frozen across Rust/Python.
STATUS_OK: Final[str] = "ok"
STATUS_COMPUTE_ERROR: Final[str] = "compute_error"

ACCEPTED_STATUS_VALUES: Final[tuple[str, ...]] = (
    STATUS_OK,
    STATUS_COMPUTE_ERROR,
)

#: Error-class wire-string values.  Frozen across Rust/Python.  Empty
#: string is reserved for the success path (``status == "ok"``).
ERROR_CLASS_COMPUTE: Final[str] = "PersonaHashComputeError"


# ---------------------------------------------------------------------------
# Trace dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V907VerifyTrace:
    """Canonical-trace projection of a V-907 engine-side compute outcome.

    Fields are ordered to match the alphabetical JCS sort the wire form
    uses; the dataclass itself is otherwise an opaque record.
    """

    accepted_status: str
    canonical_subset_jcs_sha256_hex: str
    default_schema_version_used: bool
    error_class: str
    optional_keys_present: str
    pin: str
    schema_version: str

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project this trace onto a JSON-compatible dict, ready for JCS.

        Keys are inserted in alphabetical order to document the wire
        contract; JCS will re-sort them lexicographically anyway, so
        the insertion order has no effect on the resulting bytes.
        """
        return {
            "accepted_status": self.accepted_status,
            "canonical_subset_jcs_sha256_hex": self.canonical_subset_jcs_sha256_hex,
            "default_schema_version_used": bool(self.default_schema_version_used),
            "error_class": self.error_class,
            "optional_keys_present": self.optional_keys_present,
            "pin": self.pin,
            "schema": V907_VERIFY_TRACE_SCHEMA,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Trace-build helpers.
# ---------------------------------------------------------------------------


def _compute_v907_subset_and_pin(
    md_text: str,
) -> tuple[dict[str, Any], str, bool, list[str]]:
    """Compute (canonical_subset, pin, default_used, optional_keys_present).

    Re-implements the canonical-subset-construction block of
    :mod:`wirelang.persona_engine.v907_verify` so the trace surface
    can capture the *intermediate* canonical subset (for the
    ``canonical_subset_jcs_sha256_hex`` field) without re-parsing.

    Returns:
        Tuple of ``(canonical_subset, pin, default_used, optional_keys_present_sorted)``.

    Raises:
        Anything that the underlying parse/hash primitives raise;
        callers must catch and project into a ``compute_error`` trace.
    """
    from wirelang.persona.persona_canonical_form import (
        parse_frontmatter,
        split_frontmatter,
    )
    from wirelang.persona.persona_hash import (
        compute_persona_hash_from_canonical,
    )

    fm, _body = split_frontmatter(md_text)
    mapping = parse_frontmatter(fm)

    raw_schema_version = mapping.get("schema_version")
    default_used = not raw_schema_version
    schema_version = (
        raw_schema_version if raw_schema_version else DEFAULT_SCHEMA_VERSION
    )

    canonical_subset: dict[str, Any] = {"schema_version": schema_version}
    present_keys: list[str] = []
    for key in ENGINE_OPTIONAL_KEYS:
        if key in mapping:
            canonical_subset[key] = mapping[key]
            present_keys.append(key)
    present_keys.sort()

    pin = compute_persona_hash_from_canonical(canonical_subset)
    return canonical_subset, pin, default_used, present_keys


def build_v907_verify_trace(md_text: str) -> V907VerifyTrace:
    """Build a canonical V-907-verify compute-outcome trace.

    The function is **infallible** at the trace-build layer: every
    compute outcome (success, parse failure, YAML error, hash-input
    error) is captured as a structured trace with the appropriate
    ``accepted_status`` and ``error_class`` populated.  This is the
    cross-lang contract — both Rust and Python must always return a
    trace, never raise, so the fixture vectors can pin error paths
    just as easily as success paths.

    The ``pin``, ``canonical_subset_jcs_sha256_hex``, and
    ``optional_keys_present`` fields are populated only when
    ``accepted_status == "ok"``; otherwise they are empty strings
    (NOT a SHA-256 of empty input).
    """
    from wirelang.persona.persona_canonical_form import (
        canonical_jcs_bytes,
        PersonaCanonicalFormDependencyMissingError,
    )

    try:
        canonical_subset, pin, default_used, present_keys = (
            _compute_v907_subset_and_pin(md_text)
        )
    except PersonaCanonicalFormDependencyMissingError:
        # YAML/rfc8785 missing — re-raise so callers can surface env errors.
        # Mirrors persona_canonical_form's resolver discipline.
        raise
    except Exception:  # noqa: BLE001 - any compute path failure -> trace
        return V907VerifyTrace(
            accepted_status=STATUS_COMPUTE_ERROR,
            canonical_subset_jcs_sha256_hex="",
            default_schema_version_used=False,
            error_class=ERROR_CLASS_COMPUTE,
            optional_keys_present="",
            pin="",
            schema_version="",
        )

    canonical_sha = hashlib.sha256(canonical_jcs_bytes(canonical_subset)).hexdigest()
    optional_keys_present = ",".join(present_keys)

    return V907VerifyTrace(
        accepted_status=STATUS_OK,
        canonical_subset_jcs_sha256_hex=canonical_sha,
        default_schema_version_used=default_used,
        error_class="",
        optional_keys_present=optional_keys_present,
        pin=pin,
        schema_version=canonical_subset["schema_version"],
    )


# ---------------------------------------------------------------------------
# Trace serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_v907_verify_trace(trace: V907VerifyTrace) -> bytes:
    """Serialise a trace to its JCS-canonical UTF-8 bytes.

    Raises:
        ImportError: if ``rfc8785`` is not installed in this environment.
            (Re-raised as the underlying dependency-missing error so
            callers can surface install hints.)
    """
    if not _HAS_RFC8785:
        from wirelang.persona.persona_canonical_form import (
            PersonaCanonicalFormDependencyMissingError,
        )

        raise PersonaCanonicalFormDependencyMissingError("rfc8785")
    return _rfc8785_lib.dumps(trace.to_canonical_dict())


def v907_verify_trace_sha256_hex(trace: V907VerifyTrace) -> str:
    """SHA-256 hex of the JCS bytes of ``trace``."""
    return hashlib.sha256(serialize_v907_verify_trace(trace)).hexdigest()


def v907_verify_trace_hash_prefixed(trace: V907VerifyTrace) -> str:
    """Prefixed outer hash: ``"sha256:" + v907_verify_trace_sha256_hex``."""
    return HASH_PREFIX + v907_verify_trace_sha256_hex(trace)


# ---------------------------------------------------------------------------
# Re-exports for downstream importers that want one-stop access.
# ---------------------------------------------------------------------------

__all__ = [
    "ACCEPTED_STATUS_VALUES",
    "DEFAULT_SCHEMA_VERSION",
    "ENGINE_OPTIONAL_KEYS",
    "ERROR_CLASS_COMPUTE",
    "HASH_PREFIX",
    "SHA256_HEX_LEN",
    "STATUS_COMPUTE_ERROR",
    "STATUS_OK",
    "V907_VERIFY_TRACE_SCHEMA",
    "V907VerifyTrace",
    "build_v907_verify_trace",
    "serialize_v907_verify_trace",
    "v907_verify_trace_hash_prefixed",
    "v907_verify_trace_sha256_hex",
]
