# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""A1 Cross-Modul-Drift — Defence-Layer-4 (Marathon-Rollup Cascade).

Auftrag-Anker
-------------

* Tag-51 Amara Auftrag (Mira, 2026-05-19): formalise the fourth A1
  defence-layer that the Tag-50 Consolidated Coverage-Sweep
  (`tests/phase_3c/test_pre_mortem_coverage_sweep_tag_50_consolidated.py`
  §5 `test_t50_a1_cross_welle_hot_spot_cascade_marathon_coverage_uplift`)
  surfaced informally. Tag-51 promotes that uplift to a dedicated
  test-class with >=20 hermetic tests, and updates the Pre-Mortem
  coverage-matrix doc to record Defence-Layer-4 in the §2 A1 entry.
* Tag-50 §7.3 Candidate 3 (Amara,
  `docs/quality-gates/pre-mortem-failure-mode-coverage.md`) — A1
  marathon-rollup defence-in-depth, no state transition (stays
  COVERED), fourth defence-layer added.
* Tag-49 PR #316 (`tests/phase_3c/test_cross_welle_hot_spot_e2e.py`)
  + PR #317 (`tests/ci/test_cross_welle_hot_spot_aggregator.py`) are
  the underlying substrate. This file is the **A1-Failure-Mode
  framing** layer on top of that substrate: every assertion below
  is phrased in terms of the A1 invariant it pins, not in terms of
  the aggregator's internal contract.

Why a dedicated test-class
--------------------------

The four A1 defence-layers are now:

1. **Layer-1 — Pairwise Welle-Isolation** (Tag-40,
   `test_phase_3_final_regression.py`).
   Invariant: ``state(welle_m).intersection(state(welle_n)) == {}``
   for all ``m < n``. Pairwise structural isolation.

2. **Layer-2 — Marathon-Aggregate Blocker-Rejection** (Tag-43,
   `test_marathon_schluss_acceptance_drill.py`).
   Invariant: marathon-aggregate refuses a blocker marker on any
   cross-welle drift signal between adjacent wellen.

3. **Layer-3 — Namespace-Prefix Discipline (AP-4)** (Tag-44,
   `test_marathon_anti_patterns.py`).
   Invariant: state-backing namespace prefix is bidirectionally
   strict; no cross-prefix read/write across welle boundaries.

4. **Layer-4 — Marathon-Rollup Cascade-Detection** (Tag-49 PR #316
   substrate + Tag-51 dedicated framing — this file).
   Invariant: when an earlier-welle goes BLOCK during the four-week
   marathon, downstream welle readiness is forfeit *per the
   Henrik-Tag-44 Cross-Welle-Risiko-Matrix propagation map*, and
   the marathon-rollup escalates to BLOCK regardless of downstream
   per-welle verdict.

Defence-Layer-4 is *operationally distinct* from Layer-1..3: where
Layer-1..3 detect drift on the static contract surface (schema /
namespace), Layer-4 detects drift on the **dynamic marathon
trace** by attributing per-welle BLOCK to downstream readiness
loss. This catches A1 incarnations that only manifest under
temporal coupling: a Welle-3 audit-trail-integrity red on day D
mechanically invalidates Welle-4/5/7 downstream readiness on
day D, even if the static contracts hold.

Test taxonomy (A1-DL4-* IDs, 22 tests, Auftrag minimum 20)
----------------------------------------------------------

A1-DL4-ANCHOR-* — substance-anchor presence (5 tests)
  01. test_a1_dl4_anchor_per_welle_aggregators_all_five_on_tree
  02. test_a1_dl4_anchor_cross_welle_aggregator_on_tree
  03. test_a1_dl4_anchor_e2e_test_on_tree
  04. test_a1_dl4_anchor_ci_test_on_tree
  05. test_a1_dl4_anchor_matrix_doc_records_layer_4

A1-DL4-PROP-* — propagation-map cross-validation (5 tests)
  06. test_a1_dl4_prop_welle_3_downstream_set
  07. test_a1_dl4_prop_welle_4_downstream_set
  08. test_a1_dl4_prop_welle_5_downstream_set
  09. test_a1_dl4_prop_welle_6_downstream_set
  10. test_a1_dl4_prop_welle_7_terminal_empty_downstream

A1-DL4-CASCADE-* — single-day cascade contracts (5 tests)
  11. test_a1_dl4_cascade_welle_3_block_propagates_to_4_5_7
  12. test_a1_dl4_cascade_welle_4_block_propagates_to_5_7
  13. test_a1_dl4_cascade_welle_5_block_propagates_to_7
  14. test_a1_dl4_cascade_welle_6_block_propagates_to_7
  15. test_a1_dl4_cascade_welle_7_block_does_not_cascade

A1-DL4-MARATHON-* — marathon-rollup contracts (4 tests)
  16. test_a1_dl4_marathon_all_green_28_days_no_cascade_no_block
  17. test_a1_dl4_marathon_single_welle_3_block_escalates_marathon
  18. test_a1_dl4_marathon_multi_day_flap_each_block_recorded
  19. test_a1_dl4_marathon_terminal_welle_7_red_no_cascade_records

A1-DL4-DOC-* — doc-anchor / coverage-classification (3 tests)
  20. test_a1_dl4_doc_a1_section_lists_defence_layer_4
  21. test_a1_dl4_doc_tag_50_candidate_3_records_layer_4
  22. test_a1_dl4_doc_a1_stays_covered_no_state_transition

Hermetic posture
----------------

stdlib + pytest only. The per-welle aggregators are loaded via
``importlib`` from in-repo paths and exercised purely on env-var
dicts. No subprocess, no network, no podman, no live-VM. The
matrix doc is read as text only.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import pytest


# ---------------------------------------------------------------------------
# Repo paths and constants
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HOT_SPOT_WELLEN: Tuple[int, ...] = (3, 4, 5, 6, 7)

# Henrik Tag-44 Pre-Mortem Cross-Welle-Risiko-Matrix propagation map.
# Source-of-truth for Defence-Layer-4: a BLOCK on the source welle
# pre-conditionally blocks every welle in its downstream tuple.
EXPECTED_PROPAGATION: Dict[int, Tuple[int, ...]] = {
    3: (4, 5, 7),
    4: (5, 7),
    5: (7,),
    6: (7,),
    7: (),
}

MATRIX_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
)


# ---------------------------------------------------------------------------
# Substance loaders
# ---------------------------------------------------------------------------


def _load_aggregator(welle: int):
    path = REPO_ROOT / "tooling" / "ci" / f"welle_{welle}_hot_spot_aggregator.py"
    if not path.is_file():
        pytest.fail(f"A1-DL4 substance gap: per-welle aggregator missing: {path}")
    mod_name = f"_a1_dl4_load_welle_{welle}_hot_spot_aggregator"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        pytest.fail(f"A1-DL4 substance gap: importlib spec build failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aggregators() -> Dict[int, Any]:
    return {w: _load_aggregator(w) for w in HOT_SPOT_WELLEN}


def _green_env_for_welle(welle: int) -> Dict[str, str]:
    """Env-dict that yields a CLEAR per-welle verdict."""
    base = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "PRE_AUDITOR_STATE": "present",
    }
    integrity_key = {
        3: "WELLE_3_AUDIT_TRAIL_INTEGRITY",
        4: "WELLE_4_PERSISTENCE_DRIFT",
        5: "WELLE_5_LIFECYCLE_FSM_INTEGRITY",
        6: "WELLE_6_SUBSCRIBE_LOOP_INTEGRITY",
        7: "WELLE_7_RECOVERY_INTEGRITY",
    }[welle]
    base[integrity_key] = "green"
    return base


def _red_env_for_welle(welle: int) -> Dict[str, str]:
    """Env-dict that yields a BLOCK per-welle verdict via integrity-red."""
    env = _green_env_for_welle(welle)
    integrity_key = {
        3: "WELLE_3_AUDIT_TRAIL_INTEGRITY",
        4: "WELLE_4_PERSISTENCE_DRIFT",
        5: "WELLE_5_LIFECYCLE_FSM_INTEGRITY",
        6: "WELLE_6_SUBSCRIBE_LOOP_INTEGRITY",
        7: "WELLE_7_RECOVERY_INTEGRITY",
    }[welle]
    env[integrity_key] = "red"
    env["CHECK2_STATUS"] = "red"
    return env


def _build_envelope(aggregators: Mapping[int, Any], welle: int,
                    env: Mapping[str, str]) -> Dict[str, Any]:
    return aggregators[welle].build_envelope(dict(env))


def _marathon_dates(start: date, days: int) -> Tuple[str, ...]:
    return tuple((start + timedelta(days=i)).isoformat() for i in range(days))


# ---------------------------------------------------------------------------
# Defence-Layer-4 reference rollup (A1-framed, derived from Tag-49 PR #316
# `reference_cross_welle_rollup`). Kept inline to make the A1 contract
# explicit and independent of the substrate test-file's refactors.
# ---------------------------------------------------------------------------


def _reference_dl4_rollup(
    daily_envelopes: Mapping[str, Mapping[int, Mapping[str, Any]]],
) -> Dict[str, Any]:
    rank = {"CLEAR": 0, "CAUTION": 1, "BLOCK": 2}
    inv_rank = {v: k for k, v in rank.items()}
    per_welle_worst: Dict[int, str] = {w: "CLEAR" for w in HOT_SPOT_WELLEN}
    cascade_events: list[Dict[str, Any]] = []
    for day in sorted(daily_envelopes.keys()):
        day_envs = daily_envelopes[day]
        for welle in HOT_SPOT_WELLEN:
            env = day_envs.get(welle)
            v = env.get("verdict", "BLOCK") if env is not None else "BLOCK"
            if rank[v] > rank[per_welle_worst[welle]]:
                per_welle_worst[welle] = v
            if v == "BLOCK":
                for downstream in EXPECTED_PROPAGATION[welle]:
                    cascade_events.append(
                        {
                            "day": day,
                            "source_welle": welle,
                            "downstream_welle": downstream,
                        }
                    )
    worst_rank = max(rank[v] for v in per_welle_worst.values())
    if cascade_events:
        marathon_rank = max(worst_rank, rank["BLOCK"])
    else:
        marathon_rank = worst_rank
    cascade_events.sort(
        key=lambda e: (e["day"], e["source_welle"], e["downstream_welle"])
    )
    return {
        "per_welle_worst": per_welle_worst,
        "cascade_events": cascade_events,
        "marathon_verdict": inv_rank[marathon_rank],
    }


# ===========================================================================
# A1-DL4-ANCHOR-* — substance-anchor presence (5 tests).
# ===========================================================================


def test_a1_dl4_anchor_per_welle_aggregators_all_five_on_tree() -> None:
    """All five per-welle hot-spot aggregators (Tag-45 + Tag-48) on tree.

    Defence-Layer-4 cannot fire without the upstream per-welle
    verdict envelopes; this anchor pins their presence.
    """
    for welle in HOT_SPOT_WELLEN:
        path = (
            REPO_ROOT / "tooling" / "ci" / f"welle_{welle}_hot_spot_aggregator.py"
        )
        assert path.is_file(), (
            f"A1-DL4 substrate gap: welle-{welle} aggregator missing — "
            f"defence-layer-4 cascade-detection has no input."
        )


def test_a1_dl4_anchor_cross_welle_aggregator_on_tree() -> None:
    """Tag-49 PR #317 cross-welle aggregator carries Defence-Layer-4."""
    path = REPO_ROOT / "tooling" / "ci" / "cross_welle_hot_spot_aggregator.py"
    assert path.is_file(), (
        "A1-DL4 substrate gap: cross-welle aggregator missing — "
        "defence-layer-4 marathon-rollup unreachable."
    )


def test_a1_dl4_anchor_e2e_test_on_tree() -> None:
    """Tag-49 PR #316 E2E test is the Layer-4 substrate acceptance gate."""
    path = REPO_ROOT / "tests" / "phase_3c" / "test_cross_welle_hot_spot_e2e.py"
    assert path.is_file(), (
        "A1-DL4 substrate gap: Tag-49 PR #316 E2E missing — "
        "defence-layer-4 unanchored."
    )


def test_a1_dl4_anchor_ci_test_on_tree() -> None:
    """Tag-49 PR #317 CI test pins the aggregator-side Layer-4 substrate."""
    path = REPO_ROOT / "tests" / "ci" / "test_cross_welle_hot_spot_aggregator.py"
    assert path.is_file(), (
        "A1-DL4 substrate gap: Tag-49 PR #317 CI test missing."
    )


def test_a1_dl4_anchor_matrix_doc_records_layer_4() -> None:
    """The Pre-Mortem coverage-matrix doc records Defence-Layer-4 for A1.

    Tag-51 Mira-Auftrag includes a coverage-matrix-update for the §2
    A1 entry naming Defence-Layer-4. This anchor pins that the doc
    mention exists and is the canonical record.
    """
    assert MATRIX_DOC.is_file(), "Pre-Mortem coverage-matrix doc removed."
    content = MATRIX_DOC.read_text(encoding="utf-8")
    # Layer-4 must be named in some form near the A1 section.
    assert "Defence-Layer-4" in content or "defence-layer-4" in content.lower(), (
        "A1-DL4 doc-anchor missing: matrix-doc does not name "
        "Defence-Layer-4. Tag-51 update incomplete."
    )


# ===========================================================================
# A1-DL4-PROP-* — propagation-map cross-validation (5 tests).
# ===========================================================================


@pytest.mark.parametrize("welle,expected", [
    (3, (4, 5, 7)),
    (4, (5, 7)),
    (5, (7,)),
    (6, (7,)),
])
def test_a1_dl4_prop_per_welle_downstream_matches_expected(
    aggregators: Dict[int, Any], welle: int, expected: Tuple[int, ...]
) -> None:
    """Per-welle DOWNSTREAM_PROPAGATION_WELLEN matches Henrik-Risiko-Matrix.

    A1-DL4-PROP-{3,4,5,6}: the per-welle aggregator's own constant
    must agree with the Defence-Layer-4 expected propagation map.
    Drift here would mean cascade-detection misses an A1
    propagation path.
    """
    mod = aggregators[welle]
    got = tuple(getattr(mod, "DOWNSTREAM_PROPAGATION_WELLEN"))
    assert got == expected, (
        f"A1-DL4 propagation-map drift for welle-{welle}: "
        f"aggregator says {got}, Defence-Layer-4 expects {expected}."
    )


def test_a1_dl4_prop_welle_7_terminal_empty_downstream(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-7 is terminal: empty downstream set.

    The Welle-7 aggregator may legitimately omit
    ``DOWNSTREAM_PROPAGATION_WELLEN`` (no downstream); if the
    constant is present it must be empty. A non-empty value would
    indicate a Defence-Layer-4 propagation-map error.
    """
    mod = aggregators[7]
    got = tuple(getattr(mod, "DOWNSTREAM_PROPAGATION_WELLEN", ()))
    assert got == (), (
        f"A1-DL4 terminal-welle violation: welle-7 has downstream {got} "
        f"but Defence-Layer-4 declares welle-7 terminal."
    )


# ===========================================================================
# A1-DL4-CASCADE-* — single-day cascade contracts (5 tests).
# ===========================================================================


def test_a1_dl4_cascade_welle_3_block_propagates_to_4_5_7(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-3 BLOCK on day D pre-conditionally blocks {4, 5, 7}."""
    env = _build_envelope(aggregators, 3, _red_env_for_welle(3))
    assert env["verdict"] == "BLOCK"
    cprop = env.get("cross_welle_propagation", {})
    assert cprop, "A1-DL4 propagation block missing on welle-3 BLOCK."
    pcb = tuple(sorted(cprop.get("pre_conditional_blocked", [])))
    assert pcb == (4, 5, 7), (
        f"A1-DL4 cascade contract violated: welle-3 BLOCK propagates "
        f"to {pcb}, defence-layer-4 expects (4, 5, 7)."
    )


def test_a1_dl4_cascade_welle_4_block_propagates_to_5_7(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-4 BLOCK propagates to {5, 7}."""
    env = _build_envelope(aggregators, 4, _red_env_for_welle(4))
    assert env["verdict"] == "BLOCK"
    cprop = env.get("cross_welle_propagation", {})
    assert cprop, "A1-DL4 propagation block missing on welle-4 BLOCK."
    pcb = tuple(sorted(cprop.get("pre_conditional_blocked", [])))
    assert pcb == (5, 7), (
        f"A1-DL4 cascade contract violated: welle-4 BLOCK propagates "
        f"to {pcb}, defence-layer-4 expects (5, 7)."
    )


def test_a1_dl4_cascade_welle_5_block_propagates_to_7(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-5 BLOCK propagates to {7}."""
    env = _build_envelope(aggregators, 5, _red_env_for_welle(5))
    assert env["verdict"] == "BLOCK"
    cprop = env.get("cross_welle_propagation", {})
    assert cprop, "A1-DL4 propagation block missing on welle-5 BLOCK."
    pcb = tuple(sorted(cprop.get("pre_conditional_blocked", [])))
    assert pcb == (7,), (
        f"A1-DL4 cascade contract violated: welle-5 BLOCK propagates "
        f"to {pcb}, defence-layer-4 expects (7,)."
    )


def test_a1_dl4_cascade_welle_6_block_propagates_to_7(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-6 BLOCK propagates to {7}.

    Welle-6 is the subscribe-loop integrity layer; a BLOCK here
    means the Welle-7 recovery path cannot rely on the message-bus
    contract holding, hence downstream-7 is pre-conditionally
    blocked.
    """
    env = _build_envelope(aggregators, 6, _red_env_for_welle(6))
    assert env["verdict"] == "BLOCK"
    cprop = env.get("cross_welle_propagation", {})
    assert cprop, "A1-DL4 propagation block missing on welle-6 BLOCK."
    pcb = tuple(sorted(cprop.get("pre_conditional_blocked", [])))
    assert pcb == (7,), (
        f"A1-DL4 cascade contract violated: welle-6 BLOCK propagates "
        f"to {pcb}, defence-layer-4 expects (7,)."
    )


def test_a1_dl4_cascade_welle_7_block_does_not_cascade(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-7 is terminal: a BLOCK does not cascade.

    Welle-7 is the recovery-path welle and the last in the
    marathon; a BLOCK here surfaces only as welle-7 own verdict,
    no downstream pre-conditional block (no downstream to block).
    """
    env = _build_envelope(aggregators, 7, _red_env_for_welle(7))
    assert env["verdict"] == "BLOCK"
    cprop = env.get("cross_welle_propagation", {}) or {}
    pcb = tuple(sorted(cprop.get("pre_conditional_blocked", [])))
    assert pcb == (), (
        f"A1-DL4 terminal-welle violation: welle-7 BLOCK propagates "
        f"to {pcb}, defence-layer-4 declares welle-7 terminal "
        f"(empty downstream)."
    )


# ===========================================================================
# A1-DL4-MARATHON-* — marathon-rollup contracts (4 tests).
# ===========================================================================


def test_a1_dl4_marathon_all_green_28_days_no_cascade_no_block(
    aggregators: Dict[int, Any],
) -> None:
    """28-day all-green marathon: no cascade events, no marathon BLOCK.

    Negative-control: Defence-Layer-4 must not fabricate cascades
    in the absence of any welle-BLOCK. The marathon-rollup is CLEAR.
    """
    start = date(2026, 6, 15)
    days = _marathon_dates(start, 28)
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for day in days:
        daily[day] = {
            w: _build_envelope(aggregators, w, _green_env_for_welle(w))
            for w in HOT_SPOT_WELLEN
        }
    rollup = _reference_dl4_rollup(daily)
    assert rollup["marathon_verdict"] == "CLEAR", (
        f"A1-DL4 false-positive: all-green marathon escalated to "
        f"{rollup['marathon_verdict']}."
    )
    assert rollup["cascade_events"] == [], (
        f"A1-DL4 false-positive: cascade events on all-green marathon: "
        f"{rollup['cascade_events']}."
    )
    assert all(v == "CLEAR" for v in rollup["per_welle_worst"].values())


def test_a1_dl4_marathon_single_welle_3_block_escalates_marathon(
    aggregators: Dict[int, Any],
) -> None:
    """Single Welle-3 BLOCK on one day escalates marathon-verdict to BLOCK
    and records cascade-events to {4, 5, 7} on that day.

    Positive-test: Defence-Layer-4 catches the A1 marathon-trace
    incarnation that Layer-1..3 cannot see (Layer-1..3 only check
    static contracts; this catches dynamic temporal coupling).
    """
    start = date(2026, 6, 15)
    days = _marathon_dates(start, 28)
    red_day = days[10]
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for day in days:
        envs: Dict[int, Dict[str, Any]] = {}
        for w in HOT_SPOT_WELLEN:
            env_input = _red_env_for_welle(3) if (day == red_day and w == 3) \
                else _green_env_for_welle(w)
            envs[w] = _build_envelope(aggregators, w, env_input)
        daily[day] = envs
    rollup = _reference_dl4_rollup(daily)
    assert rollup["marathon_verdict"] == "BLOCK", (
        f"A1-DL4 escalation failure: single welle-3 BLOCK left "
        f"marathon-verdict at {rollup['marathon_verdict']}."
    )
    cascade_downstreams = {
        (e["source_welle"], e["downstream_welle"])
        for e in rollup["cascade_events"]
        if e["day"] == red_day
    }
    assert cascade_downstreams == {(3, 4), (3, 5), (3, 7)}, (
        f"A1-DL4 cascade-recording incomplete: got {cascade_downstreams}, "
        f"expected (3,4), (3,5), (3,7)."
    )


def test_a1_dl4_marathon_multi_day_flap_each_block_recorded(
    aggregators: Dict[int, Any],
) -> None:
    """Flap pattern (red-green-red over three days) records two cascades.

    Multi-day-flap is the A1 incarnation that single-day cascade
    tests cannot see: an oscillating welle-4 integrity signal must
    surface each red-day's cascade independently. The marathon-
    rollup must record both, not deduplicate by source-welle.
    """
    start = date(2026, 6, 15)
    days = _marathon_dates(start, 5)
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    red_pattern = {days[1]: True, days[2]: False, days[3]: True}
    for day in days:
        envs: Dict[int, Dict[str, Any]] = {}
        for w in HOT_SPOT_WELLEN:
            if w == 4 and red_pattern.get(day, False):
                env_input = _red_env_for_welle(4)
            else:
                env_input = _green_env_for_welle(w)
            envs[w] = _build_envelope(aggregators, w, env_input)
        daily[day] = envs
    rollup = _reference_dl4_rollup(daily)
    red_days_in_events = sorted(
        {e["day"] for e in rollup["cascade_events"] if e["source_welle"] == 4}
    )
    assert red_days_in_events == [days[1], days[3]], (
        f"A1-DL4 flap-recording failure: got days {red_days_in_events}, "
        f"expected {[days[1], days[3]]}."
    )
    # Each red day must record both (4->5) and (4->7).
    for d in (days[1], days[3]):
        downstreams = {
            e["downstream_welle"]
            for e in rollup["cascade_events"]
            if e["day"] == d and e["source_welle"] == 4
        }
        assert downstreams == {5, 7}, (
            f"A1-DL4 flap-day {d} cascade incomplete: got {downstreams}."
        )


def test_a1_dl4_marathon_terminal_welle_7_red_no_cascade_records(
    aggregators: Dict[int, Any],
) -> None:
    """Welle-7 isolated BLOCK records zero cascade-events.

    Negative-test for the terminal welle: a Welle-7 recovery-path
    BLOCK is a marathon failure (marathon-verdict BLOCK) but
    Defence-Layer-4 must NOT fabricate downstream cascade events
    where no downstream exists. This is the terminal-welle
    invariant complementary to the test in A1-DL4-CASCADE.
    """
    start = date(2026, 6, 15)
    days = _marathon_dates(start, 28)
    red_day = days[20]
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for day in days:
        envs: Dict[int, Dict[str, Any]] = {}
        for w in HOT_SPOT_WELLEN:
            env_input = _red_env_for_welle(7) if (day == red_day and w == 7) \
                else _green_env_for_welle(w)
            envs[w] = _build_envelope(aggregators, w, env_input)
        daily[day] = envs
    rollup = _reference_dl4_rollup(daily)
    assert rollup["marathon_verdict"] == "BLOCK", (
        "A1-DL4 escalation failure: terminal-welle BLOCK did not "
        "escalate marathon-verdict."
    )
    assert rollup["cascade_events"] == [], (
        f"A1-DL4 false-cascade on terminal welle: "
        f"got {rollup['cascade_events']}."
    )
    assert rollup["per_welle_worst"][7] == "BLOCK"
    # Welle 3,4,5,6 stay CLEAR (no upstream cascaded into them).
    for w in (3, 4, 5, 6):
        assert rollup["per_welle_worst"][w] == "CLEAR", (
            f"A1-DL4 reverse-cascade leak: welle-{w} worst "
            f"{rollup['per_welle_worst'][w]}."
        )


# ===========================================================================
# A1-DL4-DOC-* — doc-anchor / coverage-classification (3 tests).
# ===========================================================================


def test_a1_dl4_doc_a1_section_lists_defence_layer_4() -> None:
    """The §2 A1 entry in the matrix doc names Defence-Layer-4.

    Tag-51 Mira-Auftrag explicitly required a coverage-matrix
    update. The §2 A1 ``Notes`` section must enumerate the four
    defence-layers, with Layer-4 framed as the marathon-rollup
    cascade-detection layer (Tag-49 PR #316 + PR #317 substrate,
    Tag-51 framing).
    """
    content = MATRIX_DOC.read_text(encoding="utf-8")
    # Locate A1 section header.
    a1_header = "#### A1 — Cross-Modul-Drift"
    assert a1_header in content, "A1 section header missing in matrix doc."
    idx = content.index(a1_header)
    next_header = content.find("#### A2", idx)
    assert next_header > idx, "A1 section has no closing boundary."
    a1_block = content[idx:next_header]
    # Layer-4 must be named, with substrate anchors referenced.
    assert "Defence-Layer-4" in a1_block or "Layer-4" in a1_block, (
        "A1 §2 entry does not enumerate Defence-Layer-4. "
        "Tag-51 doc-update incomplete."
    )
    # Substrate-PR-anchors must appear.
    assert "#316" in a1_block or "cross_welle_hot_spot_e2e" in a1_block, (
        "A1 §2 entry does not anchor PR #316 (E2E substrate)."
    )
    assert "#317" in a1_block or "cross_welle_hot_spot_aggregator" in a1_block, (
        "A1 §2 entry does not anchor PR #317 (aggregator substrate)."
    )


def test_a1_dl4_doc_tag_50_candidate_3_records_layer_4() -> None:
    """Tag-50 §7.3 Candidate 3 records the Defence-Layer-4 promotion.

    The Tag-50 consolidated coverage-sweep §7.3 Candidate 3
    surfaced the fourth A1 defence as the substantive promotion.
    Tag-51 inscribes it; this anchor pins that the §7.3 entry
    still exists with the marathon-rollup / cascade framing.
    """
    content = MATRIX_DOC.read_text(encoding="utf-8")
    anchor = "Candidate 3: A1 marathon-rollup defence-in-depth"
    assert anchor in content, (
        f"Tag-50 §7.3 Candidate 3 anchor missing: '{anchor}' not in "
        f"matrix doc. Tag-51 update must not delete Tag-50 inscription."
    )
    idx = content.index(anchor)
    # Block ends before next ### or ## header.
    end = content.find("\n### ", idx)
    if end < 0:
        end = content.find("\n## ", idx)
    candidate_block = content[idx:end] if end > idx else content[idx:]
    assert "marathon-rollup" in candidate_block, (
        "Tag-50 §7.3 Candidate 3 missing marathon-rollup keyword."
    )
    assert "cascade" in candidate_block.lower(), (
        "Tag-50 §7.3 Candidate 3 missing cascade keyword."
    )


def test_a1_dl4_doc_a1_stays_covered_no_state_transition() -> None:
    """A1 stays COVERED — Defence-Layer-4 is defence-in-depth, not promotion.

    Defence-Layer-4 is added as a *fourth* defence-in-depth layer
    on an already-COVERED failure-mode. There is no state
    transition (was COVERED, is COVERED). This anchor pins that
    the §2 A1 ``Coverage state.`` line still reads COVERED.
    """
    content = MATRIX_DOC.read_text(encoding="utf-8")
    a1_header = "#### A1 — Cross-Modul-Drift"
    idx = content.index(a1_header)
    next_header = content.find("#### A2", idx)
    a1_block = content[idx:next_header]
    # The first "Coverage state." line should be COVERED.
    cs_idx = a1_block.find("Coverage state.")
    assert cs_idx >= 0, "A1 §2 ``Coverage state.`` line missing."
    cs_line_end = a1_block.find("\n", cs_idx)
    cs_line = a1_block[cs_idx:cs_line_end]
    assert "COVERED" in cs_line, (
        f"A1 unexpected state transition: ``Coverage state.`` line "
        f"reads '{cs_line.strip()}' — Defence-Layer-4 must not flip "
        f"A1 off COVERED."
    )
