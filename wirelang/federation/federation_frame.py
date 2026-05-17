# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-Engine federation-frame parser — Python pendant.

This module is the byte-identical Python sibling of the Rust crate
``wirelang-rust/crates/persona-engine-federation-frame-parser``
(Phase-3a Item 9, PR #148). The Rust crate originally shipped with
a ``TODO_PYTHON_FRAME_PARITY_PIN`` placeholder because the Python
side did not yet exist; this Tag-14 follow-up closes that gap and
elevates the cross-lang pin to a real byte-pinned fixture file.

# Public surface

- :class:`FederationFrame` — typed envelope (dataclass).
- :class:`FrameHeader`     — schema, frame_id, source_runtime,
                             target_runtime, ts_utc, version.
- :class:`FederationPayload` — typed enum-like union over the four
                                payload kinds (TaskAssigned,
                                TaskOutput, MultiOrgAttestation,
                                SpiffeBundleSync).
- :func:`parse_frame`       — JCS-canonical JSON bytes -> typed frame.
- :func:`serialize_frame`   — typed frame -> JCS-canonical JSON bytes.
- :func:`compute_frame_id`  — deterministic frame-id derivation
                              (``"frame-sha256:<hex>"``).
- :func:`signing_payload_bytes` — JCS bytes of ``{header, payload}``
                                  subtree (anchor_ref + signature
                                  excluded; signer-input helper).
- :class:`ParseError`       — error surface (mirrors Rust enum
                              variant set).

# Cross-language byte-parity contract

The function pair :func:`serialize_frame` / :func:`parse_frame` is
byte-identical to the Rust crate's
``persona_engine_federation_frame_parser::serialize_frame`` /
``parse_frame``. The contract is pinned by the fixture file at::

    tests/federation/fixtures/federation_frame_cross_lang_pins.json

which contains five reference (input, expected-bytes) pairs. The
Python test suite at ``wirelang/tests/test_federation_frame_parser.py``
and the Rust cross-lang test at
``wirelang-rust/crates/persona-engine-federation-frame-parser/tests/cross_lang_python_sync_test.rs``
both read the same JSON file and verify their respective
``serialize_frame`` produces byte-identical output for each fixture
input. Any drift between the two implementations fails both lanes
at once.

# Schema-parity table (Rust <-> Python)

  Rust ``FederationFrame::header.schema``     <-> Python ``FederationFrame.header.schema``
  Rust ``FederationFrame::header.frame_id``   <-> Python ``FederationFrame.header.frame_id``
  Rust ``parse_frame(bytes) -> Result``       <-> Python ``parse_frame(bytes) -> FederationFrame``
  Rust ``serialize_frame(frame) -> Vec<u8>``  <-> Python ``serialize_frame(frame) -> bytes``
  Rust ``compute_frame_id(seed) -> String``   <-> Python ``compute_frame_id(seed: bytes) -> str``
  Rust ``signing_payload_bytes(frame)``       <-> Python ``signing_payload_bytes(frame)``

# Wire-string discipline

All frames are JCS-canonical JSON per RFC 8785. JCS canonicalisation
is delegated to :func:`wirelang.identity._jcs_pure.canonicalize`,
which is the same byte-for-byte equivalent of ``rfc8785.dumps`` used
by every other signed Wakir document (AIP, DID, FTD).

# Frame anatomy (high-level)

::

  {
    "anchor_ref": "wat:<sha256-hex>"      (optional; WAT-anchor pointer)
    "header": {
      "frame_id":         "<frame-sha256:hex>",
      "schema":           "wakir.federation.frame/1",
      "source_runtime":   "mira-sandbox" | "wakir-runtime" | "<orgid>/<runtime>",
      "target_runtime":   "wakir-runtime" | "<orgid>/<runtime>",
      "ts_utc":           "YYYY-MM-DDTHH:MM:SSZ",
      "version":          1
    },
    "payload": {
      "data":             { ... payload-kind-specific JSON ... },
      "kind":             "task-assigned" | "task-output"
                        | "multi-org-attestation" | "spiffe-bundle-sync",
      "schema":           "<payload-kind-schema>"
    },
    "signature": "<ed25519-hex-sig>"     (optional; signature is over
                                          the JCS bytes of {header, payload})
  }

Note JCS key-ordering: keys sort by UTF-16 code-unit sequence. The
outer key order is therefore ``anchor_ref, header, payload, signature``;
the payload sub-keys sort to ``data, kind, schema``.

# ADR anchors

- ADR-0063 §Folgeartefakte Phase-3a Item 9 — Rust crate.
- Tag-14 Mini-Welle Phase-3a-Folge — this Python sibling.
- ADR-0035 Errata 1 — Rust as Phase-1c language for persona-engine;
  Python sibling remains the wirelang-side contract carrier.
- Tomás Sprint-10 Tag-6 PR #69 — ``bridge-forward-pipe-v1.md``
  task-assigned payload schema authority.
- Reza Sprint-7 Tag-1 — ``multi_org_substrate.py``
  multi-org-attestation payload schema authority.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Mapping, Optional

from wirelang.identity._jcs_pure import canonicalize as _jcs_canonicalize


# ---------------------------------------------------------------------
# Constants — must be string-identical to the Rust crate.
# ---------------------------------------------------------------------

#: Outer-envelope schema tag emitted in every frame header. Bumped on
#: any wire-shape change; consumers MUST reject unknown values.
FRAME_ENVELOPE_SCHEMA: str = "wakir.federation.frame/1"

#: Current frame-envelope wire version. Bumped in lock-step with
#: :data:`FRAME_ENVELOPE_SCHEMA`.
FRAME_ENVELOPE_VERSION: int = 1

#: Schema identifier accepted on inbound task-assigned payloads
#: (parity with ``ACCEPTED_INBOUND_SCHEMA`` in
#: ``wirelang/persona_engine/nats_subscribe_loop.py``).
PAYLOAD_SCHEMA_TASK_ASSIGNED: str = "wakir.agent.task-assigned/1"

#: Schema identifier emitted on task-output payloads
#: (parity with ``OUTBOUND_OUTPUT_SCHEMA`` in
#: ``wirelang/persona_engine/nats_subscribe_loop.py``).
PAYLOAD_SCHEMA_TASK_OUTPUT: str = "wakir.agent.task-output/1"

#: Schema identifier for the multi-org attestation pointer payload
#: (parity with ``ATTESTATION_VALUE_SCHEMA`` in
#: ``wirelang/federation/multi_org_substrate.py``).
PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION: str = (
    "wakir.federation.multi-org-attestation/1"
)

#: Schema identifier for the SPIFFE trust-bundle sync notice.
PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC: str = (
    "wakir.federation.spiffe-bundle-sync/1"
)

#: Prefix prepended to the SHA-256 hex tail by :func:`compute_frame_id`.
FRAME_ID_PREFIX: str = "frame-sha256:"

#: Prefix prepended to the SHA-256 hex tail by a caller building a
#: WAT anchor reference.
ANCHOR_REF_PREFIX: str = "wat:"

#: Maximum size (bytes) of the JCS-canonical frame payload. Matches
#: the bridge-forward-pipe-v1 §3.3 ``prompt_payload`` ceiling
#: (256 KiB) plus envelope headroom (signature + header).
MAX_FRAME_JCS_BYTES: int = 320 * 1024

#: Hex-string length of a SHA-256 digest (lower-case, no prefix).
SHA256_HEX_LEN: int = 64

#: Recognised payload-kind tags (wire-side strings).
_PAYLOAD_KIND_TASK_ASSIGNED: str = "task-assigned"
_PAYLOAD_KIND_TASK_OUTPUT: str = "task-output"
_PAYLOAD_KIND_MULTI_ORG_ATTESTATION: str = "multi-org-attestation"
_PAYLOAD_KIND_SPIFFE_BUNDLE_SYNC: str = "spiffe-bundle-sync"

#: Mapping from wire-side payload-kind tag to schema constant.
_KIND_TO_SCHEMA: Mapping[str, str] = {
    _PAYLOAD_KIND_TASK_ASSIGNED: PAYLOAD_SCHEMA_TASK_ASSIGNED,
    _PAYLOAD_KIND_TASK_OUTPUT: PAYLOAD_SCHEMA_TASK_OUTPUT,
    _PAYLOAD_KIND_MULTI_ORG_ATTESTATION: PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION,
    _PAYLOAD_KIND_SPIFFE_BUNDLE_SYNC: PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC,
}


# ---------------------------------------------------------------------
# Errors — mirrors the Rust ``ParseError`` enum variant set.
# ---------------------------------------------------------------------


class ParseError(ValueError):
    """Base error raised by :func:`parse_frame` / :func:`serialize_frame`.

    Concrete failure modes are surfaced via the ``kind`` attribute,
    which carries one of the variant-tag strings in :attr:`KINDS`.
    The exact tag set mirrors the Rust ``ParseError`` enum, so a
    cross-lang caller can compare error kinds across the two
    implementations.
    """

    #: Stable set of error-kind tags (parity with Rust enum variants).
    KINDS: ClassVar[frozenset] = frozenset(
        {
            "BadUtf8",
            "BadJson",
            "MissingField",
            "UnknownSchema",
            "UnsupportedVersion",
            "BadTimestampShape",
            "BadFrameIdShape",
            "BadAnchorRefShape",
            "BadSignatureShape",
            "BadRuntimeId",
            "JcsFailure",
            "FrameTooLarge",
            "UnknownPayloadKind",
            "PayloadDataNotObject",
        }
    )

    def __init__(self, kind: str, message: str, **detail: Any) -> None:
        if kind not in self.KINDS:
            raise AssertionError(
                f"ParseError kind {kind!r} is not in the canonical set "
                f"(parity broken with Rust crate). Add the variant on "
                f"both sides before raising it."
            )
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.detail = detail


# ---------------------------------------------------------------------
# Frame structs (typed Python surface, dataclasses).
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class FrameHeader:
    """Frame header — fields every frame carries regardless of payload."""

    frame_id: str
    schema: str
    source_runtime: str
    target_runtime: str
    ts_utc: str
    version: int


@dataclass(frozen=True)
class FederationPayload:
    """Closed enum-like payload type.

    Field semantics:

    - ``kind`` is the wire-tag string (``"task-assigned"`` etc.); must
      be one of the four recognised values.
    - ``data`` is a JSON-object (``dict[str, Any]``); preserved
      verbatim (no re-shaping) so forward-compat payload extensions
      round-trip.

    The convenience constructors :meth:`task_assigned`,
    :meth:`task_output`, :meth:`multi_org_attestation`,
    :meth:`spiffe_bundle_sync` exist for parity with the Rust enum
    variants.
    """

    kind: str
    data: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.kind not in _KIND_TO_SCHEMA:
            raise ParseError(
                "UnknownPayloadKind",
                f"payload kind {self.kind!r} is not a recognised variant",
                payload_kind=self.kind,
            )
        if not isinstance(self.data, dict):
            raise ParseError(
                "PayloadDataNotObject",
                "payload `data` must be a JSON object (dict)",
            )

    @property
    def schema(self) -> str:
        """Return the schema tag for this payload kind."""
        return _KIND_TO_SCHEMA[self.kind]

    @classmethod
    def task_assigned(cls, data: Dict[str, Any]) -> "FederationPayload":
        return cls(kind=_PAYLOAD_KIND_TASK_ASSIGNED, data=data)

    @classmethod
    def task_output(cls, data: Dict[str, Any]) -> "FederationPayload":
        return cls(kind=_PAYLOAD_KIND_TASK_OUTPUT, data=data)

    @classmethod
    def multi_org_attestation(
        cls, data: Dict[str, Any]
    ) -> "FederationPayload":
        return cls(kind=_PAYLOAD_KIND_MULTI_ORG_ATTESTATION, data=data)

    @classmethod
    def spiffe_bundle_sync(
        cls, data: Dict[str, Any]
    ) -> "FederationPayload":
        return cls(kind=_PAYLOAD_KIND_SPIFFE_BUNDLE_SYNC, data=data)


@dataclass(frozen=True)
class FederationFrame:
    """Top-level inter-runtime federation frame."""

    header: FrameHeader
    payload: FederationPayload
    anchor_ref: Optional[str] = None
    signature: Optional[str] = None


# ---------------------------------------------------------------------
# Public API — parse / serialize / helpers.
# ---------------------------------------------------------------------


def parse_frame(data: bytes) -> FederationFrame:
    """Parse a federation frame from JCS-canonical JSON bytes.

    Performs the same 12-step validation as the Rust crate:

    1. Size <= :data:`MAX_FRAME_JCS_BYTES`.
    2. UTF-8 decode.
    3. JSON decode.
    4. Envelope-schema == :data:`FRAME_ENVELOPE_SCHEMA`.
    5. Envelope version == :data:`FRAME_ENVELOPE_VERSION`.
    6. ``ts_utc`` matches RFC-3339 second-precision UTC.
    7. ``frame_id`` matches ``frame-sha256:<64-hex>``.
    8. ``source_runtime`` / ``target_runtime`` are non-empty printable ASCII.
    9. ``anchor_ref`` (if present) matches ``wat:<64-hex>``.
    10. ``signature`` (if present) is lower-case hex.
    11. ``payload.kind`` is one of the four recognised variants and
        ``payload.schema`` matches the kind-implied schema tag.
    12. ``payload.data`` is a JSON object.

    Returns a :class:`FederationFrame`. Raises :class:`ParseError`
    on any check failure, with ``kind`` carrying the failure tag.
    """
    if len(data) > MAX_FRAME_JCS_BYTES:
        raise ParseError(
            "FrameTooLarge",
            f"JCS-canonical frame size {len(data)} bytes exceeds "
            f"ceiling {MAX_FRAME_JCS_BYTES} bytes",
            bytes=len(data),
            max=MAX_FRAME_JCS_BYTES,
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("BadUtf8", f"frame bytes are not UTF-8: {exc}") from exc
    try:
        wire = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(
            "BadJson", f"frame bytes are not valid JSON: {exc}"
        ) from exc
    if not isinstance(wire, dict):
        raise ParseError("BadJson", "frame top-level must be a JSON object")

    # Header.
    header_obj = wire.get("header")
    if header_obj is None:
        raise ParseError("BadJson", "frame missing required field 'header'")
    if not isinstance(header_obj, dict):
        raise ParseError("BadJson", "frame 'header' must be a JSON object")
    for required in (
        "frame_id",
        "schema",
        "source_runtime",
        "target_runtime",
        "ts_utc",
        "version",
    ):
        if required not in header_obj:
            raise ParseError(
                "MissingField",
                f"header missing required field {required!r}",
                field=required,
            )
    schema_val = header_obj["schema"]
    if schema_val != FRAME_ENVELOPE_SCHEMA:
        raise ParseError(
            "UnknownSchema",
            f"frame field 'header.schema' carries unknown schema value "
            f"{schema_val!r}",
            field="header.schema",
            value=schema_val,
        )
    version_val = header_obj["version"]
    # Bool is a subclass of int in Python; reject it.
    if isinstance(version_val, bool) or not isinstance(version_val, int):
        raise ParseError(
            "UnsupportedVersion",
            f"frame envelope version {version_val!r} is not an integer",
        )
    if version_val != FRAME_ENVELOPE_VERSION:
        raise ParseError(
            "UnsupportedVersion",
            f"frame envelope version {version_val} is not supported "
            f"(want {FRAME_ENVELOPE_VERSION})",
            version=version_val,
        )
    _validate_timestamp_shape(header_obj["ts_utc"])
    _validate_frame_id_shape(header_obj["frame_id"])
    _validate_runtime_id("source_runtime", header_obj["source_runtime"])
    _validate_runtime_id("target_runtime", header_obj["target_runtime"])

    # Optional anchor_ref + signature.
    anchor_ref = wire.get("anchor_ref")
    if anchor_ref is not None:
        if not isinstance(anchor_ref, str):
            raise ParseError(
                "BadAnchorRefShape",
                f"anchor_ref must be a string, got {type(anchor_ref).__name__}",
            )
        _validate_anchor_ref_shape(anchor_ref)
    signature = wire.get("signature")
    if signature is not None:
        if not isinstance(signature, str):
            raise ParseError(
                "BadSignatureShape",
                f"signature must be a string, got {type(signature).__name__}",
            )
        _validate_signature_shape(signature)

    # Payload.
    payload_obj = wire.get("payload")
    if payload_obj is None:
        raise ParseError("BadJson", "frame missing required field 'payload'")
    if not isinstance(payload_obj, dict):
        raise ParseError("BadJson", "frame 'payload' must be a JSON object")
    for required in ("kind", "data", "schema"):
        if required not in payload_obj:
            raise ParseError(
                "MissingField",
                f"payload missing required field {required!r}",
                field=required,
            )
    kind_val = payload_obj["kind"]
    data_val = payload_obj["data"]
    schema_payload_val = payload_obj["schema"]
    if not isinstance(data_val, dict):
        raise ParseError(
            "PayloadDataNotObject",
            "payload `data` must be a JSON object",
        )
    if kind_val not in _KIND_TO_SCHEMA:
        raise ParseError(
            "UnknownPayloadKind",
            f"payload kind {kind_val!r} is not a recognised variant",
            payload_kind=kind_val,
        )
    expected_schema = _KIND_TO_SCHEMA[kind_val]
    if schema_payload_val != expected_schema:
        raise ParseError(
            "UnknownSchema",
            f"frame field 'payload.schema' carries unknown schema value "
            f"{schema_payload_val!r} for kind {kind_val!r} (want "
            f"{expected_schema!r})",
            field="payload.schema",
            value=schema_payload_val,
        )

    header = FrameHeader(
        frame_id=header_obj["frame_id"],
        schema=schema_val,
        source_runtime=header_obj["source_runtime"],
        target_runtime=header_obj["target_runtime"],
        ts_utc=header_obj["ts_utc"],
        version=version_val,
    )
    payload = FederationPayload(kind=kind_val, data=dict(data_val))
    return FederationFrame(
        header=header,
        payload=payload,
        anchor_ref=anchor_ref,
        signature=signature,
    )


def serialize_frame(frame: FederationFrame) -> bytes:
    """Serialise a :class:`FederationFrame` to JCS-canonical JSON bytes.

    Inverse of :func:`parse_frame`. The output is RFC-8785 canonical;
    ``serialize_frame(parse_frame(b)) == b`` is the round-trip
    invariant the smoke-test suite pins for every fixture.

    The byte output is byte-identical to the Rust crate's
    ``serialize_frame``; the fixture file at
    ``tests/federation/fixtures/federation_frame_cross_lang_pins.json``
    is the cross-lang contract anchor.
    """
    # Re-validate the header so we can never emit a frame that would
    # fail :func:`parse_frame`.
    if frame.header.schema != FRAME_ENVELOPE_SCHEMA:
        raise ParseError(
            "UnknownSchema",
            f"frame.header.schema must be {FRAME_ENVELOPE_SCHEMA!r}",
            field="header.schema",
            value=frame.header.schema,
        )
    if frame.header.version != FRAME_ENVELOPE_VERSION:
        raise ParseError(
            "UnsupportedVersion",
            f"frame.header.version must be {FRAME_ENVELOPE_VERSION}",
            version=frame.header.version,
        )
    _validate_timestamp_shape(frame.header.ts_utc)
    _validate_frame_id_shape(frame.header.frame_id)
    _validate_runtime_id("source_runtime", frame.header.source_runtime)
    _validate_runtime_id("target_runtime", frame.header.target_runtime)
    if frame.anchor_ref is not None:
        _validate_anchor_ref_shape(frame.anchor_ref)
    if frame.signature is not None:
        _validate_signature_shape(frame.signature)

    wire: Dict[str, Any] = {
        "header": {
            "frame_id": frame.header.frame_id,
            "schema": frame.header.schema,
            "source_runtime": frame.header.source_runtime,
            "target_runtime": frame.header.target_runtime,
            "ts_utc": frame.header.ts_utc,
            "version": frame.header.version,
        },
        "payload": {
            "data": dict(frame.payload.data),
            "kind": frame.payload.kind,
            "schema": frame.payload.schema,
        },
    }
    if frame.anchor_ref is not None:
        wire["anchor_ref"] = frame.anchor_ref
    if frame.signature is not None:
        wire["signature"] = frame.signature

    try:
        canonical = _jcs_canonicalize(wire)
    except (TypeError, ValueError) as exc:
        raise ParseError(
            "JcsFailure", f"JCS canonicalisation failed: {exc}"
        ) from exc

    if len(canonical) > MAX_FRAME_JCS_BYTES:
        raise ParseError(
            "FrameTooLarge",
            f"JCS-canonical frame size {len(canonical)} bytes exceeds "
            f"ceiling {MAX_FRAME_JCS_BYTES} bytes",
            bytes=len(canonical),
            max=MAX_FRAME_JCS_BYTES,
        )
    return canonical


def compute_frame_id(seed: bytes) -> str:
    """Derive a deterministic frame identifier from a caller-supplied seed.

    The seed is hashed with SHA-256; the hex tail is prefixed with
    :data:`FRAME_ID_PREFIX`. Mirrors the Rust crate's
    ``compute_frame_id`` byte-for-byte.
    """
    if not isinstance(seed, (bytes, bytearray)):
        raise TypeError(f"seed must be bytes, got {type(seed).__name__}")
    digest = hashlib.sha256(bytes(seed)).hexdigest()
    return f"{FRAME_ID_PREFIX}{digest}"


def signing_payload_bytes(frame: FederationFrame) -> bytes:
    """JCS bytes of the ``{header, payload}`` subtree (signing input).

    The slice is the JCS-canonical bytes of the ``{header, payload}``
    subtree (``anchor_ref`` and ``signature`` are NOT included in the
    signing input — they are out-of-signature side channels). Returns
    the byte-identical equivalent of the Rust crate's
    ``signing_payload_bytes``.
    """
    signing_wire: Dict[str, Any] = {
        "header": {
            "frame_id": frame.header.frame_id,
            "schema": frame.header.schema,
            "source_runtime": frame.header.source_runtime,
            "target_runtime": frame.header.target_runtime,
            "ts_utc": frame.header.ts_utc,
            "version": frame.header.version,
        },
        "payload": {
            "data": dict(frame.payload.data),
            "kind": frame.payload.kind,
            "schema": frame.payload.schema,
        },
    }
    try:
        return _jcs_canonicalize(signing_wire)
    except (TypeError, ValueError) as exc:
        raise ParseError(
            "JcsFailure", f"JCS canonicalisation failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------
# Validators — exact-parity with Rust ``validate_*`` helpers.
# ---------------------------------------------------------------------


def _validate_timestamp_shape(s: str) -> None:
    """RFC-3339 second-precision UTC: ``YYYY-MM-DDTHH:MM:SSZ`` (20 chars)."""
    if not isinstance(s, str):
        raise ParseError(
            "BadTimestampShape",
            f"ts_utc must be a string, got {type(s).__name__}",
        )
    if len(s) != 20:
        raise ParseError(
            "BadTimestampShape",
            f"frame header ts_utc {s!r} is not RFC-3339 second-precision UTC "
            f"(YYYY-MM-DDTHH:MM:SSZ)",
        )
    if s[10] != "T" or s[19] != "Z":
        raise ParseError(
            "BadTimestampShape",
            f"frame header ts_utc {s!r} is not RFC-3339 second-precision UTC",
        )

    def _digit(i: int) -> bool:
        return s[i].isascii() and s[i].isdigit()

    # YYYY
    if not all(_digit(i) for i in (0, 1, 2, 3)):
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad year")
    # -MM-
    if s[4] != "-" or not _digit(5) or not _digit(6) or s[7] != "-":
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad month")
    # DD
    if not _digit(8) or not _digit(9):
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad day")
    # HH:MM:SS
    if not _digit(11) or not _digit(12) or s[13] != ":":
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad hour")
    if not _digit(14) or not _digit(15) or s[16] != ":":
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad minute")
    if not _digit(17) or not _digit(18):
        raise ParseError("BadTimestampShape", f"ts_utc {s!r} bad second")


def _validate_frame_id_shape(s: str) -> None:
    """``frame-sha256:`` + 64 lower-case hex chars."""
    if not isinstance(s, str):
        raise ParseError(
            "BadFrameIdShape",
            f"frame_id must be a string, got {type(s).__name__}",
        )
    if not s.startswith(FRAME_ID_PREFIX):
        raise ParseError(
            "BadFrameIdShape",
            f"frame header frame_id {s!r} is not in frame-sha256:<64-hex> shape",
        )
    tail = s[len(FRAME_ID_PREFIX):]
    if len(tail) != SHA256_HEX_LEN:
        raise ParseError(
            "BadFrameIdShape",
            f"frame header frame_id {s!r} hex-tail length {len(tail)} != 64",
        )
    if not all(c in "0123456789abcdef" for c in tail):
        raise ParseError(
            "BadFrameIdShape",
            f"frame header frame_id {s!r} hex-tail not lower-case hex",
        )


def _validate_anchor_ref_shape(s: str) -> None:
    """``wat:`` + 64 lower-case hex chars."""
    if not s.startswith(ANCHOR_REF_PREFIX):
        raise ParseError(
            "BadAnchorRefShape",
            f"frame anchor_ref {s!r} is not in wat:<64-hex> shape",
        )
    tail = s[len(ANCHOR_REF_PREFIX):]
    if len(tail) != SHA256_HEX_LEN:
        raise ParseError(
            "BadAnchorRefShape",
            f"anchor_ref {s!r} hex-tail length {len(tail)} != 64",
        )
    if not all(c in "0123456789abcdef" for c in tail):
        raise ParseError(
            "BadAnchorRefShape",
            f"anchor_ref {s!r} hex-tail not lower-case hex",
        )


def _validate_signature_shape(s: str) -> None:
    """Non-empty lower-case hex string, even length."""
    if not s:
        raise ParseError(
            "BadSignatureShape", "signature must be a non-empty string"
        )
    if not all(c in "0123456789abcdef" for c in s):
        raise ParseError(
            "BadSignatureShape",
            f"signature {s!r} is not lower-case hex",
        )
    if len(s) % 2 != 0:
        raise ParseError(
            "BadSignatureShape",
            f"signature {s!r} has odd length {len(s)}",
        )


def _validate_runtime_id(field: str, s: str) -> None:
    """Runtime IDs are non-empty printable ASCII (no whitespace, no control)."""
    if not isinstance(s, str):
        raise ParseError(
            "BadRuntimeId",
            f"{field} must be a string, got {type(s).__name__}",
            field=field,
        )
    if not s:
        raise ParseError(
            "BadRuntimeId",
            f"frame header {field} is empty",
            field=field,
            value=s,
        )
    for ch in s:
        code = ord(ch)
        if code < 0x21 or code > 0x7E:
            raise ParseError(
                "BadRuntimeId",
                f"frame header {field} {s!r} contains non-printable-ASCII "
                f"character {ch!r}",
                field=field,
                value=s,
            )


__all__ = [
    "FRAME_ENVELOPE_SCHEMA",
    "FRAME_ENVELOPE_VERSION",
    "PAYLOAD_SCHEMA_TASK_ASSIGNED",
    "PAYLOAD_SCHEMA_TASK_OUTPUT",
    "PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION",
    "PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC",
    "FRAME_ID_PREFIX",
    "ANCHOR_REF_PREFIX",
    "MAX_FRAME_JCS_BYTES",
    "SHA256_HEX_LEN",
    "FrameHeader",
    "FederationPayload",
    "FederationFrame",
    "ParseError",
    "parse_frame",
    "serialize_frame",
    "compute_frame_id",
    "signing_payload_bytes",
]
