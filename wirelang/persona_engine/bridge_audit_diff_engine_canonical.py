# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-audit-diff-engine canonical-trace helpers (Tag-36 Phase-3a 13. Modul).

This module is the **Python sibling** of the Rust canonical sub-module
``persona_engine_bridge_diff::canonical`` (Tag-36 expansion of the
already-existing crate ``persona-engine-bridge-diff``).  Where the
existing :mod:`wirelang.persona_engine.bridge_audit_diff_engine` provides
the operator-facing ``DiffReport`` surface (with the live ``envelope_a``
and ``envelope_b`` echoes for inspection), this module provides the
canonical-trace surface that pairs byte-paritätisch with the Rust
canonical sub-module — both sides emit a JCS-canonical
``BridgeDiffTrace`` per compare outcome so the Phase-3a 3-way-triangle
(Doppelbetrieb-Vergleich) can diff Python-side and Rust-side
bridge-audit-diff-engine traces byte-for-byte without round-tripping
through any other substrate.

Why a sibling module?
---------------------

The existing :mod:`wirelang.persona_engine.bridge_audit_diff_engine`
provides the live ``DiffReport`` with ``envelope_a`` / ``envelope_b``
echoes; those are operator-readable inspection fields, not stable
cross-lang wire shape (caller-supplied envelopes carry arbitrary
nesting and number variants).  The Rust crate already exposes the
operator-facing ``DiffReport`` (with ``envelope_a`` / ``envelope_b`` as
``serde_json::Value`` echoes) but the cross-lang test suite needs a
stable projection — that is the canonical-trace.

Keeping the helpers in a separate Apache-2.0 module preserves the
existing ``bridge_audit_diff_engine.py`` BUSL surface unchanged
(spec §5 anchor, no licence change) and matches the sibling-pattern
Reza used for ``wirelang.persona_engine.v907_verify_canonical``
(Tag-35 sibling of ``persona-engine-v907-verify``).

Schema
------

The canonical-trace carries exactly eight top-level fields
(alphabetically sorted in the JCS-canonical wire form):

- ``byte_identical`` — ``True`` iff both implementations produced
  byte-identical JCS canonical bytes for the same input.  Fast-path
  indicator.
- ``drift_count`` — Number of :class:`FieldDiff` entries in the live
  ``DiffReport`` (i.e. ``len(report.field_diffs)``).  ``0`` iff
  ``byte_identical``.
- ``field_diffs_summary`` — Compact deterministic projection of the
  field-level drift entries.  Format: each entry is rendered as
  ``"<path>|<kind>"`` and the list is joined alphabetically with
  ``;``.  Empty string ``""`` iff ``byte_identical``.  The full
  field values are NOT projected into the trace (they carry
  arbitrary user data with no cross-lang stability guarantee); the
  ``path`` and ``kind`` are sufficient to pin the divergence
  location and class.  Example for two drifted leaves:
  ``"/data/payload|value-mismatch;/data/ts|type-mismatch"``.
- ``jcs_hash_a`` — ``"sha256:<64hex>"`` of implementation-A canonical
  bytes (echo of ``DiffReport.jcs_hash_a``).
- ``jcs_hash_b`` — ``"sha256:<64hex>"`` of implementation-B canonical
  bytes (echo of ``DiffReport.jcs_hash_b``).
- ``leaves_total`` — Total leaf count over the maximum of envelope-A
  and envelope-B leaf counts (the denominator used by
  :func:`consistency_score`).  Used by downstream consumers that
  want to reconstruct the score without float arithmetic across
  Python/Rust runtime boundaries.
- ``schema`` — Constant schema id
  ``"wakir.persona-engine.bridge-audit-diff-canonical/1"``.
- ``score_milli`` — Integer projection of the float
  ``consistency_score`` in ``[0, 1000]``.  Computed as
  ``floor(consistency_score * 1000)`` to remove float-formatting
  drift across language runtimes.  ``1000`` iff ``byte_identical``;
  ``0`` iff every leaf drifted.  Reverse derivation:
  ``score = score_milli / 1000.0`` (operator-readable, NOT a
  cross-lang stability anchor).

Serialisation
-------------

The canonical bytes are produced by ``rfc8785.dumps`` (RFC 8785 JCS).
The outer trace hash is ``"sha256:" + hex(SHA-256(canonical_bytes))``.

This is the same serialisation discipline used by every other Phase-3a
cross-lang canonical-trace module — JCS-canonical bytes, SHA-256, hex,
prefixed with the schema id ``"sha256:"``.  Rust pendant uses
``serde_jcs::to_vec`` + ``sha2::Sha256``.

Why integer ``score_milli`` instead of float ``consistency_score``?
-------------------------------------------------------------------

The float ``consistency_score`` is correct for operator-readable
output (it reads as ``0.8333`` in Python and ``0.8333`` in Rust for
the same drift), but float-formatting across the JCS canonicaliser
is fragile: ECMA-262 Number-to-String (RFC 8785 § 3.2.2.3) is
deterministic per-spec but real-world ``serde_jcs`` 0.2 + Python
``rfc8785`` MAY drift on edge cases (e.g. trailing zero handling,
exponent thresholds).  The bridge-audit-diff-engine is a determinism
oracle; introducing a float-formatting drift surface inside the
determinism oracle is contradictory.  The integer ``score_milli``
gives 3-decimal-place operator readability without the float wire-
shape liability.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/bridge-audit-diff-engine-cross-lang/fixtures.json``
is the byte-level cross-lang pin: both
``wirelang/tests/persona_engine/test_bridge_audit_diff_engine_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-bridge-diff/tests/cross_lang_diff_trace_fixture_test.rs``
(Rust) consume the same vectors.  Any drift on either side fails both
suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                          <-> Rust pendant
    ---------------------------------------------------------------------------
    build_bridge_diff_trace(envelope_a, envelope_b)        <-> build_bridge_diff_trace
    serialize_bridge_diff_trace(trace) -> bytes            <-> serialize_trace
    bridge_diff_trace_sha256_hex(trace) -> str             <-> trace_sha256_hex
    bridge_diff_trace_hash_prefixed(trace) -> str          <-> trace_hash_prefixed
    BridgeDiffTrace (dataclass)                            <-> BridgeDiffTrace
    BRIDGE_DIFF_TRACE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                                       <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a — Item 2 (deterministic-diff oracle)
  + Item 4 (Rust bridge-diff Crate, already merged Tag-17).
- ADR-0066 — Welle-3 Konsistenz-Oracle-Selbst-Cutover; this canonical
  surface closes the cross-lang trace leg for the diff-engine itself.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from wirelang.persona_engine.bridge_audit_diff_engine import (
    CloudEventEnvelope,
    DiffKind,
    DiffReport,
    FieldDiff,
    canonicalize_envelope,
    consistency_score as _live_consistency_score,
    diff_envelopes,
    jcs_hash as _live_jcs_hash,
)

# ---------------------------------------------------------------------------
# Optional-dependency resolver (same posture as v907_verify_canonical).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False


#: JCS-canonical schema id for the bridge-audit-diff trace wire form.
#: Cross-lang anchor — must match the Rust constant of the same name.
BRIDGE_DIFF_TRACE_SCHEMA: Final[str] = (
    "wakir.persona-engine.bridge-audit-diff-canonical/1"
)

#: Outer-hash prefix.  Cross-lang anchor.
HASH_PREFIX: Final[str] = "sha256:"

#: Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
SHA256_HEX_LEN: Final[int] = 64

#: DiffKind wire-string alphabet, frozen across Rust/Python.
KIND_VALUE_MISMATCH: Final[str] = "value-mismatch"
KIND_ONLY_IN_A: Final[str] = "only-in-a"
KIND_ONLY_IN_B: Final[str] = "only-in-b"
KIND_TYPE_MISMATCH: Final[str] = "type-mismatch"

DIFF_KIND_VALUES: Final[tuple[str, ...]] = (
    KIND_VALUE_MISMATCH,
    KIND_ONLY_IN_A,
    KIND_ONLY_IN_B,
    KIND_TYPE_MISMATCH,
)

#: Field-diff summary separator characters.  Frozen across Rust/Python.
#: ``|`` separates the path from the kind inside a single entry; ``;``
#: separates entries.  Neither character appears in any RFC-6901 path
#: token (JSON-Pointer escapes any literal ``/`` to ``~1`` and any
#: literal ``~`` to ``~0``); neither appears in the DiffKind alphabet
#: above.  Wire-stable.
SUMMARY_ENTRY_SEP: Final[str] = ";"
SUMMARY_PATH_KIND_SEP: Final[str] = "|"


# ---------------------------------------------------------------------------
# Trace dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeDiffTrace:
    """Canonical-trace projection of a bridge-audit-diff-engine compare outcome.

    Fields are ordered to match the alphabetical JCS sort the wire form
    uses; the dataclass itself is otherwise an opaque record.
    """

    byte_identical: bool
    drift_count: int
    field_diffs_summary: str
    jcs_hash_a: str
    jcs_hash_b: str
    leaves_total: int
    score_milli: int

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project this trace onto a JSON-compatible dict, ready for JCS.

        Keys are inserted in alphabetical order to document the wire
        contract; JCS will re-sort them lexicographically anyway, so
        the insertion order has no effect on the resulting bytes.
        """
        return {
            "byte_identical": bool(self.byte_identical),
            "drift_count": int(self.drift_count),
            "field_diffs_summary": self.field_diffs_summary,
            "jcs_hash_a": self.jcs_hash_a,
            "jcs_hash_b": self.jcs_hash_b,
            "leaves_total": int(self.leaves_total),
            "schema": BRIDGE_DIFF_TRACE_SCHEMA,
            "score_milli": int(self.score_milli),
        }


# ---------------------------------------------------------------------------
# Trace-build helpers.
# ---------------------------------------------------------------------------


def _count_leaves(value: Any) -> int:
    """Count leaf positions (non-container values) in a JSON-tree.

    Byte-identical algorithm to the live module's ``_count_leaves``.
    Pulled inline here (rather than imported as a private helper)
    so the trace contract is self-contained and changes to the live
    module's private helpers cannot silently shift the trace shape.

    Leaves are non-Mapping, non-list values.  The empty mapping /
    empty list counts as a single leaf to keep the count well-
    defined for edge cases (matches the live ``consistency_score``
    helper's normalisation).
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


def _field_diffs_summary(diffs: Sequence[FieldDiff]) -> str:
    """Render the field-diff list as a compact deterministic string.

    Format: ``"<path>|<kind>"`` per entry, joined with ``;`` in
    path-alphabetical order.  Empty string for an empty list.

    The input is assumed already path-sorted (the live
    :func:`diff_envelopes` guarantees this); we re-sort defensively
    so a caller who hand-builds the list cannot break the trace.
    """
    parts = sorted(
        f"{d.path}{SUMMARY_PATH_KIND_SEP}{d.kind.value}" for d in diffs
    )
    return SUMMARY_ENTRY_SEP.join(parts)


def _score_milli(score: float) -> int:
    """Project a float ``consistency_score`` into the integer ``[0, 1000]``.

    Uses ``floor`` (truncation toward zero for non-negative values) so
    Python and Rust agree byte-for-byte without depending on either
    runtime's rounding-mode default.
    """
    if score >= 1.0:
        return 1000
    if score <= 0.0:
        return 0
    # `int()` on a positive float truncates toward zero (matches
    # Rust's `as u32` cast on a positive `f64`).
    return int(score * 1000.0)


def build_bridge_diff_trace(
    envelope_a: CloudEventEnvelope,
    envelope_b: CloudEventEnvelope,
) -> BridgeDiffTrace:
    """Build a canonical bridge-audit-diff compare-outcome trace.

    Takes the same two envelopes the live
    :func:`bridge_audit_diff_engine.compare_implementations` would
    feed to the diff-engine and emits the canonical-trace projection.

    The function is **infallible** at the trace-build layer: the
    canonicaliser handles arbitrary nested mapping / list / scalar
    shapes the way the live module does.  Any drift in the
    canonicaliser surfaces as a trace-hash mismatch in the cross-lang
    fixture test, which is the intended boundary detector.
    """
    hash_a = _live_jcs_hash(envelope_a)
    hash_b = _live_jcs_hash(envelope_b)

    if hash_a == hash_b:
        return BridgeDiffTrace(
            byte_identical=True,
            drift_count=0,
            field_diffs_summary="",
            jcs_hash_a=hash_a,
            jcs_hash_b=hash_b,
            leaves_total=max(
                _count_leaves(envelope_a), _count_leaves(envelope_b)
            ),
            score_milli=1000,
        )

    diffs = diff_envelopes(envelope_a, envelope_b)
    score = _live_consistency_score(envelope_a, envelope_b, diffs)
    summary = _field_diffs_summary(diffs)
    leaves = max(_count_leaves(envelope_a), _count_leaves(envelope_b))

    return BridgeDiffTrace(
        byte_identical=False,
        drift_count=len(diffs),
        field_diffs_summary=summary,
        jcs_hash_a=hash_a,
        jcs_hash_b=hash_b,
        leaves_total=leaves,
        score_milli=_score_milli(score),
    )


def build_trace_from_report(report: DiffReport) -> BridgeDiffTrace:
    """Project an existing live :class:`DiffReport` into a canonical-trace.

    Convenience helper for callers that already have a live report
    and want the canonical projection without re-running the
    canonicaliser.  Byte-identical to
    :func:`build_bridge_diff_trace` on the same envelopes.
    """
    if report.byte_identical:
        return BridgeDiffTrace(
            byte_identical=True,
            drift_count=0,
            field_diffs_summary="",
            jcs_hash_a=report.jcs_hash_a,
            jcs_hash_b=report.jcs_hash_b,
            leaves_total=max(
                _count_leaves(report.envelope_a),
                _count_leaves(report.envelope_b),
            ),
            score_milli=1000,
        )
    return BridgeDiffTrace(
        byte_identical=False,
        drift_count=len(report.field_diffs),
        field_diffs_summary=_field_diffs_summary(report.field_diffs),
        jcs_hash_a=report.jcs_hash_a,
        jcs_hash_b=report.jcs_hash_b,
        leaves_total=max(
            _count_leaves(report.envelope_a),
            _count_leaves(report.envelope_b),
        ),
        score_milli=_score_milli(report.consistency_score),
    )


# ---------------------------------------------------------------------------
# Trace serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_bridge_diff_trace(trace: BridgeDiffTrace) -> bytes:
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


def bridge_diff_trace_sha256_hex(trace: BridgeDiffTrace) -> str:
    """SHA-256 hex of the JCS bytes of ``trace``."""
    return hashlib.sha256(serialize_bridge_diff_trace(trace)).hexdigest()


def bridge_diff_trace_hash_prefixed(trace: BridgeDiffTrace) -> str:
    """Prefixed outer hash: ``"sha256:" + bridge_diff_trace_sha256_hex``."""
    return HASH_PREFIX + bridge_diff_trace_sha256_hex(trace)


# ---------------------------------------------------------------------------
# Re-exports for downstream importers that want one-stop access.
# ---------------------------------------------------------------------------

__all__ = [
    "BRIDGE_DIFF_TRACE_SCHEMA",
    "BridgeDiffTrace",
    "DIFF_KIND_VALUES",
    "HASH_PREFIX",
    "KIND_ONLY_IN_A",
    "KIND_ONLY_IN_B",
    "KIND_TYPE_MISMATCH",
    "KIND_VALUE_MISMATCH",
    "SHA256_HEX_LEN",
    "SUMMARY_ENTRY_SEP",
    "SUMMARY_PATH_KIND_SEP",
    "bridge_diff_trace_hash_prefixed",
    "bridge_diff_trace_sha256_hex",
    "build_bridge_diff_trace",
    "build_trace_from_report",
    "serialize_bridge_diff_trace",
]
