# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Deterministic-Diff-Engine for the Doppelbetrieb-Shadow bridge.

Sprint-Pengine-15-Mini (ADR-0063 §Folgeartefakte Item 2).

During the Phase-3a Doppelbetrieb-Bridge window (~4 weeks, KW 27-31)
the Python persona-engine and the Rust persona-engine run in parallel.
Both implementations MUST produce byte-identical CloudEvent envelopes
for the same logical input — otherwise the cutover acceptance gate
cannot trust the Rust implementation as a drop-in replacement.

This module is the **deterministic-diff oracle** that the bridge-audit-
writer uses to compare two implementations' outputs for the same input
and surface structured drift reports.

Comparison contract
-------------------

The engine takes a logical input descriptor (:class:`DiffInput`) and a
pair of :class:`Implementation` adapters. It runs both implementations,
JCS-canonicalises their resulting CloudEvent envelopes, hashes the
canonical bytes, and produces a :class:`DiffReport` with:

- ``byte_identical`` — short-circuit boolean: True iff both JCS hashes
  match. The common-case fast path: byte-identical → no drift, done.
- ``field_diffs`` — list of structured :class:`FieldDiff` entries when
  bytes diverge. Each entry pins a JSON-Pointer-style field path
  (e.g. ``"/output_payload_sha256"``) and the two values.
- ``consistency_score`` — float in ``[0.0, 1.0]``. ``1.0`` = byte-
  identical; ``0.0`` = total drift (no shared fields). Computed as
  ``1 - (drifted_fields / total_fields)`` over the union of fields
  present in either envelope.
- ``jcs_hash_a`` / ``jcs_hash_b`` — ``"sha256:<64hex>"`` of each
  implementation's canonical bytes. Operators can paste these into
  the audit log without re-running the diff.

JCS choice
----------

The engine canonicalises with :func:`wirelang.identity._jcs_pure.canonicalize`
(RFC 8785 § 3, pure-Python fallback). The pure-Python path is the
default to keep the diff-engine dependency-free; production callers
that already have the ``rfc8785`` C-extension installed get the same
bytes from either path (the pure-Python module is byte-identical to
the C extension for the JSON subset Wakir uses — see the
``test_pure_python_fallback.py`` consistency suite).

Why not use the existing bridge-audit-writer envelope directly?
---------------------------------------------------------------

The two implementations to compare (Python ``BridgeAuditWriter.emit``
in ``wirelang/persona_engine/bridge_audit_writer.py`` and the WAT-anchor
LeafRecord in ``wat/anchor/bridge_audit_writer.py``) emit envelopes
with **different field shapes** today — that is fine and expected.
The diff-engine compares envelopes at the **CloudEvent-conformant
intersection layer**: a canonical projection that both implementations
populate. Implementation-private fields (e.g. ``v907_pin``,
``capability_token_hash``) are NOT projected away — they are surfaced
as drift in the report when only one side carries them, so operators
see what diverges.

The intent for Phase-3a is that both implementations converge on the
same envelope shape; the diff-engine is the surfacing tool that tracks
that convergence.

Use as a CI gate
----------------

The 4-week Doppelbetrieb-Vergleich-Clock counts as "consistent" only
when the diff-engine reports ``byte_identical=True`` for every output
emission. A CI replay over a 1000-event mock-trace produces a
``DiffReport`` summary; ``consistency_score < 1.0`` for any single
event fails the gate.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from wirelang.identity import _jcs_pure


__all__ = [
    "CloudEventEnvelope",
    "DiffInput",
    "DiffKind",
    "FieldDiff",
    "DiffReport",
    "Implementation",
    "canonicalize_envelope",
    "jcs_hash",
    "diff_envelopes",
    "consistency_score",
    "compare_implementations",
]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


#: A CloudEvent envelope is, for diff purposes, a plain JSON-friendly
#: mapping. We do not pin a schema here because the diff-engine's job
#: is to detect drift *between* implementations — including drift in
#: the envelope shape itself. The canonicaliser handles ordering.
CloudEventEnvelope = Mapping[str, Any]


@dataclass(frozen=True)
class DiffInput:
    """Logical input fed identically to both implementations.

    The diff-engine does not care how each implementation translates
    these fields into envelope bytes; that is the comparison's whole
    point. Fields:

    - ``org_id`` / ``persona_id`` / ``session_id``: identity tuple.
    - ``step_index``: 0-based emission counter within the session.
    - ``output_kind``: one of ``"tool_call"``, ``"reply"``,
      ``"audit_annotation"`` — mirrors the persona-engine alphabet.
      Implementations that use a different alphabet (e.g. the WAT-
      anchor ``action_type``) are expected to translate.
    - ``payload``: opaque bytes the implementation will hash.
    - ``ts_utc``: RFC-3339 UTC, second-precision; identical for both
      implementations to remove clock-skew as a drift source.
    """

    org_id: str
    persona_id: str
    session_id: str
    step_index: int
    output_kind: str
    payload: bytes
    ts_utc: str


class Implementation(Protocol):
    """Adapter contract: run an implementation against a DiffInput.

    The diff-engine is intentionally callable with arbitrary adapters
    so the same machinery serves Python-engine-vs-WAT-anchor today
    AND Python-engine-vs-Rust-engine in Phase-3a. The adapter is
    responsible for translating ``DiffInput`` to its native call
    signature and returning the resulting envelope as a JSON-friendly
    mapping.
    """

    def __call__(self, input_: DiffInput) -> CloudEventEnvelope:  # pragma: no cover - protocol
        ...


class DiffKind(enum.Enum):
    """Kind of field-level divergence between two envelopes."""

    #: Field present in both but values differ.
    VALUE_MISMATCH = "value-mismatch"

    #: Field present only in implementation A.
    ONLY_IN_A = "only-in-a"

    #: Field present only in implementation B.
    ONLY_IN_B = "only-in-b"

    #: Field present in both with same value but different JSON type
    #: (e.g. ``1`` int vs ``"1"`` string). Numeric-precision drift
    #: also lands here.
    TYPE_MISMATCH = "type-mismatch"


@dataclass(frozen=True)
class FieldDiff:
    """One field-level drift entry in a :class:`DiffReport`.

    The ``path`` is JSON-Pointer-style (RFC 6901): leading slash,
    member tokens joined by ``/``, array indices as decimal strings.
    The root envelope is ``""``.
    """

    path: str
    kind: DiffKind
    value_a: Any
    value_b: Any


@dataclass(frozen=True)
class DiffReport:
    """Outcome of a single diff-engine comparison.

    Attributes
    ----------
    byte_identical
        True iff ``jcs_hash_a == jcs_hash_b``. The fast-path indicator.
    jcs_hash_a, jcs_hash_b
        ``"sha256:<64hex>"`` of the canonical bytes per implementation.
    field_diffs
        Ordered list of :class:`FieldDiff`. Empty iff ``byte_identical``.
        Order is deterministic (sorted by ``path``).
    consistency_score
        Float in ``[0.0, 1.0]``. See module docstring.
    envelope_a, envelope_b
        Echo of the implementations' raw envelopes for caller-side
        inspection. Not mutated by the diff-engine.
    """

    byte_identical: bool
    jcs_hash_a: str
    jcs_hash_b: str
    field_diffs: Sequence[FieldDiff]
    consistency_score: float
    envelope_a: CloudEventEnvelope
    envelope_b: CloudEventEnvelope

    def has_drift(self) -> bool:
        return not self.byte_identical

    def summary(self) -> str:
        """One-line operator-readable summary."""
        if self.byte_identical:
            return (
                f"byte-identical jcs={self.jcs_hash_a} "
                f"score={self.consistency_score:.4f}"
            )
        return (
            f"drift fields={len(self.field_diffs)} "
            f"score={self.consistency_score:.4f} "
            f"hash_a={self.jcs_hash_a} hash_b={self.jcs_hash_b}"
        )


# ---------------------------------------------------------------------------
# JCS canonicalisation + hash
# ---------------------------------------------------------------------------


def _coerce_for_jcs(value: Any) -> Any:
    """Recursively coerce mapping-like containers to plain ``dict`` so
    the ``_jcs_pure.canonicalize`` walker accepts them.

    ``_jcs_pure`` does an ``isinstance(value, dict)`` check; the
    diff-engine accepts any ``Mapping`` from caller adapters (the
    ``CloudEventEnvelope`` type alias is ``Mapping[str, Any]``) so we
    normalise here. Tuples are normalised to lists so adapters can
    return immutable structures without breaking the canonicaliser.
    """
    if isinstance(value, Mapping):
        return {k: _coerce_for_jcs(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_for_jcs(v) for v in value]
    return value


def canonicalize_envelope(envelope: CloudEventEnvelope) -> bytes:
    """JCS-canonicalise ``envelope`` to its RFC 8785 byte form.

    Delegates to :func:`wirelang.identity._jcs_pure.canonicalize` so
    the diff-engine shares its canonicaliser with the AIP / DID / FTD
    signers. Byte-identical to the ``rfc8785`` C extension for the
    JSON subset Wakir documents use.

    Mapping-typed inputs are coerced to plain ``dict`` first so the
    canonicaliser accepts envelopes built from ``MappingProxyType``,
    ``frozendict``, or any other ``Mapping`` flavour.
    """
    return _jcs_pure.canonicalize(_coerce_for_jcs(envelope))


def jcs_hash(envelope: CloudEventEnvelope) -> str:
    """Return ``"sha256:<64hex>"`` of the envelope's JCS bytes."""
    return "sha256:" + hashlib.sha256(canonicalize_envelope(envelope)).hexdigest()


# ---------------------------------------------------------------------------
# Field-path diff (JSON-Pointer-style)
# ---------------------------------------------------------------------------


_SENTINEL = object()


def _escape_jp_token(token: str) -> str:
    """Escape a JSON-Pointer reference token (RFC 6901 § 4)."""
    return token.replace("~", "~0").replace("/", "~1")


def _walk(
    path: str,
    a: Any,
    b: Any,
    out: list[FieldDiff],
) -> None:
    """Recursively collect field-level diffs starting at ``path``.

    Comparison rules:

    - If both values are plain mappings, recurse on the union of keys.
    - If both values are lists, compare element-by-element. Length
      mismatch surfaces an ``ONLY_IN_*`` entry per orphan index.
    - Otherwise compare by value; ``TYPE_MISMATCH`` is emitted when
      the Python types differ but ``repr`` round-trips agree (covers
      the numeric-precision-drift case: ``1`` vs ``1.0`` vs ``"1"``).
    """
    if a is _SENTINEL:
        out.append(FieldDiff(path=path, kind=DiffKind.ONLY_IN_B, value_a=None, value_b=b))
        return
    if b is _SENTINEL:
        out.append(FieldDiff(path=path, kind=DiffKind.ONLY_IN_A, value_a=a, value_b=None))
        return

    if isinstance(a, Mapping) and isinstance(b, Mapping):
        keys = sorted(set(a.keys()) | set(b.keys()))
        for k in keys:
            child_path = f"{path}/{_escape_jp_token(str(k))}"
            _walk(
                child_path,
                a.get(k, _SENTINEL) if k in a else _SENTINEL,
                b.get(k, _SENTINEL) if k in b else _SENTINEL,
                out,
            )
        return

    if isinstance(a, list) and isinstance(b, list):
        max_len = max(len(a), len(b))
        for i in range(max_len):
            child_path = f"{path}/{i}"
            av = a[i] if i < len(a) else _SENTINEL
            bv = b[i] if i < len(b) else _SENTINEL
            _walk(child_path, av, bv, out)
        return

    if a == b and type(a) is type(b):
        return

    if a == b and type(a) is not type(b):
        out.append(
            FieldDiff(path=path, kind=DiffKind.TYPE_MISMATCH, value_a=a, value_b=b)
        )
        return

    # Different value. If types also differ, prefer TYPE_MISMATCH so
    # operators see the structural divergence; otherwise VALUE_MISMATCH.
    if type(a) is not type(b):
        out.append(
            FieldDiff(path=path, kind=DiffKind.TYPE_MISMATCH, value_a=a, value_b=b)
        )
    else:
        out.append(
            FieldDiff(path=path, kind=DiffKind.VALUE_MISMATCH, value_a=a, value_b=b)
        )


def diff_envelopes(
    envelope_a: CloudEventEnvelope,
    envelope_b: CloudEventEnvelope,
) -> Sequence[FieldDiff]:
    """Return field-level diff entries between two envelopes.

    The result is sorted by ``path`` for deterministic comparison
    across runs. Empty list iff the envelopes are structurally equal
    (which implies byte-identical JCS output).
    """
    out: list[FieldDiff] = []
    _walk("", envelope_a, envelope_b, out)
    out.sort(key=lambda fd: fd.path)
    return tuple(out)


# ---------------------------------------------------------------------------
# Consistency score
# ---------------------------------------------------------------------------


def _count_leaves(value: Any) -> int:
    """Count leaf positions (non-container values) in a JSON-tree.

    Leaves are non-Mapping, non-list values. The empty mapping / empty
    list counts as a single leaf to keep the score well-defined for
    edge cases.
    """
    if isinstance(value, Mapping):
        if not value:
            return 1
        return sum(_count_leaves(v) for v in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return sum(_count_leaves(v) for v in value)
    return 1


def consistency_score(
    envelope_a: CloudEventEnvelope,
    envelope_b: CloudEventEnvelope,
    diffs: Sequence[FieldDiff],
) -> float:
    """Compute the consistency score in ``[0.0, 1.0]``.

    Definition: ``1 - (drifted_leaves / total_leaves)`` where
    ``total_leaves`` is the leaf count over the union of both
    envelopes' leaves. ``1.0`` ⇒ byte-identical; ``0.0`` ⇒ no shared
    leaves at all.
    """
    if not diffs:
        return 1.0
    total_a = _count_leaves(envelope_a)
    total_b = _count_leaves(envelope_b)
    # Use the maximum so a one-sided huge envelope cannot inflate the
    # score artificially.
    total = max(total_a, total_b)
    if total == 0:
        return 1.0
    drifted = len(diffs)
    if drifted >= total:
        return 0.0
    return 1.0 - (drifted / total)


# ---------------------------------------------------------------------------
# Top-level compare
# ---------------------------------------------------------------------------


def compare_implementations(
    input_: DiffInput,
    impl_a: Implementation,
    impl_b: Implementation,
) -> DiffReport:
    """Run both implementations against ``input_`` and produce a DiffReport.

    The function is pure: it does not mutate ``input_``, and it does
    not touch the filesystem or network on its own. Side-effects (if
    any) come from the implementation adapters.
    """
    envelope_a = impl_a(input_)
    envelope_b = impl_b(input_)
    hash_a = jcs_hash(envelope_a)
    hash_b = jcs_hash(envelope_b)
    if hash_a == hash_b:
        return DiffReport(
            byte_identical=True,
            jcs_hash_a=hash_a,
            jcs_hash_b=hash_b,
            field_diffs=(),
            consistency_score=1.0,
            envelope_a=envelope_a,
            envelope_b=envelope_b,
        )
    diffs = diff_envelopes(envelope_a, envelope_b)
    score = consistency_score(envelope_a, envelope_b, diffs)
    return DiffReport(
        byte_identical=False,
        jcs_hash_a=hash_a,
        jcs_hash_b=hash_b,
        field_diffs=diffs,
        consistency_score=score,
        envelope_a=envelope_a,
        envelope_b=envelope_b,
    )
