# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Shared fixtures + opt-in gate for the Phase-3c End-to-End Rollback-
Drill SLA-Verifikations-Suite.

Anchors
-------

- ADR-0065 §Rollback-Strategie — ENV-Flag-Switch ≤10min SLA pro
  Komponente; Bridge-Audit-Writer-Konsistenz-Re-Verify post-rollback;
  Postmortem-Pflicht.
- ADR-0066 §Rollback — Doppel-Welle-Rollback-Kompatibilität (gleicher
  10min SLA pro Komponente, sequential application).
- ``tests/acceptance/phase_3c/conftest.py`` (Amara, PR series) — the
  parent fixture-set providing ``WELLE_ORDER``, the existing record
  dataclasses (``BackendDecisionRecord``,
  ``SingleKomponenteRollbackRecord``), and the per-welle oracle
  builders. This sub-conftest extends — not replaces — that surface.
- ``tests/acceptance/phase_3c/_ac_assertions.py`` (Amara, PR series) —
  the ``ROLLBACK_SLA_SECONDS = 600.0`` constant and ``DW-AC-3``
  asymmetric-rollback assertion-helper. Both are imported here.

Scope
-----

The drill-suite verifies, per Phase-3c-Komponente, the four RD-1...
RD-4 acceptance-criteria:

* **RD-1** — ENV-Flag-Switch ``rust → python`` has a behavioural
  effect on the engine-boot-record. The Quadlet-ENV-state moves the
  flipped modul from ``rust`` to ``python`` and the engine reflects
  the change at next boot.
* **RD-2** — Backend-Decision-Audit emits a record documenting the
  rollback event: ``target_backend == "python"``, modul name correct,
  operator-actor populated, cutover-cycle-id present.
* **RD-3** — Cross-Modul-Konsistenz post-rollback green (mocked
  Phase-2-Acceptance-Gate). The rollback must not leave the system
  in a cross-modul-drift state (Phase-2 acceptance-gate, ADR-0066
  §Mitigation 1, must pass after the rollback completes).
* **RD-4** — Time-to-rollback ≤10min SLA (mocked-clock). The ENV-Flag-
  Switch elapsed-seconds must be ≤``ROLLBACK_SLA_SECONDS`` (600.0s).

The nine drill-files (one per Phase-3c-Komponente) each carry these
four tests, modulwise-parametrised through the ``PHASE_3C_COMPONENTS``
inventory below.

Component inventory
-------------------

Phase-3c-Komponenten covered by this drill-suite:

1. ``v907_verify`` (ADR-0065 §Verifikations-Plan Welle-1)
2. ``svid_workload_identity`` (Welle-2)
3. ``bridge_audit_writer`` (Welle-3, Henrik-Caution-Carve-out)
4. ``state_backing`` (Welle-4)
5. ``lifecycle_state_machine`` (Welle-5)
6. ``subscribe_loop`` (Welle-6)
7. ``recovery_workflow`` (Welle-7)
8. ``anchor_emitter`` (additional Phase-3c-Komponente; Bridge-side
   anchor-fan-out, see ``wakir-runtime`` PR series Tag-18+).
9. ``federation_resolver`` (additional Phase-3c-Komponente; cross-
   org-name resolution, see ``wakir-runtime`` PR series Tag-14+).

Components 1...7 mirror the ADR-0065 §Verifikations-Plan welle-list.
Components 8 + 9 are the two non-welle Phase-3c-cutover-surfaces that
the SLA-verification must also cover (ENV-Flag-Switch substrate
identical, rollback contract identical).

Opt-in gate
-----------

Two independent opt-in paths (parallel to the per-welle and Doppel-
Welle skeletons):

1. ``pytest --rollback-drill`` — explicit CLI flag.
2. ``WAKIR_PHASE_3C_ROLLBACK_DRILL=1`` — env-var.

Either path enables the suite; module-level ``pytestmark =
pytest.mark.phase_3c_rollback_drill`` in each drill-file consults
both. The suite is **skip-by-default** to keep CI lean during the
pre-cutover steady-state; the drill is intended to be exercised on
each cutover-week and post-rollback-event.

Sandbox boundary
----------------

Hermetic-only. No podman, no live ``systemctl restart wakir-persona-
engine``, no live ENV-rewrite on a host. The ENV-Flag-Switch substrate
is captured as a ``RollbackEvent`` dataclass with a mocked-clock
timestamp pair (pre/post-switch). Phase-3c-trigger-sprint replaces
the mock with the real Operator-Hand-runbook drill output.

Vermutungs-Kennzeichnung (P2)
-----------------------------

* The ``ROLLBACK_SLA_SECONDS = 600.0`` constant is ADR-0065/-0066-
  fixed (10min ENV-Flag-Switch); the Welle-4-specific 2-Stunden
  Schema-Migrations-Rollback drill is *not* covered here (separate
  Reza-Folge-Spawn-Artefakt per ADR-0065 §Folgeartefakte 3).
* The ``mocked_phase_2_acceptance_gate`` fixture emits a
  green-by-construction Phase-2-Acceptance-Gate record (RD-3
  oracle). The Phase-3c-trigger-sprint wires this against the real
  Tomás Tag-29 Cross-Modul-Stress-Test substrate output.
* Operator-actor-string ``operator-hand-rollback-runbook`` is a
  placeholder anchor; sprint-time wiring replaces with the actual
  ``operator/<handle>`` field from the Quadlet-ENV-rewrite tooling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import pytest

from tests.acceptance.phase_3c.conftest import (
    BackendDecisionRecord,
    SingleKomponenteRollbackRecord,
    WELLE_ORDER,
)


# ---------------------------------------------------------------------------
# Opt-in gate.
# ---------------------------------------------------------------------------

ROLLBACK_DRILL_OPT_IN_ENV = "WAKIR_PHASE_3C_ROLLBACK_DRILL"
ROLLBACK_DRILL_OPT_IN = os.environ.get(ROLLBACK_DRILL_OPT_IN_ENV) == "1"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--rollback-drill`` opt-in CLI flag.

    Two independent opt-in paths:

    1. ``pytest --rollback-drill``
    2. ``WAKIR_PHASE_3C_ROLLBACK_DRILL=1``

    The skeleton stays skip-by-default in both cases unless one path
    is active. Either flag turns the gate green together; both flags
    together is idempotent.
    """
    group = parser.getgroup(
        "wakir-phase-3c-rollback-drill",
        "Wakir Phase-3c Rollback-Drill SLA-Verification",
    )
    group.addoption(
        "--rollback-drill",
        action="store_true",
        default=False,
        help=(
            "Enable Phase-3c Rollback-Drill SLA-verification suite "
            "(skip-by-default; opt-in for cutover-week + post-rollback-"
            "event drills per ADR-0065 §Rollback-Strategie)."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip ``phase_3c_rollback_drill``-marked tests unless opt-in.

    Mirrors the per-welle and Doppel-Welle opt-in patterns: collection-
    time skip-marker so default CI runs see a clean fast-skip without
    fixture-evaluation surprises.
    """
    if config.getoption("--rollback-drill") or ROLLBACK_DRILL_OPT_IN:
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "Phase-3c Rollback-Drill skeleton skip-by-default — opt in "
            "with WAKIR_PHASE_3C_ROLLBACK_DRILL=1 env-var or "
            "--rollback-drill CLI flag (cutover-week + post-rollback-"
            "event drill per ADR-0065 §Rollback-Strategie)."
        )
    )
    for item in items:
        if "phase_3c_rollback_drill" in item.keywords:
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Phase-3c-Component inventory — anchors the nine rollback-drill files.
# ---------------------------------------------------------------------------

#: All Phase-3c-Komponenten covered by the rollback-drill suite.
#:
#: Tuples 1...7 mirror ``WELLE_ORDER`` from the parent conftest (the
#: ADR-0065 §Verifikations-Plan welle-sequence). Tuples 8 + 9 are the
#: two additional Phase-3c-Komponenten that share the same ENV-Flag-
#: Switch rollback substrate but are not part of the seven-welle
#: cutover sequence:
#:
#: * ``anchor_emitter`` — Bridge-side anchor-fan-out surface (PR series
#:   wakir-runtime Tag-18+).
#: * ``federation_resolver`` — cross-org-name resolution surface
#:   (PR series wakir-runtime Tag-14+).
#:
#: Both share ``WAKIR_ENGINE_<MODUL>_BACKEND`` flag semantics with the
#: seven welle-Komponenten and are therefore drill-eligible.
PHASE_3C_COMPONENTS: tuple[str, ...] = tuple(
    modul for _, modul in WELLE_ORDER
) + (
    "anchor_emitter",
    "federation_resolver",
)


# ---------------------------------------------------------------------------
# Rollback-event mock — RD-1, RD-2, RD-4 oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RollbackEvent:
    """One ENV-Flag-Switch rollback-event record.

    Captures the pre/post-switch ENV-state of the affected modul, the
    elapsed-seconds of the switch operation (mocked clock), the
    associated Backend-Decision-Audit-Record (the rollback flip emits
    its own audit entry), and a Bridge-Audit-Writer re-verify hash
    that ADR-0065 §Rollback-Strategie step 4 requires.

    Fields:
        modul: The Phase-3c-Komponente that was rolled back.
        pre_switch_backend: ENV-state before the switch (expected
            ``"rust"`` on a real rollback).
        post_switch_backend: ENV-state after the switch (expected
            ``"python"`` on a real rollback).
        elapsed_seconds: Wall-clock from ``systemctl restart``-start
            to engine-boot-complete (mocked).
        audit_record: The single Backend-Decision-Audit-Record the
            engine emitted on the rollback boot.
        bridge_audit_re_verify_ok: Whether the post-rollback Bridge-
            Audit-Writer-Konsistenz-Re-Verify (ADR-0065 §Rollback-
            Strategie step 4) returned consistent.
    """

    modul: str
    pre_switch_backend: str
    post_switch_backend: str
    elapsed_seconds: float
    audit_record: BackendDecisionRecord
    bridge_audit_re_verify_ok: bool


@pytest.fixture
def mocked_rollback_event() -> Callable[..., RollbackEvent]:
    """Fixture returning a ``RollbackEvent``-builder.

    Default builder produces a successful rollback-event for the given
    ``modul``:

    * ``pre_switch_backend = "rust"`` → ``post_switch_backend = "python"``.
    * ``elapsed_seconds = 240.0`` (4 minutes, well inside the 600s SLA).
    * Audit-record ``target_backend = "python"`` (rollback-flip).
    * Bridge-Audit-Writer-Re-Verify ok.

    Drill-tests inject failure-modes:

    * ``elapsed_seconds=700.0`` — SLA-violation (RD-4 failure-shape).
    * ``post_switch_backend="rust"`` — switch had no effect (RD-1
      failure-shape).
    * ``audit_target="rust"`` — audit-record mis-targets the rollback
      direction (RD-2 failure-shape).
    * ``bridge_audit_re_verify_ok=False`` — cross-modul-konsistenz
      broken post-rollback (RD-3 contributor, also flagged separately
      by ``mocked_phase_2_acceptance_gate``).
    * ``missing_audit=True`` — engine emitted no audit-record on the
      rollback boot (RD-2 failure-shape; rare but Henrik-Audit-relevant).

    The mocked-clock substrate is deliberately coarse (the fixture
    accepts an ``elapsed_seconds`` float directly) — the Phase-3c-
    trigger-sprint wires this against the real Quadlet-restart elapsed-
    seconds measured by Noa-Prometheus-Gauges in the
    ``operator-hand-rollback-runbook`` lane.
    """

    def _build(
        modul: str,
        pre_switch_backend: str = "rust",
        post_switch_backend: str = "python",
        elapsed_seconds: float = 240.0,
        audit_target: str = "python",
        cutover_cycle_id: str = "cycle-rollback-2026-05-17T20:00:00Z",
        bridge_audit_re_verify_ok: bool = True,
        missing_audit: bool = False,
    ) -> RollbackEvent:
        if missing_audit:
            # Engine boot completed but emitted no audit-record — the
            # RD-2 failure-shape. We synthesize a sentinel record with
            # an empty modul-string so the drill-test can detect the
            # missing-audit case via a positive assertion on
            # ``audit_record.modul != modul``.
            audit_record = BackendDecisionRecord(
                cutover_cycle_id="",
                modul="",
                target_backend="",
                cutover_ts_utc="",
                operator_actor="",
            )
        else:
            audit_record = BackendDecisionRecord(
                cutover_cycle_id=cutover_cycle_id,
                modul=modul,
                target_backend=audit_target,
                cutover_ts_utc="2026-05-17T20:04:00Z",
                operator_actor="operator-hand-rollback-runbook",
            )
        return RollbackEvent(
            modul=modul,
            pre_switch_backend=pre_switch_backend,
            post_switch_backend=post_switch_backend,
            elapsed_seconds=elapsed_seconds,
            audit_record=audit_record,
            bridge_audit_re_verify_ok=bridge_audit_re_verify_ok,
        )

    return _build


# ---------------------------------------------------------------------------
# Phase-2-Acceptance-Gate mock — RD-3 oracle.
#
# Post-rollback the system must re-pass the Phase-2-Acceptance-Gate
# (Cross-Modul-Konsistenz). This fixture is the mocked output of that
# gate; the Phase-3c-trigger-sprint replaces it with the real Tomás
# Tag-29 Cross-Modul-Stress-Test substrate emitting a real pass/fail.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Phase2AcceptanceGateRecord:
    """One Phase-2-Acceptance-Gate run record (post-rollback).

    Mirrors the Phase-2-Doppelbetrieb-Acceptance-Gate that ADR-0058
    §Phase-2 and ADR-0066 §Mitigation 1 anchor. The post-rollback
    re-run must return ``gate_green = True`` to certify that the
    rollback left the system in a cross-modul-consistent state.

    Fields:
        modul: The Komponente that was rolled back.
        gate_green: Whether all sub-gates of the Phase-2-Acceptance-
            Gate passed on the post-rollback re-run.
        failed_sub_gates: List of sub-gate-IDs that failed (empty when
            ``gate_green=True``).
        sample_size: Number of cross-modul requests probed by the
            re-run (mocked default 500).
    """

    modul: str
    gate_green: bool
    failed_sub_gates: tuple[str, ...]
    sample_size: int


@pytest.fixture
def mocked_phase_2_acceptance_gate() -> Callable[
    ..., Phase2AcceptanceGateRecord
]:
    """Fixture returning a Phase-2-Acceptance-Gate builder for the
    post-rollback re-run.

    Default builder produces a green record (all sub-gates pass).
    Drill-tests inject ``gate_green=False`` + ``failed_sub_gates``
    to verify the RD-3 failure-shape assertion.
    """

    def _build(
        modul: str,
        gate_green: bool = True,
        failed_sub_gates: tuple[str, ...] = (),
        sample_size: int = 500,
    ) -> Phase2AcceptanceGateRecord:
        return Phase2AcceptanceGateRecord(
            modul=modul,
            gate_green=gate_green,
            failed_sub_gates=failed_sub_gates,
            sample_size=sample_size,
        )

    return _build


# ---------------------------------------------------------------------------
# Shared RD-1...RD-4 assertion helpers.
#
# Encapsulating the four assertion-shapes once keeps the nine drill-
# files lean: each drill-file binds the modul-name + injects fixtures,
# then calls ``assert_rd_*`` on the produced records.
# ---------------------------------------------------------------------------


# The 10-minute Rollback-SLA constant. Mirrors the value in
# ``tests/acceptance/phase_3c/_ac_assertions.py``
# (``ROLLBACK_SLA_SECONDS``) to keep the drill-suite self-contained
# without crossing the package boundary for a single float constant.
ROLLBACK_SLA_SECONDS: float = 600.0


def assert_rd_1_env_flag_switch_effective(
    event: RollbackEvent, modul: str
) -> None:
    """RD-1 — ENV-Flag-Switch ``rust → python`` has a behavioural effect.

    Three sub-gates:

    * The event's ``modul`` matches the drill target.
    * Pre-switch backend was ``"rust"`` (else there was nothing to roll
      back from).
    * Post-switch backend is ``"python"`` (the rollback direction).
    """
    assert event.modul == modul, (
        f"RD-1[{modul}]: event-modul {event.modul!r} does not match "
        f"drill-target {modul!r}"
    )
    assert event.pre_switch_backend == "rust", (
        f"RD-1[{modul}]: pre-switch-backend must be 'rust' (else "
        f"nothing to roll back); got {event.pre_switch_backend!r}"
    )
    assert event.post_switch_backend == "python", (
        f"RD-1[{modul}]: post-switch-backend must be 'python' (the "
        f"rollback direction); got {event.post_switch_backend!r}"
    )


def assert_rd_2_audit_record_documents_rollback(
    event: RollbackEvent, modul: str
) -> None:
    """RD-2 — Backend-Decision-Audit emits a record for the rollback.

    Four sub-gates:

    * Audit-record's modul matches the drill target (also catches the
      ``missing_audit=True`` synthesised-empty-record failure-shape).
    * Audit-record's ``target_backend`` is ``"python"`` (the rollback
      direction; the cutover-flip emits ``"rust"``, the rollback-flip
      emits ``"python"``).
    * Audit-record carries a non-empty ``cutover_cycle_id`` (required
      for Henrik-Audit-Trail-Consistency, Zone-N).
    * Audit-record names an operator-actor (the Operator-Hand-runbook
      ran the switch).
    """
    rec = event.audit_record
    assert rec.modul == modul, (
        f"RD-2[{modul}]: audit-record modul {rec.modul!r} does not "
        f"match drill-target {modul!r} (missing-audit failure-shape "
        f"if empty-string)"
    )
    assert rec.target_backend == "python", (
        f"RD-2[{modul}]: audit-record target_backend must be 'python' "
        f"on a rollback; got {rec.target_backend!r}"
    )
    assert rec.cutover_cycle_id, (
        f"RD-2[{modul}]: audit-record cutover_cycle_id must be non-"
        f"empty for Henrik-Audit-Trail consistency"
    )
    assert rec.operator_actor, (
        f"RD-2[{modul}]: audit-record operator_actor must be populated "
        f"(Operator-Hand-runbook ran the switch)"
    )


def assert_rd_3_cross_modul_konsistenz_post_rollback(
    gate: Phase2AcceptanceGateRecord, modul: str
) -> None:
    """RD-3 — Cross-Modul-Konsistenz post-rollback green.

    Three sub-gates:

    * Gate-record's modul matches the drill target.
    * ``gate_green`` is True (the Phase-2-Acceptance-Gate re-passes
      after the rollback).
    * ``failed_sub_gates`` is empty (consistent with ``gate_green`` but
      independently asserted to surface partial-failure shapes).
    """
    assert gate.modul == modul, (
        f"RD-3[{modul}]: gate-record modul {gate.modul!r} does not "
        f"match drill-target {modul!r}"
    )
    assert gate.gate_green, (
        f"RD-3[{modul}]: Phase-2-Acceptance-Gate must re-pass post-"
        f"rollback; failed sub-gates: {gate.failed_sub_gates}"
    )
    assert not gate.failed_sub_gates, (
        f"RD-3[{modul}]: Phase-2-Acceptance-Gate has non-empty "
        f"failed_sub_gates while reporting gate_green=True — "
        f"inconsistent record-shape: {gate.failed_sub_gates}"
    )


def assert_rd_4_time_to_rollback_within_sla(
    event: RollbackEvent, modul: str
) -> None:
    """RD-4 — Time-to-rollback ≤10min ENV-Flag-Switch SLA (mocked clock).

    Two sub-gates:

    * Elapsed-seconds is strictly positive (no zero-time-elapsed
      sentinel slips through).
    * Elapsed-seconds ≤ ``ROLLBACK_SLA_SECONDS`` (600.0s).
    """
    assert event.elapsed_seconds > 0.0, (
        f"RD-4[{modul}]: rollback elapsed_seconds must be strictly "
        f"positive; got {event.elapsed_seconds:.2f}s"
    )
    assert event.elapsed_seconds <= ROLLBACK_SLA_SECONDS, (
        f"RD-4[{modul}]: rollback elapsed_seconds "
        f"{event.elapsed_seconds:.2f}s exceeds "
        f"{ROLLBACK_SLA_SECONDS:.0f}s 10-minute SLA "
        f"(ADR-0065 §Rollback-Strategie)"
    )


# Re-export selected parent-conftest symbols for drill-test convenience
# (the drill-files import from this sub-conftest by package path, so
# they should not need to reach into the parent module directly).
__all__ = (
    "PHASE_3C_COMPONENTS",
    "Phase2AcceptanceGateRecord",
    "ROLLBACK_DRILL_OPT_IN",
    "ROLLBACK_DRILL_OPT_IN_ENV",
    "ROLLBACK_SLA_SECONDS",
    "RollbackEvent",
    "SingleKomponenteRollbackRecord",
    "assert_rd_1_env_flag_switch_effective",
    "assert_rd_2_audit_record_documents_rollback",
    "assert_rd_3_cross_modul_konsistenz_post_rollback",
    "assert_rd_4_time_to_rollback_within_sla",
)
