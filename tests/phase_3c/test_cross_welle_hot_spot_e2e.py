# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""E2E acceptance for the Tag-49 Cross-Welle Hot-Spot Aggregator.

Background
----------

Tag-45 (Tomas, PR #288) introduced the Welle-3 hot-spot aggregator;
Tag-48 (Tomas, PR #312) added the Welle-{4,5,6,7} symmetric variants
(``tooling/ci/welle_{3,4,5,6,7}_hot_spot_aggregator.py``). Each per-
welle aggregator emits a single-day verdict envelope of shape
``schema_version=1`` with ``verdict in {CLEAR, CAUTION, BLOCK}``,
``check_results`` (four tri-state inputs), and an optional
``cross_welle_propagation`` block listing ``pre_conditional_blocked``
downstream wellen.

The Tag-49 Cross-Welle-Hot-Spot Aggregator (Tomas, parallel spawn)
consumes the **set** of per-welle envelopes (one or more days per
welle) and produces a **marathon-rollup** envelope:

* Per-welle worst-case verdict over the trace window.
* Cross-welle cascade: when a welle is BLOCK on day D, every
  downstream welle on day D inherits ``pre_conditional_blocked`` from
  the per-welle propagation map (see ``EXPECTED_PROPAGATION``).
* Marathon-verdict: the worst per-welle verdict over the trace, taking
  cascade-induced blocks into account.
* Hot-spot-cascade-detection: lists every (source_welle, day,
  downstream_welle) triple where a cascade propagation fired.

This file is the **E2E acceptance gate** for the Tag-49 aggregator
substance. It validates the expected semantics by:

1. Loading the five per-welle aggregators (Tag-45+48 substance, on
   tree today) and exercising their envelope shape contract.
2. Defining a *reference rollup* (``reference_cross_welle_rollup``)
   in this test-file that captures the Tag-49 contract. The Tag-49
   ``tooling/ci/cross_welle_hot_spot_aggregator.py`` (Tomas, parallel
   spawn) must match this reference under the same inputs.
3. Simulating a 4-week marathon trace (KW-24..KW-27, 28 daily
   snapshots) with scenarios covering: all-green-marathon, single-
   welle-3-hot, welle-4-hot-with-cascade, multi-day-flap, terminal-
   welle-7-isolated, full-cascade-from-welle-3, late-onset-welle-5,
   cross-cascade-overlap.
4. Cascade-detection unit-cases per per-welle aggregator
   (cross-validating propagation maps against ``EXPECTED_PROPAGATION``).

Auftrag-Anker
-------------

* Tag-49 Amara Auftrag (2026-05-19): Cross-Welle Hot-Spot E2E Test
  Suite, 4-week marathon trace, hot-spot cascade detection, >=20
  tests, Continuous-Mode, AR-persistent.
* Henrik Tag-44 Pre-Mortem (`mira/inbox/2026-05-18-henrik-tag-44-
  pre-mortem-done.md`) Cross-Welle-Risiko-Matrix is the source of
  ``EXPECTED_PROPAGATION``.
* PR #288 (Welle-3, Tag-45), PR #312 (Welle-{4,5,6,7}, Tag-48) — the
  five per-welle aggregators consumed here.
* Tomas Tag-49 cross-welle-hot-spot-aggregator spawn (parallel; the
  reference-impl below is the contract Tomas's substance must match).

Sandbox posture
---------------

Strict hermetic: stdlib + pytest only. No subprocess, no network,
no podman, no live-VM. The five per-welle aggregators are loaded
via importlib from in-repo paths and exercised purely on env-var
dicts; no on-disk state outside ``tmp_path``.

Test taxonomy (HSCWE-* IDs, 22 tests total, Auftrag minimum 20)
---------------------------------------------------------------

HSCWE-PROP-* — propagation-map cross-validation (5 tests)
  1. test_hscwe_prop_welle_3_map_matches_expected
  2. test_hscwe_prop_welle_4_map_matches_expected
  3. test_hscwe_prop_welle_5_map_matches_expected
  4. test_hscwe_prop_welle_6_map_matches_expected
  5. test_hscwe_prop_welle_7_terminal_no_downstream

HSCWE-ENV-* — single-day envelope shape (3 tests)
  6. test_hscwe_env_all_five_aggregators_emit_identical_schema
  7. test_hscwe_env_cross_welle_propagation_block_fires_on_red
  8. test_hscwe_env_cross_welle_propagation_block_absent_on_green

HSCWE-CASCADE-* — single-day cascade detection (4 tests)
  9. test_hscwe_cascade_welle_3_block_propagates_to_4_5_7
  10. test_hscwe_cascade_welle_4_block_propagates_to_5_7
  11. test_hscwe_cascade_double_source_overlap_union_taken
  12. test_hscwe_cascade_terminal_welle_7_block_does_not_cascade

HSCWE-MARATHON-* — 4-week trace scenarios (8 tests)
  13. test_hscwe_marathon_all_green_28_days_clear_verdict
  14. test_hscwe_marathon_single_red_day_welle_3_marathon_blocks
  15. test_hscwe_marathon_late_onset_welle_5_flag_after_day_14
  16. test_hscwe_marathon_welle_3_red_cascades_into_4_5_7_per_day
  17. test_hscwe_marathon_flap_caution_then_clear_then_caution_recorded
  18. test_hscwe_marathon_terminal_welle_7_isolated_red_no_cascade
  19. test_hscwe_marathon_overlapping_cascade_union_no_double_count
  20. test_hscwe_marathon_per_welle_worst_verdict_taken_over_window

HSCWE-CONTRACT-* — reference-rollup contract surface (2 tests)
  21. test_hscwe_contract_reference_rollup_schema_keys_stable
  22. test_hscwe_contract_reference_rollup_deterministic_on_replay
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import pytest


# ---------------------------------------------------------------------------
# Repo paths and aggregator loader
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HOT_SPOT_WELLEN: Tuple[int, ...] = (3, 4, 5, 6, 7)

# Expected cross-welle propagation map from Henrik Tag-44 Pre-Mortem
# Cross-Welle-Risiko-Matrix, also encoded in the per-welle
# DOWNSTREAM_PROPAGATION_WELLEN constants in the aggregators.
EXPECTED_PROPAGATION: Dict[int, Tuple[int, ...]] = {
    3: (4, 5, 7),
    4: (5, 7),
    5: (7,),
    6: (7,),
    7: (),
}


def _load_aggregator(welle: int):
    path = REPO_ROOT / "tooling" / "ci" / f"welle_{welle}_hot_spot_aggregator.py"
    if not path.is_file():
        pytest.fail(f"per-welle aggregator missing on tree: {path}")
    mod_name = f"_e2e_load_welle_{welle}_hot_spot_aggregator"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build importlib spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aggregators() -> Dict[int, Any]:
    return {w: _load_aggregator(w) for w in HOT_SPOT_WELLEN}


# ---------------------------------------------------------------------------
# Helpers: build per-welle single-day envelope, marathon trace, rollup.
# ---------------------------------------------------------------------------


def _green_env_for_welle(welle: int) -> Dict[str, str]:
    """Build an env-var dict that yields a CLEAR verdict for welle.

    The welle-3 aggregator additionally consumes
    ``WELLE_3_AUDIT_TRAIL_INTEGRITY`` to decide propagation; the
    welle-4/5/6 aggregators each have their own welle-specific
    integrity-input. We provide the green-state name for each.
    """
    base = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "PRE_AUDITOR_STATE": "present",
    }
    integrity_env = {
        3: ("WELLE_3_AUDIT_TRAIL_INTEGRITY", "green"),
        4: ("WELLE_4_PERSISTENCE_DRIFT", "green"),
        5: ("WELLE_5_LIFECYCLE_FSM_INTEGRITY", "green"),
        6: ("WELLE_6_SUBSCRIBE_LOOP_INTEGRITY", "green"),
        7: ("WELLE_7_RECOVERY_INTEGRITY", "green"),
    }
    key, val = integrity_env[welle]
    base[key] = val
    return base


def _red_env_for_welle(welle: int) -> Dict[str, str]:
    env = _green_env_for_welle(welle)
    env["CHECK2_STATUS"] = "red"
    integrity_env = {
        3: "WELLE_3_AUDIT_TRAIL_INTEGRITY",
        4: "WELLE_4_PERSISTENCE_DRIFT",
        5: "WELLE_5_LIFECYCLE_FSM_INTEGRITY",
        6: "WELLE_6_SUBSCRIBE_LOOP_INTEGRITY",
        7: "WELLE_7_RECOVERY_INTEGRITY",
    }
    env[integrity_env[welle]] = "red"
    return env


def _caution_env_for_welle(welle: int) -> Dict[str, str]:
    env = _green_env_for_welle(welle)
    env["CHECK4_STATUS"] = "yellow"
    return env


def _build_envelope(aggregators: Mapping[int, Any], welle: int,
                    env: Mapping[str, str]) -> Dict[str, Any]:
    return aggregators[welle].build_envelope(dict(env))


def _marathon_window_dates(start: date, days: int) -> List[str]:
    """Return ISO-date strings for ``days`` consecutive days
    beginning at ``start`` (inclusive). 4-week marathon = 28 days."""
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


# ---------------------------------------------------------------------------
# Reference cross-welle rollup -- the contract Tomas Tag-49 must match.
# ---------------------------------------------------------------------------


def reference_cross_welle_rollup(
    daily_envelopes: Mapping[str, Mapping[int, Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Reference implementation of the Tag-49 cross-welle rollup.

    Input: ``daily_envelopes[day_iso][welle] -> per-welle envelope``.
    Days are arbitrary ISO-date strings; the rollup is order-stable
    by sorted day-key.

    Semantics
    ---------

    * ``per_welle_worst`` -- worst verdict per welle over the trace
      window. Order: CLEAR < CAUTION < BLOCK.
    * ``cascade_events`` -- list of dicts {day, source_welle,
      downstream_welle} for every day where a source-welle was BLOCK
      AND its per-welle propagation map fires. Sorted by (day,
      source, downstream).
    * ``cascade_blocked_per_day`` -- mapping day -> sorted union of
      downstream wellen pre-conditionally blocked on that day.
    * ``marathon_verdict`` -- worst of any per-welle verdict over the
      window, escalated to BLOCK if any cascade-event fired (cascade
      means *downstream* readiness is forfeit even if downstream
      itself was green).
    * ``hot_spot_summary`` -- per-source-welle count of cascade-days.

    Determinism: sorting is total over (day_iso, welle_int) and the
    output JSON is sort-key-stable.
    """
    rank = {"CLEAR": 0, "CAUTION": 1, "BLOCK": 2}
    inv_rank = {v: k for k, v in rank.items()}

    per_welle_worst: Dict[int, str] = {w: "CLEAR" for w in HOT_SPOT_WELLEN}
    cascade_events: List[Dict[str, Any]] = []
    cascade_blocked_per_day: Dict[str, List[int]] = {}
    hot_spot_summary: Dict[int, int] = {w: 0 for w in HOT_SPOT_WELLEN}

    for day in sorted(daily_envelopes.keys()):
        day_envs = daily_envelopes[day]
        day_cascade_targets: set[int] = set()
        for welle in HOT_SPOT_WELLEN:
            env = day_envs.get(welle)
            if env is None:
                # Missing day-welle envelope is a loud-failure red.
                v = "BLOCK"
            else:
                v = env.get("verdict", "BLOCK")
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
                    day_cascade_targets.add(downstream)
                    hot_spot_summary[welle] += 1
        if day_cascade_targets:
            cascade_blocked_per_day[day] = sorted(day_cascade_targets)

    cascade_events.sort(
        key=lambda e: (e["day"], e["source_welle"], e["downstream_welle"])
    )

    worst_per_welle_rank = max(rank[v] for v in per_welle_worst.values())
    if cascade_events:
        marathon_rank = max(worst_per_welle_rank, rank["BLOCK"])
    else:
        marathon_rank = worst_per_welle_rank
    marathon_verdict = inv_rank[marathon_rank]

    return {
        "schema_version": 1,
        "workflow": "phase-3c-cross-welle-hot-spot-aggregator",
        "trace_days": sorted(daily_envelopes.keys()),
        "trace_day_count": len(daily_envelopes),
        "per_welle_worst": {str(w): v for w, v in sorted(per_welle_worst.items())},
        "marathon_verdict": marathon_verdict,
        "cascade_events": cascade_events,
        "cascade_blocked_per_day": {
            d: cascade_blocked_per_day[d] for d in sorted(cascade_blocked_per_day)
        },
        "hot_spot_summary": {
            str(w): hot_spot_summary[w] for w in HOT_SPOT_WELLEN
        },
    }


# ---------------------------------------------------------------------------
# HSCWE-PROP-* : propagation-map cross-validation (5 tests)
# ---------------------------------------------------------------------------


def test_hscwe_prop_welle_3_map_matches_expected(aggregators) -> None:
    """Welle-3 aggregator DOWNSTREAM_PROPAGATION_WELLEN must equal
    (4, 5, 7) per Henrik Tag-44 Cross-Welle-Risiko-Matrix."""
    actual = tuple(aggregators[3].DOWNSTREAM_PROPAGATION_WELLEN)
    assert actual == EXPECTED_PROPAGATION[3], (
        f"Welle-3 propagation map drift: aggregator={actual}, "
        f"expected={EXPECTED_PROPAGATION[3]}"
    )


def test_hscwe_prop_welle_4_map_matches_expected(aggregators) -> None:
    """Welle-4 persistence-drift cascades into Welle-{5,7}."""
    actual = tuple(aggregators[4].DOWNSTREAM_PROPAGATION_WELLEN)
    assert actual == EXPECTED_PROPAGATION[4]


def test_hscwe_prop_welle_5_map_matches_expected(aggregators) -> None:
    """Welle-5 FSM-integrity cascades only into Welle-7
    (recovery_workflow replays FSM transitions)."""
    actual = tuple(aggregators[5].DOWNSTREAM_PROPAGATION_WELLEN)
    assert actual == EXPECTED_PROPAGATION[5]


def test_hscwe_prop_welle_6_map_matches_expected(aggregators) -> None:
    """Welle-6 subscribe-loop integrity cascades into Welle-7
    (recovery replays NATS deliveries)."""
    actual = tuple(aggregators[6].DOWNSTREAM_PROPAGATION_WELLEN)
    assert actual == EXPECTED_PROPAGATION[6]


def test_hscwe_prop_welle_7_terminal_no_downstream(aggregators) -> None:
    """Welle-7 (recovery_workflow) is the **terminal** welle: its
    cutover is the marathon finale; nothing depends on it
    downstream within the seven-welle marathon."""
    actual = tuple(aggregators[7].DOWNSTREAM_PROPAGATION_WELLEN)
    assert actual == ()
    assert actual == EXPECTED_PROPAGATION[7]


# ---------------------------------------------------------------------------
# HSCWE-ENV-* : single-day envelope shape (3 tests)
# ---------------------------------------------------------------------------


REQUIRED_ENVELOPE_KEYS = {
    "schema_version",
    "workflow",
    "welle",
    "verdict",
    "check_results",
    "failed_checks",
    "counts",
    "cross_welle_propagation",
}


def test_hscwe_env_all_five_aggregators_emit_identical_schema(
    aggregators,
) -> None:
    """The five per-welle aggregators must emit envelopes with the
    same required-keys, same schema_version, and the welle field
    must equal the source welle. Interchangeability is a hard
    contract for the Tag-49 rollup consumer."""
    seen_keys: List[frozenset] = []
    for w in HOT_SPOT_WELLEN:
        env = _build_envelope(aggregators, w, _green_env_for_welle(w))
        assert env["schema_version"] == 1, f"welle {w} schema drift"
        assert env["welle"] == w, f"welle {w} self-id wrong: {env['welle']}"
        assert REQUIRED_ENVELOPE_KEYS.issubset(env.keys()), (
            f"welle {w} missing keys: "
            f"{REQUIRED_ENVELOPE_KEYS - set(env.keys())}"
        )
        seen_keys.append(frozenset(REQUIRED_ENVELOPE_KEYS & env.keys()))
    # All five aggregators agree on the required-key surface.
    assert len(set(seen_keys)) == 1, (
        "per-welle aggregators disagree on the required-key surface: "
        f"{seen_keys}"
    )


def test_hscwe_env_cross_welle_propagation_block_fires_on_red(
    aggregators,
) -> None:
    """On a red welle-3 env, the cross_welle_propagation block must
    fire and list (4, 5, 7) as pre_conditional_blocked."""
    env = _build_envelope(aggregators, 3, _red_env_for_welle(3))
    assert env["verdict"] == "BLOCK"
    prop = env["cross_welle_propagation"]
    assert prop is not None, "propagation block missing on red welle-3"
    assert prop["pre_conditional_blocked"] == [4, 5, 7]


def test_hscwe_env_cross_welle_propagation_block_absent_on_green(
    aggregators,
) -> None:
    """On all-green inputs, the cross_welle_propagation block is None
    for every welle (no cascade fires)."""
    for w in HOT_SPOT_WELLEN:
        env = _build_envelope(aggregators, w, _green_env_for_welle(w))
        assert env["verdict"] == "CLEAR", f"welle {w} not clear on green"
        assert env["cross_welle_propagation"] is None, (
            f"welle {w} fires propagation on green inputs (regression)"
        )


# ---------------------------------------------------------------------------
# HSCWE-CASCADE-* : single-day cascade detection (4 tests)
# ---------------------------------------------------------------------------


def _single_day_trace(
    aggregators: Mapping[int, Any],
    day: str,
    welle_states: Mapping[int, str],
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Build a one-day trace where each welle has the given state
    (``green`` / ``red`` / ``caution``)."""
    state_to_env = {
        "green": _green_env_for_welle,
        "red": _red_env_for_welle,
        "caution": _caution_env_for_welle,
    }
    day_envs: Dict[int, Dict[str, Any]] = {}
    for w in HOT_SPOT_WELLEN:
        st = welle_states.get(w, "green")
        env_in = state_to_env[st](w)
        day_envs[w] = _build_envelope(aggregators, w, env_in)
    return {day: day_envs}


def test_hscwe_cascade_welle_3_block_propagates_to_4_5_7(
    aggregators,
) -> None:
    """Welle-3 BLOCK on day D yields cascade events for downstream
    Welle-{4, 5, 7} on the same day."""
    trace = _single_day_trace(aggregators, "2026-06-08", {3: "red"})
    roll = reference_cross_welle_rollup(trace)
    sources = sorted(
        {(e["source_welle"], e["downstream_welle"]) for e in roll["cascade_events"]}
    )
    assert sources == [(3, 4), (3, 5), (3, 7)]
    assert roll["cascade_blocked_per_day"]["2026-06-08"] == [4, 5, 7]
    assert roll["marathon_verdict"] == "BLOCK"


def test_hscwe_cascade_welle_4_block_propagates_to_5_7(
    aggregators,
) -> None:
    """Welle-4 BLOCK on day D yields cascade events into Welle-{5, 7}
    only (Welle-3 is upstream, Welle-6 is on a parallel substrate)."""
    trace = _single_day_trace(aggregators, "2026-06-15", {4: "red"})
    roll = reference_cross_welle_rollup(trace)
    sources = sorted(
        {(e["source_welle"], e["downstream_welle"]) for e in roll["cascade_events"]}
    )
    assert sources == [(4, 5), (4, 7)]
    assert 3 not in roll["cascade_blocked_per_day"]["2026-06-15"]
    assert 6 not in roll["cascade_blocked_per_day"]["2026-06-15"]


def test_hscwe_cascade_double_source_overlap_union_taken(
    aggregators,
) -> None:
    """On a day where Welle-3 AND Welle-5 both BLOCK, the per-day
    cascade-blocked set is the UNION ({4, 5, 7}) -- not the
    multiset. Welle-5 cascade also includes 7 (already in W3-set);
    no double-count."""
    trace = _single_day_trace(
        aggregators, "2026-06-20", {3: "red", 5: "red"}
    )
    roll = reference_cross_welle_rollup(trace)
    assert roll["cascade_blocked_per_day"]["2026-06-20"] == [4, 5, 7]
    # cascade_events is a list (multiset of edges), so welle-7 appears
    # twice (once as 3->7, once as 5->7). The union-flattened
    # cascade_blocked_per_day suppresses the multiplicity.
    targets = [e["downstream_welle"] for e in roll["cascade_events"]]
    assert targets.count(7) == 2  # one from welle-3, one from welle-5


def test_hscwe_cascade_terminal_welle_7_block_does_not_cascade(
    aggregators,
) -> None:
    """Welle-7 BLOCK on day D does NOT produce any cascade event
    (terminal welle). Marathon-verdict is BLOCK from per-welle worst,
    not from cascade."""
    trace = _single_day_trace(aggregators, "2026-06-22", {7: "red"})
    roll = reference_cross_welle_rollup(trace)
    assert roll["cascade_events"] == []
    assert "2026-06-22" not in roll["cascade_blocked_per_day"]
    assert roll["marathon_verdict"] == "BLOCK"
    assert roll["per_welle_worst"]["7"] == "BLOCK"


# ---------------------------------------------------------------------------
# HSCWE-MARATHON-* : 4-week trace scenarios (8 tests)
# ---------------------------------------------------------------------------


MARATHON_START = date(2026, 5, 19)  # KW-21 -- 4 weeks pre-cutover.
MARATHON_DAYS = 28


def _all_green_trace(
    aggregators: Mapping[int, Any],
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    trace: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for d in days:
        trace[d] = {}
        for w in HOT_SPOT_WELLEN:
            trace[d][w] = _build_envelope(
                aggregators, w, _green_env_for_welle(w)
            )
    return trace


def test_hscwe_marathon_all_green_28_days_clear_verdict(
    aggregators,
) -> None:
    """4-week all-green marathon: marathon_verdict CLEAR, no
    cascade events, per_welle_worst all CLEAR."""
    trace = _all_green_trace(aggregators)
    roll = reference_cross_welle_rollup(trace)
    assert roll["trace_day_count"] == MARATHON_DAYS
    assert roll["marathon_verdict"] == "CLEAR"
    assert roll["cascade_events"] == []
    assert roll["cascade_blocked_per_day"] == {}
    assert all(v == "CLEAR" for v in roll["per_welle_worst"].values())
    assert all(c == 0 for c in roll["hot_spot_summary"].values())


def test_hscwe_marathon_single_red_day_welle_3_marathon_blocks(
    aggregators,
) -> None:
    """A single red welle-3 day in an otherwise-green marathon trace
    yields marathon_verdict=BLOCK and one day in cascade_blocked."""
    trace = _all_green_trace(aggregators)
    red_day = (MARATHON_START + timedelta(days=10)).isoformat()
    trace[red_day][3] = _build_envelope(
        aggregators, 3, _red_env_for_welle(3)
    )
    roll = reference_cross_welle_rollup(trace)
    assert roll["marathon_verdict"] == "BLOCK"
    assert roll["per_welle_worst"]["3"] == "BLOCK"
    # The other four wellen remain CLEAR on their own (cascade is
    # recorded separately).
    for w in (4, 5, 6, 7):
        assert roll["per_welle_worst"][str(w)] == "CLEAR"
    assert list(roll["cascade_blocked_per_day"].keys()) == [red_day]
    assert roll["cascade_blocked_per_day"][red_day] == [4, 5, 7]


def test_hscwe_marathon_late_onset_welle_5_flag_after_day_14(
    aggregators,
) -> None:
    """A welle-5 BLOCK starting at day 15 (mid-marathon) is detected
    on every subsequent day; cascade fires into welle-7 only."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    onset_days = days[14:]  # day 15..28
    for d in onset_days:
        trace[d][5] = _build_envelope(
            aggregators, 5, _red_env_for_welle(5)
        )
    roll = reference_cross_welle_rollup(trace)
    assert roll["marathon_verdict"] == "BLOCK"
    assert roll["per_welle_worst"]["5"] == "BLOCK"
    # Cascade from welle-5 fires on every onset day, downstream = 7.
    assert len(roll["cascade_events"]) == len(onset_days)
    assert all(
        e["source_welle"] == 5 and e["downstream_welle"] == 7
        for e in roll["cascade_events"]
    )
    assert roll["hot_spot_summary"]["5"] == len(onset_days)


def test_hscwe_marathon_welle_3_red_cascades_into_4_5_7_per_day(
    aggregators,
) -> None:
    """A 5-day welle-3 outage in the marathon: cascade events fire on
    each day for downstream Welle-{4, 5, 7}. Total = 5*3 = 15
    cascade-events."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    outage_days = days[7:12]  # 5-day welle-3 outage
    for d in outage_days:
        trace[d][3] = _build_envelope(
            aggregators, 3, _red_env_for_welle(3)
        )
    roll = reference_cross_welle_rollup(trace)
    assert len(roll["cascade_events"]) == 15
    assert roll["hot_spot_summary"]["3"] == 15
    assert sorted(roll["cascade_blocked_per_day"].keys()) == outage_days
    for d in outage_days:
        assert roll["cascade_blocked_per_day"][d] == [4, 5, 7]


def test_hscwe_marathon_flap_caution_then_clear_then_caution_recorded(
    aggregators,
) -> None:
    """A welle-6 flap (CAUTION on day 5, CLEAR day 6, CAUTION day 7):
    per_welle_worst[6] = CAUTION, no cascade events (CAUTION does
    not cascade -- only BLOCK does)."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    trace[days[4]][6] = _build_envelope(
        aggregators, 6, _caution_env_for_welle(6)
    )
    trace[days[6]][6] = _build_envelope(
        aggregators, 6, _caution_env_for_welle(6)
    )
    roll = reference_cross_welle_rollup(trace)
    assert roll["per_welle_worst"]["6"] == "CAUTION"
    # No BLOCK anywhere -> marathon_verdict = CAUTION.
    assert roll["marathon_verdict"] == "CAUTION"
    assert roll["cascade_events"] == []
    assert roll["hot_spot_summary"]["6"] == 0


def test_hscwe_marathon_terminal_welle_7_isolated_red_no_cascade(
    aggregators,
) -> None:
    """A welle-7 outage in the marathon: per_welle_worst[7] = BLOCK,
    marathon_verdict = BLOCK, but no cascade events (terminal)."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    for d in days[20:23]:
        trace[d][7] = _build_envelope(
            aggregators, 7, _red_env_for_welle(7)
        )
    roll = reference_cross_welle_rollup(trace)
    assert roll["per_welle_worst"]["7"] == "BLOCK"
    assert roll["marathon_verdict"] == "BLOCK"
    assert roll["cascade_events"] == []
    assert roll["cascade_blocked_per_day"] == {}


def test_hscwe_marathon_overlapping_cascade_union_no_double_count(
    aggregators,
) -> None:
    """Welle-3 AND Welle-4 simultaneously BLOCK on day D: cascade-
    blocked union is {4, 5, 7} (note: welle-3 cascade includes 4;
    welle-4 cascade includes 5,7 -- union no double-count in the
    per-day flattened set)."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    overlap_day = days[18]
    trace[overlap_day][3] = _build_envelope(
        aggregators, 3, _red_env_for_welle(3)
    )
    trace[overlap_day][4] = _build_envelope(
        aggregators, 4, _red_env_for_welle(4)
    )
    roll = reference_cross_welle_rollup(trace)
    assert roll["cascade_blocked_per_day"][overlap_day] == [4, 5, 7]
    # Cascade-events on overlap_day: W3->{4,5,7}, W4->{5,7} = 5 events.
    overlap_events = [
        e for e in roll["cascade_events"] if e["day"] == overlap_day
    ]
    assert len(overlap_events) == 5
    sources = sorted(
        {(e["source_welle"], e["downstream_welle"]) for e in overlap_events}
    )
    assert sources == [(3, 4), (3, 5), (3, 7), (4, 5), (4, 7)]


def test_hscwe_marathon_per_welle_worst_verdict_taken_over_window(
    aggregators,
) -> None:
    """Per-welle worst-verdict semantics: a welle that is CLEAR on
    27 days and BLOCK on 1 day has worst=BLOCK over the trace
    window. Worst-of-window dominates."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    trace[days[3]][6] = _build_envelope(
        aggregators, 6, _caution_env_for_welle(6)
    )
    trace[days[15]][6] = _build_envelope(
        aggregators, 6, _red_env_for_welle(6)
    )
    trace[days[20]][6] = _build_envelope(
        aggregators, 6, _caution_env_for_welle(6)
    )
    roll = reference_cross_welle_rollup(trace)
    assert roll["per_welle_worst"]["6"] == "BLOCK"
    assert roll["marathon_verdict"] == "BLOCK"
    # Welle-6 cascade fires only on the BLOCK day, downstream = 7.
    assert roll["hot_spot_summary"]["6"] == 1


# ---------------------------------------------------------------------------
# HSCWE-CONTRACT-* : reference-rollup contract surface (2 tests)
# ---------------------------------------------------------------------------


REQUIRED_ROLLUP_KEYS = {
    "schema_version",
    "workflow",
    "trace_days",
    "trace_day_count",
    "per_welle_worst",
    "marathon_verdict",
    "cascade_events",
    "cascade_blocked_per_day",
    "hot_spot_summary",
}


def test_hscwe_contract_reference_rollup_schema_keys_stable(
    aggregators,
) -> None:
    """The reference rollup has the documented required-keys for the
    Tag-49 marathon-rollup envelope contract; schema_version=1."""
    trace = _all_green_trace(aggregators)
    roll = reference_cross_welle_rollup(trace)
    assert set(roll.keys()) >= REQUIRED_ROLLUP_KEYS
    assert roll["schema_version"] == 1
    assert roll["workflow"] == "phase-3c-cross-welle-hot-spot-aggregator"
    # per_welle_worst keys are string-form of HOT_SPOT_WELLEN for
    # JSON-portability (the Tag-49 aggregator output is consumed by
    # a Grafana dashboard).
    assert set(roll["per_welle_worst"].keys()) == {
        str(w) for w in HOT_SPOT_WELLEN
    }


def test_hscwe_contract_reference_rollup_deterministic_on_replay(
    aggregators,
) -> None:
    """Replaying the same trace yields a byte-identical JSON
    serialisation -- deterministic, sort-key-stable output."""
    trace = _all_green_trace(aggregators)
    days = _marathon_window_dates(MARATHON_START, MARATHON_DAYS)
    trace[days[10]][3] = _build_envelope(
        aggregators, 3, _red_env_for_welle(3)
    )
    trace[days[15]][5] = _build_envelope(
        aggregators, 5, _red_env_for_welle(5)
    )
    roll_a = reference_cross_welle_rollup(trace)
    roll_b = reference_cross_welle_rollup(trace)
    a = json.dumps(roll_a, indent=2, sort_keys=True)
    b = json.dumps(roll_b, indent=2, sort_keys=True)
    assert a == b, "reference rollup is non-deterministic"
    # cascade_events list is sorted by (day, source_welle,
    # downstream_welle) -- the canonical replay order.
    events = roll_a["cascade_events"]
    sorted_events = sorted(
        events,
        key=lambda e: (e["day"], e["source_welle"], e["downstream_welle"]),
    )
    assert events == sorted_events
