# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/doppelbetrieb-score-aggregator.py — Tag-15 Mini-Welle.

Hermetic — no real pytest subprocess (each Phase-2-gate evaluator
accepts a ``runner`` seam), no real LatencyEmitter import (the
producer evaluator accepts a ``probe_factory`` seam). Cross-lang pin
counts can be injected via ``counts_override``.

The aggregator script is stdlib-only and lives outside the python
package tree under ``scripts/``. We import it via importlib.util so
the hyphenated filename stays legal.

Scope (8 tests + 2 cross-axis tests = 10 total)
-----------------------------------------------

1. test_module_loads_and_exports_public_surface
2. test_axis_order_is_stable
3. test_phase_2_gate_evaluator_delegates_to_pytest_runner
4. test_phase_2_gate_evaluator_reports_failure_on_nonzero_rc
5. test_bridge_audit_e2e_evaluator_pass_and_fail
6. test_cross_lang_pin_coverage_pass_with_expected_counts
7. test_cross_lang_pin_coverage_fail_on_per_contract_drift
8. test_cross_lang_pin_coverage_reads_fixture_file_layout
9. test_wat_anchor_latency_producer_env_only_mode
10. test_build_envelope_rolls_axes_and_threshold_correctly
11. test_build_envelope_marks_missing_axes_as_failed
12. test_cli_main_writes_to_out_path_and_returns_passcode
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the aggregator script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "doppelbetrieb-score-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "doppelbetrieb_score_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve cls.__module__.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# 1. Module surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """Public surface (``__all__``) MUST stay stable: callers of the
    aggregator (Henrik weekly-rollup, Amara spot-check) import these
    names. Drift is a breaking change.
    """
    expected = {
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
    }
    assert set(aggregator.__all__) == expected
    assert aggregator.SCHEMA == "wakir.doppelbetrieb.aggregator/1"
    assert aggregator.EXPECTED_PIN_TOTAL == 16
    assert aggregator.EXPECTED_PIN_COUNTS == {
        "federation_frame": 5,
        "nats_subjects": 8,
        "bridge_audit_stream_hash": 3,
    }


# ---------------------------------------------------------------------------
# 2. Axis ordering
# ---------------------------------------------------------------------------


def test_axis_order_is_stable():
    """AXIS_ORDER MUST list all 8 axes in the QA-doc topology order
    (Phase-2 Gate-2-1..2-5 first, then Phase-3a Foundation axes). The
    Henrik weekly-rollup template depends on this ordering.
    """
    assert aggregator.AXIS_ORDER == (
        "gate-2-1-bridge-forward-symmetry",
        "gate-2-2-konsistenz-score-threshold",
        "gate-2-3-v907-hash-stability-marker",
        "gate-2-4-recovery-r1-r4-mock-drill",
        "gate-2-5-subscribe-loop-lag-mock",
        "bridge-audit-e2e-roundtrip-pass",
        "cross-lang-pin-coverage",
        "wat-anchor-latency-producer-emitting",
    )
    # Mapping from each Phase-2-gate label MUST resolve to one
    # pytest -k expression that exists in the gate test file. We
    # don't run pytest here — the integration is covered by the
    # phase-2-validation-gate.yml workflow — but we DO assert the
    # mapping covers all five gate labels.
    pytest_k_map = aggregator.PHASE_2_GATE_PYTEST_K
    assert set(pytest_k_map.keys()) == {
        "gate-2-1-bridge-forward-symmetry",
        "gate-2-2-konsistenz-score-threshold",
        "gate-2-3-v907-hash-stability-marker",
        "gate-2-4-recovery-r1-r4-mock-drill",
        "gate-2-5-subscribe-loop-lag-mock",
    }
    # All -k expressions must reference test functions in the gate
    # suite by their exact name.
    gate_test_src = aggregator.PHASE_2_GATE_TEST.read_text(encoding="utf-8")
    for k_expr in pytest_k_map.values():
        assert f"def {k_expr}(" in gate_test_src, (
            f"pytest -k expression {k_expr!r} not found in {aggregator.PHASE_2_GATE_TEST}"
        )


# ---------------------------------------------------------------------------
# 3. Phase-2-Gate evaluator (with runner seam)
# ---------------------------------------------------------------------------


def test_phase_2_gate_evaluator_delegates_to_pytest_runner():
    """The Phase-2 gate evaluator MUST delegate via the ``runner`` seam.
    We inject a stub runner that records the call shape and returns 0
    (pass) — the AxisResult must then report ``pass_=True``.
    """
    captured = {}

    def stub_runner(test_path, k_expr):
        captured["test_path"] = test_path
        captured["k_expr"] = k_expr
        return 0

    result = aggregator.evaluate_phase_2_gate(
        "gate-2-1-bridge-forward-symmetry", runner=stub_runner
    )
    assert result.label == "gate-2-1-bridge-forward-symmetry"
    assert result.pass_ is True
    assert result.weight == 1
    assert captured["test_path"] == aggregator.PHASE_2_GATE_TEST
    assert captured["k_expr"] == "test_gate_2_1_bridge_forward_symmetry"


def test_phase_2_gate_evaluator_reports_failure_on_nonzero_rc():
    """Non-zero pytest exit-code MUST surface as ``pass_=False``. We
    walk all five labels with a runner that returns a different
    non-zero rc per call to confirm no label silently maps to pass.
    """
    rc_counter = {"n": 0}

    def failing_runner(test_path, k_expr):
        rc_counter["n"] += 1
        return rc_counter["n"]  # 1, 2, 3, 4, 5 — all non-zero

    for label in aggregator.PHASE_2_GATE_PYTEST_K:
        result = aggregator.evaluate_phase_2_gate(label, runner=failing_runner)
        assert result.pass_ is False, (
            f"label {label!r} silently passed on non-zero rc"
        )


# ---------------------------------------------------------------------------
# 5. Bridge-Audit-E2E evaluator
# ---------------------------------------------------------------------------


def test_bridge_audit_e2e_evaluator_pass_and_fail():
    """Bridge-Audit-E2E evaluator wraps the integration test path with
    the same runner seam. Pass + fail in one test for parity coverage.
    """
    def pass_runner(test_path, k_expr):
        assert test_path == aggregator.BRIDGE_AUDIT_E2E_TEST
        assert k_expr is None  # full file, no -k narrowing
        return 0

    def fail_runner(test_path, k_expr):
        return 1

    passing = aggregator.evaluate_bridge_audit_e2e(runner=pass_runner)
    assert passing.label == "bridge-audit-e2e-roundtrip-pass"
    assert passing.pass_ is True

    failing = aggregator.evaluate_bridge_audit_e2e(runner=fail_runner)
    assert failing.label == "bridge-audit-e2e-roundtrip-pass"
    assert failing.pass_ is False


# ---------------------------------------------------------------------------
# 6. Cross-lang-pin coverage
# ---------------------------------------------------------------------------


def test_cross_lang_pin_coverage_pass_with_expected_counts():
    """The 5+8+3=16 pin contract MUST pass when each contract reports
    its expected count.
    """
    result = aggregator.evaluate_cross_lang_pin_coverage(
        counts_override={
            "federation_frame": 5,
            "nats_subjects": 8,
            "bridge_audit_stream_hash": 3,
        }
    )
    assert result.label == "cross-lang-pin-coverage"
    assert result.pass_ is True
    assert result.details["total"] == 16
    assert result.details["expected_total"] == 16
    assert result.details["federation_frame"] == 5
    assert result.details["nats_subjects"] == 8
    assert result.details["bridge_audit_stream_hash"] == 3


def test_cross_lang_pin_coverage_fail_on_per_contract_drift():
    """Per-contract drift MUST fail even if the total still equals 16."""
    # Shift one pin from federation_frame to nats_subjects: total stays
    # 16 but the per-contract assertion catches it.
    result = aggregator.evaluate_cross_lang_pin_coverage(
        counts_override={
            "federation_frame": 4,
            "nats_subjects": 9,
            "bridge_audit_stream_hash": 3,
        }
    )
    assert result.pass_ is False
    assert result.details["total"] == 16
    assert result.details["federation_frame"] == 4

    # Total-only drift also fails.
    result2 = aggregator.evaluate_cross_lang_pin_coverage(
        counts_override={
            "federation_frame": 5,
            "nats_subjects": 8,
            "bridge_audit_stream_hash": 2,
        }
    )
    assert result2.pass_ is False
    assert result2.details["total"] == 15

    # Extra pin in any contract is also drift.
    result3 = aggregator.evaluate_cross_lang_pin_coverage(
        counts_override={
            "federation_frame": 5,
            "nats_subjects": 8,
            "bridge_audit_stream_hash": 4,
        }
    )
    assert result3.pass_ is False
    assert result3.details["total"] == 17


def test_cross_lang_pin_coverage_reads_fixture_file_layout(tmp_path):
    """The fixture-file reader MUST tolerate the
    ``{"fixtures": [...]}`` wrapper layout that PR #157 ships.
    """
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps({
            "x-spdx-license-identifier": "BUSL-1.1",
            "fixture_set_version": 1,
            "cross_lang_contract": "python<->rust",
            "fixtures": [
                {"input": "a", "expected_canonical_bytes": "61"},
                {"input": "b", "expected_canonical_bytes": "62"},
                {"input": "c", "expected_canonical_bytes": "63"},
            ],
        }),
        encoding="utf-8",
    )
    # Inject the path via the federation-fixture-path argument so we
    # bypass the in-tree module introspection for nats_subjects /
    # bridge_audit_stream_hash; just confirm the file-layout path
    # works.
    count = aggregator._count_federation_frame_pins(fixture)
    assert count == 3

    # Bare-list layout MUST also work (defensive read).
    bare = tmp_path / "bare.json"
    bare.write_text(
        json.dumps([{"input": "x"}, {"input": "y"}]),
        encoding="utf-8",
    )
    assert aggregator._count_federation_frame_pins(bare) == 2

    # Malformed layout MUST raise.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"no_fixtures_key": True}), encoding="utf-8")
    with pytest.raises(ValueError):
        aggregator._count_federation_frame_pins(bad)


# ---------------------------------------------------------------------------
# 9. WAT-anchor-latency producer
# ---------------------------------------------------------------------------


def test_wat_anchor_latency_producer_env_only_mode():
    """Default mode (probe=False) passes solely on env-var-set; the
    emit-check is reported as ``"emitted": null``. With env unset the
    axis must fail.
    """
    # Env set + no probe ⇒ pass on env-set alone.
    result_set = aggregator.evaluate_wat_anchor_latency_producer(
        probe=False,
        env={"WAKIR_ANCHOR_LATENCY_JSONL": "/tmp/wakir-anchor.jsonl"},
    )
    assert result_set.pass_ is True
    assert result_set.details == {"env_set": True, "emitted": None}

    # Env unset ⇒ fail.
    result_unset = aggregator.evaluate_wat_anchor_latency_producer(
        probe=False, env={}
    )
    assert result_unset.pass_ is False
    assert result_unset.details == {"env_set": False, "emitted": None}

    # Env set to empty string ⇒ also unset per the producer contract.
    result_empty = aggregator.evaluate_wat_anchor_latency_producer(
        probe=False, env={"WAKIR_ANCHOR_LATENCY_JSONL": "   "}
    )
    assert result_empty.pass_ is False
    assert result_empty.details["env_set"] is False

    # Probe=True with stub probe_factory that succeeds ⇒ pass on both.
    result_probe_ok = aggregator.evaluate_wat_anchor_latency_producer(
        probe=True,
        env={"WAKIR_ANCHOR_LATENCY_JSONL": "/tmp/wakir-anchor.jsonl"},
        probe_factory=lambda env_map: True,
    )
    assert result_probe_ok.pass_ is True
    assert result_probe_ok.details == {"env_set": True, "emitted": True}

    # Probe=True with stub probe that fails ⇒ axis fails.
    result_probe_fail = aggregator.evaluate_wat_anchor_latency_producer(
        probe=True,
        env={"WAKIR_ANCHOR_LATENCY_JSONL": "/tmp/wakir-anchor.jsonl"},
        probe_factory=lambda env_map: False,
    )
    assert result_probe_fail.pass_ is False
    assert result_probe_fail.details == {"env_set": True, "emitted": False}


# ---------------------------------------------------------------------------
# 10. Envelope assembly
# ---------------------------------------------------------------------------


def test_build_envelope_rolls_axes_and_threshold_correctly():
    """The envelope must:
      - render axes in AXIS_ORDER sequence,
      - sum pass-weights into ``total_score``,
      - default threshold to sum of all weights,
      - set ``threshold_pass`` iff ``total_score >= threshold``.
    """
    AR = aggregator.AxisResult
    axes = [
        AR("gate-2-1-bridge-forward-symmetry", True),
        AR("gate-2-2-konsistenz-score-threshold", True),
        AR("gate-2-3-v907-hash-stability-marker", True),
        AR("gate-2-4-recovery-r1-r4-mock-drill", True),
        AR("gate-2-5-subscribe-loop-lag-mock", True),
        AR("bridge-audit-e2e-roundtrip-pass", True),
        AR(
            "cross-lang-pin-coverage",
            True,
            details={
                "federation_frame": 5,
                "nats_subjects": 8,
                "bridge_audit_stream_hash": 3,
                "total": 16,
                "expected_total": 16,
            },
        ),
        AR(
            "wat-anchor-latency-producer-emitting",
            True,
            details={"env_set": True, "emitted": None},
        ),
    ]
    envelope = aggregator.build_envelope(
        axes, ts_utc="2026-05-17T09:50:00Z"
    )
    assert envelope["schema"] == "wakir.doppelbetrieb.aggregator/1"
    assert envelope["ts_utc"] == "2026-05-17T09:50:00Z"
    assert envelope["total_score"] == 8
    assert envelope["threshold"] == 8
    assert envelope["threshold_pass"] is True
    # Axes must be present in AXIS_ORDER sequence.
    assert list(envelope["axes"].keys()) == list(aggregator.AXIS_ORDER)
    # Cross-lang-pin-coverage carries its details dict.
    assert envelope["axes"]["cross-lang-pin-coverage"]["details"]["total"] == 16

    # Operator-relaxed threshold: 6 ⇒ threshold_pass still true.
    relaxed = aggregator.build_envelope(
        axes, threshold=6, ts_utc="2026-05-17T09:50:00Z"
    )
    assert relaxed["threshold"] == 6
    assert relaxed["threshold_pass"] is True

    # Failure mode: two axes fail ⇒ total_score=6 ⇒ default threshold=8
    # ⇒ threshold_pass=False.
    axes_with_failures = list(axes)
    axes_with_failures[5] = AR("bridge-audit-e2e-roundtrip-pass", False)
    axes_with_failures[6] = AR("cross-lang-pin-coverage", False, details={})
    envelope_fail = aggregator.build_envelope(
        axes_with_failures, ts_utc="2026-05-17T09:50:00Z"
    )
    assert envelope_fail["total_score"] == 6
    assert envelope_fail["threshold"] == 8
    assert envelope_fail["threshold_pass"] is False


def test_build_envelope_marks_missing_axes_as_failed():
    """An axis missing from the input list MUST be rendered as a
    failing axis with ``details.reason == "axis-missing"``. This
    prevents the rollup from silently dropping an expected gate.
    """
    AR = aggregator.AxisResult
    only_two = [
        AR("gate-2-1-bridge-forward-symmetry", True),
        AR("bridge-audit-e2e-roundtrip-pass", True),
    ]
    envelope = aggregator.build_envelope(
        only_two, ts_utc="2026-05-17T09:50:00Z"
    )
    # All 8 axes still present.
    assert list(envelope["axes"].keys()) == list(aggregator.AXIS_ORDER)
    # The two supplied axes pass; the other six are flagged missing.
    missing_axes = [
        label
        for label, env in envelope["axes"].items()
        if isinstance(env.get("details"), dict)
        and env["details"].get("reason") == "axis-missing"
    ]
    assert len(missing_axes) == 6
    assert "gate-2-1-bridge-forward-symmetry" not in missing_axes
    assert "bridge-audit-e2e-roundtrip-pass" not in missing_axes
    assert envelope["total_score"] == 2
    assert envelope["threshold_pass"] is False


# ---------------------------------------------------------------------------
# 12. CLI main()
# ---------------------------------------------------------------------------


def test_cli_main_writes_to_out_path_and_returns_passcode(
    tmp_path, monkeypatch
):
    """End-to-end CLI: ``--mode=cross-lang-only --out PATH`` writes
    a JSON envelope to PATH and returns 0 on threshold-pass.
    """
    out = tmp_path / "rollup.json"
    rc = aggregator.main([
        "--mode", "cross-lang-only",
        "--out", str(out),
        "--ts-utc", "2026-05-17T10:00:00Z",
        # Relax threshold so the single-axis cross-lang-only mode can
        # pass (cross-lang-pin-coverage axis weight=1; default total
        # would be the single-axis sum already, but we pin
        # threshold=1 for clarity).
        "--threshold", "1",
    ])
    assert rc == 0, "cross-lang pin coverage MUST pass against the in-tree substrate"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "wakir.doppelbetrieb.aggregator/1"
    assert payload["ts_utc"] == "2026-05-17T10:00:00Z"
    # In cross-lang-only mode, the seven non-cross-lang axes are
    # rendered as "axis-missing" and the single cross-lang axis
    # carries the live counts.
    cross_axis = payload["axes"]["cross-lang-pin-coverage"]
    assert cross_axis["pass"] is True
    assert cross_axis["details"]["total"] == 16
    assert cross_axis["details"]["federation_frame"] == 5
    assert cross_axis["details"]["nats_subjects"] == 8
    assert cross_axis["details"]["bridge_audit_stream_hash"] == 3

    # Exit-code=1 mode: tighter threshold than achievable.
    rc_fail = aggregator.main([
        "--mode", "cross-lang-only",
        "--out", str(tmp_path / "rollup2.json"),
        "--threshold", "5",  # one axis can yield at most weight=1
    ])
    assert rc_fail == 1
