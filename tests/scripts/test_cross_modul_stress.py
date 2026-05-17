# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the Tag-29 Cross-Modul-Stress-Test axes in
``scripts/doppelbetrieb-score-aggregator.py`` (ADR-0066 KW-26
Mitigation).

The three Cross-Modul-Stress-Test axes catch cross-module drift
BEFORE the KW-26 + KW-27 Doppel-Welle cutovers. Each axis is paired
with a Doppel-Welle pairing from ADR-0066:

* ``cross-modul-state-backing-lifecycle-state-machine`` —
  Welle-4 (KW 26) + Welle-5 (KW 26)
* ``cross-modul-subscribe-loop-recovery-workflow`` —
  Welle-6 (KW 27) + Welle-7 (KW 27)
* ``cross-modul-v907-verify-svid-workload-identity`` —
  Welle-1 (KW 24) + Welle-2 (KW 24, opt-in)

Per axis we ship at least two tests: a *success* path that pins the
pass-conditions tight (both ENVs rust + both fixtures intact) and a
*drift-detection* path that flips one condition at a time and asserts
``pass_=False``. The pairing yields 6 tests minimum (3 axes ×
{success, drift}); we ship 9 total to cover the schema-version-pin
drift and the ``run_cross_modul_stress()`` driver as well.

All tests are hermetic — no real ENV-var manipulation
(``env={...}`` injection), no real filesystem writes for the
fixture-pair axes (the in-tree fixtures are read directly so the
contract is enforced; counts can be injected via the
``counts_override`` seam for negative cases), and no subprocess.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the aggregator script as a module (mirrors the pattern in
# test_doppelbetrieb_score_aggregator.py — the script lives outside
# the python package tree under scripts/).
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "doppelbetrieb-score-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "doppelbetrieb_score_aggregator_xmod", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Shared env-map helpers
# ---------------------------------------------------------------------------


ALL_RUST_ENV = {
    "WAKIR_STATE_BACKING_BACKEND": "rust",
    "WAKIR_FSM_BACKEND": "rust",
    "WAKIR_SUBSCRIBE_LOOP_BACKEND": "rust",
    "WAKIR_RECOVERY_BACKEND": "rust",
    "WAKIR_V907_VERIFY_BACKEND": "rust",
    "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND": "rust",
}


# ---------------------------------------------------------------------------
# Axis 1: cross-modul-state-backing-lifecycle-state-machine
# ---------------------------------------------------------------------------


def test_cross_modul_state_backing_lifecycle_success():
    """Both ENV-flags rust + both fixture files intact ⇒ pass.

    Pin-anchor: ADR-0066 §"Cross-Modul-Drift-Detection für Doppel-
    Wellen" — Welle-4+5 KW-26 parallel cutover. Schema-byte-identity
    of the state-backing PersonaStateSnapshot JCS contract is the
    Welle-4 hash-anchor; lifecycle-state-machine carries the Welle-5
    FSM-transition contract.
    """
    result = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env=ALL_RUST_ENV,
    )
    assert (
        result.label
        == "cross-modul-state-backing-lifecycle-state-machine"
    )
    assert result.pass_ is True
    assert result.details["both_envs_rust"] is True
    # In-tree substrate ships 5 fixtures per file. The contract is
    # "non-empty list" — we pin 5 here as the substrate-state at
    # Tag-29 (extending the test if the fixture-set grows is a
    # deliberate substrate decision, not silent).
    assert result.details["state_backing_fixtures"] == 5
    assert result.details["lifecycle_state_machine_fixtures"] == 5


def test_cross_modul_state_backing_lifecycle_drift_detection():
    """Any of the four drift modes MUST surface as ``pass_=False``.

    Drift modes covered:
      (a) only state_backing ENV set ⇒ both_envs_rust=False
      (b) only fsm ENV set ⇒ both_envs_rust=False
      (c) both ENVs set but state_backing fixtures empty ⇒ drift
      (d) both ENVs set but lifecycle_state_machine fixtures empty
    """
    # (a) only state_backing ENV
    only_sb = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env={"WAKIR_STATE_BACKING_BACKEND": "rust"},
    )
    assert only_sb.pass_ is False
    assert only_sb.details["both_envs_rust"] is False

    # (b) only fsm ENV
    only_fsm = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env={"WAKIR_FSM_BACKEND": "rust"},
    )
    assert only_fsm.pass_ is False
    assert only_fsm.details["both_envs_rust"] is False

    # (c) state_backing fixtures injected as 0
    no_sb_fix = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env=ALL_RUST_ENV,
        counts_override={
            "state_backing_fixtures": 0,
            "lifecycle_state_machine_fixtures": 5,
        },
    )
    assert no_sb_fix.pass_ is False
    assert no_sb_fix.details["state_backing_fixtures"] == 0

    # (d) lifecycle_state_machine fixtures injected as 0
    no_fsm_fix = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env=ALL_RUST_ENV,
        counts_override={
            "state_backing_fixtures": 5,
            "lifecycle_state_machine_fixtures": 0,
        },
    )
    assert no_fsm_fix.pass_ is False
    assert no_fsm_fix.details["lifecycle_state_machine_fixtures"] == 0


# ---------------------------------------------------------------------------
# Axis 2: cross-modul-subscribe-loop-recovery-workflow
# ---------------------------------------------------------------------------


def test_cross_modul_subscribe_loop_recovery_success():
    """Both ENV-flags rust + both ack-record/recovery fixture files
    intact ⇒ pass.

    Pin-anchor: ADR-0066 — Welle-6+7 KW-27 parallel cutover. Subscribe-
    loop ack-records are the NATS-ingress audit substrate; recovery-
    workflow carries the R1-R4 recovery contract.
    """
    result = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-subscribe-loop-recovery-workflow",
        env=ALL_RUST_ENV,
    )
    assert result.label == "cross-modul-subscribe-loop-recovery-workflow"
    assert result.pass_ is True
    assert result.details["both_envs_rust"] is True
    assert result.details["subscribe_loop_fixtures"] == 5
    assert result.details["recovery_workflow_fixtures"] == 5


def test_cross_modul_subscribe_loop_recovery_drift_detection():
    """ENV-only-half and fixture-empty drift MUST surface."""
    # ENV: only subscribe-loop
    only_sub = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-subscribe-loop-recovery-workflow",
        env={"WAKIR_SUBSCRIBE_LOOP_BACKEND": "rust"},
    )
    assert only_sub.pass_ is False
    assert only_sub.details["both_envs_rust"] is False

    # ENV: only recovery
    only_rec = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-subscribe-loop-recovery-workflow",
        env={"WAKIR_RECOVERY_BACKEND": "rust"},
    )
    assert only_rec.pass_ is False
    assert only_rec.details["both_envs_rust"] is False

    # Fixture-empty drift via override.
    no_sub_fix = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-subscribe-loop-recovery-workflow",
        env=ALL_RUST_ENV,
        counts_override={
            "subscribe_loop_fixtures": 0,
            "recovery_workflow_fixtures": 5,
        },
    )
    assert no_sub_fix.pass_ is False
    assert no_sub_fix.details["subscribe_loop_fixtures"] == 0


# ---------------------------------------------------------------------------
# Axis 3: cross-modul-v907-verify-svid-workload-identity
# ---------------------------------------------------------------------------


def test_cross_modul_v907_svid_success():
    """Both ENVs rust + V907 pin-pack non-empty + SVID e2e present
    ⇒ pass.

    Pin-anchor: ADR-0066 — Welle-1+2 KW-24 parallel cutover. V907 is
    the hash-byte-identity anchor (persona-hash pin); SVID-workload-
    identity is the ADR-0065 Welle-2 opt-in candidate.
    """
    result = aggregator.evaluate_cross_modul_v907_svid(env=ALL_RUST_ENV)
    assert (
        result.label
        == "cross-modul-v907-verify-svid-workload-identity"
    )
    assert result.pass_ is True
    assert result.details["both_envs_rust"] is True
    # Pin-pack ships at least one persona file at Tag-29.
    assert result.details["v907_pin_pack_personas"] >= 1
    assert result.details["svid_e2e_substrate_present"] is True


def test_cross_modul_v907_svid_drift_detection():
    """Three drift modes: missing ENV, empty pin-pack, missing SVID
    substrate. Each MUST surface as ``pass_=False``.
    """
    # (a) Only V907 ENV set.
    only_v907 = aggregator.evaluate_cross_modul_v907_svid(
        env={"WAKIR_V907_VERIFY_BACKEND": "rust"}
    )
    assert only_v907.pass_ is False
    assert only_v907.details["both_envs_rust"] is False

    # (b) Both ENVs but empty pin-pack ⇒ fail. v907_pin_pack_override
    # injects the count without touching the real directory.
    empty_pinpack = aggregator.evaluate_cross_modul_v907_svid(
        env=ALL_RUST_ENV, v907_pin_pack_override=0
    )
    assert empty_pinpack.pass_ is False
    assert empty_pinpack.details["v907_pin_pack_personas"] == 0

    # (c) Both ENVs, pin-pack OK, but SVID substrate missing ⇒ fail.
    no_svid = aggregator.evaluate_cross_modul_v907_svid(
        env=ALL_RUST_ENV,
        v907_pin_pack_override=5,
        svid_substrate_override=False,
    )
    assert no_svid.pass_ is False
    assert no_svid.details["svid_e2e_substrate_present"] is False


# ---------------------------------------------------------------------------
# Schema-version drift on the state-backing fixture file
# ---------------------------------------------------------------------------


def test_cross_modul_state_backing_schema_version_drift(tmp_path, monkeypatch):
    """The state-backing fixture file carries a pinned ``schema_version``
    of ``wakir.persona-engine.persona-state-snapshot/1``. If that pin
    drifts (e.g. a contributor bumps to /2 without coordinating the
    Rust crate sibling), the axis MUST fail even when ENVs are set
    and the fixtures list is non-empty.

    We re-point REPO_ROOT at a tmp tree that mirrors the cross-lang
    fixture-pair layout but ships a drifted schema_version.
    """
    # Build a parallel substrate under tmp_path that matches the
    # CROSS_MODUL_SPEC fixture-pair layout for the first axis.
    sb_dir = tmp_path / "tests" / "fixtures" / "state-backing-cross-lang"
    sb_dir.mkdir(parents=True)
    drifted = {
        "schema_version": "wakir.persona-engine.persona-state-snapshot/2",
        "fixtures": [
            {"name": "f01", "input": {}, "expected": {}},
        ],
    }
    (sb_dir / "fixtures.json").write_text(
        json.dumps(drifted), encoding="utf-8"
    )
    lc_dir = tmp_path / "tests" / "fixtures" / "lifecycle-state-machine-cross-lang"
    lc_dir.mkdir(parents=True)
    (lc_dir / "fixtures.json").write_text(
        json.dumps(
            {
                "schema_version": "wakir.persona-engine.lifecycle/1",
                "fixtures": [{"name": "f01"}],
            }
        ),
        encoding="utf-8",
    )

    result = aggregator.evaluate_cross_modul_fixture_pair(
        "cross-modul-state-backing-lifecycle-state-machine",
        env=ALL_RUST_ENV,
        repo_root=tmp_path,
    )
    assert result.pass_ is False
    drift = result.details.get("state_backing_fixtures_schema_drift")
    assert drift is not None
    assert (
        drift["expected"]
        == "wakir.persona-engine.persona-state-snapshot/1"
    )
    assert (
        drift["actual"]
        == "wakir.persona-engine.persona-state-snapshot/2"
    )


# ---------------------------------------------------------------------------
# run_cross_modul_stress() driver + envelope integration
# ---------------------------------------------------------------------------


def test_run_cross_modul_stress_returns_three_axes_in_canonical_order():
    """``run_cross_modul_stress()`` MUST emit the three Cross-Modul
    axes in the same order they appear in :data:`AXIS_ORDER` — the
    workflow + step-summary render depend on this ordering.
    """
    axes = aggregator.run_cross_modul_stress()
    assert len(axes) == 3
    labels = [a.label for a in axes]
    assert labels == [
        "cross-modul-state-backing-lifecycle-state-machine",
        "cross-modul-subscribe-loop-recovery-workflow",
        "cross-modul-v907-verify-svid-workload-identity",
    ]


def test_cli_main_cross_modul_stress_mode(tmp_path):
    """End-to-end CLI: ``--mode=cross-modul-stress --out PATH``
    writes an 11-axis envelope where the three Cross-Modul axes
    carry the live verdicts and the other eight are flagged
    ``axis-missing``. Threshold relaxed so the pre-cutover smoke
    can pass when only the Cross-Modul subset is evaluated.

    Note: the success-on-ENV path is exercised by the per-axis
    success tests above; this CLI test exercises the mode-dispatch
    plumbing and JSON-envelope contract.
    """
    out = tmp_path / "rollup.json"
    rc = aggregator.main([
        "--mode", "cross-modul-stress",
        "--out", str(out),
        "--ts-utc", "2026-05-17T11:00:00Z",
        # All three axes will fail (no ENV set in subprocess parent),
        # so we relax threshold to 0 — the test confirms mode-dispatch
        # + envelope shape, not the pass verdict.
        "--threshold", "0",
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "wakir.doppelbetrieb.aggregator/2"
    assert payload["ts_utc"] == "2026-05-17T11:00:00Z"
    # The CLI renders the envelope with ``sort_keys=True`` (stable
    # byte-output across runs), so the JSON-key order on disk is
    # alphabetical, not AXIS_ORDER. The order-stability contract is
    # exercised by the in-process ``build_envelope`` test in
    # ``test_doppelbetrieb_score_aggregator.py``. Here we assert
    # set-equality on the axes keys plus the per-axis verdict shape.
    assert set(payload["axes"].keys()) == set(aggregator.AXIS_ORDER)
    # The three Cross-Modul axes carry their evaluator details.
    cm_axis = payload["axes"][
        "cross-modul-state-backing-lifecycle-state-machine"
    ]
    assert "both_envs_rust" in cm_axis["details"]
    # The eight non-Cross-Modul axes are marked missing.
    missing = [
        label
        for label, env in payload["axes"].items()
        if isinstance(env.get("details"), dict)
        and env["details"].get("reason") == "axis-missing"
    ]
    assert len(missing) == 8


def test_cross_modul_unknown_label_raises_keyerror():
    """Calling the fixture-pair evaluator with an unknown label MUST
    raise :class:`KeyError` — defensive against silent drift in the
    workflow YAML (a typo'd label name would otherwise emit a
    misleading ``pass_=False`` axis).
    """
    with pytest.raises(KeyError):
        aggregator.evaluate_cross_modul_fixture_pair(
            "cross-modul-typo-axis-name", env=ALL_RUST_ENV
        )
