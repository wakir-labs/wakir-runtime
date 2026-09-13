# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-74 Welle-6
Cross-Substrate-Parity-Alert-Routing-Erweiterung + Tomas-Tag-73
``reuse-lint`` pre-commit-hook follow-up (Noa SRE,
Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-74 Noa Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):

Teil 1 -- Welle-6 Cross-Substrate-Parity-Alert-Routing-Erweiterung.
Two additional Welle-6 subscribe-loop alarms close the positive-
confirmation + consumer-lag routing gap surfaced during the KW-27
doppel-cutover audit (cross-substrate-parity race patterns, see
``tests/phase_3c/test_doppel_welle_6_7_acceptance.py``):

  * WakirPhase3Welle6SubscribeLoopHealthy   (info)
  * WakirPhase3Welle6JetStreamConsumerLag   (warning,
                                              consumer-lag-Pfad)

Both alerts are appended to the existing ``welle-6-alerts``
group in ``dashboards/phase-3-marathon-alerts.yaml`` and carry
the new routing class ``welle-6-subscribe-loop-info``. The
bridge ``scripts/observability/alert-rule-to-mira-notify-bridge.py``
catalog table and ROUTING_CLASS_CHANNELS table are extended to
cover the new alerts + routing class. Both files are mirrored
byte-equal into ``wirelang/specs/protocol-mirror-seed/``.

Teil 2 -- ``reuse-lint`` pre-commit-hook follow-up (Tomas Tag-73
recommendation). The existing Tag-61 hint-mode hook caught drift
advisorily but did NOT block commits, and four Tag-66/68/71 drift
episodes slipped through despite the advisory. Tag-74 adds a
second hook bound to the same lint helper in enforce-mode,
scoped narrowly to ``tests/observability/**/*.py`` and
``tests/phase_3c/**/*.py`` where the drift recurs.

Scope
-----

* Welle-6 alert YAML surface (alert names, severity, labels,
  routing class, expr contract).
* Bridge ALERT_CATALOG entries + routing-class table.
* Cross-Repo-Mirror byte-equality.
* Cross-Reference consistency (alert name <-> catalog,
  routing class <-> channel set).
* ``.pre-commit-config.yaml`` enforce-mode hook structure.
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

PRE_COMMIT_CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"


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
        "bridge_tag74", str(BRIDGE_PATH)
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


@pytest.fixture(scope="module")
def pre_commit_doc() -> dict:
    return yaml.safe_load(
        PRE_COMMIT_CONFIG_PATH.read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def pre_commit_text() -> str:
    return PRE_COMMIT_CONFIG_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# Section 1: Welle-6 alert YAML surface.
# ---------------------------------------------------------------


def test_both_tag74_alerts_present_in_yaml(alerts_text: str) -> None:
    """The two Tag-74 alerts are appended to the alerts YAML."""
    assert "WakirPhase3Welle6SubscribeLoopHealthy" in alerts_text
    assert "WakirPhase3Welle6JetStreamConsumerLag" in alerts_text


def test_tag74_alerts_live_in_welle_6_group(alerts_doc: dict) -> None:
    """Both alerts must be in the existing ``welle-6-alerts``
    group, not in a new top-level group. This keeps the Welle-6
    subscribe-loop observability surface contiguous and
    grep-discoverable.
    """
    welle_6_groups = [
        g for g in alerts_doc["groups"] if g["name"] == "welle-6-alerts"
    ]
    assert len(welle_6_groups) == 1, (
        "expected exactly one welle-6-alerts group"
    )
    rule_names = [r["alert"] for r in welle_6_groups[0]["rules"]]
    assert "WakirPhase3Welle6SubscribeLoopHealthy" in rule_names
    assert "WakirPhase3Welle6JetStreamConsumerLag" in rule_names
    # Both Tag-74 alerts MUST come AFTER the pre-existing Welle-6
    # page-level alerts (append, not prepend).
    idx_replay = rule_names.index("WakirWelle6SubscribeLoopReplayStorm")
    idx_healthy = rule_names.index(
        "WakirPhase3Welle6SubscribeLoopHealthy"
    )
    idx_lag = rule_names.index(
        "WakirPhase3Welle6JetStreamConsumerLag"
    )
    assert idx_replay < idx_healthy < idx_lag


def test_subscribe_loop_healthy_severity_info_and_labels(
    alerts_doc: dict,
) -> None:
    """The Healthy alert must be severity=info with the
    canonical Tag-74 Welle-6 labels.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle6SubscribeLoopHealthy"
    )
    labels = rule["labels"]
    assert labels["severity"] == "info"
    assert labels["welle"] == "welle-6"
    assert labels["component"] == "subscribe_loop"
    assert labels["routing_class"] == "welle-6-subscribe-loop-info"
    assert labels["tag"] == "tag-74"
    assert labels["owner"] == "noa-sre"
    assert labels["team"] == "sre"
    assert labels["topology"] == "doppel"
    assert labels["kw_week"] == "kw-27"


def test_consumer_lag_severity_warning_and_labels(
    alerts_doc: dict,
) -> None:
    """The ConsumerLag alert must be severity=warning
    (consumer-lag-Pfad, NOT page) with the canonical Tag-74
    labels plus the ``lag_path: consumer-pending-past-target-
    threshold`` discriminator.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle6JetStreamConsumerLag"
    )
    labels = rule["labels"]
    assert labels["severity"] == "warning"
    assert labels["welle"] == "welle-6"
    assert labels["component"] == "subscribe_loop"
    assert labels["routing_class"] == "welle-6-subscribe-loop-info"
    assert labels["tag"] == "tag-74"
    assert labels["lag_path"] == "consumer-pending-past-target-threshold"
    assert labels["owner"] == "noa-sre"


def test_subscribe_loop_healthy_expr_contract(alerts_doc: dict) -> None:
    """The Healthy alert expr must positively match the
    message-delivered rate (>= 0.1 in last 5m) AND the consumer
    pending-messages threshold (< 100). Mutual exclusion with
    stall regime is enforced by the rate gate; mutual exclusion
    with consumer-lag is enforced by the < 100 pending threshold.
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle6SubscribeLoopHealthy"
    )
    expr = rule["expr"]
    assert (
        "rate(wakir_welle6_subscribe_loop_message_delivered_total[5m])"
        in expr
    )
    assert ">= 0.1" in expr
    assert (
        "wakir_welle6_jetstream_consumer_pending_messages < 100"
        in expr
    )


def test_consumer_lag_expr_uses_pending_gauge(
    alerts_doc: dict,
) -> None:
    """The ConsumerLag alert expr must use the canonical pending-
    messages gauge ``wakir_welle6_jetstream_consumer_pending_messages``
    with the >= 500 threshold (target SLO is < 100, the
    >= 500 threshold flags accumulated backlog before delivery
    races materialise per ADR-0066 KW-27 doppel-cutover spec).
    """
    rule = _find_rule(
        alerts_doc, "WakirPhase3Welle6JetStreamConsumerLag"
    )
    expr = rule["expr"]
    assert (
        "wakir_welle6_jetstream_consumer_pending_messages" in expr
    )
    assert ">= 500" in expr


def test_both_alerts_notify_path_is_info_only(alerts_doc: dict) -> None:
    """Both Tag-74 alerts must route to ntfy:ar-hand-info +
    activity-log:append only. No pagerduty, no on-call page.
    """
    for name in (
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
    ):
        rule = _find_rule(alerts_doc, name)
        notify = rule["annotations"]["notify_path"]
        assert "ntfy:ar-hand-info" in notify
        assert "activity-log:append" in notify
        assert "pagerduty" not in notify, (
            f"info/warning Tag-74 alert {name} must NOT page on-call"
        )


def test_tag74_alerts_carry_runbook_url(alerts_doc: dict) -> None:
    """Both alerts must declare a runbook_url annotation that
    matches the bridge catalog runbook_url.
    """
    rule_healthy = _find_rule(
        alerts_doc, "WakirPhase3Welle6SubscribeLoopHealthy"
    )
    rule_lag = _find_rule(
        alerts_doc, "WakirPhase3Welle6JetStreamConsumerLag"
    )
    assert rule_healthy["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-6-subscribe-loop-healthy"
    )
    assert rule_lag["annotations"]["runbook_url"] == (
        "https://wakir-labs.example/runbooks/"
        "welle-6-jetstream-consumer-lag"
    )


def test_tag74_header_comment_present(alerts_text: str) -> None:
    """A Tag-74 header comment anchors the new block for future
    grep-ability and audit-trail reading.
    """
    assert (
        "Tag-74 Welle-6 Cross-Substrate-Parity-Alert-Routing-"
        "Erweiterung"
    ) in alerts_text


def test_tag74_alerts_carry_for_window(alerts_doc: dict) -> None:
    """Both Tag-74 alerts must declare a 2m ``for:`` window to
    survive a single Prometheus scrape gap (~15s) without
    false-positives on transient state-flips.
    """
    for name in (
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
    ):
        rule = _find_rule(alerts_doc, name)
        assert rule["for"] == "2m", (
            f"alert {name} for-window drift: expected 2m, "
            f"got {rule['for']}"
        )


# ---------------------------------------------------------------
# Section 2: Bridge ALERT_CATALOG + routing-class table.
# ---------------------------------------------------------------


def test_bridge_catalog_has_both_tag74_alerts(bridge_module) -> None:
    """Both Tag-74 alerts must be catalogued in ALERT_CATALOG
    with the correct severity + runbook_url.
    """
    cat = bridge_module.ALERT_CATALOG
    assert "WakirPhase3Welle6SubscribeLoopHealthy" in cat
    assert "WakirPhase3Welle6JetStreamConsumerLag" in cat
    assert (
        cat["WakirPhase3Welle6SubscribeLoopHealthy"]["severity"]
        == "info"
    )
    assert (
        cat["WakirPhase3Welle6JetStreamConsumerLag"]["severity"]
        == "warning"
    )
    assert (
        cat["WakirPhase3Welle6SubscribeLoopHealthy"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-6-subscribe-loop-healthy"
    )
    assert (
        cat["WakirPhase3Welle6JetStreamConsumerLag"]["runbook_url"]
    ) == (
        "https://wakir-labs.example/runbooks/"
        "welle-6-jetstream-consumer-lag"
    )


def test_bridge_new_routing_class_registered(bridge_module) -> None:
    """The ``welle-6-subscribe-loop-info`` routing class must be
    in VALID_ROUTING_CLASSES, ROUTING_CLASS_CHANNELS, and
    ROUTING_CLASS_ESCALATION_SECONDS. Shape invariants hold.
    """
    rc = "welle-6-subscribe-loop-info"
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
    new Tag-74 routing class.
    """
    assert bridge_module.lookup_routing_class_channels(
        "welle-6-subscribe-loop-info"
    ) == ("ntfy:ar-hand-info", "activity-log:append")
    assert (
        bridge_module.lookup_routing_class_escalation_seconds(
            "welle-6-subscribe-loop-info"
        )
        == 0
    )


def test_bridge_trinary_shape_still_ok(bridge_module) -> None:
    """Adding the Tag-74 routing class must NOT break the
    trinary routing-table shape invariants (Tag-64 contract).
    """
    shape = bridge_module.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


def test_bridge_lookup_catalog_returns_tag74_entries(
    bridge_module,
) -> None:
    """lookup_catalog() must return a copy of the catalog entry
    for both Tag-74 alerts (and the copy must be independent of
    the catalog dict).
    """
    e1 = bridge_module.lookup_catalog(
        "WakirPhase3Welle6SubscribeLoopHealthy"
    )
    assert e1 is not None
    assert e1["severity"] == "info"
    e1["severity"] = "MUTATED"
    # Mutation must not leak back into the catalog.
    assert (
        bridge_module.ALERT_CATALOG[
            "WakirPhase3Welle6SubscribeLoopHealthy"
        ]["severity"]
        == "info"
    )
    e2 = bridge_module.lookup_catalog(
        "WakirPhase3Welle6JetStreamConsumerLag"
    )
    assert e2 is not None
    assert e2["severity"] == "warning"


def test_bridge_prior_routing_classes_still_registered(
    bridge_module,
) -> None:
    """Regression guard: Tag-74 addition must NOT remove the
    Tag-72 ``welle-4-state-backing-info`` or Tag-73
    ``welle-5-capability-token-info`` routing classes.
    """
    for rc in (
        "welle-4-state-backing-info",
        "welle-5-capability-token-info",
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
        "alerts mirror drifted from primary; Tag-74 cross-repo "
        "invariant broken"
    )


def test_bridge_mirror_byte_equal(
    bridge_text: str, bridge_mirror_text: str
) -> None:
    """The protocol-mirror-seed bridge copy is byte-equal."""
    assert bridge_text == bridge_mirror_text, (
        "bridge mirror drifted from primary; Tag-74 cross-repo "
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
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
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
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
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
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
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
        "WakirPhase3Welle6SubscribeLoopHealthy",
        "WakirPhase3Welle6JetStreamConsumerLag",
    ):
        rule = _find_rule(alerts_doc, name)
        yaml_sev = rule["labels"]["severity"]
        catalog_sev = bridge_module.ALERT_CATALOG[name]["severity"]
        assert yaml_sev == catalog_sev, (
            f"severity drift for {name}: YAML={yaml_sev} "
            f"catalog={catalog_sev}"
        )


def test_failure_mode_id_tag74_prefix(bridge_module) -> None:
    """Both Tag-74 catalog entries must carry a failure_mode_id
    prefixed with ``Tag-74-Welle6-SubscribeLoop-`` for audit-trail
    grep-ability.
    """
    cat = bridge_module.ALERT_CATALOG
    fmi_healthy = cat["WakirPhase3Welle6SubscribeLoopHealthy"][
        "failure_mode_id"
    ]
    fmi_lag = cat["WakirPhase3Welle6JetStreamConsumerLag"][
        "failure_mode_id"
    ]
    assert fmi_healthy.startswith("Tag-74-Welle6-SubscribeLoop-")
    assert fmi_lag.startswith("Tag-74-Welle6-SubscribeLoop-")
    assert fmi_healthy != fmi_lag


# ---------------------------------------------------------------
# Section 5: Tag-74 ``reuse-lint`` pre-commit-hook enforce-mode.
# ---------------------------------------------------------------


def test_pre_commit_config_has_tag74_enforce_hook(
    pre_commit_doc: dict,
) -> None:
    """``.pre-commit-config.yaml`` must contain the Tag-74
    enforce-mode hook ``reuse-wrap-pre-merge-lint-enforce`` in
    the local-repo section.
    """
    local_hooks: list[dict] = []
    for repo in pre_commit_doc["repos"]:
        if repo.get("repo") == "local":
            local_hooks.extend(repo.get("hooks", []))
    hook_ids = [h["id"] for h in local_hooks]
    assert "reuse-wrap-pre-merge-lint-enforce" in hook_ids, (
        "Tag-74 enforce-mode hook missing from local hooks"
    )
    # Tag-61 hint-mode hook must still be present (additive,
    # not replacement).
    assert "reuse-wrap-pre-merge-lint" in hook_ids, (
        "Tag-61 hint-mode hook regression: must remain present"
    )


def test_pre_commit_enforce_hook_runs_enforce_mode(
    pre_commit_doc: dict,
) -> None:
    """The Tag-74 enforce hook must invoke the lint helper with
    ``--mode enforce`` (NOT hint), so the commit blocks on
    findings.
    """
    enforce_hook = _find_pre_commit_hook(
        pre_commit_doc, "reuse-wrap-pre-merge-lint-enforce"
    )
    entry = enforce_hook["entry"]
    assert "tooling/ci/lint_reuse_ignore_wrap_pattern.py" in entry
    assert "--mode enforce" in entry, (
        "Tag-74 enforce-mode hook must pass --mode enforce; "
        f"got entry={entry}"
    )
    assert "--mode hint" not in entry, (
        "Tag-74 enforce-mode hook must NOT pass --mode hint"
    )


def test_pre_commit_enforce_hook_scope_is_narrow(
    pre_commit_doc: dict,
) -> None:
    """The Tag-74 enforce hook ``files:`` regex must scope to
    ``tests/observability/**/*.py`` AND ``tests/phase_3c/**/*.py``
    only -- broader scope would block non-observability test work
    on wrap-style drift. The Tag-61 hint-mode hook covers the
    broader ``tests/**/*.py`` advisorily.
    """
    enforce_hook = _find_pre_commit_hook(
        pre_commit_doc, "reuse-wrap-pre-merge-lint-enforce"
    )
    files_regex = enforce_hook["files"]
    # Must match both target sub-trees.
    import re
    pattern = re.compile(files_regex)
    assert pattern.match("tests/observability/test_foo.py")
    assert pattern.match("tests/observability/sub/test_bar.py")
    assert pattern.match("tests/phase_3c/test_baz.py")
    # Must NOT match unrelated test paths.
    assert not pattern.match("tests/unit/test_foo.py")
    assert not pattern.match("tests/integration/test_bar.py")
    # Must NOT match non-test substance paths.
    assert not pattern.match("scripts/foo.py")
    assert not pattern.match("src/observability/bar.py")


def test_pre_commit_enforce_hook_preserves_hint_hook(
    pre_commit_doc: dict,
) -> None:
    """The Tag-61 hint-mode hook must remain in the config and
    keep its broader ``tests/**/*.py`` scope, so the Tag-74
    enforce-mode hook is additive (not replacement).
    """
    hint_hook = _find_pre_commit_hook(
        pre_commit_doc, "reuse-wrap-pre-merge-lint"
    )
    assert "--mode hint" in hint_hook["entry"]
    assert hint_hook["files"] == r"^tests/.+\.py$"


def test_pre_commit_config_carries_tag74_header_comment(
    pre_commit_text: str,
) -> None:
    """A Tag-74 header comment block anchors the new hook for
    audit-trail grep-ability, mirroring the Tag-61 block above.
    """
    assert (
        "Tag-74 — REUSE-IgnoreStart/End wrap pre-merge lint"
        in pre_commit_text
        or "Tag-74 - REUSE-IgnoreStart/End wrap pre-merge lint"
        in pre_commit_text
        or "Tag-74" in pre_commit_text
    ), "Tag-74 header comment missing from .pre-commit-config.yaml"
    # The Tomas-Tag-73 follow-up attribution must be referenced.
    assert "Tomás" in pre_commit_text or "Tomas" in pre_commit_text


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


def _find_pre_commit_hook(pre_commit_doc: dict, hook_id: str) -> dict:
    """Return the hook dict for the local hook with the given id."""
    for repo in pre_commit_doc["repos"]:
        if repo.get("repo") == "local":
            for hook in repo.get("hooks", []):
                if hook.get("id") == hook_id:
                    return hook
    raise AssertionError(
        f"hook id {hook_id} not found in .pre-commit-config.yaml "
        f"local hooks"
    )
