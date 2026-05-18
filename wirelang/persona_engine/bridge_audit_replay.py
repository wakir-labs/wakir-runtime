# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-audit stream-replay engine (Tag-37 Phase-3a 14. Modul).

This module is the **Python sibling** of the Rust crate
``persona-engine-bridge-audit-replay`` (PR #205 / ADR-0063 §Folgeartefakte
Phase-3a Item 11).  Where the live Python writer
:mod:`wirelang.persona_engine.bridge_audit_writer` records one
``EngineeringOutputEvent`` per emission, the replay engine ingests an
ORDERED STREAM of such events and validates the sequence against an
expected trajectory.  It surfaces the FIRST drifting step plus a
list of all subsequent divergence entries.

Layer vs. ``bridge_audit_diff_engine``
--------------------------------------

- :mod:`wirelang.persona_engine.bridge_audit_diff_engine` — single
  envelope oracle (A vs. B, one envelope per side).
- This module — stream-level oracle (ordered sequences of envelopes;
  first-divergence semantics, time-to-divergence telemetry).

The two layers share the same ``jcs_hash`` primitive (delegated to
:func:`wirelang.persona_engine.bridge_audit_diff_engine.jcs_hash`) so
the canonicalisation contract is identical and the cross-lang anchor
pins live in one place.

Cross-language pin
------------------

Stream-fixture hashes are pinned byte-for-byte against the Rust
pendant ``persona_engine_bridge_audit_replay::stream_hash`` and
``ReplayEngine::replay_stream``.  See the fixture file
``tests/fixtures/bridge-audit-replay-cross-lang/fixtures.json`` and
its sibling tests:

- Python: ``wirelang/tests/persona_engine/test_bridge_audit_replay_cross_lang_parity.py``
- Rust:   ``wirelang-rust/crates/persona-engine-bridge-audit-replay/tests/cross_lang_replay_trace_fixture_test.rs``

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item 11 (this crate / sibling).
- ADR-0066 — Welle-3 Konsistenz-Oracle-Selbst-Cutover closure
  (replay leg, completing the bridge-audit trilogy:
  writer / diff-engine / replay).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Sequence

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffKind,
    FieldDiff,
    diff_envelopes,
    jcs_hash,
)
from wirelang.persona_engine.bridge_audit_writer import (
    ENGINEERING_OUTPUT_SCHEMA,
    EngineeringOutputEvent,
)


#: Constant event-kind tag matching the Rust crate (`EVENT_KIND`).
EVENT_KIND: Final[str] = "engineering_output"


# ---------------------------------------------------------------------------
# AuditRecord — flat dataclass, byte-identical envelope shape to the
# Rust pendant `persona_engine_bridge_audit_replay::AuditRecord`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditRecord:
    """One Bridge-Audit record in a replay stream.

    Mirrors :class:`wirelang.persona_engine.bridge_audit_writer.
    EngineeringOutputEvent` field-for-field, but adds the
    :meth:`to_envelope` and :meth:`jcs_hash` helpers needed for the
    replay engine to operate on a flat dataclass without re-importing
    the writer's BUSL surface.
    """

    org_id: str
    persona_id: str
    session_id: str
    step_index: int
    output_kind: str  # "tool_call" | "reply" | "audit_annotation"
    output_payload_sha256: str  # "sha256:<64hex>"
    engine_version: str
    v907_pin: str  # "sha256:<64hex>"
    ts_utc: str  # RFC 3339 UTC second-precision

    def to_envelope(self) -> dict[str, Any]:
        """Return the canonical 11-key envelope dict.

        Keys are emitted in alphabetical insertion order to match the
        Rust pendant `AuditRecord::to_envelope`; the JCS canonicaliser
        re-sorts lexicographically so insertion order has no effect on
        the resulting bytes, but source-level reviews diff cleanly.
        """
        return {
            "engine_version": self.engine_version,
            "event_kind": EVENT_KIND,
            "org_id": self.org_id,
            "output_kind": self.output_kind,
            "output_payload_sha256": self.output_payload_sha256,
            "persona_id": self.persona_id,
            "schema": ENGINEERING_OUTPUT_SCHEMA,
            "session_id": self.session_id,
            "step_index": int(self.step_index),
            "ts_utc": self.ts_utc,
            "v907_pin": self.v907_pin,
        }

    def jcs_hash(self) -> str:
        """JCS-hash this record's canonical envelope.

        Returns ``"sha256:<64hex>"`` — byte-identical to the Rust
        pendant `AuditRecord::jcs_hash`.
        """
        return jcs_hash(self.to_envelope())

    @classmethod
    def from_writer_event(cls, evt: EngineeringOutputEvent) -> "AuditRecord":
        """Construct an :class:`AuditRecord` from an :class:`EngineeringOutputEvent`.

        Field-for-field copy so callers that already have a writer
        event (Doppelbetrieb-Shadow capture path) can replay it without
        re-typing the constructor.
        """
        return cls(
            org_id=evt.org_id,
            persona_id=evt.persona_id,
            session_id=evt.session_id,
            step_index=int(evt.step_index),
            output_kind=evt.output_kind,
            output_payload_sha256=evt.output_payload_sha256,
            engine_version=evt.engine_version,
            v907_pin=evt.v907_pin,
            ts_utc=evt.ts_utc,
        )


# ---------------------------------------------------------------------------
# DivergenceKind — wire-stable string alphabet, byte-identical to the
# Rust pendant `DivergenceKind::as_str`.
# ---------------------------------------------------------------------------


class DivergenceKind(str, Enum):
    """Stream-level divergence classification.

    Three kinds, lower-case-hyphen wire form, byte-identical to the
    Rust `DivergenceKind::as_str` pendant.
    """

    VALUE_MISMATCH = "value-mismatch"
    MISSING_IN_ACTUAL = "missing-in-actual"
    EXTRA_IN_ACTUAL = "extra-in-actual"


# ---------------------------------------------------------------------------
# ExpectedTrajectory.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedTrajectory:
    """The expected sequence of audit records for a replay.

    Newtype around ``tuple[AuditRecord, ...]`` so the engine can grow
    trajectory-level metadata (per-step assertions, tolerances) without
    breaking the call signature.
    """

    records: tuple[AuditRecord, ...] = field(default_factory=tuple)

    @classmethod
    def from_records(cls, records: Sequence[AuditRecord]) -> "ExpectedTrajectory":
        """Convenience constructor — copy the input into a tuple."""
        return cls(records=tuple(records))

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.records)

    def is_empty(self) -> bool:
        """``True`` iff the trajectory has no expected records."""
        return len(self.records) == 0


# ---------------------------------------------------------------------------
# Divergence + ReplayReport.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Divergence:
    """One stream-level divergence entry."""

    step_index: int
    kind: DivergenceKind
    expected: AuditRecord | None  # None iff kind == EXTRA_IN_ACTUAL
    actual: AuditRecord | None  # None iff kind == MISSING_IN_ACTUAL
    expected_hash: str | None
    actual_hash: str | None
    field_diffs: tuple[FieldDiff, ...] = ()


@dataclass(frozen=True)
class ReplayReport:
    """Outcome of one stream-replay run."""

    success: bool
    actual_record_count: int
    expected_record_count: int
    time_to_divergence_steps: int | None
    divergences: tuple[Divergence, ...]
    stream_hash_actual: str
    stream_hash_expected: str

    def has_divergence(self) -> bool:
        """``True`` iff at least one divergence was recorded."""
        return not self.success

    def summary(self) -> str:
        """One-line operator-readable summary; parity with Rust pendant."""
        if self.success:
            return (
                f"replay-ok records={self.actual_record_count} "
                f"stream_hash={self.stream_hash_actual}"
            )
        first_step = (
            "-"
            if self.time_to_divergence_steps is None
            else str(self.time_to_divergence_steps)
        )
        return (
            f"replay-drift first_step={first_step} "
            f"divergences={len(self.divergences)} "
            f"actual_hash={self.stream_hash_actual} "
            f"expected_hash={self.stream_hash_expected}"
        )


# ---------------------------------------------------------------------------
# Stream hash helper.
# ---------------------------------------------------------------------------


def _build_stream_envelope(records: Sequence[AuditRecord]) -> dict[str, Any]:
    """Build the canonical stream envelope.

    Wraps the record envelopes in ``{"stream": [...], "stream_len": <n>}``
    so the hash discriminates empty streams from missing-stream inputs
    and resists silent truncation in transit.  Byte-identical to the
    Rust pendant `build_stream_envelope`.
    """
    arr = [r.to_envelope() for r in records]
    return {"stream": arr, "stream_len": len(arr)}


def stream_hash(records: Sequence[AuditRecord]) -> str:
    """JCS-hash a record stream.

    Returns ``"sha256:<64hex>"``.  Byte-identical to the Rust pendant
    :func:`persona_engine_bridge_audit_replay::stream_hash`.
    """
    return jcs_hash(_build_stream_envelope(records))


# ---------------------------------------------------------------------------
# ReplayEngine.
# ---------------------------------------------------------------------------


class ReplayEngine:
    """Deterministic stream-replay engine.

    Stateless: :meth:`replay_stream` is a pure function of its
    arguments.  Modelled as a class (rather than a bare function) so
    future configuration knobs attach to a typed handle rather than
    growing the call signature.  Parity with the Rust pendant.
    """

    def replay_stream(
        self,
        actual: Sequence[AuditRecord],
        expected: ExpectedTrajectory,
    ) -> ReplayReport:
        """Replay an actual record sequence against ``expected``.

        Algorithm (byte-identical to the Rust pendant):

        1. Hash both streams (`stream_hash`).
        2. If the hashes match -> early-return success.
        3. Walk both streams pairwise up to ``max(len(actual), len(expected))``.
           Per step emit a :class:`Divergence` with the appropriate kind.
        4. ``time_to_divergence_steps`` is the first divergence's step
           index.
        """
        sh_actual = stream_hash(actual)
        sh_expected = stream_hash(expected.records)

        if sh_actual == sh_expected:
            return ReplayReport(
                success=True,
                actual_record_count=len(actual),
                expected_record_count=len(expected.records),
                time_to_divergence_steps=None,
                divergences=(),
                stream_hash_actual=sh_actual,
                stream_hash_expected=sh_expected,
            )

        max_len = max(len(actual), len(expected.records))
        divergences: list[Divergence] = []

        for i in range(max_len):
            act = actual[i] if i < len(actual) else None
            exp = expected.records[i] if i < len(expected.records) else None

            if act is not None and exp is not None:
                a_hash = act.jcs_hash()
                e_hash = exp.jcs_hash()
                if a_hash != e_hash:
                    a_env = act.to_envelope()
                    e_env = exp.to_envelope()
                    # diff_envelopes(a=actual, b=expected) -> only-in-a ==
                    # only-in-actual; only-in-b == only-in-expected
                    fdiffs = tuple(diff_envelopes(a_env, e_env))
                    divergences.append(
                        Divergence(
                            step_index=i,
                            kind=DivergenceKind.VALUE_MISMATCH,
                            expected=exp,
                            actual=act,
                            expected_hash=e_hash,
                            actual_hash=a_hash,
                            field_diffs=fdiffs,
                        )
                    )
            elif act is not None and exp is None:
                a_hash = act.jcs_hash()
                divergences.append(
                    Divergence(
                        step_index=i,
                        kind=DivergenceKind.EXTRA_IN_ACTUAL,
                        expected=None,
                        actual=act,
                        expected_hash=None,
                        actual_hash=a_hash,
                        field_diffs=(),
                    )
                )
            elif act is None and exp is not None:
                e_hash = exp.jcs_hash()
                divergences.append(
                    Divergence(
                        step_index=i,
                        kind=DivergenceKind.MISSING_IN_ACTUAL,
                        expected=exp,
                        actual=None,
                        expected_hash=e_hash,
                        actual_hash=None,
                        field_diffs=(),
                    )
                )
            else:  # pragma: no cover - unreachable: loop bound is max
                break

        first_step = divergences[0].step_index if divergences else None
        success = len(divergences) == 0

        return ReplayReport(
            success=success,
            actual_record_count=len(actual),
            expected_record_count=len(expected.records),
            time_to_divergence_steps=first_step,
            divergences=tuple(divergences),
            stream_hash_actual=sh_actual,
            stream_hash_expected=sh_expected,
        )


# ---------------------------------------------------------------------------
# Re-exports.
# ---------------------------------------------------------------------------


__all__ = [
    "AuditRecord",
    "Divergence",
    "DivergenceKind",
    "ENGINEERING_OUTPUT_SCHEMA",
    "EVENT_KIND",
    "ExpectedTrajectory",
    "ReplayEngine",
    "ReplayReport",
    "stream_hash",
]
