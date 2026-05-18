# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-audit-replay canonical-trace helpers (Tag-37 Phase-3a 14. Modul).

This module is the **Python sibling** of the Rust canonical sub-module
``persona_engine_bridge_audit_replay::canonical`` (Tag-37 expansion of
the existing crate ``persona-engine-bridge-audit-replay``).  Where the
live :mod:`wirelang.persona_engine.bridge_audit_replay` module provides
the operator-facing :class:`ReplayReport` surface (with the per-step
``Divergence`` echoes and the live field-level :class:`FieldDiff`
list), this module provides the canonical-trace surface that pairs
byte-paritätisch with the Rust canonical sub-module — both sides emit
a JCS-canonical :class:`ReplayTrace` per replay outcome so the
Phase-3a Welle-3 Konsistenz-Oracle can diff Python-side and Rust-side
replay traces byte-for-byte without round-tripping through any other
substrate.

Why a sibling module?
---------------------

The live :class:`ReplayReport` carries ``actual`` / ``expected``
record echoes and field-level :class:`FieldDiff` entries inside its
:class:`Divergence` list; those are operator-readable inspection
fields, not stable cross-lang wire shape (the field-diff path
alphabet is wire-stable but the full :class:`AuditRecord` echo
re-introduces unbounded user-data into the trace).  The Rust crate
already exposes the operator-facing :class:`ReplayReport` with
:class:`Divergence` echoes; the cross-lang test suite needs a
stable projection — that is the replay-trace.

Keeping the helpers in a separate Apache-2.0 module preserves the
existing :mod:`wirelang.persona_engine.bridge_audit_replay` surface
unchanged and matches the sibling-pattern Reza used for
:mod:`wirelang.persona_engine.bridge_audit_diff_engine_canonical`
(Tag-36 13. Modul) and
:mod:`wirelang.persona_engine.v907_verify_canonical` (Tag-35 12. Modul).

Schema
------

The replay-trace carries exactly nine top-level fields (alphabetically
sorted in the JCS-canonical wire form):

- ``actual_record_count`` — Number of records in the actual stream
  (echo of :attr:`ReplayReport.actual_record_count`).
- ``divergence_first_kind`` — Wire-string of the first divergence's
  :class:`DivergenceKind` (one of ``value-mismatch`` /
  ``missing-in-actual`` / ``extra-in-actual``), or the empty string
  ``""`` if the replay succeeded.
- ``divergence_first_step`` — 0-based step index of the first
  divergence, or ``-1`` if the replay succeeded.  Integer wire form
  (not nullable) to keep the trace integer-typed across both
  languages.
- ``divergences_summary`` — Compact deterministic projection of the
  divergence list.  Format: each entry is rendered as
  ``"<step>|<kind>"`` and the list is joined in step-index order
  with ``;``.  Empty string ``""`` if the replay succeeded.
  ``AuditRecord`` echoes and field-level :class:`FieldDiff` entries
  are NOT projected into the trace (they carry arbitrary user data
  with no cross-lang stability guarantee); the ``step`` and ``kind``
  are sufficient to pin the divergence location and class.
  Example for two drifted steps: ``"1|value-mismatch;3|missing-in-actual"``.
- ``expected_record_count`` — Number of records the trajectory
  expected.
- ``schema`` — Constant schema id
  ``"wakir.persona-engine.bridge-audit-replay-canonical/1"``.
- ``stream_hash_actual`` — ``"sha256:<64hex>"`` of the actual record
  sequence (echo of :attr:`ReplayReport.stream_hash_actual`).
- ``stream_hash_expected`` — ``"sha256:<64hex>"`` of the expected
  record sequence.
- ``success`` — ``True`` iff every expected record matches the
  actual record at the same step (echo of
  :attr:`ReplayReport.success`).

Serialisation
-------------

The canonical bytes are produced by ``rfc8785.dumps`` (RFC 8785 JCS).
The outer trace hash is ``"sha256:" + hex(SHA-256(canonical_bytes))``.

This is the same serialisation discipline used by every other
Phase-3a cross-lang canonical-trace module — JCS-canonical bytes,
SHA-256, hex, prefixed with ``"sha256:"``.  Rust pendant uses
``serde_jcs::to_vec`` + ``sha2::Sha256``.

Why integer ``divergence_first_step = -1`` instead of nullable?
---------------------------------------------------------------

The live :attr:`ReplayReport.time_to_divergence_steps` is
``Optional[int]`` (``None`` on success).  Nullable integers across
the JCS canonicaliser are a known drift surface (``null`` vs.
``0`` collisions in operator-readable diffs; Rust-side ``Option<usize>``
serialises to ``null``).  Pinning the success-path to the sentinel
``-1`` keeps the trace integer-typed without introducing a nullable-
type drift surface inside the determinism oracle.  Reverse derivation:
``time_to_divergence = None if divergence_first_step == -1 else
divergence_first_step``.

Cross-lang anchor
-----------------

The fixture file ``tests/fixtures/bridge-audit-replay-cross-lang/
fixtures.json`` is the byte-level cross-lang pin: both
``wirelang/tests/persona_engine/test_bridge_audit_replay_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-bridge-audit-replay/tests/cross_lang_replay_trace_fixture_test.rs``
(Rust) consume the same vectors.  Any drift on either side fails
both suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                          <-> Rust pendant
    ---------------------------------------------------------------------------
    build_replay_trace(actual, expected) -> ReplayTrace    <-> build_replay_trace
    build_trace_from_report(report) -> ReplayTrace         <-> build_trace_from_report
    serialize_replay_trace(trace) -> bytes                 <-> serialize_trace
    replay_trace_sha256_hex(trace) -> str                  <-> trace_sha256_hex
    replay_trace_hash_prefixed(trace) -> str               <-> trace_hash_prefixed
    ReplayTrace (dataclass)                                <-> ReplayTrace
    REPLAY_TRACE_SCHEMA / HASH_PREFIX / SHA256_HEX_LEN     <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item 11 (this crate).
- ADR-0066 — Welle-3 Konsistenz-Oracle-Selbst-Cutover closure
  (replay leg of the bridge-audit trilogy:
  writer/diff-engine/replay).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final, Sequence

from wirelang.persona_engine.bridge_audit_replay import (
    AuditRecord,
    Divergence,
    DivergenceKind,
    ExpectedTrajectory,
    ReplayEngine,
    ReplayReport,
)

# ---------------------------------------------------------------------------
# Optional-dependency resolver (same posture as v907_verify_canonical and
# bridge_audit_diff_engine_canonical).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False


#: JCS-canonical schema id for the bridge-audit-replay trace wire form.
#: Cross-lang anchor — must match the Rust constant of the same name.
REPLAY_TRACE_SCHEMA: Final[str] = (
    "wakir.persona-engine.bridge-audit-replay-canonical/1"
)

#: Outer-hash prefix.  Cross-lang anchor.
HASH_PREFIX: Final[str] = "sha256:"

#: Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
SHA256_HEX_LEN: Final[int] = 64

#: Sentinel integer for the success-path ``divergence_first_step`` field.
#: Cross-lang anchor.
DIVERGENCE_NONE_SENTINEL: Final[int] = -1

#: DivergenceKind wire-string alphabet (echo of the live enum), frozen
#: across Rust/Python.
KIND_VALUE_MISMATCH: Final[str] = "value-mismatch"
KIND_MISSING_IN_ACTUAL: Final[str] = "missing-in-actual"
KIND_EXTRA_IN_ACTUAL: Final[str] = "extra-in-actual"

DIVERGENCE_KIND_VALUES: Final[tuple[str, ...]] = (
    KIND_VALUE_MISMATCH,
    KIND_MISSING_IN_ACTUAL,
    KIND_EXTRA_IN_ACTUAL,
)

#: Divergence summary separator characters.  Frozen across Rust/Python.
#: ``|`` separates the step from the kind inside a single entry; ``;``
#: separates entries.  Neither character appears in the
#: :class:`DivergenceKind` alphabet above; the step is a decimal
#: integer with no separator overlap.  Wire-stable.
SUMMARY_ENTRY_SEP: Final[str] = ";"
SUMMARY_STEP_KIND_SEP: Final[str] = "|"


# ---------------------------------------------------------------------------
# Trace dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayTrace:
    """Canonical-trace projection of a bridge-audit-replay outcome.

    Fields are ordered to match the alphabetical JCS sort the wire
    form uses; the dataclass itself is otherwise an opaque record.
    """

    actual_record_count: int
    divergence_first_kind: str
    divergence_first_step: int
    divergences_summary: str
    expected_record_count: int
    stream_hash_actual: str
    stream_hash_expected: str
    success: bool

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project this trace onto a JSON-compatible dict, ready for JCS.

        Keys are inserted in alphabetical order to document the wire
        contract; JCS will re-sort them lexicographically anyway, so
        the insertion order has no effect on the resulting bytes.
        """
        return {
            "actual_record_count": int(self.actual_record_count),
            "divergence_first_kind": self.divergence_first_kind,
            "divergence_first_step": int(self.divergence_first_step),
            "divergences_summary": self.divergences_summary,
            "expected_record_count": int(self.expected_record_count),
            "schema": REPLAY_TRACE_SCHEMA,
            "stream_hash_actual": self.stream_hash_actual,
            "stream_hash_expected": self.stream_hash_expected,
            "success": bool(self.success),
        }


# ---------------------------------------------------------------------------
# Trace-build helpers.
# ---------------------------------------------------------------------------


def _divergences_summary(divergences: Sequence[Divergence]) -> str:
    """Render the divergence list as a compact deterministic string.

    Format: ``"<step>|<kind>"`` per entry, joined with ``;`` in
    step-index order.  Empty string for an empty list.

    The input is assumed already step-index-sorted (the live
    :meth:`ReplayEngine.replay_stream` guarantees this); we re-sort
    defensively so a caller who hand-builds the list cannot break the
    trace.
    """
    parts = sorted(
        (
            (d.step_index, f"{d.step_index}{SUMMARY_STEP_KIND_SEP}{d.kind.value}")
            for d in divergences
        ),
        key=lambda t: t[0],
    )
    return SUMMARY_ENTRY_SEP.join(p for _, p in parts)


def build_replay_trace(
    actual: Sequence[AuditRecord],
    expected: ExpectedTrajectory,
) -> ReplayTrace:
    """Build a canonical replay-outcome trace.

    Takes the same arguments the live
    :meth:`ReplayEngine.replay_stream` would, runs the engine, and
    emits the canonical-trace projection.

    The function is **infallible** at the trace-build layer: the
    canonicaliser handles arbitrary record content the way the live
    module does.  Any drift in the canonicaliser surfaces as a
    trace-hash mismatch in the cross-lang fixture test, which is
    the intended boundary detector.
    """
    report = ReplayEngine().replay_stream(actual, expected)
    return build_trace_from_report(report)


def build_trace_from_report(report: ReplayReport) -> ReplayTrace:
    """Project an existing live :class:`ReplayReport` into a canonical-trace.

    Convenience helper for callers that already have a live report
    and want the canonical projection without re-running the engine.
    Byte-identical to :func:`build_replay_trace` on the same inputs.
    """
    if report.success:
        return ReplayTrace(
            actual_record_count=int(report.actual_record_count),
            divergence_first_kind="",
            divergence_first_step=DIVERGENCE_NONE_SENTINEL,
            divergences_summary="",
            expected_record_count=int(report.expected_record_count),
            stream_hash_actual=report.stream_hash_actual,
            stream_hash_expected=report.stream_hash_expected,
            success=True,
        )

    first = report.divergences[0]
    return ReplayTrace(
        actual_record_count=int(report.actual_record_count),
        divergence_first_kind=first.kind.value,
        divergence_first_step=int(first.step_index),
        divergences_summary=_divergences_summary(report.divergences),
        expected_record_count=int(report.expected_record_count),
        stream_hash_actual=report.stream_hash_actual,
        stream_hash_expected=report.stream_hash_expected,
        success=False,
    )


# ---------------------------------------------------------------------------
# Trace serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_replay_trace(trace: ReplayTrace) -> bytes:
    """Serialise a trace to its JCS-canonical UTF-8 bytes.

    Raises:
        :class:`wirelang.persona.persona_canonical_form.PersonaCanonicalFormDependencyMissingError`:
            if ``rfc8785`` is not installed in this environment.
    """
    if not _HAS_RFC8785:
        from wirelang.persona.persona_canonical_form import (
            PersonaCanonicalFormDependencyMissingError,
        )

        raise PersonaCanonicalFormDependencyMissingError("rfc8785")
    return _rfc8785_lib.dumps(trace.to_canonical_dict())


def replay_trace_sha256_hex(trace: ReplayTrace) -> str:
    """SHA-256 hex of the JCS bytes of ``trace``."""
    return hashlib.sha256(serialize_replay_trace(trace)).hexdigest()


def replay_trace_hash_prefixed(trace: ReplayTrace) -> str:
    """Prefixed outer hash: ``"sha256:" + replay_trace_sha256_hex``."""
    return HASH_PREFIX + replay_trace_sha256_hex(trace)


# ---------------------------------------------------------------------------
# Re-exports.
# ---------------------------------------------------------------------------


__all__ = [
    "DIVERGENCE_KIND_VALUES",
    "DIVERGENCE_NONE_SENTINEL",
    "HASH_PREFIX",
    "KIND_EXTRA_IN_ACTUAL",
    "KIND_MISSING_IN_ACTUAL",
    "KIND_VALUE_MISMATCH",
    "REPLAY_TRACE_SCHEMA",
    "ReplayTrace",
    "SHA256_HEX_LEN",
    "SUMMARY_ENTRY_SEP",
    "SUMMARY_STEP_KIND_SEP",
    "build_replay_trace",
    "build_trace_from_report",
    "replay_trace_hash_prefixed",
    "replay_trace_sha256_hex",
    "serialize_replay_trace",
]
