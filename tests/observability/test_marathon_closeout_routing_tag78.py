# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-78 Marathon-Closeout-
Alert-Routing-Erweiterung (Noa SRE, Continuous-Mode-Marathon-Polish).

Auftrag-Anker
-------------

Tag-78 Noa-Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon-Polish):

Marathon-Closeout-Alert-Routing-Erweiterung. Seven alerts aggregate
the per-welle final-sealing outcomes (Welle-1..7) into THREE
layer-verdicts (Closeout, Final) plus the Phase-3-COMPLETE-Marker-
Fire signal:

  * WakirMarathonCloseoutReady       (info)
  * WakirMarathonCloseoutPartial     (warning)
  * WakirMarathonCloseoutDefect      (page)
  * WakirMarathonFinalIntact         (info)
  * WakirMarathonFinalDrift          (warning)
  * WakirMarathonFinalDefect         (page)
  * WakirPhase3CompleteMarkerFire    (info)

The alerts live in the dedicated ``marathon-closeout-routing``
group in ``dashboards/phase-3-marathon-alerts.yaml`` and carry the
new trinary routing-class family:

  * ``marathon-closeout-info``    -> ntfy:ar-hand-info, activity-log:append
  * ``marathon-closeout-warning`` -> ntfy:ar-hand, activity-log:append
  * ``marathon-closeout-page``    -> pagerduty:sre-oncall, ntfy:ar-hand,
                                     activity-log:append

The bridge ``scripts/observability/alert-rule-to-mira-notify-bridge.py``
ALERT_CATALOG and routing-class tables (VALID_ROUTING_CLASSES,
ROUTING_CLASS_CHANNELS, ROUTING_CLASS_ESCALATION_SECONDS) are
extended to cover the seven new alerts + three routing classes.
Both files are mirrored byte-equal into
``wirelang/specs/protocol-mirror-seed/``.

Scope
-----

* Marathon-closeout alert YAML surface (alert names, severity,
  labels, routing class, expr contract, group cardinality, header
  comment).
* Bridge ALERT_CATALOG entries + routing-class tables.
* Cross-Repo-Mirror byte-equality.
* Cross-Reference consistency (alert name <-> catalog,
  routing class <-> channel set, runbook_url alignment).
* Regression guard: prior Tag-71..75 routing classes preserved;
  Tag-64 trinary shape invariants hold; Tag-50 welle-N groups
  not contaminated by Tag-78 alerts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

ALERTS_PATH = REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
ALERTS_MIRROR_PATH = (
    REPO_ROOT
    / "wirelang"
    / "specs"
    / "protocol-mirror-seed"
    / "dashboards"
    / "phase-3-marathon-alerts.yaml"
)

BRIDGE_PATH = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "alert-rule-to-mira-notify-bridge.py"
)
BRIDGE_MIRROR_PATH = (
    REPO_ROOT
    / "wirelang"
    / "specs"
    / "protocol-mirror-seed"
    / "scripts"
    / "observability"
    / "alert-rule-to-mira-notify-bridge.py"
)


# Tag-78 alert inventory (alert-name -> expected severity).
TAG78_ALERTS: dict[str, str] = {
    "WakirMarathonCloseoutReady": "info",
    "WakirMarathonCloseoutPartial": "warning",
    "WakirMarathonCloseoutDefect": "page",
    "WakirMarathonFinalIntact": "info",
    "WakirMarathonFinalDrift": "warning",
    "WakirMarathonFinalDefect": "page",
    "WakirPhase3CompleteMarkerFire": "info",
}

# Tag-78 alert -> expected routing_class.
TAG78_ROUTING_CLASS: dict[str, str] = {
    "WakirMarathonCloseoutReady": "marathon-closeout-info",
    "WakirMarathonCloseoutPartial": "marathon-closeout-warning",
    "WakirMarathonCloseoutDefect": "marathon-closeout-page",
    "WakirMarathonFinalIntact": "marathon-closeout-info",
    "WakirMarathonFinalDrift": "marathon-closeout-warning",
    "WakirMarathonFinalDefect": "marathon-closeout-page",
    "WakirPhase3CompleteMarkerFire": "marathon-closeout-info",
}

# Tag-78 alert -> expected runbook URL (verbatim).
TAG78_RUNBOOK_URL: dict[str, str] = {
    "WakirMarathonCloseoutReady": (
        "https://wakir-labs.example/runbooks/marathon-closeout-ready"
    ),
    "WakirMarathonCloseoutPartial": (
        "https://wakir-labs.example/runbooks/marathon-closeout-partial"
    ),
    "WakirMarathonCloseoutDefect": (
        "https://wakir-labs.example/runbooks/marathon-closeout-defect"
    ),
    "WakirMarathonFinalIntact": (
        "https://wakir-labs.example/runbooks/marathon-final-intact"
    ),
    "WakirMarathonFinalDrift": (
        "https://wakir-labs.example/runbooks/marathon-final-drift"
    ),
    "WakirMarathonFinalDefect": (
        "https://wakir-labs.example/runbooks/marathon-final-defect"
    ),
    "WakirPhase3CompleteMarkerFire": (
        "https://wakir-labs.example/runbooks/phase-3-complete-marker-fire"
    ),
}

# Channel sets per routing class.
TAG78_CHANNELS: dict[str, tuple[str, ...]] = {
    "marathon-closeout-info": (
        "ntfy:ar-hand-info",
        "activity-log:append",
    ),
    "marathon-closeout-warning": (
        "ntfy:ar-hand",
        "activity-log:append",
    ),
    "marathon-closeout-page": (
        "pagerduty:sre-oncall",
        "ntfy:ar-hand",
        "activity-log:append",
    ),
}

# Escalation seconds per routing class.
TAG78_ESCALATION_SECONDS: dict[str, int] = {
    "marathon-closeout-info": 0,
    "marathon-closeout-warning": 0,
    "marathon-closeout-page": 600,
}


# ---------------------------------------------------------------
# Fixtures: load the artefacts once.
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def alerts_text() -> str:
    return ALERTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_mirror_text() -> str:
    return ALERTS_MIRROR_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_doc() -> dict:
    return yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bridge_module():
    spec = importlib.util.spec_from_file_location(
        "bridge_tag78", str(BRIDGE_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bridge_text() -> str:
    return BRIDGE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bridge_mirror_text() -> str:
    return BRIDGE_MIRROR_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# Section 1: Marathon-Closeout alert YAML surface.
# ---------------------------------------------------------------


def test_all_seven_tag78_alerts_present_in_yaml(alerts_text: str) -> None:
    """All seven Tag-78 alerts are appended to the alerts YAML."""
    for name in TAG78_ALERTS:
        assert name in alerts_text, (
            f"Tag-78 marathon-closeout alert {name} missing from YAML"
        )


def test_tag78_alerts_live_in_marathon_closeout_group(
    alerts_doc: dict,
) -> None:
    """All seven alerts must live in the dedicated
    ``marathon-closeout-routing`` group (NOT in any welle-N group
    and NOT split across multiple groups). Cardinality pinned at 7.
    """
    groups = [
        g for g in alerts_doc["groups"]
        if g["name"] == "marathon-closeout-routing"
    ]
    assert len(groups) == 1, (
        "expected exactly one marathon-closeout-routing group; got "
        f"{len(groups)}"
    )
    rule_names = {r["alert"] for r in groups[0]["rules"]}
    assert rule_names == set(TAG78_ALERTS), (
        f"marathon-closeout-routing rule-set drift: "
        f"missing={sorted(set(TAG78_ALERTS) - rule_names)} "
        f"extra={sorted(rule_names - set(TAG78_ALERTS))}"
    )
    assert len(groups[0]["rules"]) == 7
    assert groups[0]["interval"] == "30s"


@pytest.mark.parametrize(
    "alert_name,expected_severity", sorted(TAG78_ALERTS.items())
)
def test_tag78_alert_severity_and_canonical_labels(
    alerts_doc: dict, alert_name: str, expected_severity: str
) -> None:
    """Each Tag-78 alert carries the expected severity AND the
    canonical Tag-78 labels (tag, owner, team, mitigation, phase).
    """
    rule = _find_rule(alerts_doc, alert_name)
    labels = rule["labels"]
    assert labels["severity"] == expected_severity, (
        f"{alert_name} severity drift: expected={expected_severity} "
        f"got={labels.get('severity')}"
    )
    assert labels["tag"] == "tag-78"
    assert labels["owner"] == "noa-sre"
    assert labels["team"] == "sre"
    assert labels["phase"] == "phase-3-marathon"
    assert labels["mitigation"] == "marathon-closeout-routing-extension"
    assert labels["adr"] == "adr-0066"


@pytest.mark.parametrize(
    "alert_name,expected_rc", sorted(TAG78_ROUTING_CLASS.items())
)
def test_tag78_alert_routing_class(
    alerts_doc: dict, alert_name: str, expected_rc: str
) -> None:
    """Each Tag-78 alert carries the expected routing_class label
    (trinary family marathon-closeout-{info,warning,page}).
    """
    rule = _find_rule(alerts_doc, alert_name)
    assert rule["labels"]["routing_class"] == expected_rc, (
        f"{alert_name} routing_class drift: expected={expected_rc} "
        f"got={rule['labels'].get('routing_class')}"
    )


def test_closeout_verdict_alerts_use_closeout_class_metric(
    alerts_doc: dict,
) -> None:
    """The three Closeout-Verdict alerts (Ready/Partial/Defect) fire
    on the ``wakir_marathon_closeout_verdict_class`` recording rule
    with integer-encoded class values 0/1/2 (mutual-exclusion).
    """
    for name, expected_class in (
        ("WakirMarathonCloseoutReady", "== 0"),
        ("WakirMarathonCloseoutPartial", "== 1"),
        ("WakirMarathonCloseoutDefect", "== 2"),
    ):
        rule = _find_rule(alerts_doc, name)
        expr = rule["expr"]
        assert "wakir_marathon_closeout_verdict_class" in expr, (
            f"{name} must fire on wakir_marathon_closeout_verdict_class; "
            f"got expr={expr!r}"
        )
        assert expected_class in expr, (
            f"{name} expr must contain '{expected_class}'; got {expr!r}"
        )


def test_final_verdict_alerts_use_final_class_metric(
    alerts_doc: dict,
) -> None:
    """The three Final-Verdict alerts (Intact/Drift/Defect) fire on
    the ``wakir_marathon_final_verdict_class`` recording rule with
    integer-encoded class values 0/1/2.
    """
    for name, expected_class in (
        ("WakirMarathonFinalIntact", "== 0"),
        ("WakirMarathonFinalDrift", "== 1"),
        ("WakirMarathonFinalDefect", "== 2"),
    ):
        rule = _find_rule(alerts_doc, name)
        expr = rule["expr"]
        assert "wakir_marathon_final_verdict_class" in expr, (
            f"{name} must fire on wakir_marathon_final_verdict_class; "
            f"got expr={expr!r}"
        )
        assert expected_class in expr


def test_complete_marker_fire_expr_uses_marker_fire_gauge(
    alerts_doc: dict,
) -> None:
    """The Phase-3-COMPLETE-Marker-Fire alert fires on the level
    metric ``wakir_phase_3_complete_marker_fire == 1`` (boolean-
    style; latched once the marker is emitted).
    """
    rule = _find_rule(alerts_doc, "WakirPhase3CompleteMarkerFire")
    expr = rule["expr"]
    assert "wakir_phase_3_complete_marker_fire" in expr
    assert "== 1" in expr


def test_closeout_layer_labels_consistent(alerts_doc: dict) -> None:
    """All three Closeout-Verdict alerts carry layer=marathon-closeout;
    all three Final-Verdict alerts carry layer=marathon-final; the
    Marker-Fire alert carries layer=phase-3-complete-marker.
    """
    closeout_layer = "marathon-closeout"
    final_layer = "marathon-final"
    marker_layer = "phase-3-complete-marker"
    for name in (
        "WakirMarathonCloseoutReady",
        "WakirMarathonCloseoutPartial",
        "WakirMarathonCloseoutDefect",
    ):
        assert _find_rule(alerts_doc, name)["labels"]["layer"] == (
            closeout_layer
        )
    for name in (
        "WakirMarathonFinalIntact",
        "WakirMarathonFinalDrift",
        "WakirMarathonFinalDefect",
    ):
        assert _find_rule(alerts_doc, name)["labels"]["layer"] == (
            final_layer
        )
    assert _find_rule(
        alerts_doc, "WakirPhase3CompleteMarkerFire"
    )["labels"]["layer"] == marker_layer


def test_verdict_class_labels_pinned(alerts_doc: dict) -> None:
    """Each verdict-class alert carries an explicit verdict_class
    label that matches the alert-name discriminator. Mutual-
    exclusion contract surface for the route-tree.
    """
    expected_verdict_class = {
        "WakirMarathonCloseoutReady": "ready",
        "WakirMarathonCloseoutPartial": "partial",
        "WakirMarathonCloseoutDefect": "defect",
        "WakirMarathonFinalIntact": "intact",
        "WakirMarathonFinalDrift": "drift",
        "WakirMarathonFinalDefect": "defect",
    }
    for name, vclass in expected_verdict_class.items():
        rule = _find_rule(alerts_doc, name)
        assert rule["labels"]["verdict_class"] == vclass, (
            f"{name} verdict_class drift: expected={vclass} "
            f"got={rule['labels'].get('verdict_class')}"
        )


def test_marker_fire_carries_marker_event_discriminator(
    alerts_doc: dict,
) -> None:
    """Phase-3-COMPLETE-Marker-Fire carries ``marker_event=marker-fire``
    discriminator (distinct from the existing
    WakirPhase3CompleteMarkerFalsePositive alert which surfaces
    drift, not the emit-positive event).
    """
    rule = _find_rule(alerts_doc, "WakirPhase3CompleteMarkerFire")
    assert rule["labels"]["marker_event"] == "marker-fire"


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_tag78_alert_for_window(
    alerts_doc: dict, alert_name: str
) -> None:
    """All Tag-78 alerts carry a 2m ``for:`` window to tolerate a
    single Prometheus scrape gap (~15s) without false-positives on
    transient state-flips at verdict-publication time.
    """
    rule = _find_rule(alerts_doc, alert_name)
    assert rule["for"] == "2m", (
        f"{alert_name} for-window drift: expected 2m, got {rule['for']}"
    )


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_tag78_alert_runbook_url(
    alerts_doc: dict, alert_name: str
) -> None:
    """Each alert declares the expected runbook_url annotation."""
    rule = _find_rule(alerts_doc, alert_name)
    assert rule["annotations"]["runbook_url"] == (
        TAG78_RUNBOOK_URL[alert_name]
    ), (
        f"{alert_name} runbook_url drift: expected="
        f"{TAG78_RUNBOOK_URL[alert_name]!r} got="
        f"{rule['annotations'].get('runbook_url')!r}"
    )


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_tag78_alert_notify_path_matches_severity(
    alerts_doc: dict, alert_name: str
) -> None:
    """The notify_path annotation must reflect the severity:
    * info -> ntfy:ar-hand-info + activity-log:append (no page).
    * warning -> ntfy:ar-hand + activity-log:append (no page).
    * page -> pagerduty + ntfy:ar-hand + activity-log:append.
    """
    rule = _find_rule(alerts_doc, alert_name)
    sev = rule["labels"]["severity"]
    notify = rule["annotations"]["notify_path"]
    if sev == "info":
        assert "ntfy:ar-hand-info" in notify
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify, (
            f"info alert {alert_name} must NOT page on-call"
        )
    elif sev == "warning":
        assert "ntfy:ar-hand" in notify
        assert "ntfy:ar-hand-info" not in notify, (
            f"warning alert {alert_name} uses ntfy:ar-hand, NOT "
            f"ntfy:ar-hand-info"
        )
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify
    elif sev == "page":
        assert "pagerduty:sre-oncall" in notify
        assert "ntfy:ar-hand" in notify
        assert "activity-log:append" in notify


def test_tag78_header_comment_present(alerts_text: str) -> None:
    """A Tag-78 header comment anchors the new block for grep-
    discoverability and audit-trail reading.
    """
    assert (
        "Tag-78 Marathon-Closeout-Alert-Routing-Erweiterung"
        in alerts_text
    )


# ---------------------------------------------------------------
# Section 2: Bridge ALERT_CATALOG + routing-class table.
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "alert_name,expected_severity", sorted(TAG78_ALERTS.items())
)
def test_bridge_catalog_has_each_tag78_alert(
    bridge_module, alert_name: str, expected_severity: str
) -> None:
    """Each Tag-78 alert is catalogued in ALERT_CATALOG with the
    correct severity + runbook_url.
    """
    cat = bridge_module.ALERT_CATALOG
    assert alert_name in cat, (
        f"Tag-78 alert {alert_name} missing from ALERT_CATALOG"
    )
    entry = cat[alert_name]
    assert entry["severity"] == expected_severity
    assert entry["runbook_url"] == TAG78_RUNBOOK_URL[alert_name]


def test_bridge_new_routing_classes_registered(bridge_module) -> None:
    """The three Tag-78 routing classes must be in
    VALID_ROUTING_CLASSES, ROUTING_CLASS_CHANNELS, and
    ROUTING_CLASS_ESCALATION_SECONDS. Shape invariants hold.
    """
    for rc in (
        "marathon-closeout-info",
        "marathon-closeout-warning",
        "marathon-closeout-page",
    ):
        assert rc in bridge_module.VALID_ROUTING_CLASSES, (
            f"routing_class {rc} missing from VALID_ROUTING_CLASSES"
        )
        assert rc in bridge_module.ROUTING_CLASS_CHANNELS, (
            f"routing_class {rc} missing from ROUTING_CLASS_CHANNELS"
        )
        assert rc in bridge_module.ROUTING_CLASS_ESCALATION_SECONDS, (
            f"routing_class {rc} missing from "
            f"ROUTING_CLASS_ESCALATION_SECONDS"
        )


@pytest.mark.parametrize(
    "routing_class,expected_channels", sorted(TAG78_CHANNELS.items())
)
def test_bridge_routing_class_channels(
    bridge_module, routing_class: str, expected_channels: tuple[str, ...]
) -> None:
    """The channel-tuple for each Tag-78 routing class matches the
    expected (deterministic, ordered) channel-set.
    """
    actual = bridge_module.ROUTING_CLASS_CHANNELS[routing_class]
    assert actual == expected_channels, (
        f"routing_class {routing_class} channel drift: "
        f"expected={expected_channels} got={actual}"
    )


@pytest.mark.parametrize(
    "routing_class,expected_seconds",
    sorted(TAG78_ESCALATION_SECONDS.items()),
)
def test_bridge_routing_class_escalation_seconds(
    bridge_module, routing_class: str, expected_seconds: int
) -> None:
    """The escalation-seconds pin: info/warning = 0, page = 600s."""
    actual = bridge_module.ROUTING_CLASS_ESCALATION_SECONDS[routing_class]
    assert actual == expected_seconds, (
        f"routing_class {routing_class} escalation drift: "
        f"expected={expected_seconds} got={actual}"
    )


def test_bridge_lookup_helpers_for_tag78_classes(bridge_module) -> None:
    """The lookup_* helpers return the correct values for the
    three Tag-78 routing classes.
    """
    assert bridge_module.lookup_routing_class_channels(
        "marathon-closeout-info"
    ) == ("ntfy:ar-hand-info", "activity-log:append")
    assert bridge_module.lookup_routing_class_channels(
        "marathon-closeout-warning"
    ) == ("ntfy:ar-hand", "activity-log:append")
    assert bridge_module.lookup_routing_class_channels(
        "marathon-closeout-page"
    ) == ("pagerduty:sre-oncall", "ntfy:ar-hand", "activity-log:append")
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "marathon-closeout-info"
        )
        == 0
    )
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "marathon-closeout-warning"
        )
        == 0
    )
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "marathon-closeout-page"
        )
        == 600
    )


def test_bridge_trinary_shape_still_ok(bridge_module) -> None:
    """Adding the Tag-78 routing classes must NOT break the
    Tag-64 trinary routing-table shape invariants.
    """
    shape = bridge_module.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


def test_bridge_prior_routing_classes_still_registered(
    bridge_module,
) -> None:
    """Regression guard: Tag-78 addition must NOT remove the
    Tag-64 trinary or Tag-71/72/73/74/75 per-welle routing classes.
    """
    for rc in (
        "standard",
        "ops-on-call",
        "ops-on-call-plus-management",
        "welle-3-pre-auditor-info",
        "welle-4-state-backing-info",
        "welle-5-capability-token-info",
        "welle-6-subscribe-loop-info",
        "welle-7-final-sealing-info",
    ):
        assert rc in bridge_module.VALID_ROUTING_CLASSES, (
            f"prior routing_class {rc} dropped from VALID_ROUTING_CLASSES"
        )
        assert rc in bridge_module.ROUTING_CLASS_CHANNELS
        assert rc in bridge_module.ROUTING_CLASS_ESCALATION_SECONDS


def test_bridge_lookup_catalog_returns_independent_copy(
    bridge_module,
) -> None:
    """lookup_catalog() must return a copy of each Tag-78 catalog
    entry (mutation must not leak back into ALERT_CATALOG).
    """
    e = bridge_module.lookup_catalog("WakirMarathonCloseoutDefect")
    assert e is not None
    assert e["severity"] == "page"
    e["severity"] = "MUTATED"
    assert (
        bridge_module.ALERT_CATALOG["WakirMarathonCloseoutDefect"][
            "severity"
        ]
        == "page"
    )


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_failure_mode_id_tag78_prefix(
    bridge_module, alert_name: str
) -> None:
    """Each Tag-78 catalog entry carries a failure_mode_id prefixed
    with ``Tag-78-`` for audit-trail grep-ability.
    """
    fmi = bridge_module.ALERT_CATALOG[alert_name]["failure_mode_id"]
    assert fmi is not None, (
        f"{alert_name} missing failure_mode_id in catalog"
    )
    assert fmi.startswith("Tag-78-"), (
        f"{alert_name} failure_mode_id={fmi!r} missing Tag-78- prefix"
    )


# ---------------------------------------------------------------
# Section 3: Cross-Repo-Mirror byte-equality.
# ---------------------------------------------------------------


def test_alerts_mirror_byte_equal(
    alerts_text: str, alerts_mirror_text: str
) -> None:
    """The protocol-mirror-seed alerts copy is byte-equal."""
    assert alerts_text == alerts_mirror_text, (
        "alerts mirror drifted from primary; Tag-78 cross-repo "
        "invariant broken"
    )


def test_bridge_mirror_byte_equal(
    bridge_text: str, bridge_mirror_text: str
) -> None:
    """The protocol-mirror-seed bridge copy is byte-equal."""
    assert bridge_text == bridge_mirror_text, (
        "bridge mirror drifted from primary; Tag-78 cross-repo "
        "invariant broken"
    )


# ---------------------------------------------------------------
# Section 4: Cross-Reference checks (YAML <-> bridge).
# ---------------------------------------------------------------


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_alert_yaml_and_catalog_share_alert_names(
    alerts_text: str, bridge_module, alert_name: str
) -> None:
    """Each alertname appears in both the YAML and the bridge
    catalog with the same spelling.
    """
    assert alert_name in alerts_text
    assert alert_name in bridge_module.ALERT_CATALOG


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_alert_yaml_and_catalog_share_runbook_url(
    alerts_doc: dict, bridge_module, alert_name: str
) -> None:
    """runbook_url in the YAML annotations must match the bridge
    catalog runbook_url verbatim.
    """
    rule = _find_rule(alerts_doc, alert_name)
    yaml_url = rule["annotations"]["runbook_url"]
    catalog_url = bridge_module.ALERT_CATALOG[alert_name]["runbook_url"]
    assert yaml_url == catalog_url, (
        f"runbook_url drift for {alert_name}: YAML={yaml_url} "
        f"catalog={catalog_url}"
    )


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_alert_yaml_routing_class_matches_bridge_table(
    alerts_doc: dict, bridge_module, alert_name: str
) -> None:
    """The routing_class label in the YAML is a registered class in
    the bridge ROUTING_CLASS_CHANNELS table.
    """
    rule = _find_rule(alerts_doc, alert_name)
    rc = rule["labels"]["routing_class"]
    assert rc in bridge_module.ROUTING_CLASS_CHANNELS, (
        f"alert {alert_name} routing_class={rc} not in bridge table"
    )
    assert rc in bridge_module.VALID_ROUTING_CLASSES


@pytest.mark.parametrize("alert_name", sorted(TAG78_ALERTS))
def test_alert_yaml_severity_matches_bridge_catalog(
    alerts_doc: dict, bridge_module, alert_name: str
) -> None:
    """The severity label in the YAML must match the bridge catalog
    severity entry verbatim.
    """
    rule = _find_rule(alerts_doc, alert_name)
    yaml_sev = rule["labels"]["severity"]
    catalog_sev = bridge_module.ALERT_CATALOG[alert_name]["severity"]
    assert yaml_sev == catalog_sev, (
        f"severity drift for {alert_name}: YAML={yaml_sev} "
        f"catalog={catalog_sev}"
    )


def test_tag78_alerts_map_to_event_kwargs_with_info_channels(
    bridge_module,
) -> None:
    """End-to-end: an AlertManager v4 alert dict carrying a Tag-78
    info-class routing label produces ``map_alert_to_event_kwargs``
    output that pins the Tag-78 info channel-set + zero escalation.
    """
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "WakirMarathonCloseoutReady",
            "severity": "info",
            "layer": "marathon-closeout",
            "verdict_class": "ready",
            "routing_class": "marathon-closeout-info",
            "tag": "tag-78",
        },
        "annotations": {
            "summary": "Marathon-Closeout verdict: READY",
            "runbook_url": (
                "https://wakir-labs.example/runbooks/"
                "marathon-closeout-ready"
            ),
        },
        "startsAt": "2026-05-19T18:00:00Z",
    }
    kwargs = bridge_module.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    assert kwargs["alert_name"] == "WakirMarathonCloseoutReady"
    assert kwargs["severity"] == "info"
    assert kwargs["failure_mode_id"] == "Tag-78-MarathonCloseout-Ready"
    labels = kwargs["labels"]
    assert (
        labels["notify_channels"]
        == "ntfy:ar-hand-info,activity-log:append"
    )
    assert labels["escalation_after_seconds"] == "0"


def test_tag78_page_class_maps_to_pagerduty_channel_set(
    bridge_module,
) -> None:
    """Closeout-Defect carries the page-class routing; the bridge
    must emit the pagerduty:sre-oncall + ntfy:ar-hand +
    activity-log:append channel-tuple and a 600s escalation.
    """
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "WakirMarathonCloseoutDefect",
            "severity": "page",
            "layer": "marathon-closeout",
            "verdict_class": "defect",
            "routing_class": "marathon-closeout-page",
            "tag": "tag-78",
        },
        "annotations": {
            "summary": "Marathon-Closeout verdict: DEFECT",
            "runbook_url": (
                "https://wakir-labs.example/runbooks/"
                "marathon-closeout-defect"
            ),
        },
        "startsAt": "2026-05-19T18:00:00Z",
    }
    kwargs = bridge_module.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    assert kwargs["severity"] == "page"
    labels = kwargs["labels"]
    assert labels["notify_channels"] == (
        "pagerduty:sre-oncall,ntfy:ar-hand,activity-log:append"
    )
    assert labels["escalation_after_seconds"] == "600"


def test_tag78_warning_class_maps_to_ntfy_arhand_no_pager(
    bridge_module,
) -> None:
    """Closeout-Partial carries the warning-class routing; the
    bridge must emit ntfy:ar-hand + activity-log:append (no
    pagerduty, no info topic).
    """
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "WakirMarathonCloseoutPartial",
            "severity": "warning",
            "layer": "marathon-closeout",
            "verdict_class": "partial",
            "routing_class": "marathon-closeout-warning",
            "tag": "tag-78",
        },
        "annotations": {
            "summary": "Marathon-Closeout verdict: PARTIAL",
            "runbook_url": (
                "https://wakir-labs.example/runbooks/"
                "marathon-closeout-partial"
            ),
        },
        "startsAt": "2026-05-19T18:00:00Z",
    }
    kwargs = bridge_module.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    assert kwargs["severity"] == "warning"
    labels = kwargs["labels"]
    assert labels["notify_channels"] == (
        "ntfy:ar-hand,activity-log:append"
    )
    assert "pagerduty" not in labels["notify_channels"]
    assert "ar-hand-info" not in labels["notify_channels"]
    assert labels["escalation_after_seconds"] == "0"


# ---------------------------------------------------------------
# Section 5: Regression guards (cross-layer separation).
# ---------------------------------------------------------------


def test_tag78_alerts_not_in_welle_n_groups(alerts_doc: dict) -> None:
    """Hard separation: Tag-78 layer-verdict alerts must NOT appear
    in any of the per-welle ``welle-N-alerts`` groups. Cross-layer-
    contamination would corrupt the Tag-50 + Tag-7X cardinality
    contract pinned in tests/ci/test_welle_n_specific_alerts.py.
    """
    welle_group_names = {
        f"welle-{n}-alerts" for n in range(1, 8)
    }
    for group in alerts_doc["groups"]:
        if group["name"] in welle_group_names:
            for rule in group["rules"]:
                assert rule["alert"] not in TAG78_ALERTS, (
                    f"Tag-78 alert {rule['alert']} leaked into "
                    f"{group['name']} (cross-layer-contamination)"
                )


def test_existing_complete_marker_false_positive_alert_preserved(
    alerts_doc: dict,
) -> None:
    """Regression guard: the Tag-40 baseline
    WakirPhase3CompleteMarkerFalsePositive (page-severity drift
    alert) must remain in the YAML. The new
    WakirPhase3CompleteMarkerFire (info-severity positive alert) is
    its positive-confirmation counterpart, NOT a replacement.
    """
    drift = _find_rule(
        alerts_doc, "WakirPhase3CompleteMarkerFalsePositive"
    )
    fire = _find_rule(alerts_doc, "WakirPhase3CompleteMarkerFire")
    assert drift["labels"]["severity"] == "page"
    assert fire["labels"]["severity"] == "info"
    # They MUST live in different groups so the route-tree can fan
    # out independently.
    drift_group = _find_group_for_alert(
        alerts_doc, "WakirPhase3CompleteMarkerFalsePositive"
    )
    fire_group = _find_group_for_alert(
        alerts_doc, "WakirPhase3CompleteMarkerFire"
    )
    assert drift_group != fire_group, (
        "marker false-positive (drift) and marker fire (positive) "
        "must NOT share a group; route-tree fan-out invariant"
    )
    assert fire_group == "marathon-closeout-routing"


def test_tag78_pin_set_in_welle_n_test_file() -> None:
    """The Tag-78 anti-regression pin-set
    ``_TAG78_MARATHON_CLOSEOUT_ALERTS`` MUST be declared in
    tests/ci/test_welle_n_specific_alerts.py (Noa-Tag-76-Lehre:
    extensions pinned at the source).
    """
    pin_file = REPO_ROOT / "tests" / "ci" / "test_welle_n_specific_alerts.py"
    text = pin_file.read_text(encoding="utf-8")
    assert "_TAG78_MARATHON_CLOSEOUT_ALERTS" in text, (
        "Tag-78 pin-set missing from test_welle_n_specific_alerts.py; "
        "Noa-Tag-76-Lehre violation"
    )
    for name in TAG78_ALERTS:
        assert name in text, (
            f"Tag-78 alert {name} missing from pin-set in "
            f"test_welle_n_specific_alerts.py"
        )


# ---------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------


def _find_rule(alerts_doc: dict, alert_name: str) -> dict:
    """Return the rule dict for the alert with the given name."""
    for group in alerts_doc["groups"]:
        for rule in group["rules"]:
            if rule.get("alert") == alert_name:
                return rule
    raise AssertionError(
        f"alert {alert_name} not found in dashboards/"
        f"phase-3-marathon-alerts.yaml"
    )


def _find_group_for_alert(alerts_doc: dict, alert_name: str) -> str:
    """Return the group-name containing the alert."""
    for group in alerts_doc["groups"]:
        for rule in group["rules"]:
            if rule.get("alert") == alert_name:
                return group["name"]
    raise AssertionError(
        f"alert {alert_name} not found in any group"
    )
