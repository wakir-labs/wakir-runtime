# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-73 Welle-5
Capability-Token-Rotation-Alert-Routing-Erweiterung (Noa SRE,
Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-73 Noa Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Two additional Welle-5 capability-token-rotation alarms close the
positive-confirmation + rotation-lag routing gap surfaced during
the KW-26 doppel-cutover audit (DW-AC-6-7-RC R1 rotation-race
patterns, see
``tests/phase_3c/test_doppel_welle_6_7_acceptance.py``):

  * WakirPhase3Welle5CapabilityTokenRotated     (info)
  * WakirPhase3Welle5CapabilityTokenRotationLag (warning,
                                                 rotation-lag-Pfad)

Both alerts are appended to the existing ``welle-5-alerts``
group in ``dashboards/phase-3-marathon-alerts.yaml`` and carry
the new routing class ``welle-5-capability-token-info``. The
bridge ``scripts/observability/alert-rule-to-mira-notify-bridge.py``
catalog table and ROUTING_CLASS_CHANNELS table are extended to
cover the new alerts + routing class. Both files are mirrored
byte-equal into ``wirelang/specs/protocol-mirror-seed/``.

Scope
-----

* Welle-5 alert YAML surface (alert names, severity, labels,
  routing class, expr contract).
* Bridge ALERT_CATALOG entries + routing-class table.
* Cross-Repo-Mirror byte-equality.
* Cross-Reference consistency (alert name <-> catalog,
  routing class <-> channel set).
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
        "bridge_tag73", str(BRIDGE_PATH)
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
# Section 1: Welle-5 alert YAML surface.
# ---------------------------------------------------------------


def test_both_tag73_alerts_present_in_yaml(alerts_text: str) -> None:
    """The two Tag-73 alerts are appended to the alerts YAML."""
    assert "WakirPhase3Welle5CapabilityTokenRotated" in alerts_text
    assert "WakirPhase3Welle5CapabilityTokenRotationLag" in alerts_text


def test_tag73_alerts_live_in_welle_5_group(alerts_doc: dict) -> None:
    """Both alerts must be in the existing ``welle-5-alerts``
    group, not in a new top-level group. This keeps the Welle-5
    capability-token observability surface contiguous and
    grep-discoverable.
    """
    welle_5_groups = [
        g for g in alerts_doc["groups"] if g["name"] == "welle-5-alerts"
    ]
    assert len(welle_5_groups) == 1, (
        "expected exactly one welle-5-alerts group"
    )
    rule_names = [r["alert"] for r in welle_5_groups[0]["rules"]]
    assert "WakirPhase3Welle5CapabilityTokenRotated" in rule_names
    assert "WakirPhase3Welle5CapabilityTokenRotationLag" in rule_names
    # Both Tag-73 alerts MUST come AFTER the pre-existing Welle-5
    # page-level alerts (append, not prepend).
    idx_signoff = rule_names.index("WakirWelle5SignedOffBeforeWelle4Stable")
    idx_rotated = rule_names.index(
        "WakirPhase3Welle5CapabilityTokenRotated"
    )
    idx_lag = rule_names.index(
        "WakirPhase3Welle5CapabilityTokenRotationLag"
    )
    assert idx_signoff < idx_rotated < idx_lag


def test_cap_token_rotated_severity_info_and_labels(
    alerts_doc: dict,
) -> None:
    """The Rotated alert must be severity=info with the
    canonical Tag-73 Welle-5 labels.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotated"
    )
    labels = rule["labels"]
    assert labels["severity"] == "info"
    assert labels["welle"] == "welle-5"
    assert labels["component"] == "capability_token_rotator"
    assert labels["routing_class"] == "welle-5-capability-token-info"
    assert labels["tag"] == "tag-73"
    assert labels["owner"] == "noa-sre"
    assert labels["team"] == "sre"
    assert labels["topology"] == "doppel"
    assert labels["kw_week"] == "kw-26"


def test_cap_token_rotation_lag_severity_warning_and_labels(
    alerts_doc: dict,
) -> None:
    """The RotationLag alert must be severity=warning
    (rotation-lag-Pfad, NOT page) with the canonical Tag-73
    labels plus the ``rotation_path: lag-past-target-interval``
    discriminator.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotationLag"
    )
    labels = rule["labels"]
    assert labels["severity"] == "warning"
    assert labels["welle"] == "welle-5"
    assert labels["component"] == "capability_token_rotator"
    assert labels["routing_class"] == "welle-5-capability-token-info"
    assert labels["tag"] == "tag-73"
    assert labels["rotation_path"] == "lag-past-target-interval"
    assert labels["owner"] == "noa-sre"


def test_cap_token_rotated_expr_contract(alerts_doc: dict) -> None:
    """The Rotated alert expr must positively match the
    rotation-epoch increase (>= 1 in last 10m) AND the steady
    ``rotated`` rotator-state. Mutual exclusion with rotator
    not-yet-rotated states is enforced by the gauge contract.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotated"
    )
    expr = rule["expr"]
    assert (
        "increase(wakir_welle5_capability_token_rotation_epoch_total[10m])"
        in expr
    )
    assert ">= 1" in expr
    assert (
        'wakir_welle5_capability_token_rotator_state{state="rotated"} == 1'
        in expr
    )


def test_cap_token_rotation_lag_expr_uses_lag_gauge(
    alerts_doc: dict,
) -> None:
    """The RotationLag alert expr must use the canonical lag
    gauge ``wakir_welle5_capability_token_rotation_lag_seconds``
    with the >= 1350 threshold (target 900s + 50% margin per
    ADR-0066 KW-26 doppel-cutover spec).
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotationLag"
    )
    expr = rule["expr"]
    assert (
        "wakir_welle5_capability_token_rotation_lag_seconds" in expr
    )
    assert ">= 1350" in expr


def test_both_alerts_notify_path_is_info_only(alerts_doc: dict) -> None:
    """Both Tag-73 alerts must route to ntfy:ar-hand-info +
    activity-log:append only. No pagerduty, no on-call page.
    """
    for name in (
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
    ):
        rule = _find_rule(alerts_doc, name)
        notify = rule["annotations"]["notify_path"]
        assert "ntfy:ar-hand-info" in notify
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify, (
            f"info/warning Tag-73 alert {name} must NOT page on-call"
        )


def test_tag73_alerts_carry_runbook_url(alerts_doc: dict) -> None:
    """Both alerts must declare a runbook_url annotation that
    matches the bridge catalog runbook_url.
    """
    rule_rotated = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotated"
    )
    rule_lag = _find_rule(
        alerts_doc, "WakirPhase3Welle5CapabilityTokenRotationLag"
    )
    assert rule_rotated["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-5-capability-token-rotated"
    )
    assert rule_lag["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-5-capability-token-rotation-lag"
    )


def test_tag73_header_comment_present(alerts_text: str) -> None:
    """A Tag-73 header comment anchors the new block for future
    grep-ability and audit-trail reading.
    """
    assert (
        "Tag-73 Welle-5 Capability-Token-Rotation-Alert-Routing-"
        "Erweiterung"
    ) in alerts_text


def test_tag73_alerts_carry_for_window(alerts_doc: dict) -> None:
    """Both Tag-73 alerts must declare a 2m ``for:`` window to
    survive a single Prometheus scrape gap (~15s) without
    false-positives on transient state-flips.
    """
    for name in (
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
    ):
        rule = _find_rule(alerts_doc, name)
        assert rule["for"] == "2m", (
            f"alert {name} for-window drift: expected 2m, "
            f"got {rule['for']}"
        )


# ---------------------------------------------------------------
# Section 2: Bridge ALERT_CATALOG + routing-class table.
# ---------------------------------------------------------------


def test_bridge_catalog_has_both_tag73_alerts(bridge_module) -> None:
    """Both Tag-73 alerts must be catalogued in ALERT_CATALOG
    with the correct severity + runbook_url.
    """
    cat = bridge_module.ALERT_CATALOG
    assert "WakirPhase3Welle5CapabilityTokenRotated" in cat
    assert "WakirPhase3Welle5CapabilityTokenRotationLag" in cat
    assert (
        cat["WakirPhase3Welle5CapabilityTokenRotated"]["severity"]
        == "info"
    )
    assert (
        cat["WakirPhase3Welle5CapabilityTokenRotationLag"]["severity"]
        == "warning"
    )
    assert (
        cat["WakirPhase3Welle5CapabilityTokenRotated"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-5-capability-token-rotated"
    )
    assert (
        cat["WakirPhase3Welle5CapabilityTokenRotationLag"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-5-capability-token-rotation-lag"
    )


def test_bridge_new_routing_class_registered(bridge_module) -> None:
    """The ``welle-5-capability-token-info`` routing class must
    be in VALID_ROUTING_CLASSES, ROUTING_CLASS_CHANNELS, and
    ROUTING_CLASS_ESCALATION_SECONDS. Shape invariants hold.
    """
    rc = "welle-5-capability-token-info"
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
    new Tag-73 routing class.
    """
    assert bridge_module.lookup_routing_class_channels(
        "welle-5-capability-token-info"
    ) == ("ntfy:ar-hand-info", "activity-log:append")
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "welle-5-capability-token-info"
        )
        == 0
    )


def test_bridge_trinary_shape_still_ok(bridge_module) -> None:
    """Adding the Tag-73 routing class must NOT break the
    trinary routing-table shape invariants (Tag-64 contract).
    """
    shape = bridge_module.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


def test_bridge_lookup_catalog_returns_tag73_entries(
    bridge_module,
) -> None:
    """lookup_catalog() must return a copy of the catalog entry
    for both Tag-73 alerts (and the copy must be independent of
    the catalog dict).
    """
    e1 = bridge_module.lookup_catalog(
        "WakirPhase3Welle5CapabilityTokenRotated"
    )
    assert e1 is not None
    assert e1["severity"] == "info"
    e1["severity"] = "MUTATED"
    # Mutation must not leak back into the catalog.
    assert (
        bridge_module.ALERT_CATALOG[
            "WakirPhase3Welle5CapabilityTokenRotated"
        ]["severity"]
        == "info"
    )
    e2 = bridge_module.lookup_catalog(
        "WakirPhase3Welle5CapabilityTokenRotationLag"
    )
    assert e2 is not None
    assert e2["severity"] == "warning"


def test_bridge_normalise_severity_maps_warning_and_info(
    bridge_module,
) -> None:
    """Severity normalisation maps the Tag-73 vocabulary
    (info -> info, warning -> warning) through unchanged.
    """
    assert bridge_module.normalise_severity("info", None) == "info"
    assert (
        bridge_module.normalise_severity("warning", None) == "warning"
    )


def test_bridge_tag72_routing_class_still_registered(
    bridge_module,
) -> None:
    """Regression guard: Tag-73 addition must NOT remove the
    Tag-72 ``welle-4-state-backing-info`` routing class.
    """
    rc = "welle-4-state-backing-info"
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
        "alerts mirror drifted from primary; Tag-73 cross-repo "
        "invariant broken"
    )


def test_bridge_mirror_byte_equal(
    bridge_text: str, bridge_mirror_text: str
) -> None:
    """The protocol-mirror-seed bridge copy is byte-equal."""
    assert bridge_text == bridge_mirror_text, (
        "bridge mirror drifted from primary; Tag-73 cross-repo "
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
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
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
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
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
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
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
        "WakirPhase3Welle5CapabilityTokenRotated",
        "WakirPhase3Welle5CapabilityTokenRotationLag",
    ):
        rule = _find_rule(alerts_doc, name)
        yaml_sev = rule["labels"]["severity"]
        catalog_sev = bridge_module.ALERT_CATALOG[name]["severity"]
        assert yaml_sev == catalog_sev, (
            f"severity drift for {name}: YAML={yaml_sev} "
            f"catalog={catalog_sev}"
        )


def test_failure_mode_id_tag73_prefix(bridge_module) -> None:
    """Both Tag-73 catalog entries must carry a failure_mode_id
    prefixed with ``Tag-73-Welle5-CapToken-`` for audit-trail
    grep-ability.
    """
    cat = bridge_module.ALERT_CATALOG
    fmi_rotated = cat["WakirPhase3Welle5CapabilityTokenRotated"][
        "failure_mode_id"
    ]
    fmi_lag = cat["WakirPhase3Welle5CapabilityTokenRotationLag"][
        "failure_mode_id"
    ]
    assert fmi_rotated.startswith("Tag-73-Welle5-CapToken-")
    assert fmi_lag.startswith("Tag-73-Welle5-CapToken-")
    assert fmi_rotated != fmi_lag


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
