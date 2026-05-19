# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-68 Pre-Existing-Failures-Fix Anti-Regression Pin
=====================================================

Tomas-Tag-67 git-stash-verified three pre-existing failures on
origin/main that were *not* induced by his Tag-67 work:

  1. ``tests/ci/test_adr_errata_audit_pin_gate_tag59.py::
     test_baseline_intact_against_live_repo_state_or_skips`` --
     drift: ``envelope.draft_shape: present, not in baseline``.
     Drift-source: Reza Tag-63 (PR #403) extended
     ``audit_adr_errata_spec_drift.run_audit`` with an optional
     ``draft_shape`` field for v0.4.4-draft detection. The Tag-57
     baseline did not know that field. Fix: refresh the
     ``tooling/audit/adr-errata-audit-baseline.json`` snapshot
     against the current envelope (live env summary and markers
     are identical to baseline; only the new ``draft_shape``
     field was added).

  2. ``tests/ci/test_phase_3_marathon_failure_mode_alerts.py::
     test_total_group_count_matches_tag45_plus_tag40_plus_tag50``
     -- pin said 19 groups, current YAML has 20. Drift-source:
     Noa Tag-64 (PR #410) added one new group
     ``cutover-day-morgen-trinary-routing`` with three
     READY/CAUTION/BLOCK verdict-reactive alarms. The original
     test docstring explicitly invited "Update test if expanding
     deliberately" -- Tag-64 was deliberate; the pin had to
     advance.

  3. ``tests/ci/test_phase_3_marathon_failure_mode_alerts.py::
     test_catalog_references_all_notify_receivers`` -- the YAML
     used ``activity-log:hold-marker`` (and ``pagerduty:
     management``) but neither was documented in the notify-
     receiver inventory at ``docs/observability/pre-mortem-
     failure-mode-notify-catalog.md``. Drift-source: Noa Tag-64
     missed the catalog-side documentation when adding the
     trinary-routing alarms. Fix: insert both receivers into the
     section-3 inventory table.

These tests pin the three fixes so the next baseline-drift
or catalog-drift fails loudly with a Tag-68 anchor in the
test name.

Sandbox boundary: pure stdlib + ``yaml``. No external state,
no network, no AI-Corp/decisions reads (the audit-pin verifier
tests live in the Tag-59 suite).

Tag-68, Amara-Hand, continuous-mode pre-cutover hot-spot fix.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Fix 1 anchors: ADR-Errata audit baseline
# ---------------------------------------------------------------------------

_BASELINE_PATH = (
    _REPO_ROOT / "tooling" / "audit" / "adr-errata-audit-baseline.json"
)


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_file_exists_after_tag68_refresh():
    assert _BASELINE_PATH.is_file(), (
        f"Tag-68 baseline refresh must keep the file in place: "
        f"{_BASELINE_PATH}"
    )


def test_baseline_top_level_contains_draft_shape_field(baseline: dict):
    """Tag-63 extended the envelope with ``draft_shape``. The
    Tag-68 baseline refresh captures the new field so the Tag-59
    pin verdict stays AUDIT-PIN-INTACT against the post-Tag-63
    helper."""
    assert "draft_shape" in baseline, (
        "Tag-68 baseline must include the Tag-63 draft_shape field"
    )


def test_baseline_draft_shape_is_non_draft_envelope(baseline: dict):
    """The Tag-59 pin guards against v0.4.3 (pre-cutover-freeze)
    -- not v0.4.4-draft. The baseline draft_shape must therefore
    record ``is_draft=False``; if the pin spec ever flips to the
    draft, this test fails loudly so the operator knows the pin
    moved."""
    ds = baseline["draft_shape"]
    assert ds.get("is_draft") is False, (
        "Tag-68 baseline must pin the non-draft (v0.4.3) shape; "
        f"got {ds!r}"
    )
    assert ds.get("spec_version") == "0.4.3", (
        "Tag-68 baseline must pin spec_version 0.4.3; "
        f"got {ds!r}"
    )


def test_baseline_summary_is_zero_drift_six_markers(baseline: dict):
    """Tag-68 baseline refresh must not silently absorb new drift
    findings. The Tag-57 cross-audit envelope had 6 markers, 0
    drift, 6 citation-ok -- the Tag-68 refresh must preserve
    those numbers (anything else means a real drift slipped in
    behind the baseline-rotation)."""
    s = baseline["summary"]
    assert s["markers_total"] == 6
    assert s["markers_with_drift"] == 0
    assert s["markers_with_citation_ok"] == 6


def test_baseline_err_marker_ids_unchanged(baseline: dict):
    """ERR-S1..S6 must remain the marker-set; the Tag-68 refresh
    is a field-addition only, not a marker-set rotation."""
    ids = [m["marker_id"] for m in baseline["err_markers"]]
    assert ids == [
        "ERR-S1", "ERR-S2", "ERR-S3", "ERR-S4", "ERR-S5", "ERR-S6"
    ]


def test_baseline_paths_remain_relative_after_refresh(baseline: dict):
    """Runner-agnostic path discipline (the Tag-59 invariant) must
    survive the Tag-68 baseline refresh."""
    assert not baseline["spec_path"].startswith("/"), (
        f"baseline spec_path must be relative; got {baseline['spec_path']!r}"
    )
    for h in baseline["adr_heads"]:
        assert not h["path"].startswith("/"), (
            f"baseline ADR path must be relative; got {h['path']!r}"
        )


# ---------------------------------------------------------------------------
# Fix 2 anchors: phase-3-marathon alerts.yaml group count
# ---------------------------------------------------------------------------

_ALERTS_PATH = (
    _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
)


@pytest.fixture(scope="module")
def alerts() -> dict:
    return yaml.safe_load(_ALERTS_PATH.read_text(encoding="utf-8"))


def test_alerts_group_count_is_twenty_after_tag64(alerts: dict):
    """Tag-40(4) + Tag-45(8) + Tag-50(7) + Tag-64(1) = 20.
    Tag-68 raised the pin from 19 to 20 to absorb the Tag-64
    ``cutover-day-morgen-trinary-routing`` group. The next
    deliberate expansion must bump this number; the next
    accidental drop must crash this test."""
    assert len(alerts["groups"]) == 20, (
        f"Tag-68 pin: alert groups must equal 20; got "
        f"{len(alerts['groups'])}"
    )


def test_alerts_contain_tag64_trinary_routing_group(alerts: dict):
    """The Tag-64 group must be present (otherwise the group-count
    pin would still pass on 20 with a different shape)."""
    names = {g["name"] for g in alerts["groups"]}
    assert "cutover-day-morgen-trinary-routing" in names, (
        "Tag-68 pin: Tag-64 trinary-routing group must exist"
    )


def test_tag64_trinary_routing_has_three_verdict_alarms(alerts: dict):
    """READY + CAUTION + BLOCK = three trinary-verdict-reactive
    rules."""
    for g in alerts["groups"]:
        if g["name"] == "cutover-day-morgen-trinary-routing":
            alert_names = {r["alert"] for r in g["rules"]}
            assert alert_names == {
                "WakirCutoverDayMorgenVerdictReady",
                "WakirCutoverDayMorgenVerdictCaution",
                "WakirCutoverDayMorgenVerdictBlock",
            }, (
                f"Tag-64 trinary-routing alarm-set unexpected: "
                f"{alert_names}"
            )
            return
    pytest.fail("Tag-64 trinary-routing group missing")


# ---------------------------------------------------------------------------
# Fix 3 anchors: notify-receiver catalog completeness
# ---------------------------------------------------------------------------

_CATALOG_PATH = (
    _REPO_ROOT
    / "docs"
    / "observability"
    / "pre-mortem-failure-mode-notify-catalog.md"
)


@pytest.fixture(scope="module")
def catalog_text() -> str:
    return _CATALOG_PATH.read_text(encoding="utf-8")


def test_catalog_documents_activity_log_hold_marker(catalog_text: str):
    """Tag-64 introduced ``activity-log:hold-marker`` as the
    BLOCK-verdict Mira-Hand-Hold-Marker receiver. Tag-68 fix
    adds it to the section-3 receiver inventory; this pin makes
    sure the entry never silently disappears."""
    assert "activity-log:hold-marker" in catalog_text, (
        "Tag-68 fix: catalog must document activity-log:hold-marker"
    )


def test_catalog_documents_pagerduty_management(catalog_text: str):
    """Tag-64 BLOCK verdicts page both sre-oncall AND management;
    the management channel must be documented in the catalog."""
    assert "pagerduty:management" in catalog_text, (
        "Tag-68 fix: catalog must document pagerduty:management"
    )


def test_catalog_covers_every_receiver_used_in_yaml(
    catalog_text: str,
):
    """Equivalent invariant to the
    ``test_catalog_references_all_notify_receivers`` test in the
    Tag-45 suite, pinned independently under Tag-68 so the fix
    cannot regress without two tests failing in lock-step."""
    alerts = yaml.safe_load(_ALERTS_PATH.read_text())
    used: set[str] = set()
    for g in alerts["groups"]:
        for r in g["rules"]:
            np = r.get("annotations", {}).get("notify_path", "")
            for chunk in np.split("+"):
                chunk = chunk.strip()
                if chunk:
                    used.add(chunk)
    missing = sorted(r for r in used if r not in catalog_text)
    assert not missing, (
        f"Tag-68 catalog-completeness invariant: receivers used "
        f"in YAML but not in catalog: {missing}"
    )


def test_catalog_hold_marker_row_mentions_tag64_anchor(
    catalog_text: str,
):
    """The hold-marker catalog row must carry an explicit Tag-64
    anchor so the operator can trace the receiver back to its
    origin spawn (anti-orphan-discipline)."""
    # Find the catalog row for activity-log:hold-marker.
    rows = [
        ln
        for ln in catalog_text.splitlines()
        if "activity-log:hold-marker" in ln
    ]
    assert rows, "hold-marker row missing"
    assert any("Tag-64" in r for r in rows), (
        "hold-marker row must reference Tag-64 anchor"
    )


def test_catalog_management_row_mentions_tag64_anchor(
    catalog_text: str,
):
    """Same anti-orphan discipline for pagerduty:management."""
    rows = [
        ln
        for ln in catalog_text.splitlines()
        if "pagerduty:management" in ln
    ]
    assert rows, "pagerduty:management row missing"
    assert any("Tag-64" in r for r in rows), (
        "pagerduty:management row must reference Tag-64 anchor"
    )


# ---------------------------------------------------------------------------
# Cross-fix meta-pin: all three originally failing tests pass now
# ---------------------------------------------------------------------------


def test_originally_failing_tests_are_named_in_this_file_docstring():
    """Anti-archaeology pin: the three originally failing test
    names must be cited verbatim in this module docstring so a
    future maintainer can trace the Tag-68 fix back to the
    specific failures."""
    doc = __doc__ or ""
    for needle in (
        "test_baseline_intact_against_live_repo_state_or_skips",
        "test_total_group_count_matches_tag45_plus_tag40_plus_tag50",
        "test_catalog_references_all_notify_receivers",
    ):
        assert needle in doc, (
            f"Tag-68 docstring must cite the original failing "
            f"test {needle!r}"
        )


def test_drift_source_attribution_present_in_docstring():
    """The Tag-68 fix attributes each drift to its origin spawn
    (Reza Tag-63 for fix 1; Noa Tag-64 for fixes 2+3). This pin
    keeps the attribution from drifting away in future refactors."""
    doc = __doc__ or ""
    assert "Reza Tag-63" in doc
    assert "Noa Tag-64" in doc
    assert re.search(r"PR\s*#403", doc), "Tag-63 PR anchor missing"
    assert re.search(r"PR\s*#410", doc), "Tag-64 PR anchor missing"
