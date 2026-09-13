# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-75 Welle-7
Final-Sealing-Alert-Routing-Erweiterung (Noa SRE, Continuous-
Mode-Marathon).

Auftrag-Anker
-------------

Tag-75 Noa Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):

Welle-7 Final-Sealing-Alert-Routing-Erweiterung. Two additional
Welle-7 alarms close the Welle-7 final-sealing positive-
confirmation + Pre-Auditor-Signal routing gap surfaced during
the Tag-74 stability-window review (Welle-7 is the terminal
welle in the KW-27 doppel-cutover sequence; sealing-handshake
state needs an explicit positive surface):

  * WakirPhase3Welle7FinalSealingComplete   (info)
  * WakirPhase3Welle7PreAuditorSignalReceived   (info)

Both alerts are appended to the existing ``welle-7-alerts``
group in ``dashboards/phase-3-marathon-alerts.yaml`` and carry
the new routing class ``welle-7-final-sealing-info``. The
bridge ``scripts/observability/alert-rule-to-mira-notify-bridge.py``
ALERT_CATALOG and ROUTING_CLASS_CHANNELS table are extended to
cover the new alerts + routing class. Both files are mirrored
byte-equal into ``wirelang/specs/protocol-mirror-seed/``.

Scope
-----

* Welle-7 alert YAML surface (alert names, severity, labels,
  routing class, expr contract).
* Bridge ALERT_CATALOG entries + routing-class table.
* Cross-Repo-Mirror byte-equality.
* Cross-Reference consistency (alert name <-> catalog,
  routing class <-> channel set, runbook_url alignment).
* Regression guard: prior Tag-71/72/73/74 routing classes
  preserved.
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
        "bridge_tag75", str(BRIDGE_PATH)
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
# Section 1: Welle-7 alert YAML surface.
# ---------------------------------------------------------------


def test_both_tag75_alerts_present_in_yaml(alerts_text: str) -> None:
    """The two Tag-75 alerts are appended to the alerts YAML."""
    assert "WakirPhase3Welle7FinalSealingComplete" in alerts_text
    assert "WakirPhase3Welle7PreAuditorSignalReceived" in alerts_text


def test_tag75_alerts_live_in_welle_7_group(alerts_doc: dict) -> None:
    """Both alerts must be in the existing ``welle-7-alerts``
    group, not in a new top-level group. This keeps the Welle-7
    final-sealing observability surface contiguous and grep-
    discoverable. Both Tag-75 alerts must come AFTER the pre-
    existing Welle-7 page-level alerts (append, not prepend).
    """
    welle_7_groups = [
        g for g in alerts_doc["groups"] if g["name"] == "welle-7-alerts"
    ]
    assert len(welle_7_groups) == 1, (
        "expected exactly one welle-7-alerts group"
    )
    rule_names = [r["alert"] for r in welle_7_groups[0]["rules"]]
    assert "WakirPhase3Welle7FinalSealingComplete" in rule_names
    assert "WakirPhase3Welle7PreAuditorSignalReceived" in rule_names
    idx_divergence = rule_names.index(
        "WakirWelle7RecoveryReplayDivergence"
    )
    idx_complete = rule_names.index(
        "WakirPhase3Welle7FinalSealingComplete"
    )
    idx_signal = rule_names.index(
        "WakirPhase3Welle7PreAuditorSignalReceived"
    )
    assert idx_divergence < idx_complete < idx_signal


def test_final_sealing_complete_severity_info_and_labels(
    alerts_doc: dict,
) -> None:
    """The FinalSealingComplete alert must be severity=info with
    the canonical Tag-75 Welle-7 labels.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle7FinalSealingComplete"
    )
    labels = rule["labels"]
    assert labels["severity"] == "info"
    assert labels["welle"] == "welle-7"
    assert labels["component"] == "final_sealing"
    assert labels["routing_class"] == "welle-7-final-sealing-info"
    assert labels["tag"] == "tag-75"
    assert labels["owner"] == "noa-sre"
    assert labels["team"] == "sre"
    assert labels["topology"] == "doppel"
    assert labels["kw_week"] == "kw-27"


def test_pre_auditor_signal_severity_info_and_labels(
    alerts_doc: dict,
) -> None:
    """The PreAuditorSignalReceived alert must be severity=info
    with the canonical Tag-75 labels plus the ``signal_path:
    external-pre-auditor-designation-received`` discriminator.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle7PreAuditorSignalReceived"
    )
    labels = rule["labels"]
    assert labels["severity"] == "info"
    assert labels["welle"] == "welle-7"
    assert labels["component"] == "final_sealing"
    assert labels["routing_class"] == "welle-7-final-sealing-info"
    assert labels["tag"] == "tag-75"
    assert (
        labels["signal_path"]
        == "external-pre-auditor-designation-received"
    )
    assert labels["owner"] == "noa-sre"


def test_final_sealing_complete_expr_contract(alerts_doc: dict) -> None:
    """The FinalSealingComplete expr must require ALL six prior
    welle Schluss-Audit-Signoffs (welles 1..6) AND Welle-7 signoff
    carrying ``auditor="external-pre-auditor"``. Mutual exclusion
    with the existing IIA-1130 Henrik-default warning is enforced
    by the auditor discriminator.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle7FinalSealingComplete"
    )
    expr = rule["expr"]
    for wk in ("welle-1", "welle-2", "welle-3",
               "welle-4", "welle-5", "welle-6"):
        assert (
            f'wakir_welle_schluss_audit_signoff{{welle="{wk}"}} == 1'
            in expr
        ), f"final-sealing expr missing prior signoff for {wk}"
    assert (
        'wakir_welle_schluss_audit_signoff{welle="welle-7", '
        'auditor="external-pre-auditor"} == 1'
    ) in expr


def test_pre_auditor_signal_expr_uses_designation_gauge(
    alerts_doc: dict,
) -> None:
    """The PreAuditorSignalReceived expr must use the canonical
    Pre-Auditor designation-received gauge
    ``wakir_welle_pre_auditor_designation_received`` scoped to
    ``welle="welle-7"`` with ``== 1`` (boolean-style level metric).
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle7PreAuditorSignalReceived"
    )
    expr = rule["expr"]
    assert "wakir_welle_pre_auditor_designation_received" in expr
    assert 'welle="welle-7"' in expr
    assert "== 1" in expr


def test_both_alerts_notify_path_is_info_only(alerts_doc: dict) -> None:
    """Both Tag-75 alerts must route to ntfy:ar-hand-info +
    activity-log:append only. No pagerduty, no on-call page.
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        rule = _find_rule(alerts_doc, name)
        notify = rule["annotations"]["notify_path"]
        assert "ntfy:ar-hand-info" in notify
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify, (
            f"info Tag-75 alert {name} must NOT page on-call"
        )


def test_tag75_alerts_carry_runbook_url(alerts_doc: dict) -> None:
    """Both alerts must declare a runbook_url annotation that
    matches the bridge catalog runbook_url.
    """
    rule_complete = _find_rule(
        alerts_doc, "WakirPhase3Welle7FinalSealingComplete"
    )
    rule_signal = _find_rule(
        alerts_doc, "WakirPhase3Welle7PreAuditorSignalReceived"
    )
    assert rule_complete["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-7-final-sealing-complete"
    )
    assert rule_signal["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-7-pre-auditor-signal-received"
    )


def test_tag75_header_comment_present(alerts_text: str) -> None:
    """A Tag-75 header comment anchors the new block for future
    grep-ability and audit-trail reading.
    """
    assert (
        "Tag-75 Welle-7 Final-Sealing-Alert-Routing-Erweiterung"
        in alerts_text
    )


def test_tag75_alerts_carry_for_window(alerts_doc: dict) -> None:
    """Both Tag-75 alerts must declare a 2m ``for:`` window to
    survive a single Prometheus scrape gap (~15s) without
    false-positives on transient state-flips.
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        rule = _find_rule(alerts_doc, name)
        assert rule["for"] == "2m", (
            f"alert {name} for-window drift: expected 2m, "
            f"got {rule['for']}"
        )


# ---------------------------------------------------------------
# Section 2: Bridge ALERT_CATALOG + routing-class table.
# ---------------------------------------------------------------


def test_bridge_catalog_has_both_tag75_alerts(bridge_module) -> None:
    """Both Tag-75 alerts must be catalogued in ALERT_CATALOG
    with the correct severity + runbook_url.
    """
    cat = bridge_module.ALERT_CATALOG
    assert "WakirPhase3Welle7FinalSealingComplete" in cat
    assert "WakirPhase3Welle7PreAuditorSignalReceived" in cat
    assert (
        cat["WakirPhase3Welle7FinalSealingComplete"]["severity"]
        == "info"
    )
    assert (
        cat["WakirPhase3Welle7PreAuditorSignalReceived"]["severity"]
        == "info"
    )
    assert (
        cat["WakirPhase3Welle7FinalSealingComplete"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-7-final-sealing-complete"
    )
    assert (
        cat["WakirPhase3Welle7PreAuditorSignalReceived"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-7-pre-auditor-signal-received"
    )


def test_bridge_new_routing_class_registered(bridge_module) -> None:
    """The ``welle-7-final-sealing-info`` routing class must be
    in VALID_ROUTING_CLASSES, ROUTING_CLASS_CHANNELS, and
    ROUTING_CLASS_ESCALATION_SECONDS. Shape invariants hold.
    """
    rc = "welle-7-final-sealing-info"
    assert rc in bridge_module.VALID_ROUTING_CLASSES
    assert rc in bridge_module.ROUTING_CLASS_CHANNELS
    assert rc in bridge_module.ROUTING_CLASS_ESCALATION_SECONDS
    # Info routing class -- no escalation.
    assert bridge_module.ROUTING_CLASS_ESCALATION_SECONDS[rc] == 0
    channels = bridge_module.ROUTING_CLASS_CHANNELS[rc]
    assert channels == (
        "ntfy:ar-hand-info",
        "activity-log:append",
    )


def test_bridge_routing_class_lookup_helpers(bridge_module) -> None:
    """The lookup_* helpers return the correct values for the
    new Tag-75 routing class.
    """
    assert bridge_module.lookup_routing_class_channels(
        "welle-7-final-sealing-info"
    ) == ("ntfy:ar-hand-info", "activity-log:append")
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "welle-7-final-sealing-info"
        )
        == 0
    )


def test_bridge_trinary_shape_still_ok(bridge_module) -> None:
    """Adding the Tag-75 routing class must NOT break the
    trinary routing-table shape invariants (Tag-64 contract).
    """
    shape = bridge_module.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


def test_bridge_lookup_catalog_returns_tag75_entries(
    bridge_module,
) -> None:
    """lookup_catalog() must return a copy of the catalog entry
    for both Tag-75 alerts (and the copy must be independent of
    the catalog dict).
    """
    e1 = bridge_module.lookup_catalog(
        "WakirPhase3Welle7FinalSealingComplete"
    )
    assert e1 is not None
    assert e1["severity"] == "info"
    e1["severity"] = "MUTATED"
    # Mutation must not leak back into the catalog.
    assert (
        bridge_module.ALERT_CATALOG[
            "WakirPhase3Welle7FinalSealingComplete"
        ]["severity"]
        == "info"
    )
    e2 = bridge_module.lookup_catalog(
        "WakirPhase3Welle7PreAuditorSignalReceived"
    )
    assert e2 is not None
    assert e2["severity"] == "info"


def test_bridge_prior_routing_classes_still_registered(
    bridge_module,
) -> None:
    """Regression guard: Tag-75 addition must NOT remove the
    Tag-71/72/73/74 routing classes.
    """
    for rc in (
        "welle-3-pre-auditor-info",
        "welle-4-state-backing-info",
        "welle-5-capability-token-info",
        "welle-6-subscribe-loop-info",
    ):
        assert rc in bridge_module.VALID_ROUTING_CLASSES
        assert rc in bridge_module.ROUTING_CLASS_CHANNELS
        assert rc in bridge_module.ROUTING_CLASS_ESCALATION_SECONDS


# ---------------------------------------------------------------
# Section 3: Cross-Repo-Mirror byte-equality.
# ---------------------------------------------------------------


def test_alerts_mirror_byte_equal(
    alerts_text: str, alerts_mirror_text: str
) -> None:
    """The protocol-mirror-seed alerts copy is byte-equal."""
    assert alerts_text == alerts_mirror_text, (
        "alerts mirror drifted from primary; Tag-75 cross-repo "
        "invariant broken"
    )


def test_bridge_mirror_byte_equal(
    bridge_text: str, bridge_mirror_text: str
) -> None:
    """The protocol-mirror-seed bridge copy is byte-equal."""
    assert bridge_text == bridge_mirror_text, (
        "bridge mirror drifted from primary; Tag-75 cross-repo "
        "invariant broken"
    )


# ---------------------------------------------------------------
# Section 4: Cross-Reference checks (YAML <-> bridge).
# ---------------------------------------------------------------


def test_alert_yaml_and_catalog_share_alert_names(
    alerts_text: str, bridge_module
) -> None:
    """The two alertnames must appear in both the YAML and the
    bridge catalog with the same spelling.
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        assert name in alerts_text
        assert name in bridge_module.ALERT_CATALOG


def test_alert_yaml_and_catalog_share_runbook_url(
    alerts_doc: dict, bridge_module
) -> None:
    """The runbook_url in the YAML annotations must match the
    runbook_url in the bridge catalog. Drift breaks operator
    flow (page -> runbook-link 404).
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        rule = _find_rule(alerts_doc, name)
        yaml_url = rule["annotations"]["runbook_url"]
        catalog_url = bridge_module.ALERT_CATALOG[name]["runbook_url"]
        assert yaml_url == catalog_url, (
            f"runbook_url drift for {name}: YAML={yaml_url} "
            f"catalog={catalog_url}"
        )


def test_alert_yaml_routing_class_matches_bridge_table(
    alerts_doc: dict, bridge_module
) -> None:
    """The routing_class label in the YAML must be a valid
    routing class in the bridge ROUTING_CLASS_CHANNELS table.
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        rule = _find_rule(alerts_doc, name)
        rc = rule["labels"]["routing_class"]
        assert rc in bridge_module.ROUTING_CLASS_CHANNELS, (
            f"alert {name} routing_class={rc} not in bridge table"
        )
        assert rc in bridge_module.VALID_ROUTING_CLASSES


def test_alert_yaml_severity_matches_bridge_catalog(
    alerts_doc: dict, bridge_module
) -> None:
    """The severity label in the YAML must match the bridge
    catalog severity entry verbatim.
    """
    for name in (
        "WakirPhase3Welle7FinalSealingComplete",
        "WakirPhase3Welle7PreAuditorSignalReceived",
    ):
        rule = _find_rule(alerts_doc, name)
        yaml_sev = rule["labels"]["severity"]
        catalog_sev = bridge_module.ALERT_CATALOG[name]["severity"]
        assert yaml_sev == catalog_sev, (
            f"severity drift for {name}: YAML={yaml_sev} "
            f"catalog={catalog_sev}"
        )


def test_failure_mode_id_tag75_prefix(bridge_module) -> None:
    """Both Tag-75 catalog entries must carry a failure_mode_id
    prefixed with ``Tag-75-Welle7-FinalSealing-`` for audit-trail
    grep-ability.
    """
    cat = bridge_module.ALERT_CATALOG
    fmi_complete = cat["WakirPhase3Welle7FinalSealingComplete"][
        "failure_mode_id"
    ]
    fmi_signal = cat["WakirPhase3Welle7PreAuditorSignalReceived"][
        "failure_mode_id"
    ]
    assert fmi_complete.startswith("Tag-75-Welle7-FinalSealing-")
    assert fmi_signal.startswith("Tag-75-Welle7-FinalSealing-")
    assert fmi_complete != fmi_signal


def test_tag75_alerts_map_to_event_kwargs_with_channels(
    bridge_module,
) -> None:
    """End-to-end: an AlertManager v4 alert dict carrying the
    Tag-75 routing class must produce ``map_alert_to_event_kwargs``
    output that pins the Tag-75 channel-set + escalation-deadline
    on the label-passthrough.
    """
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "WakirPhase3Welle7FinalSealingComplete",
            "severity": "info",
            "welle": "welle-7",
            "component": "final_sealing",
            "routing_class": "welle-7-final-sealing-info",
            "tag": "tag-75",
        },
        "annotations": {
            "summary": "Welle-7 final sealing complete",
            "runbook_url": (
                "https://wakir-labs.example/runbooks/"
                "welle-7-final-sealing-complete"
            ),
        },
        "startsAt": "2026-05-19T18:00:00Z",
    }
    kwargs = bridge_module.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    assert (
        kwargs["alert_name"]
        == "WakirPhase3Welle7FinalSealingComplete"
    )
    assert kwargs["severity"] == "info"
    assert (
        kwargs["failure_mode_id"]
        == "Tag-75-Welle7-FinalSealing-Complete"
    )
    labels = kwargs["labels"]
    assert (
        labels["notify_channels"]
        == "ntfy:ar-hand-info,activity-log:append"
    )
    assert labels["escalation_after_seconds"] == "0"


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
