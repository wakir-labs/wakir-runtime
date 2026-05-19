# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-66 AR-Hand Override Audit-Trail Verifier.

Tests cover ``tooling/ci/verify_ar_hand_override_audit_trail.py``:

* Schema validation of listener output envelopes.
* Decision-rule consistency (applied vs. verdicts vs. marker).
* Stale-marker guard advisory.
* Marker sub-schema mirror checks.
* CLI plumbing + aggregate verdict.

Sandbox boundary: stdlib + pytest only. No network, no podman.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from tooling.ci import verify_ar_hand_override_audit_trail as verifier  # noqa: E402
from tooling.ci import ar_hand_cutover_override_listener as listener  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_marker() -> dict:
    return {
        "schema_version": 1,
        "kind": "ar-hand-cutover-override-flag",
        "operator": "ar-hand-mira",
        "ts": "2026-06-15T06:05:00Z",
        "iso_week": 25,
        "reason": (
            "engine_composite DEFECT triaged out-of-band; "
            "see ar-risk-tag-66-01 dossier."
        ),
        "accepted_risk_id": "ar-risk-tag-66-01",
        "override_target_verdict": "CUTOVER-DAY-MORGEN-BLOCK",
        "post_override_verdict": "CUTOVER-DAY-MORGEN-CAUTION",
    }


@pytest.fixture()
def block_envelope() -> dict:
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": "2026-06-15T06:00:00+00:00",
        "verdict": "CUTOVER-DAY-MORGEN-BLOCK",
        "step_results": {
            "engine_composite": "red",
            "pyramide_composite": "green",
            "e2e_smoke": "green",
        },
        "failed_steps": ["engine_composite"],
        "per_substrate_notes": {
            "engine_composite": "engine_composite: verdict='PRE-CUTOVER-DEFECT'",
        },
        "counts": {"green": 2, "yellow": 0, "red": 1},
    }


@pytest.fixture()
def ready_envelope() -> dict:
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": "2026-06-15T06:00:00+00:00",
        "verdict": "CUTOVER-DAY-MORGEN-READY",
        "step_results": {
            "engine_composite": "green",
            "pyramide_composite": "green",
            "e2e_smoke": "green",
        },
        "failed_steps": [],
        "per_substrate_notes": {},
        "counts": {"green": 3, "yellow": 0, "red": 0},
    }


@pytest.fixture()
def caution_envelope() -> dict:
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": "2026-06-15T06:00:00+00:00",
        "verdict": "CUTOVER-DAY-MORGEN-CAUTION",
        "step_results": {
            "engine_composite": "yellow",
            "pyramide_composite": "green",
            "e2e_smoke": "green",
        },
        "failed_steps": ["engine_composite"],
        "per_substrate_notes": {
            "engine_composite": "engine_composite: verdict='PRE-CUTOVER-DRIFT'",
        },
        "counts": {"green": 2, "yellow": 1, "red": 0},
    }


def _listener_envelope(
    input_envelope: dict, marker: dict | None
) -> dict:
    """Build a real Tag-65 listener envelope (the verifier's target)."""
    return listener.build_output_envelope(input_envelope, marker)


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. Happy-path: a real applied-override envelope passes cleanly.
# ---------------------------------------------------------------------------


def test_01_verify_applied_override_envelope_passes(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    result = verifier.verify_envelope(env, "test:applied")
    assert result.verdict() == "PASS", result.violations
    assert result.applied is True
    assert result.input_verdict == "CUTOVER-DAY-MORGEN-BLOCK"
    assert "AR-Hand override applied" in (result.audit_trail_note or "")


# ---------------------------------------------------------------------------
# 2. Happy-path: a no-marker pass-through envelope passes cleanly.
# ---------------------------------------------------------------------------


def test_02_verify_no_marker_passthrough_passes(
    ready_envelope: dict,
) -> None:
    env = _listener_envelope(ready_envelope, None)
    result = verifier.verify_envelope(env, "test:no-marker")
    assert result.verdict() == "PASS", result.violations
    assert result.applied is False
    assert result.input_verdict == "CUTOVER-DAY-MORGEN-READY"
    assert "no override marker" in (result.audit_trail_note or "")


# ---------------------------------------------------------------------------
# 3. Stale-marker guard: present marker against CAUTION input emits ADVISORY.
# ---------------------------------------------------------------------------


def test_03_stale_marker_against_caution_is_advisory(
    caution_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(caution_envelope, valid_marker)
    result = verifier.verify_envelope(env, "test:stale-marker")
    assert result.verdict() == "ADVISORY", (
        result.violations,
        result.advisories,
    )
    assert result.applied is False
    assert any(
        "stale-marker downgrade guard fired" in adv
        for adv in result.advisories
    )


# ---------------------------------------------------------------------------
# 4. Missing top-level key fails fast.
# ---------------------------------------------------------------------------


def test_04_missing_required_key_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    del env["audit_trail_note"]
    result = verifier.verify_envelope(env, "test:missing-key")
    assert result.verdict() == "FAIL"
    assert any(
        "missing required keys" in v for v in result.violations
    )


# ---------------------------------------------------------------------------
# 5. Schema-version mismatch fails.
# ---------------------------------------------------------------------------


def test_05_wrong_schema_version_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["schema_version"] = 99
    result = verifier.verify_envelope(env, "test:wrong-sv")
    assert result.verdict() == "FAIL"
    assert any("schema_version" in v for v in result.violations)


# ---------------------------------------------------------------------------
# 6. applied=true with non-BLOCK input fails (contradiction).
# ---------------------------------------------------------------------------


def test_06_applied_true_with_non_block_input_fails(
    ready_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(ready_envelope, valid_marker)
    # Forcibly flip applied to true; the envelope is now inconsistent.
    env["applied"] = True
    env["verdict"] = "CUTOVER-DAY-MORGEN-CAUTION"
    result = verifier.verify_envelope(env, "test:applied-non-block")
    assert result.verdict() == "FAIL"
    assert any(
        "input_verdict is" in v and "must be 'CUTOVER-DAY-MORGEN-BLOCK'" in v
        for v in result.violations
    )


# ---------------------------------------------------------------------------
# 7. applied=true with verdict != CAUTION fails.
# ---------------------------------------------------------------------------


def test_07_applied_true_wrong_post_verdict_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["verdict"] = "CUTOVER-DAY-MORGEN-READY"
    result = verifier.verify_envelope(env, "test:wrong-post")
    assert result.verdict() == "FAIL"
    assert any(
        "post-override verdict" in v for v in result.violations
    )


# ---------------------------------------------------------------------------
# 8. applied=true with null marker fails.
# ---------------------------------------------------------------------------


def test_08_applied_true_null_marker_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["override_marker"] = None
    result = verifier.verify_envelope(env, "test:null-marker")
    assert result.verdict() == "FAIL"
    assert any(
        "override_marker is null" in v for v in result.violations
    )


# ---------------------------------------------------------------------------
# 9. Operator + risk-id MUST appear in audit_trail_note.
# ---------------------------------------------------------------------------


def test_09_audit_note_must_reference_operator_and_risk_id(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["audit_trail_note"] = "AR-Hand override applied: BLOCK -> CAUTION"
    # The marker contains operator "ar-hand-mira" and
    # risk-id "ar-risk-tag-66-01", neither of which appear here.
    result = verifier.verify_envelope(env, "test:note-missing-fields")
    assert result.verdict() == "FAIL"
    refs = " ".join(result.violations)
    assert "operator" in refs and "accepted_risk_id" in refs


# ---------------------------------------------------------------------------
# 10. Marker schema violation (bad operator slug) is reported.
# ---------------------------------------------------------------------------


def test_10_marker_bad_operator_slug_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    # Bypass the listener's validation by direct-injection.
    env["override_marker"]["operator"] = "Mira Kessler"
    result = verifier.verify_envelope(env, "test:bad-operator")
    assert result.verdict() == "FAIL"
    assert any("operator is not a slug" in v for v in result.violations)


# ---------------------------------------------------------------------------
# 11. Marker schema violation (bad ts format) is reported.
# ---------------------------------------------------------------------------


def test_11_marker_bad_ts_format_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["override_marker"]["ts"] = "2026-06-15 06:05:00"
    result = verifier.verify_envelope(env, "test:bad-ts")
    assert result.verdict() == "FAIL"
    assert any("ts is not RFC3339" in v for v in result.violations)


# ---------------------------------------------------------------------------
# 12. Input-envelope preservation: tampering is detected.
# ---------------------------------------------------------------------------


def test_12_input_envelope_mutation_is_detected(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    # Mutate the embedded input envelope.
    env["input_verdict_envelope"]["verdict"] = "CUTOVER-DAY-MORGEN-READY"
    result = verifier.verify_envelope(env, "test:input-mutation")
    assert result.verdict() == "FAIL"
    assert any(
        "input envelope has been mutated" in v for v in result.violations
    )


# ---------------------------------------------------------------------------
# 13. decision_rule integrity is checked.
# ---------------------------------------------------------------------------


def test_13_decision_rule_block_must_be_intact(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    env["decision_rule"]["applies_to_input"] = "CUTOVER-DAY-MORGEN-READY"
    result = verifier.verify_envelope(env, "test:bad-rule")
    assert result.verdict() == "FAIL"
    assert any(
        "applies_to_input" in v for v in result.violations
    )


# ---------------------------------------------------------------------------
# 14. applied=false + marker + BLOCK input is a hard contradiction.
# ---------------------------------------------------------------------------


def test_14_applied_false_with_marker_and_block_input_fails(
    block_envelope: dict, valid_marker: dict
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    # Force applied=false while keeping marker + BLOCK input.
    env["applied"] = False
    env["verdict"] = "CUTOVER-DAY-MORGEN-BLOCK"
    env["audit_trail_note"] = "marker recorded, verdict unchanged"
    result = verifier.verify_envelope(env, "test:contradiction")
    assert result.verdict() == "FAIL"
    assert any(
        "contradicts the Tag-65 decision rule" in v
        for v in result.violations
    )


# ---------------------------------------------------------------------------
# 15. Aggregate roll-up: mixed inputs produce FAIL verdict.
# ---------------------------------------------------------------------------


def test_15_aggregate_mixed_inputs(
    block_envelope: dict,
    ready_envelope: dict,
    caution_envelope: dict,
    valid_marker: dict,
) -> None:
    good = verifier.verify_envelope(
        _listener_envelope(block_envelope, valid_marker), "good"
    )
    advisory = verifier.verify_envelope(
        _listener_envelope(caution_envelope, valid_marker), "advisory"
    )
    bad_env = _listener_envelope(ready_envelope, None)
    del bad_env["audit_trail_note"]
    bad = verifier.verify_envelope(bad_env, "bad")

    roll = verifier.aggregate([good, advisory, bad])
    assert roll["verdict"] == "FAIL"
    assert roll["pass_count"] == 1
    assert roll["advisory_count"] == 1
    assert roll["fail_count"] == 1
    assert roll["input_count"] == 3


# ---------------------------------------------------------------------------
# 16. CLI: write a small fixture set and run main(); exit code 0.
# ---------------------------------------------------------------------------


def test_16_cli_pass_path(
    tmp_path: Path,
    block_envelope: dict,
    valid_marker: dict,
) -> None:
    env = _listener_envelope(block_envelope, valid_marker)
    inp_dir = tmp_path / "envelopes"
    inp_dir.mkdir()
    _write_json(inp_dir / "applied.json", env)
    out = tmp_path / "rollup.json"

    rc = verifier.main(
        [str(inp_dir), "--output", str(out)]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["input_count"] == 1
    assert payload["pass_count"] == 1


# ---------------------------------------------------------------------------
# 17. CLI: a malformed envelope drives exit code 1 + FAIL.
# ---------------------------------------------------------------------------


def test_17_cli_fail_path(
    tmp_path: Path,
    ready_envelope: dict,
) -> None:
    env = _listener_envelope(ready_envelope, None)
    del env["audit_trail_note"]
    inp = tmp_path / "broken.json"
    _write_json(inp, env)
    out = tmp_path / "rollup.json"

    rc = verifier.main([str(inp), "--output", str(out)])
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "FAIL"
    assert payload["fail_count"] == 1


# ---------------------------------------------------------------------------
# 18. CLI: --allow-empty produces ADVISORY rollup, exit 0.
# ---------------------------------------------------------------------------


def test_18_cli_allow_empty_advisory(
    tmp_path: Path,
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    out = tmp_path / "rollup.json"

    rc = verifier.main(
        [str(empty_dir), "--output", str(out), "--allow-empty"]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "ADVISORY"
    assert payload["input_count"] == 0


# ---------------------------------------------------------------------------
# 19. CLI: zero inputs without --allow-empty exits 2.
# ---------------------------------------------------------------------------


def test_19_cli_zero_inputs_strict_exits_2(
    tmp_path: Path,
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    out = tmp_path / "rollup.json"

    rc = verifier.main([str(empty_dir), "--output", str(out)])
    assert rc == 2
    assert not out.exists()


# ---------------------------------------------------------------------------
# 20. Non-JSON file is reported as a FAIL on that path, not a crash.
# ---------------------------------------------------------------------------


def test_20_cli_non_json_file_fails_gracefully(
    tmp_path: Path,
) -> None:
    junk = tmp_path / "not-json.json"
    junk.write_text("this is not JSON {", encoding="utf-8")
    out = tmp_path / "rollup.json"

    rc = verifier.main([str(junk), "--output", str(out)])
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "FAIL"
    per = payload["per_envelope"][0]
    assert per["verdict"] == "FAIL"
    assert any("not valid JSON" in v for v in per["violations"])
