# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/ci/emit-welle-sign-off.py`` (Tag-51 / Tomas).

Strict hermetic posture: stdlib + pytest only. No network, no
subprocess, no host filesystem writes outside ``tmp_path``. Every
fixture is built inline. Module is loaded by file path because the
emitter lives under ``scripts/ci/`` with a hyphenated filename that is
not import-friendly as a package module.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EMITTER_PATH = REPO_ROOT / "scripts" / "ci" / "emit-welle-sign-off.py"


def _load_emitter():
    spec = importlib.util.spec_from_file_location(
        "emit_welle_sign_off", EMITTER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


emitter = _load_emitter()


# --- pure-function layer ---------------------------------------------------


def test_schema_version_constant_is_stable():
    """Schema version is the contract surface read by downstream tools."""
    assert emitter.SCHEMA_VERSION == "wakir.phase-3c.welle-sign-off/1"


def test_welle_to_component_map_covers_all_seven_wellen():
    """The component map must cover Welle 1..7 with canonical names."""
    expected = {
        1: "v907_verify",
        2: "svid_workload_identity",
        3: "bridge_audit_writer",
        4: "state_backing",
        5: "lifecycle_state_machine",
        6: "subscribe_loop",
        7: "recovery_workflow",
    }
    assert emitter.WELLE_TO_COMPONENT == expected


def test_derive_verdict_prefers_explicit_verdict_over_boolean():
    """When both fields are present, explicit verdict wins."""
    envelope = {"verdict": "CAUTION", "ready_for_live_smoke": True}
    assert emitter.derive_verdict(envelope) == "CAUTION"


def test_derive_verdict_falls_back_to_boolean_flag():
    """Welle-1/2/4 shape: only ready_for_live_smoke is present."""
    assert emitter.derive_verdict({"ready_for_live_smoke": True}) == "READY"
    assert emitter.derive_verdict({"ready_for_live_smoke": False}) == "BLOCK"


def test_derive_verdict_defaults_to_block_when_no_fields_present():
    """Conservative default: missing data is treated as BLOCK."""
    assert emitter.derive_verdict({}) == "BLOCK"
    assert emitter.derive_verdict(None) == "BLOCK"
    assert emitter.derive_verdict("not a dict") == "BLOCK"


def test_derive_verdict_normalises_case():
    """Verdict strings are uppercased before validation."""
    assert emitter.derive_verdict({"verdict": "ready"}) == "READY"
    assert emitter.derive_verdict({"verdict": "Caution"}) == "CAUTION"


def test_derive_verdict_rejects_unknown_verdict_string():
    """Unknown verdict strings collapse to BLOCK rather than passing through."""
    assert emitter.derive_verdict({"verdict": "TBD"}) == "BLOCK"
    assert emitter.derive_verdict({"verdict": "MAYBE"}) == "BLOCK"


def test_verdict_to_audit_ok_only_ready_is_true():
    """CAUTION must surface to Mira-Hand (audit_ok=False)."""
    assert emitter.verdict_to_audit_ok("READY") is True
    assert emitter.verdict_to_audit_ok("CAUTION") is False
    assert emitter.verdict_to_audit_ok("BLOCK") is False


def test_extract_decision_summary_handles_full_welle_3_shape():
    """Welle-3/5/6/7 shape with verdict + hard_block_reasons."""
    envelope = {
        "verdict": "BLOCK",
        "score_band_floor": "GREEN",
        "observed_band": "AMBER",
        "hard_block_reasons": ["drift>0", "phantom-state"],
    }
    summary = emitter.extract_decision_summary(envelope)
    assert summary["ready_for_live_smoke"] is None
    assert summary["score_band_floor"] == "GREEN"
    assert summary["observed_band"] == "AMBER"
    assert summary["hard_block_reasons"] == ["drift>0", "phantom-state"]


def test_extract_decision_summary_handles_welle_1_shape():
    """Welle-1/2/4 shape with ready_for_live_smoke boolean."""
    envelope = {
        "ready_for_live_smoke": True,
        "score_band_floor": "GREEN",
        "observed_band": "GREEN",
    }
    summary = emitter.extract_decision_summary(envelope)
    assert summary["ready_for_live_smoke"] is True
    assert summary["hard_block_reasons"] == []


def test_extract_decision_summary_filters_malformed_hard_blocks():
    """Non-string entries in hard_block_reasons are filtered out."""
    envelope = {"hard_block_reasons": ["valid", 42, None, "another"]}
    summary = emitter.extract_decision_summary(envelope)
    assert summary["hard_block_reasons"] == ["valid", "another"]


def test_extract_decision_summary_handles_non_dict_input():
    """Stub summary returned for malformed input -- never raises."""
    summary = emitter.extract_decision_summary(None)
    assert summary == {
        "ready_for_live_smoke": None,
        "score_band_floor": None,
        "observed_band": None,
        "hard_block_reasons": [],
    }


def test_build_sign_off_happy_path_ready():
    """READY decision produces audit_ok=true sign-off with correct schema."""
    decision = {
        "verdict": "READY",
        "ready_for_live_smoke": True,
        "score_band_floor": "GREEN",
        "observed_band": "GREEN",
    }
    sign_off = emitter.build_sign_off(
        welle=3,
        decision_envelope=decision,
        source_envelope_path="out/cutover-acceptance-decision.json",
        signed_off_at="2026-06-25T08:00:00Z",
    )
    assert sign_off["schema"] == "wakir.phase-3c.welle-sign-off/1"
    assert sign_off["welle"] == 3
    assert sign_off["welle_slug"] == "welle-3"
    assert sign_off["component"] == "bridge_audit_writer"
    assert sign_off["signed_off_by"] == "henrik"
    assert sign_off["audit_ok"] is True
    assert sign_off["verdict"] == "READY"
    assert sign_off["signed_off_at"] == "2026-06-25T08:00:00Z"


def test_build_sign_off_caution_yields_audit_ok_false_with_note():
    """CAUTION verdict carries a Mira-Hand surfacing note."""
    decision = {"verdict": "CAUTION", "score_band_floor": "GREEN"}
    sign_off = emitter.build_sign_off(
        welle=5,
        decision_envelope=decision,
        source_envelope_path="x.json",
        signed_off_at="2026-06-26T08:00:00Z",
    )
    assert sign_off["verdict"] == "CAUTION"
    assert sign_off["audit_ok"] is False
    assert any("CAUTION" in n for n in sign_off["notes"])


def test_build_sign_off_missing_envelope_defaults_to_block_with_note():
    """Conservative posture: absent envelope -> BLOCK + provenance note."""
    sign_off = emitter.build_sign_off(
        welle=7,
        decision_envelope=None,
        source_envelope_path="missing.json",
        signed_off_at="2026-06-27T08:00:00Z",
    )
    assert sign_off["verdict"] == "BLOCK"
    assert sign_off["audit_ok"] is False
    assert any("absent" in n.lower() for n in sign_off["notes"])


def test_build_sign_off_rejects_out_of_range_welle():
    """Welle index outside 1..7 is a hard error."""
    with pytest.raises(SystemExit):
        emitter.build_sign_off(
            welle=0,
            decision_envelope={"verdict": "READY"},
            source_envelope_path="x.json",
            signed_off_at="2026-06-25T08:00:00Z",
        )
    with pytest.raises(SystemExit):
        emitter.build_sign_off(
            welle=8,
            decision_envelope={"verdict": "READY"},
            source_envelope_path="x.json",
            signed_off_at="2026-06-25T08:00:00Z",
        )


def test_build_sign_off_respects_component_override():
    """The optional --component flag overrides the canonical name."""
    sign_off = emitter.build_sign_off(
        welle=3,
        decision_envelope={"verdict": "READY"},
        source_envelope_path="x.json",
        signed_off_at="2026-06-25T08:00:00Z",
        component_override="anchor_emitter",
    )
    assert sign_off["component"] == "anchor_emitter"


def test_build_sign_off_appends_user_notes():
    """User-supplied notes appear in the envelope alongside auto-notes."""
    sign_off = emitter.build_sign_off(
        welle=1,
        decision_envelope={"verdict": "READY"},
        source_envelope_path="x.json",
        signed_off_at="2026-06-23T08:00:00Z",
        notes=["operator-confirmed-go", "logged-in-activity-log"],
    )
    assert "operator-confirmed-go" in sign_off["notes"]
    assert "logged-in-activity-log" in sign_off["notes"]


def test_build_sign_off_aggregator_compatible_for_henrik_slot(tmp_path):
    """End-to-end: an emitted envelope is consumed cleanly by the
    Tag-50 Marathon-Final-Bilanz aggregator's Henrik slot evaluator.
    """
    sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))
    import marathon_final_bilanz_aggregator as agg

    sign_offs = {}
    for welle_id in agg.WELLEN:
        # welle-3-bridge-audit-writer -> 3
        idx = int(welle_id.split("-")[1])
        envelope = emitter.build_sign_off(
            welle=idx,
            decision_envelope={"verdict": "READY"},
            source_envelope_path=f"out/welle-{idx}.json",
            signed_off_at="2026-06-29T08:00:00Z",
        )
        sign_offs[welle_id] = envelope

    slot = agg.evaluate_henrik_slot(sign_offs)
    assert slot["persona"] == "henrik"
    assert slot["status"] == "READY"


def test_main_writes_output_file_and_exits_zero(tmp_path):
    """CLI integration: writes the expected file and exits 0 for READY."""
    decision_path = tmp_path / "decision.json"
    output_path = tmp_path / "state" / "welle-1-sign-off.json"
    decision_path.write_text(
        json.dumps(
            {
                "ready_for_live_smoke": True,
                "score_band_floor": "GREEN",
                "observed_band": "GREEN",
            }
        ),
        encoding="utf-8",
    )
    rc = emitter.main(
        [
            "--welle",
            "1",
            "--decision-envelope",
            str(decision_path),
            "--output",
            str(output_path),
            "--signed-off-at",
            "2026-06-23T08:00:00Z",
        ]
    )
    assert rc == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text("utf-8"))
    assert payload["audit_ok"] is True
    assert payload["welle"] == 1
    assert payload["component"] == "v907_verify"
    assert payload["signed_off_at"] == "2026-06-23T08:00:00Z"


def test_main_strict_exits_one_on_block(tmp_path):
    """--strict turns a BLOCK verdict into a non-zero exit code."""
    decision_path = tmp_path / "decision.json"
    output_path = tmp_path / "state" / "welle-7-sign-off.json"
    decision_path.write_text(
        json.dumps(
            {
                "verdict": "BLOCK",
                "hard_block_reasons": ["drift>0"],
            }
        ),
        encoding="utf-8",
    )
    rc = emitter.main(
        [
            "--welle",
            "7",
            "--decision-envelope",
            str(decision_path),
            "--output",
            str(output_path),
            "--signed-off-at",
            "2026-06-29T08:00:00Z",
            "--strict",
        ]
    )
    assert rc == 1
    payload = json.loads(output_path.read_text("utf-8"))
    assert payload["verdict"] == "BLOCK"
    assert payload["decision_summary"]["hard_block_reasons"] == ["drift>0"]


def test_main_envelope_missing_file_writes_block_envelope(tmp_path):
    """Missing decision envelope is handled (BLOCK + provenance note)."""
    output_path = tmp_path / "state" / "welle-4-sign-off.json"
    rc = emitter.main(
        [
            "--welle",
            "4",
            "--decision-envelope",
            str(tmp_path / "does-not-exist.json"),
            "--output",
            str(output_path),
            "--signed-off-at",
            "2026-06-26T08:00:00Z",
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text("utf-8"))
    assert payload["verdict"] == "BLOCK"
    assert any("absent" in n.lower() for n in payload["notes"])


def test_main_envelope_malformed_json_raises(tmp_path):
    """Malformed JSON is a hard error, not a silent BLOCK."""
    decision_path = tmp_path / "decision.json"
    decision_path.write_text("{not-valid-json", encoding="utf-8")
    output_path = tmp_path / "state" / "welle-2-sign-off.json"
    with pytest.raises(SystemExit) as exc:
        emitter.main(
            [
                "--welle",
                "2",
                "--decision-envelope",
                str(decision_path),
                "--output",
                str(output_path),
                "--signed-off-at",
                "2026-06-24T08:00:00Z",
            ]
        )
    assert "malformed JSON" in str(exc.value)


def test_main_output_is_deterministic_for_pinned_inputs(tmp_path):
    """Same inputs -> byte-identical output (sort_keys + indent stable)."""
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "verdict": "READY",
                "score_band_floor": "GREEN",
                "observed_band": "GREEN",
            }
        ),
        encoding="utf-8",
    )
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    rc_a = emitter.main(
        [
            "--welle",
            "6",
            "--decision-envelope",
            str(decision_path),
            "--output",
            str(out_a),
            "--signed-off-at",
            "2026-06-28T08:00:00Z",
        ]
    )
    rc_b = emitter.main(
        [
            "--welle",
            "6",
            "--decision-envelope",
            str(decision_path),
            "--output",
            str(out_b),
            "--signed-off-at",
            "2026-06-28T08:00:00Z",
        ]
    )
    assert rc_a == 0 and rc_b == 0
    assert out_a.read_bytes() == out_b.read_bytes()
