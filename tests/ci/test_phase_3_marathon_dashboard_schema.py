# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Schema-validation tests for the Tag-40 Phase-3 Marathon
Live-Coordination dashboard extension and companion alert rules.

Covers two artifacts:

  * ``dashboards/phase-3c-cross-welle-coordination.json`` -- the
    Grafana JSON model, extended in Tag-40 with the Marathon-
    Live-Extension (42 new panels: 21 per-welle Pre/Cutover/Post
    tiles, Marathon-Timeline Gantt, 3 coordination markers, 6
    Phase-3-COMPLETE conjunction tiles, 3 Cutover-Day-Live panels,
    1 aggregate health gauge + 1 anchor text).
  * ``dashboards/phase-3-marathon-alerts.yaml`` -- the Prometheus
    AlertManager rule groups for critical Marathon events.

Sandbox boundary: pure stdlib + ``yaml`` (already in
production-lane install set). No network, no Prometheus
connection, no Grafana API contact. The tests assert structure
and invariants ("is this dashboard the shape an SRE expects")
rather than rendering correctness.

Anchors:
  - Tag-40 auftrag (Noa-SRE, Marathon Live-Coordination).
  - ADR-0066 (Phase-3c Beschleunigung, §Marathon-KW-24..27).
  - Henrik-Spec Phase-3-Schluss-Akzeptanz (5-Konjunktion).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DASHBOARD_PATH = (
    _REPO_ROOT / "dashboards" / "phase-3c-cross-welle-coordination.json"
)
_ALERTS_PATH = _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"


# ---------------------------------------------------------------------------
# Constants describing the Tag-40 Marathon contract
# ---------------------------------------------------------------------------


_WELLEN = [
    "welle-1",
    "welle-2",
    "welle-3",
    "welle-4",
    "welle-5",
    "welle-6",
    "welle-7",
]
_PHASES = ["pre", "cutover", "post"]


# Per-welle Pre/Cutover/Post tile contract: 7 x 3 = 21 panels, ids
# 101..121 in 3-stride blocks (one welle = three consecutive ids).
_PRE_CUTOVER_POST_PANEL_IDS = list(range(101, 122))

# Marathon-Timeline (Gantt) row + panel.
_TIMELINE_ROW_ID = 130
_TIMELINE_PANEL_ID = 131

# Cross-Welle-Coordination-Indikatoren: solo + two doppel markers.
_COORDINATION_ROW_ID = 140
_COORDINATION_PANEL_IDS = [141, 142, 143]

# Phase-3-COMPLETE 5-condition checkboxes + composite tile.
_COMPLETE_MARKER_ROW_ID = 150
_COMPLETE_MARKER_COND_IDS = [151, 152, 153, 154, 155]
_COMPLETE_MARKER_COMPOSITE_ID = 156

# Cutover-Day-Live-View panels.
_CUTOVER_DAY_ROW_ID = 160
_CUTOVER_DAY_PANEL_IDS = [161, 162, 163]

# Aggregat-Health-Score gauge + anchor.
_HEALTH_ROW_ID = 170
_HEALTH_GAUGE_ID = 171
_HEALTH_ANCHOR_ID = 172


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dashboard() -> dict:
    raw = _DASHBOARD_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def panels(dashboard: dict) -> list[dict]:
    return dashboard["panels"]


@pytest.fixture(scope="module")
def panels_by_id(panels: list[dict]) -> dict[int, dict]:
    return {p["id"]: p for p in panels}


@pytest.fixture(scope="module")
def alerts() -> dict:
    raw = _ALERTS_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


# ---------------------------------------------------------------------------
# Dashboard-level invariants
# ---------------------------------------------------------------------------


def test_dashboard_file_exists():
    assert _DASHBOARD_PATH.exists(), (
        f"dashboard missing: {_DASHBOARD_PATH}"
    )


def test_dashboard_parses_as_json(dashboard: dict):
    assert isinstance(dashboard, dict)


def test_dashboard_title_includes_marathon(dashboard: dict):
    assert "Marathon" in dashboard["title"], (
        "Tag-40 title must surface 'Marathon' for operator search; "
        f"got {dashboard['title']!r}"
    )


def test_dashboard_uid_preserved(dashboard: dict):
    # The Tag-38 UID must stay stable so existing bookmarks and
    # alert-dashboard-url annotations keep resolving.
    assert dashboard["uid"] == "wakir-phase-3c-cross-welle-coordination"


def test_dashboard_version_bumped(dashboard: dict):
    # Tag-38 was v1; Tag-40 must bump to >=2.
    assert dashboard["version"] >= 2


def test_dashboard_tags_include_tag40_and_marathon(dashboard: dict):
    tags = set(dashboard["tags"])
    required = {"tag-40", "phase-3-marathon", "marathon-live"}
    missing = required - tags
    assert not missing, f"tags missing: {missing}"


def test_dashboard_schema_version_is_grafana_10(dashboard: dict):
    # Grafana 10.x = schemaVersion 38.
    assert dashboard["schemaVersion"] == 38


def test_panel_ids_unique(panels: list[dict]):
    ids = [p["id"] for p in panels]
    duplicates = [pid for pid in ids if ids.count(pid) > 1]
    assert not duplicates, f"duplicate panel ids: {sorted(set(duplicates))}"


# ---------------------------------------------------------------------------
# Tag-40 Block 1: Pre/Cutover/Post 21 panels
# ---------------------------------------------------------------------------


def test_pre_cutover_post_block_has_21_panels(panels_by_id: dict[int, dict]):
    present = [pid for pid in _PRE_CUTOVER_POST_PANEL_IDS if pid in panels_by_id]
    assert present == _PRE_CUTOVER_POST_PANEL_IDS, (
        f"missing Pre/Cutover/Post panels: "
        f"{set(_PRE_CUTOVER_POST_PANEL_IDS) - set(present)}"
    )


@pytest.mark.parametrize(
    "welle_index,phase_index,panel_id",
    [
        (w, p, 101 + 3 * w + p)
        for w in range(7)
        for p in range(3)
    ],
)
def test_pre_cutover_post_panel_targets_correct_metric(
    panels_by_id: dict[int, dict],
    welle_index: int,
    phase_index: int,
    panel_id: int,
):
    panel = panels_by_id[panel_id]
    welle = _WELLEN[welle_index]
    phase = _PHASES[phase_index]
    targets = panel.get("targets", [])
    assert len(targets) == 1
    expr = targets[0]["expr"]
    assert "persona_engine_phase_3c_welle_phase_state" in expr, (
        f"panel {panel_id} must query the welle_phase_state metric"
    )
    assert f'welle="{welle}"' in expr, (
        f"panel {panel_id} must filter welle={welle!r}; got {expr!r}"
    )
    assert f'phase="{phase}"' in expr, (
        f"panel {panel_id} must filter phase={phase!r}; got {expr!r}"
    )


@pytest.mark.parametrize("panel_id", _PRE_CUTOVER_POST_PANEL_IDS)
def test_pre_cutover_post_panel_has_4_state_mappings(
    panels_by_id: dict[int, dict],
    panel_id: int,
):
    panel = panels_by_id[panel_id]
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    assert len(mappings) == 4
    flattened_texts = set()
    flattened_colors = set()
    for m in mappings:
        for spec in m["options"].values():
            flattened_texts.add(spec["text"])
            flattened_colors.add(spec["color"])
    assert flattened_texts == {"pending", "running", "signed-off", "rolled-back"}
    assert flattened_colors == {"grey", "blue", "green", "red"}


# ---------------------------------------------------------------------------
# Tag-40 Block 2: Marathon-Timeline (Gantt)
# ---------------------------------------------------------------------------


def test_timeline_row_present(panels_by_id: dict[int, dict]):
    row = panels_by_id[_TIMELINE_ROW_ID]
    assert row["type"] == "row"
    assert "Timeline" in row["title"] or "Gantt" in row["title"]


def test_timeline_panel_present_with_7_targets(panels_by_id: dict[int, dict]):
    p = panels_by_id[_TIMELINE_PANEL_ID]
    assert p["type"] == "state-timeline"
    assert len(p["targets"]) == 7, (
        "Marathon-Timeline must plot all 7 wellen as parallel tracks"
    )
    welles_referenced = set()
    for t in p["targets"]:
        m = re.search(r'welle="(welle-\d)"', t["expr"])
        if m:
            welles_referenced.add(m.group(1))
    assert welles_referenced == set(_WELLEN)


def test_timeline_has_ar_hand_signoff_annotation(panels_by_id: dict[int, dict]):
    p = panels_by_id[_TIMELINE_PANEL_ID]
    annotations = p.get("annotations", {}).get("list", [])
    assert annotations, "Timeline must carry AR-Hand-Sign-Off annotations"
    assert any(
        "ar_hand_signoff" in (a.get("expr", "") or "")
        or "AR-Hand" in (a.get("name", "") or "")
        for a in annotations
    )


# ---------------------------------------------------------------------------
# Tag-40 Block 3: Cross-Welle-Coordination-Indikatoren
# ---------------------------------------------------------------------------


def test_coordination_row_present(panels_by_id: dict[int, dict]):
    row = panels_by_id[_COORDINATION_ROW_ID]
    assert row["type"] == "row"


@pytest.mark.parametrize(
    "panel_id,topology",
    [
        (141, "welle-3-solo"),
        (142, "welle-4-5-doppel"),
        (143, "welle-6-7-doppel"),
    ],
)
def test_coordination_marker_targets_topology(
    panels_by_id: dict[int, dict],
    panel_id: int,
    topology: str,
):
    p = panels_by_id[panel_id]
    expr = p["targets"][0]["expr"]
    assert f'topology="{topology}"' in expr, (
        f"panel {panel_id} must mark topology={topology}; got {expr}"
    )


# ---------------------------------------------------------------------------
# Tag-40 Block 4: Phase-3-COMPLETE 5-Konjunktion
# ---------------------------------------------------------------------------


def test_complete_marker_row_present(panels_by_id: dict[int, dict]):
    row = panels_by_id[_COMPLETE_MARKER_ROW_ID]
    assert row["type"] == "row"
    assert "COMPLETE" in row["title"] or "Konjunktion" in row["title"]


@pytest.mark.parametrize("panel_id", _COMPLETE_MARKER_COND_IDS)
def test_complete_marker_condition_panels_present(
    panels_by_id: dict[int, dict],
    panel_id: int,
):
    p = panels_by_id[panel_id]
    assert p["type"] == "stat"
    # Each condition must have a 2-mapping (0/1) value-mapping.
    mappings = p["fieldConfig"]["defaults"]["mappings"]
    flat_values = {
        k
        for m in mappings
        for k in m["options"].keys()
    }
    assert flat_values == {"0", "1"}, (
        f"Cond panel {panel_id} must be boolean (0/1) only"
    )


def test_complete_marker_composite_is_conjunction(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[_COMPLETE_MARKER_COMPOSITE_ID]
    expr = p["targets"][0]["expr"]
    # Must AND all five conditions; we don't pin the exact spelling
    # but require all five known sub-expressions to appear.
    required_fragments = [
        "persona_engine_phase_3c_welle_state == 4",
        "wakir_henrik_audit_signoff == 1",
        "persona_engine_phase_3c_welle_state == 3",
        "wakir_cross_modul_drift_count",
        "wakir_ar_hand_final_signoff_phase_3",
    ]
    for frag in required_fragments:
        assert frag in expr, (
            f"composite COMPLETE marker missing condition fragment "
            f"{frag!r}; expr={expr!r}"
        )
    assert expr.count(" and ") >= 4, (
        "composite must be a 5-way conjunction (>=4 'and' operators)"
    )


# ---------------------------------------------------------------------------
# Tag-40 Block 5: Cutover-Day-Live-View
# ---------------------------------------------------------------------------


def test_cutover_day_row_present(panels_by_id: dict[int, dict]):
    row = panels_by_id[_CUTOVER_DAY_ROW_ID]
    assert row["type"] == "row"


def test_cutover_day_has_backenddecision_stream(panels_by_id: dict[int, dict]):
    p = panels_by_id[161]
    expr = p["targets"][0]["expr"]
    assert "persona_engine_backend_decision_total" in expr
    assert "rate(" in expr


def test_cutover_day_has_latency_histogram_p50_p99(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[162]
    exprs = [t["expr"] for t in p["targets"]]
    assert any("histogram_quantile(0.50" in e for e in exprs)
    assert any("histogram_quantile(0.99" in e for e in exprs)
    assert all(
        "persona_engine_backend_decision_latency_seconds_bucket" in e
        for e in exprs
    )


def test_cutover_day_has_realtime_drift_indicator(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[163]
    exprs = [t["expr"] for t in p["targets"]]
    assert any("wakir_cross_modul_drift_count" in e for e in exprs)


# ---------------------------------------------------------------------------
# Tag-40 Block 6: Aggregat-Health-Score gauge
# ---------------------------------------------------------------------------


def test_health_gauge_panel_present(panels_by_id: dict[int, dict]):
    p = panels_by_id[_HEALTH_GAUGE_ID]
    assert p["type"] == "gauge"
    expr = p["targets"][0]["expr"]
    assert expr == "wakir_phase_3_marathon_health_score"
    defaults = p["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["min"] == 0
    assert defaults["max"] == 100
    steps = defaults["thresholds"]["steps"]
    step_colors = [s["color"] for s in steps]
    # 0..50 red, 50..75 orange, 75..90 yellow, 90..100 green.
    assert step_colors == ["red", "orange", "yellow", "green"]


def test_health_anchor_text_panel_present(panels_by_id: dict[int, dict]):
    p = panels_by_id[_HEALTH_ANCHOR_ID]
    assert p["type"] == "text"
    content = p["options"]["content"]
    assert "Tag-40" in content
    assert "Marathon" in content


# ---------------------------------------------------------------------------
# Alert-rule YAML invariants
# ---------------------------------------------------------------------------


def test_alerts_file_exists():
    assert _ALERTS_PATH.exists(), f"alerts missing: {_ALERTS_PATH}"


def test_alerts_yaml_parses(alerts: dict):
    assert isinstance(alerts, dict)
    assert "groups" in alerts


def test_alerts_has_required_groups(alerts: dict):
    group_names = {g["name"] for g in alerts["groups"]}
    required = {
        "phase-3-marathon-welle-rollback",
        "phase-3-marathon-complete-marker-integrity",
        "phase-3-marathon-cross-modul-drift",
        "phase-3-marathon-aggregate-health",
    }
    missing = required - group_names
    assert not missing, f"alert groups missing: {missing}"


def test_alert_groups_have_unique_alert_names(alerts: dict):
    names: list[str] = []
    for g in alerts["groups"]:
        for r in g["rules"]:
            names.append(r["alert"])
    duplicates = [n for n in names if names.count(n) > 1]
    assert not duplicates, f"duplicate alert names: {sorted(set(duplicates))}"


def test_critical_alerts_present(alerts: dict):
    by_name = {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }
    required = {
        "WakirPhase3MarathonWelleRollback",
        "WakirPhase3CompleteMarkerFalsePositive",
        "WakirPhase3CrossModulDriftDetected",
    }
    missing = required - set(by_name)
    assert not missing, f"critical alerts missing: {missing}"


@pytest.mark.parametrize(
    "alert_name",
    [
        "WakirPhase3MarathonWelleRollback",
        "WakirPhase3CompleteMarkerFalsePositive",
        "WakirPhase3CrossModulDriftDetected",
    ],
)
def test_critical_alerts_are_page_severity(alerts: dict, alert_name: str):
    by_name = {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }
    rule = by_name[alert_name]
    assert rule["labels"]["severity"] == "page", (
        f"{alert_name} must be severity=page for Marathon-critical events"
    )


def test_all_alerts_have_owner_noa(alerts: dict):
    for g in alerts["groups"]:
        for r in g["rules"]:
            assert r["labels"].get("owner") == "noa-sre", (
                f"{r['alert']} missing owner=noa-sre label"
            )


def test_all_alerts_have_summary_and_description(alerts: dict):
    for g in alerts["groups"]:
        for r in g["rules"]:
            ann = r.get("annotations", {})
            assert ann.get("summary"), f"{r['alert']} missing summary"
            assert ann.get("description"), f"{r['alert']} missing description"


def test_welle_rollback_alert_has_60s_for_window(alerts: dict):
    by_name = {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }
    rule = by_name["WakirPhase3MarathonWelleRollback"]
    assert rule["for"] in ("60s", "1m"), (
        f"welle-rollback for-window must be 60s/1m to tolerate one "
        f"scrape gap; got {rule['for']}"
    )


def test_health_score_critical_below_50(alerts: dict):
    by_name = {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }
    rule = by_name["WakirPhase3MarathonHealthScoreCritical"]
    assert "< 50" in rule["expr"]
    assert rule["labels"]["severity"] == "page"
