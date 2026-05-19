# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-76 tests for the Marathon-Closeout-Aggregator
(Welle-1..7 Verifier-Family Bundler).

============================================================================
Test inventory (>=20 hermetic tests, stdlib + pytest only):

  T01  Helper file exists at the expected path.
  T02  Helper file declares SPDX Apache-2.0 header and "-- Reza"
       signature line (REUSE-discipline).
  T03  A minimal valid closeout document (all-seven-welle GREEN,
       global GREEN, live-verify-gate GREEN, marker_emit_ready=true,
       bringup ready) passes verify_closeout() and produces
       MARATHON-CLOSEOUT-READY.
  T04  I-1: tag != 'Tag-76' rejected.
  T05  I-2: marathon_id != 'phase-3c-welle-marathon' rejected.
  T06  I-3: audit_only=false rejected; doc_form_only=false rejected.
  T07  I-4: malformed closeout_id (wrong prefix / too short) rejected.
  T08  I-5: missing Welle-N record rejected; duplicate welle_id
       rejected; eight wellen rejected; six wellen rejected.
  T09  I-6: welle-outcome with unknown extra field rejected;
       missing field rejected; test_count == 0 rejected;
       verifier_pin empty string rejected.
  T10  I-7: verifier_kind not in canonical set rejected;
       verifier_kind for Welle-N not matching the canonical-kind-per-
       welle expectation rejected (all 7 wellen cross-pinned).
  T11  I-8: signoff_date with wrong format rejected; signoff_date
       not matching canonical date for the welle rejected
       (all 7 wellen cross-pinned).
  T12  I-9: production_bringup_marker missing field rejected;
       trigger_kind != 'post-welle-7-signoff' rejected;
       trigger_date != '2026-07-03' rejected.
  T13  I-10: bringup_status not in canonical set rejected;
       operator_handoff_required non-bool rejected.
  T14  I-11: phase_3_complete_marker_readiness missing field
       rejected; global_verdict not in canonical set rejected;
       live_verify_gate_status not in canonical set rejected;
       emit_blocked_reason inconsistency rejected (null when
       blocked, string when ready).
  T15  I-12: marker_emit_ready=true when any welle is RED rejected
       (consistency violation).
  T16  I-12: marker_emit_ready=false when all-green-and-signed
       rejected (consistency violation).
  T17  I-13: sandbox_boundary with any of the seven booleans flipped
       to false rejected; probe_default_mode != 'inspection-only'
       rejected.
  T18  I-14: cross_anchors missing 'tag_75_welle_7_final_sealing_
       verifier' rejected.
  T19  I-15: unknown top-level field rejected (strict shape).
  T20  I-16: audit_only as int 1 (truthy but not bool) rejected.
  T21  compute_verdict: all-RED Welle-N -> DEFECT, blocking_wellen
       lists all RED wellen.
  T22  compute_verdict: one Welle CAUTION (and consistent
       readiness=false) -> PARTIAL, blocking_wellen lists that welle.
  T23  compute_verdict: all-green-and-ready -> MARATHON-CLOSEOUT-READY
       with all_green=true, marker_emit_ready=true, blocking_wellen=[].
  T24  compute_verdict: bringup_status='blocked' (with all-green
       welle outcomes) -> DEFECT.
  T25  CLI: subprocess invocation with a valid closeout JSON exits 0
       and prints a JSON envelope on stdout with verdict field.
  T26  CLI: subprocess with no arguments exits non-zero with usage
       banner on stderr.
  T27  CLI: subprocess with non-existent path exits non-zero with
       'not found' message on stderr.
  T28  CLI: subprocess with malformed JSON file exits non-zero with
       JSON parse-error message on stderr.
  T29  Sandbox-boundary recital: helper does NOT import any module
       outside the stdlib whitelist (no requests, urllib3, httpx,
       NATS-py, biscuit-auth, etc.).
  T30  All-7-Welle-cross-pin: build the canonical-kind-per-welle
       mapping in-test and assert that the helper's mapping matches
       exactly (no welle missing, no welle extra, no kind drift).
  T31  All-7-Welle-cross-pin: build the canonical signoff-date-per-
       welle mapping in-test and assert that the helper's mapping
       matches exactly (Welle-6 and Welle-7 must be 2026-07-03;
       Welle-3 must be 2026-06-19; Welle-1/2 must be 2026-06-12;
       Welle-4/5 must be 2026-06-26).

-- Reza
"""
from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_REL = "tooling/audit/verify_marathon_closeout.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


# --- import the helper as a module ----------------------------------- #
sys.path.insert(0, str(REPO_ROOT / "tooling" / "audit"))
import verify_marathon_closeout as vmc  # noqa: E402


# --- fixture builders ------------------------------------------------- #
def _valid_welle_outcome(welle_id: str, verdict: str = "GREEN") -> dict:
    kind = vmc.CANONICAL_VERIFIER_KIND_PER_WELLE[welle_id]
    sdate = vmc.CANONICAL_SIGNOFF_DATE_PER_WELLE[welle_id]
    return {
        "welle_id": welle_id,
        "verifier_pin": f"pin-{welle_id.lower()}-aaaa",
        "verifier_kind": kind,
        "verdict": verdict,
        "signoff_date": sdate,
        "test_count": 17,
    }


def _valid_closeout_doc() -> dict:
    outcomes = [
        _valid_welle_outcome(w) for w in vmc.CANONICAL_WELLE_IDS
    ]
    return {
        "tag": "Tag-76",
        "marathon_id": "phase-3c-welle-marathon",
        "audit_only": True,
        "doc_form_only": True,
        "closeout_id": "closeout-marathon-tag76-aaaa",
        "welle_verifier_outcomes": outcomes,
        "production_bringup_marker": {
            "trigger_kind": "post-welle-7-signoff",
            "trigger_date": "2026-07-03",
            "production_substrate": "production-mirror-canary",
            "bringup_status": "ready",
            "operator_handoff_required": True,
        },
        "phase_3_complete_marker_readiness": {
            "all_welle_signed_off": True,
            "global_verdict": "GREEN",
            "live_verify_gate_status": "GREEN",
            "marker_emit_ready": True,
            "emit_blocked_reason": None,
        },
        "sandbox_boundary": {
            "no_engine_invocation": True,
            "no_schema_registry_write": True,
            "no_audit_trail_write": True,
            "no_per_welle_verifier_exec": True,
            "no_marker_emission": True,
            "no_promotion_pr_opening": True,
            "no_release_tag_cut": True,
            "probe_default_mode": "inspection-only",
        },
        "cross_anchors": {
            "adr_0007": "ADR-0007 OTS substrate",
            "adr_0017": "ADR-0017 Wirelang foundation",
            "adr_0023a": "ADR-0023a substrate-anchor",
            "adr_0023b": "ADR-0023b sealing-pattern",
            "adr_0025": "ADR-0025 performance-anchor",
            "adr_0066": "ADR-0066 four-Wochen-cadence",
            "pre_cutover_acceptance_run_order_doc":
                "docs/quality-gates/pre-cutover-acceptance-run-order.md",
            "tag_75_welle_7_final_sealing_verifier":
                "tooling/audit/verify_welle_7_final_sealing.py",
            "tag_74_welle_6_parity_verifier":
                "tooling/audit/verify_cross_substrate_parity_spec.py",
            "tag_73_welle_5_capability_verifier":
                "tooling/audit/verify_capability_token_layer_state.py",
        },
    }


# --- T01-T02: structural / REUSE -------------------------------------- #
def test_t01_helper_file_exists():
    assert HELPER_PATH.is_file(), (
        f"helper file missing at {HELPER_PATH}"
    )


def test_t02_helper_file_has_spdx_and_reza_signature():
    text = HELPER_PATH.read_text(encoding="utf-8")
    # REUSE-IgnoreStart
    assert "SPDX-License-Identifier: Apache-2.0" in text, (
        "helper must carry SPDX Apache-2.0 header (REUSE-discipline)"
    )
    # REUSE-IgnoreEnd
    assert "-- Reza" in text, (
        "helper must carry '-- Reza' signature line"
    )


# --- T03: happy path -------------------------------------------------- #
def test_t03_valid_minimal_closeout_passes():
    doc = _valid_closeout_doc()
    vmc.verify_closeout(doc)  # raises on failure
    env = vmc.compute_verdict(doc)
    assert env["verdict"] == "MARATHON-CLOSEOUT-READY"
    assert env["all_green"] is True
    assert env["marker_emit_ready"] is True
    assert env["blocking_wellen"] == []
    assert env["welle_count"] == 7
    assert env["marathon_id"] == "phase-3c-welle-marathon"
    assert env["doc_version"] == "tag-76"
    assert env["schema_version"] == "1.0.0"


# --- T04-T07: tag/marathon_id/audit_only/closeout_id ------------------ #
def test_t04_tag_must_be_tag_76():
    doc = _valid_closeout_doc()
    doc["tag"] = "Tag-75"
    with pytest.raises(vmc.VerifyError, match="I-1"):
        vmc.verify_closeout(doc)


def test_t05_marathon_id_must_be_canonical():
    doc = _valid_closeout_doc()
    doc["marathon_id"] = "phase-3-welle-marathon"
    with pytest.raises(vmc.VerifyError, match="I-2"):
        vmc.verify_closeout(doc)


def test_t06_audit_only_false_rejected():
    doc = _valid_closeout_doc()
    doc["audit_only"] = False
    with pytest.raises(vmc.VerifyError, match="I-3"):
        vmc.verify_closeout(doc)
    doc = _valid_closeout_doc()
    doc["doc_form_only"] = False
    with pytest.raises(vmc.VerifyError, match="I-3"):
        vmc.verify_closeout(doc)


def test_t07_closeout_id_malformed():
    doc = _valid_closeout_doc()
    doc["closeout_id"] = "marathon-tag76"  # missing prefix
    with pytest.raises(vmc.VerifyError, match="I-4"):
        vmc.verify_closeout(doc)
    doc = _valid_closeout_doc()
    doc["closeout_id"] = "closeout-ab"  # too short
    with pytest.raises(vmc.VerifyError, match="I-4"):
        vmc.verify_closeout(doc)


# --- T08: welle outcomes cardinality / uniqueness --------------------- #
def test_t08_welle_outcomes_cardinality_and_uniqueness():
    # missing one welle (only six)
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"] = doc["welle_verifier_outcomes"][:6]
    with pytest.raises(vmc.VerifyError, match="I-5"):
        vmc.verify_closeout(doc)
    # eight wellen (one duplicated)
    doc = _valid_closeout_doc()
    extra = copy.deepcopy(doc["welle_verifier_outcomes"][0])
    doc["welle_verifier_outcomes"].append(extra)
    with pytest.raises(vmc.VerifyError, match="I-5"):
        vmc.verify_closeout(doc)
    # duplicate welle_id at length 7 (replace last with copy of first)
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][6] = copy.deepcopy(
        doc["welle_verifier_outcomes"][0]
    )
    with pytest.raises(vmc.VerifyError, match="I-5"):
        vmc.verify_closeout(doc)


# --- T09: welle-outcome field discipline ------------------------------ #
def test_t09_welle_outcome_field_discipline():
    # unknown extra field
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][0]["extra_field"] = "bogus"
    with pytest.raises(vmc.VerifyError, match="I-6"):
        vmc.verify_closeout(doc)
    # missing field
    doc = _valid_closeout_doc()
    del doc["welle_verifier_outcomes"][0]["test_count"]
    with pytest.raises(vmc.VerifyError, match="I-6"):
        vmc.verify_closeout(doc)
    # test_count == 0
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][0]["test_count"] = 0
    with pytest.raises(vmc.VerifyError, match="I-6"):
        vmc.verify_closeout(doc)
    # verifier_pin empty string
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][0]["verifier_pin"] = ""
    with pytest.raises(vmc.VerifyError, match="I-6"):
        vmc.verify_closeout(doc)


# --- T10: verifier_kind discipline + all-7-welle-cross-pin ------------ #
def test_t10_verifier_kind_canonical_and_per_welle_cross_pin():
    # unknown kind
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][0]["verifier_kind"] = "unknown-kind"
    with pytest.raises(vmc.VerifyError, match="I-7"):
        vmc.verify_closeout(doc)
    # per-welle mismatch: each welle must reject all six wrong kinds.
    # Cross-pin every one of the 7 wellen against its canonical kind.
    for idx, welle_id in enumerate(vmc.CANONICAL_WELLE_IDS):
        for wrong_kind in vmc.CANONICAL_VERIFIER_KINDS:
            if wrong_kind == vmc.CANONICAL_VERIFIER_KIND_PER_WELLE[welle_id]:
                continue
            doc = _valid_closeout_doc()
            doc["welle_verifier_outcomes"][idx]["verifier_kind"] = wrong_kind
            with pytest.raises(vmc.VerifyError, match="I-7"):
                vmc.verify_closeout(doc)


# --- T11: signoff_date discipline + all-7-welle-cross-pin ------------- #
def test_t11_signoff_date_format_and_per_welle_cross_pin():
    # wrong format
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][0]["signoff_date"] = "2026/06/12"
    with pytest.raises(vmc.VerifyError, match="I-8"):
        vmc.verify_closeout(doc)
    # per-welle canonical date mismatch: for each welle, set a wrong
    # date and expect rejection. This pins all 7 wellen.
    wrong_date_pool = [
        "2026-06-10",  # cutover-mittwoch not sign-off-Freitag
        "2026-07-04",  # day after Welle-7 sign-off
        "2026-06-20",  # outside any welle
    ]
    for idx, welle_id in enumerate(vmc.CANONICAL_WELLE_IDS):
        canonical = vmc.CANONICAL_SIGNOFF_DATE_PER_WELLE[welle_id]
        for wrong in wrong_date_pool:
            if wrong == canonical:
                continue
            doc = _valid_closeout_doc()
            doc["welle_verifier_outcomes"][idx]["signoff_date"] = wrong
            with pytest.raises(vmc.VerifyError, match="I-8"):
                vmc.verify_closeout(doc)


# --- T12: production_bringup_marker fields ---------------------------- #
def test_t12_production_bringup_marker_fields():
    # missing field
    doc = _valid_closeout_doc()
    del doc["production_bringup_marker"]["trigger_date"]
    with pytest.raises(vmc.VerifyError, match="I-9"):
        vmc.verify_closeout(doc)
    # wrong trigger_kind
    doc = _valid_closeout_doc()
    doc["production_bringup_marker"]["trigger_kind"] = "post-welle-6-signoff"
    with pytest.raises(vmc.VerifyError, match="I-9"):
        vmc.verify_closeout(doc)
    # wrong trigger_date
    doc = _valid_closeout_doc()
    doc["production_bringup_marker"]["trigger_date"] = "2026-07-04"
    with pytest.raises(vmc.VerifyError, match="I-9"):
        vmc.verify_closeout(doc)


# --- T13: bringup_status / operator_handoff_required ------------------ #
def test_t13_bringup_status_and_operator_handoff():
    doc = _valid_closeout_doc()
    doc["production_bringup_marker"]["bringup_status"] = "GREEN"
    with pytest.raises(vmc.VerifyError, match="I-10"):
        vmc.verify_closeout(doc)
    doc = _valid_closeout_doc()
    doc["production_bringup_marker"]["operator_handoff_required"] = 1
    with pytest.raises(vmc.VerifyError, match="I-10"):
        vmc.verify_closeout(doc)


# --- T14: phase_3_complete_marker_readiness fields -------------------- #
def test_t14_phase_3_complete_marker_readiness_fields():
    # missing field
    doc = _valid_closeout_doc()
    del doc["phase_3_complete_marker_readiness"]["global_verdict"]
    with pytest.raises(vmc.VerifyError, match="I-11"):
        vmc.verify_closeout(doc)
    # global_verdict not canonical
    doc = _valid_closeout_doc()
    doc["phase_3_complete_marker_readiness"]["global_verdict"] = "READY"
    with pytest.raises(vmc.VerifyError, match="I-11"):
        vmc.verify_closeout(doc)
    # live_verify_gate_status not canonical
    doc = _valid_closeout_doc()
    doc["phase_3_complete_marker_readiness"][
        "live_verify_gate_status"
    ] = "ok"
    with pytest.raises(vmc.VerifyError, match="I-11"):
        vmc.verify_closeout(doc)
    # emit_blocked_reason inconsistency: reason set while
    # marker_emit_ready=true
    doc = _valid_closeout_doc()
    doc["phase_3_complete_marker_readiness"][
        "emit_blocked_reason"
    ] = "should be null when ready"
    with pytest.raises(vmc.VerifyError, match="I-11"):
        vmc.verify_closeout(doc)


# --- T15-T16: marker_emit_ready consistency --------------------------- #
def test_t15_marker_emit_ready_true_with_red_welle_rejected():
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][3]["verdict"] = "RED"
    # marker_emit_ready remains true -> consistency violation
    with pytest.raises(vmc.VerifyError, match="I-12"):
        vmc.verify_closeout(doc)


def test_t16_marker_emit_ready_false_when_all_green_rejected():
    doc = _valid_closeout_doc()
    doc["phase_3_complete_marker_readiness"]["marker_emit_ready"] = False
    doc["phase_3_complete_marker_readiness"][
        "emit_blocked_reason"
    ] = "manually paused for inspection"
    # but all welle outcomes are GREEN and global GREEN -> inconsistency
    with pytest.raises(vmc.VerifyError, match="I-12"):
        vmc.verify_closeout(doc)


# --- T17: sandbox_boundary discipline --------------------------------- #
def test_t17_sandbox_boundary_discipline():
    for key in vmc.CANONICAL_BOUNDARY_BOOL_KEYS:
        doc = _valid_closeout_doc()
        doc["sandbox_boundary"][key] = False
        with pytest.raises(vmc.VerifyError, match="I-13"):
            vmc.verify_closeout(doc)
    doc = _valid_closeout_doc()
    doc["sandbox_boundary"]["probe_default_mode"] = "live"
    with pytest.raises(vmc.VerifyError, match="I-13"):
        vmc.verify_closeout(doc)


# --- T18: cross_anchors discipline ------------------------------------ #
def test_t18_cross_anchors_missing_tag75_anchor():
    doc = _valid_closeout_doc()
    del doc["cross_anchors"]["tag_75_welle_7_final_sealing_verifier"]
    with pytest.raises(vmc.VerifyError, match="I-14"):
        vmc.verify_closeout(doc)


# --- T19: strict top-level shape -------------------------------------- #
def test_t19_unknown_top_level_field_rejected():
    doc = _valid_closeout_doc()
    doc["extra_top_level"] = {"x": 1}
    with pytest.raises(vmc.VerifyError, match="I-15"):
        vmc.verify_closeout(doc)


# --- T20: audit_only type strictness ---------------------------------- #
def test_t20_audit_only_as_int_rejected():
    doc = _valid_closeout_doc()
    doc["audit_only"] = 1  # truthy int, but not bool
    with pytest.raises(vmc.VerifyError, match="I-16"):
        vmc.verify_closeout(doc)


# --- T21: compute_verdict DEFECT-on-RED ------------------------------- #
def test_t21_compute_verdict_red_to_defect():
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][2]["verdict"] = "RED"
    doc["welle_verifier_outcomes"][5]["verdict"] = "RED"
    # Make consistency hold so verify_closeout passes
    doc["phase_3_complete_marker_readiness"]["global_verdict"] = "RED"
    doc["phase_3_complete_marker_readiness"]["marker_emit_ready"] = False
    doc["phase_3_complete_marker_readiness"][
        "emit_blocked_reason"
    ] = "Welle-3 and Welle-6 RED"
    vmc.verify_closeout(doc)
    env = vmc.compute_verdict(doc)
    assert env["verdict"] == "DEFECT"
    assert env["all_green"] is False
    assert "Welle-3" in env["blocking_wellen"]
    assert "Welle-6" in env["blocking_wellen"]


# --- T22: compute_verdict PARTIAL-on-CAUTION -------------------------- #
def test_t22_compute_verdict_caution_to_partial():
    doc = _valid_closeout_doc()
    doc["welle_verifier_outcomes"][4]["verdict"] = "CAUTION"
    # consistency: emit not ready
    doc["phase_3_complete_marker_readiness"][
        "global_verdict"
    ] = "CAUTION"
    doc["phase_3_complete_marker_readiness"]["marker_emit_ready"] = False
    doc["phase_3_complete_marker_readiness"][
        "emit_blocked_reason"
    ] = "Welle-5 CAUTION"
    doc["production_bringup_marker"]["bringup_status"] = "pending"
    vmc.verify_closeout(doc)
    env = vmc.compute_verdict(doc)
    assert env["verdict"] == "PARTIAL"
    assert "Welle-5" in env["blocking_wellen"]


# --- T23: compute_verdict MARATHON-CLOSEOUT-READY --------------------- #
def test_t23_compute_verdict_all_green_ready():
    doc = _valid_closeout_doc()
    vmc.verify_closeout(doc)
    env = vmc.compute_verdict(doc)
    assert env["verdict"] == "MARATHON-CLOSEOUT-READY"
    assert env["all_green"] is True
    assert env["marker_emit_ready"] is True
    assert env["blocking_wellen"] == []


# --- T24: compute_verdict DEFECT-on-bringup-blocked ------------------- #
def test_t24_compute_verdict_bringup_blocked_to_defect():
    doc = _valid_closeout_doc()
    # all green outcomes, but bringup blocked. Make consistency hold:
    # marker_emit_ready stays true (still inputs are all green) but
    # verdict-aggregator catches blocked status.
    doc["production_bringup_marker"]["bringup_status"] = "blocked"
    vmc.verify_closeout(doc)
    env = vmc.compute_verdict(doc)
    assert env["verdict"] == "DEFECT"


# --- T25-T28: CLI ----------------------------------------------------- #
def test_t25_cli_valid_closeout_exits_0(tmp_path):
    doc = _valid_closeout_doc()
    p = tmp_path / "closeout.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(p)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}, "
        f"stderr={result.stderr!r}, stdout={result.stdout!r}"
    )
    envelope = json.loads(result.stdout)
    assert envelope["verdict"] == "MARATHON-CLOSEOUT-READY"
    assert envelope["welle_count"] == 7
    assert envelope["doc_version"] == "tag-76"


def test_t26_cli_no_arguments_exits_nonzero():
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "usage" in result.stderr


def test_t27_cli_nonexistent_path_exits_nonzero(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(missing)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_t28_cli_malformed_json_exits_nonzero(tmp_path):
    p = tmp_path / "garbled.json"
    p.write_text("{not-json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(p)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr


# --- T29: sandbox-boundary recital (import discipline) ---------------- #
def test_t29_helper_imports_stdlib_only():
    text = HELPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.append(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
    # Whitelisted stdlib roots only
    allowed = {
        "__future__", "json", "re", "sys", "typing",
    }
    bad = [i for i in imports if i not in allowed]
    assert not bad, (
        f"helper must import stdlib-only; offending imports: {bad!r}"
    )


# --- T30: all-7-welle cross-pin (canonical-kind mapping) -------------- #
def test_t30_canonical_verifier_kind_per_welle_cross_pin():
    expected = {
        "Welle-1": "v907-verify",
        "Welle-2": "state-conventions",
        "Welle-3": "recipe-patch-doc",
        "Welle-4": "state-backing",
        "Welle-5": "capability-token",
        "Welle-6": "parity",
        "Welle-7": "final-sealing",
    }
    assert vmc.CANONICAL_VERIFIER_KIND_PER_WELLE == expected, (
        "canonical-kind-per-welle mapping drift detected; "
        "the helper's mapping must match the brief's mapping exactly"
    )
    # Every welle covered exactly once
    assert set(vmc.CANONICAL_VERIFIER_KIND_PER_WELLE.keys()) == set(
        vmc.CANONICAL_WELLE_IDS
    )
    # Every kind in the mapping is itself canonical
    for kind in vmc.CANONICAL_VERIFIER_KIND_PER_WELLE.values():
        assert kind in vmc.CANONICAL_VERIFIER_KINDS


# --- T31: all-7-welle cross-pin (canonical signoff-date mapping) ----- #
def test_t31_canonical_signoff_date_per_welle_cross_pin():
    # Per pre-cutover-acceptance-run-order.md §3.2 (Tag-57 canonical):
    #   Welle-1 KW-24 sign-off-Freitag 2026-06-12
    #   Welle-2 KW-24 sign-off-Freitag 2026-06-12 (Doppel-Welle-1+2)
    #   Welle-3 KW-25 sign-off-Freitag 2026-06-19
    #   Welle-4 KW-26 sign-off-Freitag 2026-06-26
    #   Welle-5 KW-26 sign-off-Freitag 2026-06-26 (Doppel-Welle-4+5)
    #   Welle-6 KW-27 sign-off-Freitag 2026-07-03
    #   Welle-7 KW-27 sign-off-Freitag 2026-07-03 (Doppel-Welle-6+7)
    expected = {
        "Welle-1": "2026-06-12",
        "Welle-2": "2026-06-12",
        "Welle-3": "2026-06-19",
        "Welle-4": "2026-06-26",
        "Welle-5": "2026-06-26",
        "Welle-6": "2026-07-03",
        "Welle-7": "2026-07-03",
    }
    assert vmc.CANONICAL_SIGNOFF_DATE_PER_WELLE == expected, (
        "canonical-signoff-date-per-welle mapping drift detected; "
        "the helper's mapping must match pre-cutover-acceptance-run-"
        "order.md §3.2 exactly"
    )
    assert vmc.EXPECTED_WELLE_7_SIGNOFF_DATE == "2026-07-03"
