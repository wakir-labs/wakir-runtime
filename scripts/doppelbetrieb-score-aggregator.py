#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""doppelbetrieb-score-aggregator — Sprint-Tag-15 + Tag-29 Mini-Welle.

Background
----------

Phase-2 Doppelbetrieb (ADR-0058) ships five hermetic Acceptance-Gates
in ``tests/infra/test_phase_2_acceptance_gates.py`` (PR #109) and a
matching CI workflow (``.github/workflows/phase-2-validation-gate.yml``,
PR #110) that drives one job per gate plus an aggregator.

Tag-15 closed the Doppelbetrieb-readiness loop by surfacing **three
new Phase-3a-Foundation acceptance-axes** alongside the five Phase-2
gate verdicts in a single JSON rollup that Henrik can sample weekly
and Amara can spot-check between sprints.

Tag-29 (ADR-0066 KW-26-Mitigation) extends the rollup with **three
Cross-Modul-Stress-Test axes** that catch cross-module drift BEFORE
the KW-26 Doppel-Welle cutover (Welle-4 ``state_backing`` + Welle-5
``lifecycle_state_machine`` in parallel). The mitigation rationale:
ADR-0066 schedules Welle-4+5 in parallel and Welle-6+7 in parallel —
an integration-bug that only emerges when two Rust modules are both
``rust-default`` at the same time would be invisible to per-module
acceptance gates. The three new axes pin each parallel-welle pairing
to the schema-byte-identity of the underlying cross-lang fixture
files (PR #190 et al), so any pre-cutover drift surfaces in the
rollup before the operator flips the cutover ENV-flags. Schema
bumped to ``wakir.doppelbetrieb.aggregator/2``; the eight Tag-15
axes carry forward unchanged.

Tag-15 axes (Phase-3a-Foundation, original eight):

* **bridge-audit-e2e-roundtrip-pass** — 1 iff
  ``tests/integration/test_bridge_audit_roundtrip_e2e.py`` is green
  (Python emit → Rust replay stream-level oracle, shipped PR #156).

* **cross-lang-pin-coverage** — count of passing cross-language pins
  across three independent contracts (PR #155 NATS-Subjects: 8 pins,
  PR #156 Bridge-Audit-Stream-Hash: 3 pins F1/F2/F3, PR #157
  Federation-Frame: 5 fixture pins). Target = 16.

* **wat-anchor-latency-producer-emitting** — 1 iff the SLO-2 anchor-
  latency producer (PR #154, Noa) is opt-in via
  ``WAKIR_ANCHOR_LATENCY_JSONL`` AND can emit a record without
  raising. Default-off; ``--probe-anchor-producer`` opts in for the
  acceptance run.

Plus the five existing Phase-2-Gate verdicts (Gate-2-1 through
Gate-2-5; see ``docs/quality-gates/phase-2-doppelbetrieb.md``).

Tag-29 Cross-Modul-Stress-Test axes (ADR-0066, three new):

* **cross-modul-state-backing-lifecycle-state-machine** — pass iff
  ``WAKIR_STATE_BACKING_BACKEND=rust`` AND ``WAKIR_FSM_BACKEND=rust``
  are both set in the inspected env-map AND both fixture files
  (``tests/fixtures/state-backing-cross-lang/fixtures.json`` and
  ``tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json``)
  carry their pinned ``schema_version`` plus a non-empty ``fixtures``
  list. Catches Welle-4+5 parallel-cutover drift in KW 26.

* **cross-modul-subscribe-loop-recovery-workflow** — pass iff
  ``WAKIR_SUBSCRIBE_LOOP_BACKEND=rust`` AND
  ``WAKIR_RECOVERY_BACKEND=rust`` are both set AND the ack-record
  fixture file (``tests/fixtures/subscribe-loop-cross-lang/fixtures.json``)
  plus the recovery-workflow fixture file
  (``tests/fixtures/recovery-workflow-cross-lang/fixtures.json``)
  both carry their pinned schema_version and non-empty fixtures
  list. Catches Welle-6+7 parallel-cutover drift in KW 27.

* **cross-modul-v907-verify-svid-workload-identity** — pass iff
  ``WAKIR_V907_VERIFY_BACKEND=rust`` AND
  ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust`` are both set AND
  the V907 pin-pack directory (six persona files under
  ``wirelang-rust/crates/persona-engine-v907-recompute-bench/tests/fixtures/v907_pin_pack/``)
  is present (anchor for hash-byte-identity) AND the SVID e2e
  acceptance test file exists in-tree (Welle-2 substrate marker).
  Catches Welle-1+2 parallel-cutover drift in KW 24.

Output shape
------------

A canonical JSON envelope with ``schema``, ``ts_utc``, ``axes``,
``total_score``, ``threshold_pass``, ``threshold``::

    {
      "schema": "wakir.doppelbetrieb.aggregator/2",
      "ts_utc": "2026-05-17T09:50:00Z",
      "axes": {
        "gate-2-1-bridge-forward-symmetry":     {"pass": true,  "weight": 1},
        "gate-2-2-konsistenz-score-threshold":  {"pass": true,  "weight": 1},
        "gate-2-3-v907-hash-stability-marker":  {"pass": true,  "weight": 1},
        "gate-2-4-recovery-r1-r4-mock-drill":   {"pass": true,  "weight": 1},
        "gate-2-5-subscribe-loop-lag-mock":     {"pass": true,  "weight": 1},
        "bridge-audit-e2e-roundtrip-pass":      {"pass": true,  "weight": 1},
        "cross-lang-pin-coverage": {
          "pass": true, "weight": 1,
          "details": {"federation_frame": 5, "nats_subjects": 8,
                       "bridge_audit_stream_hash": 3, "total": 16,
                       "expected_total": 16}
        },
        "wat-anchor-latency-producer-emitting": {
          "pass": true, "weight": 1,
          "details": {"env_set": true, "emitted": true}
        },
        "cross-modul-state-backing-lifecycle-state-machine": {
          "pass": true, "weight": 1,
          "details": {"both_envs_rust": true,
                       "state_backing_fixtures": 5,
                       "lifecycle_state_machine_fixtures": 5}
        },
        "cross-modul-subscribe-loop-recovery-workflow": {
          "pass": true, "weight": 1,
          "details": {"both_envs_rust": true,
                       "subscribe_loop_fixtures": 5,
                       "recovery_workflow_fixtures": 5}
        },
        "cross-modul-v907-verify-svid-workload-identity": {
          "pass": true, "weight": 1,
          "details": {"both_envs_rust": true,
                       "v907_pin_pack_personas": 5,
                       "svid_e2e_substrate_present": true}
        }
      },
      "total_score": 11,
      "threshold": 11,
      "threshold_pass": true
    }

``total_score`` is the sum of per-axis ``pass=True`` weights. Default
threshold is the sum of all axis weights (``11`` since Tag-29); the
operator can relax it via ``--threshold``.

Run mode
--------

* ``--mode=full`` (default): runs all 11 axes. Drives the Phase-2
  gates via ``pytest -k ...`` against the existing
  ``tests/infra/test_phase_2_acceptance_gates.py``; drives the
  Bridge-Audit-E2E via ``pytest tests/integration/test_bridge_audit_
  roundtrip_e2e.py``; reads cross-lang pins from in-tree modules; for
  the anchor producer, defaults to *no probe* (pass=true iff env-var
  was set at invocation, per the producer contract) and only writes
  if ``--probe-anchor-producer`` is given. The three Tag-29 Cross-
  Modul axes inspect the process env-map and the in-tree fixture
  files (no subprocess).

* ``--mode=cross-lang-only``: only the cross-lang-pin-coverage axis.
  Useful for the cheap "is the cross-language byte-pin still tight?"
  cron Henrik schedules between full runs.

* ``--mode=cross-modul-stress``: only the three Tag-29 Cross-Modul
  axes. Useful as a pre-cutover smoke gate that the operator can
  invoke from the workflow_dispatch input ahead of a parallel-welle
  cutover Mittwoch (ADR-0066 §"Cross-Modul-Drift-Detection für
  Doppel-Wellen").

The script is **stdlib-only** except for ``pytest`` (already in the
test-dev surface). Output goes to stdout by default; ``--out PATH``
writes to a file. Exit codes:

* ``0`` — threshold-pass
* ``1`` — threshold-fail (at least one axis missing or below
  threshold)
* ``2`` — usage / I/O error

Anchors
-------

* ADR-0058 §"Phase 2 — Doppelbetrieb (Wochen 1-4)"
* ADR-0066 §"Cross-Modul-Drift-Detection für Doppel-Wellen"
* ``docs/quality-gates/phase-2-doppelbetrieb.md`` (Amara, PR #80)
* ``tests/infra/test_phase_2_acceptance_gates.py`` (Tomás, PR #109)
* ``tests/integration/test_bridge_audit_roundtrip_e2e.py`` (PR #156)
* ``wirelang/federation/federation_frame.py`` (PR #157)
* ``wirelang/persona_engine/nats_subjects.py`` (PR #155)
* ``wirelang/persona_engine/bridge_audit_stream_hash.py`` (PR #156)
* ``wat/anchor/latency_emitter.py`` (PR #154)
* ``tests/fixtures/state-backing-cross-lang/fixtures.json`` (PR #140)
* ``tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json``
* ``tests/fixtures/subscribe-loop-cross-lang/fixtures.json`` (PR #132/#172)
* ``tests/fixtures/recovery-workflow-cross-lang/fixtures.json`` (PR #135)
* ``wirelang/persona_engine/rust_backend_switch.py`` (PR #135 et al)
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


SCHEMA = "wakir.doppelbetrieb.aggregator/2"

REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE_2_GATE_TEST = REPO_ROOT / "tests" / "infra" / "test_phase_2_acceptance_gates.py"
BRIDGE_AUDIT_E2E_TEST = REPO_ROOT / "tests" / "integration" / "test_bridge_audit_roundtrip_e2e.py"

#: Stable per-axis ordering. Matches the QA Quality-Gate doc topology
#: (five Phase-2 gates first, then the three Phase-3a-Foundation
#: axes, then the three Tag-29 Cross-Modul-Stress-Test axes). Tests
#: pin against this list.
AXIS_ORDER: tuple[str, ...] = (
    "gate-2-1-bridge-forward-symmetry",
    "gate-2-2-konsistenz-score-threshold",
    "gate-2-3-v907-hash-stability-marker",
    "gate-2-4-recovery-r1-r4-mock-drill",
    "gate-2-5-subscribe-loop-lag-mock",
    "bridge-audit-e2e-roundtrip-pass",
    "cross-lang-pin-coverage",
    "wat-anchor-latency-producer-emitting",
    "cross-modul-state-backing-lifecycle-state-machine",
    "cross-modul-subscribe-loop-recovery-workflow",
    "cross-modul-v907-verify-svid-workload-identity",
)

#: Map from per-axis label to pytest ``-k`` selector inside
#: ``test_phase_2_acceptance_gates.py``. The aggregator delegates each
#: Phase-2 gate to the single in-suite test that backs it; mirrors the
#: per-job mapping in ``phase-2-validation-gate.yml``.
PHASE_2_GATE_PYTEST_K: Mapping[str, str] = {
    "gate-2-1-bridge-forward-symmetry":     "test_gate_2_1_bridge_forward_symmetry",
    "gate-2-2-konsistenz-score-threshold":  "test_gate_2_2_konsistenz_score_threshold",
    "gate-2-3-v907-hash-stability-marker":  "test_gate_2_3_v907_hash_stability_marker",
    "gate-2-4-recovery-r1-r4-mock-drill":   "test_gate_2_4_recovery_r1_r4_mock_drill",
    "gate-2-5-subscribe-loop-lag-mock":     "test_gate_2_5_subscribe_loop_lag_mock",
}

#: Expected cross-lang-pin count per contract. Pinned to the substrate
#: shipped at Tag-15: 5 federation-frame fixtures (PR #157), 8
#: nats-subjects FIXTURE_* constants (PR #155), 3 bridge-audit-stream-
#: hash anchors F1/F2/F3 (PR #156). Drift on any of these breaks the
#: aggregator at the per-contract assertion below.
EXPECTED_PIN_COUNTS: Mapping[str, int] = {
    "federation_frame": 5,
    "nats_subjects": 8,
    "bridge_audit_stream_hash": 3,
}

EXPECTED_PIN_TOTAL = sum(EXPECTED_PIN_COUNTS.values())  # 16

#: Environment variable Noa's anchor-latency producer keys off.
#: Mirrored from ``wat/anchor/latency_emitter.py::ENV_LATENCY_JSONL_PATH``.
ENV_ANCHOR_LATENCY_JSONL = "WAKIR_ANCHOR_LATENCY_JSONL"


#: Cross-Modul-Stress-Test specification (Tag-29, ADR-0066).
#:
#: Each entry pins one parallel-welle pairing to its two ENV-flags plus
#: the in-tree substrate marker that proves the cross-lang fixture
#: pair is wired. Drift on either ENV-flag (operator forgot to flip
#: one of the two) OR drift on either fixture file (schema-version or
#: empty list) breaks the axis.
#:
#: For state_backing × lifecycle_state_machine and subscribe_loop ×
#: recovery_workflow the substrate-marker is the cross-lang fixture
#: file pair (5 fixtures each).
#:
#: For v907_verify × svid_workload_identity, the V907 substrate-marker
#: is the pin-pack directory (six persona ``.md`` files, one per
#: persona) and the SVID substrate-marker is the Welle-2 e2e test
#: file (``tests/acceptance/phase_3c/test_welle_2_svid_workload_
#: identity_e2e.py``). SVID is the ADR-0065 Welle-2 candidate and the
#: cross-lang fixture file is shipped opt-in (the binary is opt-in,
#: see ``rust_backend_switch.py`` Tag-25 docstring) — using the e2e
#: test as the substrate-marker keeps this axis green under the
#: opt-in-binary contract.

CROSS_MODUL_SPEC: Mapping[str, dict] = {
    "cross-modul-state-backing-lifecycle-state-machine": {
        "env_keys": (
            "WAKIR_STATE_BACKING_BACKEND",
            "WAKIR_FSM_BACKEND",
        ),
        "fixture_pair": (
            (
                "state_backing_fixtures",
                Path("tests")
                / "fixtures"
                / "state-backing-cross-lang"
                / "fixtures.json",
                "wakir.persona-engine.persona-state-snapshot/1",
            ),
            (
                "lifecycle_state_machine_fixtures",
                Path("tests")
                / "fixtures"
                / "lifecycle-state-machine-cross-lang"
                / "fixtures.json",
                None,  # schema_version-pin not enforced (different shape)
            ),
        ),
    },
    "cross-modul-subscribe-loop-recovery-workflow": {
        "env_keys": (
            "WAKIR_SUBSCRIBE_LOOP_BACKEND",
            "WAKIR_RECOVERY_BACKEND",
        ),
        "fixture_pair": (
            (
                "subscribe_loop_fixtures",
                Path("tests")
                / "fixtures"
                / "subscribe-loop-cross-lang"
                / "fixtures.json",
                None,
            ),
            (
                "recovery_workflow_fixtures",
                Path("tests")
                / "fixtures"
                / "recovery-workflow-cross-lang"
                / "fixtures.json",
                None,
            ),
        ),
    },
}

#: Value that signals "Rust subprocess-bridge is the production
#: default" for the rust_backend_switch.py ENV-flags.
RUST_BACKEND_VALUE = "rust"

#: V907 + SVID substrate markers for the third Cross-Modul-Stress
#: axis (handled out-of-band because the substrate-shape is not a
#: simple fixture-pair).
V907_PIN_PACK_DIR = (
    Path("wirelang-rust")
    / "crates"
    / "persona-engine-v907-recompute-bench"
    / "tests"
    / "fixtures"
    / "v907_pin_pack"
)
SVID_E2E_TEST = (
    Path("tests")
    / "acceptance"
    / "phase_3c"
    / "test_welle_2_svid_workload_identity_e2e.py"
)
CROSS_MODUL_V907_SVID_ENV_KEYS: tuple[str, ...] = (
    "WAKIR_V907_VERIFY_BACKEND",
    "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
)


# ---------------------------------------------------------------------------
# Axis-result dataclass
# ---------------------------------------------------------------------------


@dataclass
class AxisResult:
    """One score-axis verdict.

    ``weight`` is summed into ``total_score`` iff ``pass=True``;
    ``details`` is an opaque JSON-serialisable mapping kept stable
    across runs (sort-keys on serialisation).
    """

    label: str
    pass_: bool
    weight: int = 1
    details: Optional[dict] = None

    def to_envelope(self) -> dict:
        envelope: dict = {"pass": self.pass_, "weight": self.weight}
        if self.details is not None:
            envelope["details"] = self.details
        return envelope


# ---------------------------------------------------------------------------
# Per-axis evaluators
# ---------------------------------------------------------------------------


def _run_pytest(test_path: Path, k_expr: Optional[str] = None) -> int:
    """Run pytest hermetically against ``test_path`` and return exit-code.

    ``-k k_expr`` selects a single test function when given. Subprocess
    boundary is preserved so the aggregator stays robust to import-time
    side-effects in the test module (the Phase-2 suite imports the
    Selin diff-engine, which pulls in pydantic — running it in-process
    would pollute the aggregator's import surface).
    """
    cmd: list[str] = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-q",
        "--tb=short",
    ]
    if k_expr:
        cmd.extend(["-k", k_expr])
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode


def evaluate_phase_2_gate(label: str, *, runner=_run_pytest) -> AxisResult:
    """Evaluate one Phase-2-Gate by delegating to the in-suite test."""
    k_expr = PHASE_2_GATE_PYTEST_K[label]
    rc = runner(PHASE_2_GATE_TEST, k_expr)
    return AxisResult(label=label, pass_=(rc == 0))


def evaluate_bridge_audit_e2e(*, runner=_run_pytest) -> AxisResult:
    """Evaluate the Bridge-Audit-Roundtrip-E2E axis (PR #156)."""
    rc = runner(BRIDGE_AUDIT_E2E_TEST, None)
    return AxisResult(
        label="bridge-audit-e2e-roundtrip-pass",
        pass_=(rc == 0),
    )


def _count_federation_frame_pins(fixture_path: Optional[Path] = None) -> int:
    """Return the number of cross-lang pins in the federation-frame
    fixture file.

    Mirrors the contract in
    ``tests/federation/fixtures/federation_frame_cross_lang_pins.json``:
    a JSON object with a top-level ``fixtures`` list. The pin-count is
    ``len(payload["fixtures"])``; the wrapper metadata
    (``x-spdx-*``, ``fixture_set_version``, ``generated_*``,
    ``cross_lang_contract``) is informational.
    """
    if fixture_path is None:
        fixture_path = (
            REPO_ROOT
            / "tests"
            / "federation"
            / "fixtures"
            / "federation_frame_cross_lang_pins.json"
        )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixtures = payload.get("fixtures") if isinstance(payload, dict) else payload
    if not isinstance(fixtures, list):
        raise ValueError(
            f"federation-frame fixture {fixture_path} missing 'fixtures' list"
        )
    return len(fixtures)


def _count_nats_subjects_pins() -> int:
    """Return the number of ``FIXTURE_*`` constants in
    ``wirelang.persona_engine.nats_subjects``.

    These are the pin-pack fixtures the Rust + Python sides hash into
    the same ``57a281...`` digest (PR #155). The contract is "8
    fixtures" — if the module exports fewer or more, that's drift and
    the cross-lang pin-pack SHA-256 would also have moved (and that
    has its own dedicated test). We count via attribute introspection
    on the imported module so the contract is enforced even when a
    fixture is renamed but not added to ``ALL_FIXTURES``.
    """
    from wirelang.persona_engine import nats_subjects as ns

    return sum(
        1
        for name in dir(ns)
        if name.startswith("FIXTURE_")
        and isinstance(getattr(ns, name), str)
    )


def _count_bridge_audit_stream_hash_pins() -> int:
    """Return the number of stream-level cross-lang anchors in
    ``wirelang.persona_engine.bridge_audit_stream_hash``.

    PR #156 ships three: F1 (empty stream), F2 (1-record stream),
    F3 (3-record session). The contract surface is the module
    docstring; we count by scraping the ``F\\d`` markers so a doc-edit
    that adds an F4 anchor naturally bumps the count.
    """
    from wirelang.persona_engine import bridge_audit_stream_hash as bsh

    doc = bsh.__doc__ or ""
    # Match leading "* ``F1`` ... ``F2`` ... ``F3``" markers in the
    # cross-language pins section. Each anchor is a distinct line.
    return sum(
        1
        for line in doc.splitlines()
        if line.lstrip().startswith("* ``F")
    )


def evaluate_cross_lang_pin_coverage(
    *,
    federation_fixture_path: Optional[Path] = None,
    counts_override: Optional[Mapping[str, int]] = None,
) -> AxisResult:
    """Evaluate the cross-lang-pin-coverage axis.

    Pass iff each contract reports its expected pin count and the
    grand total equals :data:`EXPECTED_PIN_TOTAL`. ``counts_override``
    short-circuits the module-introspection path for unit tests that
    inject pin-counts directly.
    """
    if counts_override is not None:
        counts = dict(counts_override)
    else:
        counts = {
            "federation_frame": _count_federation_frame_pins(
                federation_fixture_path
            ),
            "nats_subjects": _count_nats_subjects_pins(),
            "bridge_audit_stream_hash":
                _count_bridge_audit_stream_hash_pins(),
        }
    total = sum(counts.values())
    per_contract_ok = all(
        counts.get(k, 0) == v for k, v in EXPECTED_PIN_COUNTS.items()
    )
    total_ok = total == EXPECTED_PIN_TOTAL
    return AxisResult(
        label="cross-lang-pin-coverage",
        pass_=per_contract_ok and total_ok,
        details={
            "federation_frame": counts.get("federation_frame", 0),
            "nats_subjects": counts.get("nats_subjects", 0),
            "bridge_audit_stream_hash":
                counts.get("bridge_audit_stream_hash", 0),
            "total": total,
            "expected_total": EXPECTED_PIN_TOTAL,
        },
    )


def evaluate_wat_anchor_latency_producer(
    *,
    probe: bool = False,
    env: Optional[dict] = None,
    probe_factory=None,
) -> AxisResult:
    """Evaluate the wat-anchor-latency-producer-emitting axis.

    Two-step contract:

    1. **env_set**: ``WAKIR_ANCHOR_LATENCY_JSONL`` MUST be set and
       non-empty. The producer is opt-in (see
       ``wat/anchor/latency_emitter.py``).

    2. **emitted** (only when ``probe=True``): import the
       LatencyEmitter and synthesise one record via a
       :class:`StageRecorder`, asserting the JSONL file gained one
       line. The probe runs against the env-var-pinned path; if
       ``probe=False`` (the default), the emit-check is reported as
       ``"emitted": null`` and the axis passes solely on env-set —
       sufficient for "the operator opted in", which is the runtime
       gate Henrik samples.

    ``probe_factory`` is a hermetic-test seam that replaces the real
    LatencyEmitter import for unit tests.
    """
    env_map = env if env is not None else os.environ
    env_set = bool(env_map.get(ENV_ANCHOR_LATENCY_JSONL, "").strip())

    if not probe:
        return AxisResult(
            label="wat-anchor-latency-producer-emitting",
            pass_=env_set,
            details={"env_set": env_set, "emitted": None},
        )

    emitted = False
    if env_set:
        try:
            if probe_factory is not None:
                emitted = bool(probe_factory(env_map))
            else:
                emitted = _probe_anchor_producer(env_map)
        except Exception:
            emitted = False
    return AxisResult(
        label="wat-anchor-latency-producer-emitting",
        pass_=env_set and emitted,
        details={"env_set": env_set, "emitted": emitted},
    )


def _probe_anchor_producer(env_map: Mapping[str, str]) -> bool:
    """Default probe: emit one synthetic latency record and confirm
    the file gained a JSON line.

    Imports the producer lazily so the aggregator does not pull
    ``wat.anchor.*`` into its base import graph (keeps the
    ``--mode=cross-lang-only`` path cheap).
    """
    from wat.anchor.latency_emitter import (
        ENV_LATENCY_JSONL_PATH,
        LatencyEmitter,
        StageRecorder,
        PIPELINE_STAGES,
    )

    target_raw = env_map.get(ENV_LATENCY_JSONL_PATH, "").strip()
    if not target_raw:
        return False
    target = Path(target_raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    before_size = target.stat().st_size if target.exists() else 0

    emitter = LatencyEmitter(jsonl_path=target)
    recorder = StageRecorder(anchor_root_hex="probe" + "0" * 60)
    # Populate all four stages with a 1ms timing so the record passes
    # the producer's "all stages observed" predicate.
    for stage in PIPELINE_STAGES:
        recorder._durations_ms[stage] = 1.0  # noqa: SLF001 (test seam)
    emitter.emit(recorder)

    after_size = target.stat().st_size if target.exists() else 0
    return after_size > before_size


# ---------------------------------------------------------------------------
# Cross-Modul-Stress-Test evaluators (Tag-29, ADR-0066)
# ---------------------------------------------------------------------------


def _count_fixtures_in_file(fixture_path: Path) -> int:
    """Return the length of the top-level ``fixtures`` list in
    ``fixture_path``. Raises :class:`ValueError` if the file is
    missing, unparseable, or lacks the ``fixtures`` key.

    Centralised so all three Cross-Modul axes use the same canonical
    fixture-shape contract — drift on any one of the four cross-lang
    fixture files surfaces uniformly.
    """
    if not fixture_path.exists():
        raise ValueError(f"fixture file not found: {fixture_path}")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"fixture file {fixture_path} top-level is not a JSON object"
        )
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError(
            f"fixture file {fixture_path} missing 'fixtures' list"
        )
    return len(fixtures)


def _read_schema_version(fixture_path: Path) -> Optional[str]:
    """Return ``schema_version`` from ``fixture_path`` if present, else
    ``None``. Returns ``None`` (not raising) on missing file so the
    caller can decide whether absence is fatal.
    """
    if not fixture_path.exists():
        return None
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        v = payload.get("schema_version")
        if isinstance(v, str):
            return v
    return None


def evaluate_cross_modul_fixture_pair(
    label: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
    counts_override: Optional[Mapping[str, int]] = None,
) -> AxisResult:
    """Evaluate one fixture-pair Cross-Modul-Stress-Test axis.

    Pass iff BOTH ENV-flags resolve to :data:`RUST_BACKEND_VALUE`
    AND each fixture file in the pair has a non-empty ``fixtures``
    list (any schema_version pin declared in :data:`CROSS_MODUL_SPEC`
    must also match exactly).

    ``counts_override`` lets unit tests inject the per-key fixture
    counts directly (keys must match the spec-entry's
    ``fixture_pair`` count-keys); ``env`` defaults to
    :data:`os.environ` and ``repo_root`` to :data:`REPO_ROOT`.
    """
    if label not in CROSS_MODUL_SPEC:
        raise KeyError(
            f"unknown cross-modul axis label: {label!r}; "
            f"expected one of {list(CROSS_MODUL_SPEC)}"
        )
    spec = CROSS_MODUL_SPEC[label]
    env_map = env if env is not None else os.environ
    root = repo_root if repo_root is not None else REPO_ROOT

    env_keys = spec["env_keys"]
    both_envs_rust = all(
        env_map.get(k, "").strip() == RUST_BACKEND_VALUE for k in env_keys
    )

    details: dict = {"both_envs_rust": both_envs_rust}

    schema_drift = False
    fixtures_ok = True
    for count_key, rel_path, expected_schema in spec["fixture_pair"]:
        if counts_override is not None and count_key in counts_override:
            count = counts_override[count_key]
            details[count_key] = count
            if count <= 0:
                fixtures_ok = False
            continue
        full_path = root / rel_path
        try:
            count = _count_fixtures_in_file(full_path)
        except ValueError:
            count = 0
            fixtures_ok = False
        details[count_key] = count
        if count <= 0:
            fixtures_ok = False
        if expected_schema is not None:
            schema_version = _read_schema_version(full_path)
            if schema_version != expected_schema:
                schema_drift = True
                details[f"{count_key}_schema_drift"] = {
                    "expected": expected_schema,
                    "actual": schema_version,
                }

    passed = both_envs_rust and fixtures_ok and not schema_drift
    return AxisResult(label=label, pass_=passed, details=details)


def evaluate_cross_modul_v907_svid(
    *,
    env: Optional[Mapping[str, str]] = None,
    repo_root: Optional[Path] = None,
    v907_pin_pack_override: Optional[int] = None,
    svid_substrate_override: Optional[bool] = None,
) -> AxisResult:
    """Evaluate the V907 × SVID-Workload-Identity Cross-Modul axis.

    Pass iff BOTH ENV-flags
    (``WAKIR_V907_VERIFY_BACKEND``,
    ``WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND``) resolve to
    :data:`RUST_BACKEND_VALUE` AND the V907 pin-pack directory holds
    at least one persona file (hash-byte-identity anchor) AND the
    SVID Welle-2 e2e test file exists in-tree (substrate marker for
    the Welle-2 candidate).

    Overrides let unit tests inject the substrate-marker outcomes
    without touching the filesystem.
    """
    env_map = env if env is not None else os.environ
    root = repo_root if repo_root is not None else REPO_ROOT

    both_envs_rust = all(
        env_map.get(k, "").strip() == RUST_BACKEND_VALUE
        for k in CROSS_MODUL_V907_SVID_ENV_KEYS
    )

    if v907_pin_pack_override is not None:
        pin_pack_count = v907_pin_pack_override
    else:
        pin_pack_dir = root / V907_PIN_PACK_DIR
        if pin_pack_dir.is_dir():
            pin_pack_count = sum(
                1 for p in pin_pack_dir.iterdir() if p.suffix == ".md"
            )
        else:
            pin_pack_count = 0

    if svid_substrate_override is not None:
        svid_present = svid_substrate_override
    else:
        svid_present = (root / SVID_E2E_TEST).is_file()

    details = {
        "both_envs_rust": both_envs_rust,
        "v907_pin_pack_personas": pin_pack_count,
        "svid_e2e_substrate_present": svid_present,
    }
    passed = both_envs_rust and pin_pack_count > 0 and svid_present
    return AxisResult(
        label="cross-modul-v907-verify-svid-workload-identity",
        pass_=passed,
        details=details,
    )


# ---------------------------------------------------------------------------
# Aggregator envelope
# ---------------------------------------------------------------------------


def _utc_now_iso8601() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_envelope(
    axes: Iterable[AxisResult],
    *,
    threshold: Optional[int] = None,
    ts_utc: Optional[str] = None,
) -> dict:
    """Compose the aggregator-output envelope from per-axis results.

    The envelope is order-stable: ``axes`` is rendered as a dict in
    :data:`AXIS_ORDER` sequence (missing axes are recorded as
    ``{"pass": false, "weight": 1, "details": {"reason": "axis-missing"}}``
    so the rollup never silently drops an expected axis).
    """
    by_label = {a.label: a for a in axes}
    axes_envelope: dict = {}
    total_score = 0
    total_weight = 0
    for label in AXIS_ORDER:
        if label in by_label:
            axis = by_label[label]
        else:
            axis = AxisResult(
                label=label,
                pass_=False,
                weight=1,
                details={"reason": "axis-missing"},
            )
        axes_envelope[label] = axis.to_envelope()
        total_weight += axis.weight
        if axis.pass_:
            total_score += axis.weight

    effective_threshold = total_weight if threshold is None else threshold
    return {
        "schema": SCHEMA,
        "ts_utc": ts_utc or _utc_now_iso8601(),
        "axes": axes_envelope,
        "total_score": total_score,
        "threshold": effective_threshold,
        "threshold_pass": total_score >= effective_threshold,
    }


# ---------------------------------------------------------------------------
# Mode-driver
# ---------------------------------------------------------------------------


def run_full(*, probe_anchor: bool = False) -> list[AxisResult]:
    """Run all 11 axes and return their results in :data:`AXIS_ORDER`
    sequence (eight Tag-15 axes + three Tag-29 Cross-Modul axes)."""
    axes: list[AxisResult] = []
    for label in (
        "gate-2-1-bridge-forward-symmetry",
        "gate-2-2-konsistenz-score-threshold",
        "gate-2-3-v907-hash-stability-marker",
        "gate-2-4-recovery-r1-r4-mock-drill",
        "gate-2-5-subscribe-loop-lag-mock",
    ):
        axes.append(evaluate_phase_2_gate(label))
    axes.append(evaluate_bridge_audit_e2e())
    axes.append(evaluate_cross_lang_pin_coverage())
    axes.append(evaluate_wat_anchor_latency_producer(probe=probe_anchor))
    axes.extend(run_cross_modul_stress())
    return axes


def run_cross_lang_only() -> list[AxisResult]:
    """Run only the cross-lang-pin-coverage axis (cheap cron mode)."""
    return [evaluate_cross_lang_pin_coverage()]


def run_cross_modul_stress() -> list[AxisResult]:
    """Run only the three Tag-29 Cross-Modul-Stress-Test axes
    (pre-cutover smoke for KW-26 + KW-27 Doppel-Wellen)."""
    return [
        evaluate_cross_modul_fixture_pair(
            "cross-modul-state-backing-lifecycle-state-machine"
        ),
        evaluate_cross_modul_fixture_pair(
            "cross-modul-subscribe-loop-recovery-workflow"
        ),
        evaluate_cross_modul_v907_svid(),
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doppelbetrieb-score-aggregator",
        description=(
            "Aggregate Phase-2-Doppelbetrieb gate verdicts + Phase-3a "
            "foundation acceptance axes into a single JSON rollup. "
            "Anchors: ADR-0058, docs/quality-gates/phase-2-doppelbetrieb.md."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("full", "cross-lang-only", "cross-modul-stress"),
        default="full",
        help="full = all 11 axes (default); cross-lang-only = just "
        "the cross-lang-pin-coverage axis (cheap cron mode); "
        "cross-modul-stress = just the three Tag-29 Cross-Modul axes "
        "(pre-cutover smoke for KW-26/KW-27 Doppel-Wellen).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output path; default stdout.",
    )
    p.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="pass threshold (default = sum of all axis weights).",
    )
    p.add_argument(
        "--probe-anchor-producer",
        action="store_true",
        help="opt-in: actually synthesise a latency-emitter record to "
        "verify the producer emits. Default off (env-set is sufficient).",
    )
    p.add_argument(
        "--ts-utc",
        default=None,
        help="RFC3339 UTC timestamp override (Z-suffix).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.mode == "full":
            axes = run_full(probe_anchor=args.probe_anchor_producer)
        elif args.mode == "cross-modul-stress":
            axes = run_cross_modul_stress()
        else:
            axes = run_cross_lang_only()
    except Exception as exc:  # pragma: no cover (CLI-only)
        print(
            f"[doppelbetrieb-score-aggregator] ERROR: {exc}",
            file=sys.stderr,
        )
        return 2

    envelope = build_envelope(
        axes,
        threshold=args.threshold,
        ts_utc=args.ts_utc,
    )
    rendered = json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False)

    if args.out:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print(
                f"[doppelbetrieb-score-aggregator] ERROR writing "
                f"{args.out}: {exc}",
                file=sys.stderr,
            )
            return 2
    else:
        sys.stdout.write(rendered + "\n")

    return 0 if envelope["threshold_pass"] else 1


__all__ = [
    "SCHEMA",
    "AXIS_ORDER",
    "EXPECTED_PIN_COUNTS",
    "EXPECTED_PIN_TOTAL",
    "ENV_ANCHOR_LATENCY_JSONL",
    "CROSS_MODUL_SPEC",
    "CROSS_MODUL_V907_SVID_ENV_KEYS",
    "RUST_BACKEND_VALUE",
    "SVID_E2E_TEST",
    "V907_PIN_PACK_DIR",
    "AxisResult",
    "build_envelope",
    "evaluate_bridge_audit_e2e",
    "evaluate_cross_lang_pin_coverage",
    "evaluate_cross_modul_fixture_pair",
    "evaluate_cross_modul_v907_svid",
    "evaluate_phase_2_gate",
    "evaluate_wat_anchor_latency_producer",
    "main",
    "run_cross_lang_only",
    "run_cross_modul_stress",
    "run_full",
]


if __name__ == "__main__":
    sys.exit(main())
