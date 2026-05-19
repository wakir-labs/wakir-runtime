# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-64 Cutover-Day-Morgen Trinary-Verdict-Reactive-Routing tests.

Covers (>= 12 tests; ships 16):

  T01  Bridge module importable; trinary constants present (3 classes).
  T02  ROUTING_CLASS_CHANNELS table shape: 3 classes, each tuple non-
       empty, each class has an escalation entry.
  T03  EXPECTED_TRINARY_ROUTING binds the 3 alertnames to the 3
       canonical routing_class values.
  T04  ALERT_CATALOG has all 3 Tag-64 entries with the expected
       severity ladder (info / page / page-storm).
  T05  `validate_trinary_routing_table_shape` returns all-empty lists
       on the real bridge module (no missing classes/channels/esc).
  T06  Channel-set for `ops-on-call-plus-management` is a superset of
       `ops-on-call` channels in spirit (page + ar-hand ntfy).
  T07  Escalation deadline: standard=0, ops-on-call=600, ops-on-call-
       plus-management=300 (BLOCK faster than CAUTION because BLOCK
       gates the operator-trigger pipeline).
  T08  PROM_SEVERITY_TO_NOTIFY maps `page-storm` -> `page` (emitter
       vocabulary tops out at page).
  T09  `lookup_routing_class_channels` returns a tuple for every
       VALID_ROUTING_CLASSES member and () for unknown class.
  T10  Alerts YAML contains all 3 trinary alertnames as top-level
       `- alert: <Name>` lines.
  T11  Each trinary alert in the YAML carries the EXPECTED routing_class
       label value, a verdict_class label, and tag: tag-64.
  T12  Each trinary alert in the YAML uses the recording-rule
       `wakir_cutover_day_morgen_verdict_class` as its expr-source.
  T13  `map_alert_to_event_kwargs` enriches a synthetic CAUTION
       AlertManager envelope with notify_channels + escalation.
  T14  `map_alert_to_event_kwargs` enriches a synthetic BLOCK
       envelope with the page-storm channel-set.
  T15  `map_alert_to_event_kwargs` does NOT add notify_channels when
       the routing_class label is missing OR unknown.
  T16  CLI `validate-trinary-routing` exits 0 on real bridge module
       and emits a parseable JSON envelope with empty drift lists.

Anchor: Tag-64 Marathon-Continuous-Mode Pre-KW-24 Alert-Routing
        Cutover-Day-Morgen Trinary-Verdict-Reactive-Wiring.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PATH = REPO_ROOT / "scripts/observability/alert-rule-to-mira-notify-bridge.py"
ALERTS_PATH = REPO_ROOT / "dashboards/phase-3-marathon-alerts.yaml"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github/workflows/cutover-day-morgen-trinary-routing-validate.yml"
)


def _load_bridge():
    mod_name = "alert_rule_to_mira_notify_bridge"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(BRIDGE_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bridge():
    return _load_bridge()


# ---------------------------------------------------------------------------
# T01 - constants present
# ---------------------------------------------------------------------------


def test_t01_trinary_constants_present(bridge) -> None:
    assert bridge.ROUTING_CLASS_STANDARD == "standard"
    assert bridge.ROUTING_CLASS_OPS_ON_CALL == "ops-on-call"
    assert (
        bridge.ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT
        == "ops-on-call-plus-management"
    )
    assert isinstance(bridge.VALID_ROUTING_CLASSES, frozenset)
    # Tag-64 baseline: standard / ops-on-call / ops-on-call-plus-management.
    # Tag-71 extends with welle-3-pre-auditor-info (positive ack for
    # Welle-3 external Pre-Auditor designation). The Tag-64 trinary
    # contract still holds for the cutover-day-morgen verdict surface;
    # the new routing class is additive and orthogonal.
    assert bridge.VALID_ROUTING_CLASSES >= {
        bridge.ROUTING_CLASS_STANDARD,
        bridge.ROUTING_CLASS_OPS_ON_CALL,
        bridge.ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT,
    }
    assert isinstance(bridge.TRINARY_ROUTING_ALERTNAMES, frozenset)
    assert len(bridge.TRINARY_ROUTING_ALERTNAMES) == 3


# ---------------------------------------------------------------------------
# T02 - routing-class channels table shape
# ---------------------------------------------------------------------------


def test_t02_routing_class_channels_shape(bridge) -> None:
    table = bridge.ROUTING_CLASS_CHANNELS
    assert set(table.keys()) == bridge.VALID_ROUTING_CLASSES
    for cls, channels in table.items():
        assert isinstance(channels, tuple)
        assert len(channels) >= 1, f"{cls!r} has empty channel-tuple"
        assert all(isinstance(c, str) and c for c in channels)
    esc = bridge.ROUTING_CLASS_ESCALATION_SECONDS
    assert set(esc.keys()) == bridge.VALID_ROUTING_CLASSES


# ---------------------------------------------------------------------------
# T03 - expected trinary routing alertname<->class binding
# ---------------------------------------------------------------------------


def test_t03_expected_trinary_routing_binding(bridge) -> None:
    expected = bridge.EXPECTED_TRINARY_ROUTING
    assert expected == {
        "WakirCutoverDayMorgenVerdictReady": "standard",
        "WakirCutoverDayMorgenVerdictCaution": "ops-on-call",
        "WakirCutoverDayMorgenVerdictBlock": "ops-on-call-plus-management",
    }
    assert set(expected.keys()) == bridge.TRINARY_ROUTING_ALERTNAMES


# ---------------------------------------------------------------------------
# T04 - alert-catalog severity ladder for the 3 Tag-64 entries
# ---------------------------------------------------------------------------


def test_t04_alert_catalog_severity_ladder(bridge) -> None:
    cat = bridge.ALERT_CATALOG
    assert cat["WakirCutoverDayMorgenVerdictReady"]["severity"] == "info"
    assert cat["WakirCutoverDayMorgenVerdictCaution"]["severity"] == "page"
    assert (
        cat["WakirCutoverDayMorgenVerdictBlock"]["severity"] == "page-storm"
    )
    for n in bridge.TRINARY_ROUTING_ALERTNAMES:
        url = cat[n]["runbook_url"]
        assert "cutover-day-morgen" in url, f"{n} runbook_url lacks anchor"


# ---------------------------------------------------------------------------
# T05 - validate_trinary_routing_table_shape returns all-empty
# ---------------------------------------------------------------------------


def test_t05_validate_trinary_routing_table_shape_clean(bridge) -> None:
    shape = bridge.validate_trinary_routing_table_shape()
    assert shape == {
        "missing_class": [],
        "missing_channels": [],
        "missing_escalation": [],
    }


# ---------------------------------------------------------------------------
# T06 - BLOCK channel-set includes pagerduty + ar-hand ntfy
# ---------------------------------------------------------------------------


def test_t06_block_channels_superset_in_spirit(bridge) -> None:
    block = set(
        bridge.ROUTING_CLASS_CHANNELS[
            bridge.ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT
        ]
    )
    on_call = set(
        bridge.ROUTING_CLASS_CHANNELS[bridge.ROUTING_CLASS_OPS_ON_CALL]
    )
    # BLOCK fan-out must include the SRE on-call PagerDuty + AR ntfy.
    assert "pagerduty:sre-oncall" in block
    assert "pagerduty:sre-oncall" in on_call
    assert "ntfy:ar-hand" in block
    assert "pagerduty:management" in block, "BLOCK must escalate to management"
    # BLOCK uses the hold-marker, CAUTION uses the plain append.
    assert "activity-log:hold-marker" in block
    assert "activity-log:append" in on_call


# ---------------------------------------------------------------------------
# T07 - escalation deadlines: standard=0, on-call=600, +mgmt=300
# ---------------------------------------------------------------------------


def test_t07_escalation_deadlines(bridge) -> None:
    esc = bridge.ROUTING_CLASS_ESCALATION_SECONDS
    assert esc[bridge.ROUTING_CLASS_STANDARD] == 0
    assert esc[bridge.ROUTING_CLASS_OPS_ON_CALL] == 600
    assert (
        esc[bridge.ROUTING_CLASS_OPS_ON_CALL_PLUS_MANAGEMENT] == 300
    ), "BLOCK escalation must be FASTER than CAUTION"


# ---------------------------------------------------------------------------
# T08 - PROM_SEVERITY_TO_NOTIFY caps page-storm at page
# ---------------------------------------------------------------------------


def test_t08_page_storm_maps_to_page(bridge) -> None:
    assert bridge.PROM_SEVERITY_TO_NOTIFY["page-storm"] == "page"
    # Existing mappings unchanged.
    assert bridge.PROM_SEVERITY_TO_NOTIFY["page"] == "page"
    assert bridge.PROM_SEVERITY_TO_NOTIFY["info"] == "info"
    assert bridge.PROM_SEVERITY_TO_NOTIFY["warning"] == "warning"


# ---------------------------------------------------------------------------
# T09 - lookup_routing_class_channels behaviour
# ---------------------------------------------------------------------------


def test_t09_lookup_routing_class_channels(bridge) -> None:
    for cls in bridge.VALID_ROUTING_CLASSES:
        channels = bridge.lookup_routing_class_channels(cls)
        assert isinstance(channels, tuple) and len(channels) >= 1
    assert bridge.lookup_routing_class_channels("nonexistent-class") == ()
    assert bridge.lookup_routing_class_escalation_seconds("nonexistent") == 0


# ---------------------------------------------------------------------------
# T10 - alerts YAML contains all 3 trinary alertnames
# ---------------------------------------------------------------------------


def test_t10_alerts_yaml_has_all_three_trinary_alerts() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    for name in (
        "WakirCutoverDayMorgenVerdictReady",
        "WakirCutoverDayMorgenVerdictCaution",
        "WakirCutoverDayMorgenVerdictBlock",
    ):
        assert (
            f"- alert: {name}" in text
        ), f"alerts YAML missing {name}"


# ---------------------------------------------------------------------------
# T11 - each trinary alert carries the expected labels
# ---------------------------------------------------------------------------


def test_t11_each_alert_has_expected_labels(bridge) -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^\s*- alert:\s*", text)
    by_name: dict[str, str] = {}
    for block in blocks:
        m = re.match(r"([A-Za-z0-9_]+)", block)
        if not m:
            continue
        by_name[m.group(1)] = block

    for alert_name, expected_class in bridge.EXPECTED_TRINARY_ROUTING.items():
        block = by_name.get(alert_name)
        assert block is not None, f"{alert_name} not found in YAML"
        m_rc = re.search(
            r"(?m)^\s*routing_class:\s*([A-Za-z0-9_-]+)\s*$",
            block,
        )
        assert m_rc is not None, f"{alert_name} missing routing_class label"
        assert m_rc.group(1) == expected_class, (
            f"{alert_name}: routing_class={m_rc.group(1)!r} "
            f"!= expected {expected_class!r}"
        )
        assert re.search(
            r"(?m)^\s*verdict_class:\s*[A-Za-z0-9_-]+\s*$", block
        ), f"{alert_name} missing verdict_class label"
        assert re.search(
            r"(?m)^\s*tag:\s*tag-64\s*$", block
        ), f"{alert_name} missing tag: tag-64 label"


# ---------------------------------------------------------------------------
# T12 - each trinary alert sources the canonical recording rule
# ---------------------------------------------------------------------------


def test_t12_alerts_use_canonical_recording_rule() -> None:
    text = ALERTS_PATH.read_text(encoding="utf-8")
    # All three alerts should reference the same recording-rule name.
    blocks = re.split(r"(?m)^\s*- alert:\s*", text)
    for block in blocks:
        m = re.match(
            r"(WakirCutoverDayMorgenVerdict(?:Ready|Caution|Block))",
            block,
        )
        if not m:
            continue
        # Expr line must reference the recording rule.
        m_expr = re.search(
            r"(?m)^\s*expr:\s*(wakir_cutover_day_morgen_verdict_class == \d)",
            block,
        )
        assert m_expr is not None, (
            f"{m.group(1)} expr does not reference "
            f"wakir_cutover_day_morgen_verdict_class"
        )


# ---------------------------------------------------------------------------
# T13 - map_alert_to_event_kwargs enriches CAUTION with channels + esc
# ---------------------------------------------------------------------------


def _synthetic_alert(name: str, routing_class: str | None) -> dict:
    labels = {
        "alertname": name,
        "severity": "page",
        "verdict_class": "caution",
        "tag": "tag-64",
    }
    if routing_class is not None:
        labels["routing_class"] = routing_class
    return {
        "status": "firing",
        "labels": labels,
        "annotations": {
            "summary": f"{name} test fixture summary",
        },
        "startsAt": "2026-06-09T04:30:00Z",
    }


def test_t13_caution_envelope_enriched(bridge) -> None:
    alert = _synthetic_alert(
        "WakirCutoverDayMorgenVerdictCaution", "ops-on-call"
    )
    kwargs = bridge.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    labels = kwargs["labels"]
    channels = labels["notify_channels"].split(",")
    assert "pagerduty:sre-oncall" in channels
    assert "ntfy:ar-hand" in channels
    assert labels["escalation_after_seconds"] == "600"
    assert kwargs["severity"] == "page"


# ---------------------------------------------------------------------------
# T14 - BLOCK envelope gets page-storm channel-set
# ---------------------------------------------------------------------------


def test_t14_block_envelope_enriched(bridge) -> None:
    alert = _synthetic_alert(
        "WakirCutoverDayMorgenVerdictBlock",
        "ops-on-call-plus-management",
    )
    # BLOCK label severity should be page-storm; override the fixture.
    alert["labels"]["severity"] = "page-storm"
    alert["labels"]["verdict_class"] = "block"
    kwargs = bridge.map_alert_to_event_kwargs(alert)
    assert kwargs is not None
    labels = kwargs["labels"]
    channels = labels["notify_channels"].split(",")
    assert "pagerduty:sre-oncall" in channels
    assert "pagerduty:management" in channels
    assert "ntfy:ar-hand" in channels
    assert "activity-log:hold-marker" in channels
    assert labels["escalation_after_seconds"] == "300"
    # Severity maps page-storm -> page (emitter vocabulary cap).
    assert kwargs["severity"] == "page"


# ---------------------------------------------------------------------------
# T15 - no routing_class -> no notify_channels enrichment
# ---------------------------------------------------------------------------


def test_t15_missing_or_unknown_routing_class_skips_enrichment(bridge) -> None:
    # Missing label entirely.
    alert_missing = _synthetic_alert(
        "WakirCutoverDayMorgenVerdictReady", None
    )
    kwargs = bridge.map_alert_to_event_kwargs(alert_missing)
    assert kwargs is not None
    assert "notify_channels" not in kwargs["labels"]
    assert "escalation_after_seconds" not in kwargs["labels"]

    # Unknown routing class.
    alert_unknown = _synthetic_alert(
        "WakirCutoverDayMorgenVerdictReady", "freeform-class"
    )
    kwargs2 = bridge.map_alert_to_event_kwargs(alert_unknown)
    assert kwargs2 is not None
    assert "notify_channels" not in kwargs2["labels"]
    assert "escalation_after_seconds" not in kwargs2["labels"]


# ---------------------------------------------------------------------------
# T16 - CLI validate-trinary-routing exit 0 on real bridge module
# ---------------------------------------------------------------------------


def test_t16_cli_validate_trinary_routing_exit_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(BRIDGE_PATH), "validate-trinary-routing"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"validate-trinary-routing exit={result.returncode}; "
        f"stdout={result.stdout}; stderr={result.stderr}"
    )
    parsed = json.loads(result.stdout)
    assert parsed["missing_class"] == []
    assert parsed["missing_channels"] == []
    assert parsed["missing_escalation"] == []


# ---------------------------------------------------------------------------
# Workflow shape - the validator workflow exists and has the right
# trigger surface (NO push, NO schedule).
# ---------------------------------------------------------------------------


def test_workflow_exists_and_has_correct_trigger_surface() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "name: cutover-day-morgen-trinary-routing-validate" in text
    # pull_request: + workflow_dispatch: are required.
    assert re.search(r"(?m)^on:\s*$", text)
    assert "workflow_dispatch" in text
    assert "pull_request:" in text
    # Forbid push: and schedule: at the top-level `on:` block.
    # (we keep the check narrow: scan for `push:` / `schedule:` as
    # mapping-keys inside the on: block.)
    on_block = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "push:" not in on_block, "trinary-routing workflow MUST NOT use push:"
    assert (
        "schedule:" not in on_block
    ), "trinary-routing workflow MUST NOT use schedule:"
