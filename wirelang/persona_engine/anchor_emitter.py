# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-engine anchor-envelope emitter — Python pendant.

This module is the **Python sibling** of the Rust
``persona-engine-anchor-emitter`` crate (Phase-3a Item 7, PR #141,
merged 2026-05-17 00:27 UTC). The Rust crate defines the
authoritative wire-shape; this module mirrors it byte-for-byte so
the Phase-3a 3-way-triangle (Doppelbetrieb) can diff Python-side and
Rust-side anchor envelopes byte-for-byte before either reaches the
OTS calendar.

Schema-parity is enforced by the cross-lang fixture vectors at
``tests/fixtures/anchor-emitter-cross-lang/fixtures.json``: both
sides hash the same five fixture envelopes and pin the same
envelope-hash + payload-hash tuples in their respective test trees.
Any drift on either side breaks both test suites.

Relationship to ``recovery_drill_anchor.py``
--------------------------------------------

The pre-existing module
:mod:`wirelang.persona.recovery_drill_anchor` carries two helpers
``envelope_jcs_bytes`` / ``envelope_payload_hash`` that hash the
**input envelope dict** directly. Those helpers serve the
recovery-drill OI-PILOT-4 path: an envelope-dict comes in already
shaped, and the SHA-256 of its JCS bytes is the WAT-spool
payload-hash.

The anchor-emitter pattern here is **different and complementary**:
the caller supplies four discrete fields (event_id +
timestamp_utc + persona_id + already-canonicalised payload bytes)
and the emitter builds an **outer wire-envelope** with five fields
(adds ``payload_sha256`` + ``schema``). The outer envelope is the
artefact that goes onto the WAT spool and gets OTS-anchored. The
two helpers therefore live next to each other in the codebase
without overlapping — ``recovery_drill_anchor`` is the input-side
helper for a specific schema; ``anchor_emitter`` is the
output-side emitter for the generic WAT-anchor-envelope wire-shape
that the Rust crate also emits.

Schema parity table (Python <-> Rust)
-------------------------------------

::

    Python helper                          <-> Rust function
    ---------------------------------------------------------------
    serialize_anchor(env) -> bytes         <-> serialize_anchor
    hash_anchor(env) -> str                <-> hash_anchor
    build_anchor_envelope(input)           <-> build_anchor_envelope
    AnchorEnvelope (dataclass)             <-> AnchorEnvelope (struct)
    AnchorEmitterInput (dataclass)         <-> AnchorEmitterInput
    AnchorEmitterError (exception)         <-> AnchorEmitterError
    sha256_hex(bytes) -> str               <-> sha256_hex
    ENVELOPE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                       <-> same constants

Wire-shape pins
---------------

The outer envelope on the wire has five lexicographically ordered
keys (JCS-canonical order):

  - ``event_id``        (caller-owned string)
  - ``payload_sha256``  (lower-case hex tail of SHA-256 of the
                         caller-supplied payload bytes; no prefix)
  - ``persona_id``      (caller-owned string)
  - ``schema``          (constant ``ENVELOPE_SCHEMA``)
  - ``timestamp_utc``   (RFC-3339 second-precision UTC string)

``serialize_anchor`` returns the JCS-canonical bytes of that
five-field object. ``hash_anchor`` returns
``"sha256:" + hex(SHA-256(canonical_bytes))``. The bare-hex
form of the outer hash is also available via
``sha256_hex(serialize_anchor(env))``.

Hash-prefix contract
--------------------

``hash_anchor`` returns the string ``"sha256:<lower-case-64-hex>"``,
matching the Rust pendant. Downstream consumers that compare against
``recovery_drill_anchor.envelope_payload_hash`` (which returns bare
hex) can strip the seven-character prefix or compare via
``sha256_hex(serialize_anchor(env))``.

Sandbox boundary
----------------

The emitter is a **pure function** — no I/O, no clock, no network.
All hermetic; safe to call from any sandbox.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple


# ---------------------------------------------------------------------------
# Constants — mirror the Rust crate's `pub const` items.
# ---------------------------------------------------------------------------

#: Schema-version tag embedded in every emitted envelope. Bumped on
#: any wire-shape change; consumers MUST reject unknown values.
ENVELOPE_SCHEMA: str = "wakir.wat.anchor-envelope/1"

#: Hex-string length of a SHA-256 digest (lower-case, no prefix).
SHA256_HEX_LEN: int = 64

#: Prefix prepended to the SHA-256 hex tail by :func:`hash_anchor`.
HASH_PREFIX: str = "sha256:"


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class AnchorEmitterError(ValueError):
    """Base class for anchor-emitter typed errors.

    Subclasses carry the same audit-diagnostic shape as the Rust
    variants (``EmptyField`` / ``BadTimestampShape`` / ``JcsFailure``)
    so cross-lang test fixtures can compare the failure modes.
    """


class EmptyFieldError(AnchorEmitterError):
    """A required string field was empty (after whitespace trim).

    Mirrors the Rust ``AnchorEmitterError::EmptyField(&'static str)``
    variant. The ``field`` attribute carries the field name.
    """

    def __init__(self, field: str) -> None:
        super().__init__(
            f"anchor-envelope field {field!r} must be non-empty"
        )
        self.field = field


class BadTimestampShapeError(AnchorEmitterError):
    """``timestamp_utc`` does not match the RFC-3339 second-precision
    UTC shape ``YYYY-MM-DDTHH:MM:SSZ``.

    Mirrors the Rust ``AnchorEmitterError::BadTimestampShape(String)``
    variant. The ``value`` attribute carries the offending string.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f"anchor-envelope timestamp_utc {value!r} is not in "
            f"RFC-3339 second-precision UTC shape "
            f"(YYYY-MM-DDTHH:MM:SSZ)"
        )
        self.value = value


# ---------------------------------------------------------------------------
# Input + Output records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnchorEmitterInput:
    """Caller-supplied input to :func:`build_anchor_envelope`.

    Mirrors the four Sprint-Auftrag fields verbatim. ``frozen=True``
    so the input record is hashable; tests can stick inputs into
    sets / dict-keys without writing wrappers.

    Attributes
    ----------
    event_id:
        Unique identifier of the event being anchored. Caller-owned;
        no shape enforcement beyond non-emptiness.
    timestamp_utc:
        RFC-3339 second-precision UTC timestamp of the event
        (``YYYY-MM-DDTHH:MM:SSZ``). The emitter does not parse the
        calendar date but does enforce the surface shape so lexical
        sort matches chronological sort.
    persona_id:
        Persona identifier the event is attributed to. Caller-owned.
    payload_jcs_bytes:
        Already-canonicalised payload bytes. The caller is
        responsible for canonicalisation; this module hashes these
        bytes verbatim and embeds the hex tail in the outer envelope.
    """

    event_id: str
    timestamp_utc: str
    persona_id: str
    payload_jcs_bytes: bytes


@dataclass(frozen=True)
class AnchorEnvelope:
    """The emitter's output record.

    Carries the four input fields verbatim and is the input to both
    :func:`serialize_anchor` and :func:`hash_anchor`.

    ``payload_jcs_bytes`` is kept as raw bytes on the Python side
    but is embedded in the canonical envelope as its SHA-256 hex
    tail (see module-level docstring for rationale).
    """

    event_id: str
    timestamp_utc: str
    persona_id: str
    payload_jcs_bytes: bytes


# ---------------------------------------------------------------------------
# Hash primitive.
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    """Lower-case hex tail of ``SHA-256(data)``.

    Matches the Rust :func:`sha256_hex` shape (64 lower-case hex
    chars, no prefix) so cross-lang fixtures can pin the same string.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(
            f"sha256_hex requires bytes or bytearray; got {type(data)!r}"
        )
    return hashlib.sha256(bytes(data)).hexdigest()


# ---------------------------------------------------------------------------
# Timestamp surface check.
# ---------------------------------------------------------------------------


def _is_rfc3339_second_utc(s: str) -> bool:
    """Return True iff ``s`` matches ``YYYY-MM-DDTHH:MM:SSZ``.

    Surface check only; does not validate that the calendar date is
    real. Mirrors the Rust ``is_rfc3339_second_utc`` byte-for-byte
    so the cross-lang rejection table is the same on both sides.
    """
    if not isinstance(s, str) or len(s) != 20:
        return False
    for i, ch in enumerate(s):
        if i in (4, 7):
            ok = ch == "-"
        elif i == 10:
            ok = ch == "T"
        elif i in (13, 16):
            ok = ch == ":"
        elif i == 19:
            ok = ch == "Z"
        else:
            ok = "0" <= ch <= "9"
        if not ok:
            return False
    return True


# ---------------------------------------------------------------------------
# JCS canonicalisation (RFC 8785).
# ---------------------------------------------------------------------------


def _jcs_dumps(obj: Mapping[str, Any]) -> bytes:
    """Return RFC 8785 JCS-canonical bytes for ``obj``.

    Prefers the ``rfc8785`` package when available (production +
    pinned-CI path); falls back to ``json.dumps(sort_keys=True,
    separators=(",",":"), ensure_ascii=False)`` for hermetic
    environments without the dependency. For the flat
    string-only wire-shape this emitter produces, the two paths
    yield byte-identical output (verified by the cross-lang fixture
    test, which pins the bytes regardless of canonicaliser
    implementation).
    """
    try:  # pragma: no cover - prefer real JCS when available
        import rfc8785

        return rfc8785.dumps(dict(obj))
    except ImportError:
        return json.dumps(
            dict(obj),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


# ---------------------------------------------------------------------------
# Wire-shape builder.
# ---------------------------------------------------------------------------


def _to_wire(env: AnchorEnvelope) -> Dict[str, str]:
    """Return the wire-shape dict for an envelope.

    Five lexicographically ordered keys; the order matches the Rust
    ``WireEnvelope`` struct field order (which itself matches JCS lex
    order). Python dicts preserve insertion order since 3.7, but JCS
    canonicalisation sorts keys regardless — the explicit lex order
    here is documentation, not a load-bearing invariant.
    """
    payload_sha = sha256_hex(env.payload_jcs_bytes)
    return {
        "event_id": env.event_id,
        "payload_sha256": payload_sha,
        "persona_id": env.persona_id,
        "schema": ENVELOPE_SCHEMA,
        "timestamp_utc": env.timestamp_utc,
    }


# ---------------------------------------------------------------------------
# Public builder.
# ---------------------------------------------------------------------------


def build_anchor_envelope(input_: AnchorEmitterInput) -> AnchorEnvelope:
    """Build an :class:`AnchorEnvelope` from caller-supplied input.

    Mirrors the Rust ``build_anchor_envelope`` precondition:
    every string field non-empty (trimmed), timestamp shape pinned.
    Pure function.

    Raises
    ------
    EmptyFieldError
        If any of ``event_id`` / ``persona_id`` / ``timestamp_utc``
        is empty after whitespace trim.
    BadTimestampShapeError
        If ``timestamp_utc`` does not match the RFC-3339
        second-precision UTC shape ``YYYY-MM-DDTHH:MM:SSZ``.

    Notes
    -----
    Empty ``payload_jcs_bytes`` IS legal (anchoring a "this event
    happened, no payload of consequence" marker); the Rust sibling
    allows it too. SHA-256 of an empty byte string is the well-known
    constant
    ``e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855``.
    """
    if not isinstance(input_, AnchorEmitterInput):
        raise TypeError(
            f"build_anchor_envelope requires AnchorEmitterInput; "
            f"got {type(input_)!r}"
        )
    if not input_.event_id.strip():
        raise EmptyFieldError("event_id")
    if not input_.persona_id.strip():
        raise EmptyFieldError("persona_id")
    if not input_.timestamp_utc.strip():
        raise EmptyFieldError("timestamp_utc")
    if not _is_rfc3339_second_utc(input_.timestamp_utc):
        raise BadTimestampShapeError(input_.timestamp_utc)
    if not isinstance(input_.payload_jcs_bytes, (bytes, bytearray)):
        raise TypeError(
            f"AnchorEmitterInput.payload_jcs_bytes must be bytes; "
            f"got {type(input_.payload_jcs_bytes)!r}"
        )
    return AnchorEnvelope(
        event_id=input_.event_id,
        timestamp_utc=input_.timestamp_utc,
        persona_id=input_.persona_id,
        payload_jcs_bytes=bytes(input_.payload_jcs_bytes),
    )


# ---------------------------------------------------------------------------
# Serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_anchor(env: AnchorEnvelope) -> bytes:
    """Serialise an :class:`AnchorEnvelope` to RFC 8785 JCS bytes.

    The output is deterministic for a given semantic envelope; the
    cross-lang fixture test pins the byte sequence against five
    fixture envelopes (the Rust pendant pins the same bytes).
    """
    if not isinstance(env, AnchorEnvelope):
        raise TypeError(
            f"serialize_anchor requires AnchorEnvelope; got {type(env)!r}"
        )
    return _jcs_dumps(_to_wire(env))


def hash_anchor(env: AnchorEnvelope) -> str:
    """Return the ``"sha256:<hex>"`` payload-hash string for ``env``.

    Mirrors the Rust :func:`hash_anchor` shape with the Sprint-Auftrag-
    mandated ``sha256:`` prefix.

    Implementation: SHA-256 of the :func:`serialize_anchor` output.
    The bare-hex form (matching :func:`sha256_hex` over the same
    bytes) is available via ``sha256_hex(serialize_anchor(env))``.
    """
    canonical = serialize_anchor(env)
    return HASH_PREFIX + sha256_hex(canonical)


def serialize_and_hash(env: AnchorEnvelope) -> Tuple[bytes, str]:
    """Return both canonical bytes and prefixed hash in one call.

    Saves a re-canonicalisation pass for callers that need both (the
    WAT spool writer wants the bytes for the spool file and the hash
    for the bridge-audit row). Byte-identical to the pair
    ``(serialize_anchor(env), hash_anchor(env))``.
    """
    canonical = serialize_anchor(env)
    return canonical, HASH_PREFIX + sha256_hex(canonical)


# ---------------------------------------------------------------------------
# Cross-lang fixture exposure (consumed by tests).
# ---------------------------------------------------------------------------


def _test_only_wire_value(env: AnchorEnvelope) -> Dict[str, str]:
    """Test-only helper: return the wire-shape dict for an envelope.

    Hidden-looking but explicitly public so the cross-lang fixture
    test can assert that ``payload_sha256`` matches
    ``sha256_hex(env.payload_jcs_bytes)``.
    """
    return _to_wire(env)


# ---------------------------------------------------------------------------
# Spec-invariant self-check.
# ---------------------------------------------------------------------------


def assert_spec_invariants() -> None:
    """Module-internal invariant check used by unit tests.

    Mirrors the Rust ``assert_spec_invariants`` guard.

    Raises
    ------
    AssertionError
        If any spec invariant has drifted.
    """
    if not ENVELOPE_SCHEMA.startswith("wakir."):
        raise AssertionError(
            "ENVELOPE_SCHEMA must live in the wakir.* namespace"
        )
    if "/1" not in ENVELOPE_SCHEMA:
        raise AssertionError(
            "ENVELOPE_SCHEMA must carry an explicit /<version> tag"
        )
    if HASH_PREFIX != "sha256:":
        raise AssertionError(
            "HASH_PREFIX drifted from Sprint-Auftrag-pinned value"
        )
    if SHA256_HEX_LEN != 64:
        raise AssertionError(
            "SHA256_HEX_LEN must equal 64 (256 bits / 4)"
        )


__all__ = [
    "AnchorEmitterError",
    "AnchorEmitterInput",
    "AnchorEnvelope",
    "BadTimestampShapeError",
    "EmptyFieldError",
    "ENVELOPE_SCHEMA",
    "HASH_PREFIX",
    "SHA256_HEX_LEN",
    "assert_spec_invariants",
    "build_anchor_envelope",
    "hash_anchor",
    "serialize_and_hash",
    "serialize_anchor",
    "sha256_hex",
]
