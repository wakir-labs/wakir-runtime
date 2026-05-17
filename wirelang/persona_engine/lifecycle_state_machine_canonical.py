# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-engine lifecycle-state-machine canonical-trace helpers.

This module is the **Python sibling** of the canonical-trace surface
that lives on the Rust crate ``persona-engine-fsm`` (PR #137, merged
2026-05-17). Both sides emit a byte-identical JCS-canonical
``LifecycleTrace`` per finished or in-progress state-machine session
so the Phase-3a 3-way-triangle (Doppelbetrieb-Vergleich) can diff
Python-side and Rust-side persona-lifecycle traces byte-for-byte
without round-tripping through any other substrate.

Why a sibling module?
---------------------

``wirelang.persona_engine.lifecycle_state_machine`` (Selin
Sprint-Pengine-8 PR #65) is a mature substrate that already drives
the persona-engine's spawn-run-despawn semantics through
:class:`LifecycleStateMachine`. The Tag-21 canonical-trace contract
is **orthogonal** to that flow: it is a pure-function pair
``build_lifecycle_trace`` / ``serialize_lifecycle_trace`` that takes
either a live ``LifecycleStateMachine`` (or its history snapshot)
and emits a byte-deterministic JCS-canonical wire-shape.

Keeping the helpers in a separate Apache-2.0 module preserves the
Sprint-10 Doppelbetrieb-Konsistenz contract (the existing
state-machine's byte-output does not change) and matches the
sibling-pattern Reza used for ``wirelang.persona_engine.subscribe_ack``
(Tag-19 sibling of ``persona-engine-subscribe-loop``) and
``wirelang.persona_engine.anchor_emitter`` (Tag-18 sibling of
``persona-engine-anchor-emitter``). The pre-existing BUSL-licensed
file ``lifecycle_state_machine.py`` is **NOT** touched by this
module; the Apache-2.0 licence here keeps the cross-lang fixture
vectors re-usable for downstream re-implementers.

Schema
------

The canonical-trace carries exactly six top-level fields
(alphabetically sorted in the canonical form):

- ``final_state`` — Wire-string of the FSM state after the last
  accepted transition (or the ``initial_state`` if no record is
  accepted). One of the six :data:`STATES` values.
- ``initial_state`` — Wire-string of the FSM state at the start
  of the recorded session. One of the six :data:`STATES` values.
- ``org_id`` — Org identifier the machine tracks.
- ``persona_id`` — Persona identifier the machine tracks.
- ``records`` — Ordered list of :class:`TransitionRecord` projections.
  Each entry is a five-field object (alphabetically sorted) with
  the same JCS-canonical form the Rust pendant emits:

    - ``accepted`` (bool)
    - ``from_state`` (wire-string)
    - ``reason`` (string OR omitted when ``None`` / accepted records)
    - ``to_state`` (wire-string)
    - ``ts_utc`` (RFC-3339 second-precision UTC string)

- ``schema`` — Schema identifier; constant
  ``"wakir.persona-engine.lifecycle-trace/1"``.

Serialisation
-------------

The canonical bytes are produced by ``json.dumps`` with
``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=False``,
UTF-8-encoded. ``reason=None`` fields are **omitted** (matching the
Rust ``#[serde(skip_serializing_if = "Option::is_none")]`` pin from
``persona-engine-fsm::TransitionRecord``). Rejected records keep
their ``reason`` string in the wire-form.

The outer trace hash is ``"sha256:" + hex(SHA-256(canonical_bytes))``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json``
is the byte-level cross-lang pin: both
``wirelang/tests/persona_engine/test_lifecycle_state_machine_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-fsm/tests/lifecycle_state_machine_cross_lang_fixture_test.rs``
(Rust) consume the same vectors. Any drift on either side fails
both suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                  <-> Rust pendant
    ------------------------------------------------------------------------
    serialize_lifecycle_trace(trace) -> bytes      <-> serialize_trace
    lifecycle_trace_sha256_hex(trace) -> str       <-> trace_sha256_hex
    lifecycle_trace_hash_prefixed(trace) -> str    <-> trace_hash_prefixed
    build_lifecycle_trace(machine) -> LifecycleTrace <-> LifecycleTrace::from_fsm
    build_lifecycle_trace_from_records(...)        <-> LifecycleTrace::from_records
    LifecycleTrace (dataclass)                     <-> LifecycleTrace (struct)
    LIFECYCLE_TRACE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                               <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item — persona-engine FSM Rust
  migration (PR #137 authority).
- Selin PR #65 (Sprint-Pengine-8) — Python schema authority for
  the underlying six-state, nine-transition envelope.
- Reza  PR #170 (Tag-18) — sibling-module + cross-lang fixture
  pattern reference (anchor-emitter).
- Reza  PR #172 (Tag-19) — fixture-file structure + JCS-canonical
  serialisation reference (subscribe-loop ack-record).
- Reza  PR #176 (Tag-20) — recovery-workflow canonical projection
  reference (multi-record trace shape).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from wirelang.persona_engine.lifecycle_state_machine import (
    LifecycleStateMachine,
    STATES,
    TransitionRecord,
    VALID_TRANSITIONS,
)


#: Schema identifier emitted on every lifecycle-trace canonical form.
#: The version suffix ``/1`` is bumped only when a wire-shape change
#: is intentional (additive-key cases included). Both Python and Rust
#: pin this exact byte string.
LIFECYCLE_TRACE_SCHEMA = "wakir.persona-engine.lifecycle-trace/1"

#: Prefix used by the prefixed-form hash (matches the sibling pattern
#: from ``subscribe_ack`` / ``anchor_emitter``).
HASH_PREFIX = "sha256:"

#: Length of a bare-hex SHA-256 digest (no prefix).
SHA256_HEX_LEN = 64


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------


class LifecycleTraceError(ValueError):
    """Raised when a caller-supplied input fails the Tag-21 shape
    pre-conditions (unknown state strings, malformed records, etc.).
    """


# ---------------------------------------------------------------------
# Dataclass surface
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleTrace:
    """In-Python representation of the canonical-trace wire-shape.

    Field order matches the JCS-canonical key order (alphabetical).
    All six fields are required; ``records`` may be empty when the
    machine has not yet attempted any transition.

    Construct via :func:`build_lifecycle_trace` (from a live
    :class:`LifecycleStateMachine`) or via
    :func:`build_lifecycle_trace_from_records` (from a raw history
    list, e.g. after KV-replay).
    """

    final_state: str
    initial_state: str
    org_id: str
    persona_id: str
    records: List[TransitionRecord] = field(default_factory=list)
    schema: str = LIFECYCLE_TRACE_SCHEMA


# ---------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------


def build_lifecycle_trace(
    machine: LifecycleStateMachine,
    *,
    initial_state: Optional[str] = None,
) -> LifecycleTrace:
    """Build a :class:`LifecycleTrace` from a live state machine.

    ``initial_state`` defaults to the spec ``"uninstantiated"`` (the
    Python ``LifecycleStateMachine`` default). Callers that
    constructed the machine in a non-default initial state SHOULD
    pass that state explicitly so the trace's ``initial_state``
    field reflects the actual session start.

    The ``records`` list is a copy of ``machine.history`` to keep
    the returned trace immutable from the caller's perspective.
    """
    if initial_state is None:
        initial_state = "uninstantiated"
    if initial_state not in STATES:
        raise LifecycleTraceError(
            f"unknown initial_state {initial_state!r}; valid: {STATES}"
        )
    return LifecycleTrace(
        final_state=machine.state,
        initial_state=initial_state,
        org_id=machine.org_id,
        persona_id=machine.persona_id,
        records=list(machine.history),
        schema=LIFECYCLE_TRACE_SCHEMA,
    )


def build_lifecycle_trace_from_records(
    *,
    persona_id: str,
    org_id: str,
    initial_state: str,
    records: Sequence[TransitionRecord],
) -> LifecycleTrace:
    """Build a :class:`LifecycleTrace` from an explicit record list.

    The ``final_state`` is derived by walking the accepted records
    in order from ``initial_state``. Rejected records are passed
    through unchanged (audit annotations; they do not advance the
    state). The resulting ``final_state`` is **NOT** re-validated
    against :data:`VALID_TRANSITIONS` — callers that need that
    invariant should call :meth:`LifecycleStateMachine.replay`
    first and then :func:`build_lifecycle_trace`. This entry-point
    is deliberately lenient so fixture builders can pin
    "corrupted-trail" sub-cases without the replay-time guards.

    Raises :class:`LifecycleTraceError` if any record references a
    wire-string outside :data:`STATES`.
    """
    if initial_state not in STATES:
        raise LifecycleTraceError(
            f"unknown initial_state {initial_state!r}; valid: {STATES}"
        )
    state = initial_state
    materialised: List[TransitionRecord] = []
    for idx, rec in enumerate(records):
        if rec.from_state not in STATES:
            raise LifecycleTraceError(
                f"record[{idx}] from_state {rec.from_state!r} not in STATES"
            )
        if rec.to_state not in STATES:
            raise LifecycleTraceError(
                f"record[{idx}] to_state {rec.to_state!r} not in STATES"
            )
        if rec.accepted:
            # No transition-table guard here: fixture builders may
            # pin synthetic corrupted-trail cases. The replay guard
            # is intentionally NOT re-implemented in this helper.
            state = rec.to_state
        materialised.append(rec)
    return LifecycleTrace(
        final_state=state,
        initial_state=initial_state,
        org_id=org_id,
        persona_id=persona_id,
        records=materialised,
        schema=LIFECYCLE_TRACE_SCHEMA,
    )


# ---------------------------------------------------------------------
# Wire-shape (JCS-canonical) projection helpers
# ---------------------------------------------------------------------


def _record_to_wire_dict(rec: TransitionRecord) -> Dict[str, Any]:
    """Project a single :class:`TransitionRecord` onto the
    canonical-wire dict shape.

    ``reason=None`` is omitted to match the Rust
    ``#[serde(skip_serializing_if = "Option::is_none")]`` pin. The
    resulting dict has either four keys (accepted records) or five
    keys (rejected records with a reason string).
    """
    out: Dict[str, Any] = {
        "accepted": rec.accepted,
        "from_state": rec.from_state,
        "to_state": rec.to_state,
        "ts_utc": rec.ts_utc,
    }
    if rec.reason is not None:
        out["reason"] = rec.reason
    return out


def lifecycle_trace_to_wire_dict(trace: LifecycleTrace) -> Dict[str, Any]:
    """Project a :class:`LifecycleTrace` onto a JSON-compatible dict.

    The returned dict's keys are deliberately NOT pre-sorted; the
    canonical-bytes producer (:func:`serialize_lifecycle_trace`) uses
    ``sort_keys=True`` to enforce JCS-canonical alphabetical key
    order. Tests that inspect the in-Python projection should sort
    keys themselves or use the canonical bytes path.
    """
    return {
        "final_state": trace.final_state,
        "initial_state": trace.initial_state,
        "org_id": trace.org_id,
        "persona_id": trace.persona_id,
        "records": [_record_to_wire_dict(r) for r in trace.records],
        "schema": trace.schema,
    }


def serialize_lifecycle_trace(trace: LifecycleTrace) -> bytes:
    """Return the JCS-canonical UTF-8 bytes of a lifecycle trace.

    The byte-form is deterministic, sorted-key, no-whitespace JSON.
    This is the exact byte-string the Rust pendant
    (``persona-engine-fsm::serialize_trace``) emits for the same
    logical input.
    """
    obj = lifecycle_trace_to_wire_dict(trace)
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    """Return the lower-case hex digest of SHA-256 over ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def lifecycle_trace_sha256_hex(trace: LifecycleTrace) -> str:
    """Return the bare lower-case hex SHA-256 of the canonical bytes."""
    return sha256_hex(serialize_lifecycle_trace(trace))


def lifecycle_trace_hash_prefixed(trace: LifecycleTrace) -> str:
    """Return ``"sha256:" + lifecycle_trace_sha256_hex(trace)``."""
    return HASH_PREFIX + lifecycle_trace_sha256_hex(trace)


def serialize_and_hash(trace: LifecycleTrace) -> "tuple[bytes, str]":
    """One-shot helper: return ``(canonical_bytes, prefixed_hash)``.

    Equivalent to calling :func:`serialize_lifecycle_trace` and
    :func:`lifecycle_trace_hash_prefixed` individually but only
    serialises once.
    """
    payload = serialize_lifecycle_trace(trace)
    return payload, HASH_PREFIX + sha256_hex(payload)


# ---------------------------------------------------------------------
# Spec-set helpers (re-exported for fixture / test convenience)
# ---------------------------------------------------------------------


def valid_state_set() -> "frozenset[str]":
    """Return the closed set of valid state wire-strings (defensive
    snapshot for callers that want to validate fixture inputs)."""
    return frozenset(STATES)


def valid_transition_set() -> "frozenset[tuple[str, str]]":
    """Return the closed set of valid ``(from, to)`` wire-pairs."""
    return frozenset(VALID_TRANSITIONS)


__all__ = [
    "HASH_PREFIX",
    "LIFECYCLE_TRACE_SCHEMA",
    "LifecycleTrace",
    "LifecycleTraceError",
    "SHA256_HEX_LEN",
    "build_lifecycle_trace",
    "build_lifecycle_trace_from_records",
    "lifecycle_trace_hash_prefixed",
    "lifecycle_trace_sha256_hex",
    "lifecycle_trace_to_wire_dict",
    "serialize_and_hash",
    "serialize_lifecycle_trace",
    "sha256_hex",
    "valid_state_set",
    "valid_transition_set",
]
