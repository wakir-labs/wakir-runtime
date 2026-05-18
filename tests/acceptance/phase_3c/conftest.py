# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Shared fixtures for the Phase-3c-Acceptance E2E test-suite skeleton.

Anchors
-------

- ADR-0065 §Verifikations-Plan — the welle-for-welle acceptance
  criteria (AC-1 ... AC-5) that this suite enforces, one test-file
  per welle (welle-1 ... welle-7).
- ADR-0066 §Beschluss — Phase-3c-Beschleunigung Option-A+. Three
  Doppel-Wellen (KW 24, 26, 27) collapse seven solo-wochen into
  four. Doppel-Welle-test-files (``test_doppel_welle_<i>_<j>_e2e.py``)
  extend the per-welle skeleton with cross-modul-parallel-cutover
  acceptance under the five DW-AC-1 ... DW-AC-5 criteria.
- ADR-0063 §Phase-3c-Final-Cutover — the wider 7-welle cutover plan
  these E2E tests gate.
- ``docs/quality-gates/phase-3c-acceptance-criteria.md`` (Amara,
  this PR) — the welle-for-welle acceptance-criteria matrix, with
  the Doppel-Welle-Tabelle extension (§9 of that doc).
- ``tests/infra/test_phase_3_acceptance_gates.py`` (Amara, PR #80) —
  the Phase-3-Validation acceptance-gate skeleton this suite extends
  to the per-welle Phase-3c-Cutover level.

Scope
-----

The fixtures here are hermetic placeholder oracles for the
Phase-3c-Cutover-Welle E2E acceptance lane. Each fixture mocks the
substrate the per-welle E2E tests will interrogate at cutover time:

- ``mocked_bridge_audit_writer`` — Bridge-Audit-Writer roundtrip
  (Python ⇆ Rust envelope-hash parity oracle, ADR-0065 AC-1).
- ``mocked_engine_boot`` — Persona-Engine boot-sequence with per-
  modul backend selector (Python | Rust, ADR-0063 §Phase-3b).
- ``mocked_wat_anchor_sink`` — WAT-anchor-sink for cross-Python/Rust
  consistency verification.
- ``mocked_quadlet_env`` — Quadlet ENV-flag state ("WAKIR_ENGINE_
  <MODUL>_BACKEND" per ADR-0065 §Rollback-Strategie step 2).

Skip-by-default rationale
-------------------------

Phase-3c-Cutover is pending Phase-3b-Komplettierung + AR-Approval of
ADR-0065 (~KW 27-34 by stable schedule; 7-Wochen-Marathon per ADR-0065
§Empfehlung). Running the skeletons green-by-construction in CI today
would (i) waste signal (assertions are placeholder-shaped) and (ii)
risk false-positive confidence on Phase-3c readiness. Skip-by-default
keeps the skeletons compilable + import-correct without claiming a
green-light status on Phase-3c itself.

The opt-in pattern mirrors ``tests/infra/test_phase_3_acceptance_gates
.py`` (Phase-3-Validation skeleton): env-var ``WAKIR_PHASE_3C_E2E=1``
flips the gate, plus the ``phase_3c_acceptance`` pytest-marker for
selector targeting.

The Doppel-Welle skeleton adds a *second* opt-in lane:
``WAKIR_PHASE_3C_DOPPEL_E2E=1`` env-var with the
``phase_3c_doppel_welle_acceptance`` pytest-marker. The two lanes are
independent: a Phase-3c-trigger sprint may want to run per-welle
oracles without the parallel-cutover Doppel-Welle extras, or vice-
versa (e.g. during Welle-3 solo-week per ADR-0066 §Beschluss).

Sandbox boundary
----------------

Hermetic-only. No podman, no live NATS, no live Bridge-Audit-Writer
I/O, no OTS-calendar contact. The live-VM-acceptance lane (ADR-0060)
remains Operator-Hand responsibility. These fixtures are the
test-time *oracles* the live drills will compare against.

Vermutungs-Kennzeichnung (P2)
-----------------------------

The 7-welle ordering, the AC-1...AC-5 criteria shape, and the
per-welle threshold numbers are sourced from ADR-0065 §Verifikations-
Plan (proposer Tomás, AR-approval pending). They are placeholder
anchors pending Phase-3c-Welle-Start; the Phase-3c-trigger sprint
replaces the mock substrate with the real engine + bridge wiring.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Opt-in gate.
# ---------------------------------------------------------------------------

PHASE_3C_OPT_IN_ENV = "WAKIR_PHASE_3C_E2E"
PHASE_3C_OPT_IN = os.environ.get(PHASE_3C_OPT_IN_ENV) == "1"

# Doppel-Welle opt-in (ADR-0066 §Beschluss). Independent of the per-
# welle opt-in above — a Phase-3c-trigger sprint can flip either or
# both. Default-skip rationale identical (assertions are placeholder-
# shaped, parity-by-construction; running green-by-construction in
# CI would waste signal and risk false-positive Phase-3c-readiness).
PHASE_3C_DOPPEL_OPT_IN_ENV = "WAKIR_PHASE_3C_DOPPEL_E2E"
PHASE_3C_DOPPEL_OPT_IN = (
    os.environ.get(PHASE_3C_DOPPEL_OPT_IN_ENV) == "1"
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--phase-3c-acceptance`` opt-in flag.

    Two opt-in paths are supported (per ADR-0065 §Verifikations-Plan):

    1. ``pytest --phase-3c-acceptance`` — explicit CLI flag.
    2. ``WAKIR_PHASE_3C_E2E=1`` — env-var (Phase-3c-trigger-sprint
       flips this in the Operator-Hand acceptance-lane).

    Either path enables the skeleton; module-level pytestmark in each
    welle-test-file consults both.
    """
    group = parser.getgroup("wakir-phase-3c", "Wakir Phase-3c Acceptance")
    group.addoption(
        "--phase-3c-acceptance",
        action="store_true",
        default=False,
        help=(
            "Enable Phase-3c-Cutover-Welle E2E acceptance skeleton "
            "(skip-by-default; opt-in for Phase-3c-trigger sprint)."
        ),
    )
    group.addoption(
        "--phase-3c-doppel-welle-acceptance",
        action="store_true",
        default=False,
        help=(
            "Enable Phase-3c Doppel-Welle E2E acceptance skeleton "
            "(ADR-0066 §Beschluss; skip-by-default; opt-in for "
            "Doppel-Welle KW 24/26/27 cutover-trigger sprint)."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip phase_3c_acceptance + phase_3c_doppel_welle_acceptance
    tests unless the matching opt-in is present.

    Either the CLI flag or the env-var enables the matching skeleton.
    The two opt-in lanes are independent: per-welle and Doppel-Welle
    can each be enabled in isolation (or both, e.g. Doppel-Welle-trigger
    sprint runs both per-welle + Doppel-Welle oracles to verify the
    cross-modul-parallel-cutover doesn't regress the solo-welle
    guarantees).
    """
    per_welle_enabled = (
        config.getoption("--phase-3c-acceptance") or PHASE_3C_OPT_IN
    )
    doppel_enabled = (
        config.getoption("--phase-3c-doppel-welle-acceptance")
        or PHASE_3C_DOPPEL_OPT_IN
    )

    per_welle_skip = pytest.mark.skip(
        reason=(
            "Phase-3c-Acceptance skeleton skip-by-default — opt in with "
            "WAKIR_PHASE_3C_E2E=1 env-var or --phase-3c-acceptance CLI "
            "flag (Phase-3c-trigger sprint ~KW 24+ flips this gate per "
            "ADR-0065 / ADR-0066)."
        )
    )
    doppel_skip = pytest.mark.skip(
        reason=(
            "Phase-3c Doppel-Welle skeleton skip-by-default — opt in "
            "with WAKIR_PHASE_3C_DOPPEL_E2E=1 env-var or "
            "--phase-3c-doppel-welle-acceptance CLI flag (Doppel-Welle "
            "KW 24/26/27 trigger-sprint flips this gate per ADR-0066 "
            "§Beschluss)."
        )
    )

    for item in items:
        keywords = item.keywords
        if "phase_3c_doppel_welle_acceptance" in keywords:
            # Doppel-Welle marker dominates: if a test carries both
            # markers, the Doppel-Welle opt-in alone is sufficient
            # (per-welle assertions on top of Doppel-Welle context are
            # part of the Doppel-Welle skeleton's value-add).
            if not doppel_enabled:
                item.add_marker(doppel_skip)
        elif "phase_3c_acceptance" in keywords:
            if not per_welle_enabled:
                item.add_marker(per_welle_skip)


# ---------------------------------------------------------------------------
# Welle inventory — anchors the 7-welle cutover sequence from ADR-0065
# §Verifikations-Plan, Option-B-Reihenfolge (risk-ascending).
# ---------------------------------------------------------------------------

WELLE_ORDER: tuple[tuple[int, str], ...] = (
    (1, "v907_verify"),
    (2, "svid_workload_identity"),
    (3, "bridge_audit_writer"),
    (4, "state_backing"),
    (5, "lifecycle_state_machine"),
    (6, "subscribe_loop"),
    (7, "recovery_workflow"),
)

WELLE_BY_NAME: dict[str, int] = {name: idx for idx, name in WELLE_ORDER}


# ---------------------------------------------------------------------------
# Acceptance-criteria thresholds — sourced from ADR-0065 §Verifikations-
# Plan. Placeholders pending Phase-3c-trigger-sprint replacement.
# ---------------------------------------------------------------------------

# AC-1 — Bridge-Audit-Writer-Konsistenz-Report: 5/5 days green.
CONSISTENCY_REPORT_REQUIRED_GREEN_DAYS = 5
CONSISTENCY_REPORT_WINDOW_DAYS = 5

# AC-2 — Performance: P95-Latency ≤ Python-Baseline + 20%.
PERFORMANCE_HEADROOM_FACTOR = 1.20

# AC-3 — Bug-Rate: 0 substanz-relevante (S0/S1) Issues during
# Beobachtungs-Woche.
BUG_RATE_S0_S1_THRESHOLD = 0

# AC-4 — Cross-Review-Session-Konsensus: alle Engineering-Personas
# zustimmend (Aisha-Protokoll). Six-persona pool below mirrors the
# matrix in agents/ (Tomás, Reza, Kai, Lena, Noa, Selin).
CROSS_REVIEW_REQUIRED_PERSONAS: tuple[str, ...] = (
    "tomas",
    "reza",
    "kai",
    "lena",
    "noa",
    "selin",
)

# AC-5 — V-907 Pin-Validation: 100% pass-rate.
V907_PIN_VALIDATION_REQUIRED_RATE = 1.0


# ---------------------------------------------------------------------------
# Bridge-Audit-Writer roundtrip mock — AC-1 oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeAuditRoundtripRecord:
    """One Bridge-Audit-Writer roundtrip envelope.

    The roundtrip mirrors the Phase-3a Doppelbetrieb-Bridge audit-writer
    surface (ADR-0063 §Phase-3a): for each engine-call, both backends
    produce an envelope, the Bridge writes both into the WAT-anchor-
    sink, and a downstream consumer reads the consistency-report.

    A roundtrip with ``python_envelope_sha256 ==
    rust_envelope_sha256`` is *consistent* (AC-1 contributor); a drift
    blocks the AC-1 gate.
    """

    welle: str
    day_index: int  # 0..(CONSISTENCY_REPORT_WINDOW_DAYS-1)
    request_id: str
    python_envelope_sha256: str
    rust_envelope_sha256: str

    @property
    def is_consistent(self) -> bool:
        return self.python_envelope_sha256 == self.rust_envelope_sha256


def _envelope_hash(welle: str, day: int, req: str, salt: str = "") -> str:
    """Deterministic envelope-hash for the mock roundtrip.

    The Phase-3c-trigger sprint replaces this with the real envelope-
    hash oracle (real Python persona-engine output for the day's request
    set, compared to the Rust output via the Bridge-Audit-Writer).
    """
    payload = f"{welle}|d{day}|{req}|{salt}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@pytest.fixture
def mocked_bridge_audit_writer() -> Callable[
    [str, int, int], list[BridgeAuditRoundtripRecord]
]:
    """Fixture returning a Bridge-Audit-Writer roundtrip-builder.

    Usage::

        def test_x(mocked_bridge_audit_writer):
            roundtrips = mocked_bridge_audit_writer("v907_verify", days=5, per_day=3)
            assert all(rt.is_consistent for rt in roundtrips)

    The builder default produces all-consistent records (parity-by-
    construction). The welle-test injects drift by passing
    ``drift_request_ids=[...]`` to verify the failure-mode assertion-
    shape (mirrors the Phase-3-Validation skeleton pattern).
    """

    def _build(
        welle: str,
        days: int = CONSISTENCY_REPORT_WINDOW_DAYS,
        per_day: int = 3,
        drift_request_ids: tuple[str, ...] = (),
    ) -> list[BridgeAuditRoundtripRecord]:
        out: list[BridgeAuditRoundtripRecord] = []
        for day in range(days):
            for k in range(per_day):
                req = f"req-{welle}-d{day}-{k}"
                py_hash = _envelope_hash(welle, day, req, salt="py")
                if req in drift_request_ids:
                    # Drift: Rust hash differs.
                    rust_hash = _envelope_hash(welle, day, req, salt="rust-drift")
                else:
                    # Parity-by-construction.
                    rust_hash = py_hash
                out.append(
                    BridgeAuditRoundtripRecord(
                        welle=welle,
                        day_index=day,
                        request_id=req,
                        python_envelope_sha256=py_hash,
                        rust_envelope_sha256=rust_hash,
                    )
                )
        return out

    return _build


# ---------------------------------------------------------------------------
# Persona-Engine boot mock — per-welle backend-selector oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineBootRecord:
    """One persona-engine boot with per-modul backend selection.

    Mirrors the Quadlet-ENV-flag substrate (``WAKIR_ENGINE_<MODUL>_
    BACKEND=rust|python``). The boot-record captures the resolved
    backend per modul + the boot-result (succeeded | failed).

    Welle-tests use this to verify: (a) the Quadlet-flag default flip
    from ``python`` to ``rust`` for the welle-modul; (b) other
    moduln untouched (mixed-backend-substrat sichtbar pre-Welle-Ende);
    (c) boot-failure path = Rollback-trigger.
    """

    welle: str
    boot_ts_utc: str  # placeholder; Phase-3c sprint replaces with real ts
    backend_per_modul: dict[str, str]  # modul -> "python" | "rust"
    boot_succeeded: bool


@pytest.fixture
def mocked_engine_boot() -> Callable[..., EngineBootRecord]:
    """Fixture returning a persona-engine boot-builder.

    Default builder produces a successful boot with all-Python backends
    except the welle-modul (which is flipped to ``rust``). The welle-
    test injects failures via ``boot_succeeded=False`` to verify the
    Rollback-trigger assertion-shape (ADR-0065 §Rollback-Strategie).
    """

    def _build(
        welle: str,
        boot_succeeded: bool = True,
        flipped_modul: str | None = None,
    ) -> EngineBootRecord:
        # By default, the welle-modul is the one flipped to rust.
        target_modul = flipped_modul or welle
        backend_per_modul = {modul: "python" for _, modul in WELLE_ORDER}
        if target_modul in backend_per_modul:
            backend_per_modul[target_modul] = "rust"
        return EngineBootRecord(
            welle=welle,
            boot_ts_utc="2026-05-17T20:00:00Z",
            backend_per_modul=backend_per_modul,
            boot_succeeded=boot_succeeded,
        )

    return _build


# ---------------------------------------------------------------------------
# WAT-anchor-sink consistency mock — cross-Python/Rust verify oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WATAnchorRecord:
    """One WAT-anchor written by the Bridge-Audit-Writer.

    The anchor carries the canonical envelope-hash plus the backend
    identity that produced it. Post-cutover consistency requires that
    the new (Rust-backend) anchor matches the pre-cutover (Python-
    backend) anchor on the same logical request.
    """

    welle: str
    request_id: str
    backend: str  # "python" | "rust"
    anchor_sha256: str


@pytest.fixture
def mocked_wat_anchor_sink() -> Callable[..., list[WATAnchorRecord]]:
    """Fixture returning a WAT-anchor-sink builder for pre/post-cutover
    consistency checks.

    Default builder produces parity-by-construction (anchor-hash equal
    across backends on the same request_id). The welle-test injects
    pre-cutover-only or post-cutover-only anchors to verify the no-
    Anchor-Diff assertion-shape (AC-1 contributor).
    """

    def _build(
        welle: str,
        request_ids: tuple[str, ...] = ("req-a", "req-b", "req-c"),
        drift_request_ids: tuple[str, ...] = (),
    ) -> list[WATAnchorRecord]:
        out: list[WATAnchorRecord] = []
        for req in request_ids:
            py_anchor = _envelope_hash(welle, 0, req, salt="anchor-py")
            if req in drift_request_ids:
                rust_anchor = _envelope_hash(welle, 0, req, salt="anchor-rust-drift")
            else:
                rust_anchor = py_anchor
            out.append(
                WATAnchorRecord(
                    welle=welle,
                    request_id=req,
                    backend="python",
                    anchor_sha256=py_anchor,
                )
            )
            out.append(
                WATAnchorRecord(
                    welle=welle,
                    request_id=req,
                    backend="rust",
                    anchor_sha256=rust_anchor,
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# Quadlet ENV-flag state mock — Rollback-trigger oracle.
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_quadlet_env() -> Callable[..., dict[str, str]]:
    """Fixture returning a Quadlet-ENV-state builder.

    Mirrors the ENV-flag matrix ``WAKIR_ENGINE_<MODUL>_BACKEND`` per
    ADR-0065 §Rollback-Strategie step 2. Default builder flips only
    the welle-modul to ``rust``, leaves others at ``python`` (the
    Phase-3c sequential cutover state pre-Welle-Ende).
    """

    def _build(
        welle: str,
        flipped_moduln: tuple[str, ...] | None = None,
    ) -> dict[str, str]:
        moduln_to_flip = (
            flipped_moduln if flipped_moduln is not None else (welle,)
        )
        env: dict[str, str] = {}
        for _, modul in WELLE_ORDER:
            key = f"WAKIR_ENGINE_{modul.upper()}_BACKEND"
            env[key] = "rust" if modul in moduln_to_flip else "python"
        return env

    return _build


# ---------------------------------------------------------------------------
# Cross-review-session-record mock — AC-4 oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossReviewRecord:
    """One Cross-Review-Session record (Donnerstag Aisha-moderated, ADR-0065).

    The record carries the consenting persona-set + the welle context.
    AC-4 requires that all Engineering-Personas in
    ``CROSS_REVIEW_REQUIRED_PERSONAS`` consent (Aisha-Protokoll).
    """

    welle: str
    session_date: str  # placeholder; sprint replaces with real
    moderator: str
    consenting_personas: tuple[str, ...]


@pytest.fixture
def mocked_cross_review() -> Callable[..., CrossReviewRecord]:
    """Fixture returning a Cross-Review-Session-builder.

    Default builder produces an all-personas-consenting record. The
    welle-test injects withholding-personas via
    ``withheld_personas=(...)`` to verify the AC-4 failure path.
    """

    def _build(
        welle: str,
        withheld_personas: tuple[str, ...] = (),
    ) -> CrossReviewRecord:
        consenting = tuple(
            p for p in CROSS_REVIEW_REQUIRED_PERSONAS if p not in withheld_personas
        )
        return CrossReviewRecord(
            welle=welle,
            session_date="2026-05-17",
            moderator="aisha",
            consenting_personas=consenting,
        )

    return _build


# ---------------------------------------------------------------------------
# Doppel-Welle inventory — anchors the three Doppel-Welle-Kombinationen
# from ADR-0066 §Beschluss (KW 24, 26, 27). KW 25 = Welle-3 solo, not
# a Doppel-Welle (Henrik-Caution carve-out).
# ---------------------------------------------------------------------------

DOPPEL_WELLE_ORDER: tuple[tuple[str, str, str, str], ...] = (
    # (calendar-week, modul-a, modul-b, characterisation)
    ("KW24", "v907_verify", "svid_workload_identity", "read-only-paar"),
    (
        "KW26",
        "state_backing",
        "lifecycle_state_machine",
        "cross-modul-state-paar",
    ),
    ("KW27", "subscribe_loop", "recovery_workflow", "stateful-loop-paar"),
)

DOPPEL_WELLE_BY_PAIR: dict[tuple[str, str], str] = {
    (a, b): kw for kw, a, b, _ in DOPPEL_WELLE_ORDER
}


# ---------------------------------------------------------------------------
# Backend-Decision-Audit record — DW-AC-5 oracle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendDecisionRecord:
    """One backend-decision-audit record emitted per cutover-flip.

    Each per-welle cutover emits exactly one ``BackendDecisionRecord``:
    the engine logs which modul flipped to which backend at which
    boot-time. Under Doppel-Welle conditions, *two* records must be
    emitted in a single cutover event and they must be timestamp-
    consistent (same Cutover-Mittwoch, same engine-boot-cycle).

    DW-AC-5 enforces: two records present, both modul-names match the
    Doppel-Welle pair, both target ``rust``, both share the same
    cutover-cycle-id.
    """

    cutover_cycle_id: str
    modul: str
    target_backend: str  # "rust" expected on cutover-flip
    cutover_ts_utc: str
    operator_actor: str  # placeholder; real path = Operator-Hand-runbook


@pytest.fixture
def mocked_backend_decision_audit() -> Callable[
    ..., list[BackendDecisionRecord]
]:
    """Fixture returning a Backend-Decision-Audit-record builder.

    Default builder emits two consistent records for a Doppel-Welle
    pair (DW-AC-5 happy-path). Doppel-Welle-tests inject:

    * ``drift_cycle_id``: one record's cutover-cycle-id differs, i.e.
      the two flips happened in different boot-cycles → consistency
      violation.
    * ``missing_modul``: one of the two moduln has no record at all
      → DW-AC-5 emits-2-records gate fails.
    * ``wrong_target_backend``: one record's target_backend is not
      ``rust`` → cutover-direction drift.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        cutover_cycle_id: str = "cycle-doppel-2026-05-17T20:00:00Z",
        drift_cycle_id: bool = False,
        missing_modul: str | None = None,
        wrong_target_backend: str | None = None,
    ) -> list[BackendDecisionRecord]:
        out: list[BackendDecisionRecord] = []
        for idx, modul in enumerate((modul_a, modul_b)):
            if missing_modul == modul:
                continue
            cycle_id = (
                f"{cutover_cycle_id}-drift-{modul}"
                if drift_cycle_id and idx == 1
                else cutover_cycle_id
            )
            target = (
                wrong_target_backend
                if wrong_target_backend is not None and idx == 1
                else "rust"
            )
            out.append(
                BackendDecisionRecord(
                    cutover_cycle_id=cycle_id,
                    modul=modul,
                    target_backend=target,
                    cutover_ts_utc="2026-05-17T20:00:00Z",
                    operator_actor="operator-hand-runbook",
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# Cross-Modul-Stress-Test record — DW-AC-4 oracle.
#
# References Tomás Tag-29 Cross-Modul-Stress-Test substrate (Phase-2-
# Acceptance-Gate-Erweiterung per ADR-0066 §Mitigation 1). The fixture
# here is the QA-side oracle that Tomás's substrate output is wired
# against; pre-trigger-sprint this is a placeholder green-by-construction
# record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulStressTestRecord:
    """One Cross-Modul-Stress-Test run record (Doppel-Welle-specific).

    Captures: which Doppel-Welle pair the run targeted, total request
    count over the stress-window, failure-count, p99-latency-budget
    excursion-count, cross-modul-schema-drift-count.

    DW-AC-4 gate: failure_count == 0 AND
    cross_modul_schema_drift_count == 0 AND
    p99_latency_excursion_count == 0.
    """

    welle_pair: tuple[str, str]
    total_request_count: int
    failure_count: int
    p99_latency_excursion_count: int
    cross_modul_schema_drift_count: int


@pytest.fixture
def mocked_cross_modul_stress_test() -> Callable[
    ..., CrossModulStressTestRecord
]:
    """Fixture returning a Cross-Modul-Stress-Test record builder.

    Default builder produces a green record (zero failures, zero
    latency-excursions, zero schema-drift). Doppel-Welle-tests inject
    failure-modes to verify the DW-AC-4 assertion-shape.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        total: int = 1000,
        failures: int = 0,
        p99_excursions: int = 0,
        schema_drifts: int = 0,
    ) -> CrossModulStressTestRecord:
        return CrossModulStressTestRecord(
            welle_pair=(modul_a, modul_b),
            total_request_count=total,
            failure_count=failures,
            p99_latency_excursion_count=p99_excursions,
            cross_modul_schema_drift_count=schema_drifts,
        )

    return _build


# ---------------------------------------------------------------------------
# Cross-Modul-Schema-Konsistenz record — DW-AC-2 oracle.
#
# Byte-paritäre Schema-Verifikation zwischen den beiden Doppel-Welle-
# Moduln auf gemeinsamer Cross-Modul-Schnittstelle (z.B. state_backing
# schreibt JCS-record, lifecycle_state_machine liest ihn). DW-AC-2
# erzwingt byte-exakte Konsistenz across the pair.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulSchemaRecord:
    """One Cross-Modul-Schema-Konsistenz-Record.

    For each cross-modul-touchpoint (typically a record produced by
    modul_a and consumed by modul_b), the record carries both byte-
    representations and a SHA-256 hash of each.

    DW-AC-2: ``producer_bytes_sha256 == consumer_bytes_sha256`` for
    every touchpoint in the pair.
    """

    welle_pair: tuple[str, str]
    touchpoint_id: str
    producer_modul: str
    consumer_modul: str
    producer_bytes_sha256: str
    consumer_bytes_sha256: str

    @property
    def is_byte_parity(self) -> bool:
        return self.producer_bytes_sha256 == self.consumer_bytes_sha256


@pytest.fixture
def mocked_cross_modul_schema() -> Callable[
    ..., list[CrossModulSchemaRecord]
]:
    """Fixture returning a Cross-Modul-Schema-Record builder.

    Default builder emits a list of touchpoint-records with byte-parity-
    by-construction. Doppel-Welle-tests inject drift via the
    ``drift_touchpoint_ids`` knob.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        touchpoint_ids: tuple[str, ...] = (
            "tp-init",
            "tp-update",
            "tp-finalize",
        ),
        drift_touchpoint_ids: tuple[str, ...] = (),
    ) -> list[CrossModulSchemaRecord]:
        out: list[CrossModulSchemaRecord] = []
        for tp_id in touchpoint_ids:
            producer_hash = _envelope_hash(
                f"{modul_a}->{modul_b}", 0, tp_id, salt="producer"
            )
            if tp_id in drift_touchpoint_ids:
                consumer_hash = _envelope_hash(
                    f"{modul_a}->{modul_b}",
                    0,
                    tp_id,
                    salt="consumer-drift",
                )
            else:
                consumer_hash = producer_hash
            out.append(
                CrossModulSchemaRecord(
                    welle_pair=(modul_a, modul_b),
                    touchpoint_id=tp_id,
                    producer_modul=modul_a,
                    consumer_modul=modul_b,
                    producer_bytes_sha256=producer_hash,
                    consumer_bytes_sha256=consumer_hash,
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# Doppel-Welle Engine-Boot mock — DW-AC-1 oracle.
#
# Extends ``mocked_engine_boot`` to flip *two* moduln to rust in a single
# boot, modelling the Cutover-Mittwoch-Doppel-Cutover (ADR-0066
# §Mitigation 3).
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_engine_boot_doppel() -> Callable[..., EngineBootRecord]:
    """Fixture returning a Doppel-Welle persona-engine boot-builder.

    Default builder produces a successful boot with both Doppel-Welle
    moduln flipped to ``rust`` and the remaining five moduln on
    ``python``. Tests inject:

    * ``boot_succeeded=False`` — Rollback-trigger assertion-shape
      (both moduln rolled back when boot fails under Doppel-Welle
      conditions per ADR-0066 §Rollback-Strategie).
    * ``flipped_modul_a`` / ``flipped_modul_b`` — override pair shape.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        boot_succeeded: bool = True,
    ) -> EngineBootRecord:
        backend_per_modul = {modul: "python" for _, modul in WELLE_ORDER}
        for m in (modul_a, modul_b):
            if m in backend_per_modul:
                backend_per_modul[m] = "rust"
        # The welle-tag uses the modul_a-name (alphabetical-stable
        # for the Doppel-Welle pair identity in the test-output).
        return EngineBootRecord(
            welle=f"doppel:{modul_a}+{modul_b}",
            boot_ts_utc="2026-05-17T20:00:00Z",
            backend_per_modul=backend_per_modul,
            boot_succeeded=boot_succeeded,
        )

    return _build


# ---------------------------------------------------------------------------
# Single-Komponente-Rollback record — DW-AC-3 oracle.
#
# When a bug emerges in one of two Doppel-Welle-Komponenten, rollback
# *only* the affected one — the other stays on rust. This is the asym-
# metric rollback discipline (ADR-0066 §Rollback-Strategie nuance).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SingleKomponenteRollbackRecord:
    """One single-Komponente-Rollback record for the asymmetric path.

    Captures the Doppel-Welle pair, which modul rolled back, the rollback-
    elapsed-seconds (≤10min SLA per ADR-0065/-0066), and the post-
    rollback backend-state for *both* moduln.

    DW-AC-3 assertion-shape: rolled_back_modul is flipped back to
    ``python``, partner_modul stays on ``rust``, elapsed_seconds ≤
    600 (10min SLA).
    """

    welle_pair: tuple[str, str]
    rolled_back_modul: str
    rollback_elapsed_seconds: float
    post_rollback_backend_per_modul: dict[str, str]


@pytest.fixture
def mocked_single_komponente_rollback() -> Callable[
    ..., SingleKomponenteRollbackRecord
]:
    """Fixture returning a single-Komponente-Rollback-record builder.

    Default builder produces a successful asymmetric rollback (rolled
    back modul back to python, partner stays rust, elapsed = 240s).
    Doppel-Welle-tests inject:

    * ``elapsed_seconds=700`` — SLA-violation failure-mode.
    * ``partner_also_rolled_back=True`` — wrong-shape failure-mode
      (Doppel-Welle rollback should be asymmetric by default per
      ADR-0066 §Rollback-Strategie unless cross-modul-bug emerges).
    """

    def _build(
        modul_a: str,
        modul_b: str,
        rolled_back_modul: str,
        elapsed_seconds: float = 240.0,
        partner_also_rolled_back: bool = False,
    ) -> SingleKomponenteRollbackRecord:
        partner = modul_b if rolled_back_modul == modul_a else modul_a
        post_state = {modul: "python" for _, modul in WELLE_ORDER}
        if not partner_also_rolled_back:
            post_state[partner] = "rust"
        return SingleKomponenteRollbackRecord(
            welle_pair=(modul_a, modul_b),
            rolled_back_modul=rolled_back_modul,
            rollback_elapsed_seconds=elapsed_seconds,
            post_rollback_backend_per_modul=post_state,
        )

    return _build


# ---------------------------------------------------------------------------
# Doppel-Welle-4+5 Cross-Modul-Drift Acceptance-Kriterien — CMD-AC-1 ...
# CMD-AC-4
#
# Anchor: ADR-0066 §Beschluss §"Doppel-Welle-4+5 Cross-Modul-Drift-Focus"
# + Priya CTO-Coordination-Plan v2 (Tag-32 Mini-Welle) identifying
# Doppel-Welle-4+5 (``state_backing`` × ``lifecycle_state_machine``) as
# the highest cross-modul-drift-risk slot of the three Doppel-Wellen.
#
# These criteria are layered atop DW-AC-1...DW-AC-5 specifically for
# the KW 26 Doppel-Welle-4+5 cutover. The other two Doppel-Wellen
# (DW-1+2 KW 24, DW-6+7 KW 27) do not carry the CMD-AC layer — they
# have different drift-surfaces (read-only-paar resp. stateful-loop-
# paar), addressed by their own DW-AC schwerpunkte.
#
# The DW-AC layer already covers byte-parity on a single touchpoint
# (DW-AC-2) and aggregate stress-test green-rate (DW-AC-4). The CMD-AC
# layer drills deeper into the Welle-4+5 producer/consumer contract:
#
# * CMD-AC-1 — Producer→Consumer deserialization round-trip parity
#   under cross-lang Rust-Rust contract.
# * CMD-AC-2 — Consumer-triggered Producer write-back wire-form parity
#   vs. the Python-Python baseline (cross-lang baseline consistency).
# * CMD-AC-3 — Cross-Modul-Stress-Test per-Komponente joint-consistency
#   ≥99.5% (DW-AC-4 sets a zero-failure floor on aggregate; CMD-AC-3
#   sets a per-Komponente consistency-rate floor).
# * CMD-AC-4 — Drift-triggered atomic single-Komponente rollback when
#   measured cross-modul-drift exceeds 0.5 percentage points; partner
#   stays rust-Default (atomic-flip-pattern, DW-AC-3 nuance).
# ---------------------------------------------------------------------------

# CMD-AC-3 — Per-Komponente joint-consistency floor over the stress-
# window. DW-AC-4 sets total-failures==0; CMD-AC-3 sets a tighter per-
# Komponente consistency-rate floor on the joint state_backing ⇆
# lifecycle_state_machine contract.
CROSS_MODUL_DRIFT_CONSISTENCY_PCT_FLOOR = 0.995

# CMD-AC-4 — Drift threshold for atomic-flip rollback (percentage
# points). Tighter than the 1.0pp soft-warn threshold in the runbook;
# at 0.5pp the operator-hand-runbook fires an atomic ENV-flag switch
# on the affected modul only (partner stays rust per DW-AC-3
# discipline). Mirrors the Welle-3 Henrik-Caution divergence threshold
# numerically but the trigger is per-modul, not whole-bridge-audit-
# writer.
CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD = 0.5

# CMD-AC-2 — wire-form parity is checked against the Python-Python
# baseline (the pre-Welle-4-Cutover state) AND against the
# Python-Rust mixed-state (the Welle-4-only mid-Doppel-Welle state).
# Both reference oracles must agree byte-identically with the new
# Rust-Rust state under Doppel-Welle.
CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES: tuple[str, ...] = (
    "python-python-baseline",
    "python-rust-welle-4-only",
)


# ---------------------------------------------------------------------------
# CMD-AC-1 — Producer→Consumer deserialization round-trip record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftDeserializationRecord:
    """One Producer→Consumer deserialization round-trip record.

    ``state_backing-rust`` writes a JCS-canonicalised state-record to
    disk; ``lifecycle_state_machine-rust`` reads + deserialises that
    record on persona-spawn (initial-state) and on transition-resume.
    CMD-AC-1 enforces byte-identical schema-deserialization across the
    Rust-producer × Rust-consumer cross-lang contract.

    Three fields are compared:

    * ``producer_serialized_sha256`` — hash of bytes that ``state_
      backing-rust`` wrote.
    * ``consumer_deserialized_reserialized_sha256`` — hash of bytes
      after ``lifecycle_state_machine-rust`` deserialised the record
      and re-serialised it back to JCS (round-trip parity check).
    * ``schema_version_round_trip_ok`` — schema-version field
      survives the deserialize→re-serialize round-trip.
    """

    welle_pair: tuple[str, str]
    record_id: str
    producer_serialized_sha256: str
    consumer_deserialized_reserialized_sha256: str
    schema_version_round_trip_ok: bool

    @property
    def is_round_trip_parity(self) -> bool:
        return (
            self.producer_serialized_sha256
            == self.consumer_deserialized_reserialized_sha256
            and self.schema_version_round_trip_ok
        )


@pytest.fixture
def mocked_cross_modul_drift_deserialization() -> Callable[
    ..., list[CrossModulDriftDeserializationRecord]
]:
    """Fixture returning a CMD-AC-1 deserialization round-trip builder.

    Default builder produces round-trip-parity-by-construction. Tests
    inject:

    * ``drift_record_ids`` — set of record-ids that exhibit serialized
      vs. re-serialized hash drift (deserialization-mutation bug).
    * ``schema_version_breakage_ids`` — set of record-ids where the
      schema-version field is dropped or rewritten on round-trip
      (schema-version-drift bug).
    """

    def _build(
        modul_a: str,
        modul_b: str,
        record_ids: tuple[str, ...] = (
            "rec-initial-state",
            "rec-transition-1",
            "rec-transition-2",
            "rec-terminal-archived",
        ),
        drift_record_ids: tuple[str, ...] = (),
        schema_version_breakage_ids: tuple[str, ...] = (),
    ) -> list[CrossModulDriftDeserializationRecord]:
        out: list[CrossModulDriftDeserializationRecord] = []
        for rec_id in record_ids:
            producer_hash = _envelope_hash(
                f"{modul_a}->{modul_b}", 0, rec_id, salt="cmd-ac-1-producer"
            )
            if rec_id in drift_record_ids:
                consumer_hash = _envelope_hash(
                    f"{modul_a}->{modul_b}",
                    0,
                    rec_id,
                    salt="cmd-ac-1-consumer-drift",
                )
            else:
                consumer_hash = producer_hash
            out.append(
                CrossModulDriftDeserializationRecord(
                    welle_pair=(modul_a, modul_b),
                    record_id=rec_id,
                    producer_serialized_sha256=producer_hash,
                    consumer_deserialized_reserialized_sha256=consumer_hash,
                    schema_version_round_trip_ok=(
                        rec_id not in schema_version_breakage_ids
                    ),
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-2 — Consumer-triggered Producer write-back wire-form record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftWriteBackRecord:
    """One Consumer-triggered Producer-write-back wire-form record.

    ``lifecycle_state_machine-rust`` decides on a state-transition;
    ``state_backing-rust`` persists the transition-record. CMD-AC-2
    enforces that the Rust-Rust wire-form is byte-identical to the
    Python-Python and Python-Rust reference oracles for the same
    logical transition.

    The ``rust_rust_wire_sha256`` is what Doppel-Welle-4+5 produces.
    The ``oracle_wire_sha256_by_oracle`` carries the reference
    wire-forms from the pre-Welle-4 baseline (Python-Python) and the
    mid-Doppel-Welle hypothetical (Python-Rust, where state_backing
    is Rust but lifecycle_state_machine is still Python — never
    observed in production, but available as a synthetic oracle).
    """

    welle_pair: tuple[str, str]
    transition_id: str
    rust_rust_wire_sha256: str
    oracle_wire_sha256_by_oracle: dict[str, str]

    def matches_oracle(self, oracle: str) -> bool:
        return self.rust_rust_wire_sha256 == self.oracle_wire_sha256_by_oracle.get(
            oracle
        )


@pytest.fixture
def mocked_cross_modul_drift_write_back() -> Callable[
    ..., list[CrossModulDriftWriteBackRecord]
]:
    """Fixture returning a CMD-AC-2 wire-form record builder.

    Default builder produces wire-form parity across all oracles.
    Tests inject:

    * ``drift_oracle`` — which oracle the rust-rust wire-form
      diverges from (e.g. ``"python-python-baseline"`` for a
      regression vs. the pre-Welle-4-cutover baseline).
    * ``drift_transition_ids`` — set of transition-ids that show
      drift; others stay parity-by-construction.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        transition_ids: tuple[str, ...] = (
            "transition-spawn-to-ready",
            "transition-ready-to-active",
            "transition-active-to-archived",
        ),
        drift_oracle: str | None = None,
        drift_transition_ids: tuple[str, ...] = (),
    ) -> list[CrossModulDriftWriteBackRecord]:
        out: list[CrossModulDriftWriteBackRecord] = []
        for trans_id in transition_ids:
            rust_rust_hash = _envelope_hash(
                f"{modul_a}->{modul_b}",
                0,
                trans_id,
                salt="cmd-ac-2-rust-rust",
            )
            oracle_hashes: dict[str, str] = {}
            for oracle in CROSS_MODUL_DRIFT_WIRE_FORM_ORACLES:
                if (
                    drift_oracle == oracle
                    and trans_id in drift_transition_ids
                ):
                    oracle_hashes[oracle] = _envelope_hash(
                        f"{modul_a}->{modul_b}",
                        0,
                        trans_id,
                        salt=f"cmd-ac-2-{oracle}-drift",
                    )
                else:
                    oracle_hashes[oracle] = rust_rust_hash
            out.append(
                CrossModulDriftWriteBackRecord(
                    welle_pair=(modul_a, modul_b),
                    transition_id=trans_id,
                    rust_rust_wire_sha256=rust_rust_hash,
                    oracle_wire_sha256_by_oracle=oracle_hashes,
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-3 — Cross-Modul-Stress-Test per-Komponente consistency record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftPerKomponenteConsistencyRecord:
    """One Cross-Modul-Stress-Test per-Komponente consistency record.

    Extends ``CrossModulStressTestRecord`` (DW-AC-4) with per-Komponente
    consistency-rates. DW-AC-4 sets ``failure_count == 0`` on the
    aggregate; CMD-AC-3 sets a per-Komponente consistency-rate ≥99.5%
    floor — a Komponente may have non-failure-class drift (e.g.
    transient latency-tail without throw) that DW-AC-4 misses but CMD-
    AC-3 catches.

    Both per-Komponente rates must clear the floor; the joint-pair-rate
    is computed as the min() of the two for gate-evaluation purposes.
    """

    welle_pair: tuple[str, str]
    total_request_count: int
    modul_a_consistency_rate: float
    modul_b_consistency_rate: float

    @property
    def joint_consistency_rate(self) -> float:
        return min(self.modul_a_consistency_rate, self.modul_b_consistency_rate)


@pytest.fixture
def mocked_cross_modul_drift_per_komponente_consistency() -> Callable[
    ..., CrossModulDriftPerKomponenteConsistencyRecord
]:
    """Fixture returning a CMD-AC-3 per-Komponente consistency record builder.

    Default builder produces both rates at 0.999 (above 0.995 floor).
    Tests inject ``modul_a_rate`` / ``modul_b_rate`` overrides to
    exercise the per-Komponente floor logic.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        total: int = 5000,
        modul_a_rate: float = 0.999,
        modul_b_rate: float = 0.999,
    ) -> CrossModulDriftPerKomponenteConsistencyRecord:
        return CrossModulDriftPerKomponenteConsistencyRecord(
            welle_pair=(modul_a, modul_b),
            total_request_count=total,
            modul_a_consistency_rate=modul_a_rate,
            modul_b_consistency_rate=modul_b_rate,
        )

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-4 — Drift-triggered atomic single-Komponente rollback record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftAtomicFlipRecord:
    """One CMD-AC-4 drift-triggered atomic-flip rollback record.

    Extends ``SingleKomponenteRollbackRecord`` (DW-AC-3) with the drift-
    magnitude that triggered the flip. The atomic-flip-pattern means:
    when measured cross-modul-drift exceeds 0.5pp, exactly the modul
    whose drift signal exceeded the threshold is flipped back to
    python; the partner stays on rust-Default (no contagious rollback).

    Gates:

    * ``measured_drift_pct > CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD``
      → flip-trigger fires for the high-drift modul.
    * ``post_flip_backend_per_modul`` — high-drift modul on
      ``python``, partner modul on ``rust``.
    * ``flip_elapsed_seconds`` ≤ ``ROLLBACK_SLA_SECONDS`` (10min, same
      ENV-Flag-Switch SLA as DW-AC-3).
    * ``flip_was_atomic`` — single ``systemctl restart`` cycle, no
      partial state where both moduln are mid-flip simultaneously.
    """

    welle_pair: tuple[str, str]
    high_drift_modul: str
    measured_drift_pct: float
    threshold_drift_pct: float
    flip_elapsed_seconds: float
    flip_was_atomic: bool
    post_flip_backend_per_modul: dict[str, str]


@pytest.fixture
def mocked_cross_modul_drift_atomic_flip() -> Callable[
    ..., CrossModulDriftAtomicFlipRecord
]:
    """Fixture returning a CMD-AC-4 atomic-flip record builder.

    Default builder produces a successful atomic-flip (high-drift modul
    rolled back to python, partner stays rust, elapsed = 180s, atomic
    flag True). Tests inject:

    * ``measured_drift_pct`` — set below 0.5pp to verify the no-flip
      sub-threshold path (a flip on sub-threshold drift would be
      spurious and is rejected).
    * ``flip_elapsed_seconds=700`` — SLA-violation failure-mode.
    * ``partner_also_flipped=True`` — non-atomic contagion failure-
      mode (Doppel-Welle-4+5 discipline forbids this unless the bug
      is in the contract, which is covered by DW-AC-3 both-rollback
      path).
    """

    def _build(
        modul_a: str,
        modul_b: str,
        high_drift_modul: str,
        measured_drift_pct: float = 0.8,
        flip_elapsed_seconds: float = 180.0,
        flip_was_atomic: bool = True,
        partner_also_flipped: bool = False,
    ) -> CrossModulDriftAtomicFlipRecord:
        partner = modul_b if high_drift_modul == modul_a else modul_a
        post_state = {modul: "python" for _, modul in WELLE_ORDER}
        if not partner_also_flipped:
            post_state[partner] = "rust"
        return CrossModulDriftAtomicFlipRecord(
            welle_pair=(modul_a, modul_b),
            high_drift_modul=high_drift_modul,
            measured_drift_pct=measured_drift_pct,
            threshold_drift_pct=CROSS_MODUL_DRIFT_ROLLBACK_PCT_THRESHOLD,
            flip_elapsed_seconds=flip_elapsed_seconds,
            flip_was_atomic=flip_was_atomic,
            post_flip_backend_per_modul=post_state,
        )

    return _build


# ---------------------------------------------------------------------------
# Doppel-Welle-6+7 Cross-Modul-Drift Acceptance-Kriterien — CMD-AC-6-7-1 ...
# CMD-AC-6-7-4
#
# Anchor: ADR-0066 §Beschluss + Priya CTO-Coordination-Plan v3 (Tag-32
# Mini-Welle, Welle-6+7 Cross-Modul-AC extension). These criteria layer
# atop DW-AC-1...DW-AC-5 specifically for the KW 27 Doppel-Welle-6+7
# cutover (``subscribe_loop`` × ``recovery_workflow``) — the stateful-
# loop-paar.
#
# The Welle-6+7 contract differs from Welle-4+5 in shape:
#
# * Welle-4+5: ``state_backing`` (producer) → ``lifecycle_state_machine``
#   (consumer) — JCS-state-record schema-touchpoint, producer/consumer
#   contract on persisted state.
# * Welle-6+7: ``subscribe_loop`` *emits ack-records* that
#   ``recovery_workflow`` consumes during restart-point reconstruction;
#   ``recovery_workflow`` *triggers* Re-subscribe events that
#   ``subscribe_loop`` re-honours. The relationship is bidirectional
#   (ack-records flow loop→recovery, Re-subscribe-triggers flow
#   recovery→loop).
#
# The CMD-AC-6-7 layer accordingly inverts CMD-AC-2's direction: where
# CMD-AC-2 covers consumer→producer write-back wire-form, CMD-AC-6-7-2
# covers consumer→producer Re-subscribe-trigger wire-form (recovery
# triggers loop). The other three criteria mirror CMD-AC-1, CMD-AC-3,
# CMD-AC-4 with Welle-6+7-specific substrate.
#
# Doppel-Welle-1+2 (read-only-paar) carries no CMD-AC layer — no
# producer/consumer schema-touchpoint exists between v907_verify and
# svid_workload_identity.
# ---------------------------------------------------------------------------

# CMD-AC-6-7-3 — per-Komponente joint-consistency floor for Welle-6+7.
# Same 99.5% as CMD-AC-3 (Welle-4+5); ADR-0066-fixed across both
# Doppel-Wellen carrying the CMD-AC layer. Loosening per-DW requires
# an ADR-Folge-Item.
CROSS_MODUL_DRIFT_CONSISTENCY_WELLE_6_7_PCT_FLOOR = 0.995

# CMD-AC-6-7-4 — atomic-flip drift-threshold for Welle-6+7. Same 0.5pp
# as CMD-AC-4 (Welle-4+5); the threshold is the operationally-relevant
# bar across the two DWs.
CROSS_MODUL_DRIFT_ROLLBACK_WELLE_6_7_PCT_THRESHOLD = 0.5

# CMD-AC-6-7-2 — Re-subscribe-trigger taxonomy. recovery_workflow emits
# four Re-subscribe-trigger types during restart-point reconstruction
# (R1: cursor-restore, R2: connection-keepalive-replay, R3: backlog-
# replay, R4: terminal-archive-rebuild). All four must round-trip with
# byte-identical wire-form vs. the Python pendant.
CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS: tuple[str, ...] = (
    "R1-cursor-restore",
    "R2-keepalive-replay",
    "R3-backlog-replay",
    "R4-terminal-archive-rebuild",
)

# CMD-AC-6-7-2 — wire-form reference oracle for the Re-subscribe-trigger
# path. The Welle-6+7 oracle is single-valued (python-python-baseline)
# because the mid-Doppel-Welle hypothetical (python-rust-welle-6-only)
# is operationally unreachable: subscribe_loop and recovery_workflow
# share the same cutover-cycle by Doppel-Welle definition. The
# Python-Python production state is the only historical reference.
CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_ORACLES: tuple[str, ...] = (
    "python-python-baseline",
)


# ---------------------------------------------------------------------------
# CMD-AC-6-7-1 — subscribe_loop ack-record → recovery_workflow consume
#                round-trip byte-parity record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftWelle6_7AckConsumeRecord:
    """One ``subscribe_loop`` ack-record consumed by ``recovery_workflow``.

    ``subscribe_loop-rust`` emits an ack-record (NATS-ack envelope +
    subscription-cursor delta + keepalive-window snapshot) on each
    successful subscribe-cycle. ``recovery_workflow-rust`` consumes
    these records during restart-point reconstruction to compute the
    correct resume-cursor.

    CMD-AC-6-7-1 enforces byte-identical schema-deserialization across
    the Rust-producer × Rust-consumer cross-lang ack-record contract:

    * ``producer_ack_sha256`` — hash of bytes that
      ``subscribe_loop-rust`` emitted.
    * ``consumer_deserialized_reserialized_sha256`` — hash of bytes
      after ``recovery_workflow-rust`` deserialised + re-serialised
      the record to its canonical wire-form.
    * ``cursor_delta_round_trip_ok`` — the subscription-cursor delta
      field survives the deserialize→re-serialize round-trip without
      mutation. This is the Bug-42-Lessons-Learned-adjacent surface
      (cursor-serialisation drift would cause recovery to compute a
      wrong restart-point).
    """

    welle_pair: tuple[str, str]
    ack_record_id: str
    producer_ack_sha256: str
    consumer_deserialized_reserialized_sha256: str
    cursor_delta_round_trip_ok: bool

    @property
    def is_round_trip_parity(self) -> bool:
        return (
            self.producer_ack_sha256
            == self.consumer_deserialized_reserialized_sha256
            and self.cursor_delta_round_trip_ok
        )


@pytest.fixture
def mocked_cross_modul_drift_welle_6_7_ack_consume() -> Callable[
    ..., list[CrossModulDriftWelle6_7AckConsumeRecord]
]:
    """Fixture returning a CMD-AC-6-7-1 ack-record consume-builder.

    Default builder produces round-trip-parity-by-construction over a
    Welle-6+7-realistic ack-record set (subscribe-init, ack-cycle-N,
    cursor-advance, keepalive-snapshot). Tests inject:

    * ``drift_ack_ids`` — ack-record-ids that exhibit producer vs.
      consumer-reserialised hash drift (deserialization-mutation bug).
    * ``cursor_breakage_ids`` — ack-record-ids where the cursor-delta
      field is dropped or rewritten on round-trip (Bug-42-adjacent
      cursor-serialisation drift).
    """

    def _build(
        modul_a: str,
        modul_b: str,
        ack_record_ids: tuple[str, ...] = (
            "ack-subscribe-init",
            "ack-cycle-1",
            "ack-cycle-2",
            "ack-cursor-advance",
            "ack-keepalive-snapshot",
        ),
        drift_ack_ids: tuple[str, ...] = (),
        cursor_breakage_ids: tuple[str, ...] = (),
    ) -> list[CrossModulDriftWelle6_7AckConsumeRecord]:
        out: list[CrossModulDriftWelle6_7AckConsumeRecord] = []
        for ack_id in ack_record_ids:
            producer_hash = _envelope_hash(
                f"{modul_a}->{modul_b}",
                0,
                ack_id,
                salt="cmd-ac-6-7-1-producer",
            )
            if ack_id in drift_ack_ids:
                consumer_hash = _envelope_hash(
                    f"{modul_a}->{modul_b}",
                    0,
                    ack_id,
                    salt="cmd-ac-6-7-1-consumer-drift",
                )
            else:
                consumer_hash = producer_hash
            out.append(
                CrossModulDriftWelle6_7AckConsumeRecord(
                    welle_pair=(modul_a, modul_b),
                    ack_record_id=ack_id,
                    producer_ack_sha256=producer_hash,
                    consumer_deserialized_reserialized_sha256=consumer_hash,
                    cursor_delta_round_trip_ok=(
                        ack_id not in cursor_breakage_ids
                    ),
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-6-7-2 — recovery_workflow R1..R4 → subscribe_loop Re-subscribe
#                trigger wire-form parity record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftWelle6_7ResubscribeTriggerRecord:
    """One recovery→loop Re-subscribe-trigger wire-form record.

    ``recovery_workflow-rust`` emits one of four R1..R4 Re-subscribe-
    triggers during restart-point reconstruction:

    * R1: cursor-restore — resume from a stored subscription-cursor.
    * R2: keepalive-replay — replay the keepalive-window to re-arm.
    * R3: backlog-replay — replay buffered backlog messages.
    * R4: terminal-archive-rebuild — rebuild from terminal-archive.

    ``subscribe_loop-rust`` honours each trigger by emitting a Re-
    subscribe-event whose wire-form must be byte-identical to the
    Python-pendant's output for the same logical trigger.

    CMD-AC-6-7-2 enforces wire-form byte-parity vs. the
    ``python-python-baseline`` oracle for every trigger-id.
    """

    welle_pair: tuple[str, str]
    trigger_id: str  # one of R1..R4 from CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS
    rust_rust_wire_sha256: str
    oracle_wire_sha256_by_oracle: dict[str, str]

    def matches_oracle(self, oracle: str) -> bool:
        return self.rust_rust_wire_sha256 == self.oracle_wire_sha256_by_oracle.get(
            oracle
        )


@pytest.fixture
def mocked_cross_modul_drift_welle_6_7_resubscribe_trigger() -> Callable[
    ..., list[CrossModulDriftWelle6_7ResubscribeTriggerRecord]
]:
    """Fixture returning a CMD-AC-6-7-2 Re-subscribe-trigger record builder.

    Default builder produces wire-form parity across the single
    ``python-python-baseline`` oracle for every R1..R4 trigger. Tests
    inject:

    * ``drift_trigger_ids`` — set of trigger-ids that show Rust-Rust vs.
      python-python-baseline wire-form divergence.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        trigger_ids: tuple[str, ...] = CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_IDS,
        drift_trigger_ids: tuple[str, ...] = (),
    ) -> list[CrossModulDriftWelle6_7ResubscribeTriggerRecord]:
        out: list[CrossModulDriftWelle6_7ResubscribeTriggerRecord] = []
        for trig_id in trigger_ids:
            rust_rust_hash = _envelope_hash(
                f"{modul_a}->{modul_b}",
                0,
                trig_id,
                salt="cmd-ac-6-7-2-rust-rust",
            )
            oracle_hashes: dict[str, str] = {}
            for oracle in CROSS_MODUL_DRIFT_WELLE_6_7_RECOVERY_TRIGGER_ORACLES:
                if trig_id in drift_trigger_ids:
                    oracle_hashes[oracle] = _envelope_hash(
                        f"{modul_a}->{modul_b}",
                        0,
                        trig_id,
                        salt=f"cmd-ac-6-7-2-{oracle}-drift",
                    )
                else:
                    oracle_hashes[oracle] = rust_rust_hash
            out.append(
                CrossModulDriftWelle6_7ResubscribeTriggerRecord(
                    welle_pair=(modul_a, modul_b),
                    trigger_id=trig_id,
                    rust_rust_wire_sha256=rust_rust_hash,
                    oracle_wire_sha256_by_oracle=oracle_hashes,
                )
            )
        return out

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-6-7-3 — Cross-Modul-Stress-Test per-Komponente consistency
#                ≥99.5% for Welle-6+7 (PR #197 substrate joint-load
#                broken out per Komponente, Welle-6+7-specific load).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftWelle6_7PerKomponenteConsistencyRecord:
    """One Welle-6+7 per-Komponente consistency record.

    Identical shape to ``CrossModulDriftPerKomponenteConsistencyRecord``
    (CMD-AC-3, Welle-4+5) but distinguished by type to anchor Welle-6+7-
    specific substrate wire-up. The PR #197 Cross-Modul-Stress-Test
    output emits Welle-6+7-specific per-Komponente consistency-rates:

    * ``subscribe_loop_consistency_rate`` — Rust-side NATS-subscribe-
      cycle consistency observed during joint-load (subscribe-event-
      flood profile).
    * ``recovery_workflow_consistency_rate`` — Rust-side restart-point-
      reconstruction consistency observed during the same window
      (recovery-restart-points simultaneous to the subscribe-flood).

    The joint-rate is computed as ``min(rate_a, rate_b)`` — both per-
    Komponente rates must clear the 0.995 floor for the gate to pass.
    """

    welle_pair: tuple[str, str]
    total_request_count: int
    modul_a_consistency_rate: float
    modul_b_consistency_rate: float

    @property
    def joint_consistency_rate(self) -> float:
        return min(self.modul_a_consistency_rate, self.modul_b_consistency_rate)


@pytest.fixture
def mocked_cross_modul_drift_welle_6_7_per_komponente_consistency() -> Callable[
    ..., CrossModulDriftWelle6_7PerKomponenteConsistencyRecord
]:
    """Fixture returning a CMD-AC-6-7-3 per-Komponente consistency builder.

    Default builder produces both rates at 0.999 (above 0.995 floor).
    Tests inject ``modul_a_rate`` / ``modul_b_rate`` overrides to
    exercise the per-Komponente floor logic on the Welle-6+7 substrate.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        total: int = 2000,
        modul_a_rate: float = 0.999,
        modul_b_rate: float = 0.999,
    ) -> CrossModulDriftWelle6_7PerKomponenteConsistencyRecord:
        return CrossModulDriftWelle6_7PerKomponenteConsistencyRecord(
            welle_pair=(modul_a, modul_b),
            total_request_count=total,
            modul_a_consistency_rate=modul_a_rate,
            modul_b_consistency_rate=modul_b_rate,
        )

    return _build


# ---------------------------------------------------------------------------
# CMD-AC-6-7-4 — Drift-triggered atomic single-Komponente rollback
#                record for Welle-6+7 (atomic-flip-pattern, ≤10min SLA).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossModulDriftWelle6_7AtomicFlipRecord:
    """One CMD-AC-6-7-4 drift-triggered atomic-flip rollback record.

    Identical shape to ``CrossModulDriftAtomicFlipRecord`` (CMD-AC-4,
    Welle-4+5) but distinguished by type to anchor Welle-6+7-specific
    operator-hand-runbook wire-up. The atomic-flip-pattern means:

    * When measured cross-modul-drift exceeds 0.5pp on exactly one of
      the two Welle-6+7 moduln, that modul flips back to python while
      the partner stays on rust-Default (atomic single-Komponente
      rollback).
    * The flip is single-shot (one ``systemctl restart`` cycle) and
      completes within the 10min ENV-Flag-Switch SLA (600s).
    * Welle-6+7-specific risk: a recovery_workflow rollback delays
      Phase-3c-Ende + ADR-0035-C-Drift-Closure by ≥1 week because
      recovery is the last welle. The atomic-flip discipline reduces
      blast-radius vs. a both-modul rollback.

    Gates: same shape as CMD-AC-4 — trigger-precondition (drift >
    threshold), atomicity flag, post-flip backend-state per modul,
    elapsed-seconds ≤ ROLLBACK_SLA_SECONDS.
    """

    welle_pair: tuple[str, str]
    high_drift_modul: str
    measured_drift_pct: float
    threshold_drift_pct: float
    flip_elapsed_seconds: float
    flip_was_atomic: bool
    post_flip_backend_per_modul: dict[str, str]


@pytest.fixture
def mocked_cross_modul_drift_welle_6_7_atomic_flip() -> Callable[
    ..., CrossModulDriftWelle6_7AtomicFlipRecord
]:
    """Fixture returning a CMD-AC-6-7-4 atomic-flip record builder.

    Default builder produces a successful atomic-flip (high-drift modul
    rolled back to python, partner stays rust, elapsed = 180s, atomic
    flag True). Tests inject the same failure-modes as CMD-AC-4:

    * ``measured_drift_pct`` below threshold → spurious flip rejected.
    * ``flip_elapsed_seconds`` > 600 → SLA-violation.
    * ``partner_also_flipped=True`` → contagion failure-mode.
    * ``flip_was_atomic=False`` → non-atomic multi-cycle flip.
    """

    def _build(
        modul_a: str,
        modul_b: str,
        high_drift_modul: str,
        measured_drift_pct: float = 0.8,
        flip_elapsed_seconds: float = 180.0,
        flip_was_atomic: bool = True,
        partner_also_flipped: bool = False,
    ) -> CrossModulDriftWelle6_7AtomicFlipRecord:
        partner = modul_b if high_drift_modul == modul_a else modul_a
        post_state = {modul: "python" for _, modul in WELLE_ORDER}
        if not partner_also_flipped:
            post_state[partner] = "rust"
        return CrossModulDriftWelle6_7AtomicFlipRecord(
            welle_pair=(modul_a, modul_b),
            high_drift_modul=high_drift_modul,
            measured_drift_pct=measured_drift_pct,
            threshold_drift_pct=CROSS_MODUL_DRIFT_ROLLBACK_WELLE_6_7_PCT_THRESHOLD,
            flip_elapsed_seconds=flip_elapsed_seconds,
            flip_was_atomic=flip_was_atomic,
            post_flip_backend_per_modul=post_state,
        )

    return _build
