# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""3-Way-Mode bridge-audit cross-check triangle.

Sprint-Pengine-15-Folge (ADR-0063 §Folgeartefakte Item 3, follow-on to
PR #106 Item 2 — the Deterministic-Diff-Engine).

PR #106 shipped the pairwise diff-engine: given two CloudEvent envelopes
from two implementations against the same logical input, produce a
:class:`DiffReport`. That covers the Phase-2 Doppelbetrieb-Shadow
window where the **Pre-Framework Markdown sink** and the
**Wakir-Runtime structured-log sink** are the two outputs the operator
trusts pairwise.

Phase-3a (KW 27-31) introduces a **third sink**: the Rust persona-
engine. The Rust engine is being built in parallel (``wirelang-rust``
crates) and the cutover gate requires that **all three outputs agree
byte-for-byte** for every emission, not just one pairwise comparison.

This module wraps the pairwise diff-engine into a **triangle cross-
check**: given three implementations A (Pre-Framework / Python markdown
sink projection), B (Wakir-Runtime / Python structured-log sink), and
C (Rust-engine-stub for Phase-3a), the triangle compares all three
pairs (A↔B, B↔C, A↔C) and emits a single :class:`TriangleReport` that
collapses to ``all_consistent=True`` only when every pair is byte-
identical.

ENV-var contract
----------------

``WAKIR_BRIDGE_MODE`` (default ``"2way"``):

- ``"2way"`` — Phase-2 behaviour: only Pre-Framework + Wakir-Runtime
  sinks are written. The Rust-engine adapter is NOT invoked. The
  diff-engine compares A↔B and the operator-facing report degenerates
  to a pairwise :class:`DiffReport`.
- ``"3way"`` — Phase-3a behaviour: the Rust-engine adapter is invoked
  alongside the two Python sinks. The triangle cross-check runs over
  all three pairs. A single drift in any pair fails the consistency
  gate.

The default is ``"2way"`` so existing Phase-2 deployments are
untouched. Operators opt into 3-way mode by setting the env-var on
the Quadlet unit ahead of the Phase-3a cutover dry-run.

Rust-engine-stub semantics
--------------------------

The Phase-3a Rust persona-engine is still in flight. The 3rd-sink
adapter shipped here is a **stub** with a documented placeholder API:

- :func:`default_rust_engine_stub` produces a CloudEvent envelope by
  delegating to the same canonical projection the Python writer uses.
  By construction it is byte-identical to the Python writer's
  projection — so the triangle reports ``all_consistent=True`` for the
  stub.
- Production callers swap in a real adapter that subprocess-invokes
  the Rust binary (or links via PyO3 once the ``wirelang-rust``
  ``persona-engine`` crate ships its FFI surface). The adapter
  contract is the same :class:`Implementation` protocol the pairwise
  diff-engine already takes.

This separation lets us land the triangle infrastructure now and swap
the Rust adapter in without touching the bridge-audit writer or the
test surface — the stub is the test-pinned baseline.

Cross-check contract
--------------------

The triangle is **all-pairs**, not chained: A↔B, B↔C, A↔C are
independently computed. This catches the pathological case where two
pairs agree but the third disagrees (transitivity failure — possible
if one implementation has a non-deterministic field that happens to
match one peer but not the other). The triangle ``all_consistent``
flag is ``True`` iff every pair reports ``byte_identical``.

Schema-version drift
--------------------

When the projection schema version differs between adapters
(e.g. ``"wakir.persona.engineering-output/1"`` vs ``".../2"``), the
``/schema`` field surfaces as a ``VALUE_MISMATCH`` in the relevant
pairwise diff. The triangle bubbles this up via
:attr:`TriangleReport.schema_version_drift` so operators see schema-
evolution drift independently of payload drift.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

from .bridge_audit_diff_engine import (
    CloudEventEnvelope,
    DiffInput,
    DiffKind,
    DiffReport,
    FieldDiff,
    Implementation,
    canonicalize_envelope,
    compare_implementations,
    jcs_hash,
)
from .bridge_audit_writer import ENGINEERING_OUTPUT_SCHEMA, sha256_hex


__all__ = [
    "BridgeMode",
    "BRIDGE_MODE_ENV",
    "DEFAULT_BRIDGE_MODE",
    "TriangleReport",
    "default_rust_engine_stub",
    "default_python_markdown_projection",
    "default_python_structured_projection",
    "resolve_bridge_mode",
    "cross_check_triangle",
]


# ---------------------------------------------------------------------------
# Mode contract
# ---------------------------------------------------------------------------


BRIDGE_MODE_ENV = "WAKIR_BRIDGE_MODE"


class BridgeMode:
    """Closed string enum for bridge-audit mode.

    Plain string values (not :class:`enum.Enum`) so the Quadlet env-var
    pass-through stays human-grep-able and the JSON-serialised
    :class:`TriangleReport` round-trips cleanly.
    """

    TWO_WAY = "2way"
    THREE_WAY = "3way"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return (cls.TWO_WAY, cls.THREE_WAY)


DEFAULT_BRIDGE_MODE = BridgeMode.TWO_WAY


def resolve_bridge_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """Resolve the active bridge-mode string from ``env`` (default ``os.environ``).

    Unknown values raise :class:`ValueError` — the bridge-audit writer
    is a load-bearing audit substrate; a typo in the Quadlet env-var
    must NOT silently degrade to 2-way mode.
    """
    if env is None:
        env = os.environ
    raw = env.get(BRIDGE_MODE_ENV, DEFAULT_BRIDGE_MODE)
    if raw not in BridgeMode.values():
        raise ValueError(
            f"unknown {BRIDGE_MODE_ENV}={raw!r}; "
            f"valid: {BridgeMode.values()}"
        )
    return raw


# ---------------------------------------------------------------------------
# Default adapters (Implementation protocol)
# ---------------------------------------------------------------------------


def _canonical_engineering_output_envelope(
    input_: DiffInput,
    *,
    engine_version: str,
    v907_pin: str,
    schema: str = ENGINEERING_OUTPUT_SCHEMA,
) -> CloudEventEnvelope:
    """Reference canonical CloudEvent envelope for an engineering-output emission.

    This is the **projection contract** all three adapters target. Both
    Python sinks (markdown + structured-log) derive their projections
    from this shape; the Rust-engine-stub mirrors the same shape. By
    construction the triangle then collapses to byte-identical.
    """
    return {
        "engine_version": engine_version,
        "event_kind": "engineering_output",
        "org_id": input_.org_id,
        "output_kind": input_.output_kind,
        "output_payload_sha256": sha256_hex(input_.payload),
        "persona_id": input_.persona_id,
        "schema": schema,
        "session_id": input_.session_id,
        "step_index": input_.step_index,
        "ts_utc": input_.ts_utc,
        "v907_pin": v907_pin,
    }


def default_python_markdown_projection(
    *,
    engine_version: str = "0.2.0-pilot",
    v907_pin: str = "sha256:" + "a" * 64,
) -> Implementation:
    """Adapter for the Python Pre-Framework Markdown sink projection.

    The Pre-Framework Markdown sink stores envelopes as JCS-canonical
    JSON inside fenced code blocks (see
    :meth:`BridgeAuditWriter._write_preframework_sink`). The diff-engine
    only sees the JSON projection — the surrounding Markdown is operator-
    substrate and not part of the comparison.
    """

    def _impl(input_: DiffInput) -> CloudEventEnvelope:
        return _canonical_engineering_output_envelope(
            input_,
            engine_version=engine_version,
            v907_pin=v907_pin,
        )

    return _impl


def default_python_structured_projection(
    *,
    engine_version: str = "0.2.0-pilot",
    v907_pin: str = "sha256:" + "a" * 64,
) -> Implementation:
    """Adapter for the Python Wakir-Runtime structured-log sink projection.

    The structured-log sink emits one JCS-canonical JSON line per
    emission to stderr (which ``podman logs`` collects). Same canonical
    shape as the Markdown sink — by writer construction, see
    :meth:`BridgeAuditWriter._write_wakir_runtime_sink`.
    """

    def _impl(input_: DiffInput) -> CloudEventEnvelope:
        return _canonical_engineering_output_envelope(
            input_,
            engine_version=engine_version,
            v907_pin=v907_pin,
        )

    return _impl


def default_rust_engine_stub(
    *,
    engine_version: str = "0.2.0-pilot-rust-stub",
    v907_pin: str = "sha256:" + "a" * 64,
) -> Implementation:
    """Placeholder adapter for the Phase-3a Rust persona-engine.

    The Rust persona-engine (``wirelang-rust/crates/persona-engine-*``)
    is still being built. This stub returns a CloudEvent envelope that
    is **byte-identical** to the Python sinks' projection — that is the
    Phase-3a cutover contract: the Rust engine MUST emit envelopes
    that match the Python engine for the same input.

    Production callers swap this stub for a subprocess-invocation
    adapter once the Rust binary ships:

    .. code-block:: python

        def rust_engine_adapter(input_: DiffInput) -> CloudEventEnvelope:
            proc = subprocess.run(
                ["wakir-rust-persona-engine", "emit", "--json"],
                input=json.dumps(input_._asdict()).encode("utf-8"),
                capture_output=True,
                check=True,
            )
            return json.loads(proc.stdout)

    The stub keeps the default ``engine_version`` distinct (suffixed
    ``-rust-stub``) so test fixtures can detect that the stub — not a
    real Rust engine — produced the envelope. Production swaps the
    suffix off via the constructor parameter.

    Note the ``engine_version`` value will surface as a drift entry
    when compared with the Python sinks unless the caller overrides it
    to match. Tests that exercise byte-identical behaviour pass
    ``engine_version="0.2.0-pilot"`` (matching the Python default).
    """

    def _impl(input_: DiffInput) -> CloudEventEnvelope:
        return _canonical_engineering_output_envelope(
            input_,
            engine_version=engine_version,
            v907_pin=v907_pin,
        )

    return _impl


# ---------------------------------------------------------------------------
# Triangle report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriangleReport:
    """Outcome of a 3-way cross-check.

    All three pairwise :class:`DiffReport` instances are retained so
    operators can drill into any specific drift edge. The triangle's
    own boolean ``all_consistent`` is the only-true-if-every-pair-true
    AND-fold across the three reports.

    Attributes
    ----------
    mode
        The :class:`BridgeMode` string under which the triangle was run.
        ``"2way"`` ⇒ ``report_bc`` and ``report_ac`` are ``None`` and
        the triangle degrades to a pairwise comparison.
    all_consistent
        ``True`` iff every populated pairwise report is byte-identical.
        In 2-way mode this equals ``report_ab.byte_identical``.
    report_ab, report_bc, report_ac
        Pairwise :class:`DiffReport` instances. ``report_bc`` and
        ``report_ac`` are ``None`` in 2-way mode.
    schema_version_drift
        ``True`` iff any pairwise diff contains a non-empty
        ``/schema`` field-diff entry — surfaces schema-version
        evolution drift independently of payload drift.
    """

    mode: str
    all_consistent: bool
    report_ab: DiffReport
    report_bc: Optional[DiffReport]
    report_ac: Optional[DiffReport]
    schema_version_drift: bool

    def pairwise_reports(self) -> Tuple[DiffReport, ...]:
        """Return all populated pairwise reports (1 in 2-way, 3 in 3-way)."""
        if self.mode == BridgeMode.TWO_WAY:
            return (self.report_ab,)
        # Defensive: in well-formed 3-way reports both follow-on
        # reports are populated. The Optional typing is for the 2-way
        # degenerate case only.
        assert self.report_bc is not None
        assert self.report_ac is not None
        return (self.report_ab, self.report_bc, self.report_ac)

    def summary(self) -> str:
        """One-line operator-readable summary."""
        if self.mode == BridgeMode.TWO_WAY:
            return f"2way {self.report_ab.summary()}"
        if self.all_consistent:
            return (
                f"3way all-consistent jcs={self.report_ab.jcs_hash_a}"
            )
        drifted = sum(1 for r in self.pairwise_reports() if r.has_drift())
        return (
            f"3way drift edges={drifted}/3 "
            f"schema_drift={self.schema_version_drift} "
            f"score_ab={self.report_ab.consistency_score:.4f}"
        )


# ---------------------------------------------------------------------------
# Cross-check entry point
# ---------------------------------------------------------------------------


def _diff_has_schema_drift(report: DiffReport) -> bool:
    """Return True iff the report contains a ``/schema`` field-diff."""
    for fd in report.field_diffs:
        if fd.path == "/schema":
            return True
    return False


def cross_check_triangle(
    input_: DiffInput,
    *,
    impl_a: Implementation,
    impl_b: Implementation,
    impl_c: Optional[Implementation] = None,
    mode: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> TriangleReport:
    """Run a 2-way or 3-way cross-check over the three implementations.

    Mode resolution:

    1. If ``mode`` is explicit (caller-pinned), use it verbatim.
    2. Otherwise, resolve from ``env`` (defaults to :data:`os.environ`)
       via :func:`resolve_bridge_mode`.

    In 3-way mode, ``impl_c`` MUST be provided; a missing 3rd adapter
    raises :class:`ValueError`. In 2-way mode, ``impl_c`` is ignored
    (but accepted — operators can pre-bind all three adapters and let
    the env-var pick the mode).

    The function is pure: it does not write to either sink. Bridge-
    audit-writer-side integration calls this and then conditionally
    fails the emission (or writes a drift annotation) based on
    :attr:`TriangleReport.all_consistent`.
    """
    effective_mode = mode if mode is not None else resolve_bridge_mode(env)
    if effective_mode not in BridgeMode.values():
        raise ValueError(
            f"unknown mode {effective_mode!r}; "
            f"valid: {BridgeMode.values()}"
        )

    report_ab = compare_implementations(input_, impl_a, impl_b)

    if effective_mode == BridgeMode.TWO_WAY:
        return TriangleReport(
            mode=effective_mode,
            all_consistent=report_ab.byte_identical,
            report_ab=report_ab,
            report_bc=None,
            report_ac=None,
            schema_version_drift=_diff_has_schema_drift(report_ab),
        )

    # 3-way mode below this line.
    if impl_c is None:
        raise ValueError(
            "3way mode requires impl_c (the Rust-engine adapter)"
        )

    report_bc = compare_implementations(input_, impl_b, impl_c)
    report_ac = compare_implementations(input_, impl_a, impl_c)
    all_consistent = (
        report_ab.byte_identical
        and report_bc.byte_identical
        and report_ac.byte_identical
    )
    schema_drift = (
        _diff_has_schema_drift(report_ab)
        or _diff_has_schema_drift(report_bc)
        or _diff_has_schema_drift(report_ac)
    )
    return TriangleReport(
        mode=effective_mode,
        all_consistent=all_consistent,
        report_ab=report_ab,
        report_bc=report_bc,
        report_ac=report_ac,
        schema_version_drift=schema_drift,
    )
