# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-50 Welle-N-Specific Alert-Rules.

Tag-40 / Tag-45 alerts surface marathon-wide aggregate failure-
modes and cross-welle hot-spots. Tag-50 adds a separate alert
GROUP per Phase-3c welle (welle-1..welle-7) so the operator sees
welle-scoped pages immediately without disambiguating from the
labels of an aggregate alert.

Coverage:

  * Group existence + naming convention (``welle-N-alerts``).
  * Per-welle alarm-count contract (2..3 per group).
  * Each Tag-50 alert MUST carry a ``welle`` label with the
    correct ``welle-N`` value.
  * Each Tag-50 alert MUST carry ``team=sre`` and ``owner=noa-sre``.
  * Severity must be in {page, ticket, warning}.
  * Welle-3 group MUST scrape at 15s (KW-25 SOLO critical).
  * Welle-1+2 groups MUST carry topology=doppel (KW-24 partners).
  * Welle-4+5 groups MUST carry topology=doppel (KW-26 partners).
  * Welle-6+7 groups MUST carry topology=doppel (KW-27 partners).
  * Per-welle signature-expression assertions (substance check).
  * Notify-catalog references each Tag-50 alert (drift-detection
    mirroring the Tag-45 catalog test).

Sandbox boundary: pure stdlib + ``yaml``. No Prometheus, no Grafana,
no network. Pinned-thread fixtures for the YAML + catalog reads.

Anchors:
  - Tag-50 auftrag (Noa-SRE, Welle-N-Specific Alert-Rules).
  - dashboards/phase-3-marathon-alerts.yaml (groups welle-1-alerts
    .. welle-7-alerts).
  - docs/observability/pre-mortem-failure-mode-notify-catalog.md
    (Tag-50 section added below the Tag-45 sections).
  - ADR-0065 / ADR-0066 (welle-component mapping + KW topology).
  - tests/ci/test_phase_3_marathon_failure_mode_alerts.py (Tag-45
    sibling test; this file extends the contract without
    overlapping).
"""

from __future__ import annotations

import pathlib

import pytest
import yaml


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALERTS_PATH = _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
_CATALOG_PATH = (
    _REPO_ROOT
    / "docs"
    / "observability"
    / "pre-mortem-failure-mode-notify-catalog.md"
)


# ---------------------------------------------------------------------------
# Tag-50 contract
# ---------------------------------------------------------------------------


# Welle-component mapping per ADR-0065 / ADR-0066 (matches dashboard
# persona-engine-phase-3c-welle-status.json welle-N descriptions).
_WELLE_COMPONENT_MAP = {
    "welle-1": "v907_verify",
    "welle-2": "svid_workload_identity",
    "welle-3": "bridge_audit_writer",
    "welle-4": "state_backing",
    "welle-5": "lifecycle_state_machine",
    "welle-6": "subscribe_loop",
    "welle-7": "recovery_workflow",
}


# KW-week + topology per ADR-0066 sequence.
_WELLE_KW_TOPOLOGY = {
    "welle-1": ("kw-24", "doppel"),
    "welle-2": ("kw-24", "doppel"),
    "welle-3": ("kw-25", "solo"),
    "welle-4": ("kw-26", "doppel"),
    "welle-5": ("kw-26", "doppel"),
    "welle-6": ("kw-27", "doppel"),
    "welle-7": ("kw-27", "doppel"),
}


# Tag-50 group-name -> expected (min alarms, max alarms, scrape interval).
#
# Tag-76 cardinality-fix (Noa SRE): the max-count was bumped per
# welle to absorb the Tag-72/73/74/75 routing-extension alerts
# that are APPENDED to the existing welle-N-alerts groups (see
# tests/observability/test_welle_*_routing_tag*.py which pin
# ``live_in_welle_N_group``). The Tag-50 original-alarm count is
# preserved by the _TAG50_ALERTS set; the per-group max simply
# accounts for the additional ``WakirPhase3Welle*`` extensions
# that live alongside the Tag-50 ``WakirWelle*`` originals.
#
# Per-welle Tag-7X extensions (Tomás-Tag-75 §3 side-finding):
#   welle-1: +0 (no Tag-7X routing extension)
#   welle-2: +0
#   welle-3: +0
#   welle-4: +2 (Tag-72 StateBackingActive + SnapshotRestoreTriggered)
#   welle-5: +2 (Tag-73 CapabilityTokenRotated + RotationLag)
#   welle-6: +2 (Tag-74 SubscribeLoopHealthy + JetStreamConsumerLag)
#   welle-7: +2 (Tag-75 FinalSealingComplete + PreAuditorSignalReceived)
_TAG50_GROUP_CONTRACT = {
    "welle-1-alerts": (2, 3, "30s"),
    "welle-2-alerts": (2, 3, "30s"),
    "welle-3-alerts": (2, 3, "15s"),  # KW-25 SOLO critical = faster scrape.
    "welle-4-alerts": (2, 5, "30s"),  # Tag-50 (3) + Tag-72 extension (2)
    "welle-5-alerts": (2, 5, "30s"),  # Tag-50 (3) + Tag-73 extension (2)
    "welle-6-alerts": (2, 4, "30s"),  # Tag-50 (2) + Tag-74 extension (2)
    "welle-7-alerts": (2, 5, "30s"),  # Tag-50 (3) + Tag-75 extension (2)
}


# Exhaustive set of Tag-50 alert names that MUST be present.
_TAG50_ALERTS = {
    # welle-1
    "WakirWelle1V907VerifyRustRateCollapse": "welle-1",
    "WakirWelle1Welle2DoppelDivergence": "welle-1",
    # welle-2
    "WakirWelle2SvidRotationFailure": "welle-2",
    "WakirWelle2SelfScoreCollapse": "welle-2",
    # welle-3
    "WakirWelle3SelfReferenceTrapFire": "welle-3",
    "WakirWelle3SoloTopologyViolation": "welle-3",
    "WakirWelle3StressOracleDivergence": "welle-3",
    # welle-4
    "WakirWelle4StateReadFail": "welle-4",
    "WakirWelle4StateBackingMigrationRollback": "welle-4",
    "WakirWelle4WriteLatencyP99Excess": "welle-4",
    # welle-5
    "WakirWelle5FsmPhantomTransition": "welle-5",
    "WakirWelle5LifecycleOrphanState": "welle-5",
    "WakirWelle5SignedOffBeforeWelle4Stable": "welle-5",
    # welle-6
    "WakirWelle6SubscribeLoopStall": "welle-6",
    "WakirWelle6SubscribeLoopReplayStorm": "welle-6",
    # welle-7
    "WakirWelle7RecoveryRehearsalFail": "welle-7",
    "WakirWelle7RecoveryWithoutPreAuditWarning": "welle-7",
    "WakirWelle7RecoveryReplayDivergence": "welle-7",
}


# Tag-76 cardinality-fix (Noa SRE) -- Anti-Regression-Pin:
# Explicit per-welle inventory of the Tag-72/73/74/75 routing-
# extension alerts that are appended to the welle-N-alerts
# groups. Pinned here so the welle-group max-count drift can be
# detected at the SOURCE (someone adds a Tag-7X extension without
# updating this set) rather than only at the symptom (group cap
# overrun). Maps alert-name -> tag.
_TAG7X_EXTENSIONS = {
    # welle-4 (Tag-72 state-backing routing-extension)
    "WakirPhase3Welle4StateBackingActive": "tag-72",
    "WakirPhase3Welle4SnapshotRestoreTriggered": "tag-72",
    # welle-5 (Tag-73 capability-token routing-extension)
    "WakirPhase3Welle5CapabilityTokenRotated": "tag-73",
    "WakirPhase3Welle5CapabilityTokenRotationLag": "tag-73",
    # welle-6 (Tag-74 subscribe-loop routing-extension)
    "WakirPhase3Welle6SubscribeLoopHealthy": "tag-74",
    "WakirPhase3Welle6JetStreamConsumerLag": "tag-74",
    # welle-7 (Tag-75 final-sealing routing-extension)
    "WakirPhase3Welle7FinalSealingComplete": "tag-75",
    "WakirPhase3Welle7PreAuditorSignalReceived": "tag-75",
}


# Expected per-welle Tag-7X extension count -- pin against drift.
_TAG7X_EXTENSION_COUNT_PER_WELLE = {
    "welle-1-alerts": 0,
    "welle-2-alerts": 0,
    "welle-3-alerts": 0,
    "welle-4-alerts": 2,
    "welle-5-alerts": 2,
    "welle-6-alerts": 2,
    "welle-7-alerts": 2,
}


_ALLOWED_SEVERITIES = {"page", "ticket", "warning"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alerts() -> dict:
    return yaml.safe_load(_ALERTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def groups_by_name(alerts: dict) -> dict[str, dict]:
    return {g["name"]: g for g in alerts["groups"]}


@pytest.fixture(scope="module")
def alerts_by_name(alerts: dict) -> dict[str, dict]:
    return {
        r["alert"]: r
        for g in alerts["groups"]
        for r in g["rules"]
    }


@pytest.fixture(scope="module")
def tag50_alerts_by_name(alerts: dict) -> dict[str, dict]:
    """Alerts strictly inside the welle-N-alerts groups, FILTERED to
    the Tag-50 original-alarm set.

    Tag-76 cardinality-fix (Noa SRE): Tag-72/73/74/75 routing-
    extension alerts (``WakirPhase3Welle*``) are appended to the
    same welle-N-alerts groups -- pinned by
    tests/observability/test_welle_*_routing_tag*.py. To keep the
    Tag-50 contract assertions (count, name-prefix-disjointness,
    severity-set, owner/team labels) crisp, this fixture restricts
    to the named Tag-50 originals declared in ``_TAG50_ALERTS``.
    The full-group cardinality is exercised separately by
    ``test_welle_group_alarm_count_in_range``.
    """

    out: dict[str, dict] = {}
    for g in alerts["groups"]:
        if g["name"] in _TAG50_GROUP_CONTRACT:
            for r in g["rules"]:
                if r["alert"] in _TAG50_ALERTS:
                    out[r["alert"]] = r
    return out


@pytest.fixture(scope="module")
def welle_group_all_alerts_by_name(alerts: dict) -> dict[str, dict]:
    """Every alert in the welle-N-alerts groups (Tag-50 originals
    PLUS Tag-72/73/74/75 routing-extensions).

    Tag-76 helper fixture: separate from ``tag50_alerts_by_name``
    so the Tag-50 contract stays scoped to the original alarm-set.
    Used by group-level cardinality checks.
    """

    out: dict[str, dict] = {}
    for g in alerts["groups"]:
        if g["name"] in _TAG50_GROUP_CONTRACT:
            for r in g["rules"]:
                out[r["alert"]] = r
    return out


@pytest.fixture(scope="module")
def catalog_text() -> str:
    return _CATALOG_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Group-level invariants
# ---------------------------------------------------------------------------


def test_all_seven_welle_groups_present(groups_by_name: dict):
    missing = set(_TAG50_GROUP_CONTRACT) - set(groups_by_name)
    assert not missing, f"Tag-50 welle-N groups missing: {missing}"


@pytest.mark.parametrize("group_name", sorted(_TAG50_GROUP_CONTRACT))
def test_welle_group_alarm_count_in_range(
    groups_by_name: dict, group_name: str
):
    min_n, max_n, _ = _TAG50_GROUP_CONTRACT[group_name]
    rules = groups_by_name[group_name]["rules"]
    assert min_n <= len(rules) <= max_n, (
        f"{group_name} must have {min_n}..{max_n} rules; got {len(rules)}"
    )


@pytest.mark.parametrize("group_name", sorted(_TAG50_GROUP_CONTRACT))
def test_welle_group_scrape_interval(
    groups_by_name: dict, group_name: str
):
    _, _, expected_interval = _TAG50_GROUP_CONTRACT[group_name]
    actual = groups_by_name[group_name].get("interval")
    assert actual == expected_interval, (
        f"{group_name} scrape interval mismatch: expected="
        f"{expected_interval} got={actual}"
    )


def test_welle_3_group_scrapes_at_15s_for_kw25_solo(
    groups_by_name: dict,
):
    g = groups_by_name["welle-3-alerts"]
    assert g["interval"] == "15s", (
        "welle-3-alerts MUST scrape every 15s; KW-25 SOLO critical "
        "and Self-Reference-Trap detection requires fast tick"
    )


# ---------------------------------------------------------------------------
# Per-alert contract invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alert_name,expected_welle", sorted(_TAG50_ALERTS.items())
)
def test_tag50_alert_present_and_correct_welle_label(
    tag50_alerts_by_name: dict,
    alert_name: str,
    expected_welle: str,
):
    assert alert_name in tag50_alerts_by_name, (
        f"Tag-50 alert missing: {alert_name}"
    )
    rule = tag50_alerts_by_name[alert_name]
    assert rule["labels"].get("welle") == expected_welle, (
        f"{alert_name} must carry welle={expected_welle}; got "
        f"welle={rule['labels'].get('welle')}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_tag50_alert_owner_and_team(
    tag50_alerts_by_name: dict, alert_name: str
):
    labels = tag50_alerts_by_name[alert_name]["labels"]
    assert labels.get("team") == "sre", f"{alert_name} missing team=sre"
    assert labels.get("owner") == "noa-sre", (
        f"{alert_name} missing owner=noa-sre"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_tag50_alert_severity_in_allowed_set(
    tag50_alerts_by_name: dict, alert_name: str
):
    sev = tag50_alerts_by_name[alert_name]["labels"].get("severity")
    assert sev in _ALLOWED_SEVERITIES, (
        f"{alert_name} severity={sev!r} not in {_ALLOWED_SEVERITIES}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_tag50_alert_has_summary_description_runbook_notify(
    tag50_alerts_by_name: dict, alert_name: str
):
    ann = tag50_alerts_by_name[alert_name].get("annotations", {})
    for key in ("summary", "description", "runbook_url", "notify_path"):
        assert ann.get(key), (
            f"{alert_name} missing annotations.{key}"
        )


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_tag50_alert_has_adr_anchor(
    tag50_alerts_by_name: dict, alert_name: str
):
    labels = tag50_alerts_by_name[alert_name]["labels"]
    assert labels.get("adr") == "adr-0066", (
        f"{alert_name} must reference adr-0066 (Phase-3c "
        f"Beschleunigung); got adr={labels.get('adr')}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_tag50_alert_has_kw_and_topology(
    tag50_alerts_by_name: dict, alert_name: str
):
    welle = _TAG50_ALERTS[alert_name]
    expected_kw, expected_topology = _WELLE_KW_TOPOLOGY[welle]
    labels = tag50_alerts_by_name[alert_name]["labels"]
    # kw_week + topology labels are part of the Tag-50 contract.
    assert labels.get("kw_week") == expected_kw, (
        f"{alert_name} expected kw_week={expected_kw}; got "
        f"{labels.get('kw_week')}"
    )
    assert labels.get("topology") == expected_topology, (
        f"{alert_name} expected topology={expected_topology}; got "
        f"{labels.get('topology')}"
    )


# ---------------------------------------------------------------------------
# Welle-3 KW-25 SOLO critical-marker substance assertions
# ---------------------------------------------------------------------------


def test_welle_3_self_reference_trap_fire_rate_threshold_2x(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle3SelfReferenceTrapFire"]
    expr = rule["expr"]
    # Welle-3-scoped: tighter 2x threshold (Tag-45 A5 uses 3x).
    assert ">= 2" in expr, (
        "Welle-3 SelfReferenceTrapFire must use 2x baseline "
        "threshold (tighter than Tag-45 A5 3x for welle-scoped page)"
    )
    assert 'welle="welle-3"' in expr
    assert "audit-bridge" in expr
    assert rule["labels"].get("critical") == "kw-25-solo"


def test_welle_3_solo_topology_violation_signature(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle3SoloTopologyViolation"]
    expr = rule["expr"]
    assert 'welle="welle-3"' in expr
    # Pre-cutover = 1 and in-cutover = 2 must both be referenced.
    assert "== 1" in expr
    assert "== 2" in expr
    # The count() short-circuit makes more than one welle in pre/in
    # states the trigger.
    assert "count(" in expr
    assert "> 1" in expr


def test_welle_3_stress_oracle_divergence_threshold_0_5pp(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle3StressOracleDivergence"]
    expr = rule["expr"]
    assert "abs(" in expr
    assert "> 0.5" in expr, (
        "Welle-3 stress-oracle divergence threshold MUST be 0.5pp "
        "per ADR-0066 Welle-3 immediate-rollback trigger (Henrik "
        "caution panel 43)"
    )
    assert "bridge_audit_writer" in expr


# ---------------------------------------------------------------------------
# Welle-4 + Welle-5 cross-welle ordering substance check
# ---------------------------------------------------------------------------


def test_welle_5_signoff_before_welle_4_stable_is_conjunction(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name[
        "WakirWelle5SignedOffBeforeWelle4Stable"
    ]
    expr = rule["expr"]
    assert 'welle="welle-5"' in expr
    assert 'welle="welle-4"' in expr
    assert "wakir_welle_schluss_audit_signoff" in expr
    assert "wakir_state_backing_self_check_hash" in expr
    assert "changes(" in expr
    # Conjunction.
    assert "and" in expr.lower().split()
    assert rule["labels"].get("ordering") == "welle-4-must-stabilize-first"


# ---------------------------------------------------------------------------
# Welle-6 + Welle-7 KW-27 contract
# ---------------------------------------------------------------------------


def test_welle_6_subscribe_loop_stall_uses_zero_rate(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle6SubscribeLoopStall"]
    expr = rule["expr"]
    assert "rate(" in expr
    assert "subscribe_loop_message_delivered_total" in expr
    assert "== 0" in expr
    assert rule["for"] == "2m"


def test_welle_6_replay_storm_threshold_above_10_per_s(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle6SubscribeLoopReplayStorm"]
    expr = rule["expr"]
    assert "redelivery" in expr
    assert "> 10" in expr


def test_welle_7_recovery_without_pre_audit_is_warning(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name[
        "WakirWelle7RecoveryWithoutPreAuditWarning"
    ]
    assert rule["labels"]["severity"] == "warning", (
        "Welle-7 IIA-1130 default-path parallels Tag-45 B3 -- "
        "warning, not page"
    )
    expr = rule["expr"]
    assert 'auditor="henrik"' in expr
    assert 'auditor="external-pre-auditor"' in expr
    assert rule["labels"].get("standard") == "iia-1130"


def test_welle_7_replay_divergence_uses_increase_function(
    tag50_alerts_by_name: dict,
):
    rule = tag50_alerts_by_name["WakirWelle7RecoveryReplayDivergence"]
    expr = rule["expr"]
    assert "increase(" in expr
    assert "welle7_recovery_replay_divergence_total" in expr


# ---------------------------------------------------------------------------
# Disjointness invariants vs Tag-45
# ---------------------------------------------------------------------------


def test_tag50_alert_names_disjoint_from_tag45(
    alerts_by_name: dict, tag50_alerts_by_name: dict
):
    # Tag-50 original-alarm names start with "WakirWelle". The
    # Tag-45 marathon-aggregate names start with "WakirPhase3".
    # The two name-prefixes MUST stay disjoint for the Tag-50
    # original-alarm set.
    #
    # Tag-76 cardinality-fix note: Tag-72/73/74/75 routing-
    # extension alerts also use the "WakirPhase3Welle*" prefix
    # because they semantically extend the marathon-aggregate
    # naming scheme (positive-state + warning counterparts). They
    # are FILTERED OUT of ``tag50_alerts_by_name`` by the fixture
    # so this disjointness assertion holds for the original
    # Tag-50 alarm-set only.
    tag45_names = {
        n for n in alerts_by_name if n.startswith("WakirPhase3")
    }
    tag50_names = set(tag50_alerts_by_name)
    overlap = tag45_names & tag50_names
    assert not overlap, (
        f"Tag-45 ('WakirPhase3*') and Tag-50 ('WakirWelle*') alert "
        f"names overlap: {overlap}"
    )


def test_tag50_count_equals_eighteen(tag50_alerts_by_name: dict):
    # 2 + 2 + 3 + 3 + 3 + 2 + 3 = 18 Tag-50 alarms.
    assert len(tag50_alerts_by_name) == 18, (
        f"Tag-50 expected 18 welle-scoped alerts (2+2+3+3+3+2+3); "
        f"got {len(tag50_alerts_by_name)}"
    )


# ---------------------------------------------------------------------------
# Tag-76 cardinality-fix Anti-Regression Pins (Noa SRE)
#
# These tests pin the Tag-72/73/74/75 routing-extension alerts at
# the SOURCE so a future welle-routing-extension cannot silently
# slip into the welle-N-alerts groups and re-overrun the max-count
# cap. If somebody adds another ``WakirPhase3Welle*`` extension,
# they MUST update ``_TAG7X_EXTENSIONS`` and the per-welle
# ``_TAG7X_EXTENSION_COUNT_PER_WELLE`` (and bump
# ``_TAG50_GROUP_CONTRACT`` max) -- enforced here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "group_name", sorted(_TAG7X_EXTENSION_COUNT_PER_WELLE)
)
def test_tag7x_extension_count_pinned_per_welle(
    welle_group_all_alerts_by_name: dict,
    groups_by_name: dict,
    group_name: str,
):
    # For each welle-N-alerts group: count alerts that are NOT in
    # the Tag-50 original-set. That residual must match the pinned
    # Tag-7X extension-count.
    rules = groups_by_name[group_name]["rules"]
    tag50_in_group = {
        r["alert"] for r in rules if r["alert"] in _TAG50_ALERTS
    }
    extensions_in_group = {
        r["alert"] for r in rules if r["alert"] not in _TAG50_ALERTS
    }
    expected = _TAG7X_EXTENSION_COUNT_PER_WELLE[group_name]
    assert len(extensions_in_group) == expected, (
        f"{group_name}: pinned Tag-7X extension-count {expected} "
        f"!= actual {len(extensions_in_group)}; "
        f"tag50_in_group={sorted(tag50_in_group)}, "
        f"extensions_in_group={sorted(extensions_in_group)}"
    )


def test_tag7x_extension_inventory_exhaustive(
    welle_group_all_alerts_by_name: dict,
):
    # Every alert in the welle-N-alerts groups must be EITHER a
    # Tag-50 original OR a pinned Tag-7X extension. No drift.
    all_names = set(welle_group_all_alerts_by_name)
    accounted = set(_TAG50_ALERTS) | set(_TAG7X_EXTENSIONS)
    drift = all_names - accounted
    assert not drift, (
        f"Unaccounted alerts in welle-N-alerts groups (not Tag-50 "
        f"original and not pinned Tag-7X extension): {sorted(drift)}; "
        f"add to _TAG7X_EXTENSIONS and bump _TAG50_GROUP_CONTRACT max"
    )


def test_tag7x_extension_total_count_equals_eight(
    welle_group_all_alerts_by_name: dict,
):
    # 0+0+0+2+2+2+2 = 8 Tag-7X routing-extensions total.
    found = {
        n for n in welle_group_all_alerts_by_name if n in _TAG7X_EXTENSIONS
    }
    expected_total = sum(_TAG7X_EXTENSION_COUNT_PER_WELLE.values())
    assert len(found) == expected_total == 8, (
        f"Tag-7X extension total: expected {expected_total}=8; "
        f"got {len(found)}: {sorted(found)}"
    )


@pytest.mark.parametrize(
    "alert_name,expected_tag", sorted(_TAG7X_EXTENSIONS.items())
)
def test_tag7x_extension_uses_wakirphase3_prefix(
    alert_name: str, expected_tag: str
):
    # Pin the naming-convention: Tag-7X routing-extension alerts
    # MUST use the "WakirPhase3Welle*" prefix (they semantically
    # extend the marathon-aggregate naming scheme).
    assert alert_name.startswith("WakirPhase3Welle"), (
        f"Tag-7X extension {alert_name} ({expected_tag}) must use "
        f"'WakirPhase3Welle' prefix"
    )


def test_tag50_group_contract_max_accommodates_pinned_extensions():
    # Cross-check: _TAG50_GROUP_CONTRACT max-count per welle MUST
    # be >= Tag-50-originals-count + Tag-7X-extensions-count.
    # (Headroom above the actual count is allowed -- the Tag-50
    # original contract has welle-1/2/3/6 at max=3 even though
    # they only carry 2 originals + 0 extensions, for future
    # Tag-50-aligned additions.)
    tag50_per_welle: dict[str, int] = {}
    for _alert, welle in _TAG50_ALERTS.items():
        group_name = f"{welle}-alerts"
        tag50_per_welle[group_name] = tag50_per_welle.get(group_name, 0) + 1

    for group_name, (_min_n, max_n, _) in _TAG50_GROUP_CONTRACT.items():
        tag50_n = tag50_per_welle.get(group_name, 0)
        tag7x_n = _TAG7X_EXTENSION_COUNT_PER_WELLE[group_name]
        required_min_max = tag50_n + tag7x_n
        assert max_n >= required_min_max, (
            f"{group_name}: _TAG50_GROUP_CONTRACT max={max_n} but "
            f"_TAG50_ALERTS({tag50_n}) + "
            f"_TAG7X_EXTENSION_COUNT_PER_WELLE({tag7x_n}) = "
            f"{required_min_max} required"
        )


# ---------------------------------------------------------------------------
# Notify-catalog drift-detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alert_name", sorted(_TAG50_ALERTS))
def test_catalog_references_each_tag50_alert(
    catalog_text: str, alert_name: str
):
    assert alert_name in catalog_text, (
        f"Tag-50 alert {alert_name} not mentioned in notify-catalog; "
        f"drift between YAML and Markdown"
    )


def test_catalog_section_5_welle_n_header_present(catalog_text: str):
    # Section 5 added by Tag-50; header text contract.
    assert "Tag-50" in catalog_text
    assert "Welle-N" in catalog_text or "welle-n" in catalog_text.lower()


def test_catalog_lists_each_welle_with_kw_anchor(catalog_text: str):
    # Every welle-N must appear with its KW-week label in the
    # Tag-50 section so the catalog is operator-readable.
    for welle, (kw, _) in _WELLE_KW_TOPOLOGY.items():
        assert welle in catalog_text, (
            f"welle anchor {welle} missing from notify-catalog"
        )
        assert kw in catalog_text, (
            f"kw-week anchor {kw} missing from notify-catalog"
        )
