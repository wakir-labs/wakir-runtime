# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-74 tests for the Welle-6 (Cross-Substrate-Parity)
Spec-Conformance Verifier.

============================================================================
Test inventory (>=15 hermetic tests, stdlib + pytest only):

  T01  Helper file exists at the expected path.
  T02  Helper file declares SPDX Apache-2.0 header and "-- Reza"
       signature line (REUSE-discipline).
  T03  A minimal valid parity document (all four substrates, one
       invariant claim, status=parity) passes verify_parity().
  T04  I-1: A document with tag != 'Tag-74' is rejected.
  T05  I-1: A document with welle != 'Welle-6' is rejected.
  T06  I-2: A document with audit_only flipped to false is rejected.
  T07  I-2: A document with doc_form_only flipped to false is rejected.
  T08  I-3: A document with parity_scope != 'Cross-Substrate-Parity'
       is rejected.
  T09  I-4: A document with malformed parity_id (wrong prefix or too
       short) is rejected.
  T10  I-5: A document missing one of the four canonical substrates
       is rejected; a document with five substrates is rejected;
       duplicate substrate-ids are rejected.
  T11  I-6: A substrate-record with lag_ticks=17 (over budget) is
       rejected; with lag_ticks=-1 is rejected; with unknown extra
       field is rejected.
  T12  I-7: An empty parity_claims list is rejected; a parity_claims
       list with no 'invariant' kind is rejected; duplicate claim_ids
       are rejected.
  T13  I-8: A claim-record with observed_in not subset of
       expected_substrates is rejected; expected_substrates empty
       is rejected; claim_kind unknown is rejected.
  T14  I-9: A claim with status='parity' but observed_in != expected
       is rejected; status='unobserved' with non-empty observed_in
       is rejected; status='divergent' with observed_in == expected
       (no actual divergence) is rejected.
  T15  I-10: A substrate.claim_coverage referencing an unknown
       claim_id is rejected; a claim declared 'parity' but not
       listed in every expected substrate's coverage is rejected.
  T16  I-11: divergence_budget missing field is rejected;
       max_divergent_claims out of [0,3] is rejected;
       tolerated_divergence_kinds with non-canonical entry is
       rejected.
  T17  I-12: divergent claim count exceeding budget is rejected.
  T18  I-13: substrate.lag_ticks exceeding budget is rejected.
  T19  I-14: a divergent claim of an intolerable kind is rejected.
  T20  I-15: sandbox_boundary with one of the five booleans flipped
       to false is rejected; probe_default_mode != 'inspection-only'
       is rejected.
  T21  I-16: cross_anchors missing 'tag_73_capability_layer' is
       rejected.
  T22  I-17: An unknown top-level field is rejected (strict shape).
  T23  I-18: audit_only as int 1 (truthy but not bool) is rejected.
  T24  I-19: only two of four substrates with non-empty
       claim_coverage is rejected.
  T25  CLI: subprocess invocation with a valid parity JSON exits 0
       and prints the expected OK banner.
  T26  CLI: subprocess invocation with no arguments exits non-zero
       with the usage banner on stderr.
  T27  CLI: subprocess invocation with a non-existent path exits
       non-zero with a 'not found' message on stderr.
  T28  CLI: subprocess invocation with a malformed JSON file exits
       non-zero with a JSON parse-error message on stderr.
  T29  Sandbox-boundary recital: helper does NOT import any module
       outside the stdlib whitelist (no requests, urllib3, httpx,
       NATS-py, etc.).
  T30  A divergent claim within budget passes verify_parity().
  T31  An unobserved claim (observed_in == []) passes if all other
       invariants hold.

-- Reza
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_REL = "tooling/audit/verify_cross_substrate_parity_spec.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


# --- import the helper as a module ----------------------------------- #
sys.path.insert(0, str(REPO_ROOT / "tooling" / "audit"))
import verify_cross_substrate_parity_spec as vcsp  # noqa: E402


# --------------------------------------------------------------------- #
# Canonical valid fixtures                                              #
# --------------------------------------------------------------------- #


def _base_doc() -> dict:
    """Return a minimal valid parity document with one invariant claim."""
    return {
        "tag": "Tag-74",
        "welle": "Welle-6",
        "audit_only": True,
        "doc_form_only": True,
        "parity_scope": "Cross-Substrate-Parity",
        "parity_id": "parity-welle6-test-0001",
        "substrates": [
            {
                "substrate_id": "engine",
                "version_pin": "engine-v0.41.0",
                "claim_coverage": ["claim-invariant-overlap-01"],
                "lag_ticks": 0,
            },
            {
                "substrate_id": "spec",
                "version_pin": "wirelang-spec-v0.41",
                "claim_coverage": ["claim-invariant-overlap-01"],
                "lag_ticks": 0,
            },
            {
                "substrate_id": "schema-registry",
                "version_pin": "schema-registry-v0.41",
                "claim_coverage": ["claim-invariant-overlap-01"],
                "lag_ticks": 1,
            },
            {
                "substrate_id": "audit-trail",
                "version_pin": "wat-layer-4",
                "claim_coverage": ["claim-invariant-overlap-01"],
                "lag_ticks": 2,
            },
        ],
        "parity_claims": [
            {
                "claim_id": "claim-invariant-overlap-01",
                "claim_kind": "invariant",
                "claim_text": (
                    "ADOL overlap-validity-window invariant holds across "
                    "engine / spec / schema-registry / audit-trail."
                ),
                "expected_substrates": [
                    "engine",
                    "spec",
                    "schema-registry",
                    "audit-trail",
                ],
                "observed_in": [
                    "engine",
                    "spec",
                    "schema-registry",
                    "audit-trail",
                ],
                "parity_status": "parity",
            }
        ],
        "divergence_budget": {
            "max_divergent_claims": 1,
            "max_substrate_lag_ticks": 4,
            "tolerated_divergence_kinds": ["shape", "ordering"],
        },
        "sandbox_boundary": {
            "no_engine_invocation": True,
            "no_schema_registry_write": True,
            "no_audit_trail_write": True,
            "no_spec_compiler_call": True,
            "no_promotion_pr_opening": True,
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
        },
    }


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


def test_t03_minimal_valid_parity_doc_passes() -> None:
    vcsp.verify_parity(_base_doc())


# --------------------------------------------------------------------- #
# I-1                                                                   #
# --------------------------------------------------------------------- #


def test_t04_wrong_tag_rejected() -> None:
    doc = _base_doc()
    doc["tag"] = "Tag-73"
    with pytest.raises(vcsp.VerifyError, match=r"^I-1:"):
        vcsp.verify_parity(doc)


def test_t05_wrong_welle_rejected() -> None:
    doc = _base_doc()
    doc["welle"] = "Welle-5"
    with pytest.raises(vcsp.VerifyError, match=r"^I-1:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-2                                                                   #
# --------------------------------------------------------------------- #


def test_t06_audit_only_false_rejected() -> None:
    doc = _base_doc()
    doc["audit_only"] = False
    with pytest.raises(vcsp.VerifyError, match=r"^I-2:"):
        vcsp.verify_parity(doc)


def test_t07_doc_form_only_false_rejected() -> None:
    doc = _base_doc()
    doc["doc_form_only"] = False
    with pytest.raises(vcsp.VerifyError, match=r"^I-2:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-3                                                                   #
# --------------------------------------------------------------------- #


def test_t08_wrong_parity_scope_rejected() -> None:
    doc = _base_doc()
    doc["parity_scope"] = "Some-Other-Parity"
    with pytest.raises(vcsp.VerifyError, match=r"^I-3:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-4                                                                   #
# --------------------------------------------------------------------- #


def test_t09_malformed_parity_id_rejected() -> None:
    doc = _base_doc()
    doc["parity_id"] = "PARITY-UPPERCASE-WRONG"
    with pytest.raises(vcsp.VerifyError, match=r"^I-4:"):
        vcsp.verify_parity(doc)
    doc["parity_id"] = "parity-x"  # too short
    with pytest.raises(vcsp.VerifyError, match=r"^I-4:"):
        vcsp.verify_parity(doc)
    doc["parity_id"] = "rot-wrong-prefix-0001"
    with pytest.raises(vcsp.VerifyError, match=r"^I-4:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-5                                                                   #
# --------------------------------------------------------------------- #


def test_t10_substrates_count_and_uniqueness() -> None:
    # missing one canonical substrate
    doc = _base_doc()
    doc["substrates"] = doc["substrates"][:3]
    with pytest.raises(vcsp.VerifyError, match=r"^I-5:"):
        vcsp.verify_parity(doc)
    # five substrates -> count failure
    doc = _base_doc()
    extra = dict(doc["substrates"][0])
    doc["substrates"].append(extra)
    with pytest.raises(vcsp.VerifyError, match=r"^I-5:"):
        vcsp.verify_parity(doc)
    # duplicate substrate_id (replace 'spec' with second 'engine')
    doc = _base_doc()
    doc["substrates"][1]["substrate_id"] = "engine"
    with pytest.raises(vcsp.VerifyError, match=r"^I-5:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-6                                                                   #
# --------------------------------------------------------------------- #


def test_t11_substrate_record_shape_rejects() -> None:
    # lag_ticks=17 over budget
    doc = _base_doc()
    doc["substrates"][0]["lag_ticks"] = 17
    with pytest.raises(vcsp.VerifyError, match=r"^I-6:"):
        vcsp.verify_parity(doc)
    # negative lag_ticks
    doc = _base_doc()
    doc["substrates"][0]["lag_ticks"] = -1
    with pytest.raises(vcsp.VerifyError, match=r"^I-6:"):
        vcsp.verify_parity(doc)
    # unknown extra field
    doc = _base_doc()
    doc["substrates"][0]["unknown_field"] = "x"
    with pytest.raises(vcsp.VerifyError, match=r"^I-6:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-7                                                                   #
# --------------------------------------------------------------------- #


def test_t12_parity_claims_shape_rejects() -> None:
    # empty parity_claims list
    doc = _base_doc()
    doc["parity_claims"] = []
    # also remove substrate coverage so I-10 doesn't fire first
    for s in doc["substrates"]:
        s["claim_coverage"] = []
    # I-19 (coverage breadth) will fire before I-7 because we removed
    # all coverage. Restore coverage breadth by leaving non-empty
    # coverage but in a non-existent claim -- which would trip I-10.
    # Cleanest path: only empty parity_claims (and the I-19 + I-7
    # both fail; verifier raises whichever comes first). Use a
    # different approach: keep coverage entries but with all-empty
    # claims is impossible. Instead test the more direct path: set
    # claims to [] AND make substrates have empty coverage -- the
    # verifier hits I-7 first (substrates check happens before
    # parity_claims check). To force I-7 alone, retain default
    # coverage but if claims are [], the consistency check (I-10)
    # will reject substrate coverage referencing missing ids.
    # So make substrates have empty coverage AND claims [].
    with pytest.raises(vcsp.VerifyError) as ei:
        vcsp.verify_parity(doc)
    assert ei.value.args[0].startswith(("I-7:", "I-19:")), (
        f"expected I-7 or I-19, got {ei.value.args[0]!r}"
    )

    # No invariant kind
    doc = _base_doc()
    doc["parity_claims"][0]["claim_kind"] = "shape"
    with pytest.raises(vcsp.VerifyError, match=r"^I-7:"):
        vcsp.verify_parity(doc)

    # Duplicate claim_ids
    doc = _base_doc()
    duplicate = dict(doc["parity_claims"][0])
    doc["parity_claims"].append(duplicate)
    with pytest.raises(vcsp.VerifyError, match=r"^I-7:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-8                                                                   #
# --------------------------------------------------------------------- #


def test_t13_claim_record_shape_rejects() -> None:
    # observed_in not subset of expected_substrates
    doc = _base_doc()
    doc["parity_claims"][0]["observed_in"] = [
        "engine",
        "spec",
        "schema-registry",
        "audit-trail",
        "spec",  # duplicate but still in set; need an outsider:
    ]
    # That doesn't break subset. Force a real subset violation:
    doc["parity_claims"][0]["expected_substrates"] = ["engine", "spec"]
    doc["parity_claims"][0]["observed_in"] = ["engine", "audit-trail"]
    # parity_status becomes inconsistent too -- I-8 subset failure
    # should fire before I-9 (claim shape is checked first).
    with pytest.raises(vcsp.VerifyError, match=r"^I-8:"):
        vcsp.verify_parity(doc)

    # expected_substrates empty
    doc = _base_doc()
    doc["parity_claims"][0]["expected_substrates"] = []
    with pytest.raises(vcsp.VerifyError, match=r"^I-8:"):
        vcsp.verify_parity(doc)

    # claim_kind unknown
    doc = _base_doc()
    doc["parity_claims"][0]["claim_kind"] = "no-such-kind"
    with pytest.raises(vcsp.VerifyError, match=r"^I-8:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-9                                                                   #
# --------------------------------------------------------------------- #


def test_t14_parity_status_consistency_rejects() -> None:
    # status=parity but observed_in != expected_substrates
    doc = _base_doc()
    doc["parity_claims"][0]["observed_in"] = ["engine", "spec"]
    # observed_in is now a strict subset of expected; status says
    # 'parity' which is inconsistent.
    with pytest.raises(vcsp.VerifyError, match=r"^I-9:"):
        vcsp.verify_parity(doc)

    # status=unobserved but observed_in non-empty
    doc = _base_doc()
    doc["parity_claims"][0]["parity_status"] = "unobserved"
    # observed_in still full -> I-9 fires
    with pytest.raises(vcsp.VerifyError, match=r"^I-9:"):
        vcsp.verify_parity(doc)

    # status=divergent but observed_in == expected (no actual divergence)
    doc = _base_doc()
    doc["parity_claims"][0]["parity_status"] = "divergent"
    with pytest.raises(vcsp.VerifyError, match=r"^I-9:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-10                                                                  #
# --------------------------------------------------------------------- #


def test_t15_coverage_consistency_rejects() -> None:
    # substrate.claim_coverage references unknown claim_id
    doc = _base_doc()
    doc["substrates"][0]["claim_coverage"] = ["claim-does-not-exist"]
    with pytest.raises(vcsp.VerifyError, match=r"^I-10:"):
        vcsp.verify_parity(doc)

    # claim declared 'parity' but not listed in every expected
    # substrate's coverage
    doc = _base_doc()
    # remove the claim from one substrate's coverage
    doc["substrates"][2]["claim_coverage"] = []
    # now I-19 may still pass (3 of 4 substrates still have non-empty
    # coverage), so I-10 should fire on the parity-coverage check.
    with pytest.raises(vcsp.VerifyError, match=r"^I-10:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-11                                                                  #
# --------------------------------------------------------------------- #


def test_t16_divergence_budget_shape_rejects() -> None:
    # missing field
    doc = _base_doc()
    del doc["divergence_budget"]["max_divergent_claims"]
    with pytest.raises(vcsp.VerifyError, match=r"^I-11:"):
        vcsp.verify_parity(doc)

    # max_divergent_claims out of [0,3]
    doc = _base_doc()
    doc["divergence_budget"]["max_divergent_claims"] = 4
    with pytest.raises(vcsp.VerifyError, match=r"^I-11:"):
        vcsp.verify_parity(doc)

    # tolerated_divergence_kinds with non-canonical entry
    doc = _base_doc()
    doc["divergence_budget"]["tolerated_divergence_kinds"] = ["nonsense"]
    with pytest.raises(vcsp.VerifyError, match=r"^I-11:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-12                                                                  #
# --------------------------------------------------------------------- #


def test_t17_divergent_count_over_budget_rejected() -> None:
    doc = _base_doc()
    # add two divergent claims; budget is 1.
    div1 = {
        "claim_id": "claim-divergent-shape-01",
        "claim_kind": "shape",
        "claim_text": "divergent shape claim 1",
        "expected_substrates": ["engine", "spec", "schema-registry"],
        "observed_in": ["engine"],
        "parity_status": "divergent",
    }
    div2 = {
        "claim_id": "claim-divergent-shape-02",
        "claim_kind": "shape",
        "claim_text": "divergent shape claim 2",
        "expected_substrates": ["engine", "spec", "schema-registry"],
        "observed_in": ["spec"],
        "parity_status": "divergent",
    }
    doc["parity_claims"].extend([div1, div2])
    with pytest.raises(vcsp.VerifyError, match=r"^I-12:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-13                                                                  #
# --------------------------------------------------------------------- #


def test_t18_substrate_lag_over_budget_rejected() -> None:
    doc = _base_doc()
    # budget is 4; set substrate lag to 5
    doc["substrates"][3]["lag_ticks"] = 5
    with pytest.raises(vcsp.VerifyError, match=r"^I-13:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-14                                                                  #
# --------------------------------------------------------------------- #


def test_t19_intolerable_divergent_kind_rejected() -> None:
    doc = _base_doc()
    # add a divergent claim of kind 'invariant' which is NOT in
    # tolerated_divergence_kinds (['shape', 'ordering']).
    div = {
        "claim_id": "claim-divergent-invariant-01",
        "claim_kind": "invariant",
        "claim_text": "divergent invariant claim (intolerable)",
        "expected_substrates": ["engine", "spec", "schema-registry"],
        "observed_in": ["engine"],
        "parity_status": "divergent",
    }
    doc["parity_claims"].append(div)
    with pytest.raises(vcsp.VerifyError, match=r"^I-14:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-15                                                                  #
# --------------------------------------------------------------------- #


def test_t20_sandbox_boundary_rejects() -> None:
    doc = _base_doc()
    doc["sandbox_boundary"]["no_engine_invocation"] = False
    with pytest.raises(vcsp.VerifyError, match=r"^I-15:"):
        vcsp.verify_parity(doc)

    doc = _base_doc()
    doc["sandbox_boundary"]["probe_default_mode"] = "active-call"
    with pytest.raises(vcsp.VerifyError, match=r"^I-15:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-16                                                                  #
# --------------------------------------------------------------------- #


def test_t21_missing_cross_anchor_rejected() -> None:
    doc = _base_doc()
    del doc["cross_anchors"]["tag_73_capability_layer"]
    with pytest.raises(vcsp.VerifyError, match=r"^I-16:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-17                                                                  #
# --------------------------------------------------------------------- #


def test_t22_unknown_top_level_field_rejected() -> None:
    doc = _base_doc()
    doc["surprise_extra_field"] = "boom"
    with pytest.raises(vcsp.VerifyError, match=r"^I-17:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-18                                                                  #
# --------------------------------------------------------------------- #


def test_t23_audit_only_non_bool_rejected() -> None:
    doc = _base_doc()
    doc["audit_only"] = 1  # truthy but not bool
    with pytest.raises(vcsp.VerifyError, match=r"^I-18:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# I-19                                                                  #
# --------------------------------------------------------------------- #


def test_t24_coverage_breadth_rejected() -> None:
    doc = _base_doc()
    # Add an additional invariant claim so we can drop coverage
    # without I-10 firing first.
    extra_claim = {
        "claim_id": "claim-invariant-shape-02",
        "claim_kind": "shape",
        "claim_text": "extra shape claim, unobserved",
        "expected_substrates": ["engine"],
        "observed_in": [],
        "parity_status": "unobserved",
    }
    doc["parity_claims"].append(extra_claim)
    # Drop coverage from two substrates so only 2/4 have non-empty
    # claim_coverage. But the first claim is still 'parity' and
    # requires coverage in all four expected substrates -> I-10 would
    # fire first. So downgrade the first claim to 'unobserved' first.
    doc["parity_claims"][0]["parity_status"] = "unobserved"
    doc["parity_claims"][0]["observed_in"] = []
    # And clear two substrates' coverage.
    doc["substrates"][2]["claim_coverage"] = []
    doc["substrates"][3]["claim_coverage"] = []
    with pytest.raises(vcsp.VerifyError, match=r"^I-19:"):
        vcsp.verify_parity(doc)


# --------------------------------------------------------------------- #
# CLI                                                                   #
# --------------------------------------------------------------------- #


def test_t25_cli_valid_doc_exits_zero(tmp_path: Path) -> None:
    doc = _base_doc()
    p = tmp_path / "parity.json"
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
    assert "verify_cross_substrate_parity_spec: OK" in result.stdout
    assert "Tag-74" in result.stdout
    assert "Welle-6" in result.stdout


def test_t26_cli_no_args_exits_nonzero() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_t27_cli_missing_file_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_t28_cli_malformed_json_exits_nonzero(tmp_path: Path) -> None:
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


def test_t29_helper_imports_stdlib_only() -> None:
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


def test_t30_divergent_within_budget_passes() -> None:
    doc = _base_doc()
    div = {
        "claim_id": "claim-divergent-shape-allowed",
        "claim_kind": "shape",
        "claim_text": "tolerated divergent shape claim within budget",
        "expected_substrates": ["engine", "spec", "schema-registry"],
        "observed_in": ["engine"],
        "parity_status": "divergent",
    }
    doc["parity_claims"].append(div)
    # Budget allows 1 divergent claim of kind 'shape' -- should pass.
    vcsp.verify_parity(doc)


def test_t31_unobserved_claim_passes() -> None:
    doc = _base_doc()
    extra = {
        "claim_id": "claim-unobserved-overlap-01",
        "claim_kind": "overlap",
        "claim_text": "unobserved overlap claim (audit-only, awaiting cycle)",
        "expected_substrates": ["engine", "spec"],
        "observed_in": [],
        "parity_status": "unobserved",
    }
    doc["parity_claims"].append(extra)
    vcsp.verify_parity(doc)
