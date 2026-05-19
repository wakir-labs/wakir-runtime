# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic observability tests for the Tag-71 Live-Smoke
Stability-Window-Operator-Runbook + Welle-3 Pre-Auditor Routing
Element (Noa SRE, Continuous-Mode-Marathon).

Auftrag-Anker
-------------

Tag-71 Noa Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Operator-Doc that describes the Tag-69 Live-Smoke Stability-
Window-Probe as a Day-1 operator action + a Welle-3-specific
routing element (Pre-Auditor positive-confirmation alert).

The Operator-Runbook lives at
``docs/observability/live-smoke-stability-window-operator-runbook.md``
and is mirrored to
``wirelang/specs/protocol-mirror-seed/docs/observability/``.

The Welle-3 Pre-Auditor alert
(``WakirPhase3Welle3PreAuditorDesignated``) is appended to the
existing ``phase-3-marathon-failure-mode-b3-iia-1130-default``
alert-group in ``dashboards/phase-3-marathon-alerts.yaml`` and
mirrored into the protocol-mirror-seed dashboards copy.

Scope
-----

* Operator-Runbook structural assertions (sections, gates,
  trinary-verdict matrix, hand-off fields).
* Welle-3 Pre-Auditor alert structural assertions in the
  alerts YAML (alert name, severity, routing class, expr
  contract, mutual exclusion vs. the Tag-45 default-path
  warning).
* Cross-Repo-Mirror byte-equality.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

RUNBOOK_PATH = (
    REPO_ROOT
    / "docs"
    / "observability"
    / "live-smoke-stability-window-operator-runbook.md"
)
RUNBOOK_MIRROR_PATH = (
    REPO_ROOT
    / "wirelang"
    / "specs"
    / "protocol-mirror-seed"
    / "docs"
    / "observability"
    / "live-smoke-stability-window-operator-runbook.md"
)

ALERTS_PATH = REPO_ROOT / "dashboards" / "phase-3-marathon-alerts.yaml"
ALERTS_MIRROR_PATH = (
    REPO_ROOT
    / "wirelang"
    / "specs"
    / "protocol-mirror-seed"
    / "dashboards"
    / "phase-3-marathon-alerts.yaml"
)


# ---------------------------------------------------------------
# Fixtures: load the artefacts once.
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def runbook_mirror_text() -> str:
    return RUNBOOK_MIRROR_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_text() -> str:
    return ALERTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def alerts_mirror_text() -> str:
    return ALERTS_MIRROR_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# Section 1: Operator-Runbook surface.
# ---------------------------------------------------------------


def test_runbook_exists_and_nonempty(runbook_text: str) -> None:
    """The Tag-71 operator-runbook is committed and not empty."""
    assert RUNBOOK_PATH.exists(), (
        f"runbook missing at {RUNBOOK_PATH}"
    )
    assert len(runbook_text) > 2000, (
        "runbook unexpectedly short; Day-1 doc must carry the "
        "full procedural surface"
    )


def test_runbook_has_spdx_header(runbook_text: str) -> None:
    """SPDX header present (Apache-2.0, Callandor copyright)."""
    # REUSE-IgnoreStart
    head = runbook_text[:200]
    expected_spdx_line = "SPDX-License-" "Identifier: " "Apache-2.0"
    assert expected_spdx_line in head
    assert "Callandor GmbH" in head
    # REUSE-IgnoreEnd


def test_runbook_has_six_sections(runbook_text: str) -> None:
    """The runbook carries the six Day-1-operator sections plus
    references. Auftrag-Spec: 6 Sektionen, Day-1-Operator-Aktion.
    """
    required_headings = [
        "## 1. Purpose",
        "## 2. Day-1 Operator Action -- Pre-Shift Checklist",
        "## 3. Trigger Procedure",
        "## 4. Reading the Verdict",
        "## 5. Verdict Hand-Off to AR-Hand",
        "## 6. Welle-3 Pre-Auditor Routing Element (Tag-71 Extension)",
    ]
    for h in required_headings:
        assert h in runbook_text, f"missing section heading: {h}"


def test_runbook_trinary_verdict_matrix(runbook_text: str) -> None:
    """All three Tag-59 N-Run-Pattern verdicts must be enumerated
    in Section 4 with explicit operator actions for each.
    """
    for verdict in (
        "STABILITY-WINDOW-CONFIRMED",
        "STABILITY-WINDOW-NOT-YET",
        "STABILITY-WINDOW-DEFECT",
    ):
        assert verdict in runbook_text, (
            f"verdict {verdict} missing from runbook"
        )
    # Operator-action sub-headers (4.1 / 4.2 / 4.3).
    assert "### 4.1 STABILITY-WINDOW-CONFIRMED" in runbook_text
    assert "### 4.2 STABILITY-WINDOW-NOT-YET" in runbook_text
    assert "### 4.3 STABILITY-WINDOW-DEFECT" in runbook_text


def test_runbook_preshift_gates_g1_through_g5(runbook_text: str) -> None:
    """Section 2 enumerates exactly G1..G5 pre-shift gates."""
    for gate in ("G1", "G2", "G3", "G4", "G5"):
        assert gate in runbook_text, f"pre-shift gate {gate} missing"


def test_runbook_handoff_fields(runbook_text: str) -> None:
    """Section 5 lists the five canonical hand-off fields."""
    handoff_fields = [
        "verdict",
        "workflow_run_url",
        "pre_shift_gates",
        "operator_initials",
        "notes_freetext",
    ]
    for fld in handoff_fields:
        assert fld in runbook_text, (
            f"hand-off field `{fld}` missing"
        )


def test_runbook_section_6_welle3_routing(runbook_text: str) -> None:
    """Section 6 documents the Tag-71 Welle-3 Pre-Auditor
    routing element with the four-row table (alert name, severity,
    routing class, notify path)."""
    sec6_marker = "## 6. Welle-3 Pre-Auditor Routing Element"
    assert sec6_marker in runbook_text
    sec6_idx = runbook_text.index(sec6_marker)
    sec7_idx = runbook_text.index("## 7.")
    section_6 = runbook_text[sec6_idx:sec7_idx]
    assert "WakirPhase3Welle3PreAuditorDesignated" in section_6
    assert "welle-3-pre-auditor-info" in section_6
    assert "ntfy:ar-hand-info" in section_6
    assert "external-pre-auditor" in section_6
    # The mutual-exclusion-with-Tag-45-alert is the load-bearing
    # contract; it must be spelled out.
    assert "WakirPhase3FailureModeB3Iia1130DefaultPath" in section_6


def test_runbook_failure_mode_escalation_table(runbook_text: str) -> None:
    """Section 7 enumerates the symptom -> action -> escalation
    table including the Welle-3 Pre-Auditor designation row."""
    sec7_marker = "## 7. Failure-Mode Escalation Table"
    assert sec7_marker in runbook_text
    sec8_idx = runbook_text.index("## 8. References")
    sec7_text = runbook_text[runbook_text.index(sec7_marker):sec8_idx]
    assert "Workflow missing in Actions" in sec7_text
    assert "STABILITY-WINDOW-DEFECT" in sec7_text
    assert "Welle-3 Pre-Auditor designation missing" in sec7_text


# ---------------------------------------------------------------
# Section 2: Welle-3 Pre-Auditor alert YAML surface.
# ---------------------------------------------------------------


def test_alerts_yaml_contains_new_alert(alerts_text: str) -> None:
    """The Tag-71 alert is appended to the alerts YAML."""
    assert "WakirPhase3Welle3PreAuditorDesignated" in alerts_text


def test_alert_carries_info_severity_and_routing_class(alerts_text: str) -> None:
    """The new alert must be severity=info and carry the
    `welle-3-pre-auditor-info` routing class (so the AlertManager
    route-tree fans out to AR-Hand info topic + activity-log).
    """
    # Slice to the alert block: from the alert-key to the next
    # blank line that's not inside an annotation block.
    alert_start = alerts_text.index("WakirPhase3Welle3PreAuditorDesignated")
    # Take the next 2000 chars; the block is well below that.
    block = alerts_text[alert_start:alert_start + 2500]
    assert re.search(r"severity:\s*info", block), (
        "Tag-71 alert must be severity=info, not warning/page"
    )
    assert "routing_class: welle-3-pre-auditor-info" in block
    assert "tag: tag-71" in block
    assert "failure_mode: B3" in block
    assert "welle: welle-3" in block


def test_alert_expr_uses_external_pre_auditor_signoff(alerts_text: str) -> None:
    """The expr must positively match
    auditor=external-pre-auditor AND negatively match
    auditor=henrik. This is the mutual-exclusion contract that
    distinguishes Tag-71 (positive ack) from Tag-45 (warning).
    """
    alert_start = alerts_text.index("WakirPhase3Welle3PreAuditorDesignated")
    block = alerts_text[alert_start:alert_start + 2500]
    assert (
        'wakir_welle_schluss_audit_signoff{welle="welle-3", '
        'auditor="external-pre-auditor"} == 1'
    ) in block
    assert (
        'wakir_welle_schluss_audit_signoff{welle="welle-3", '
        'auditor="henrik"} == 0'
    ) in block


def test_alert_notify_path_is_info_only(alerts_text: str) -> None:
    """The alert is informational: notify path must be ntfy
    info topic + activity-log append. No pagerduty, no storm.
    """
    alert_start = alerts_text.index("WakirPhase3Welle3PreAuditorDesignated")
    block = alerts_text[alert_start:alert_start + 2500]
    notify_match = re.search(r'notify_path:\s*"([^"]+)"', block)
    assert notify_match, "notify_path annotation missing"
    notify = notify_match.group(1)
    assert "ntfy:ar-hand-info" in notify
    assert "activity-log:append" in notify
    assert "pagerduty" not in notify, (
        "info-only routing element must NOT page on-call"
    )


def test_alert_is_in_b3_group_not_new_group(alerts_text: str) -> None:
    """The Tag-71 alert is appended to the existing
    `phase-3-marathon-failure-mode-b3-iia-1130-default` group,
    not lifted into a new top-level group. This preserves the
    mutual-exclusion locality with the Tag-45 default-path
    warning."""
    group_marker = (
        "- name: phase-3-marathon-failure-mode-b3-iia-1130-default"
    )
    group_idx = alerts_text.index(group_marker)
    new_alert_idx = alerts_text.index("WakirPhase3Welle3PreAuditorDesignated")
    # Next group after b3 group:
    c1_group_marker = (
        "- name: phase-3-marathon-failure-mode-c1-marker-false-positive-granular"
    )
    c1_idx = alerts_text.index(c1_group_marker)
    assert group_idx < new_alert_idx < c1_idx, (
        "Tag-71 alert must live inside the B3 group, before the "
        "C1 group"
    )


def test_alert_anchors_tag_71_in_inline_comment(alerts_text: str) -> None:
    """A `Tag-71 Welle-3 Pre-Auditor Routing Element` comment
    anchors the new block for future grep-ability."""
    assert (
        "Tag-71 Welle-3 Pre-Auditor Routing Element" in alerts_text
    )


def test_alert_owner_and_adr_labels(alerts_text: str) -> None:
    """Ownership labels are correctly set: owner=noa-sre,
    adr=adr-0066, team=sre."""
    alert_start = alerts_text.index("WakirPhase3Welle3PreAuditorDesignated")
    block = alerts_text[alert_start:alert_start + 2500]
    assert "owner: noa-sre" in block
    assert "adr: adr-0066" in block
    assert "team: sre" in block


# ---------------------------------------------------------------
# Section 3: Cross-Repo-Mirror byte-equality.
# ---------------------------------------------------------------


def test_runbook_mirror_byte_equal(
    runbook_text: str, runbook_mirror_text: str
) -> None:
    """The protocol-mirror-seed runbook copy is byte-equal."""
    assert runbook_text == runbook_mirror_text, (
        "runbook mirror drifted from primary; cross-repo invariant "
        "broken"
    )


def test_alerts_mirror_byte_equal(
    alerts_text: str, alerts_mirror_text: str
) -> None:
    """The protocol-mirror-seed alerts copy is byte-equal."""
    assert alerts_text == alerts_mirror_text, (
        "alerts mirror drifted from primary; cross-repo invariant "
        "broken"
    )


# ---------------------------------------------------------------
# Section 4: Cross-Reference checks (doc <-> alert consistency).
# ---------------------------------------------------------------


def test_runbook_references_tag_69_workflow_filename(runbook_text: str) -> None:
    """The runbook must point at the Tag-69 workflow file
    by exact relative path so the operator can find it."""
    assert (
        ".github/workflows/live-smoke-stability-window-probe.yml"
        in runbook_text
    )


def test_runbook_and_alert_share_routing_class_token(
    runbook_text: str, alerts_text: str
) -> None:
    """The runbook's Section 6 routing-class string must match
    the YAML alert's routing_class label exactly."""
    token = "welle-3-pre-auditor-info"
    assert token in runbook_text
    assert token in alerts_text


def test_runbook_and_alert_share_alert_name(
    runbook_text: str, alerts_text: str
) -> None:
    """The runbook documents the alert by name; the YAML defines
    it. The two strings must match exactly."""
    name = "WakirPhase3Welle3PreAuditorDesignated"
    assert name in runbook_text
    assert name in alerts_text
