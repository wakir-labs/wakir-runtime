#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for alert-rule-to-mira-notify-bridge.py (Tag-47).

Coverage targets:
* Pure-function core: ``lookup_catalog``, ``normalise_severity``,
  ``_truncate_summary``, ``map_alert_to_event_kwargs``,
  ``_normalise_starts_at``, ``iter_envelope_alerts``,
  ``extract_alert_names_from_rules_yaml``,
  ``audit_catalog_against_rules``.
* End-to-end I/O surface: ``route_envelope`` -> ``infra/notify-log.jsonl``
  + integration with the Tag-46 receiver materialisation.
* CLI: ``route --input`` + ``validate-catalog --rules``.
* Cross-validation: every alert in
  ``dashboards/phase-3-marathon-alerts.yaml`` is in the catalog.

Author: Noa Bergstroem (SRE)
Anchor: Tag-45 catalog PR #292; Tag-46 emitter+receiver PR #296;
        Tag-47 bridge substance.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (mirrors the emitter-test pattern; bridge file path has
# a hyphen).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_BRIDGE_PATH = (
    _REPO_ROOT / "scripts" / "observability" /
    "alert-rule-to-mira-notify-bridge.py"
)
_EMITTER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "mira-notify-emitter.py"
)
_RECEIVER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "mira-notify-receiver.py"
)
_RULES_PATH = _REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"

_spec = importlib.util.spec_from_file_location(
    "alert_rule_to_mira_notify_bridge", str(_BRIDGE_PATH)
)
assert _spec is not None and _spec.loader is not None
bridge = importlib.util.module_from_spec(_spec)
sys.modules["alert_rule_to_mira_notify_bridge"] = bridge
_spec.loader.exec_module(bridge)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def alert_a1_firing() -> dict:
    """Synthetic AlertManager v4 alert for A1 (CrossModulDriftPerWelle)."""
    return {
        "status": "firing",
        "labels": {
            "alertname": "WakirPhase3FailureModeA1CrossModulDriftPerWelle",
            "severity": "page",
            "source_welle": "welle-3",
            "target_welle": "welle-4",
            "phase": "phase-3-marathon",
            "owner": "noa-sre",
        },
        "annotations": {
            "summary": "Cross-Modul-Drift welle-3 -> welle-4 detected",
            "description": "drift counter > 0 for 2m on per-welle pair",
            "runbook_url": (
                "https://wakir-labs.example/runbooks/"
                "failure-mode-a1-cross-modul-drift"
            ),
        },
        "startsAt": "2026-05-18T10:11:12.345Z",
    }


@pytest.fixture
def alert_a5_firing() -> dict:
    return {
        "status": "firing",
        "labels": {
            "alertname": (
                "WakirPhase3FailureModeA5SelfReferenceTrapWelle3Critical"
            ),
            "severity": "page",
            "welle": "welle-3",
        },
        "annotations": {
            "summary": "Welle-3 audit-bridge rate-ratio >= 3 vs baseline",
        },
        "startsAt": "2026-05-18T10:11:12Z",
    }


@pytest.fixture
def alert_b3_warning() -> dict:
    return {
        "status": "firing",
        "labels": {
            "alertname": "WakirPhase3FailureModeB3Iia1130DefaultPath",
            "severity": "warning",
            "welle": "welle-3",
            "auditor": "henrik",
        },
        "annotations": {
            "summary": "Welle-3 IIA-1130 default path: Henrik self-signed",
        },
        "startsAt": "2026-05-18T10:11:12+00:00",
    }


@pytest.fixture
def alert_unknown() -> dict:
    return {
        "status": "firing",
        "labels": {
            "alertname": "SomeAdHocAlertNotInCatalog",
            "severity": "info",
        },
        "annotations": {
            "summary": "free-form alert",
        },
        "startsAt": "2026-05-18T10:11:12Z",
    }


@pytest.fixture
def alert_resolved(alert_a1_firing) -> dict:
    return {**alert_a1_firing, "status": "resolved"}


@pytest.fixture
def envelope_v4(alert_a1_firing, alert_a5_firing) -> dict:
    return {
        "version": "4",
        "groupKey": "phase-3-marathon-cross-modul-drift",
        "status": "firing",
        "alerts": [alert_a1_firing, alert_a5_firing],
    }


# ---------------------------------------------------------------------------
# Test 01: lookup_catalog hits Pre-Mortem table.
# ---------------------------------------------------------------------------


class TestLookupCatalog:
    def test_hit_pre_mortem(self):
        entry = bridge.lookup_catalog(
            "WakirPhase3FailureModeA1CrossModulDriftPerWelle"
        )
        assert entry is not None
        assert entry["failure_mode_id"] == "A1"
        assert entry["severity"] == "page"
        assert entry["runbook_url"].endswith(
            "failure-mode-a1-cross-modul-drift"
        )

    def test_hit_baseline(self):
        entry = bridge.lookup_catalog("WakirPhase3MarathonWelleRollback")
        assert entry is not None
        assert entry["failure_mode_id"] is None
        assert entry["severity"] == "page"

    def test_miss(self):
        assert bridge.lookup_catalog("CompletelyUnknownAlertName") is None


# ---------------------------------------------------------------------------
# Test 02: normalise_severity prefers Prometheus label.
# ---------------------------------------------------------------------------


class TestNormaliseSeverity:
    def test_prom_severity_wins(self):
        assert (
            bridge.normalise_severity("warning", "page") == "warning"
        )

    def test_critical_maps_to_page(self):
        assert bridge.normalise_severity("critical", None) == "page"

    def test_ticket_maps_to_warning(self):
        assert bridge.normalise_severity("ticket", None) == "warning"

    def test_falls_back_to_catalog(self):
        assert bridge.normalise_severity(None, "page") == "page"

    def test_falls_back_to_info(self):
        assert bridge.normalise_severity(None, None) == "info"


# ---------------------------------------------------------------------------
# Test 03: _truncate_summary respects 200-char cap.
# ---------------------------------------------------------------------------


class TestTruncateSummary:
    def test_no_truncation(self):
        assert bridge._truncate_summary("short") == "short"

    def test_truncated_with_ellipsis(self):
        out = bridge._truncate_summary("x" * 250)
        assert len(out) == 200
        assert out.endswith("...")

    def test_strips_whitespace(self):
        assert bridge._truncate_summary("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# Test 04: _normalise_starts_at handles RFC-3339 variants.
# ---------------------------------------------------------------------------


class TestNormaliseStartsAt:
    def test_z_passthrough(self):
        assert (
            bridge._normalise_starts_at("2026-05-18T10:11:12Z")
            == "2026-05-18T10:11:12Z"
        )

    def test_strips_fractional_seconds(self):
        assert (
            bridge._normalise_starts_at("2026-05-18T10:11:12.345Z")
            == "2026-05-18T10:11:12Z"
        )

    def test_zone_offset_to_z(self):
        assert (
            bridge._normalise_starts_at("2026-05-18T10:11:12+00:00")
            == "2026-05-18T10:11:12Z"
        )

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            bridge._normalise_starts_at("not-a-timestamp")


# ---------------------------------------------------------------------------
# Test 05: map_alert_to_event_kwargs full path (catalog hit).
# ---------------------------------------------------------------------------


def test_map_alert_a1_full(alert_a1_firing):
    kwargs = bridge.map_alert_to_event_kwargs(alert_a1_firing)
    assert kwargs is not None
    assert kwargs["alert_name"] == (
        "WakirPhase3FailureModeA1CrossModulDriftPerWelle"
    )
    assert kwargs["severity"] == "page"
    assert kwargs["failure_mode_id"] == "A1"
    assert kwargs["fired_at_utc"] == "2026-05-18T10:11:12Z"
    # alertname is stripped from labels (emitter records it separately).
    assert "alertname" not in kwargs["labels"]
    assert kwargs["labels"]["source_welle"] == "welle-3"
    assert kwargs["runbook_url"].endswith(
        "failure-mode-a1-cross-modul-drift"
    )
    assert kwargs["source"] == "alert-rule-to-mira-notify-bridge"


# ---------------------------------------------------------------------------
# Test 06: map_alert_to_event_kwargs drops resolved.
# ---------------------------------------------------------------------------


def test_map_alert_resolved_returns_none(alert_resolved):
    assert bridge.map_alert_to_event_kwargs(alert_resolved) is None


# ---------------------------------------------------------------------------
# Test 07: map_alert_to_event_kwargs respects strict_catalog.
# ---------------------------------------------------------------------------


def test_map_alert_unknown_strict(alert_unknown):
    assert (
        bridge.map_alert_to_event_kwargs(
            alert_unknown, strict_catalog=True
        )
        is None
    )


def test_map_alert_unknown_passthrough(alert_unknown):
    kwargs = bridge.map_alert_to_event_kwargs(
        alert_unknown, strict_catalog=False
    )
    assert kwargs is not None
    assert kwargs["failure_mode_id"] is None
    assert kwargs["severity"] == "info"


# ---------------------------------------------------------------------------
# Test 08: map_alert_to_event_kwargs raises on missing alertname.
# ---------------------------------------------------------------------------


def test_map_alert_missing_alertname():
    with pytest.raises(ValueError):
        bridge.map_alert_to_event_kwargs(
            {
                "status": "firing",
                "labels": {"severity": "page"},
                "annotations": {"summary": "x"},
                "startsAt": "2026-05-18T10:11:12Z",
            }
        )


# ---------------------------------------------------------------------------
# Test 09: iter_envelope_alerts accepts both shapes.
# ---------------------------------------------------------------------------


def test_iter_envelope_v4(envelope_v4):
    alerts = bridge.iter_envelope_alerts(envelope_v4)
    assert len(alerts) == 2


def test_iter_envelope_bare_list(alert_a1_firing):
    alerts = bridge.iter_envelope_alerts([alert_a1_firing])
    assert len(alerts) == 1


def test_iter_envelope_rejects_no_alerts():
    with pytest.raises(ValueError):
        bridge.iter_envelope_alerts({"version": "4"})


# ---------------------------------------------------------------------------
# Test 10: route_envelope writes a valid JSONL line + counters.
# ---------------------------------------------------------------------------


def test_route_envelope_single_alert(tmp_path, alert_a1_firing):
    log_path = tmp_path / "notify-log.jsonl"
    counters = bridge.route_envelope(
        {"version": "4", "alerts": [alert_a1_firing]},
        log_path=log_path,
    )
    assert counters == {
        "routed": 1,
        "skipped_resolved": 0,
        "skipped_unknown": 0,
        "errors": 0,
    }
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["alert_name"] == (
        "WakirPhase3FailureModeA1CrossModulDriftPerWelle"
    )
    assert obj["severity"] == "page"
    assert obj["failure_mode_id"] == "A1"
    assert obj["source"] == "alert-rule-to-mira-notify-bridge"
    assert obj["schema_version"] == "1"


# ---------------------------------------------------------------------------
# Test 11: route_envelope mixes routed + resolved + unknown.
# ---------------------------------------------------------------------------


def test_route_envelope_mixed(
    tmp_path,
    alert_a1_firing,
    alert_resolved,
    alert_unknown,
):
    log_path = tmp_path / "notify-log.jsonl"
    counters = bridge.route_envelope(
        {
            "version": "4",
            "alerts": [alert_a1_firing, alert_resolved, alert_unknown],
        },
        log_path=log_path,
        strict_catalog=True,
    )
    assert counters["routed"] == 1
    assert counters["skipped_resolved"] == 1
    assert counters["skipped_unknown"] == 1
    assert counters["errors"] == 0


# ---------------------------------------------------------------------------
# Test 12: route_envelope is idempotent (deterministic event_id).
# ---------------------------------------------------------------------------


def test_route_envelope_deterministic_event_id(
    tmp_path, alert_a1_firing
):
    log_path = tmp_path / "notify-log.jsonl"
    bridge.route_envelope(
        {"version": "4", "alerts": [alert_a1_firing]},
        log_path=log_path,
    )
    bridge.route_envelope(
        {"version": "4", "alerts": [alert_a1_firing]},
        log_path=log_path,
    )
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    obj_a = json.loads(lines[0])
    obj_b = json.loads(lines[1])
    # Same alert -> same deterministic id (the Tag-46 receiver dedupes).
    assert obj_a["event_id"] == obj_b["event_id"]


# ---------------------------------------------------------------------------
# Test 13: route_envelope writes severity-page summary <=200 chars.
# ---------------------------------------------------------------------------


def test_route_envelope_summary_truncated(tmp_path, alert_a1_firing):
    alert = dict(alert_a1_firing)
    alert["annotations"] = dict(alert["annotations"])
    alert["annotations"]["summary"] = "x" * 250
    log_path = tmp_path / "notify-log.jsonl"
    counters = bridge.route_envelope(
        {"version": "4", "alerts": [alert]}, log_path=log_path
    )
    assert counters["routed"] == 1
    line = log_path.read_text(encoding="utf-8").splitlines()[0]
    obj = json.loads(line)
    assert len(obj["summary"]) == 200
    assert obj["summary"].endswith("...")


# ---------------------------------------------------------------------------
# Test 14: extract_alert_names_from_rules_yaml + audit_catalog roundtrip.
# ---------------------------------------------------------------------------


def test_extract_alert_names_minimal_yaml():
    text = (
        "groups:\n"
        "  - name: g1\n"
        "    rules:\n"
        "      - alert: AlphaAlert\n"
        "        expr: up == 0\n"
        "      - alert: BetaAlert\n"
        "        expr: up == 1\n"
    )
    assert bridge.extract_alert_names_from_rules_yaml(text) == [
        "AlphaAlert",
        "BetaAlert",
    ]


def test_audit_catalog_reports_missing():
    text = (
        "groups:\n"
        "  - name: g1\n"
        "    rules:\n"
        "      - alert: AlphaUncatalogued\n"
        "        expr: up == 0\n"
    )
    audit = bridge.audit_catalog_against_rules(text)
    assert "AlphaUncatalogued" in audit["missing"]


# ---------------------------------------------------------------------------
# Test 15: cross-check against the real phase-3-marathon-alerts.yaml.
# Every alert in the YAML MUST appear in either ALERT_CATALOG or
# CATALOG_NON_PRE_MORTEM.  If this fails: the catalog is stale
# relative to the rules YAML.
# ---------------------------------------------------------------------------


def test_catalog_covers_all_marathon_rules():
    assert _RULES_PATH.exists(), f"rules YAML not found at {_RULES_PATH}"
    text = _RULES_PATH.read_text(encoding="utf-8")
    audit = bridge.audit_catalog_against_rules(text)
    assert audit["missing"] == [], (
        f"alerts in rules YAML missing from bridge catalog: "
        f"{audit['missing']}"
    )


# ---------------------------------------------------------------------------
# Test 16: CLI route --input writes to log + exits 0.
# ---------------------------------------------------------------------------


def test_cli_route_input_file(tmp_path, envelope_v4):
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(envelope_v4), encoding="utf-8")
    log_path = tmp_path / "notify-log.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(_BRIDGE_PATH),
            "route",
            "--input",
            str(envelope_path),
            "--log-path",
            str(log_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "routed=2" in result.stderr
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# Test 17: CLI validate-catalog against the real rules YAML exits 0.
# ---------------------------------------------------------------------------


def test_cli_validate_catalog_real_rules():
    result = subprocess.run(
        [
            sys.executable,
            str(_BRIDGE_PATH),
            "validate-catalog",
            "--rules",
            str(_RULES_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    audit = json.loads(result.stdout)
    assert audit["missing"] == []


# ---------------------------------------------------------------------------
# Test 18: End-to-end with Tag-46 receiver --mode=file materialises
# a Mira-Hand inbox markdown file from a bridge-routed envelope.
# This is the *wiring proof*: Tag-45 alert -> Tag-46 emitter ->
# Tag-46 receiver -> Mira-Hand inbox.
# ---------------------------------------------------------------------------


def test_end_to_end_alert_to_inbox(tmp_path, alert_a1_firing):
    log_path = tmp_path / "notify-log.jsonl"
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    # Step 1: bridge routes the envelope.
    counters = bridge.route_envelope(
        {"version": "4", "alerts": [alert_a1_firing]},
        log_path=log_path,
    )
    assert counters["routed"] == 1

    # Step 2: receiver materialises the inbox file.
    result = subprocess.run(
        [
            sys.executable,
            str(_RECEIVER_PATH),
            "--mode",
            "file",
            "--input",
            str(log_path),
            "--inbox",
            str(inbox),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    # One markdown file written into the inbox with the page prefix.
    inbox_files = [
        p for p in inbox.iterdir()
        if p.is_file() and p.name.startswith("notify-page-")
    ]
    assert len(inbox_files) == 1, (
        f"expected one notify-page-*.md, got: {list(inbox.iterdir())}"
    )
    body = inbox_files[0].read_text(encoding="utf-8")
    assert (
        "WakirPhase3FailureModeA1CrossModulDriftPerWelle" in body
    ), "alert_name should appear in materialised inbox file"
    assert "failure-mode-a1-cross-modul-drift" in body, (
        "runbook_url should appear in materialised inbox file"
    )
