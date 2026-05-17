# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-Forward-Pipe canonical-frame helpers (Tag-25 Mini-Welle).

This module is the **Python authority** for the cross-language
canonical-frame surface of the Bridge-Forward-Pipe publisher. A
Rust sibling crate
(``wirelang-rust/crates/persona-engine-bridge-forward``) emits
byte-identical canonical frames; the two sides are pinned by the
cross-lang fixture file
``tests/fixtures/bridge-forward-cross-lang/fixtures.json``.

Why a sibling module?
---------------------

The pre-existing :mod:`wirelang.cli.bridge_forward` module
(Sprint-10 Tag-6, PR landed 2026-05-15) is the Mira-side publisher
CLI. It already exposes the canonical helpers (:class:`AuftragEnvelope`,
:func:`build_subject`, :func:`envelope_to_jcs_bytes`,
:func:`validate_envelope`) under Apache-2.0; this sibling module
**re-exports** those helpers AND adds the cross-lang contract
surface that the Tag-25 Mini-Welle introduces:

- :func:`build_forward_frame` — pure-function frame constructor
  from a :class:`ForwardFrameInput` dataclass; mirrors the Rust
  ``build_forward_frame(input: ForwardFrameInput) -> ForwardFrame``.
- :func:`serialize_forward_frame` — RFC 8785 / JCS-light canonical
  bytes of the forward-frame wire-shape.
- :func:`forward_frame_sha256_hex` — bare-hex SHA-256 of the
  canonical bytes.
- :func:`forward_frame_hash_prefixed` — ``"sha256:<hex>"`` prefixed
  form (Rust ``hash_anchor`` parity).
- :func:`serialize_and_hash` — tuple of (canonical_bytes,
  prefixed_hash) for one-shot consumers.

The pre-existing :mod:`wirelang.cli.bridge_forward` module is
**unchanged** by this Tag-25 sibling; the CLI continues to honour
its Sprint-10 Tag-6 contract and emits the same envelope bytes.
The canonical helpers in this module are a **superset**: the
forward-frame wire-shape adds a ``forward_frame`` outer wrapper
around the existing envelope so the Rust pendant can emit and
verify the same byte-string without inheriting the CLI's
``argparse`` / ``sys.exit`` baggage.

Schema
------

The canonical forward-frame carries exactly three top-level fields
(alphabetical):

- ``envelope`` — The ``AuftragEnvelope.to_dict()`` projection of
  the inner Sprint-10 Tag-6 envelope (nine-field shape: ``schema``,
  ``event_kind``, ``org_id``, ``persona_id``, ``auftrag_id``,
  ``ts_utc``, ``source``, ``prompt_sha256``, ``prompt_payload``,
  ``metadata``). Sort-key invariance is delegated to the inner
  ``envelope_to_jcs_bytes``.
- ``schema`` — Schema identifier; constant
  ``"wakir.bridge.forward-frame/1"``.
- ``subject`` — The canonical NATS subject string built by
  :func:`build_subject` (subject-mapping-v1 regex compliant).

Serialisation
-------------

Canonical bytes are produced by ``json.dumps`` with
``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=False``,
UTF-8-encoded. This is the same JCS-light convention used by the
inner :func:`envelope_to_jcs_bytes` and matches the Rust pendant's
``serde_jcs::to_vec`` output for the subset of JSON the Wakir
forward-frame uses (string-only object keys, UTF-8 string scalars,
nested object for ``metadata``, no number / boolean leaves at the
top level).

The outer forward-frame hash is
``"sha256:" + hex(SHA-256(canonical_bytes))``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/bridge-forward-cross-lang/fixtures.json`` is the
byte-level cross-lang pin. Both
``tests/cli/test_bridge_forward_cross_lang_parity.py`` (Python) and
``wirelang-rust/crates/persona-engine-bridge-forward/tests/
bridge_forward_cross_lang_fixture_test.rs`` (Rust) consume the
same vectors. Any drift on either side fails both suites.

Five fixture vectors map the surface:

- f01-empty-payload — minimal envelope, empty ``prompt_payload`` /
  empty ``metadata``.
- f02-single-record — Sprint-10 Tag-6 golden envelope (single
  ``prompt_payload`` line, two-key metadata).
- f03-multi-record-batch — five metadata keys, multi-line prompt.
- f04-error-frame — wire-shape for the size-limit / validation
  rejection path: prompt at exact ``MAX_PROMPT_PAYLOAD_BYTES``
  boundary (still valid, byte-pinned).
- f05-large-payload — 4 KiB + 1 byte prompt_payload (above the
  4 KiB threshold mentioned in the Sprint-Auftrag).

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python                                       <-> Rust
    -------------------------------------------------------------------------
    AuftragEnvelope (dataclass)                  <-> AuftragEnvelope (struct)
    ForwardFrameInput (dataclass)                <-> ForwardFrameInput (struct)
    ForwardFrame (dataclass)                     <-> ForwardFrame (struct)
    build_forward_frame(input) -> ForwardFrame   <-> build_forward_frame
    serialize_forward_frame(frame) -> bytes      <-> serialize_forward_frame
    forward_frame_sha256_hex(frame) -> str       <-> forward_frame_sha256_hex
    forward_frame_hash_prefixed(frame) -> str    <-> forward_frame_hash_prefixed
    serialize_and_hash(frame) -> (bytes, str)    <-> serialize_and_hash
    BRIDGE_FORWARD_FRAME_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                             <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item 10 (this Mini-Welle).
- Reza PR #170 (Tag-18) — anchor-emitter Python sibling +
  cross-lang fixture pattern reference (sibling-module + 5-fixture
  file).
- Reza PR #177 (Tag-21) — lifecycle-FSM canonical-trace cross-lang
  fixture pattern reference.
- Reza PR #183 (Tag-23) — state-backing cross-lang parity
  reference (InMemory* + 5-fixture file pattern).
- Reza PR #188 (Tag-24) — federation-resolver cross-lang parity
  reference (most recent sibling).
- Sprint-10 Tag-6 — original Sprint-10 Bridge-Forward-Pipe CLI
  (PR landed 2026-05-15; spec at ``wirelang/specs/bridge-forward-
  pipe-v1.md``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

# Re-export the canonical helpers + size constants from the pre-existing
# Sprint-10 Tag-6 CLI module. The CLI module is Apache-2.0; we do NOT
# duplicate the envelope construction logic here.
from wirelang.cli.bridge_forward import (
    AGENT_TASK_ASSIGNED_SCHEMA,
    AuftragEnvelope,
    EnvelopeFormatError,
    MAX_AUFTRAG_ID_OCTETS,
    MAX_METADATA_BYTES,
    MAX_PROMPT_PAYLOAD_BYTES,
    SizeLimitError,
    build_subject,
    envelope_to_jcs_bytes,
    validate_envelope,
)

# ---------------------------------------------------------------------
# Constants — single source of truth for both Python and Rust pendant
# ---------------------------------------------------------------------

#: Schema-id literal for the forward-frame canonical wire-shape.
#: Mirrors the Rust ``BRIDGE_FORWARD_FRAME_SCHEMA`` constant.
BRIDGE_FORWARD_FRAME_SCHEMA = "wakir.bridge.forward-frame/1"

#: Prefix prepended to every ``"sha256:<64hex>"`` string emitted by
#: this module. Matches the Rust ``HASH_PREFIX`` and the conventions
#: used by ``persona-engine-anchor-emitter`` / ``persona-engine-
#: bridge-diff`` / ``persona-engine-federation-resolver``.
HASH_PREFIX = "sha256:"

#: Hex-string length of a SHA-256 digest (lower-case, no prefix).
SHA256_HEX_LEN = 64


# ---------------------------------------------------------------------
# Input + frame dataclasses
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ForwardFrameInput:
    """Logical input to :func:`build_forward_frame`.

    Mirrors the Rust ``ForwardFrameInput`` struct. The four required
    string fields plus the timestamp form the inner
    :class:`AuftragEnvelope`; the ``env`` and ``persona_slug`` fields
    are pulled in for subject construction. ``metadata`` is optional
    (defaults to empty); ``source`` and ``org_id`` default to the
    Sprint-10 Tag-6 CLI defaults (``"mira-sandbox"`` / ``"acme"``).
    """

    env: str
    persona_slug: str
    auftrag_id: str
    ts_utc: str
    prompt_payload: str
    org_id: str = "acme"
    source: str = "mira-sandbox"
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ForwardFrame:
    """Canonical forward-frame wire-shape.

    The three-field outer wrapper around an :class:`AuftragEnvelope`
    plus the canonical subject string. Use :func:`serialize_forward_frame`
    to obtain the JCS-canonical bytes; use :func:`forward_frame_sha256_hex`
    / :func:`forward_frame_hash_prefixed` to obtain the SHA-256 hash.

    Mirrors the Rust ``ForwardFrame`` struct.
    """

    subject: str
    envelope: AuftragEnvelope

    def to_wire_dict(self) -> dict:
        """Return the alphabetised wire-shape dict.

        Key order in the returned mapping is irrelevant because
        :func:`serialize_forward_frame` sorts keys via
        ``json.dumps(sort_keys=True, ...)``. The dict is returned in a
        documented insertion order purely for inspection.
        """
        return {
            "envelope": self.envelope.to_dict(),
            "schema": BRIDGE_FORWARD_FRAME_SCHEMA,
            "subject": self.subject,
        }


# ---------------------------------------------------------------------
# Pure-function frame builder / serialiser / hasher
# ---------------------------------------------------------------------


def build_forward_frame(input_: ForwardFrameInput) -> ForwardFrame:
    """Construct a :class:`ForwardFrame` from a :class:`ForwardFrameInput`.

    Pure function: no IO, no clock, no network. Re-uses the Sprint-10
    Tag-6 :func:`build_subject` for subject construction (which also
    enforces the subject-mapping-v1 regex) and
    :class:`AuftragEnvelope` for the inner envelope. The forward-frame
    inherits the inner envelope's size invariants (callers MUST
    :func:`validate_envelope` the inner envelope to enforce the
    Sprint-10 Tag-6 §3.3 size envelope).

    :param input_: Logical input dataclass.
    :returns: Canonical :class:`ForwardFrame`.
    :raises EnvelopeFormatError: If ``env`` is not one of
        ``("dev", "staging", "prod")`` or ``persona_slug`` does not
        match ``[a-z][a-z0-9_-]*``.
    """
    subject = build_subject(input_.env, input_.persona_slug)
    envelope = AuftragEnvelope(
        org_id=input_.org_id,
        persona_id=input_.persona_slug,
        auftrag_id=input_.auftrag_id,
        ts_utc=input_.ts_utc,
        source=input_.source,
        prompt_payload=input_.prompt_payload,
        metadata=dict(input_.metadata),
    )
    return ForwardFrame(subject=subject, envelope=envelope)


def serialize_forward_frame(frame: ForwardFrame) -> bytes:
    """Render ``frame`` as JCS-canonical UTF-8 bytes.

    Delegates to ``json.dumps(sort_keys=True, separators=(",",
    ":"), ensure_ascii=False)`` — the same JCS-light convention used
    by :func:`envelope_to_jcs_bytes` (RFC 8785 strict-canonical is
    NOT required; determinism-across-repeats is the floor and the
    Rust pendant uses ``serde_jcs::to_vec`` whose output coincides
    with this convention for the subset of JSON the forward-frame
    uses).
    """
    return json.dumps(
        frame.to_wire_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def forward_frame_sha256_hex(frame: ForwardFrame) -> str:
    """Return the bare lower-case-hex SHA-256 of the canonical bytes.

    Mirrors the Rust ``forward_frame_sha256_hex`` helper. The
    returned string is exactly :data:`SHA256_HEX_LEN` characters
    (no prefix).
    """
    return hashlib.sha256(serialize_forward_frame(frame)).hexdigest()


def forward_frame_hash_prefixed(frame: ForwardFrame) -> str:
    """Return the ``"sha256:<hex>"`` prefixed SHA-256.

    Mirrors the Rust ``forward_frame_hash_prefixed`` helper. The
    return value is ``HASH_PREFIX + forward_frame_sha256_hex(frame)``.
    """
    return f"{HASH_PREFIX}{forward_frame_sha256_hex(frame)}"


def serialize_and_hash(frame: ForwardFrame) -> Tuple[bytes, str]:
    """Return ``(canonical_bytes, prefixed_hash)`` for one-shot consumers.

    The two values are byte-identical to two independent calls of
    :func:`serialize_forward_frame` / :func:`forward_frame_hash_prefixed`
    on the same frame. The pair is exposed because the Rust pendant
    callsites typically need both — folding them into one entry-point
    avoids a duplicated JCS canonicalisation pass.
    """
    canonical = serialize_forward_frame(frame)
    prefixed = f"{HASH_PREFIX}{hashlib.sha256(canonical).hexdigest()}"
    return canonical, prefixed


# ---------------------------------------------------------------------
# Optional: validate_forward_frame — convenience for callers that want
# the inner envelope validated AND the frame canonicalised in one shot.
# ---------------------------------------------------------------------


def validate_forward_frame(frame: ForwardFrame) -> None:
    """Apply the Sprint-10 Tag-6 §3.3 size envelope to the inner envelope.

    Raises :class:`SizeLimitError` (re-exported from the parent CLI
    module) if any size invariant is breached. The forward-frame
    outer wrapper has no additional size limit of its own; the
    envelope's caps transitively bound the frame size.
    """
    validate_envelope(frame.envelope)


# ---------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------

__all__ = [
    # Constants.
    "AGENT_TASK_ASSIGNED_SCHEMA",
    "BRIDGE_FORWARD_FRAME_SCHEMA",
    "HASH_PREFIX",
    "SHA256_HEX_LEN",
    "MAX_AUFTRAG_ID_OCTETS",
    "MAX_METADATA_BYTES",
    "MAX_PROMPT_PAYLOAD_BYTES",
    # Re-exported envelope helpers (Sprint-10 Tag-6).
    "AuftragEnvelope",
    "EnvelopeFormatError",
    "SizeLimitError",
    "build_subject",
    "envelope_to_jcs_bytes",
    "validate_envelope",
    # Tag-25 cross-lang canonical surface.
    "ForwardFrame",
    "ForwardFrameInput",
    "build_forward_frame",
    "serialize_forward_frame",
    "forward_frame_sha256_hex",
    "forward_frame_hash_prefixed",
    "serialize_and_hash",
    "validate_forward_frame",
]
