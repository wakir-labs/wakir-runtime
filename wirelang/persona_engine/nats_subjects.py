# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# This file is part of the Wakir Persona-Engine real-implementation
# module. Licensed under the Business Source License 1.1; see
# ../LICENSE-BSL.md for the canonical wirelang-package header. Change
# Date: four (4) years after first publication; Change License:
# Apache 2.0.
"""Typed NATS-Subject-Builders for the Persona-Engine (Python parity).

This module is the **Python-Side-Sync** counterpart of the Rust crate
``wirelang-rust/crates/persona-engine-nats-subjects`` (Phase-3a Modul
10, Tag-12 Mini-Welle, merged via PR #146 as "Rust-canonical,
Python-Sync-Folge dokumentiert"). Tag-14 Mini-Welle (this file)
closes the parity loop: the 8 pin-pack fixtures listed in the Rust
``pins`` sub-module are reproduced here byte-identically by the typed
builder functions, and a SHA-256 over the ``\\n``-joined list is
asserted equal across both languages.

Subject-family (identical to the Rust crate)
--------------------------------------------

    persona.lifecycle.{id}.{event}
    persona.federation.{cluster}.{id}.frame
    persona.audit.{kind}.{id}
    persona.anchor.{batch}.submitted
    persona.recovery.{step}.{id}

Wildcard tokens
---------------

    ``*``  one token at this position
    ``>``  tail-wildcard (terminal, matches one or more tokens)

Cross-Lang invariants
---------------------

The following invariants are asserted by
``tests/persona_engine/test_nats_subjects.py``:

1. Each of the 8 ``FIXTURE_*`` constants in this module equals the
   string that the Rust crate exports under the same name. The Rust
   strings are reproduced here as documentation; the test suite
   re-derives each one from the typed builder and compares against
   both the local constant and (where the Rust binary is available
   in-tree) the Rust source.
2. The SHA-256 over ``"\\n".join(ALL_FIXTURES).encode("utf-8")``
   equals the digest computed by the Rust test
   ``test_pin_pack_cross_lang_sha256`` (added in this commit to the
   Rust side as the Python-parity-verifier).

Error model
-----------

:class:`SubjectError` mirrors the Rust ``SubjectError`` enum 1:1
(InvalidChar / TokenTooLong / ReservedWord / EmptyToken /
LeadingDigit). The ``kind`` attribute carries the discriminant tag
as a string identical to the Rust ``#[serde(tag = "error")]``
encoding, so any JSON-serialised error from either side round-trips.
"""

from __future__ import annotations

from typing import Final, Optional, Tuple

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Maximum length of a single NATS token under the Persona-Engine
#: policy (mirrors ``persona_engine_nats_subjects::MAX_TOKEN_LEN``).
MAX_TOKEN_LEN: Final[int] = 64

#: Reserved NATS tokens that may never appear as dynamic input values.
RESERVED_WORDS: Final[Tuple[str, ...]] = (">", "*", "")


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------


class SubjectError(Exception):
    """Validation failure for a NATS subject token.

    Mirrors the Rust ``SubjectError`` enum. The :attr:`kind` field
    carries the discriminant tag string identical to the Rust
    ``#[serde(tag = "error")]`` encoding:

    - ``"InvalidChar"``
    - ``"TokenTooLong"``
    - ``"ReservedWord"``
    - ``"EmptyToken"``
    - ``"LeadingDigit"``

    The remaining attributes (``position``, ``character``, ``field``,
    ``actual``, ``max``, ``value``) match the per-variant Rust struct
    fields. Attributes not relevant for the active variant default to
    ``None``.
    """

    #: Discriminant tag string (parity with Rust ``#[serde(tag =
    #: "error")]``).
    kind: str
    #: Logical field name where the token was being placed (e.g.
    #: ``"id"``, ``"event"``, ``"cluster"``, ``"kind"``, ``"batch"``,
    #: ``"step"``).
    field: str
    position: Optional[int]
    character: Optional[str]
    actual: Optional[int]
    max: Optional[int]
    value: Optional[str]

    def __init__(
        self,
        kind: str,
        field: str,
        *,
        position: Optional[int] = None,
        character: Optional[str] = None,
        actual: Optional[int] = None,
        max: Optional[int] = None,  # noqa: A002 - parity with Rust field name
        value: Optional[str] = None,
    ) -> None:
        self.kind = kind
        self.field = field
        self.position = position
        self.character = character
        self.actual = actual
        self.max = max
        self.value = value
        super().__init__(self._render())

    def _render(self) -> str:
        # Display strings here are intentionally **not** byte-identical
        # to Rust's ``fmt::Display`` output (Python's str/repr quoting
        # differs from Rust's ``{:?}``). The structured ``kind`` /
        # ``field`` / ``value`` attributes are the cross-language
        # contract; the prose is local diagnostic.
        if self.kind == "InvalidChar":
            return (
                f"invalid character {self.character!r} at position "
                f"{self.position} in token field {self.field!r}"
            )
        if self.kind == "TokenTooLong":
            return (
                f"token field {self.field!r} is {self.actual} bytes "
                f"(max {self.max})"
            )
        if self.kind == "ReservedWord":
            return (
                f"token field {self.field!r} uses reserved word "
                f"{self.value!r}"
            )
        if self.kind == "EmptyToken":
            return f"token field {self.field!r} is empty"
        if self.kind == "LeadingDigit":
            return (
                f"token field {self.field!r} starts with a digit "
                f"(got {self.value!r})"
            )
        # Defensive: unknown discriminant -> generic string so caller
        # diagnostics never lose information.
        return f"subject error {self.kind!r} on field {self.field!r}"

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        bits = [f"kind={self.kind!r}", f"field={self.field!r}"]
        for attr in ("position", "character", "actual", "max", "value"):
            v = getattr(self, attr)
            if v is not None:
                bits.append(f"{attr}={v!r}")
        return f"SubjectError({', '.join(bits)})"


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


def validate_token(token: str, field: str) -> None:
    """Validate a single token against the Persona-Engine rules.

    Rules (applied in this order, mirroring
    ``persona_engine_nats_subjects::validate_token``):

    1. Token must not be empty (else :class:`SubjectError` with kind
       ``"EmptyToken"``).
    2. Token must not equal any :data:`RESERVED_WORDS` entry (else
       kind ``"ReservedWord"``).
    3. Token byte-length must be ``<= MAX_TOKEN_LEN`` (else kind
       ``"TokenTooLong"``).
    4. First character must be an ASCII letter ``[A-Za-z]``. If the
       first character is an ASCII digit, a more specific
       ``"LeadingDigit"`` variant is raised; for other non-letter
       first chars, the path falls through to step 5.
    5. All characters must be in ``[A-Za-z0-9_-]`` (else kind
       ``"InvalidChar"``).

    :raises SubjectError: on any rule violation.
    """

    if token == "":
        raise SubjectError("EmptyToken", field)
    if token in RESERVED_WORDS:
        raise SubjectError("ReservedWord", field, value=token)
    # NATS subjects are ASCII; the byte length equals the character
    # count for any valid input. Reject by byte length to match the
    # Rust crate's ``token.len()`` (which is byte-length on ``&str``).
    token_bytes = token.encode("utf-8")
    if len(token_bytes) > MAX_TOKEN_LEN:
        raise SubjectError(
            "TokenTooLong",
            field,
            actual=len(token_bytes),
            max=MAX_TOKEN_LEN,
        )
    for position, ch in enumerate(token):
        if position == 0:
            allowed = ch.isascii() and ch.isalpha()
        else:
            allowed = ch.isascii() and (ch.isalnum() or ch in ("-", "_"))
        if not allowed:
            if position == 0 and ch.isascii() and ch.isdigit():
                raise SubjectError("LeadingDigit", field, value=token)
            raise SubjectError(
                "InvalidChar",
                field,
                position=position,
                character=ch,
            )


def is_valid_token(token: str) -> bool:
    """Return ``True`` if ``token`` passes :func:`validate_token`."""

    try:
        validate_token(token, "token")
    except SubjectError:
        return False
    return True


# ---------------------------------------------------------------------------
# Typed Subject-Builders (concrete subjects)
# ---------------------------------------------------------------------------


def persona_lifecycle_subject(id: str, event: str) -> str:
    """Build ``persona.lifecycle.{id}.{event}``.

    Lifecycle events of a single persona instance (``spawned``,
    ``ready``, ``paused``, ``despawned``, ``crashed``, ...).
    """

    validate_token(id, "id")
    validate_token(event, "event")
    return f"persona.lifecycle.{id}.{event}"


def persona_federation_subject(cluster: str, id: str) -> str:
    """Build ``persona.federation.{cluster}.{id}.frame``.

    Federation frames between persona-engine clusters. The terminal
    constant token ``frame`` is fixed so subscribers can sweep all
    federation traffic via ``persona.federation.*.*.frame``.
    """

    validate_token(cluster, "cluster")
    validate_token(id, "id")
    return f"persona.federation.{cluster}.{id}.frame"


def persona_audit_subject(kind: str, id: str) -> str:
    """Build ``persona.audit.{kind}.{id}``.

    Audit-trail events. ``kind`` categorises the audit type
    (``lifecycle-change``, ``identity-rotate``, ``policy-violation``);
    ``id`` is the run identifier (audit-run UUID or short tag).
    """

    validate_token(kind, "kind")
    validate_token(id, "id")
    return f"persona.audit.{kind}.{id}"


def persona_anchor_subject(batch: str) -> str:
    """Build ``persona.anchor.{batch}.submitted``.

    OTS / V-907 anchor submission events. ``batch`` is the
    anchor-batch identifier (date-tag or hash-prefix). The terminal
    token ``submitted`` marks the submit lifecycle stand.
    """

    validate_token(batch, "batch")
    return f"persona.anchor.{batch}.submitted"


def persona_recovery_subject(step: str, id: str) -> str:
    """Build ``persona.recovery.{step}.{id}``.

    Recovery-protocol events (spawn-replay, state-rebuild,
    identity-refetch). ``step`` names the recovery phase (``replay``,
    ``rebuild``, ``verify``); ``id`` identifies the recovery-run
    instance.
    """

    validate_token(step, "step")
    validate_token(id, "id")
    return f"persona.recovery.{step}.{id}"


# ---------------------------------------------------------------------------
# Wildcard-Subscribe-Pattern-Builders
# ---------------------------------------------------------------------------


def lifecycle_wildcard_all_events(id: str) -> str:
    """``persona.lifecycle.{id}.*`` — all events for a single persona."""

    validate_token(id, "id")
    return f"persona.lifecycle.{id}.*"


def lifecycle_wildcard_all() -> str:
    """``persona.lifecycle.>`` — all lifecycle events across personas."""

    return "persona.lifecycle.>"


def federation_wildcard_by_cluster(cluster: str) -> str:
    """``persona.federation.{cluster}.>`` — all frames of one cluster."""

    validate_token(cluster, "cluster")
    return f"persona.federation.{cluster}.>"


def federation_wildcard_all() -> str:
    """``persona.federation.>`` — all federation frames."""

    return "persona.federation.>"


def audit_wildcard_by_kind(kind: str) -> str:
    """``persona.audit.{kind}.*`` — all audit events of one kind."""

    validate_token(kind, "kind")
    return f"persona.audit.{kind}.*"


def audit_wildcard_all() -> str:
    """``persona.audit.>`` — all audit events."""

    return "persona.audit.>"


def anchor_wildcard_all() -> str:
    """``persona.anchor.>`` — all anchor events across batches."""

    return "persona.anchor.>"


def recovery_wildcard_by_step(step: str) -> str:
    """``persona.recovery.{step}.*`` — all recovery events of one step."""

    validate_token(step, "step")
    return f"persona.recovery.{step}.*"


def recovery_wildcard_all() -> str:
    """``persona.recovery.>`` — all recovery events."""

    return "persona.recovery.>"


def persona_root_wildcard() -> str:
    """``persona.>`` — root wildcard for all Persona-Engine subjects."""

    return "persona.>"


# ---------------------------------------------------------------------------
# Cross-Lang Pin-Pack (Python parity for the Rust pin-pack)
# ---------------------------------------------------------------------------

#: Lifecycle pin — spawn event of a test persona.
FIXTURE_LIFECYCLE_SPAWNED: Final[str] = (
    "persona.lifecycle.reza-2026-05-17.spawned"
)
#: Lifecycle pin — despawn event of the same test persona.
FIXTURE_LIFECYCLE_DESPAWNED: Final[str] = (
    "persona.lifecycle.reza-2026-05-17.despawned"
)
#: Federation pin — frame in the default cluster.
FIXTURE_FEDERATION_FRAME: Final[str] = (
    "persona.federation.cluster-eu-1.reza-2026-05-17.frame"
)
#: Audit pin — identity-rotation audit run.
FIXTURE_AUDIT_IDENTITY_ROTATE: Final[str] = (
    "persona.audit.identity-rotate.run-0001"
)
#: Audit pin — policy-violation audit run.
FIXTURE_AUDIT_POLICY_VIOLATION: Final[str] = (
    "persona.audit.policy-violation.run-0002"
)
#: Anchor pin — submit event of a test batch.
FIXTURE_ANCHOR_SUBMITTED: Final[str] = (
    "persona.anchor.batch-2026-05-17.submitted"
)
#: Recovery pin — replay step of a test recovery run.
FIXTURE_RECOVERY_REPLAY: Final[str] = "persona.recovery.replay.run-0003"
#: Recovery pin — verify step of the same recovery run.
FIXTURE_RECOVERY_VERIFY: Final[str] = "persona.recovery.verify.run-0003"

#: Full pin list in the stable order defined by the Rust crate.
#:
#: The order is part of the cross-language contract: the SHA-256 over
#: ``"\\n".join(ALL_FIXTURES).encode("utf-8")`` must be byte-identical
#: to the digest produced by the Rust test
#: ``test_pin_pack_cross_lang_sha256``. Reordering this tuple is a
#: breaking change for the cross-lang parity test.
ALL_FIXTURES: Final[Tuple[str, ...]] = (
    FIXTURE_LIFECYCLE_SPAWNED,
    FIXTURE_LIFECYCLE_DESPAWNED,
    FIXTURE_FEDERATION_FRAME,
    FIXTURE_AUDIT_IDENTITY_ROTATE,
    FIXTURE_AUDIT_POLICY_VIOLATION,
    FIXTURE_ANCHOR_SUBMITTED,
    FIXTURE_RECOVERY_REPLAY,
    FIXTURE_RECOVERY_VERIFY,
)


def pin_pack_sha256_hex() -> str:
    """Return the SHA-256 (lowercase hex) over the joined pin pack.

    The hash input is ``"\\n".join(ALL_FIXTURES).encode("utf-8")``.
    This value must equal the digest produced by the Rust-side
    parity test; the cross-lang assertion lives in both test suites.
    """

    import hashlib

    payload = "\n".join(ALL_FIXTURES).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MAX_TOKEN_LEN",
    "RESERVED_WORDS",
    "SubjectError",
    "validate_token",
    "is_valid_token",
    "persona_lifecycle_subject",
    "persona_federation_subject",
    "persona_audit_subject",
    "persona_anchor_subject",
    "persona_recovery_subject",
    "lifecycle_wildcard_all_events",
    "lifecycle_wildcard_all",
    "federation_wildcard_by_cluster",
    "federation_wildcard_all",
    "audit_wildcard_by_kind",
    "audit_wildcard_all",
    "anchor_wildcard_all",
    "recovery_wildcard_by_step",
    "recovery_wildcard_all",
    "persona_root_wildcard",
    "FIXTURE_LIFECYCLE_SPAWNED",
    "FIXTURE_LIFECYCLE_DESPAWNED",
    "FIXTURE_FEDERATION_FRAME",
    "FIXTURE_AUDIT_IDENTITY_ROTATE",
    "FIXTURE_AUDIT_POLICY_VIOLATION",
    "FIXTURE_ANCHOR_SUBMITTED",
    "FIXTURE_RECOVERY_REPLAY",
    "FIXTURE_RECOVERY_VERIFY",
    "ALL_FIXTURES",
    "pin_pack_sha256_hex",
]
