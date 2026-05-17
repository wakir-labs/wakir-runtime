# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Shared fixtures for the Phase-3c-Acceptance E2E test-suite skeleton.

Anchors
-------

- ADR-0065 §Verifikations-Plan — the welle-for-welle acceptance
  criteria (AC-1 ... AC-5) that this suite enforces, one test-file
  per welle (welle-1 ... welle-7).
- ADR-0063 §Phase-3c-Final-Cutover — the wider 7-welle cutover plan
  these E2E tests gate.
- ``docs/quality-gates/phase-3c-acceptance-criteria.md`` (Amara,
  this PR) — the welle-for-welle acceptance-criteria matrix.
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


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip phase_3c_acceptance-marked tests unless opt-in is present.

    Either the CLI flag or the env-var enables the skeleton. The
    skip-marker is added at collection-time so default CI runs see a
    clean fast-skip without import-evaluation surprises.
    """
    if config.getoption("--phase-3c-acceptance") or PHASE_3C_OPT_IN:
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "Phase-3c-Acceptance skeleton skip-by-default — opt in with "
            "WAKIR_PHASE_3C_E2E=1 env-var or --phase-3c-acceptance CLI "
            "flag (Phase-3c-trigger sprint ~KW 27+ flips this gate per "
            "ADR-0065)."
        )
    )
    for item in items:
        if "phase_3c_acceptance" in item.keywords:
            item.add_marker(skip_marker)


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
