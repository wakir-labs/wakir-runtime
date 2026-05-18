# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-45 Pre-Mortem-Failure-Mode-Alert-Extension.

Covers three artifacts:

  * ``dashboards/phase-3-marathon-alerts.yaml`` (Tag-45 alert
    groups: A1, A2, A4, A5, B1, B3, C1 granular, hot-spots).
  * ``dashboards/phase-3c-cross-welle-coordination.json`` (Tag-45
    hot-spot row, panel ids 180..184).
  * ``docs/observability/pre-mortem-failure-mode-notify-catalog.md``
    (notify-catalog completeness and consistency with the YAML).

Drift-detection: each Tag-45 alert name must appear in the
notify-catalog markdown and vice versa. The catalogue is the
single source of truth for which Tag-45 alerts exist; this test
makes any divergence between YAML + Markdown loud.

Sandbox boundary: pure stdlib + ``yaml``. No Prometheus, no
Grafana, no network.

Anchors:
  - Tag-45 auftrag (Noa-SRE, Pre-Mortem-Failure-Mode-Alerts).
  - Henrik Tag-44 Pre-Mortem
    (reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md).
  - Tag-40 baseline alerts test
    (tests/ci/test_phase_3_marathon_dashboard_schema.py).
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALERTS_PATH = _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
_DASHBOARD_PATH = (
    _REPO_ROOT / "dashboards" / "phase-3c-cross-welle-coordination.json"
)
_CATALOG_PATH = (
    _REPO_ROOT
    / "docs"
    / "observability"
    / "pre-mortem-failure-mode-notify-catalog.md"
)


# ---------------------------------------------------------------------------
# Tag-45 alert-name contract
# ---------------------------------------------------------------------------


_TAG45_ALERTS = {
    "WakirPhase3FailureModeA1CrossModulDriftPerWelle": {
        "failure_mode": "A1",
        "severity": "page",
        "for_window": "2m",
    },
    "WakirPhase3FailureModeA2FsmPhantomTransition": {
        "failure_mode": "A2",
        "severity": "page",
        "for_window": "60s",
    },
    "WakirPhase3FailureModeA4NatsModeMismatch": {
        "failure_mode": "A4",
        "severity": "page",
        "for_window": "60s",
    },
    "WakirPhase3FailureModeA5SelfReferenceTrapWelle3Critical": {
        "failure_mode": "A5",
        "severity": "page",
        "for_window": "2m",
    },
    "WakirPhase3FailureModeB1ArHandStopMissingTrigger": {
        "failure_mode": "B1",
        "severity": "page",
        "for_window": "5m",
    },
    "WakirPhase3FailureModeB3Iia1130DefaultPath": {
        "failure_mode": "B3",
        "severity": "warning",
        "for_window": "1m",
    },
    "WakirPhase3FailureModeC1MarkerFalsePositiveCond1": {
        "failure_mode": "C1",
        "severity": "page",
        "for_window": "1m",
    },
    "WakirPhase3FailureModeC1MarkerFalsePositiveCond4": {
        "failure_mode": "C1",
        "severity": "page",
        "for_window": "1m",
    },
    "WakirPhase3HotSpotWelle3Welle4Coupling": {
        "failure_mode": "A1+A5-coupling",
        "severity": "page",
        "for_window": "2m",
    },
    "WakirPhase3HotSpotWelle4Welle5Welle7Coupling": {
        "failure_mode": "A3+A8-coupling",
        "severity": "page",
        "for_window": "5m",
    },
}


_TAG45_GROUP_NAMES = {
    "phase-3-marathon-failure-mode-a1-cross-modul-drift",
    "phase-3-marathon-failure-mode-a2-fsm-phantom",
    "phase-3-marathon-failure-mode-a4-nats-mismatch",
    "phase-3-marathon-failure-mode-a5-self-reference-trap",
    "phase-3-marathon-failure-mode-b1-ar-hand-stop-missing",
    "phase-3-marathon-failure-mode-b3-iia-1130-default",
    "phase-3-marathon-failure-mode-c1-marker-false-positive-granular",
    "phase-3-marathon-failure-mode-hot-spot-welle-3-4",
}


_TAG40_GROUP_NAMES = {
    "phase-3-marathon-welle-rollback",
    "phase-3-marathon-complete-marker-integrity",
    "phase-3-marathon-cross-modul-drift",
    "phase-3-marathon-aggregate-health",
}


_TAG45_HOTSPOT_PANEL_IDS = [180, 181, 182, 183, 184]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alerts() -> dict:
    return yaml.safe_load(_ALERTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(_DASHBOARD_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def panels_by_id(dashboard: dict) -> dict[int, dict]:
    return {p["id"]: p for p in dashboard["panels"]}


@pytest.fixture(scope="module")
def catalog_text() -> str:
    return _CATALOG_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_by_name(alerts: dict) -> dict[str, dict]:
    return {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }


# ---------------------------------------------------------------------------
# YAML parses + structural invariants
# ---------------------------------------------------------------------------


def test_alerts_yaml_parses(alerts: dict):
    assert isinstance(alerts, dict)
    assert "groups" in alerts


def test_tag40_baseline_groups_still_present(alerts: dict):
    group_names = {g["name"] for g in alerts["groups"]}
    missing = _TAG40_GROUP_NAMES - group_names
    assert not missing, (
        f"Tag-40 baseline groups must still exist after Tag-45 "
        f"extension; missing: {missing}"
    )


def test_tag45_groups_present(alerts: dict):
    group_names = {g["name"] for g in alerts["groups"]}
    missing = _TAG45_GROUP_NAMES - group_names
    assert not missing, f"Tag-45 alert groups missing: {missing}"


def test_total_group_count_matches_tag45_plus_tag40_plus_tag50(alerts: dict):
    # 4 Tag-40 + 8 Tag-45 + 7 Tag-50 = 19 expected groups. The
    # Tag-50 Welle-N-specific groups are appended after the Tag-45
    # failure-mode + hot-spot groups. See
    # tests/ci/test_welle_n_specific_alerts.py for the Tag-50
    # contract. If a future task adds more, bump this expectation
    # deliberately.
    assert len(alerts["groups"]) == 19, (
        f"Expected exactly Tag-40(4) + Tag-45(8) + Tag-50(7) = 19 "
        f"groups; got {len(alerts['groups'])}. Update test if "
        f"expanding deliberately."
    )


def test_alert_names_unique(alerts: dict):
    names = [
        r["alert"]
        for g in alerts["groups"]
        for r in g["rules"]
    ]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"duplicate alert names: {duplicates}"


# ---------------------------------------------------------------------------
# Tag-45 alert-rule contract (drift-detection)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_present(alerts_by_name: dict, alert_name: str):
    assert alert_name in alerts_by_name, (
        f"Tag-45 alert missing: {alert_name}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_has_owner_noa(
    alerts_by_name: dict, alert_name: str
):
    rule = alerts_by_name[alert_name]
    assert rule["labels"].get("owner") == "noa-sre", (
        f"{alert_name} missing owner=noa-sre"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_severity_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG45_ALERTS[alert_name]["severity"]
    actual = alerts_by_name[alert_name]["labels"].get("severity")
    assert actual == expected, (
        f"{alert_name} severity mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_for_window_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG45_ALERTS[alert_name]["for_window"]
    actual = alerts_by_name[alert_name]["for"]
    assert actual == expected, (
        f"{alert_name} for-window mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_has_runbook_and_notify_path(
    alerts_by_name: dict, alert_name: str
):
    ann = alerts_by_name[alert_name].get("annotations", {})
    assert ann.get("summary"), f"{alert_name} missing summary"
    assert ann.get("description"), f"{alert_name} missing description"
    assert ann.get("runbook_url"), f"{alert_name} missing runbook_url"
    assert ann.get("notify_path"), f"{alert_name} missing notify_path"


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_has_failure_mode_label_or_hot_spot(
    alerts_by_name: dict, alert_name: str
):
    labels = alerts_by_name[alert_name]["labels"]
    has_fm = "failure_mode" in labels
    has_hs = "hot_spot" in labels
    assert has_fm or has_hs, (
        f"{alert_name} must carry failure_mode= or hot_spot= label "
        f"for catalog cross-link; labels={list(labels.keys())}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_tag45_alert_has_adr_anchor(
    alerts_by_name: dict, alert_name: str
):
    labels = alerts_by_name[alert_name]["labels"]
    assert labels.get("adr") == "adr-0066", (
        f"{alert_name} must reference adr-0066 (Phase-3c "
        f"Beschleunigung); got adr={labels.get('adr')}"
    )


# ---------------------------------------------------------------------------
# Special-case threshold invariants
# ---------------------------------------------------------------------------


def test_a5_self_reference_trap_threshold_ratio_3(
    alerts_by_name: dict,
):
    rule = alerts_by_name[
        "WakirPhase3FailureModeA5SelfReferenceTrapWelle3Critical"
    ]
    expr = rule["expr"]
    assert ">= 3" in expr, (
        "A5 self-reference-trap threshold must be 3x baseline "
        "(Henrik Pre-Mortem cites +340% spike); expr did not "
        "contain '>= 3'"
    )
    assert "welle=\"welle-3\"" in expr
    assert "audit-bridge" in expr
    # Critical: must scrape at 15s for KW-25 SOLO sensitivity.
    by_group = {
        g["name"]: g
        for g in yaml.safe_load(_ALERTS_PATH.read_text())["groups"]
    }
    g = by_group["phase-3-marathon-failure-mode-a5-self-reference-trap"]
    assert g.get("interval") == "15s", (
        f"A5 group must scrape every 15s for KW-25 SOLO "
        f"sensitivity; got interval={g.get('interval')}"
    )


def test_b1_ar_hand_stop_missing_is_conjunction(
    alerts_by_name: dict,
):
    rule = alerts_by_name[
        "WakirPhase3FailureModeB1ArHandStopMissingTrigger"
    ]
    expr = rule["expr"]
    assert "wakir_cross_modul_drift_count > 0" in expr
    assert "wakir_ar_hand_stop_marker_total" in expr
    assert "increase(" in expr
    # Tolerate `and` on its own line in YAML block-scalar
    assert "and" in expr.lower().split()


def test_b3_iia_1130_is_warning_not_page(alerts_by_name: dict):
    rule = alerts_by_name["WakirPhase3FailureModeB3Iia1130DefaultPath"]
    assert rule["labels"]["severity"] == "warning", (
        "B3 IIA-1130 default-path is governance signal, must NOT "
        "page the on-call"
    )
    expr = rule["expr"]
    assert "auditor=\"henrik\"" in expr
    assert "auditor=\"external-pre-auditor\"" in expr


def test_hot_spot_welle_3_4_requires_both_signals(
    alerts_by_name: dict,
):
    rule = alerts_by_name["WakirPhase3HotSpotWelle3Welle4Coupling"]
    expr = rule["expr"]
    assert "welle-3" in expr
    assert "audit-bridge" in expr
    assert "wakir_state_backing_self_check_hash" in expr
    assert "welle-4" in expr
    # Tolerate `and` on its own line in YAML block-scalar
    assert "and" in expr.lower().split()
    # Hot-Spot #1 threshold per catalog rationale: 1.5x baseline.
    assert "> 1.5" in expr, (
        "Hot-Spot #1 must use 1.5x baseline threshold per notify-"
        "catalog rationale; expr did not contain '> 1.5'"
    )


def test_hot_spot_welle_4_5_7_requires_downstream_consumption(
    alerts_by_name: dict,
):
    rule = alerts_by_name[
        "WakirPhase3HotSpotWelle4Welle5Welle7Coupling"
    ]
    expr = rule["expr"]
    assert "welle-4" in expr
    assert "welle-5" in expr
    assert "welle-7" in expr
    assert "wakir_state_backing_self_check_hash" in expr
    # Tolerate `and` on its own line in YAML block-scalar
    assert "and" in expr.lower().split()


def test_c1_granular_alerts_cover_two_conditions(
    alerts_by_name: dict,
):
    cond1 = alerts_by_name[
        "WakirPhase3FailureModeC1MarkerFalsePositiveCond1"
    ]
    cond4 = alerts_by_name[
        "WakirPhase3FailureModeC1MarkerFalsePositiveCond4"
    ]
    assert (
        cond1["labels"].get("condition")
        == "cond-1-all-wellen-state-4"
    )
    assert (
        cond4["labels"].get("condition")
        == "cond-4-drift-zero-marathon"
    )
    # Both must trigger the marker-audit notify-path.
    assert (
        "henrik-marker-audit"
        in cond1["annotations"]["notify_path"]
    )
    assert (
        "henrik-marker-audit"
        in cond4["annotations"]["notify_path"]
    )


# ---------------------------------------------------------------------------
# Dashboard Tag-45 hot-spot row invariants
# ---------------------------------------------------------------------------


def test_dashboard_version_bumped_to_at_least_4(dashboard: dict):
    assert dashboard["version"] >= 4, (
        "Tag-45 must bump dashboard version >= 4 (Tag-40 was 2..3)"
    )


def test_dashboard_tags_include_tag45(dashboard: dict):
    tags = set(dashboard["tags"])
    assert "tag-45" in tags
    assert "pre-mortem-failure-mode" in tags
    assert "hot-spot" in tags


def test_hot_spot_panel_ids_present(panels_by_id: dict[int, dict]):
    missing = [
        pid for pid in _TAG45_HOTSPOT_PANEL_IDS if pid not in panels_by_id
    ]
    assert not missing, f"Tag-45 hot-spot panel ids missing: {missing}"


def test_hot_spot_row_is_row_type(panels_by_id: dict[int, dict]):
    row = panels_by_id[180]
    assert row["type"] == "row"
    assert "Hot-Spot" in row["title"]
    assert "Pre-Mortem" in row["title"]


def test_hot_spot_panel_181_audit_bridge_rate(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[181]
    expr = p["targets"][0]["expr"]
    assert "persona_engine_backend_decision_total" in expr
    assert "welle-3" in expr
    assert "audit-bridge" in expr
    assert "offset 24h" in expr


def test_hot_spot_panel_182_state_backing_hash_changes(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[182]
    expr = p["targets"][0]["expr"]
    assert "wakir_state_backing_self_check_hash" in expr
    assert "welle-4" in expr
    assert "changes(" in expr


def test_hot_spot_panel_183_downstream_consumption(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[183]
    expr = p["targets"][0]["expr"]
    assert "welle-4" in expr
    assert "welle-5" in expr
    assert "welle-7" in expr


def test_hot_spot_panel_184_is_anchor_text(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[184]
    assert p["type"] == "text"
    content = p["options"]["content"]
    assert "Tag-45" in content
    assert "Henrik" in content
    assert "Hot-Spot" in content


# ---------------------------------------------------------------------------
# Notify-catalog markdown drift-detection
# ---------------------------------------------------------------------------


def test_catalog_file_exists():
    assert _CATALOG_PATH.exists(), f"catalog missing: {_CATALOG_PATH}"


@pytest.mark.parametrize("alert_name", sorted(_TAG45_ALERTS.keys()))
def test_catalog_references_each_tag45_alert(
    catalog_text: str, alert_name: str
):
    assert alert_name in catalog_text, (
        f"Tag-45 alert {alert_name} not mentioned in "
        f"notify-catalog; drift between YAML and Markdown"
    )


def test_catalog_references_henrik_pre_mortem_anchor(
    catalog_text: str,
):
    assert "phase-3-marathon-pre-mortem-2026-05-18.md" in catalog_text
    assert "Henrik" in catalog_text
    assert "Tag-44" in catalog_text


def test_catalog_references_all_notify_receivers(catalog_text: str):
    # The receiver inventory must list every receiver actually
    # used in the YAML alert rules. Extract the receivers from
    # the YAML notify_path annotations.
    alerts = yaml.safe_load(_ALERTS_PATH.read_text())
    used_receivers: set[str] = set()
    for g in alerts["groups"]:
        for r in g["rules"]:
            np = r.get("annotations", {}).get("notify_path", "")
            for chunk in np.split("+"):
                chunk = chunk.strip()
                if chunk:
                    used_receivers.add(chunk)
    # Each receiver token must appear in the catalog text.
    for recv in sorted(used_receivers):
        assert recv in catalog_text, (
            f"notify_path receiver {recv!r} used in YAML but not "
            f"documented in catalog"
        )


def test_catalog_lists_uncovered_failure_modes(catalog_text: str):
    # Section 4 enumerates failure-modes intentionally without
    # Tag-45 alert rules. The list must cover all Henrik Tag-44
    # IDs that are NOT in the Tag-45 set.
    covered = {
        spec["failure_mode"].split("+")[0]
        for spec in _TAG45_ALERTS.values()
        if "+" not in spec["failure_mode"]
    }
    # All Henrik Tag-44 IDs (A1..A8, B1..B6, C1..C5, D1..D5).
    all_ids = {
        "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
        "B1", "B2", "B3", "B4", "B5", "B6",
        "C1", "C2", "C3", "C4", "C5",
        "D1", "D2", "D3", "D4", "D5",
    }
    uncovered = all_ids - covered
    for fid in sorted(uncovered):
        # Each uncovered ID must show up somewhere in the catalog
        # (Section 4 table). We do a contains-check tolerant to
        # minor formatting.
        assert fid in catalog_text, (
            f"Failure-mode {fid} not covered by alert AND not "
            f"documented in Section 4 of notify-catalog"
        )
