# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-73 tests for the Welle-5 (Doppel-Welle-4+5) Capability-
Token-Layer State-Conformance Verifier.

============================================================================
Test inventory (>=15 hermetic tests, stdlib + pytest only):

  T01  Helper file exists at the expected path.
  T02  Helper file declares SPDX Apache-2.0 header and "-- Reza"
       signature line (REUSE-discipline).
  T03  A minimal valid pre-rotation state document passes
       verify_state() without raising.
  T04  A minimal valid rotation-in-progress state document passes.
  T05  A minimal valid post-rotation-grace state document passes.
  T06  A minimal valid post-rotation-sealed state document passes.
  T07  I-1: A state document with tag != 'Tag-73' is rejected.
  T08  I-1: A state document with welle != 'Welle-5' is rejected.
  T09  I-2: A state document with audit_only flipped to false is
       rejected (Tag-73 helper refuses non-audit-only documents).
  T10  I-3: A state document with layer != 'Layer-3-AIP+Biscuit' is
       rejected.
  T11  I-4: A state document with an unknown rotation_state is
       rejected.
  T12  I-5: A state document with an unsupported issuer_curve is
       rejected (e.g. 'P-256').
  T13  I-6: A state document with token_format != 'biscuit-v3' is
       rejected (e.g. 'biscuit-v2').
  T14  I-7: A state document with attenuation_depth_max == 0 is
       rejected, and attenuation_depth_max == 9 is rejected.
  T15  I-8: A state document where active_tokens is non-empty but
       a token-record is missing the 'rotation_role' field is
       rejected; an empty active_tokens in 'rotation-in-progress'
       state is rejected.
  T16  I-9: A post-rotation-grace document where the outgoing
       token's not_after < incoming's not_before is rejected
       (ADOL overlap violation).
  T17  I-10: A rotation_steps list with non-canonical step_kind
       order is rejected (e.g. 'seal' before 'announce-incoming').
  T18  I-11: A post-rotation-sealed state where some
       rotation_steps[*].status != 'done' is rejected; also a
       sealed state with an 'outgoing' active token is rejected.
  T19  I-12: An audit_trail_refs with no entries OR with a malformed
       wat-leaf URI is rejected.
  T20  I-13: A sandbox_boundary with one of the six boolean defaults
       flipped to false is rejected; probe_default_mode wrong is
       rejected.
  T21  I-14: A state document missing one of the required cross-
       anchors (e.g. adr_0017) is rejected.
  T22  I-15: A token-record with not_before > not_after is rejected.
  T23  I-16: A token-record carrying an unknown top-level field
       (e.g. 'extra_unrecognised') is rejected (strict shape).
  T24  I-17: A state document with malformed rotation_id (e.g.
       'rot-' too short, or wrong prefix) is rejected.
  T25  I-18: A pre-rotation state where one rotation_steps[*].status
       is 'done' (not 'planned') is rejected.
  T26  I-19: A rotation-in-progress state where the incoming
       token's not_after equals (not strictly greater than) the
       outgoing token's not_after is rejected (forward-progress
       invariant).
  T27  CLI: subprocess invocation with a valid state JSON exits 0
       and prints the expected OK banner.
  T28  CLI: subprocess invocation with a malformed JSON file exits
       non-zero with a JSON parse-error message on stderr.
  T29  CLI: subprocess invocation with no arguments exits non-zero
       with the usage banner on stderr.
  T30  CLI: subprocess invocation with a non-existent path exits
       non-zero with a 'not found' message on stderr.
  T31  Sandbox-boundary recital: helper does NOT import any module
       outside the stdlib whitelist (no requests, urllib3, httpx,
       biscuit-python, etc.).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_REL = "tooling/audit/verify_capability_token_layer_state.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


# --- import the helper as a module ----------------------------------- #
sys.path.insert(0, str(REPO_ROOT / "tooling" / "audit"))
import verify_capability_token_layer_state as vctls  # noqa: E402


# --------------------------------------------------------------------- #
# Canonical valid fixtures                                              #
# --------------------------------------------------------------------- #


def _base_state() -> dict:
    """Minimal valid state document scaffold (state-agnostic)."""
    return {
        "tag": "Tag-73",
        "welle": "Welle-5",
        "audit_only": True,
        "doc_form_only": True,
        "layer": "Layer-3-AIP+Biscuit",
        "rotation_id": "rot-welle5-test-0001",
        "rotation_state": "pre-rotation",
        "issuer_curve": "Ed25519",
        "token_format": "biscuit-v3",
        "attenuation_depth_max": 4,
        "active_tokens": [],
        "rotation_steps": [],
        "audit_trail_refs": [
            "wat-leaf://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ],
        "sandbox_boundary": {
            "no_token_mint": True,
            "no_token_revoke": True,
            "no_aip_issuer_call": True,
            "no_nats_kv_bucket_write": True,
            "no_promotion_pr_opening": True,
            "probe_default_mode": "inspection-only",
        },
        "cross_anchors": {
            "adr_0007": "ADR-0007 OTS-Substrat",
            "adr_0017": "ADR-0017 Embodied Capability Tokens",
            "adr_0023a": "ADR-0023a Capability-Token-Layer Charter",
            "adr_0023b": "ADR-0023b Wirelang Layer-3 Anchor",
            "adr_0025": "ADR-0025 Drei-Achsen-Modell",
            "wat_layer_4_anchor": "wat-layer-4-merkle-root",
            "wirelang_layer_3_schema": "wirelang/schemas/layer-3-capability-token.json",
        },
    }


def _rotation_in_progress_state() -> dict:
    s = _base_state()
    s["rotation_state"] = "rotation-in-progress"
    s["active_tokens"] = [
        {
            "token_id": "tok-outgoing-001",
            "issuer_pubkey": "ed25519:AAAA",
            "not_before": 100,
            "not_after": 200,
            "attenuation_depth": 2,
            "rotation_role": "outgoing",
        },
        {
            "token_id": "tok-incoming-001",
            "issuer_pubkey": "ed25519:BBBB",
            "not_before": 150,
            "not_after": 300,
            "attenuation_depth": 2,
            "rotation_role": "incoming",
        },
    ]
    s["rotation_steps"] = [
        {
            "step_id": "step-1",
            "step_kind": "announce-incoming",
            "status": "done",
        },
        {
            "step_id": "step-2",
            "step_kind": "dual-validity-window-open",
            "status": "done",
        },
        {
            "step_id": "step-3",
            "step_kind": "outgoing-drain",
            "status": "planned",
        },
    ]
    return s


def _post_rotation_grace_state() -> dict:
    s = _rotation_in_progress_state()
    s["rotation_state"] = "post-rotation-grace"
    # ensure overlap: outgoing.not_after >= incoming.not_before
    s["active_tokens"][0]["not_after"] = 250
    s["active_tokens"][1]["not_before"] = 200
    s["active_tokens"][1]["not_after"] = 400
    s["rotation_steps"] = [
        {
            "step_id": "step-1",
            "step_kind": "announce-incoming",
            "status": "done",
        },
        {
            "step_id": "step-2",
            "step_kind": "dual-validity-window-open",
            "status": "done",
        },
        {
            "step_id": "step-3",
            "step_kind": "outgoing-drain",
            "status": "done",
        },
        {
            "step_id": "step-4",
            "step_kind": "dual-validity-window-close",
            "status": "planned",
        },
    ]
    return s


def _post_rotation_sealed_state() -> dict:
    s = _base_state()
    s["rotation_state"] = "post-rotation-sealed"
    s["active_tokens"] = [
        {
            "token_id": "tok-stable-001",
            "issuer_pubkey": "ed25519:CCCC",
            "not_before": 100,
            "not_after": 999,
            "attenuation_depth": 1,
            "rotation_role": "stable",
        },
    ]
    s["rotation_steps"] = [
        {
            "step_id": f"step-{i+1}",
            "step_kind": kind,
            "status": "done",
        }
        for i, kind in enumerate(vctls.CANONICAL_STEP_KINDS_ORDER)
    ]
    return s


# --------------------------------------------------------------------- #
# Axis A -- helper-file shape + signature                              #
# --------------------------------------------------------------------- #


def test_t01_helper_exists():
    assert HELPER_PATH.exists(), f"helper missing at {HELPER_REL}"


def test_t02_helper_spdx_and_signature():
    text = HELPER_PATH.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0" in text, (
        "helper must carry SPDX-License-Identifier: Apache-2.0 header"
    )
    assert "-- Reza" in text, (
        "helper must carry the '-- Reza' signature line"
    )


# --------------------------------------------------------------------- #
# Axis B -- canonical-state happy paths                                 #
# --------------------------------------------------------------------- #


def test_t03_pre_rotation_valid_passes():
    vctls.verify_state(_base_state())


def test_t04_rotation_in_progress_valid_passes():
    vctls.verify_state(_rotation_in_progress_state())


def test_t05_post_rotation_grace_valid_passes():
    vctls.verify_state(_post_rotation_grace_state())


def test_t06_post_rotation_sealed_valid_passes():
    vctls.verify_state(_post_rotation_sealed_state())


# --------------------------------------------------------------------- #
# Axis C -- invariant rejection (I-1 .. I-19)                           #
# --------------------------------------------------------------------- #


def test_t07_wrong_tag_rejected():
    s = _base_state()
    s["tag"] = "Tag-72"
    with pytest.raises(vctls.VerifyError, match="I-1"):
        vctls.verify_state(s)


def test_t08_wrong_welle_rejected():
    s = _base_state()
    s["welle"] = "Welle-4"
    with pytest.raises(vctls.VerifyError, match="I-1"):
        vctls.verify_state(s)


def test_t09_audit_only_false_rejected():
    s = _base_state()
    s["audit_only"] = False
    with pytest.raises(vctls.VerifyError, match="I-2"):
        vctls.verify_state(s)


def test_t10_wrong_layer_rejected():
    s = _base_state()
    s["layer"] = "Layer-2-Wirelang"
    with pytest.raises(vctls.VerifyError, match="I-3"):
        vctls.verify_state(s)


def test_t11_unknown_rotation_state_rejected():
    s = _base_state()
    s["rotation_state"] = "mid-rotation-purple"
    with pytest.raises(vctls.VerifyError, match="I-4"):
        vctls.verify_state(s)


def test_t12_unsupported_curve_rejected():
    s = _base_state()
    s["issuer_curve"] = "P-256"
    with pytest.raises(vctls.VerifyError, match="I-5"):
        vctls.verify_state(s)


def test_t13_wrong_token_format_rejected():
    s = _base_state()
    s["token_format"] = "biscuit-v2"
    with pytest.raises(vctls.VerifyError, match="I-6"):
        vctls.verify_state(s)


def test_t14_attenuation_depth_out_of_range_rejected():
    s = _base_state()
    s["attenuation_depth_max"] = 0
    with pytest.raises(vctls.VerifyError, match="I-7"):
        vctls.verify_state(s)
    s["attenuation_depth_max"] = 9
    with pytest.raises(vctls.VerifyError, match="I-7"):
        vctls.verify_state(s)


def test_t15_active_tokens_invalid_shape_rejected():
    # Missing rotation_role on a token record.
    s = _rotation_in_progress_state()
    del s["active_tokens"][0]["rotation_role"]
    with pytest.raises(vctls.VerifyError, match="I-8"):
        vctls.verify_state(s)
    # Empty active_tokens in rotation-in-progress.
    s2 = _rotation_in_progress_state()
    s2["active_tokens"] = []
    with pytest.raises(vctls.VerifyError, match="I-8"):
        vctls.verify_state(s2)


def test_t16_post_rotation_grace_overlap_violation_rejected():
    s = _post_rotation_grace_state()
    # Break overlap: outgoing.not_after < incoming.not_before
    s["active_tokens"][0]["not_after"] = 100
    s["active_tokens"][1]["not_before"] = 500
    s["active_tokens"][1]["not_after"] = 999
    with pytest.raises(vctls.VerifyError, match="I-9"):
        vctls.verify_state(s)


def test_t17_rotation_steps_wrong_order_rejected():
    s = _rotation_in_progress_state()
    s["rotation_steps"] = [
        {"step_id": "x", "step_kind": "seal", "status": "planned"},
        {
            "step_id": "y",
            "step_kind": "announce-incoming",
            "status": "planned",
        },
    ]
    with pytest.raises(vctls.VerifyError, match="I-10"):
        vctls.verify_state(s)


def test_t18_sealed_with_outgoing_or_undone_step_rejected():
    # Sealed state with an active outgoing token.
    s = _post_rotation_sealed_state()
    s["active_tokens"].append(
        {
            "token_id": "tok-leftover",
            "issuer_pubkey": "ed25519:DDDD",
            "not_before": 100,
            "not_after": 200,
            "attenuation_depth": 1,
            "rotation_role": "outgoing",
        }
    )
    with pytest.raises(vctls.VerifyError, match="I-11"):
        vctls.verify_state(s)

    # Sealed state where one step is not done.
    s2 = _post_rotation_sealed_state()
    s2["rotation_steps"][-1]["status"] = "planned"
    with pytest.raises(vctls.VerifyError, match="I-11"):
        vctls.verify_state(s2)


def test_t19_audit_trail_refs_malformed_rejected():
    s = _base_state()
    s["audit_trail_refs"] = []
    with pytest.raises(vctls.VerifyError, match="I-12"):
        vctls.verify_state(s)
    s["audit_trail_refs"] = ["http://example.org/leaf"]
    with pytest.raises(vctls.VerifyError, match="I-12"):
        vctls.verify_state(s)
    s["audit_trail_refs"] = ["wat-leaf://NOTHEX"]
    with pytest.raises(vctls.VerifyError, match="I-12"):
        vctls.verify_state(s)


def test_t20_sandbox_boundary_violation_rejected():
    # Flip one boolean to false.
    s = _base_state()
    s["sandbox_boundary"]["no_token_mint"] = False
    with pytest.raises(vctls.VerifyError, match="I-13"):
        vctls.verify_state(s)

    # Wrong probe_default_mode.
    s2 = _base_state()
    s2["sandbox_boundary"]["probe_default_mode"] = "live-write"
    with pytest.raises(vctls.VerifyError, match="I-13"):
        vctls.verify_state(s2)


def test_t21_missing_cross_anchor_rejected():
    s = _base_state()
    del s["cross_anchors"]["adr_0017"]
    with pytest.raises(vctls.VerifyError, match="I-14"):
        vctls.verify_state(s)


def test_t22_token_record_nb_gt_na_rejected():
    s = _rotation_in_progress_state()
    s["active_tokens"][0]["not_before"] = 999
    s["active_tokens"][0]["not_after"] = 100
    with pytest.raises(vctls.VerifyError, match="I-15"):
        vctls.verify_state(s)


def test_t23_token_record_unknown_field_rejected():
    s = _rotation_in_progress_state()
    s["active_tokens"][0]["extra_unrecognised"] = "no"
    with pytest.raises(vctls.VerifyError, match="I-16"):
        vctls.verify_state(s)


def test_t24_malformed_rotation_id_rejected():
    s = _base_state()
    s["rotation_id"] = "rot-x"  # too short
    with pytest.raises(vctls.VerifyError, match="I-17"):
        vctls.verify_state(s)
    s["rotation_id"] = "wrong-prefix-1234"
    with pytest.raises(vctls.VerifyError, match="I-17"):
        vctls.verify_state(s)


def test_t25_pre_rotation_with_done_step_rejected():
    s = _base_state()  # pre-rotation
    s["rotation_steps"] = [
        {
            "step_id": "step-1",
            "step_kind": "announce-incoming",
            "status": "done",
        }
    ]
    with pytest.raises(vctls.VerifyError, match="I-18"):
        vctls.verify_state(s)


def test_t26_forward_progress_invariant_rejected():
    s = _rotation_in_progress_state()
    # Make incoming.not_after equal outgoing.not_after (must be strictly >).
    s["active_tokens"][0]["not_after"] = 300
    s["active_tokens"][1]["not_after"] = 300
    with pytest.raises(vctls.VerifyError, match="I-19"):
        vctls.verify_state(s)


# --------------------------------------------------------------------- #
# Axis D -- CLI smoke                                                   #
# --------------------------------------------------------------------- #


def _write_state(tmp_path: Path, state: dict) -> Path:
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def test_t27_cli_valid_state_exits_zero(tmp_path):
    state_path = _write_state(tmp_path, _post_rotation_sealed_state())
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(state_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; stderr={result.stderr!r}"
    )
    assert "verify_capability_token_layer_state: OK" in result.stdout, (
        f"missing OK banner; stdout={result.stdout!r}"
    )
    assert "Tag-73" in result.stdout and "Welle-5" in result.stdout


def test_t28_cli_malformed_json_exits_nonzero(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(p)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr


def test_t29_cli_no_args_exits_nonzero():
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


def test_t30_cli_missing_file_exits_nonzero(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH), str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_t31_helper_uses_stdlib_only():
    """Sandbox-boundary recital: helper imports only stdlib modules.

    Parse the helper source and assert no forbidden third-party imports.
    """
    text = HELPER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden = {
        "requests",
        "urllib3",
        "httpx",
        "biscuit",
        "biscuit_python",
        "biscuit_auth",
        "nats",
        "asyncio_nats",
    }
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    bad = imported & forbidden
    assert not bad, (
        f"helper must not import forbidden modules: {sorted(bad)!r}"
    )
