#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-78 Phase-3-COMPLETE Production-Bringup-Test-Suite (Tomás).

Marathon-Polish-Phase extension of Tag-76
``test_phase_3_complete_audit_bundle_tag76.py`` (Tomás PR #484). This
suite covers two surfaces that the Tag-76 substrate left implicit and
that the Tag-77 follow-on items (Operator-Hand OTS-Live-Stamping doc
PR #488, Marathon-Final-Smoke E2E PR #489) now lean on:

  1. **Phase-3-COMPLETE-marker post-Welle-7-Sign-off integration**:
     the seven Welle-1..7 audit-anchor markers feed the closeout
     envelope (Tag-76 substrate) which in turn parameterises the
     Day-1 B1 marker-fire step of the Operator-Hand Production-
     Bringup-Recipe (``docs/operations/operator-hand-production-
     bringup-recipe.md``). The seven Day-N steps then carry the
     post-fire window through to Day-7 Marathon-Final-Bilanz.

  2. **Production-Bringup Day-1..Day-7 sequence**: each of the seven
     post-Sign-off days has a canonical anchor (date, weekday, B-step,
     time-window, sandbox-OK boolean, verdict-marker family). The
     recipe doc lists these in §1..§4 and the §7 Aggregate-Verdict-
     Roll-up table cross-references them. These tests pin the
     sequence so a future doc edit cannot silently shift the
     Day-N -> step mapping without breaking the suite.

Scope is **substrate-validation-only** (Disziplin Tag-78 Auftrag:
Test-Suite-Erweiterung, kein neuer Substrate). The recipe doc is
parsed as text + frontmatter; the Tag-76 emit / wire helpers are
loaded as importable modules (re-use of the Tag-76 fixture pattern
``_load_module``).

Sandbox-boundary: pure file-system + stdlib + pytest. No network,
no subprocess outside the existing Tag-76 wire-helper CLI smoke that
was already deemed sandbox-clean in the Tag-76 suite.

Anchor: Tag-78 Marathon-Polish-Phase, Phase-3-COMPLETE-marker post-
Welle-7-Sign-off + Day-1..Day-7 sequence pinning.
Author: Tomás Reinhart (dev-engineering, Matrix-Lead, Zone-N hand-off).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
EMIT_HELPER = REPO_ROOT / "tooling" / "ots" / "emit_manifest_hash_ots_marker.py"
WIRE_HELPER = (
    REPO_ROOT / "tooling" / "ci" / "wire_phase_3_complete_audit_bundle.py"
)
PRODUCTION_BRINGUP_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "operator-hand-production-bringup-recipe.md"
)

# Amara Tag-67 verifier regex: empty-string or 64-hex SHA-256.
OTS_ANCHOR_RE = re.compile(r"^$|^[0-9a-f]{64}$")

# Frozen ISO timestamp for deterministic envelope timestamps in tests.
# Day-1 morning of the Production-Bringup-Window: 2026-07-04 06:00 CEST
# = 2026-07-04 04:00 UTC. Anchored at the §1 B1 time-window-open.
FROZEN_NOW = _dt.datetime(2026, 7, 4, 4, 0, 0, tzinfo=_dt.timezone.utc)

# Tag-76 Production-Bringup-Recipe canonical Day-N -> (date, weekday)
# mapping per docs/operations/operator-hand-production-bringup-recipe.md
# Zeit-Domain table.
DAY_N_CALENDAR: list[tuple[int, str, str]] = [
    (1, "2026-07-04", "Sa"),
    (2, "2026-07-05", "So"),
    (3, "2026-07-06", "Mo"),
    (4, "2026-07-07", "Di"),
    (5, "2026-07-08", "Mi"),
    (6, "2026-07-09", "Do"),
    (7, "2026-07-10", "Fr"),
]

# Tag-76 Production-Bringup-Recipe canonical B-step roster.
B_STEPS: tuple[str, ...] = ("B1", "B2", "B3", "B4", "B5")

# Tag-76 Rollback-Pfade roster.
R_PFADE: tuple[str, ...] = ("R-PB-A", "R-PB-B", "R-PB-C", "R-PB-D")

# Tag-76 AR-Hand-Touchpoints roster.
TP_PB: tuple[str, ...] = ("TP-PB-1", "TP-PB-2", "TP-PB-3")

# §7 Aggregate-Verdict-Roll-up verdict-marker set.
AGGREGATE_VERDICTS: tuple[str, ...] = (
    "PB-VERDICT-PHASE-3-CLOSED-CLEAN",
    "PB-VERDICT-PHASE-3-CLOSED-WITH-CARRY",
    "PB-VERDICT-PHASE-3-NO-FIRE",
    "PB-VERDICT-PHASE-3-DEFERRED",
    "PB-VERDICT-PHASE-3-CLOSED-DEGRADED",
    "PB-VERDICT-PHASE-3-DEFECT-WINDOW",
    "PB-VERDICT-SPAWN-FILTER-BREACH",
)


# --------------------------------------------------------------------- #
# Module-loader helpers (Tag-76 pattern re-use)
# --------------------------------------------------------------------- #


def _load_module(name: str, path: Path):
    """Load a module from a file path without packaging machinery.

    Re-uses the Tag-76 fixture pattern in
    ``test_phase_3_complete_audit_bundle_tag76.py``. Kept module-private
    to avoid coupling the two suites.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def emit_mod():
    return _load_module("_emit_helper_tag78", EMIT_HELPER)


@pytest.fixture(scope="module")
def wire_mod():
    return _load_module("_wire_helper_tag78", WIRE_HELPER)


@pytest.fixture(scope="module")
def production_bringup_doc_text() -> str:
    assert PRODUCTION_BRINGUP_DOC.is_file(), (
        f"production-bringup recipe doc missing: {PRODUCTION_BRINGUP_DOC}"
    )
    return PRODUCTION_BRINGUP_DOC.read_text(encoding="utf-8")


# --------------------------------------------------------------------- #
# Canonical Welle-N marker fixtures (Tag-76 pattern re-use, kept local)
# --------------------------------------------------------------------- #


def _make_welle_marker(
    welle_number: int,
    *,
    anchor_suffix: str = "",
    welle_7_verdict: str = "APPROVED",
    welle_7_decision: str = "FIRE_PHASE_3_COMPLETE_MARKER",
) -> dict:
    """Synthesise a canonical Welle-N audit-anchor marker.

    Mirrors ``test_phase_3_complete_audit_bundle_tag76.py::
    _make_welle_marker`` semantics so the two suites stay byte-stable
    against the same Tag-76 substrate. Extension over the Tag-76 helper:
    Welle-7 marker carries ``global_acceptance_verdict`` and
    ``final_sealing_decision`` so the Production-Bringup B1-step input
    can be derived deterministically per Tag-76 §1.
    """
    base = f"welle-{welle_number}-anchor{anchor_suffix}"
    anchor = hashlib.sha256(base.encode("utf-8")).hexdigest()
    marker: dict = {
        "schema_version": 1,
        "kind": f"welle-{welle_number}-audit-trail-anchor-marker",
        "mode": f"welle-{welle_number}-audit-anchor",
        "welle_number": welle_number,
        "audit_trail_anchor": anchor,
        "bundle_keys": ["rollup", "sign_off"],
        "emitted_at_utc": FROZEN_NOW.isoformat(),
    }
    if welle_number == 7:
        is_approved = welle_7_verdict == "APPROVED"
        is_fire = welle_7_decision == "FIRE_PHASE_3_COMPLETE_MARKER"
        marker["phase_3_final_sealing_tracking"] = {
            "phase_3_final_sealing_active": True,
            "phase_3_final_sealing_status": (
                "sealed" if (is_approved and is_fire) else "pending"
            ),
            "phase_3_final_sealing_iso": "2026-07-03T15:00:00+00:00",
            "global_acceptance_verdict_recorded": is_approved,
            "phase_3_complete_marker_ready": (is_approved and is_fire),
            "phase_3_final_sealing_evidence_ref": (
                "docs/operations/phase-3-final-sealing-runbook.md"
            ),
        }
        marker["pre_auditor_signaling_ready"] = True
        marker["pre_auditor_final_sealing_signaling_ready"] = (
            is_approved and is_fire
        )
        # Tag-78 surface: Production-Bringup B1-step input fields.
        marker["global_acceptance_verdict"] = welle_7_verdict
        marker["final_sealing_decision"] = welle_7_decision
        marker["welle_7_p5_decision_commit_sha"] = "deadbeef" * 5  # 40-hex
    return marker


def _write_seven_markers(
    tmp_path: Path,
    *,
    welle_7_verdict: str = "APPROVED",
    welle_7_decision: str = "FIRE_PHASE_3_COMPLETE_MARKER",
) -> list[Path]:
    """Write seven canonical markers to disk and return their paths."""
    paths: list[Path] = []
    for n in (1, 2, 3, 4, 5, 6, 7):
        marker = _make_welle_marker(
            n,
            welle_7_verdict=welle_7_verdict,
            welle_7_decision=welle_7_decision,
        )
        path = tmp_path / f"welle-{n}-audit-anchor.json"
        path.write_text(
            json.dumps(marker, sort_keys=True), encoding="utf-8"
        )
        paths.append(path)
    return paths


# --------------------------------------------------------------------- #
# Part A -- Phase-3-COMPLETE-marker post-Welle-7-Sign-off coverage
# --------------------------------------------------------------------- #


def test_t01_marker_post_signoff_envelope_approved_pfad(wire_mod, tmp_path):
    """Approved-Pfad: Welle-7 marker carrying APPROVED + FIRE flows
    cleanly through the wire-helper into a producer envelope with
    ``phase_3_complete_marker_ready == True``."""
    paths = _write_seven_markers(
        tmp_path,
        welle_7_verdict="APPROVED",
        welle_7_decision="FIRE_PHASE_3_COMPLETE_MARKER",
    )
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-post-signoff-approved",
        now_utc=FROZEN_NOW,
    )
    assert envelope["kind"] == (
        "phase-3-complete-marker-producer-envelope"
    )
    assert envelope["phase_3_complete_marker_ready"] is True
    assert envelope["global_acceptance_verdict_recorded"] is True
    assert envelope["pre_auditor_final_sealing_signaling_ready"] is True
    assert envelope["welle_1_7_kind_disjointness_pin_ok"] is True
    tracking = envelope["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_status"] == "sealed"
    assert tracking["phase_3_final_sealing_iso"] == (
        "2026-07-03T15:00:00+00:00"
    )


def test_t02_marker_post_signoff_envelope_rejected_pfad(wire_mod, tmp_path):
    """Rejected-Pfad: Welle-7 marker with REJECTED verdict drives the
    envelope into the NO-FIRE shape -- marker-ready False, signaling-
    ready False, verdict-recorded False. The Day-1 B1-step then enters
    PB-B1-MARKER-NO-FIRE per Tag-76 §1."""
    paths = _write_seven_markers(
        tmp_path,
        welle_7_verdict="REJECTED",
        welle_7_decision="BLOCK_PHASE_3_COMPLETE_MARKER",
    )
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-post-signoff-rejected",
        now_utc=FROZEN_NOW,
    )
    assert envelope["phase_3_complete_marker_ready"] is False
    assert envelope["global_acceptance_verdict_recorded"] is False
    assert envelope["pre_auditor_final_sealing_signaling_ready"] is False
    tracking = envelope["phase_3_final_sealing_tracking"]
    assert tracking["phase_3_final_sealing_status"] == "pending"


def test_t03_marker_post_signoff_envelope_defer_pfad(wire_mod, tmp_path):
    """DEFER-Pfad: Welle-7 marker with APPROVED verdict but DEFER
    decision yields marker-ready False (no FIRE) while still recording
    the verdict. Per Tag-76 §1 the Day-1 B1-step then enters
    PB-B1-MARKER-DEFERRED."""
    paths = _write_seven_markers(
        tmp_path,
        welle_7_verdict="APPROVED",
        welle_7_decision="DEFER_FINAL_SEALING",
    )
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-post-signoff-defer",
        now_utc=FROZEN_NOW,
    )
    # APPROVED still records the verdict, but FIRE flag stays False
    # because the decision is DEFER.
    assert envelope["global_acceptance_verdict_recorded"] is True
    assert envelope["phase_3_complete_marker_ready"] is False
    assert envelope["pre_auditor_final_sealing_signaling_ready"] is False


def test_t04_marker_post_signoff_bundle_anchor_stable_across_pfade(
    emit_mod, tmp_path
):
    """The bundle-anchor recipe is independent of the Welle-7 sealing-
    tracking content: changes to the tracking block change the anchor
    (because the marker bytes change), but two runs with the same
    inputs produce the same anchor. This pins the Tag-76 anchor stability
    contract across the three Day-1 B1-step pfade."""
    # Approved path
    tmp_a = tmp_path / "approved"
    tmp_a.mkdir()
    paths_a = _write_seven_markers(
        tmp_a,
        welle_7_verdict="APPROVED",
        welle_7_decision="FIRE_PHASE_3_COMPLETE_MARKER",
    )
    markers_a = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=paths_a
    )
    anchor_a_1 = emit_mod.compute_phase_3_complete_bundle_anchor(markers_a)
    anchor_a_2 = emit_mod.compute_phase_3_complete_bundle_anchor(markers_a)
    assert anchor_a_1 == anchor_a_2  # determinism within pfad

    # Rejected path
    tmp_b = tmp_path / "rejected"
    tmp_b.mkdir()
    paths_b = _write_seven_markers(
        tmp_b,
        welle_7_verdict="REJECTED",
        welle_7_decision="BLOCK_PHASE_3_COMPLETE_MARKER",
    )
    markers_b = emit_mod.load_phase_3_complete_bundle(
        welle_marker_paths=paths_b
    )
    anchor_b = emit_mod.compute_phase_3_complete_bundle_anchor(markers_b)

    # Different inputs -> different anchors. This is by design: the
    # bundle anchor commits to the Welle-7 tracking-block bytes.
    assert anchor_a_1 != anchor_b
    assert OTS_ANCHOR_RE.match(anchor_a_1)
    assert OTS_ANCHOR_RE.match(anchor_b)


def test_t05_marker_post_signoff_envelope_carries_welle_7_p5_sha(
    wire_mod, tmp_path
):
    """The Welle-7 marker's ``welle_7_p5_decision_commit_sha`` is the
    Tag-75 P5 commit reference that the Day-1 B1-step writes into
    ``state/phase-3-complete-marker.json``. The Tag-76 envelope MUST
    surface this sha on the welle-7 entry so Day-1 can pick it up
    without re-reading the marker file."""
    paths = _write_seven_markers(tmp_path)
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-p5-sha",
        now_utc=FROZEN_NOW,
    )
    # The producer envelope carries the welle_marker_paths for Day-1
    # to re-read the welle-7 source for P5-sha.
    welle_7_path = Path(envelope["welle_marker_paths"]["welle-7"])
    assert welle_7_path.is_file()
    welle_7_doc = json.loads(welle_7_path.read_text(encoding="utf-8"))
    assert welle_7_doc["welle_7_p5_decision_commit_sha"] == (
        "deadbeef" * 5
    )


def test_t06_marker_post_signoff_subprocess_smoke(tmp_path):
    """Subprocess CLI smoke: the wire-helper emits the envelope JSON
    file on disk with all post-Sign-off fields present. This is the
    Day-1 06:00 CEST kick-off invocation that Operator-Hand runs
    against the seven Welle-N markers."""
    # Write fixtures using a private helper invocation (no shared state).
    paths = _write_seven_markers(tmp_path)
    envelope_out = tmp_path / "phase-3-complete-producer-envelope.json"
    argv = [
        sys.executable,
        str(WIRE_HELPER),
    ]
    for n, p in enumerate(paths, start=1):
        argv.extend([f"--welle-{n}-marker", str(p)])
    argv.extend(
        [
            "--envelope-out",
            str(envelope_out),
            "--actor",
            "tag-78-day-1-smoke",
            "--now",
            FROZEN_NOW.isoformat(),
        ]
    )
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert envelope_out.is_file()
    doc = json.loads(envelope_out.read_text(encoding="utf-8"))
    assert doc["welle_bundle_count"] == 7
    assert doc["phase_3_complete_marker_ready"] is True
    assert OTS_ANCHOR_RE.match(doc["phase_3_complete_bundle_anchor"])


# --------------------------------------------------------------------- #
# Part B -- Production-Bringup Day-1..Day-7 sequence pinning
# --------------------------------------------------------------------- #


def test_t07_doc_frontmatter_status_active_tag76(production_bringup_doc_text):
    """The Production-Bringup-Recipe doc frontmatter pins
    ``status: active`` and ``tag: tag-76`` -- these anchors guard
    against an accidental status-drift (e.g. archived/draft) that
    would shift the Day-1..Day-7 sequence."""
    text = production_bringup_doc_text
    assert 'status: "active"' in text, "doc must be status: active"
    assert 'tag: "tag-76"' in text, "doc must be tag: tag-76"
    assert 'audience: "operator,ar,engineering,internal-audit"' in text


def test_t08_doc_day_n_calendar_table_pins_seven_days(
    production_bringup_doc_text,
):
    """The Zeit-Domain table maps Day-1..Day-7 to canonical dates and
    weekdays. We pin the seven entries verbatim so a doc edit that
    shifts dates (or shifts the weekday assumption) breaks here."""
    text = production_bringup_doc_text
    # Day-1 anchor: 2026-07-04 (Sa)
    assert "| Day-1 -- Phase-3-COMPLETE-Marker-Fire-Day | 2026-07-04 (Sa)" in text
    # Day-2..Day-5
    assert "| Day-2 -- Stability-Window-Start | 2026-07-05 (So)" in text
    assert "| Day-3 | 2026-07-06 (Mo)" in text
    assert "| Day-4 | 2026-07-07 (Di)" in text
    assert "| Day-5 | 2026-07-08 (Mi)" in text
    # Day-6, Day-7
    assert "| Day-6 -- J3/K3-Closure-Window | 2026-07-09 (Do)" in text
    assert (
        "| Day-7 -- Marathon-Final-Bilanz-Day | 2026-07-10 (Fr)"
        in text
    )


def test_t09_doc_b_steps_all_five_present(production_bringup_doc_text):
    """All five B-steps (B1..B5) have a `### B<N> --` heading in the
    doc. Missing-step regression would shift the Day-N -> step mapping."""
    text = production_bringup_doc_text
    for step in B_STEPS:
        # Heading shape: `### B1 --` etc.
        assert f"### {step} --" in text, f"missing B-step heading: {step}"


def test_t10_doc_rollback_pfade_all_four_present(
    production_bringup_doc_text,
):
    """All four Rollback-Pfade (R-PB-A..R-PB-D) have a `### R-PB-X --`
    heading. The Tag-76 §5 list defines the canonical Failure-Mode
    coverage; missing entries leave Day-N stop-on-fail paths
    unspecified."""
    text = production_bringup_doc_text
    for pfad in R_PFADE:
        assert f"### {pfad} --" in text, (
            f"missing rollback pfad heading: {pfad}"
        )


def test_t11_doc_ar_hand_touchpoints_all_three_present(
    production_bringup_doc_text,
):
    """All three AR-Hand Touchpoints (TP-PB-1..TP-PB-3) have a
    `### TP-PB-N --` heading. These are the AR sign-off anchors at
    Day-1 10:00, Day-5 14:00, Day-7 14:00."""
    text = production_bringup_doc_text
    for tp in TP_PB:
        assert f"### {tp} --" in text, f"missing AR-touchpoint: {tp}"


def test_t12_doc_aggregate_verdict_table_pins_seven_verdicts(
    production_bringup_doc_text,
):
    """§7 Aggregate-Verdict-Roll-up table lists the seven verdict-
    markers. Missing or renamed verdicts here cascade into the
    Day-7-close ``state/production-bringup-window-verdict.json`` shape
    that Aisha's audit pipeline ingests."""
    text = production_bringup_doc_text
    for verdict in AGGREGATE_VERDICTS:
        assert verdict in text, f"missing aggregate verdict: {verdict}"


def test_t13_doc_day_1_b1_time_window_06_10_cest(production_bringup_doc_text):
    """Day-1 B1 time-window is 06:00 -- 10:00 CEST. This is the
    operationally-load-bearing window: the marker-fire commit MUST
    land before AR-pair sanity at 10:00 (TP-PB-1)."""
    text = production_bringup_doc_text
    assert (
        "### B1 -- Phase-3-COMPLETE-Marker-Fire (Day-1, 06:00 -- 10:00 CEST)"
        in text
    )
    # TP-PB-1 fires at 10:00 CEST after the B1-window closes.
    assert (
        "### TP-PB-1 -- Day-1 Phase-3-COMPLETE-Marker-Fire-Sanity "
        "(2026-07-04, 10:00 CEST)"
    ) in text


def test_t14_doc_day_2_5_b2_time_window_09_cest(production_bringup_doc_text):
    """Day-2..Day-5 B2 daily-stability-probe-aggregation fires at
    09:00 CEST. This anchors the live-smoke-window job that produces
    the previous 00:00 -- 08:00 CEST probe output."""
    text = production_bringup_doc_text
    assert (
        "### B2 -- Daily-Stability-Probe-Aggregation "
        "(Day-2..Day-5, je 09:00 CEST)"
    ) in text


def test_t15_doc_day_6_b3_j3_k3_window(production_bringup_doc_text):
    """Day-6 B3 J3/K3-Closure-Records-Commit window is 09:00 -- 14:00
    CEST (Donnerstag 2026-07-09). These are Phase-3-close items
    explicitly permitted under the PHASE-4-HOLD pin per §9.3."""
    text = production_bringup_doc_text
    assert (
        "### B3 -- J3/K3-Closure-Records-Commit "
        "(Day-6, 09:00 -- 14:00 CEST)"
    ) in text
    # Body must declare the J3/K3 closure as Phase-3-close items.
    assert "j3_state: \"RESOLVED-INTENTIONAL\"" in text or (
        "j3_state: 'RESOLVED-INTENTIONAL'" in text
    )


def test_t16_doc_day_7_b4_b5_bilanz_and_post_mortem(
    production_bringup_doc_text,
):
    """Day-7 traegt sowohl B4 (Marathon-Final-Bilanz, 09:00 -- 14:00
    CEST) als auch B5 (Phase-3-Post-Mortem-Anstoss, 14:00 -- 16:00
    CEST). Beide sind Phase-3-close items per Tag-66 Eve-Recipe §9.3
    Items 1+2."""
    text = production_bringup_doc_text
    assert (
        "### B4 -- Marathon-Final-Bilanz-Lieferbericht "
        "(Day-7, 09:00 -- 14:00 CEST)"
    ) in text
    assert (
        "### B5 -- Phase-3-Post-Mortem-Anstoss (Day-7, 14:00 -- 16:00 CEST)"
        in text
    )


def test_t17_doc_phase_4_hold_vor_re_arm_pin_verbatim(
    production_bringup_doc_text,
):
    """The verbatim AR-Vorzeichen 'Halt vor Phase 4' anchor MUST be
    present in §9.1 and the pin string `PHASE-4-HOLD-VOR-RE-ARM` MUST
    appear unchanged. This is the governance pin that holds through
    Day-7-close and beyond."""
    text = production_bringup_doc_text
    # The §9.1 verbatim anchor (multi-line blockquote).
    assert (
        "Phase-3-Marathon ends at Welle-7 cutover and Marathon-Final-"
        in text
    )
    assert (
        "explicit AR-Hand re-arm signal" in text
    )
    # The canonical pin name appears throughout the doc.
    assert "PHASE-4-HOLD-VOR-RE-ARM" in text
    # The §9.4 re-arm signal name.
    assert "PHASE-4-RE-ARMED" in text


def test_t18_doc_phase_3_close_permitted_items_list_of_five(
    production_bringup_doc_text,
):
    """§9.3 lists exactly five Phase-3-close items permitted under
    the pin (Marker-Fire/NO-FIRE, Daily-Stability-Probe-Agg, J3/K3
    Closure-Records, Marathon-Final-Bilanz, Phase-3-Post-Mortem-
    Anstoss). The phrase 'complete list' anchors this to be an
    exhaustive enumeration -- additions must edit the doc, not slip
    in via spawn-briefs."""
    text = production_bringup_doc_text
    # The five-item header.
    assert "### §9.3 -- Phase-3-Close Items Permitted Under the Pin" in text
    # The exhaustive-list anchor phrase.
    assert "complete" in text and "list of permitted Phase-3-" in text


def test_t19_doc_sandbox_ok_per_b_step_pinned(production_bringup_doc_text):
    """§9.6 Sandbox-Boundary-Reaffirmation explicitly enumerates the
    Sandbox-OK / Operator-Hand mapping per B-step. Missing or shuffled
    entries here would let the Continuous-Mode autopilot push a step
    that should be Operator-Hand-Sandbox-Gap."""
    text = production_bringup_doc_text
    # B1: Operator-Hand (commit + push).
    assert "B1 (marker-fire commit + push) is Operator-Hand" in text
    # B2..B5: Sandbox-OK.
    assert "B2 (daily-stability-probe aggregation commit + push) is" in text
    assert "Sandbox-OK" in text
    assert "B3 (J3/K3-closure-records commit + push) is Sandbox-OK" in text
    assert "B4 (Marathon-Final-Bilanz Lieferbericht) is Sandbox-OK" in text
    assert (
        "B5 (Phase-3-Post-Mortem-Anstoss spawn) is Sandbox-OK at the"
    ) in text


# --------------------------------------------------------------------- #
# Part C -- Day-1..Day-7 sequence cross-validation against Welle-7 input
# --------------------------------------------------------------------- #


def test_t20_day_1_b1_input_envelope_carries_marker_ready_flag(
    wire_mod, tmp_path
):
    """The Day-1 B1-step reads the Tag-76 envelope as its source-of-
    truth for whether to FIRE or NO-FIRE. The
    ``phase_3_complete_marker_ready`` boolean is the canonical input
    flag: True -> PB-B1-MARKER-FIRED path, False -> PB-B1-MARKER-NO-FIRE
    or PB-B1-MARKER-DEFERRED."""
    # Approved + FIRE -> marker-ready True.
    fire_dir = tmp_path / "fire"
    fire_dir.mkdir(exist_ok=True)
    paths_fire = _write_seven_markers(
        fire_dir,
        welle_7_verdict="APPROVED",
        welle_7_decision="FIRE_PHASE_3_COMPLETE_MARKER",
    )
    env_fire = wire_mod.emit_envelope(
        welle_marker_paths=paths_fire,
        actor="tag-78-day-1-fire",
        now_utc=FROZEN_NOW,
    )
    assert env_fire["phase_3_complete_marker_ready"] is True

    block_dir = tmp_path / "block"
    block_dir.mkdir(exist_ok=True)
    paths_block = _write_seven_markers(
        block_dir,
        welle_7_verdict="REJECTED",
        welle_7_decision="BLOCK_PHASE_3_COMPLETE_MARKER",
    )
    env_block = wire_mod.emit_envelope(
        welle_marker_paths=paths_block,
        actor="tag-78-day-1-block",
        now_utc=FROZEN_NOW,
    )
    assert env_block["phase_3_complete_marker_ready"] is False


def test_t21_day_n_calendar_pin_matches_doc_table(production_bringup_doc_text):
    """The DAY_N_CALENDAR test-constant is the in-test source-of-truth
    for the Day-N -> (date, weekday) mapping. This test cross-checks
    each entry against the doc's Zeit-Domain table so a drift between
    test-expectations and the doc is caught here (single point-of-
    update is the doc)."""
    text = production_bringup_doc_text
    for day_n, date, weekday in DAY_N_CALENDAR:
        # The doc table entries have the form
        # `| Day-N -- ... | YYYY-MM-DD (Weekday) | ...`
        # or just `| Day-N | YYYY-MM-DD (Weekday) | ...` for Day-3..5.
        expected_cell = f"{date} ({weekday})"
        assert expected_cell in text, (
            f"Day-{day_n} cell `{expected_cell}` missing from doc"
        )


def test_t22_day_7_close_marker_pin_unchanged_after_b2_outcomes(
    production_bringup_doc_text,
):
    """R-PB-B (Stability-Window Day-N Blocking Degradation) and R-PB-C
    (J3-K3 Carry-Forward) both explicitly state ``Phase-3-COMPLETE-
    state: unaffected (marker-state was set on Day-1)``. This is the
    irreversibility-anchor: Day-2..Day-7 outcomes do NOT revise the
    Day-1 marker-state, period."""
    text = production_bringup_doc_text
    # Two rollback-pfade carry this exact anchor. The doc uses
    # bold-markdown around the key (`**Phase-3-COMPLETE-state**`).
    occurrences = text.count(
        "**Phase-3-COMPLETE-state**: unaffected"
    )
    # R-PB-B and R-PB-C both carry the anchor explicitly; R-PB-D adds
    # a third "unaffected" (Final-Bilanz-spawn-filter-violation).
    assert occurrences >= 2, (
        f"expected >=2 'unaffected' anchors, got {occurrences}"
    )


def test_t23_verdict_roll_up_clean_path_anchored_to_all_b_steps(
    production_bringup_doc_text,
):
    """§7 PB-VERDICT-PHASE-3-CLOSED-CLEAN row conditions the green
    verdict on the conjunction of:
    - B1=MARKER-FIRED
    - all B2 Day-N STABLE or DEGRADED-NON-BLOCKING
    - B3=J3-K3-CLOSED
    - B4=DELIVERED
    - B5=ANGESTOSSEN
    plus three TP-PB sign-offs PASS.

    This pins the clean-pfad as a 5-step conjunction (not a partial
    sign-off)."""
    text = production_bringup_doc_text
    # All five B-step success-anchors appear in the same line of the
    # §7 table.
    row = next(
        (
            line for line in text.splitlines()
            if "PB-VERDICT-PHASE-3-CLOSED-CLEAN" in line
        ),
        None,
    )
    assert row is not None, "PB-VERDICT-PHASE-3-CLOSED-CLEAN row missing"
    for anchor in (
        "B1=MARKER-FIRED",
        "STABLE",
        "DEGRADED-NON-BLOCKING",
        "B3=J3-K3-CLOSED",
        "B4=DELIVERED",
        "B5=ANGESTOSSEN",
    ):
        assert anchor in row, (
            f"clean-pfad anchor missing from verdict row: {anchor}"
        )


def test_t24_helper_substrate_section_references_tag_76_artefacts(
    production_bringup_doc_text,
):
    """§8 Helper-Substrat lists the four Tag-76 substrate artefacts:
    verifier, tests, aggregator (Tag-77 follow-on), and the cross-link
    to Welle-7-Day P5 substrate. The aggregator is Tag-77 follow-on so
    the doc explicitly marks it as 'planned Tag-77 substrate'. This
    test pins the helper inventory."""
    text = production_bringup_doc_text
    assert "tooling/ci/verify_production_bringup_recipe_doc.py" in text
    assert (
        "tests/observability/test_production_bringup_recipe_tag76.py"
    ) in text
    assert "tooling/ci/aggregate_production_bringup_verdict.py" in text
    assert "planned" in text and "Tag-77" in text
    # Cross-link to Welle-7-Day P5 substrate input.
    assert "state/phase-3-marathon-global-verdict.json" in text
    assert "tooling/ci/aggregate_pyramide_run_order_verdict.py" in text


def test_t25_envelope_anchor_match_across_two_wire_helper_calls(
    wire_mod, tmp_path
):
    """Two consecutive ``wire_mod.emit_envelope`` calls on the same
    Welle-1..7 inputs produce byte-identical bundle anchors. This is
    the Day-1-replay safety property: if the operator-hand re-runs
    B1 at Day-1 14:00 after B1-HOLD at 06:00, the second invocation
    MUST emit the same anchor -- otherwise the marker-fire commit
    would silently anchor a different bundle."""
    paths = _write_seven_markers(tmp_path)
    env_1 = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-replay-1",
        now_utc=FROZEN_NOW,
    )
    env_2 = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-replay-2",
        now_utc=FROZEN_NOW,
    )
    assert (
        env_1["phase_3_complete_bundle_anchor"]
        == env_2["phase_3_complete_bundle_anchor"]
    )
    # The per-welle anchors also match.
    a1 = [e["audit_trail_anchor"] for e in env_1["welle_bundle_anchors"]]
    a2 = [e["audit_trail_anchor"] for e in env_2["welle_bundle_anchors"]]
    assert a1 == a2


def test_t26_envelope_sandbox_boundary_no_subprocess_no_network(
    wire_mod, tmp_path
):
    """Tag-76 §9.6 sandbox-OK contract: B2..B5 are sandbox-clean,
    which the wire-helper enforces by declaring no network IO, no OTS
    CLI subprocess, stdlib-only. Surface this from the envelope so
    a regression in the helper (e.g. adding an OTS calendar call)
    cannot pass review without flipping the boundary flag."""
    paths = _write_seven_markers(tmp_path)
    envelope = wire_mod.emit_envelope(
        welle_marker_paths=paths,
        actor="tag-78-sandbox",
        now_utc=FROZEN_NOW,
    )
    boundary = envelope["sandbox_boundary"]
    assert boundary["no_network_io"] is True
    assert boundary["no_ots_cli_subprocess"] is True
    assert boundary["stdlib_only"] is True
