#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""doppelbetrieb-score-aggregator — Sprint-Tag-15 Mini-Welle.

Background
----------

Phase-2 Doppelbetrieb (ADR-0058) ships five hermetic Acceptance-Gates
in ``tests/infra/test_phase_2_acceptance_gates.py`` (PR #109) and a
matching CI workflow (``.github/workflows/phase-2-validation-gate.yml``,
PR #110) that drives one job per gate plus an aggregator.

Tag-15 closes the Doppelbetrieb-readiness loop by surfacing **three
new Phase-3a-Foundation acceptance-axes** alongside the five Phase-2
gate verdicts in a single JSON rollup that Henrik can sample weekly
and Amara can spot-check between sprints:

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

Output shape
------------

A canonical JSON envelope with ``schema``, ``ts_utc``, ``axes``,
``total_score``, ``threshold_pass``, ``threshold``::

    {
      "schema": "wakir.doppelbetrieb.aggregator/1",
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
        }
      },
      "total_score": 8,
      "threshold": 8,
      "threshold_pass": true
    }

``total_score`` is the sum of per-axis ``pass=True`` weights. Default
threshold is the sum of all axis weights (``8``); the operator can
relax it via ``--threshold``.

Run mode
--------

* ``--mode=full`` (default): runs all eight axes. Drives the Phase-2
  gates via ``pytest -k ...`` against the existing
  ``tests/infra/test_phase_2_acceptance_gates.py``; drives the
  Bridge-Audit-E2E via ``pytest tests/integration/test_bridge_audit_
  roundtrip_e2e.py``; reads cross-lang pins from in-tree modules; for
  the anchor producer, defaults to *no probe* (pass=true iff env-var
  was set at invocation, per the producer contract) and only writes
  if ``--probe-anchor-producer`` is given.

* ``--mode=cross-lang-only``: only the cross-lang-pin-coverage axis.
  Useful for the cheap "is the cross-language byte-pin still tight?"
  cron Henrik schedules between full runs.

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
* ``docs/quality-gates/phase-2-doppelbetrieb.md`` (Amara, PR #80)
* ``tests/infra/test_phase_2_acceptance_gates.py`` (Tomás, PR #109)
* ``tests/integration/test_bridge_audit_roundtrip_e2e.py`` (PR #156)
* ``wirelang/federation/federation_frame.py`` (PR #157)
* ``wirelang/persona_engine/nats_subjects.py`` (PR #155)
* ``wirelang/persona_engine/bridge_audit_stream_hash.py`` (PR #156)
* ``wat/anchor/latency_emitter.py`` (PR #154)
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


SCHEMA = "wakir.doppelbetrieb.aggregator/1"

REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE_2_GATE_TEST = REPO_ROOT / "tests" / "infra" / "test_phase_2_acceptance_gates.py"
BRIDGE_AUDIT_E2E_TEST = REPO_ROOT / "tests" / "integration" / "test_bridge_audit_roundtrip_e2e.py"

#: Stable per-axis ordering. Matches the QA Quality-Gate doc topology
#: (five Phase-2 gates first, then the three Phase-3a-Foundation
#: axes). Tests pin against this list.
AXIS_ORDER: tuple[str, ...] = (
    "gate-2-1-bridge-forward-symmetry",
    "gate-2-2-konsistenz-score-threshold",
    "gate-2-3-v907-hash-stability-marker",
    "gate-2-4-recovery-r1-r4-mock-drill",
    "gate-2-5-subscribe-loop-lag-mock",
    "bridge-audit-e2e-roundtrip-pass",
    "cross-lang-pin-coverage",
    "wat-anchor-latency-producer-emitting",
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
    """Run all eight axes and return their results in :data:`AXIS_ORDER`
    sequence."""
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
    return axes


def run_cross_lang_only() -> list[AxisResult]:
    """Run only the cross-lang-pin-coverage axis (cheap cron mode)."""
    return [evaluate_cross_lang_pin_coverage()]


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
        choices=("full", "cross-lang-only"),
        default="full",
        help="full = all 8 axes (default); cross-lang-only = just the "
        "cross-lang-pin-coverage axis (cheap cron mode).",
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
    "AxisResult",
    "build_envelope",
    "evaluate_bridge_audit_e2e",
    "evaluate_cross_lang_pin_coverage",
    "evaluate_phase_2_gate",
    "evaluate_wat_anchor_latency_producer",
    "main",
    "run_cross_lang_only",
    "run_full",
]


if __name__ == "__main__":
    sys.exit(main())
