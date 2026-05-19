# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-53 Phase-3-Marathon SLO Burn-Rate Alert-Rules.

Validates ``dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml``
(Tag-53, Noa-SRE). The file is the Multi-Window Multi-Burn-Rate
companion to the Tag-52 SLI/SLO catalogue and SLO-Dashboard.

The contract this test enforces:

  * Each cutover-blocking SLO from the Tag-52 catalogue (SLO-1, 2,
    5, 6, 7) has exactly one fast-burn page-alert and exactly one
    slow-burn ticket-alert.
  * The informational SLOs (SLO-3, SLO-4) intentionally have NO
    burn-rate alerts here (alert-fatigue avoidance per the Tag-52
    catalogue §2.3 + §2.4).
  * Fast-burn alerts use (1h, 5m) Multi-Window pairs per Google
    SRE Workbook §5; slow-burn alerts use (6h, 30m) pairs.
  * Every alert carries the owner=noa-sre + adr=adr-0066 +
    slo=slo-N + burn_rate_class=fast|slow labels for AlertManager
    routing.
  * Every alert has a runbook_url + dashboard_url (fast-burn only;
    slow-burn may omit dashboard_url) + notify_path annotation.
  * No name collisions with the Tag-40/45/50 event-based alert
    file (``dashboards/phase-3-marathon-alerts.yaml``).

Sandbox boundary: pure stdlib + ``yaml``. No Prometheus, no
Grafana, no network.

Anchors:
  - Tag-53 auftrag (Noa-SRE, SLO-Burn-Rate-Alert-Rules).
  - Tag-52 SLO catalogue (docs/observability/sli-slo-phase-3-marathon.md).
  - Tag-52 SLO dashboard (dashboards/phase-3-marathon-slo-final.json).
  - Google SRE Workbook §5 ("Alerting on SLOs").
"""

from __future__ import annotations

import pathlib

import pytest
import yaml


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BURN_RATE_PATH = (
    _REPO_ROOT
    / "dashboards"
    / "phase-3-marathon-slo-burn-rate-alerts.yaml"
)
_TAG40_45_50_PATH = (
    _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
)


# ---------------------------------------------------------------------------
# Tag-53 alert-name + contract table
# ---------------------------------------------------------------------------


# Each cutover-blocking SLO (SLO-1, 2, 5, 6, 7) gets exactly one fast
# page + one slow ticket. SLO-3 (Alert-Volume-Trend) and SLO-4
# (AR-Hand-Stop-Trigger-Rate) are intentionally absent per the
# Tag-52 catalogue (informational SLOs; no burn-rate alerts).
_TAG53_BURN_RATE_ALERTS: dict[str, dict[str, str]] = {
    "WakirSlo1WelleCutoverSuccessRateFastBurn": {
        "slo": "slo-1",
        "burn_rate_class": "fast",
        "severity": "page",
        "for_window": "2m",
        "long_window": "1h",
        "short_window": "5m",
    },
    "WakirSlo1WelleCutoverSuccessRateSlowBurn": {
        "slo": "slo-1",
        "burn_rate_class": "slow",
        "severity": "ticket",
        "for_window": "15m",
        "long_window": "6h",
        "short_window": "30m",
    },
    "WakirSlo2CrossModulDriftFastBurn": {
        "slo": "slo-2",
        "burn_rate_class": "fast",
        "severity": "page",
        "for_window": "2m",
        "long_window": "1h",
        "short_window": "5m",
    },
    "WakirSlo2CrossModulDriftSlowBurn": {
        "slo": "slo-2",
        "burn_rate_class": "slow",
        "severity": "ticket",
        "for_window": "15m",
        "long_window": "6h",
        "short_window": "30m",
    },
    "WakirSlo5BuildReproducibilityFastBurn": {
        "slo": "slo-5",
        "burn_rate_class": "fast",
        "severity": "page",
        "for_window": "2m",
        "long_window": "1h",
        "short_window": "5m",
    },
    "WakirSlo5BuildReproducibilitySlowBurn": {
        "slo": "slo-5",
        "burn_rate_class": "slow",
        "severity": "ticket",
        "for_window": "15m",
        "long_window": "6h",
        "short_window": "30m",
    },
    "WakirSlo6SbomVerdictFastBurn": {
        "slo": "slo-6",
        "burn_rate_class": "fast",
        "severity": "page",
        "for_window": "2m",
        "long_window": "1h",
        "short_window": "5m",
    },
    "WakirSlo6SbomPerBinaryDriftSlowBurn": {
        "slo": "slo-6",
        "burn_rate_class": "slow",
        "severity": "ticket",
        "for_window": "15m",
        "long_window": "6h",
        "short_window": "30m",
    },
    "WakirSlo7CosignOidcDriftFastBurn": {
        "slo": "slo-7",
        "burn_rate_class": "fast",
        "severity": "page",
        "for_window": "2m",
        "long_window": "1h",
        "short_window": "5m",
    },
    "WakirSlo7CosignOidcDriftSlowBurn": {
        "slo": "slo-7",
        "burn_rate_class": "slow",
        "severity": "ticket",
        "for_window": "15m",
        "long_window": "6h",
        "short_window": "30m",
    },
}


_TAG53_GROUP_NAMES = {
    "slo-1-welle-cutover-success-rate-burn-rate",
    "slo-2-cross-modul-drift-burn-rate",
    "slo-5-build-reproducibility-burn-rate",
    "slo-6-sbom-verdict-burn-rate",
    "slo-7-cosign-oidc-drift-burn-rate",
}


_CUTOVER_BLOCKING_SLOS = {"slo-1", "slo-2", "slo-5", "slo-6", "slo-7"}
_INFORMATIONAL_SLOS = {"slo-3", "slo-4"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def burn_rate_yaml() -> dict:
    return yaml.safe_load(_BURN_RATE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def alerts_by_name(burn_rate_yaml: dict) -> dict[str, dict]:
    return {
        r["alert"]: r
        for g in burn_rate_yaml["groups"]
        for r in g["rules"]
    }


@pytest.fixture(scope="module")
def tag40_45_50_yaml() -> dict:
    return yaml.safe_load(
        _TAG40_45_50_PATH.read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_burn_rate_file_exists():
    assert _BURN_RATE_PATH.exists(), (
        f"Tag-53 burn-rate alerts file missing: {_BURN_RATE_PATH}"
    )


def test_burn_rate_yaml_parses(burn_rate_yaml: dict):
    assert isinstance(burn_rate_yaml, dict)
    assert "groups" in burn_rate_yaml
    assert len(burn_rate_yaml["groups"]) == 5, (
        "Expected exactly 5 SLO groups (SLO-1, 2, 5, 6, 7); "
        f"got {len(burn_rate_yaml['groups'])}"
    )


def test_burn_rate_group_names_match_contract(burn_rate_yaml: dict):
    group_names = {g["name"] for g in burn_rate_yaml["groups"]}
    assert group_names == _TAG53_GROUP_NAMES, (
        f"Group-name mismatch: expected={_TAG53_GROUP_NAMES} "
        f"got={group_names}"
    )


def test_burn_rate_alert_count_is_ten(burn_rate_yaml: dict):
    # 5 cutover-blocking SLOs x (1 fast + 1 slow) = 10 alerts.
    count = sum(len(g["rules"]) for g in burn_rate_yaml["groups"])
    assert count == 10, (
        f"Expected exactly 10 burn-rate alerts (5 SLOs x 2 windows); "
        f"got {count}"
    )


def test_burn_rate_alert_names_unique(burn_rate_yaml: dict):
    names = [
        r["alert"]
        for g in burn_rate_yaml["groups"]
        for r in g["rules"]
    ]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"duplicate alert names: {duplicates}"


def test_burn_rate_no_collision_with_tag40_45_50(
    burn_rate_yaml: dict, tag40_45_50_yaml: dict
):
    """No alert-name collision with the event-based alert file."""
    burn = {
        r["alert"]
        for g in burn_rate_yaml["groups"]
        for r in g["rules"]
    }
    event = {
        r["alert"]
        for g in tag40_45_50_yaml["groups"]
        for r in g["rules"]
    }
    collision = burn & event
    assert not collision, (
        f"Tag-53 burn-rate alert-name collision with Tag-40/45/50 "
        f"event-based alerts: {collision}"
    )


# ---------------------------------------------------------------------------
# Per-alert contract (parametrized over the 10 alerts)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_present(alerts_by_name: dict, alert_name: str):
    assert alert_name in alerts_by_name, (
        f"Tag-53 burn-rate alert missing: {alert_name}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_has_owner_noa(
    alerts_by_name: dict, alert_name: str
):
    rule = alerts_by_name[alert_name]
    assert rule["labels"].get("owner") == "noa-sre", (
        f"{alert_name} missing owner=noa-sre label"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_has_adr_anchor(
    alerts_by_name: dict, alert_name: str
):
    rule = alerts_by_name[alert_name]
    assert rule["labels"].get("adr") == "adr-0066", (
        f"{alert_name} must anchor adr-0066; got "
        f"adr={rule['labels'].get('adr')}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_severity_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG53_BURN_RATE_ALERTS[alert_name]["severity"]
    actual = alerts_by_name[alert_name]["labels"].get("severity")
    assert actual == expected, (
        f"{alert_name} severity mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_burn_rate_class_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG53_BURN_RATE_ALERTS[alert_name]["burn_rate_class"]
    actual = alerts_by_name[alert_name]["labels"].get("burn_rate_class")
    assert actual == expected, (
        f"{alert_name} burn_rate_class mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_slo_label_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG53_BURN_RATE_ALERTS[alert_name]["slo"]
    actual = alerts_by_name[alert_name]["labels"].get("slo")
    assert actual == expected, (
        f"{alert_name} slo label mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_for_window_matches_contract(
    alerts_by_name: dict, alert_name: str
):
    expected = _TAG53_BURN_RATE_ALERTS[alert_name]["for_window"]
    actual = alerts_by_name[alert_name]["for"]
    assert actual == expected, (
        f"{alert_name} for-window mismatch: expected={expected} "
        f"got={actual}"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_uses_multi_window_pair(
    alerts_by_name: dict, alert_name: str
):
    """Burn-rate alerts MUST reference both a long and a short window
    in the expr (Multi-Window Multi-Burn-Rate per Google SRE
    Workbook §5)."""
    expr = alerts_by_name[alert_name]["expr"]
    long_window = _TAG53_BURN_RATE_ALERTS[alert_name]["long_window"]
    short_window = _TAG53_BURN_RATE_ALERTS[alert_name]["short_window"]
    assert f"[{long_window}]" in expr, (
        f"{alert_name} must reference long window [{long_window}] "
        f"per Multi-Window contract; expr did not contain it"
    )
    assert f"[{short_window}]" in expr, (
        f"{alert_name} must reference short window [{short_window}] "
        f"per Multi-Window contract; expr did not contain it"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_expr_is_conjunction(
    alerts_by_name: dict, alert_name: str
):
    """Multi-Window requires BOTH windows to hold => an `and` in the
    expr (per Google SRE Workbook §5)."""
    expr = alerts_by_name[alert_name]["expr"].lower()
    # Tolerate `and` on its own line in a YAML block scalar.
    tokens = expr.split()
    assert "and" in tokens, (
        f"{alert_name} expr must be a Multi-Window conjunction "
        f"(`and` between long + short window predicates); not found"
    )


@pytest.mark.parametrize("alert_name", sorted(_TAG53_BURN_RATE_ALERTS.keys()))
def test_tag53_alert_has_annotations(
    alerts_by_name: dict, alert_name: str
):
    ann = alerts_by_name[alert_name].get("annotations", {})
    assert ann.get("summary"), f"{alert_name} missing summary"
    assert ann.get("description"), f"{alert_name} missing description"
    assert ann.get("runbook_url"), f"{alert_name} missing runbook_url"
    assert ann.get("notify_path"), f"{alert_name} missing notify_path"


# ---------------------------------------------------------------------------
# Per-class invariants
# ---------------------------------------------------------------------------


def test_fast_burn_pages_only(alerts_by_name: dict):
    """All fast-burn alerts are severity=page (Google SRE Workbook
    §5 contract)."""
    for name, spec in _TAG53_BURN_RATE_ALERTS.items():
        if spec["burn_rate_class"] == "fast":
            sev = alerts_by_name[name]["labels"].get("severity")
            assert sev == "page", (
                f"Fast-burn {name} must be severity=page; got {sev}"
            )


def test_slow_burn_tickets_only(alerts_by_name: dict):
    """All slow-burn alerts are severity=ticket."""
    for name, spec in _TAG53_BURN_RATE_ALERTS.items():
        if spec["burn_rate_class"] == "slow":
            sev = alerts_by_name[name]["labels"].get("severity")
            assert sev == "ticket", (
                f"Slow-burn {name} must be severity=ticket; got {sev}"
            )


def test_fast_burn_uses_1h_and_5m_windows(alerts_by_name: dict):
    """All fast-burn alerts use the canonical (1h, 5m) pair."""
    for name, spec in _TAG53_BURN_RATE_ALERTS.items():
        if spec["burn_rate_class"] == "fast":
            expr = alerts_by_name[name]["expr"]
            assert "[1h]" in expr and "[5m]" in expr, (
                f"Fast-burn {name} must use (1h, 5m) windows"
            )


def test_slow_burn_uses_6h_and_30m_windows(alerts_by_name: dict):
    """All slow-burn alerts use the canonical (6h, 30m) pair."""
    for name, spec in _TAG53_BURN_RATE_ALERTS.items():
        if spec["burn_rate_class"] == "slow":
            expr = alerts_by_name[name]["expr"]
            assert "[6h]" in expr and "[30m]" in expr, (
                f"Slow-burn {name} must use (6h, 30m) windows"
            )


# ---------------------------------------------------------------------------
# Coverage invariants
# ---------------------------------------------------------------------------


def test_all_cutover_blocking_slos_have_fast_burn(
    alerts_by_name: dict,
):
    fast_slos = {
        rule["labels"]["slo"]
        for rule in alerts_by_name.values()
        if rule["labels"].get("burn_rate_class") == "fast"
    }
    missing = _CUTOVER_BLOCKING_SLOS - fast_slos
    assert not missing, (
        f"Cutover-blocking SLOs missing fast-burn alerts: {missing}"
    )


def test_all_cutover_blocking_slos_have_slow_burn(
    alerts_by_name: dict,
):
    slow_slos = {
        rule["labels"]["slo"]
        for rule in alerts_by_name.values()
        if rule["labels"].get("burn_rate_class") == "slow"
    }
    missing = _CUTOVER_BLOCKING_SLOS - slow_slos
    assert not missing, (
        f"Cutover-blocking SLOs missing slow-burn alerts: {missing}"
    )


def test_informational_slos_have_no_burn_rate_alerts(
    alerts_by_name: dict,
):
    """SLO-3 (Alert-Volume-Trend) and SLO-4 (AR-Hand-Stop-Trigger-
    Rate) are informational per the Tag-52 catalogue and MUST NOT
    have burn-rate alerts (alert-fatigue avoidance)."""
    present_slos = {
        rule["labels"].get("slo") for rule in alerts_by_name.values()
    }
    violations = present_slos & _INFORMATIONAL_SLOS
    assert not violations, (
        f"Informational SLOs must NOT have burn-rate alerts "
        f"(Tag-52 §2.3/§2.4 alert-fatigue avoidance); found: {violations}"
    )


# ---------------------------------------------------------------------------
# Per-SLO expr semantic checks
# ---------------------------------------------------------------------------


def test_slo1_uses_fallback_and_decisions_counters(
    alerts_by_name: dict,
):
    for name in (
        "WakirSlo1WelleCutoverSuccessRateFastBurn",
        "WakirSlo1WelleCutoverSuccessRateSlowBurn",
    ):
        expr = alerts_by_name[name]["expr"]
        assert "persona_engine_phase_3c_welle_fallback_total" in expr
        assert "persona_engine_phase_3c_welle_decisions_total" in expr


def test_slo1_fast_burn_threshold_is_14_4(alerts_by_name: dict):
    """Google SRE Workbook §5: 14.4x is the canonical fast-burn
    threshold for a 30d/99% SLO at the 1h window (2% of budget
    consumed in 1h)."""
    expr = alerts_by_name[
        "WakirSlo1WelleCutoverSuccessRateFastBurn"
    ]["expr"]
    assert "14.4" in expr, (
        "SLO-1 fast-burn must use 14.4x budget rate per Google SRE "
        "Workbook §5; expr did not contain '14.4'"
    )


def test_slo1_slow_burn_threshold_is_6(alerts_by_name: dict):
    """Google SRE Workbook §5: 6x is the canonical slow-burn
    threshold for a 30d/99% SLO at the 6h window (5% of budget
    consumed in 6h)."""
    expr = alerts_by_name[
        "WakirSlo1WelleCutoverSuccessRateSlowBurn"
    ]["expr"]
    # The literal must be present (allow either `6 *` or `> 6 *`
    # context). Use a precise substring that is hard to introduce
    # by accident in any other context in this expr.
    assert "(6 * 0.01)" in expr, (
        "SLO-1 slow-burn must use 6x budget rate per Google SRE "
        "Workbook §5; expr did not contain '(6 * 0.01)'"
    )


def test_slo2_uses_cross_modul_drift_counter(alerts_by_name: dict):
    for name in (
        "WakirSlo2CrossModulDriftFastBurn",
        "WakirSlo2CrossModulDriftSlowBurn",
    ):
        expr = alerts_by_name[name]["expr"]
        assert "wakir_cross_modul_drift_count" in expr
        assert "increase(" in expr, (
            f"{name} hard-zero SLO must use increase(...) over the "
            "burn windows"
        )


def test_slo5_uses_build_reproducibility_drift_gauge(
    alerts_by_name: dict,
):
    for name in (
        "WakirSlo5BuildReproducibilityFastBurn",
        "WakirSlo5BuildReproducibilitySlowBurn",
    ):
        expr = alerts_by_name[name]["expr"]
        assert "wakir_build_reproducibility_drift_count" in expr
        assert "max_over_time(" in expr, (
            f"{name} gauge-shaped SLO must use max_over_time over "
            "the burn windows"
        )


def test_slo6_fast_burn_uses_aggregate_verdict(alerts_by_name: dict):
    expr = alerts_by_name["WakirSlo6SbomVerdictFastBurn"]["expr"]
    assert "wakir_sbom_verification_aggregate_verdict" in expr
    assert "min_over_time(" in expr, (
        "SLO-6 fast-burn must use min_over_time on the aggregate "
        "verdict (==0 == FAIL must be sustained across the window)"
    )


def test_slo6_slow_burn_uses_per_binary_drift(alerts_by_name: dict):
    expr = alerts_by_name[
        "WakirSlo6SbomPerBinaryDriftSlowBurn"
    ]["expr"]
    assert (
        "wakir_sbom_verification_per_binary_drift_count" in expr
    )


def test_slo7_fast_burn_covers_aggregate_or_trust_root(
    alerts_by_name: dict,
):
    """SLO-7 = aggregate==0 AND trust_root==1. Burn = either
    aggregate>0 OR trust_root==0; the expr must reference both
    gauges and contain `or` between them."""
    expr = alerts_by_name["WakirSlo7CosignOidcDriftFastBurn"]["expr"]
    assert "wakir_cosign_drift_probe_aggregate" in expr
    assert "wakir_cosign_drift_probe_trust_root" in expr
    assert "or" in expr.lower().split(), (
        "SLO-7 fast-burn must be (aggregate-drift OR trust-root-"
        "rotation); `or` not found"
    )


def test_slo7_slow_burn_uses_per_binary_drift(alerts_by_name: dict):
    expr = alerts_by_name["WakirSlo7CosignOidcDriftSlowBurn"]["expr"]
    assert "wakir_cosign_drift_probe_per_binary" in expr


# ---------------------------------------------------------------------------
# Group interval invariants
# ---------------------------------------------------------------------------


def test_slo1_slo2_groups_scrape_at_30s(burn_rate_yaml: dict):
    """SLO-1 + SLO-2 are stream-driven; 30s interval is sufficient
    for the 1h/5m fast-burn window and avoids excessive PromQL eval."""
    by_name = {g["name"]: g for g in burn_rate_yaml["groups"]}
    for name in (
        "slo-1-welle-cutover-success-rate-burn-rate",
        "slo-2-cross-modul-drift-burn-rate",
    ):
        assert by_name[name].get("interval") == "30s", (
            f"{name} must scrape at 30s; got {by_name[name].get('interval')}"
        )


def test_slo5_slo6_slo7_groups_scrape_at_1m(burn_rate_yaml: dict):
    """SLO-5/6/7 are CI-run-driven; 1m interval matches the cadence
    at which the verifier scripts emit the gauges."""
    by_name = {g["name"]: g for g in burn_rate_yaml["groups"]}
    for name in (
        "slo-5-build-reproducibility-burn-rate",
        "slo-6-sbom-verdict-burn-rate",
        "slo-7-cosign-oidc-drift-burn-rate",
    ):
        assert by_name[name].get("interval") == "1m", (
            f"{name} must scrape at 1m; got {by_name[name].get('interval')}"
        )
