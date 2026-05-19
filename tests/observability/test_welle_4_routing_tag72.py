# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-72 Welle-4
State-Backing-Alert-Routing-Erweiterung (Noa SRE,
Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-72 Noa Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Two additional Welle-4 state-backing alarms close the
positive-confirmation + rollback-Pfad routing gap identified
during the Tag-71 stability-window review:

  * WakirPhase3Welle4StateBackingActive       (info)
  * WakirPhase3Welle4SnapshotRestoreTriggered (warning,
                                              rollback-Pfad)

Both alerts are appended to the existing ``welle-4-alerts``
group in ``dashboards/phase-3-marathon-alerts.yaml`` and carry
the new routing class ``welle-4-state-backing-info``. The
bridge ``scripts/observability/alert-rule-to-mira-notify-bridge.py``
catalog table and ROUTING_CLASS_CHANNELS table are extended to
cover the new alerts + routing class. Both files are mirrored
byte-equal into ``wirelang/specs/protocol-mirror-seed/``.

Scope
-----

* Welle-4 alert YAML surface (alert names, severity, labels,
  routing class, expr contract).
* Bridge ALERT_CATALOG entries + routing-class table.
* Cross-Repo-Mirror byte-equality.
* Cross-Reference consistency (alert name <-> catalog,
  routing class <-> channel set).
"""

from __future__ import annotations

import importlib.util
import re
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
        "bridge_tag72", str(BRIDGE_PATH)
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
# Section 1: Welle-4 alert YAML surface.
# ---------------------------------------------------------------


def test_both_tag72_alerts_present_in_yaml(alerts_text: str) -> None:
    """The two Tag-72 alerts are appended to the alerts YAML."""
    assert "WakirPhase3Welle4StateBackingActive" in alerts_text
    assert "WakirPhase3Welle4SnapshotRestoreTriggered" in alerts_text


def test_tag72_alerts_live_in_welle_4_group(alerts_doc: dict) -> None:
    """Both alerts must be in the existing ``welle-4-alerts``
    group, not in a new top-level group. This keeps the Welle-4
    state-backing observability surface contiguous and
    grep-discoverable.
    """
    welle_4_groups = [
        g for g in alerts_doc["groups"] if g["name"] == "welle-4-alerts"
    ]
    assert len(welle_4_groups) == 1, (
        "expected exactly one welle-4-alerts group"
    )
    rule_names = [r["alert"] for r in welle_4_groups[0]["rules"]]
    assert "WakirPhase3Welle4StateBackingActive" in rule_names
    assert "WakirPhase3Welle4SnapshotRestoreTriggered" in rule_names
    # Both Tag-72 alerts MUST come AFTER the pre-existing Tag-50
    # Welle-4 alerts (append, not prepend).
    idx_state_read_fail = rule_names.index("WakirWelle4StateReadFail")
    idx_active = rule_names.index("WakirPhase3Welle4StateBackingActive")
    idx_restore = rule_names.index(
        "WakirPhase3Welle4SnapshotRestoreTriggered"
    )
    assert idx_state_read_fail < idx_active < idx_restore


def test_state_backing_active_severity_info_and_labels(
    alerts_doc: dict,
) -> None:
    """The Active alert must be severity=info with the
    canonical Tag-72 Welle-4 labels.
    """
    rule = _find_rule(alerts_doc, "WakirPhase3Welle4StateBackingActive")
    labels = rule["labels"]
    assert labels["severity"] == "info"
    assert labels["welle"] == "welle-4"
    assert labels["component"] == "state_backing"
    assert labels["routing_class"] == "welle-4-state-backing-info"
    assert labels["tag"] == "tag-72"
    assert labels["owner"] == "noa-sre"
    assert labels["team"] == "sre"
    assert labels["topology"] == "doppel"
    assert labels["kw_week"] == "kw-26"


def test_snapshot_restore_severity_warning_and_labels(
    alerts_doc: dict,
) -> None:
    """The SnapshotRestore alert must be severity=warning
    (rollback-Pfad, NOT page) with the canonical Tag-72 labels
    plus the ``rollback_path: snapshot-restore`` discriminator.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle4SnapshotRestoreTriggered"
    )
    labels = rule["labels"]
    assert labels["severity"] == "warning"
    assert labels["welle"] == "welle-4"
    assert labels["component"] == "state_backing"
    assert labels["routing_class"] == "welle-4-state-backing-info"
    assert labels["tag"] == "tag-72"
    assert labels["rollback_path"] == "snapshot-restore"
    assert labels["owner"] == "noa-sre"


def test_state_backing_active_expr_contract(alerts_doc: dict) -> None:
    """The Active alert expr must positively match
    migration_complete=1 AND negatively match
    restore_in_progress=1 (mutual exclusion with the
    SnapshotRestore rollback-Pfad).
    """
    rule = _find_rule(alerts_doc, "WakirPhase3Welle4StateBackingActive")
    expr = rule["expr"]
    assert "wakir_welle4_state_backing_migration_complete == 1" in expr
    assert "wakir_welle4_state_backing_restore_in_progress == 0" in expr


def test_snapshot_restore_expr_uses_counter_increase(
    alerts_doc: dict,
) -> None:
    """The SnapshotRestore alert expr must use the canonical
    ``increase(...)[5m]`` form on the counter
    ``wakir_welle4_state_backing_snapshot_restore_total``.
    This is the rollback-Pfad counter exposed by the
    state-backing recovery tooling.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle4SnapshotRestoreTriggered"
    )
    expr = rule["expr"]
    assert (
        "increase(wakir_welle4_state_backing_snapshot_restore_total[5m])"
        in expr
    )
    assert ">= 1" in expr


def test_both_alerts_notify_path_is_info_only(alerts_doc: dict) -> None:
    """Both Tag-72 alerts must route to ntfy:ar-hand-info +
    activity-log:append only. No pagerduty, no on-call page.
    """
    for name in (
        "WakirPhase3Welle4StateBackingActive",
        "WakirPhase3Welle4SnapshotRestoreTriggered",
    ):
        rule = _find_rule(alerts_doc, name)
        notify = rule["annotations"]["notify_path"]
        assert "ntfy:ar-hand-info" in notify
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify, (
            f"info/warning Tag-72 alert {name} must NOT page on-call"
        )


def test_tag72_alerts_carry_runbook_url(alerts_doc: dict) -> None:
    """Both alerts must declare a runbook_url annotation that
    matches the bridge catalog runbook_url.
    """
    rule_active = _find_rule(
        alerts_doc, "WakirPhase3Welle4StateBackingActive"
    )
    rule_restore = _find_rule(
        alerts_doc, "WakirPhase3Welle4SnapshotRestoreTriggered"
    )
    assert rule_active["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/welle-4-state-backing-active"
    )
    assert rule_restore["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-4-snapshot-restore-triggered"
    )


def test_tag72_header_comment_present(alerts_text: str) -> None:
    """A Tag-72 header comment anchors the new block for future
    grep-ability and audit-trail reading.
    """
    assert "Tag-72 Welle-4 State-Backing-Alert-Routing-Erweiterung" in (
        alerts_text
    )


# ---------------------------------------------------------------
# Section 2: Bridge ALERT_CATALOG + routing-class table.
# ---------------------------------------------------------------


def test_bridge_catalog_has_both_tag72_alerts(bridge_module) -> None:
    """Both Tag-72 alerts must be catalogued in ALERT_CATALOG
    with the correct severity + runbook_url.
    """
    cat = bridge_module.ALERT_CATALOG
    assert "WakirPhase3Welle4StateBackingActive" in cat
    assert "WakirPhase3Welle4SnapshotRestoreTriggered" in cat
    assert cat["WakirPhase3Welle4StateBackingActive"]["severity"] == "info"
    assert (
        cat["WakirPhase3Welle4SnapshotRestoreTriggered"]["severity"]
        == "warning"
    )
    assert cat["WakirPhase3Welle4StateBackingActive"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/welle-4-state-backing-active"
    )
    assert (
        cat["WakirPhase3Welle4SnapshotRestoreTriggered"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-4-snapshot-restore-triggered"
    )


def test_bridge_new_routing_class_registered(bridge_module) -> None:
    """The ``welle-4-state-backing-info`` routing class must be
    in VALID_ROUTING_CLASSES, ROUTING_CLASS_CHANNELS, and
    ROUTING_CLASS_ESCALATION_SECONDS. Shape invariants hold.
    """
    rc = "welle-4-state-backing-info"
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
    new Tag-72 routing class.
    """
    assert bridge_module.lookup_routing_class_channels(
        "welle-4-state-backing-info"
    ) == ("ntfy:ar-hand-info", "activity-log:append")
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "welle-4-state-backing-info"
        )
        == 0
    )
    # Unknown class still returns empty + 0.
    assert (
        bridge_module.lookup_routing_class_channels("unknown-class") == ()
    )
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "unknown-class"
        )
        == 0
    )


def test_bridge_trinary_shape_still_ok(bridge_module) -> None:
    """Adding the Tag-72 routing class must NOT break the
    trinary routing-table shape invariants (Tag-64 contract).
    """
    shape = bridge_module.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


def test_bridge_lookup_catalog_returns_tag72_entries(
    bridge_module,
) -> None:
    """lookup_catalog() must return a copy of the catalog entry
    for both Tag-72 alerts (and the copy must be independent of
    the catalog dict).
    """
    e1 = bridge_module.lookup_catalog("WakirPhase3Welle4StateBackingActive")
    assert e1 is not None
    assert e1["severity"] == "info"
    e1["severity"] = "MUTATED"
    # Mutation must not leak back into the catalog.
    assert (
        bridge_module.ALERT_CATALOG["WakirPhase3Welle4StateBackingActive"][
            "severity"
        ]
        == "info"
    )
    e2 = bridge_module.lookup_catalog(
        "WakirPhase3Welle4SnapshotRestoreTriggered"
    )
    assert e2 is not None
    assert e2["severity"] == "warning"


def test_bridge_normalise_severity_maps_warning_and_info(
    bridge_module,
) -> None:
    """Severity normalisation maps the Tag-72 vocabulary
    (info -> info, warning -> warning) through unchanged.
    """
    assert bridge_module.normalise_severity("info", None) == "info"
    assert bridge_module.normalise_severity("warning", None) == "warning"
    # When prom_severity missing, catalog severity is used.
    assert bridge_module.normalise_severity(None, "info") == "info"
    assert bridge_module.normalise_severity(None, "warning") == "warning"


# ---------------------------------------------------------------
# Section 3: Cross-Repo-Mirror byte-equality.
# ---------------------------------------------------------------


def test_alerts_mirror_byte_equal(
    alerts_text: str, alerts_mirror_text: str
) -> None:
    """The protocol-mirror-seed alerts copy is byte-equal."""
    assert alerts_text == alerts_mirror_text, (
        "alerts mirror drifted from primary; Tag-72 cross-repo "
        "invariant broken"
    )


def test_bridge_mirror_byte_equal(
    bridge_text: str, bridge_mirror_text: str
) -> None:
    """The protocol-mirror-seed bridge copy is byte-equal."""
    assert bridge_text == bridge_mirror_text, (
        "bridge mirror drifted from primary; Tag-72 cross-repo "
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
        "WakirPhase3Welle4StateBackingActive",
        "WakirPhase3Welle4SnapshotRestoreTriggered",
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
        "WakirPhase3Welle4StateBackingActive",
        "WakirPhase3Welle4SnapshotRestoreTriggered",
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
        "WakirPhase3Welle4StateBackingActive",
        "WakirPhase3Welle4SnapshotRestoreTriggered",
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
        "WakirPhase3Welle4StateBackingActive",
        "WakirPhase3Welle4SnapshotRestoreTriggered",
    ):
        rule = _find_rule(alerts_doc, name)
        yaml_sev = rule["labels"]["severity"]
        catalog_sev = bridge_module.ALERT_CATALOG[name]["severity"]
        assert yaml_sev == catalog_sev, (
            f"severity drift for {name}: YAML={yaml_sev} "
            f"catalog={catalog_sev}"
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
