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
# Welle-3 Henrik-Caution Acceptance-Kriterien — HC-AC-1 ... HC-AC-3
#
# Anchor: ADR-0066 §Beschluss + §Mitigations — Welle-3 ("bridge_audit_
# writer") is the only Solo-Welle in the Phase-3c-Cadence, explicitly
# carved out under Henrik-Caution. The bridge-audit-writer *is* the
# consistency-oracle substrate for the other six wellen; flipping its
# own write-path to Rust-default while it remains the audit-trail-
# producer requires an extra layer of acceptance criteria beyond
# AC-1...AC-5.
#
# Three HC-AC criteria specialise the welle-3 solo-cutover:
#
# * HC-AC-1: Bridge-Audit-Writer-Output independently validated by a
#   Phase-2-Cross-Modul-Stress-Test sample. The stress-test does NOT
#   use the bridge-audit-writer as its consistency-oracle (that would
#   be self-referential); instead it uses the hold-out Python-pinned
#   writer instance from the Welle-3 Cutover-Mittwoch substrate
#   (ADR-0065 §Empfehlung Footnote).
# * HC-AC-2: Welle-3-Rollback triggered automatically when observed
#   divergence between the new Rust-writer and the hold-out Python-
#   writer exceeds 0.5% of the request-window. Atomic ENV-Flag-switch
#   ≤ROLLBACK_SLA_SECONDS (600s).
# * HC-AC-3: Pre-Cutover-Konsistenz-Baseline established from a
#   7-Tage-Observability-Window before the Cutover-Mittwoch. All seven
#   days must pass the consistency-floor (≥99.5% green-rate) to enable
#   the cutover-trigger.
# ---------------------------------------------------------------------------

# HC-AC-2 divergence-rollback threshold: any observed Bridge-Audit-
# Writer divergence ≥0.5% over the per-day request-window forces an
# atomic rollback. Tighter than AC-1's 5/5-days-green gate because
# the bridge_audit_writer is the *meta*-modul (it produces the
# consistency-reports for the other six wellen — a single drift here
# poisons downstream audit-trails).
HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD = 0.5

# HC-AC-3 pre-cutover-baseline window: seven consecutive days of
# bridge_audit_writer observability with ≥99.5% per-day consistency-
# rate before the Cutover-Mittwoch can fire. Mirrors the
# CONSISTENCY_REPORT_WINDOW_DAYS=5 post-cutover discipline but extends
# the pre-cutover side to the Henrik-Caution-requested 7-day floor.
HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS = 7
HENRIK_CAUTION_PRE_CUTOVER_BASELINE_GREEN_RATE = 0.995


@dataclass(frozen=True)
class HenrikCautionStressSampleRecord:
    """HC-AC-1 oracle — Phase-2-Cross-Modul-Stress-Test sample of the
    Bridge-Audit-Writer output, validated by the hold-out Python-pinned
    writer-instance (NOT by the writer-under-cutover itself; that would
    be self-referential).

    Captures:
    * ``stress_window_request_count`` — total writes observed.
    * ``holdout_validated_count`` — writes the hold-out Python-writer
      confirmed byte-paritär against the new Rust-writer output.
    * ``stress_test_source`` — provenance tag identifying the Phase-2
      stress-test substrate (Tomás Tag-29 reference).
    * ``oracle_independence_confirmed`` — boolean flag attesting that
      the stress-test consistency-oracle is the hold-out Python-writer
      (not the new Rust-writer-under-cutover).

    HC-AC-1 gates require: holdout_validated_count ==
    stress_window_request_count AND oracle_independence_confirmed.
    """

    welle: str
    stress_window_request_count: int
    holdout_validated_count: int
    stress_test_source: str
    oracle_independence_confirmed: bool


@dataclass(frozen=True)
class HenrikCautionDivergenceRollbackRecord:
    """HC-AC-2 oracle — Welle-3-Rollback record for a divergence-
    triggered atomic ENV-Flag-switch.

    Captures:
    * ``observed_divergence_pct`` — measured divergence between the
      new Rust-writer and the hold-out Python-writer (% of requests
      with non-matching anchor-hash over the per-day window).
    * ``threshold_pct`` — HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD copy
      stamped in for audit-trail clarity.
    * ``rollback_triggered`` — boolean flag indicating whether the
      rollback fired (must be True when divergence ≥ threshold; must
      be False when divergence < threshold).
    * ``rollback_elapsed_seconds`` — ENV-Flag-switch elapsed-time;
      ≤ROLLBACK_SLA_SECONDS gate when rollback_triggered=True.
    * ``post_rollback_backend`` — bridge_audit_writer post-state
      (must be ``python`` when rollback_triggered=True).
    * ``env_flag_switch_atomic`` — boolean attesting the ENV-Flag-
      switch was atomic (single Quadlet-rewrite, single systemctl-
      restart, no partial-state-window).

    HC-AC-2 gates:
    * If observed_divergence_pct ≥ threshold_pct →
      rollback_triggered must be True, env_flag_switch_atomic must be
      True, rollback_elapsed_seconds ≤ ROLLBACK_SLA_SECONDS,
      post_rollback_backend == "python".
    * If observed_divergence_pct < threshold_pct → rollback_triggered
      must be False (no spurious rollback).
    """

    welle: str
    observed_divergence_pct: float
    threshold_pct: float
    rollback_triggered: bool
    rollback_elapsed_seconds: float
    post_rollback_backend: str
    env_flag_switch_atomic: bool


@dataclass(frozen=True)
class HenrikCautionPreCutoverBaselineRecord:
    """HC-AC-3 oracle — Pre-Cutover 7-Tage-Observability-Window record.

    Captures, day-by-day for HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS
    consecutive days, the per-day consistency-rate of the bridge_audit_
    writer (already-deployed Python-only baseline, no Rust-writer yet).

    Each day's consistency-rate is the fraction of requests with no
    intra-Python-writer drift (e.g. concurrent-write races, anchor-
    submission-failures retry-redundancy).

    HC-AC-3 gates:
    * Exactly HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS days observed.
    * Every day's consistency_rate ≥
      HENRIK_CAUTION_PRE_CUTOVER_BASELINE_GREEN_RATE.
    * Window contiguous (no gaps in day_index).
    """

    welle: str
    per_day_consistency_rate: dict[int, float] = field(default_factory=dict)


@pytest.fixture
def mocked_henrik_caution_stress_sample() -> Callable[
    ..., HenrikCautionStressSampleRecord
]:
    """Fixture returning a HenrikCautionStressSampleRecord builder.

    Default builder produces a happy-path record (full hold-out
    validation, oracle-independence confirmed). The welle-test
    injects:

    * ``holdout_validated_count < stress_window_request_count`` —
      partial hold-out validation; HC-AC-1 must surface this gap.
    * ``oracle_independence_confirmed=False`` — the stress-test
      accidentally used the Rust-writer as its own consistency-oracle
      (self-referential validation); HC-AC-1 must reject this shape.
    """

    def _build(
        welle: str,
        stress_window_request_count: int = 5000,
        holdout_validated_count: int | None = None,
        stress_test_source: str = "phase-2-cross-modul-stress-test:tomas-tag-29",
        oracle_independence_confirmed: bool = True,
    ) -> HenrikCautionStressSampleRecord:
        if holdout_validated_count is None:
            holdout_validated_count = stress_window_request_count
        return HenrikCautionStressSampleRecord(
            welle=welle,
            stress_window_request_count=stress_window_request_count,
            holdout_validated_count=holdout_validated_count,
            stress_test_source=stress_test_source,
            oracle_independence_confirmed=oracle_independence_confirmed,
        )

    return _build


@pytest.fixture
def mocked_henrik_caution_divergence_rollback() -> Callable[
    ..., HenrikCautionDivergenceRollbackRecord
]:
    """Fixture returning a HenrikCautionDivergenceRollbackRecord
    builder.

    Default builder produces a no-rollback record (divergence below
    threshold, no rollback fired). The welle-test injects:

    * ``observed_divergence_pct`` above threshold + matching
      ``rollback_triggered=True`` → HC-AC-2 happy-path for the
      divergence-rollback direction.
    * ``observed_divergence_pct`` above threshold +
      ``rollback_triggered=False`` → missed-rollback failure-mode.
    * ``rollback_elapsed_seconds`` > ROLLBACK_SLA_SECONDS →
      SLA-violation failure-mode.
    * ``env_flag_switch_atomic=False`` → non-atomic-rollback
      failure-mode (partial-state-window).
    """

    def _build(
        welle: str,
        observed_divergence_pct: float = 0.1,
        rollback_triggered: bool | None = None,
        rollback_elapsed_seconds: float = 180.0,
        post_rollback_backend: str | None = None,
        env_flag_switch_atomic: bool = True,
    ) -> HenrikCautionDivergenceRollbackRecord:
        if rollback_triggered is None:
            rollback_triggered = (
                observed_divergence_pct
                >= HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD
            )
        if post_rollback_backend is None:
            post_rollback_backend = "python" if rollback_triggered else "rust"
        return HenrikCautionDivergenceRollbackRecord(
            welle=welle,
            observed_divergence_pct=observed_divergence_pct,
            threshold_pct=HENRIK_CAUTION_DIVERGENCE_PCT_THRESHOLD,
            rollback_triggered=rollback_triggered,
            rollback_elapsed_seconds=rollback_elapsed_seconds,
            post_rollback_backend=post_rollback_backend,
            env_flag_switch_atomic=env_flag_switch_atomic,
        )

    return _build


@pytest.fixture
def mocked_henrik_caution_pre_cutover_baseline() -> Callable[
    ..., HenrikCautionPreCutoverBaselineRecord
]:
    """Fixture returning a HenrikCautionPreCutoverBaselineRecord builder.

    Default builder produces a full-7-day window with all days at
    99.8% consistency (above the 99.5% floor). The welle-test injects:

    * ``per_day_overrides`` — selectively lower specific days below
      threshold to verify the gate fires.
    * ``observed_days`` shorter than 7 → window-incomplete failure-mode.
    """

    def _build(
        welle: str,
        observed_days: int = HENRIK_CAUTION_PRE_CUTOVER_BASELINE_DAYS,
        default_rate: float = 0.998,
        per_day_overrides: dict[int, float] | None = None,
    ) -> HenrikCautionPreCutoverBaselineRecord:
        per_day = {day: default_rate for day in range(observed_days)}
        if per_day_overrides:
            for day, rate in per_day_overrides.items():
                per_day[day] = rate
        return HenrikCautionPreCutoverBaselineRecord(
            welle=welle,
            per_day_consistency_rate=per_day,
        )

    return _build
