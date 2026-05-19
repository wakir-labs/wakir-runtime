# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-65 AR-Hand Cutover-Day-Morgen Override Listener.

Tests verify the listener (``tooling/ci/ar_hand_cutover_override_listener.py``)
and the aggregator extension (``tooling/ci/aggregate_cutover_day_morgen_verdict.py``
override-awareness).

Sandbox boundary: stdlib + pytest only. No network, no podman, no gh CLI.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module import scaffolding.
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from tooling.ci import ar_hand_cutover_override_listener as listener  # noqa: E402
from tooling.ci import aggregate_cutover_day_morgen_verdict as agg  # noqa: E402


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
        "reason": "engine_composite DEFECT triaged out-of-band; "
                  "see ar-risk-tag-65-01 dossier.",
        "accepted_risk_id": "ar-risk-tag-65-01",
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


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. Marker validation.
# ---------------------------------------------------------------------------


def test_01_validate_marker_happy_path(valid_marker: dict) -> None:
    """A schema-correct marker validates cleanly."""
    normalised = listener.validate_marker(valid_marker)
    assert normalised["operator"] == "ar-hand-mira"
    assert normalised["accepted_risk_id"] == "ar-risk-tag-65-01"
    assert normalised["override_target_verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"
    assert normalised["post_override_verdict"] == "CUTOVER-DAY-MORGEN-CAUTION"
    assert normalised["iso_week"] == 25


def test_02_validate_marker_missing_fields(valid_marker: dict) -> None:
    """Missing required field is rejected with a clear message."""
    del valid_marker["operator"]
    with pytest.raises(listener.OverrideMarkerError) as exc:
        listener.validate_marker(valid_marker)
    assert "operator" in str(exc.value)


def test_03_validate_marker_wrong_schema_version(valid_marker: dict) -> None:
    valid_marker["schema_version"] = 99
    with pytest.raises(listener.OverrideMarkerError, match="schema_version"):
        listener.validate_marker(valid_marker)


def test_04_validate_marker_wrong_kind(valid_marker: dict) -> None:
    valid_marker["kind"] = "ar-hand-stop-marker"
    with pytest.raises(listener.OverrideMarkerError, match="kind"):
        listener.validate_marker(valid_marker)


def test_05_validate_marker_bad_operator_slug(valid_marker: dict) -> None:
    valid_marker["operator"] = "Mira Kessler"  # space + uppercase
    with pytest.raises(listener.OverrideMarkerError, match="operator"):
        listener.validate_marker(valid_marker)


def test_06_validate_marker_bad_ts_format(valid_marker: dict) -> None:
    valid_marker["ts"] = "2026-06-15 06:05:00"  # no T, no zone
    with pytest.raises(listener.OverrideMarkerError, match="ts"):
        listener.validate_marker(valid_marker)


def test_07_validate_marker_reason_too_short(valid_marker: dict) -> None:
    valid_marker["reason"] = "too short"
    with pytest.raises(listener.OverrideMarkerError, match="reason"):
        listener.validate_marker(valid_marker)


def test_08_validate_marker_reason_whitespace_stripped(valid_marker: dict) -> None:
    """Reason length is measured after strip()."""
    valid_marker["reason"] = "   " + "ok " * 10 + "   "
    normalised = listener.validate_marker(valid_marker)
    assert not normalised["reason"].startswith(" ")
    assert not normalised["reason"].endswith(" ")


def test_09_validate_marker_wrong_override_target(valid_marker: dict) -> None:
    valid_marker["override_target_verdict"] = "CUTOVER-DAY-MORGEN-READY"
    with pytest.raises(listener.OverrideMarkerError, match="override_target_verdict"):
        listener.validate_marker(valid_marker)


def test_10_validate_marker_wrong_post_override(valid_marker: dict) -> None:
    valid_marker["post_override_verdict"] = "CUTOVER-DAY-MORGEN-READY"
    with pytest.raises(listener.OverrideMarkerError, match="post_override_verdict"):
        listener.validate_marker(valid_marker)


def test_11_validate_marker_iso_week_out_of_range(valid_marker: dict) -> None:
    valid_marker["iso_week"] = 0
    with pytest.raises(listener.OverrideMarkerError, match="iso_week"):
        listener.validate_marker(valid_marker)


def test_12_validate_marker_iso_week_optional(valid_marker: dict) -> None:
    del valid_marker["iso_week"]
    normalised = listener.validate_marker(valid_marker)
    assert "iso_week" not in normalised


# ---------------------------------------------------------------------------
# 2. Marker loading.
# ---------------------------------------------------------------------------


def test_13_load_marker_returns_none_for_missing_path(tmp_path: Path) -> None:
    marker = listener.load_marker(tmp_path / "absent.json")
    assert marker is None


def test_14_load_marker_returns_none_for_none_path() -> None:
    assert listener.load_marker(None) is None


def test_15_load_marker_rejects_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json {", encoding="utf-8")
    with pytest.raises(listener.OverrideMarkerError, match="not valid JSON"):
        listener.load_marker(bad)


def test_16_load_marker_happy_path(tmp_path: Path, valid_marker: dict) -> None:
    p = _write_json(tmp_path / "marker.json", valid_marker)
    loaded = listener.load_marker(p)
    assert loaded is not None
    assert loaded["operator"] == "ar-hand-mira"


# ---------------------------------------------------------------------------
# 3. Input envelope loading.
# ---------------------------------------------------------------------------


def test_17_load_input_envelope_happy_path(
    tmp_path: Path, block_envelope: dict
) -> None:
    p = _write_json(tmp_path / "input.json", block_envelope)
    env = listener.load_input_envelope(p)
    assert env["verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"


def test_18_load_input_envelope_missing_file(tmp_path: Path) -> None:
    with pytest.raises(listener.InputVerdictError, match="not found"):
        listener.load_input_envelope(tmp_path / "absent.json")


def test_19_load_input_envelope_unknown_verdict(
    tmp_path: Path, block_envelope: dict
) -> None:
    block_envelope["verdict"] = "MYSTERY-VERDICT"
    p = _write_json(tmp_path / "input.json", block_envelope)
    with pytest.raises(listener.InputVerdictError, match="not one of"):
        listener.load_input_envelope(p)


def test_20_load_input_envelope_no_verdict_field(
    tmp_path: Path, block_envelope: dict
) -> None:
    del block_envelope["verdict"]
    p = _write_json(tmp_path / "input.json", block_envelope)
    with pytest.raises(listener.InputVerdictError, match="verdict"):
        listener.load_input_envelope(p)


# ---------------------------------------------------------------------------
# 4. Override decision logic.
# ---------------------------------------------------------------------------


def test_21_decide_no_marker_returns_input_unchanged(
    block_envelope: dict,
) -> None:
    applied, verdict, note = listener.decide_override(block_envelope, None)
    assert applied is False
    assert verdict == "CUTOVER-DAY-MORGEN-BLOCK"
    assert "no override marker" in note


def test_22_decide_marker_on_block_applies(
    block_envelope: dict, valid_marker: dict
) -> None:
    normalised = listener.validate_marker(valid_marker)
    applied, verdict, note = listener.decide_override(block_envelope, normalised)
    assert applied is True
    assert verdict == "CUTOVER-DAY-MORGEN-CAUTION"
    assert "AR-Hand override applied" in note
    assert "ar-hand-mira" in note
    assert "ar-risk-tag-65-01" in note


def test_23_decide_marker_on_ready_is_noop(
    ready_envelope: dict, valid_marker: dict
) -> None:
    """Marker on READY input: marker recorded, verdict unchanged."""
    normalised = listener.validate_marker(valid_marker)
    applied, verdict, note = listener.decide_override(ready_envelope, normalised)
    assert applied is False
    assert verdict == "CUTOVER-DAY-MORGEN-READY"
    assert "not CUTOVER-DAY-MORGEN-BLOCK" in note
    assert "marker recorded" in note


def test_24_decide_marker_on_caution_is_noop(
    caution_envelope: dict, valid_marker: dict
) -> None:
    normalised = listener.validate_marker(valid_marker)
    applied, verdict, note = listener.decide_override(caution_envelope, normalised)
    assert applied is False
    assert verdict == "CUTOVER-DAY-MORGEN-CAUTION"


# ---------------------------------------------------------------------------
# 5. Output envelope construction.
# ---------------------------------------------------------------------------


def test_25_build_envelope_preserves_input_verbatim(
    block_envelope: dict, valid_marker: dict
) -> None:
    normalised = listener.validate_marker(valid_marker)
    out = listener.build_output_envelope(
        block_envelope,
        normalised,
        now_utc=datetime(2026, 6, 15, 6, 7, 0, tzinfo=timezone.utc),
    )
    assert out["input_verdict_envelope"] == block_envelope
    assert out["applied"] is True
    assert out["verdict"] == "CUTOVER-DAY-MORGEN-CAUTION"
    assert out["input_verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"
    assert out["override_marker"]["operator"] == "ar-hand-mira"


def test_26_build_envelope_no_marker(block_envelope: dict) -> None:
    out = listener.build_output_envelope(block_envelope, None)
    assert out["applied"] is False
    assert out["override_marker"] is None
    assert out["verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"


def test_27_build_envelope_schema_fields(block_envelope: dict) -> None:
    out = listener.build_output_envelope(block_envelope, None)
    assert out["schema_version"] == listener.OUTPUT_SCHEMA_VERSION
    assert out["workflow"] == "ar-hand-cutover-override-listener"
    assert out["tag"] == "tag-65"
    assert "decision_rule" in out
    assert (
        out["decision_rule"]["applies_to_input"]
        == "CUTOVER-DAY-MORGEN-BLOCK"
    )


# ---------------------------------------------------------------------------
# 6. CLI integration.
# ---------------------------------------------------------------------------


def test_28_cli_apply_override(
    tmp_path: Path, block_envelope: dict, valid_marker: dict
) -> None:
    input_path = _write_json(tmp_path / "input.json", block_envelope)
    marker_path = _write_json(tmp_path / "marker.json", valid_marker)
    out_path = tmp_path / "out" / "output.json"
    rc = listener.main(
        [
            "--input-verdict",
            str(input_path),
            "--override-marker",
            str(marker_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["applied"] is True
    assert out["verdict"] == "CUTOVER-DAY-MORGEN-CAUTION"


def test_29_cli_no_marker_passthrough(
    tmp_path: Path, block_envelope: dict
) -> None:
    input_path = _write_json(tmp_path / "input.json", block_envelope)
    out_path = tmp_path / "output.json"
    rc = listener.main(
        [
            "--input-verdict",
            str(input_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["applied"] is False
    assert out["verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"


def test_30_cli_strict_marker_rejects_invalid(
    tmp_path: Path, block_envelope: dict, valid_marker: dict
) -> None:
    input_path = _write_json(tmp_path / "input.json", block_envelope)
    valid_marker["operator"] = "Mira Kessler"  # invalid slug
    marker_path = _write_json(tmp_path / "marker.json", valid_marker)
    out_path = tmp_path / "output.json"
    rc = listener.main(
        [
            "--input-verdict",
            str(input_path),
            "--override-marker",
            str(marker_path),
            "--output",
            str(out_path),
            "--strict-marker",
        ]
    )
    assert rc == 3


def test_31_cli_lenient_marker_warns_but_passes(
    tmp_path: Path,
    block_envelope: dict,
    valid_marker: dict,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = _write_json(tmp_path / "input.json", block_envelope)
    valid_marker["reason"] = "x"  # too short
    marker_path = _write_json(tmp_path / "marker.json", valid_marker)
    out_path = tmp_path / "output.json"
    rc = listener.main(
        [
            "--input-verdict",
            str(input_path),
            "--override-marker",
            str(marker_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["applied"] is False
    assert out["verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"


def test_32_cli_missing_input_envelope_exits_2(tmp_path: Path) -> None:
    rc = listener.main(
        [
            "--input-verdict",
            str(tmp_path / "absent.json"),
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# 7. Aggregator override-marker descriptor surfacing (Tag-64 extension).
# ---------------------------------------------------------------------------


def test_33_aggregator_no_override_marker_surfaces_none(
    tmp_path: Path,
) -> None:
    envelope = agg.build_envelope(
        envelopes={s: None for s in agg.SUBSTRATES},
        override_marker_path=None,
    )
    assert envelope["ar_hand_override"] is None


def test_34_aggregator_present_marker_surfaces_descriptor(
    tmp_path: Path, valid_marker: dict
) -> None:
    marker_path = _write_json(tmp_path / "marker.json", valid_marker)
    envelope = agg.build_envelope(
        envelopes={
            "engine_composite": {"verdict": "PRE-CUTOVER-DEFECT"},
            "pyramide_composite": {"verdict": "ACCEPTANCE-PYRAMIDE-READY"},
            "e2e_smoke": {"verdict": "E2E-READY"},
        },
        override_marker_path=marker_path,
    )
    descriptor = envelope["ar_hand_override"]
    assert descriptor is not None
    assert descriptor["present"] is True
    assert descriptor["parse_ok"] is True
    assert descriptor["operator"] == "ar-hand-mira"
    assert descriptor["accepted_risk_id"] == "ar-risk-tag-65-01"
    # Aggregator verdict is BLOCK (un-overridden) -- aggregator
    # never applies the override itself.
    assert envelope["verdict"] == "CUTOVER-DAY-MORGEN-BLOCK"


def test_35_aggregator_unparseable_marker_surfaces_parse_failure(
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("garbage{", encoding="utf-8")
    envelope = agg.build_envelope(
        envelopes={s: None for s in agg.SUBSTRATES},
        override_marker_path=bad,
    )
    descriptor = envelope["ar_hand_override"]
    assert descriptor is not None
    assert descriptor["present"] is True
    assert descriptor["parse_ok"] is False


def test_36_aggregator_verdict_unaffected_by_marker(
    tmp_path: Path, valid_marker: dict, ready_envelope: dict
) -> None:
    """READY-input + marker stays READY at aggregator level."""
    marker_path = _write_json(tmp_path / "marker.json", valid_marker)
    envelope = agg.build_envelope(
        envelopes={
            "engine_composite": {"verdict": "PRE-CUTOVER-READY"},
            "pyramide_composite": {"verdict": "ACCEPTANCE-PYRAMIDE-READY"},
            "e2e_smoke": {"verdict": "E2E-READY"},
        },
        override_marker_path=marker_path,
    )
    assert envelope["verdict"] == "CUTOVER-DAY-MORGEN-READY"
    assert envelope["ar_hand_override"]["present"] is True


# ---------------------------------------------------------------------------
# 8. Schema constants & invariants.
# ---------------------------------------------------------------------------


def test_37_post_override_is_never_ready() -> None:
    """Invariant: post-override verdict is CAUTION, never READY."""
    assert listener.POST_OVERRIDE_VERDICT == "CUTOVER-DAY-MORGEN-CAUTION"
    assert listener.POST_OVERRIDE_VERDICT != listener.VERDICT_READY


def test_38_override_target_is_only_block() -> None:
    """Invariant: only BLOCK is a valid override target."""
    assert listener.OVERRIDE_TARGET_VERDICT == "CUTOVER-DAY-MORGEN-BLOCK"
    assert listener.OVERRIDE_TARGET_VERDICT not in {
        listener.VERDICT_READY,
        listener.VERDICT_CAUTION,
    }
