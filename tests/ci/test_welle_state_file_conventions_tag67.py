# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-67 Welle-N State-File-Conventions conformance test-suite (Amara).

This module pins the schema contract documented in
``docs/quality-gates/welle-n-state-file-conventions.md`` and exercised
by ``tooling/ci/verify_welle_state_file_conventions.py``.

Seventeen tests cover:

1.  All seven ``state/welle-N.json`` stub-files exist and parse.
2.  All seven stubs pass the verifier's rollup-schema.
3.  Stubs carry the canonical ``schema_version: "tag-67-v1"`` pin.
4.  Stubs carry the canonical ``phase: "phase-3-marathon"`` literal.
5.  Welle-1 KW-anchor is KW-22 per ADR-0066-Reihenfolge.
6.  Welle-3 KW-anchor stays on KW-25; Welle-4 + Welle-5 on KW-26 per
    Tag-74 W5-anchor-Drift-Fix reconciliation (``docs/persona-engine/
    welle-5-kw-anchor-reconciliation-tag74.md``; supersedes the Tag-67-
    era pin that placed all three on KW-25).
7.  Welle-7 KW-anchor is KW-27 per ADR-0066-Reihenfolge.
8.  Verifier rejects a rollup with status not in the four-value enum.
9.  Verifier rejects a rollup with mismatched welle_number-vs-filename.
10. Verifier rejects a rollup with naive (no-timezone) ISO timestamp.
11. Verifier rejects a rollup with a non-pinned ``schema_version``.
12. Verifier rejects a rollup where ``rollup_links.*`` paths do not
    match the welle-number.
13. Verifier accepts a fully-populated post-sign-off rollup (status =
    signed-off, OTS-anchor present, ISO timestamps with timezone).
14. Sign-off-schema validator pins the five mandatory fields from the
    canonical ``SignOffMarker`` shape (Tomás Tag-40 anchor).
15. Sign-off-schema validator rejects a sign-off with bad
    ``cross_welle_drift_assert`` enum.
16. Validation-last-verdict schema validator enforces non-empty
    ``verdict_iso`` and three-value ``verdict`` enum (Noa Tag-59
    notify-events cross-anchor).
17. Hot-spot-day schema validator enforces ``aggregator_verdict`` in
    CLEAR/CAUTION/BLOCK and the welle-3..7 numbering bound.

Sandbox-boundary: tests are hermetic; the verifier never writes to
``state/`` and the test-suite uses ``tmp_path`` for negative-cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make tooling.ci importable without conftest help.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tooling.ci import verify_welle_state_file_conventions as v  # noqa: E402


STATE_DIR = _REPO_ROOT / "state"
DOC_PATH = (
    _REPO_ROOT / "docs" / "quality-gates" / "welle-n-state-file-conventions.md"
)
ALL_WELLE = (1, 2, 3, 4, 5, 6, 7)


def _stub_rollup_doc(n: int, kw: str) -> dict:
    """Build a canonical Tag-67 stub rollup-doc for Welle-N."""
    return {
        "welle_number": n,
        "schema_version": "tag-67-v1",
        "phase": "phase-3-marathon",
        "kw_cutover_anchor": kw,
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": {
            "sign_off": f"state/welle-{n}-sign-off.json",
            "validation_last_verdict": f"state/welle-{n}-validation-last-verdict.json",
            "hot_spot_trend_dir": f"state/welle-{n}-hot-spot-trend/",
            "pre_auditor_decision": f"state/welle-{n}-pre-auditor-decision.json",
        },
        "audit_trail_anchor": "",
    }


# ---------------------------------------------------------------------------
# Section A -- Stub-file presence + canonical-form checks (Test 1..7)
# ---------------------------------------------------------------------------


def test_01_all_seven_stub_state_files_exist_and_parse() -> None:
    """Tag-67 §7: seven ``state/welle-{1..7}.json`` stubs committed."""
    for n in ALL_WELLE:
        path = STATE_DIR / f"welle-{n}.json"
        assert path.exists(), f"missing stub: {path}"
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        assert isinstance(doc, dict), f"stub not a JSON object: {path}"


def test_02_all_seven_stubs_pass_verifier_rollup_schema() -> None:
    """Each committed stub satisfies the Tag-67 verifier rollup-schema."""
    paths = [str(STATE_DIR / f"welle-{n}.json") for n in ALL_WELLE]
    report = v.verify_many(paths)
    assert report.ok, "violations: " + "; ".join(str(x) for x in report.violations)
    assert report.files_checked == 7


def test_03_stubs_carry_schema_version_pin() -> None:
    """All stubs pin ``schema_version: "tag-67-v1"``."""
    for n in ALL_WELLE:
        with (STATE_DIR / f"welle-{n}.json").open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc["schema_version"] == "tag-67-v1", f"welle-{n} schema_version drift"


def test_04_stubs_carry_phase_3_marathon_literal() -> None:
    """All stubs carry phase=phase-3-marathon (legacy phase-values rejected)."""
    for n in ALL_WELLE:
        with (STATE_DIR / f"welle-{n}.json").open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc["phase"] == "phase-3-marathon", f"welle-{n} phase drift"


def test_05_welle_1_kw_anchor_is_kw_22() -> None:
    """ADR-0066-Reihenfolge: Welle-1 is KW-22 (Tag-22 KW-22 Mittwoch)."""
    with (STATE_DIR / "welle-1.json").open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["kw_cutover_anchor"] == "KW-22"


def test_06_welle_345_kw_anchor_per_pre_cutover_run_order() -> None:
    """Tag-74 reconciliation: per ``pre-cutover-acceptance-run-order.md``
    §3 table Welle-3 stays on KW-25, Welle-4 + Welle-5 are on KW-26
    (Doppel-Welle-4+5 Cutover-Mittwoch 2026-06-24). The Tag-67-era
    pin (all three on KW-25) is superseded by the Tag-74 W5-anchor-fix
    PR; see ``docs/persona-engine/welle-5-kw-anchor-reconciliation-
    tag74.md``.
    """
    expected = {3: "KW-25", 4: "KW-26", 5: "KW-26"}
    for n, kw in expected.items():
        with (STATE_DIR / f"welle-{n}.json").open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc["kw_cutover_anchor"] == kw, (
            f"welle-{n} KW drift: expected {kw}, got "
            f"{doc['kw_cutover_anchor']}"
        )


def test_07_welle_7_kw_anchor_is_kw_27() -> None:
    """ADR-0066-Reihenfolge: Welle-7 (Marathon-Schluss) is KW-27."""
    with (STATE_DIR / "welle-7.json").open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["kw_cutover_anchor"] == "KW-27"


# ---------------------------------------------------------------------------
# Section B -- Verifier rejection cases on rollup-schema (Test 8..12)
# ---------------------------------------------------------------------------


def test_08_verifier_rejects_unknown_status_value() -> None:
    """Verifier rejects status not in {pending, in-progress, signed-off, rolled-back}."""
    bad = _stub_rollup_doc(3, "KW-25")
    bad["status"] = "almost-done"  # not in enum
    report = v.verify_doc("welle-3.json", bad, kind="rollup")
    assert not report.ok
    fields = [vio.field for vio in report.violations]
    assert "status" in fields


def test_09_verifier_rejects_mismatched_welle_number_vs_path() -> None:
    """Filename welle-3 with field welle_number=4 is a violation."""
    doc = _stub_rollup_doc(4, "KW-25")  # field says 4
    report = v.verify_doc("state/welle-3.json", doc, kind="rollup")
    assert not report.ok
    fields = [vio.field for vio in report.violations]
    assert "welle_number" in fields


def test_10_verifier_rejects_naive_timestamp_without_timezone() -> None:
    """ISO timestamps without timezone marker are rejected (Tag-67 §6.3)."""
    bad = _stub_rollup_doc(3, "KW-25")
    bad["cutover_iso"] = "2026-05-20T09:00:00"  # no tz marker
    report = v.verify_doc("state/welle-3.json", bad, kind="rollup")
    assert not report.ok
    fields = [vio.field for vio in report.violations]
    assert "cutover_iso" in fields


def test_11_verifier_rejects_non_pinned_schema_version() -> None:
    """schema_version must equal "tag-67-v1" by string-equality."""
    bad = _stub_rollup_doc(5, "KW-25")
    bad["schema_version"] = "tag-67-v2"  # drift
    report = v.verify_doc("state/welle-5.json", bad, kind="rollup")
    assert not report.ok
    fields = [vio.field for vio in report.violations]
    assert "schema_version" in fields


def test_12_verifier_rejects_rollup_link_with_wrong_welle_prefix() -> None:
    """rollup_links.* paths must start with state/welle-N- for the same N."""
    bad = _stub_rollup_doc(3, "KW-25")
    bad["rollup_links"]["sign_off"] = "state/welle-4-sign-off.json"  # wrong N
    report = v.verify_doc("state/welle-3.json", bad, kind="rollup")
    assert not report.ok
    fields = [vio.field for vio in report.violations]
    assert "rollup_links.sign_off" in fields


# ---------------------------------------------------------------------------
# Section C -- Happy-path post-sign-off rollup acceptance (Test 13)
# ---------------------------------------------------------------------------


def test_13_verifier_accepts_fully_populated_post_signoff_rollup() -> None:
    """A populated post-sign-off rollup (with OTS-anchor + ISO+timezone) is accepted."""
    good = _stub_rollup_doc(3, "KW-25")
    good["status"] = "signed-off"
    good["cutover_iso"] = "2026-05-20T09:00:00+02:00"
    good["signoff_iso"] = "2026-05-20T17:00:00+02:00"
    # 64-hex placeholder OTS-anchor
    good["audit_trail_anchor"] = "a" * 64
    report = v.verify_doc("state/welle-3.json", good, kind="rollup")
    assert report.ok, "violations: " + "; ".join(
        str(x) for x in report.violations
    )


# ---------------------------------------------------------------------------
# Section D -- Sign-off schema (Tomás Tag-40 anchor) (Test 14..15)
# ---------------------------------------------------------------------------


def _sign_off_doc(n: int, status: str = "pending") -> dict:
    return {
        "welle_number": n,
        "status": status,
        "ac_1_5_green": status == "signed-off",
        "ac_4_consensus_personas": [],
        "cross_welle_drift_assert": "green",
        "cutover_iso": "",
        "signoff_iso": "",
    }


def test_14_sign_off_validator_pins_five_mandatory_fields() -> None:
    """Tomás Tag-40 SignOffMarker shape: five fields required."""
    good = _sign_off_doc(3)
    rpt = v.verify_doc("state/welle-3-sign-off.json", good, kind="sign-off")
    assert rpt.ok

    for missing in (
        "welle_number",
        "status",
        "ac_1_5_green",
        "ac_4_consensus_personas",
        "cross_welle_drift_assert",
    ):
        bad = _sign_off_doc(3)
        del bad[missing]
        rpt = v.verify_doc("state/welle-3-sign-off.json", bad, kind="sign-off")
        assert not rpt.ok, f"validator did not flag missing {missing}"
        assert any(viol.field == missing for viol in rpt.violations)


def test_15_sign_off_validator_rejects_bad_drift_assert_enum() -> None:
    """cross_welle_drift_assert must be one of {green, caution, blocker}."""
    bad = _sign_off_doc(3)
    bad["cross_welle_drift_assert"] = "amber"  # not in enum
    rpt = v.verify_doc("state/welle-3-sign-off.json", bad, kind="sign-off")
    assert not rpt.ok
    fields = [vio.field for vio in rpt.violations]
    assert "cross_welle_drift_assert" in fields


# ---------------------------------------------------------------------------
# Section E -- Cross-anchor schemas (Noa Tag-59 + Tomás hot-spot) (16..17)
# ---------------------------------------------------------------------------


def test_16_validation_last_verdict_enforces_iso_and_verdict_enum() -> None:
    """Noa Tag-59 notify-events cross-anchor: verdict + verdict_iso pinned."""
    good = {
        "welle_number": 3,
        "verdict": "green",
        "verdict_iso": "2026-05-19T12:00:00+02:00",
        "checks": [
            {"name": "c1", "verdict": "green", "evidence_ref": ""},
            {"name": "c2", "verdict": "yellow", "evidence_ref": "http://x"},
        ],
        "schema_version": "tag-67-v1",
    }
    rpt = v.verify_doc(
        "state/welle-3-validation-last-verdict.json", good, kind="validation"
    )
    assert rpt.ok, "; ".join(str(x) for x in rpt.violations)

    # Case A: empty verdict_iso must fail.
    bad_iso = dict(good)
    bad_iso["verdict_iso"] = ""
    rpt = v.verify_doc(
        "state/welle-3-validation-last-verdict.json", bad_iso, kind="validation"
    )
    assert not rpt.ok
    assert any(vio.field == "verdict_iso" for vio in rpt.violations)

    # Case B: bad verdict enum must fail.
    bad_enum = dict(good)
    bad_enum["verdict"] = "ok"  # not in enum
    rpt = v.verify_doc(
        "state/welle-3-validation-last-verdict.json", bad_enum, kind="validation"
    )
    assert not rpt.ok
    assert any(vio.field == "verdict" for vio in rpt.violations)


def test_17_hot_spot_day_enforces_aggregator_verdict_and_welle_bound() -> None:
    """aggregator_verdict ∈ {CLEAR, CAUTION, BLOCK}; welle in 3..7 only."""
    good = {
        "welle_number": 3,
        "date": "2026-05-19",
        "aggregator_verdict": "CLEAR",
        "checks": {"c1": "green", "c2": "yellow"},
        "schema_version": "tag-67-v1",
    }
    rpt = v.verify_doc(
        "state/welle-3-hot-spot-trend/2026-05-19.json", good, kind="hot-spot-day"
    )
    assert rpt.ok, "; ".join(str(x) for x in rpt.violations)

    # Case A: aggregator_verdict outside enum.
    bad_agg = dict(good)
    bad_agg["aggregator_verdict"] = "WARN"  # not in enum
    rpt = v.verify_doc(
        "state/welle-3-hot-spot-trend/2026-05-19.json",
        bad_agg,
        kind="hot-spot-day",
    )
    assert not rpt.ok
    assert any(vio.field == "aggregator_verdict" for vio in rpt.violations)

    # Case B: welle-2 has no hot-spot file by §2.4 boundary.
    bad_wn = dict(good)
    bad_wn["welle_number"] = 2
    rpt = v.verify_doc(
        "state/welle-2-hot-spot-trend/2026-05-19.json",
        bad_wn,
        kind="hot-spot-day",
    )
    # The path-detector doesn't match welle-2 hot-spot-trend, so the
    # forced-kind path tests the in-file welle_number bound directly.
    assert not rpt.ok
    assert any(vio.field == "welle_number" for vio in rpt.violations)


# ---------------------------------------------------------------------------
# Section F -- Doc-presence anchor (sanity)
# ---------------------------------------------------------------------------


def test_doc_anchor_exists_and_pins_tag67() -> None:
    """The companion doc must exist and pin the Tag-67 schema_version."""
    assert DOC_PATH.exists(), f"missing companion doc: {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "tag-67-v1" in text
    assert "Welle-N State-File Conventions" in text
