# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-75 tests for the Welle-7 (Final-Sealing)
Spec-Conformance Verifier.

============================================================================
Test inventory (>=15 hermetic tests, stdlib + pytest only):

  T01  Helper file exists at the expected path.
  T02  Helper file declares SPDX Apache-2.0 header and "-- Reza"
       signature line (REUSE-discipline).
  T03  A minimal valid sealing document (six signed-off wellen,
       capability + parity families, two-link OTS-chain) passes
       verify_sealing().
  T04  I-1: A document with tag != 'Tag-75' is rejected.
  T05  I-1: A document with welle != 'Welle-7' is rejected.
  T06  I-2: A document with audit_only flipped to false is rejected.
  T07  I-2: A document with doc_form_only flipped to false is rejected.
  T08  I-3: A document with sealing_scope != 'Final-Sealing' is
       rejected.
  T09  I-4: A document with malformed sealing_id (wrong prefix or
       too short) is rejected.
  T10  I-5: A document missing one canonical welle is rejected;
       seven wellen rejected; duplicate welle_id rejected.
  T11  I-6: A welle-record with signoff_status='pending' is rejected
       (final sealing requires every predecessor signed-off);
       missing field rejected; unknown extra field rejected.
  T12  I-20: A welle-record with signoff_status='rejected' is
       rejected with I-20 (terminal-refusal).
  T13  I-7: An empty marker_families list is rejected; a list
       missing the 'capability' cornerstone family is rejected; a
       list missing the 'parity' cornerstone family is rejected;
       duplicate family_ids are rejected.
  T14  I-8: A family-record with unknown extra field is rejected;
       marker_count == 0 is rejected; family_id malformed is
       rejected; empty anchor_pins list is rejected.
  T15  I-9: A 'finalised' family with len(anchor_pins) != marker_count
       is rejected; a 'partial' family with len(anchor_pins) >=
       marker_count is rejected; an 'open' family with
       len(anchor_pins) >= marker_count is rejected.
  T16  I-10: ots_anchor_chain missing field rejected; empty links
       list rejected; chain_complete non-bool rejected.
  T17  I-11: A link with non-zero head link_index (no link_index=0)
       is rejected; a link with predecessor_pin not matching
       previous link's anchor_pin is rejected; head link with
       predecessor_pin != null is rejected.
  T18  I-12: head_anchor_pin not matching the lowest-index link's
       anchor_pin is rejected; tail_anchor_pin mismatch is rejected.
  T19  I-13: chain_complete=true with a gap in link_index is
       rejected; chain_complete=false with gap_count exceeding
       budget is rejected.
  T20  I-14: sealing_budget missing field is rejected;
       max_unfinalised_families out of [0,2] is rejected;
       tolerated_signoff_kinds with non-canonical entry is rejected.
  T21  I-15: unfinalised family count exceeding budget is rejected.
  T22  I-16: sandbox_boundary with one of the six booleans flipped
       to false is rejected; probe_default_mode != 'inspection-only'
       is rejected; no_release_tag_cut flipped to false is rejected.
  T23  I-17: cross_anchors missing 'tag_74_parity_layer' is rejected.
  T24  I-18: An unknown top-level field is rejected (strict shape).
  T25  I-19: audit_only as int 1 (truthy but not bool) is rejected.
  T26  CLI: subprocess invocation with a valid sealing JSON exits 0
       and prints the expected OK banner.
  T27  CLI: subprocess invocation with no arguments exits non-zero
       with the usage banner on stderr.
  T28  CLI: subprocess invocation with a non-existent path exits
       non-zero with a 'not found' message on stderr.
  T29  CLI: subprocess invocation with a malformed JSON file exits
       non-zero with a JSON parse-error message on stderr.
  T30  Sandbox-boundary recital: helper does NOT import any module
       outside the stdlib whitelist (no requests, urllib3, httpx,
       NATS-py, etc.).
  T31  A 'partial' family within budget passes verify_sealing().
  T32  A chain_complete=false document with gap_count == 1 (within
       max_chain_gap_count budget of 1) passes verify_sealing().

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
HELPER_REL = "tooling/audit/verify_welle_7_final_sealing.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


# --- import the helper as a module ----------------------------------- #
sys.path.insert(0, str(REPO_ROOT / "tooling" / "audit"))
import verify_welle_7_final_sealing as vws  # noqa: E402


# --------------------------------------------------------------------- #
# Canonical valid fixtures                                              #
# --------------------------------------------------------------------- #


def _base_doc() -> dict:
    """Return a minimal valid Welle-7 final-sealing document."""
    return {
        "tag": "Tag-75",
        "welle": "Welle-7",
        "audit_only": True,
        "doc_form_only": True,
        "sealing_scope": "Final-Sealing",
        "sealing_id": "sealing-welle7-test-0001",
        "predecessor_wellen": [
            {
                "welle_id": "Welle-1",
                "tag_origin": "Tag-69",
                "signoff_kind": "spec",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle1-pin",
            },
            {
                "welle_id": "Welle-2",
                "tag_origin": "Tag-70",
                "signoff_kind": "substrate",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle2-pin",
            },
            {
                "welle_id": "Welle-3",
                "tag_origin": "Tag-71",
                "signoff_kind": "substrate",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle3-pin",
            },
            {
                "welle_id": "Welle-4",
                "tag_origin": "Tag-72",
                "signoff_kind": "substrate",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle4-pin",
            },
            {
                "welle_id": "Welle-5",
                "tag_origin": "Tag-73",
                "signoff_kind": "verifier",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle5-pin",
            },
            {
                "welle_id": "Welle-6",
                "tag_origin": "Tag-74",
                "signoff_kind": "parity",
                "signoff_status": "signed-off",
                "anchor_pin": "anchor-welle6-pin",
            },
        ],
        "marker_families": [
            {
                "family_id": "family-capability-core-01",
                "family_kind": "capability",
                "finalisation_status": "finalised",
                "marker_count": 2,
                "anchor_pins": [
                    "cap-pin-001",
                    "cap-pin-002",
                ],
            },
            {
                "family_id": "family-parity-core-01",
                "family_kind": "parity",
                "finalisation_status": "finalised",
                "marker_count": 1,
                "anchor_pins": [
                    "par-pin-001",
                ],
            },
        ],
        "ots_anchor_chain": {
            "links": [
                {
                    "link_index": 0,
                    "predecessor_pin": None,
                    "successor_pin": "ots-pin-tail",
                    "anchor_pin": "ots-pin-head",
                },
                {
                    "link_index": 1,
                    "predecessor_pin": "ots-pin-head",
                    "successor_pin": None,
                    "anchor_pin": "ots-pin-tail",
                },
            ],
            "head_anchor_pin": "ots-pin-head",
            "tail_anchor_pin": "ots-pin-tail",
            "chain_complete": True,
        },
        "sealing_budget": {
            "max_unfinalised_families": 1,
            "max_chain_gap_count": 1,
            "tolerated_signoff_kinds": ["sweep", "spec"],
        },
        "sandbox_boundary": {
            "no_engine_invocation": True,
            "no_schema_registry_write": True,
            "no_audit_trail_write": True,
            "no_spec_compiler_call": True,
            "no_promotion_pr_opening": True,
            "no_release_tag_cut": True,
            "probe_default_mode": "inspection-only",
        },
        "cross_anchors": {
            "adr_0007": "adr-0007-ots-anchor",
            "adr_0017": "adr-0017-capability-tokens",
            "adr_0023a": "adr-0023a",
            "adr_0023b": "adr-0023b",
            "adr_0025": "adr-0025-three-axis-perf",
            "wat_layer_4_anchor": "wat-layer-4-merkle",
            "wirelang_layer_3_schema": "wirelang-layer-3",
            "tag_73_capability_layer": "tag-73-welle-5-cap-token",
            "tag_74_parity_layer": "tag-74-welle-6-parity",
        },
    }


def _doc() -> dict:
    return copy.deepcopy(_base_doc())


# --------------------------------------------------------------------- #
# Structural / file-level                                               #
# --------------------------------------------------------------------- #


def test_t01_helper_file_exists() -> None:
    assert HELPER_PATH.is_file(), (
        f"helper file must exist at {HELPER_PATH!s}"
    )


def test_t02_helper_spdx_and_signature() -> None:
    text = HELPER_PATH.read_text(encoding="utf-8")
    # REUSE-IgnoreStart
    assert "SPDX-License-Identifier: Apache-2.0" in text, (
        "helper must carry SPDX-License-Identifier: Apache-2.0 header"
    )
    # REUSE-IgnoreEnd
    assert "-- Reza" in text, (
        "helper must carry '-- Reza' signature line"
    )


# --------------------------------------------------------------------- #
# Happy-path                                                            #
# --------------------------------------------------------------------- #


def test_t03_minimal_valid_sealing_doc_passes() -> None:
    vws.verify_sealing(_doc())


# --------------------------------------------------------------------- #
# I-1                                                                   #
# --------------------------------------------------------------------- #


def test_t04_wrong_tag_rejected() -> None:
    doc = _doc()
    doc["tag"] = "Tag-74"
    with pytest.raises(vws.VerifyError, match=r"^I-1:"):
        vws.verify_sealing(doc)


def test_t05_wrong_welle_rejected() -> None:
    doc = _doc()
    doc["welle"] = "Welle-6"
    with pytest.raises(vws.VerifyError, match=r"^I-1:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-2                                                                   #
# --------------------------------------------------------------------- #


def test_t06_audit_only_false_rejected() -> None:
    doc = _doc()
    doc["audit_only"] = False
    with pytest.raises(vws.VerifyError, match=r"^I-2:"):
        vws.verify_sealing(doc)


def test_t07_doc_form_only_false_rejected() -> None:
    doc = _doc()
    doc["doc_form_only"] = False
    with pytest.raises(vws.VerifyError, match=r"^I-2:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-3                                                                   #
# --------------------------------------------------------------------- #


def test_t08_wrong_sealing_scope_rejected() -> None:
    doc = _doc()
    doc["sealing_scope"] = "Partial-Sealing"
    with pytest.raises(vws.VerifyError, match=r"^I-3:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-4                                                                   #
# --------------------------------------------------------------------- #


def test_t09_malformed_sealing_id_rejected() -> None:
    doc = _doc()
    doc["sealing_id"] = "SEALING-UPPERCASE-WRONG"
    with pytest.raises(vws.VerifyError, match=r"^I-4:"):
        vws.verify_sealing(doc)
    doc["sealing_id"] = "sealing-x"  # too short (suffix must be >=4)
    with pytest.raises(vws.VerifyError, match=r"^I-4:"):
        vws.verify_sealing(doc)
    doc["sealing_id"] = "rot-wrong-prefix-0001"
    with pytest.raises(vws.VerifyError, match=r"^I-4:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-5                                                                   #
# --------------------------------------------------------------------- #


def test_t10_predecessor_wellen_count_and_uniqueness() -> None:
    # missing one canonical welle
    doc = _doc()
    doc["predecessor_wellen"] = doc["predecessor_wellen"][:5]
    with pytest.raises(vws.VerifyError, match=r"^I-5:"):
        vws.verify_sealing(doc)
    # seven wellen -> count failure
    doc = _doc()
    extra = dict(doc["predecessor_wellen"][0])
    doc["predecessor_wellen"].append(extra)
    with pytest.raises(vws.VerifyError, match=r"^I-5:"):
        vws.verify_sealing(doc)
    # duplicate welle_id (replace Welle-2 with second Welle-1)
    doc = _doc()
    doc["predecessor_wellen"][1]["welle_id"] = "Welle-1"
    with pytest.raises(vws.VerifyError, match=r"^I-5:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-6                                                                   #
# --------------------------------------------------------------------- #


def test_t11_welle_record_shape_rejects() -> None:
    # signoff_status='pending' (final sealing requires signed-off)
    doc = _doc()
    doc["predecessor_wellen"][0]["signoff_status"] = "pending"
    with pytest.raises(vws.VerifyError, match=r"^I-6:"):
        vws.verify_sealing(doc)
    # missing field
    doc = _doc()
    del doc["predecessor_wellen"][0]["anchor_pin"]
    with pytest.raises(vws.VerifyError, match=r"^I-6:"):
        vws.verify_sealing(doc)
    # unknown extra field
    doc = _doc()
    doc["predecessor_wellen"][0]["unknown_field"] = "x"
    with pytest.raises(vws.VerifyError, match=r"^I-6:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-20 (terminal rejection)                                             #
# --------------------------------------------------------------------- #


def test_t12_welle_signoff_rejected_is_terminal() -> None:
    doc = _doc()
    doc["predecessor_wellen"][2]["signoff_status"] = "rejected"
    with pytest.raises(vws.VerifyError, match=r"^I-20:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-7                                                                   #
# --------------------------------------------------------------------- #


def test_t13_marker_families_shape_rejects() -> None:
    # empty marker_families list
    doc = _doc()
    doc["marker_families"] = []
    with pytest.raises(vws.VerifyError, match=r"^I-7:"):
        vws.verify_sealing(doc)
    # missing 'capability' cornerstone
    doc = _doc()
    doc["marker_families"][0]["family_kind"] = "spec"
    with pytest.raises(vws.VerifyError, match=r"^I-7:"):
        vws.verify_sealing(doc)
    # missing 'parity' cornerstone
    doc = _doc()
    doc["marker_families"][1]["family_kind"] = "sweep"
    with pytest.raises(vws.VerifyError, match=r"^I-7:"):
        vws.verify_sealing(doc)
    # duplicate family_id
    doc = _doc()
    dup = copy.deepcopy(doc["marker_families"][0])
    doc["marker_families"].append(dup)
    with pytest.raises(vws.VerifyError, match=r"^I-7:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-8                                                                   #
# --------------------------------------------------------------------- #


def test_t14_family_record_shape_rejects() -> None:
    # unknown extra field
    doc = _doc()
    doc["marker_families"][0]["surprise"] = True
    with pytest.raises(vws.VerifyError, match=r"^I-8:"):
        vws.verify_sealing(doc)
    # marker_count == 0
    doc = _doc()
    doc["marker_families"][0]["marker_count"] = 0
    with pytest.raises(vws.VerifyError, match=r"^I-8:"):
        vws.verify_sealing(doc)
    # malformed family_id
    doc = _doc()
    doc["marker_families"][0]["family_id"] = "FAMILY-UPPERCASE"
    with pytest.raises(vws.VerifyError, match=r"^I-8:"):
        vws.verify_sealing(doc)
    # empty anchor_pins
    doc = _doc()
    doc["marker_families"][0]["anchor_pins"] = []
    with pytest.raises(vws.VerifyError, match=r"^I-8:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-9                                                                   #
# --------------------------------------------------------------------- #


def test_t15_finalisation_status_consistency_rejects() -> None:
    # 'finalised' with len(anchor_pins) != marker_count
    doc = _doc()
    doc["marker_families"][0]["marker_count"] = 3  # but only 2 pins
    with pytest.raises(vws.VerifyError, match=r"^I-9:"):
        vws.verify_sealing(doc)
    # 'partial' with len(anchor_pins) >= marker_count
    doc = _doc()
    doc["marker_families"][0]["finalisation_status"] = "partial"
    # marker_count is 2, anchor_pins is 2 -> not strictly less
    with pytest.raises(vws.VerifyError, match=r"^I-9:"):
        vws.verify_sealing(doc)
    # 'open' with len(anchor_pins) >= marker_count
    doc = _doc()
    doc["marker_families"][0]["finalisation_status"] = "open"
    with pytest.raises(vws.VerifyError, match=r"^I-9:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-10                                                                  #
# --------------------------------------------------------------------- #


def test_t16_ots_anchor_chain_shape_rejects() -> None:
    # missing field
    doc = _doc()
    del doc["ots_anchor_chain"]["chain_complete"]
    with pytest.raises(vws.VerifyError, match=r"^I-10:"):
        vws.verify_sealing(doc)
    # empty links list
    doc = _doc()
    doc["ots_anchor_chain"]["links"] = []
    with pytest.raises(vws.VerifyError, match=r"^I-10:"):
        vws.verify_sealing(doc)
    # chain_complete non-bool
    doc = _doc()
    doc["ots_anchor_chain"]["chain_complete"] = "yes"
    with pytest.raises(vws.VerifyError, match=r"^I-10:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-11                                                                  #
# --------------------------------------------------------------------- #


def test_t17_chain_link_consistency_rejects() -> None:
    # head link_index != 0 (lowest must be 0)
    doc = _doc()
    for link in doc["ots_anchor_chain"]["links"]:
        link["link_index"] += 1
    # also fix head/tail predecessor/successor pins so other checks
    # do not fire first. Actually min_idx=1 triggers I-11 immediately.
    with pytest.raises(vws.VerifyError, match=r"^I-11:"):
        vws.verify_sealing(doc)

    # predecessor_pin doesn't match previous link's anchor_pin
    doc = _doc()
    doc["ots_anchor_chain"]["links"][1]["predecessor_pin"] = "wrong-pin"
    with pytest.raises(vws.VerifyError, match=r"^I-11:"):
        vws.verify_sealing(doc)

    # head link with predecessor_pin != null
    doc = _doc()
    doc["ots_anchor_chain"]["links"][0]["predecessor_pin"] = "ghost-pin"
    with pytest.raises(vws.VerifyError, match=r"^I-11:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-12                                                                  #
# --------------------------------------------------------------------- #


def test_t18_head_tail_pin_mismatch_rejected() -> None:
    # head_anchor_pin != lowest-index link's anchor_pin
    doc = _doc()
    doc["ots_anchor_chain"]["head_anchor_pin"] = "wrong-head"
    with pytest.raises(vws.VerifyError, match=r"^I-12:"):
        vws.verify_sealing(doc)
    # tail_anchor_pin mismatch
    doc = _doc()
    doc["ots_anchor_chain"]["tail_anchor_pin"] = "wrong-tail"
    with pytest.raises(vws.VerifyError, match=r"^I-12:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-13                                                                  #
# --------------------------------------------------------------------- #


def test_t19_chain_complete_gap_rejected() -> None:
    # chain_complete=true with gap in link_index
    doc = _doc()
    # Add a link_index=3 link (gap at 2). Fix predecessor/successor:
    # links: 0 -> 1 -> 3 (gap at 2). Chain_complete must become false
    # for the doc to be valid; we leave it true to trigger I-13.
    # Need to rewire successor of link 1 to point at the new link, and
    # predecessor of the new link to point at link 1's anchor pin.
    new_link = {
        "link_index": 3,
        "predecessor_pin": "ots-pin-tail",
        "successor_pin": None,
        "anchor_pin": "ots-pin-far",
    }
    # rewire old tail link (link_index=1) successor to new_link anchor
    doc["ots_anchor_chain"]["links"][1]["successor_pin"] = "ots-pin-far"
    doc["ots_anchor_chain"]["links"].append(new_link)
    doc["ots_anchor_chain"]["tail_anchor_pin"] = "ots-pin-far"
    # chain_complete still True -> I-13 fires
    with pytest.raises(vws.VerifyError, match=r"^I-13:"):
        vws.verify_sealing(doc)

    # chain_complete=false with gap_count exceeding budget (budget=1)
    doc = _doc()
    # build a 4-link chain with gap of 2 (indices 0,1,4,5 -> max=5,
    # count=4, gap_count = 5+1-4 = 2). Budget is 1.
    doc["ots_anchor_chain"]["links"] = [
        {
            "link_index": 0,
            "predecessor_pin": None,
            "successor_pin": "p1",
            "anchor_pin": "p0",
        },
        {
            "link_index": 1,
            "predecessor_pin": "p0",
            "successor_pin": "p4",
            "anchor_pin": "p1",
        },
        {
            "link_index": 4,
            "predecessor_pin": "p1",
            "successor_pin": "p5",
            "anchor_pin": "p4",
        },
        {
            "link_index": 5,
            "predecessor_pin": "p4",
            "successor_pin": None,
            "anchor_pin": "p5",
        },
    ]
    doc["ots_anchor_chain"]["head_anchor_pin"] = "p0"
    doc["ots_anchor_chain"]["tail_anchor_pin"] = "p5"
    doc["ots_anchor_chain"]["chain_complete"] = False
    with pytest.raises(vws.VerifyError, match=r"^I-13:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-14                                                                  #
# --------------------------------------------------------------------- #


def test_t20_sealing_budget_shape_rejects() -> None:
    # missing field
    doc = _doc()
    del doc["sealing_budget"]["max_unfinalised_families"]
    with pytest.raises(vws.VerifyError, match=r"^I-14:"):
        vws.verify_sealing(doc)
    # max_unfinalised_families out of [0,2]
    doc = _doc()
    doc["sealing_budget"]["max_unfinalised_families"] = 3
    with pytest.raises(vws.VerifyError, match=r"^I-14:"):
        vws.verify_sealing(doc)
    # tolerated_signoff_kinds with non-canonical entry
    doc = _doc()
    doc["sealing_budget"]["tolerated_signoff_kinds"] = ["nonsense"]
    with pytest.raises(vws.VerifyError, match=r"^I-14:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-15                                                                  #
# --------------------------------------------------------------------- #


def test_t21_unfinalised_count_over_budget_rejected() -> None:
    doc = _doc()
    # budget is 1 unfinalised; introduce 2 partials.
    doc["marker_families"][0]["finalisation_status"] = "partial"
    doc["marker_families"][0]["marker_count"] = 5  # 2 pins < 5
    doc["marker_families"][1]["finalisation_status"] = "partial"
    doc["marker_families"][1]["marker_count"] = 5  # 1 pin < 5
    with pytest.raises(vws.VerifyError, match=r"^I-15:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-16                                                                  #
# --------------------------------------------------------------------- #


def test_t22_sandbox_boundary_rejects() -> None:
    doc = _doc()
    doc["sandbox_boundary"]["no_engine_invocation"] = False
    with pytest.raises(vws.VerifyError, match=r"^I-16:"):
        vws.verify_sealing(doc)

    doc = _doc()
    doc["sandbox_boundary"]["probe_default_mode"] = "active-call"
    with pytest.raises(vws.VerifyError, match=r"^I-16:"):
        vws.verify_sealing(doc)

    doc = _doc()
    doc["sandbox_boundary"]["no_release_tag_cut"] = False
    with pytest.raises(vws.VerifyError, match=r"^I-16:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-17                                                                  #
# --------------------------------------------------------------------- #


def test_t23_missing_cross_anchor_rejected() -> None:
    doc = _doc()
    del doc["cross_anchors"]["tag_74_parity_layer"]
    with pytest.raises(vws.VerifyError, match=r"^I-17:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-18                                                                  #
# --------------------------------------------------------------------- #


def test_t24_unknown_top_level_field_rejected() -> None:
    doc = _doc()
    doc["surprise_extra_field"] = "boom"
    with pytest.raises(vws.VerifyError, match=r"^I-18:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# I-19                                                                  #
# --------------------------------------------------------------------- #


def test_t25_audit_only_non_bool_rejected() -> None:
    doc = _doc()
    doc["audit_only"] = 1  # truthy but not bool
    with pytest.raises(vws.VerifyError, match=r"^I-19:"):
        vws.verify_sealing(doc)


# --------------------------------------------------------------------- #
# CLI                                                                   #
# --------------------------------------------------------------------- #


def test_t26_cli_valid_doc_exits_zero(tmp_path: Path) -> None:
    doc = _doc()
    p = tmp_path / "sealing.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(p)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"CLI should exit 0 on valid doc, got rc={result.returncode}, "
        f"stderr={result.stderr!r}"
    )
    assert "verify_welle_7_final_sealing: OK" in result.stdout
    assert "Tag-75" in result.stdout
    assert "Welle-7" in result.stdout


def test_t27_cli_no_args_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_t28_cli_missing_file_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_t29_cli_malformed_json_exits_nonzero(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(p)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr


# --------------------------------------------------------------------- #
# Sandbox-boundary recital                                              #
# --------------------------------------------------------------------- #


def test_t30_helper_imports_stdlib_only() -> None:
    """Parse helper AST and confirm no forbidden third-party imports."""
    forbidden = {
        "requests",
        "urllib3",
        "httpx",
        "aiohttp",
        "nats",
        "biscuit",
        "biscuit_auth",
        "pynacl",
        "cryptography",
        "jwt",
    }
    tree = ast.parse(HELPER_PATH.read_text(encoding="utf-8"))
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    intersection = imported & forbidden
    assert not intersection, (
        f"helper imports forbidden third-party modules: "
        f"{sorted(intersection)!r}"
    )


# --------------------------------------------------------------------- #
# Additional happy-paths                                                #
# --------------------------------------------------------------------- #


def test_t31_partial_family_within_budget_passes() -> None:
    doc = _doc()
    # downgrade parity family to 'partial' with 1 of 3 pins recorded
    doc["marker_families"][1]["finalisation_status"] = "partial"
    doc["marker_families"][1]["marker_count"] = 3
    # anchor_pins stays at 1 -> 0 < 1 < 3 -> valid partial
    # budget allows 1 unfinalised family -> should pass.
    vws.verify_sealing(doc)


def test_t32_chain_incomplete_within_budget_passes() -> None:
    doc = _doc()
    # Build a 3-link chain with one missing index (gap_count=1, budget=1).
    doc["ots_anchor_chain"]["links"] = [
        {
            "link_index": 0,
            "predecessor_pin": None,
            "successor_pin": "p1",
            "anchor_pin": "p0",
        },
        {
            "link_index": 1,
            "predecessor_pin": "p0",
            "successor_pin": "p3",
            "anchor_pin": "p1",
        },
        {
            "link_index": 3,
            "predecessor_pin": "p1",
            "successor_pin": None,
            "anchor_pin": "p3",
        },
    ]
    doc["ots_anchor_chain"]["head_anchor_pin"] = "p0"
    doc["ots_anchor_chain"]["tail_anchor_pin"] = "p3"
    doc["ots_anchor_chain"]["chain_complete"] = False
    # gap_count = 3+1-3 = 1, budget is 1 -> should pass.
    vws.verify_sealing(doc)
