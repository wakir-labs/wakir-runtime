# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic schema-validation tests for the Tag-52 Phase-3-Marathon
Final-Pre-Cutover SLO-Dashboard and its companion SLO catalogue.

Covers two artifacts:

  * ``dashboards/phase-3-marathon-slo-final.json`` -- the Grafana
    JSON model carrying the consolidated 7-SLO surface (28 panels:
    1 header row, 1 health gauge, 2 progress stats, 7 SLO row-groups
    of 2-3 panels each, 1 anchor text panel).
  * ``docs/observability/sli-slo-phase-3-marathon.md`` -- the
    canonical SLO catalogue this dashboard renders.

Sandbox boundary: pure stdlib. No network, no Prometheus, no
Grafana API contact. The tests assert structure and invariants
("is this the SLO surface the catalogue documents") rather than
rendering correctness.

Anchors:
  - Tag-52 auftrag (Noa-SRE, Phase-3-Marathon Final-Pre-Cutover
    SLO-Dashboard).
  - ADR-0066 (Phase-3c Beschleunigung, §Marathon-KW-24..27).
  - ADR-0064 (Phase-2 SLI/SLO substrate).
  - Sister-catalogue ``docs/observability/sli-slo-phase-1b.md``
    and ``docs/observability/sli-slo-wat-phase-2.md`` (Tag-15
    Phase-1b/2 SLOs that this Marathon catalogue rolls up on top
    of, intentionally not restated).
"""

from __future__ import annotations

import json
import pathlib

import pytest


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DASHBOARD_PATH = (
    _REPO_ROOT / "dashboards" / "phase-3-marathon-slo-final.json"
)
_SLO_DOC_PATH = (
    _REPO_ROOT / "docs" / "observability" / "sli-slo-phase-3-marathon.md"
)


# ---------------------------------------------------------------------------
# Constants describing the Tag-52 SLO-rollup contract
# ---------------------------------------------------------------------------


# Header row + composite gauge + 2 progress stats.
_HEADER_ROW_ID = 1
_HEALTH_GAUGE_ID = 2
_PROGRESS_STAT_IDS = [3, 4]

# Seven SLO row-groups. Each row id is the group base (10, 20, 30, ...);
# the row's panels live in the +1, +2, +3 ids.
_SLO_GROUPS = {
    "welle-cutover-success-rate": {
        "row_id": 10,
        "panel_ids": [11, 12],
        "metric_fragments": [
            "persona_engine_phase_3c_welle_decisions_total",
            "persona_engine_phase_3c_welle_fallback_total",
        ],
        "cutover_blocking": True,
    },
    "cross-modul-drift-rate": {
        "row_id": 20,
        "panel_ids": [21, 22],
        "metric_fragments": [
            "wakir_cross_modul_drift_count",
        ],
        "cutover_blocking": True,
    },
    "alert-volume-trend": {
        "row_id": 30,
        "panel_ids": [31, 32],
        "metric_fragments": [
            "ALERTS",
        ],
        "cutover_blocking": False,
    },
    "ar-hand-stop-trigger-rate": {
        "row_id": 40,
        "panel_ids": [41, 42],
        "metric_fragments": [
            "wakir_ar_hand_stop_marker_total",
        ],
        "cutover_blocking": False,
    },
    "build-reproducibility": {
        "row_id": 50,
        "panel_ids": [51, 52],
        "metric_fragments": [
            "wakir_build_reproducibility_drift_count",
            "wakir_build_reproducibility_deterministic",
        ],
        "cutover_blocking": True,
    },
    "sbom-verdict": {
        "row_id": 60,
        "panel_ids": [61, 62, 63],
        "metric_fragments": [
            "wakir_sbom_verification_aggregate_verdict",
            "wakir_sbom_verification_binaries_by_verdict_count",
            "wakir_sbom_verification_per_binary_drift_count",
        ],
        "cutover_blocking": True,
    },
    "cosign-oidc-drift": {
        "row_id": 70,
        "panel_ids": [71, 72, 73],
        "metric_fragments": [
            "wakir_cosign_drift_probe_aggregate",
            "wakir_cosign_drift_probe_trust_root",
            "wakir_cosign_drift_probe_per_binary",
        ],
        "cutover_blocking": True,
    },
}

_ANCHOR_TEXT_PANEL_ID = 99


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dashboard() -> dict:
    raw = _DASHBOARD_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


@pytest.fixture(scope="module")
def panels(dashboard: dict) -> list[dict]:
    return dashboard["panels"]


@pytest.fixture(scope="module")
def panels_by_id(panels: list[dict]) -> dict[int, dict]:
    return {p["id"]: p for p in panels}


@pytest.fixture(scope="module")
def slo_doc() -> str:
    return _SLO_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Dashboard-level invariants
# ---------------------------------------------------------------------------


def test_dashboard_file_exists():
    assert _DASHBOARD_PATH.exists(), (
        f"dashboard missing: {_DASHBOARD_PATH}"
    )


def test_dashboard_parses_as_json(dashboard: dict):
    assert isinstance(dashboard, dict)


def test_dashboard_title_marks_marathon_final_slo(dashboard: dict):
    title = dashboard["title"]
    assert "Marathon" in title
    assert "SLO" in title
    assert "Final" in title or "Pre-Cutover" in title


def test_dashboard_uid_is_marathon_slo_final(dashboard: dict):
    assert dashboard["uid"] == "wakir-phase-3-marathon-slo-final"


def test_dashboard_tags_required(dashboard: dict):
    tags = set(dashboard["tags"])
    required = {
        "wakir",
        "sre",
        "phase-3-marathon",
        "slo",
        "error-budget",
        "tag-52",
        "marathon-final",
        "adr-0066",
    }
    missing = required - tags
    assert not missing, f"required tags missing: {missing}"


def test_dashboard_grafana_10_schema(dashboard: dict):
    assert dashboard["schemaVersion"] == 38


def test_panel_ids_unique(panels: list[dict]):
    ids = [p["id"] for p in panels]
    duplicates = sorted({pid for pid in ids if ids.count(pid) > 1})
    assert not duplicates, f"duplicate panel ids: {duplicates}"


def test_total_panel_count_minimum(panels: list[dict]):
    # 1 header + 1 gauge + 2 progress + 7 row markers + 7 row groups
    # (2-3 panels each, total 16) + 1 anchor text = 28 panels.
    assert len(panels) >= 24, (
        f"panel count below SLO-rollup minimum (24): {len(panels)}"
    )


def test_datasource_uniformly_prom(panels: list[dict]):
    # Every non-row panel must point at the prom datasource so the
    # dashboard exports cleanly without per-panel datasource fix-up.
    for p in panels:
        if p["type"] == "row":
            continue
        ds = p.get("datasource")
        assert ds is not None, f"panel {p['id']} ({p.get('title')}) missing datasource"
        assert ds.get("uid") == "prom", (
            f"panel {p['id']} datasource uid != prom: {ds!r}"
        )


# ---------------------------------------------------------------------------
# Header block (composite gauge + progress stats)
# ---------------------------------------------------------------------------


def test_header_row_present(panels_by_id: dict[int, dict]):
    row = panels_by_id[_HEADER_ROW_ID]
    assert row["type"] == "row"
    assert "Marathon" in row["title"]


def test_health_gauge_is_marathon_health_score(panels_by_id: dict[int, dict]):
    p = panels_by_id[_HEALTH_GAUGE_ID]
    assert p["type"] == "gauge"
    expr = p["targets"][0]["expr"]
    assert expr == "wakir_phase_3_marathon_health_score"
    defaults = p["fieldConfig"]["defaults"]
    assert defaults["unit"] == "percent"
    assert defaults["min"] == 0
    assert defaults["max"] == 100
    step_colors = [s["color"] for s in defaults["thresholds"]["steps"]]
    assert step_colors == ["red", "orange", "yellow", "green"]


def test_progress_stats_present(panels_by_id: dict[int, dict]):
    for pid in _PROGRESS_STAT_IDS:
        p = panels_by_id[pid]
        assert p["type"] == "stat", f"panel {pid} expected stat type"


def test_progress_stat_count_uses_welle_state(panels_by_id: dict[int, dict]):
    p = panels_by_id[3]
    expr = p["targets"][0]["expr"]
    assert "persona_engine_phase_3c_welle_state" in expr
    assert "== 3" in expr  # signed-off state-encoding from Tag-30 emitter
    assert "count(" in expr


def test_progress_stat_percent_uses_marathon_progress(
    panels_by_id: dict[int, dict],
):
    p = panels_by_id[4]
    expr = p["targets"][0]["expr"]
    assert expr == "persona_engine_phase_3c_marathon_progress_pct"


# ---------------------------------------------------------------------------
# SLO row-groups: contract per SLO
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slo_name,spec", list(_SLO_GROUPS.items()))
def test_slo_row_marker_present(
    panels_by_id: dict[int, dict],
    slo_name: str,
    spec: dict,
):
    row = panels_by_id[spec["row_id"]]
    assert row["type"] == "row", f"SLO {slo_name} row marker missing"


@pytest.mark.parametrize("slo_name,spec", list(_SLO_GROUPS.items()))
def test_slo_panels_present(
    panels_by_id: dict[int, dict],
    slo_name: str,
    spec: dict,
):
    for pid in spec["panel_ids"]:
        assert pid in panels_by_id, (
            f"SLO {slo_name} panel id {pid} missing"
        )


@pytest.mark.parametrize("slo_name,spec", list(_SLO_GROUPS.items()))
def test_slo_panels_reference_documented_metrics(
    panels_by_id: dict[int, dict],
    slo_name: str,
    spec: dict,
):
    # The panel set for an SLO must collectively reference every
    # metric the SLO catalogue names; this catches the silent-drift
    # case where the catalogue and the dashboard diverge on which
    # gauge backs the SLO.
    all_exprs = []
    for pid in spec["panel_ids"]:
        p = panels_by_id[pid]
        for t in p.get("targets", []):
            all_exprs.append(t.get("expr", ""))
    joined = " ".join(all_exprs)
    for frag in spec["metric_fragments"]:
        assert frag in joined, (
            f"SLO {slo_name} dashboard panels do not reference required "
            f"metric fragment {frag!r}; available exprs: {all_exprs!r}"
        )


def test_welle_cutover_success_rate_panel_uses_six_hour_window(
    panels_by_id: dict[int, dict],
):
    # SLO-1 doc says 6h trailing window; the dashboard panel 11 must
    # use [6h] in both rate() expressions for the ratio to match the
    # SLO contract.
    p = panels_by_id[11]
    expr = p["targets"][0]["expr"]
    assert "[6h]" in expr, (
        f"SLO-1 success-rate panel must use 6h window per SLO doc; "
        f"expr={expr!r}"
    )
    assert expr.count("[6h]") >= 2


def test_cross_modul_drift_panel_uses_24h_increase(
    panels_by_id: dict[int, dict],
):
    # SLO-2 doc says 24h trailing for the SLO eval; panel 22 stat
    # rolls increase()[24h].
    p = panels_by_id[22]
    expr = p["targets"][0]["expr"]
    assert "[24h]" in expr
    assert "increase(" in expr


def test_alert_volume_panel_filters_phase_label(
    panels_by_id: dict[int, dict],
):
    # SLO-3 contract: filter ALERTS to phase="phase-3-marathon" so
    # unrelated alert noise outside the Marathon does not pollute
    # the volume trend.
    p = panels_by_id[31]
    expr = p["targets"][0]["expr"]
    assert 'phase="phase-3-marathon"' in expr
    assert 'alertstate="firing"' in expr


def test_ar_hand_stop_trigger_rate_marathon_window(
    panels_by_id: dict[int, dict],
):
    # SLO-4 doc says Marathon-to-date (28d). Panel 42 stat uses
    # max_over_time([28d]) for the to-date approximation.
    p = panels_by_id[42]
    expr = p["targets"][0]["expr"]
    assert "[28d]" in expr
    assert "max_over_time(" in expr


# ---------------------------------------------------------------------------
# Cutover-blocking vs informational thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "panel_id,must_have_red_threshold",
    [
        # SLO-2 aggregate stat: hard-zero, drift_count >= 1 must be RED.
        (22, True),
        # SLO-5 aggregate stat: drift_count >= 1 must be RED.
        (51, True),
        # SLO-6 aggregate stat: aggregate_verdict == 0 must map FAIL/RED.
        (61, True),
        # SLO-7 aggregate stat: aggregate == 1 must map DRIFT/RED.
        (71, True),
        # SLO-7 trust-root stat: trust_root == 0 must map ROTATED/RED.
        (72, True),
    ],
)
def test_cutover_blocking_stat_has_red_threshold(
    panels_by_id: dict[int, dict],
    panel_id: int,
    must_have_red_threshold: bool,
):
    p = panels_by_id[panel_id]
    steps = p["fieldConfig"]["defaults"]["thresholds"]["steps"]
    colors = [s["color"] for s in steps]
    assert "red" in colors, (
        f"cutover-blocking panel {panel_id} ({p.get('title')}) "
        f"must include red threshold; got {colors!r}"
    )


# ---------------------------------------------------------------------------
# Anchor text panel
# ---------------------------------------------------------------------------


def test_anchor_text_panel_present(panels_by_id: dict[int, dict]):
    p = panels_by_id[_ANCHOR_TEXT_PANEL_ID]
    assert p["type"] == "text"
    content = p["options"]["content"]
    assert "Tag-52" in content
    assert "Marathon" in content
    assert "SLO" in content
    # Cross-reference to the SLO catalogue doc must be surfaced for
    # the on-shift operator.
    assert "sli-slo-phase-3-marathon.md" in content


# ---------------------------------------------------------------------------
# SLO catalogue doc invariants
# ---------------------------------------------------------------------------


def test_slo_doc_exists():
    assert _SLO_DOC_PATH.exists(), f"SLO doc missing: {_SLO_DOC_PATH}"


def test_slo_doc_owner_and_tag(slo_doc: str):
    assert "Noa Bergstroem" in slo_doc
    assert "Tag-52" in slo_doc


def test_slo_doc_covers_seven_slos(slo_doc: str):
    for sli_id in range(1, 8):
        token = f"SLI-MARATHON-{sli_id}"
        assert token in slo_doc, f"SLO doc missing entry for {token}"


def test_slo_doc_marks_cutover_blocking_set(slo_doc: str):
    # SLO-1, SLO-2, SLO-5, SLO-6, SLO-7 must be flagged
    # cutover-blocking. SLO-3, SLO-4 must be flagged informational.
    # Anchor the search by SLI token so we hit the section heading
    # rather than the in-scope-list early prose.
    sections_blocking = [
        "SLI-MARATHON-1",
        "SLI-MARATHON-2",
        "SLI-MARATHON-5",
        "SLI-MARATHON-6",
        "SLI-MARATHON-7",
    ]
    for sli_token in sections_blocking:
        idx = slo_doc.find(sli_token)
        assert idx >= 0, f"SLI section heading {sli_token!r} not found"
        # Search forward in this SLI's section until the next SLI
        # heading or end-of-doc.
        next_idx = slo_doc.find("SLI-MARATHON-", idx + 1)
        tail = slo_doc[idx : next_idx if next_idx > 0 else len(slo_doc)]
        assert "Cutover-blocking" in tail and "YES" in tail, (
            f"section {sli_token!r} missing Cutover-blocking YES marker"
        )

    sections_informational = ["SLI-MARATHON-3", "SLI-MARATHON-4"]
    for sli_token in sections_informational:
        idx = slo_doc.find(sli_token)
        next_idx = slo_doc.find("SLI-MARATHON-", idx + 1)
        tail = slo_doc[idx : next_idx if next_idx > 0 else len(slo_doc)]
        assert "Cutover-blocking" in tail and "NO" in tail, (
            f"section {sli_token!r} missing Cutover-blocking NO marker"
        )


def test_slo_doc_documents_marathon_complete_conjunction(slo_doc: str):
    # The 5-way conjunction from the Tag-40 dashboard must be re-cited
    # in the SLO doc so the rollup is grounded in the existing gate.
    required_fragments = [
        "persona_engine_phase_3c_welle_state == 3",
        "wakir_henrik_audit_signoff == 1",
        "wakir_cross_modul_drift_count == 0",
        "wakir_ar_hand_final_signoff_phase_3 == 1",
    ]
    for frag in required_fragments:
        assert frag in slo_doc, (
            f"SLO doc missing Marathon-COMPLETE conjunction fragment "
            f"{frag!r}"
        )


def test_slo_doc_lists_review_cadence(slo_doc: str):
    assert "Review cadence" in slo_doc or "review cadence" in slo_doc.lower()
    assert "Weekly" in slo_doc or "weekly" in slo_doc.lower()
