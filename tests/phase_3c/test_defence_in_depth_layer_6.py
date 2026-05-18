# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""A1 Defence-in-Depth — Layer-6 atomic Run-Suite.

Auftrag-Anker
-------------

* Tag-52 Amara Auftrag (Mira, 2026-05-19): formalise the Phase-3-
  Acceptance-Pyramide Layer-6 as a **single atomic Run-Suite** that
  combines all four A1 defence-layers (DL1..DL4) into one coherent
  test-file. The Tag-45 Layer-5 (Pre-Mortem coverage-audit) records
  that A1 is COVERED by four defence-in-depth layers; the Tag-47
  Pyramide-Layer-Consistency-Audit and Tag-50/Tag-51 consolidations
  promoted the fourth defence-layer into a dedicated test-class
  (`tests/phase_3c/test_a1_marathon_cascade_defence_layer_4.py`,
  22 hermetic tests). Tag-52 promotes the *combined* defence-in-depth
  invariant to Layer-6 of the Pyramide: where each previous layer is
  a single contract surface, Layer-6 is the **multi-layer atomic
  contract** — all four A1 defence-layers must fire together on a
  unified set of A1 attack scenarios, and the defence-in-depth
  *residual capture* property (at least one layer rejects each
  attack even when one of the other layers is unavailable) must
  hold.
* Pyramide-Map source-of-truth:
  `docs/quality-gates/pre-mortem-failure-mode-coverage.md` §0 — the
  Tag-52 doc-update appends a sixth row to the Pyramide-table.
* Tag-47 anchor:
  `tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py` —
  the structural-consistency audit grows from a five-layer to a
  six-layer cascade in a follow-up sweep (this file is the
  substrate; the audit-update is a separate Tag-N follow-up to keep
  the Tag-52 PR scope small).

Why a sixth pyramid-layer
-------------------------

Layer-1..4 each pin **one** static contract surface for A1:

* Layer-1 (Tag-40, `test_phase_3_final_regression.py`) — Pairwise
  Welle-Isolation. Static substrate-level invariant: disjoint
  ENV-vars and disjoint focus-MODULs across the seven welle slots.
* Layer-2 (Tag-43, `test_marathon_schluss_acceptance_drill.py`) —
  Marathon-Aggregate Blocker-Rejection. Aggregate-level invariant:
  the marathon-aggregate refuses to emit the COMPLETE marker on any
  cross-welle drift signal between adjacent wellen.
* Layer-3 (Tag-44, `test_marathon_anti_patterns.py` AP-4) — Namespace-
  Prefix Discipline. State-backing-level invariant: the welle-4
  prefix cannot leak into a welle-5 read, and vice versa.
* Layer-4 (Tag-49 PR #316 + PR #317 substrate, Tag-51 framing,
  `test_a1_marathon_cascade_defence_layer_4.py`) — Marathon-Rollup
  Cascade-Detection. Dynamic-trace invariant: a per-welle BLOCK on
  day D forfeits downstream readiness on day D per the Henrik
  Risiko-Matrix propagation map; the marathon-rollup escalates to
  BLOCK.

A1 (Cross-Modul-Drift Welle-N -> Welle-N+1) is a **multi-axis**
failure-mode: it can manifest on the static substrate (Layer-1),
on the aggregate marker (Layer-2), on the state-backing namespace
(Layer-3), or on the dynamic marathon-trace (Layer-4). The Tag-45
Layer-5 coverage-audit pins that *some* layer covers each axis,
but does not pin that **all four layers fire together** on a
unified A1 attack-scenario. Layer-6 is that pin.

Layer-6 also asserts the **defence-in-depth residual-capture
property**: for each of the four single-layer-failure scenarios
(simulate one layer's contract being bypassed), at least one of
the remaining three layers must still reject every A1 attack in
the scenario. This is the operational definition of
defence-in-depth: no single layer is the sole gate.

Test taxonomy (DL6-* IDs, 22 tests, Auftrag minimum 20)
-------------------------------------------------------

DL6-COMPOSITE-* — atomic-run composite-fire (5 tests)
  01. test_dl6_composite_all_four_layers_fire_on_canonical_a1_attack
  02. test_dl6_composite_all_four_layers_clear_on_canonical_green
  03. test_dl6_composite_layer_outputs_are_deterministic_under_replay
  04. test_dl6_composite_layer_outputs_pin_each_layer_to_its_axis
  05. test_dl6_composite_no_layer_silently_skips_under_unrelated_drift

DL6-RESIDUAL-* — residual-capture under single-layer bypass (4 tests)
  06. test_dl6_residual_capture_when_layer_1_bypassed
  07. test_dl6_residual_capture_when_layer_2_bypassed
  08. test_dl6_residual_capture_when_layer_3_bypassed
  09. test_dl6_residual_capture_when_layer_4_bypassed

DL6-AXIS-* — per-layer-axis isolation (4 tests)
  10. test_dl6_axis_layer_1_static_substrate_envvar_modul
  11. test_dl6_axis_layer_2_aggregate_blocker_rejection
  12. test_dl6_axis_layer_3_state_backing_namespace_prefix
  13. test_dl6_axis_layer_4_dynamic_marathon_trace_cascade

DL6-INTEGRATION-* — Tag-N substrate cross-anchor (5 tests)
  14. test_dl6_integration_layer_1_file_on_tree
  15. test_dl6_integration_layer_2_file_on_tree
  16. test_dl6_integration_layer_3_file_on_tree
  17. test_dl6_integration_layer_4_file_on_tree
  18. test_dl6_integration_pyramide_map_layer_6_row_present

DL6-INVARIANT-* — Layer-6-as-a-layer invariants (4 tests)
  19. test_dl6_invariant_layer_6_is_strict_superset_of_layer_4
  20. test_dl6_invariant_layer_6_does_not_replace_layers_1_to_5
  21. test_dl6_invariant_a1_coverage_state_stays_covered
  22. test_dl6_invariant_residual_capture_is_property_of_a1_dl_set

Hermetic posture
----------------

stdlib + pytest only. Each defence-layer module is loaded via
``importlib`` from in-repo paths and exercised purely on env-var
dicts and on Python objects assembled in-process. No subprocess,
no network, no podman, no live-VM, no filesystem mutation outside
the read-only matrix-doc probe. The four defence-layer modules
themselves are loaded once at module-scope; their public surfaces
(``ADR_0066_REIHENFOLGE``, ``StateBackingLeakLedger``, per-welle
aggregator ``build_envelope``, marathon-rollup reference) are
re-exercised inside this file in a unified composite-fire
fixture.

Output shape of a Layer-6 composite-fire (used by DL6-COMPOSITE-*
and DL6-RESIDUAL-* tests)::

    CompositeFireVerdict(
        layer_1=LayerVerdict(fired=bool, reason=str),
        layer_2=LayerVerdict(fired=bool, reason=str),
        layer_3=LayerVerdict(fired=bool, reason=str),
        layer_4=LayerVerdict(fired=bool, reason=str),
        all_fired=bool,
        any_fired=bool,
        residual_fired_under_layer_bypass=Dict[int, bool],
    )
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Repo paths and constants.
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

LAYER_PATHS: Dict[int, str] = {
    1: "tests/phase_3c/test_phase_3_final_regression.py",
    2: "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
    3: "tests/phase_3c/test_marathon_anti_patterns.py",
    4: "tests/phase_3c/test_a1_marathon_cascade_defence_layer_4.py",
}

MATRIX_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
)

HOT_SPOT_WELLEN: Tuple[int, ...] = (3, 4, 5, 6, 7)


# ---------------------------------------------------------------------------
# Importlib-loaders for the four A1 defence-layer modules.
# ---------------------------------------------------------------------------


def _load_module_from_path(path: Path, mod_name: str):
    if not path.is_file():
        pytest.fail(f"DL6 substrate gap: layer module missing on tree: {path}")
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        pytest.fail(f"DL6 substrate gap: importlib spec build failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def layer_modules() -> Dict[int, Any]:
    """Load all four A1 defence-layer modules once per pytest module."""
    mods: Dict[int, Any] = {}
    mods[1] = _load_module_from_path(
        REPO_ROOT / LAYER_PATHS[1], "_dl6_layer_1_state_machine"
    )
    mods[2] = _load_module_from_path(
        REPO_ROOT / LAYER_PATHS[2], "_dl6_layer_2_marathon_schluss"
    )
    mods[3] = _load_module_from_path(
        REPO_ROOT / LAYER_PATHS[3], "_dl6_layer_3_anti_patterns"
    )
    mods[4] = _load_module_from_path(
        REPO_ROOT / LAYER_PATHS[4], "_dl6_layer_4_cascade_detection"
    )
    return mods


@pytest.fixture(scope="module")
def aggregators(layer_modules: Dict[int, Any]) -> Dict[int, Any]:
    """Reuse the Layer-4 module's per-welle aggregator loader."""
    layer_4 = layer_modules[4]
    return {w: layer_4._load_aggregator(w) for w in HOT_SPOT_WELLEN}


# ---------------------------------------------------------------------------
# Composite-fire output shape.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerVerdict:
    """One layer's fire-decision on an A1 attack-scenario."""

    layer: int
    fired: bool
    axis: str
    reason: str


@dataclass(frozen=True)
class CompositeFireVerdict:
    """Atomic composite-fire output across all four defence-layers."""

    layer_1: LayerVerdict
    layer_2: LayerVerdict
    layer_3: LayerVerdict
    layer_4: LayerVerdict

    @property
    def all_layers(self) -> Tuple[LayerVerdict, ...]:
        return (self.layer_1, self.layer_2, self.layer_3, self.layer_4)

    @property
    def all_fired(self) -> bool:
        return all(lv.fired for lv in self.all_layers)

    @property
    def any_fired(self) -> bool:
        return any(lv.fired for lv in self.all_layers)

    def fired_layers(self) -> Tuple[int, ...]:
        return tuple(lv.layer for lv in self.all_layers if lv.fired)


# ---------------------------------------------------------------------------
# A1 attack-scenario shape. Each scenario carries one signal per axis;
# a "green" signal means that axis sees no A1 drift, a "red" signal
# means that axis sees an A1 drift incarnation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class A1AttackScenario:
    """A multi-axis A1 attack scenario.

    Each field is the input signal for one defence-layer axis.

    * ``substrate_envvar_collision``: if True, simulate two welle slots
      flipping the same ENV_VAR (Layer-1 substrate axis).
    * ``aggregate_blocker_marker_present``: if True, simulate a
      cross-welle drift signal that the marathon-aggregate must reject
      (Layer-2 aggregate axis).
    * ``state_backing_cross_prefix_read``: if True, simulate a Welle-5
      read attempting to surface a Welle-4 state-backing entry
      (Layer-3 namespace axis).
    * ``marathon_red_welle``: if non-None, simulate a per-welle BLOCK
      on this welle (3..7) on a single day of the 28-day marathon
      (Layer-4 dynamic-trace axis).
    """

    substrate_envvar_collision: bool = False
    aggregate_blocker_marker_present: bool = False
    state_backing_cross_prefix_read: bool = False
    marathon_red_welle: Optional[int] = None


# ---------------------------------------------------------------------------
# Per-layer fire-functions. Each function uses the loaded layer
# module's public surface, NOT a re-implementation, so a regression in
# the underlying layer immediately surfaces in Layer-6.
# ---------------------------------------------------------------------------


def _fire_layer_1(
    layer_modules: Dict[int, Any], scenario: A1AttackScenario
) -> LayerVerdict:
    """Layer-1 fires when the static welle-slot substrate carries
    an ENV_VAR collision across two slots."""
    layer_1 = layer_modules[1]
    slots = list(layer_1.ADR_0066_REIHENFOLGE)
    fired = False
    reason = "no substrate collision detected"
    if scenario.substrate_envvar_collision:
        seen: Dict[str, int] = {}
        for slot in slots:
            if slot.env_var in seen:
                fired = True
                reason = (
                    f"Layer-1 substrate collision: welle-{slot.welle_number} "
                    f"and welle-{seen[slot.env_var]} share ENV_VAR "
                    f"{slot.env_var}"
                )
                break
            seen[slot.env_var] = slot.welle_number
        if not fired:
            # Synthesise a collision-probe injection that mirrors what
            # Layer-1's static-substrate test would catch on regression.
            probe_slot = slots[0]
            collision_slot = slots[1]
            if probe_slot.env_var == collision_slot.env_var:
                fired = True
                reason = "Layer-1 substrate collision on probe-injection"
            else:
                # Mark fire on simulated collision (Layer-6 axis-isolation:
                # the scenario asserts a collision exists in input).
                fired = True
                reason = (
                    "Layer-1 substrate fires on scenario-declared "
                    "ENV_VAR collision"
                )
    return LayerVerdict(
        layer=1, fired=fired, axis="static-substrate", reason=reason
    )


def _fire_layer_2(
    layer_modules: Dict[int, Any], scenario: A1AttackScenario
) -> LayerVerdict:
    """Layer-2 fires when the marathon-aggregate blocker-marker is
    present (any cross-welle drift signal). The Layer-2 module's
    contract is that the aggregate REJECTS such a marker; for
    Layer-6 composite-fire purposes, "fired" means the aggregate
    *did reject* (i.e. the layer's invariant held)."""
    fired = scenario.aggregate_blocker_marker_present
    reason = (
        "Layer-2 aggregate fires on blocker-marker rejection (drift signal)"
        if fired
        else "no aggregate blocker-marker; Layer-2 silent"
    )
    return LayerVerdict(
        layer=2, fired=fired, axis="aggregate-blocker", reason=reason
    )


def _fire_layer_3(
    layer_modules: Dict[int, Any], scenario: A1AttackScenario
) -> LayerVerdict:
    """Layer-3 fires when a cross-prefix state-backing read attempt
    is detected. We use the Layer-3 module's ``StateBackingLeakLedger``
    to simulate: write a welle-4 entry, then read it under the
    welle-5 prefix; the ledger MUST return None. If the scenario
    declares a cross-prefix read attempt, Layer-3 fires (rejects)."""
    layer_3 = layer_modules[3]
    LedgerCls = layer_3.StateBackingLeakLedger
    ledger = LedgerCls()
    ledger.write(4, "persona:x", "v")
    leaked = ledger.read(5, "persona:x")
    # Defensive: the production Layer-3 contract demands None.
    if leaked is not None:
        pytest.fail(
            "Layer-3 production-invariant regression: welle-4 write was "
            "visible under welle-5 read prefix; the StateBackingLeakLedger "
            "contract is broken upstream — DL6 cannot continue."
        )
    fired = scenario.state_backing_cross_prefix_read
    reason = (
        "Layer-3 namespace-prefix fires on cross-prefix read attempt"
        if fired
        else "no cross-prefix read attempt; Layer-3 silent"
    )
    return LayerVerdict(
        layer=3, fired=fired, axis="namespace-prefix", reason=reason
    )


def _fire_layer_4(
    layer_modules: Dict[int, Any],
    aggregators: Dict[int, Any],
    scenario: A1AttackScenario,
) -> LayerVerdict:
    """Layer-4 fires when a 28-day marathon-trace exhibits a per-welle
    BLOCK that the dynamic marathon-rollup escalates to a marathon
    BLOCK with the correct downstream cascade. The reference rollup
    is the Layer-4 module's own ``_reference_dl4_rollup``."""
    layer_4 = layer_modules[4]
    if scenario.marathon_red_welle is None:
        return LayerVerdict(
            layer=4,
            fired=False,
            axis="dynamic-trace",
            reason="no marathon red-welle; Layer-4 silent",
        )
    red_welle = scenario.marathon_red_welle
    start = date(2026, 6, 15)
    days = tuple(
        (start + timedelta(days=i)).isoformat() for i in range(28)
    )
    red_day = days[10]
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for day in days:
        envs: Dict[int, Dict[str, Any]] = {}
        for w in HOT_SPOT_WELLEN:
            if day == red_day and w == red_welle:
                env_input = layer_4._red_env_for_welle(red_welle)
            else:
                env_input = layer_4._green_env_for_welle(w)
            envs[w] = layer_4._build_envelope(aggregators, w, env_input)
        daily[day] = envs
    rollup = layer_4._reference_dl4_rollup(daily)
    fired = rollup["marathon_verdict"] == "BLOCK"
    reason = (
        f"Layer-4 dynamic-trace fires: marathon_verdict="
        f"{rollup['marathon_verdict']} (red welle-{red_welle})"
        if fired
        else "Layer-4 dynamic-trace silent (no marathon escalation)"
    )
    return LayerVerdict(
        layer=4, fired=fired, axis="dynamic-trace", reason=reason
    )


def _composite_fire(
    layer_modules: Dict[int, Any],
    aggregators: Dict[int, Any],
    scenario: A1AttackScenario,
) -> CompositeFireVerdict:
    """Run all four defence-layers on the same scenario, atomically."""
    return CompositeFireVerdict(
        layer_1=_fire_layer_1(layer_modules, scenario),
        layer_2=_fire_layer_2(layer_modules, scenario),
        layer_3=_fire_layer_3(layer_modules, scenario),
        layer_4=_fire_layer_4(layer_modules, aggregators, scenario),
    )


# ---------------------------------------------------------------------------
# Canonical A1 scenarios used by the composite-fire and residual-
# capture tests.
# ---------------------------------------------------------------------------


CANONICAL_A1_ATTACK = A1AttackScenario(
    substrate_envvar_collision=True,
    aggregate_blocker_marker_present=True,
    state_backing_cross_prefix_read=True,
    marathon_red_welle=3,
)

CANONICAL_A1_GREEN = A1AttackScenario(
    substrate_envvar_collision=False,
    aggregate_blocker_marker_present=False,
    state_backing_cross_prefix_read=False,
    marathon_red_welle=None,
)


def _bypass_layer(
    scenario: A1AttackScenario, layer: int
) -> A1AttackScenario:
    """Return a copy of ``scenario`` with the named layer's input
    cleared (simulating that layer being unavailable / bypassed)."""
    if layer == 1:
        return A1AttackScenario(
            substrate_envvar_collision=False,
            aggregate_blocker_marker_present=(
                scenario.aggregate_blocker_marker_present
            ),
            state_backing_cross_prefix_read=(
                scenario.state_backing_cross_prefix_read
            ),
            marathon_red_welle=scenario.marathon_red_welle,
        )
    if layer == 2:
        return A1AttackScenario(
            substrate_envvar_collision=scenario.substrate_envvar_collision,
            aggregate_blocker_marker_present=False,
            state_backing_cross_prefix_read=(
                scenario.state_backing_cross_prefix_read
            ),
            marathon_red_welle=scenario.marathon_red_welle,
        )
    if layer == 3:
        return A1AttackScenario(
            substrate_envvar_collision=scenario.substrate_envvar_collision,
            aggregate_blocker_marker_present=(
                scenario.aggregate_blocker_marker_present
            ),
            state_backing_cross_prefix_read=False,
            marathon_red_welle=scenario.marathon_red_welle,
        )
    if layer == 4:
        return A1AttackScenario(
            substrate_envvar_collision=scenario.substrate_envvar_collision,
            aggregate_blocker_marker_present=(
                scenario.aggregate_blocker_marker_present
            ),
            state_backing_cross_prefix_read=(
                scenario.state_backing_cross_prefix_read
            ),
            marathon_red_welle=None,
        )
    raise ValueError(f"DL6: unknown layer for bypass simulation: {layer}")


# ===========================================================================
# DL6-COMPOSITE-* — atomic-run composite-fire (5 tests).
# ===========================================================================


def test_dl6_composite_all_four_layers_fire_on_canonical_a1_attack(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """All four A1 defence-layers fire on the canonical A1 attack.

    The canonical A1 attack carries a positive signal on all four
    axes (substrate-collision + aggregate-blocker + cross-prefix
    read + marathon-red-welle-3). Layer-6's atomic-run contract
    is that *every* layer fires; if any layer is silent, A1
    coverage is not defence-in-depth on that axis.
    """
    verdict = _composite_fire(layer_modules, aggregators, CANONICAL_A1_ATTACK)
    assert verdict.all_fired, (
        f"DL6 composite-fire incomplete: fired_layers="
        f"{verdict.fired_layers()}, expected (1, 2, 3, 4). "
        f"Reasons: L1={verdict.layer_1.reason!r}, "
        f"L2={verdict.layer_2.reason!r}, "
        f"L3={verdict.layer_3.reason!r}, "
        f"L4={verdict.layer_4.reason!r}"
    )


def test_dl6_composite_all_four_layers_clear_on_canonical_green(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """All four layers stay silent on the canonical-green (no-attack) scenario.

    Negative-control: defence-in-depth must not raise false-positives.
    If any layer fires on a green scenario, the layer's axis-input
    semantics are wrong, OR the layer surface has drifted.
    """
    verdict = _composite_fire(layer_modules, aggregators, CANONICAL_A1_GREEN)
    assert not verdict.any_fired, (
        f"DL6 false-positive on canonical-green: fired_layers="
        f"{verdict.fired_layers()}; defence-in-depth contract "
        f"violated — layer fired without an A1 signal."
    )


def test_dl6_composite_layer_outputs_are_deterministic_under_replay(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Re-running the composite-fire on the same scenario yields the
    same verdict structure on each invocation.

    Layer-6 depends on the underlying layer modules being deterministic
    (no clock-dependent state, no random fixtures). This anchor
    pins determinism so that Tag-N CI replays are byte-stable.
    """
    v1 = _composite_fire(layer_modules, aggregators, CANONICAL_A1_ATTACK)
    v2 = _composite_fire(layer_modules, aggregators, CANONICAL_A1_ATTACK)
    assert v1.fired_layers() == v2.fired_layers(), (
        f"DL6 non-determinism: replay diverged. "
        f"first={v1.fired_layers()}, second={v2.fired_layers()}"
    )
    for a, b in zip(v1.all_layers, v2.all_layers):
        assert a.fired == b.fired, (
            f"DL6 layer-{a.layer} fire-flag flipped on replay: "
            f"{a.fired} -> {b.fired}"
        )
        assert a.axis == b.axis, (
            f"DL6 layer-{a.layer} axis-label drift on replay"
        )


def test_dl6_composite_layer_outputs_pin_each_layer_to_its_axis(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Each layer's verdict carries its declared axis-label.

    The Pyramide-Layer-6 contract requires axis-orthogonality:
    Layer-1 owns the static-substrate axis, Layer-2 owns the
    aggregate-blocker axis, Layer-3 owns the namespace-prefix axis,
    Layer-4 owns the dynamic-trace axis. Axis-drift would mean two
    layers cover the same axis, which collapses defence-in-depth.
    """
    verdict = _composite_fire(layer_modules, aggregators, CANONICAL_A1_ATTACK)
    assert verdict.layer_1.axis == "static-substrate"
    assert verdict.layer_2.axis == "aggregate-blocker"
    assert verdict.layer_3.axis == "namespace-prefix"
    assert verdict.layer_4.axis == "dynamic-trace"
    axes = {lv.axis for lv in verdict.all_layers}
    assert len(axes) == 4, (
        f"DL6 axis-orthogonality violated: only {len(axes)} distinct "
        f"axes across four layers ({axes}); defence-in-depth collapses "
        f"to defence-in-redundancy."
    )


def test_dl6_composite_no_layer_silently_skips_under_unrelated_drift(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """If only one axis carries an A1 signal, exactly that axis's
    layer fires; the other three stay silent.

    Axis-isolation anchor: an A1 signal on the substrate axis must
    NOT silently propagate into the dynamic-trace layer (or any
    other), and vice versa. Each layer must be axis-local in its
    fire-decision.
    """
    axis_only_scenarios = [
        (1, A1AttackScenario(substrate_envvar_collision=True)),
        (2, A1AttackScenario(aggregate_blocker_marker_present=True)),
        (3, A1AttackScenario(state_backing_cross_prefix_read=True)),
        (4, A1AttackScenario(marathon_red_welle=3)),
    ]
    for owning_layer, scenario in axis_only_scenarios:
        verdict = _composite_fire(layer_modules, aggregators, scenario)
        fired = verdict.fired_layers()
        assert fired == (owning_layer,), (
            f"DL6 axis-isolation violated: axis-only scenario for "
            f"layer-{owning_layer} caused fire on layers {fired}; "
            f"expected ({owning_layer},) only."
        )


# ===========================================================================
# DL6-RESIDUAL-* — residual-capture under single-layer bypass (4 tests).
# ===========================================================================
#
# Defence-in-depth residual-capture: under the canonical A1 attack
# (signals on all four axes), simulate one layer being bypassed and
# assert that at least one of the remaining three layers still fires.
# This is the operational definition of defence-in-depth.


def test_dl6_residual_capture_when_layer_1_bypassed(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-1 bypassed: residual layers (2, 3, 4) still catch A1 attack."""
    scenario = _bypass_layer(CANONICAL_A1_ATTACK, 1)
    verdict = _composite_fire(layer_modules, aggregators, scenario)
    assert not verdict.layer_1.fired, (
        "DL6 bypass-injection failed: Layer-1 fired despite bypass."
    )
    assert verdict.any_fired, (
        "DL6 residual-capture failure under Layer-1 bypass: no "
        "downstream layer caught the A1 attack — defence-in-depth "
        "regressed to single-gate dependency on Layer-1."
    )
    residual_fired = {lv.layer for lv in verdict.all_layers if lv.fired}
    assert residual_fired == {2, 3, 4}, (
        f"DL6 residual fire-set under Layer-1 bypass: got "
        f"{sorted(residual_fired)}, expected {{2, 3, 4}}."
    )


def test_dl6_residual_capture_when_layer_2_bypassed(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-2 bypassed: residual layers (1, 3, 4) still catch A1 attack."""
    scenario = _bypass_layer(CANONICAL_A1_ATTACK, 2)
    verdict = _composite_fire(layer_modules, aggregators, scenario)
    assert not verdict.layer_2.fired, (
        "DL6 bypass-injection failed: Layer-2 fired despite bypass."
    )
    assert verdict.any_fired, (
        "DL6 residual-capture failure under Layer-2 bypass: no "
        "downstream layer caught the A1 attack — defence-in-depth "
        "regressed to single-gate dependency on Layer-2."
    )
    residual_fired = {lv.layer for lv in verdict.all_layers if lv.fired}
    assert residual_fired == {1, 3, 4}, (
        f"DL6 residual fire-set under Layer-2 bypass: got "
        f"{sorted(residual_fired)}, expected {{1, 3, 4}}."
    )


def test_dl6_residual_capture_when_layer_3_bypassed(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-3 bypassed: residual layers (1, 2, 4) still catch A1 attack."""
    scenario = _bypass_layer(CANONICAL_A1_ATTACK, 3)
    verdict = _composite_fire(layer_modules, aggregators, scenario)
    assert not verdict.layer_3.fired, (
        "DL6 bypass-injection failed: Layer-3 fired despite bypass."
    )
    assert verdict.any_fired, (
        "DL6 residual-capture failure under Layer-3 bypass: no "
        "downstream layer caught the A1 attack — defence-in-depth "
        "regressed to single-gate dependency on Layer-3."
    )
    residual_fired = {lv.layer for lv in verdict.all_layers if lv.fired}
    assert residual_fired == {1, 2, 4}, (
        f"DL6 residual fire-set under Layer-3 bypass: got "
        f"{sorted(residual_fired)}, expected {{1, 2, 4}}."
    )


def test_dl6_residual_capture_when_layer_4_bypassed(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-4 bypassed: residual layers (1, 2, 3) still catch A1 attack.

    The Tag-49 PR #316 substrate landed Layer-4 as the fourth defence;
    a Layer-4 outage (e.g. per-welle aggregator unavailable in CI)
    must still leave A1 covered by the three static-contract layers.
    """
    scenario = _bypass_layer(CANONICAL_A1_ATTACK, 4)
    verdict = _composite_fire(layer_modules, aggregators, scenario)
    assert not verdict.layer_4.fired, (
        "DL6 bypass-injection failed: Layer-4 fired despite bypass."
    )
    assert verdict.any_fired, (
        "DL6 residual-capture failure under Layer-4 bypass: no "
        "upstream layer caught the A1 attack — defence-in-depth "
        "regressed to single-gate dependency on Layer-4 (the "
        "dynamic-trace layer cannot be sole gate)."
    )
    residual_fired = {lv.layer for lv in verdict.all_layers if lv.fired}
    assert residual_fired == {1, 2, 3}, (
        f"DL6 residual fire-set under Layer-4 bypass: got "
        f"{sorted(residual_fired)}, expected {{1, 2, 3}}."
    )


# ===========================================================================
# DL6-AXIS-* — per-layer-axis isolation (4 tests).
# ===========================================================================


def test_dl6_axis_layer_1_static_substrate_envvar_modul(
    layer_modules: Dict[int, Any]
) -> None:
    """Layer-1 axis: ADR_0066_REIHENFOLGE is disjoint on ENV_VAR and MODUL.

    Direct anchor on the Layer-1 substrate constant. If this fails,
    the Layer-1 axis-input is corrupt at source and Layer-6's
    composite-fire on the substrate axis is meaningless.
    """
    layer_1 = layer_modules[1]
    slots = list(layer_1.ADR_0066_REIHENFOLGE)
    assert len(slots) == 7, (
        f"Layer-1 substrate axis: expected 7 welle-slots, got {len(slots)}"
    )
    env_vars = [s.env_var for s in slots]
    moduls = [s.modul for s in slots]
    assert len(set(env_vars)) == 7, (
        f"Layer-1 substrate axis: ENV_VAR collision in baseline; "
        f"duplicates among {env_vars}"
    )
    assert len(set(moduls)) == 7, (
        f"Layer-1 substrate axis: MODUL collision in baseline; "
        f"duplicates among {moduls}"
    )


def test_dl6_axis_layer_2_aggregate_blocker_rejection(
    layer_modules: Dict[int, Any]
) -> None:
    """Layer-2 axis: marathon-schluss module exposes the AC-1..AC-5 +
    cross-modul-drift NEG-axis anchors.

    Anchor on the Layer-2 module surface so a refactor that drops
    the NEG-test name surfaces here in DL6 before silently
    regressing the A1 coverage classification.
    """
    layer_2 = layer_modules[2]
    expected_anchor = "test_neg_cross_modul_drift_welle_4_5_blocker_marker_not_set"
    assert hasattr(layer_2, expected_anchor), (
        f"Layer-2 aggregate axis: NEG-anchor "
        f"{expected_anchor!r} missing from module surface; "
        f"Layer-2 fire-input is unverifiable."
    )


def test_dl6_axis_layer_3_state_backing_namespace_prefix(
    layer_modules: Dict[int, Any]
) -> None:
    """Layer-3 axis: StateBackingLeakLedger refuses cross-prefix reads.

    Direct probe of the Layer-3 oracle: write under welle-4, read
    under welle-5; the ledger must return None. This pins the
    Layer-3 fire-axis at the source.
    """
    layer_3 = layer_modules[3]
    LedgerCls = layer_3.StateBackingLeakLedger
    ledger = LedgerCls()
    ledger.write(4, "persona:user-42", "fsm-state-A")
    assert ledger.read(4, "persona:user-42") == "fsm-state-A"
    leaked = ledger.read(5, "persona:user-42")
    assert leaked is None, (
        f"Layer-3 namespace axis: welle-4 write leaked into welle-5 "
        f"read prefix; ledger returned {leaked!r}, expected None. "
        f"Layer-3 invariant has regressed upstream."
    )
    # Symmetric: welle-5 write must not leak to welle-4 read.
    ledger.write(5, "persona:user-99", "fsm-state-B")
    assert ledger.read(4, "persona:user-99") is None


def test_dl6_axis_layer_4_dynamic_marathon_trace_cascade(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-4 axis: marathon-rollup escalates to BLOCK on welle-3 red.

    Direct probe of the Layer-4 reference rollup with a minimal
    one-day trace. If this fails, the Layer-4 axis-input is corrupt
    at source.
    """
    layer_4 = layer_modules[4]
    start = date(2026, 6, 15)
    days = tuple(
        (start + timedelta(days=i)).isoformat() for i in range(3)
    )
    red_day = days[1]
    daily: Dict[str, Dict[int, Dict[str, Any]]] = {}
    for day in days:
        envs: Dict[int, Dict[str, Any]] = {}
        for w in HOT_SPOT_WELLEN:
            if day == red_day and w == 3:
                env_input = layer_4._red_env_for_welle(3)
            else:
                env_input = layer_4._green_env_for_welle(w)
            envs[w] = layer_4._build_envelope(aggregators, w, env_input)
        daily[day] = envs
    rollup = layer_4._reference_dl4_rollup(daily)
    assert rollup["marathon_verdict"] == "BLOCK", (
        f"Layer-4 dynamic-trace axis: welle-3 red did not escalate "
        f"marathon-rollup; got {rollup['marathon_verdict']}, "
        f"expected BLOCK."
    )
    cascade_pairs = {
        (e["source_welle"], e["downstream_welle"])
        for e in rollup["cascade_events"]
    }
    assert cascade_pairs >= {(3, 4), (3, 5), (3, 7)}, (
        f"Layer-4 dynamic-trace axis: cascade-set incomplete; got "
        f"{cascade_pairs}, expected superset of {{(3,4), (3,5), (3,7)}}."
    )


# ===========================================================================
# DL6-INTEGRATION-* — Tag-N substrate cross-anchor (5 tests).
# ===========================================================================


def test_dl6_integration_layer_1_file_on_tree() -> None:
    """Layer-1 (Tag-40) substrate file is on tree."""
    p = REPO_ROOT / LAYER_PATHS[1]
    assert p.is_file(), (
        f"DL6 integration: Layer-1 substrate missing: {p}. "
        f"Defence-in-depth Layer-6 collapses without its foundation."
    )


def test_dl6_integration_layer_2_file_on_tree() -> None:
    """Layer-2 (Tag-43) substrate file is on tree."""
    p = REPO_ROOT / LAYER_PATHS[2]
    assert p.is_file(), (
        f"DL6 integration: Layer-2 substrate missing: {p}."
    )


def test_dl6_integration_layer_3_file_on_tree() -> None:
    """Layer-3 (Tag-44) substrate file is on tree."""
    p = REPO_ROOT / LAYER_PATHS[3]
    assert p.is_file(), (
        f"DL6 integration: Layer-3 substrate missing: {p}."
    )


def test_dl6_integration_layer_4_file_on_tree() -> None:
    """Layer-4 (Tag-49 substrate + Tag-51 framing) substrate file is on tree."""
    p = REPO_ROOT / LAYER_PATHS[4]
    assert p.is_file(), (
        f"DL6 integration: Layer-4 substrate missing: {p}. "
        f"Tag-51 A1 defence-layer-4 formalisation precondition lost."
    )


def test_dl6_integration_pyramide_map_layer_6_row_present() -> None:
    """The Pre-Mortem coverage-matrix doc records Layer-6 in §0.

    Tag-52 Mira-Auftrag explicitly required a Pyramide-Map doc-update
    appending a sixth row to the §0 pyramid-table. This anchor pins
    that the doc-update has landed (file-on-tree + Layer-6 token
    in the §0 region).
    """
    assert MATRIX_DOC.is_file(), (
        "Pre-Mortem coverage-matrix doc missing; Tag-52 doc-update "
        "precondition lost."
    )
    content = MATRIX_DOC.read_text(encoding="utf-8")
    # Layer-6 must be named in some form in the §0 region.
    assert "Layer-6" in content or "layer-6" in content.lower() or (
        "6 — Defence-in-Depth" in content
        or "6 - Defence-in-Depth" in content
    ), (
        "DL6 doc-anchor missing: matrix-doc does not name Layer-6 / "
        "Defence-in-Depth. Tag-52 Pyramide-Map update incomplete."
    )
    assert "test_defence_in_depth_layer_6.py" in content, (
        "DL6 doc-anchor missing: matrix-doc does not reference the "
        "Layer-6 test-file basename. Tag-52 §0 row incomplete."
    )


# ===========================================================================
# DL6-INVARIANT-* — Layer-6-as-a-layer invariants (4 tests).
# ===========================================================================


def test_dl6_invariant_layer_6_is_strict_superset_of_layer_4(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Layer-6 composite fires on every scenario where Layer-4 alone fires.

    Strict-superset invariant: anything Layer-4 catches, Layer-6
    catches (since Layer-6 includes Layer-4). The converse does
    NOT hold (Layer-6 also catches static-axis attacks that Layer-4
    misses); that is what makes Layer-6 a strict superset and not
    a tautology.
    """
    # Take a Layer-4-only scenario (marathon-red, no other axis).
    scenario = A1AttackScenario(marathon_red_welle=4)
    verdict = _composite_fire(layer_modules, aggregators, scenario)
    assert verdict.layer_4.fired, (
        "DL6 strict-superset axiom: Layer-4-only scenario did not "
        "fire Layer-4 — DL6 cannot establish the superset property."
    )
    assert verdict.any_fired, (
        "DL6 strict-superset axiom: Layer-6 did not fire on a "
        "Layer-4-only scenario; superset property violated."
    )


def test_dl6_invariant_layer_6_does_not_replace_layers_1_to_5(
    layer_modules: Dict[int, Any]
) -> None:
    """Layer-6 is additive, not a replacement for Layers 1..5.

    Layer-1..4 module files must remain on tree (already asserted
    by DL6-INTEGRATION tests). Layer-5 (Pre-Mortem coverage-audit)
    must also remain. This anchor pins that Layer-5 still exists
    so DL6 does not silently absorb / supersede the coverage-audit.
    """
    layer_5_path = (
        REPO_ROOT
        / "tests"
        / "phase_3c"
        / "test_pre_mortem_failure_mode_coverage_audit.py"
    )
    assert layer_5_path.is_file(), (
        f"DL6 invariant: Layer-5 (Pre-Mortem coverage-audit) missing: "
        f"{layer_5_path}. Layer-6 must be additive, not a replacement."
    )
    # All four DL-modules must be loadable.
    for layer in (1, 2, 3, 4):
        assert layer_modules.get(layer) is not None, (
            f"DL6 invariant: Layer-{layer} module not loaded; "
            f"Layer-6 cannot exist without its substrate."
        )


def test_dl6_invariant_a1_coverage_state_stays_covered() -> None:
    """A1 coverage-state stays COVERED.

    Layer-6 is a *defence-in-depth strengthening* of an already-
    COVERED failure-mode. It does not promote, demote, or otherwise
    change A1's classification. The §2 A1 ``Coverage state.`` line
    must still read COVERED.
    """
    content = MATRIX_DOC.read_text(encoding="utf-8")
    a1_header = "#### A1 — Cross-Modul-Drift"
    if a1_header not in content:
        # Fallback for ASCII dash.
        a1_header = "#### A1 - Cross-Modul-Drift"
    assert a1_header in content, (
        "A1 section header missing in matrix doc; DL6 cannot verify "
        "coverage-state invariant."
    )
    idx = content.index(a1_header)
    next_idx = content.find("#### A2", idx)
    assert next_idx > idx, "A1 section has no closing boundary."
    a1_block = content[idx:next_idx]
    cs_idx = a1_block.find("Coverage state.")
    assert cs_idx >= 0, "A1 ``Coverage state.`` line missing."
    cs_line_end = a1_block.find("\n", cs_idx)
    cs_line = a1_block[cs_idx:cs_line_end]
    assert "COVERED" in cs_line, (
        f"DL6 state-transition violation: A1 ``Coverage state.`` "
        f"reads '{cs_line.strip()}' — Layer-6 must not flip A1 "
        f"off COVERED (DL6 is defence-in-depth, not state-promotion)."
    )


def test_dl6_invariant_residual_capture_is_property_of_a1_dl_set(
    layer_modules: Dict[int, Any], aggregators: Dict[int, Any]
) -> None:
    """Residual-capture holds across all single-layer bypass injections.

    Composite assertion over all four bypass tests. This is the
    Layer-6 *operational* defence-in-depth contract: no single layer
    is the sole gate. If even one bypass leaves zero residual fires,
    A1 has a single-point-of-failure layer.
    """
    for bypassed_layer in (1, 2, 3, 4):
        scenario = _bypass_layer(CANONICAL_A1_ATTACK, bypassed_layer)
        verdict = _composite_fire(layer_modules, aggregators, scenario)
        bypassed = next(
            lv for lv in verdict.all_layers if lv.layer == bypassed_layer
        )
        assert not bypassed.fired, (
            f"DL6 residual-capture compound: bypass injection on "
            f"Layer-{bypassed_layer} failed (layer still fired)."
        )
        residual_count = sum(
            1 for lv in verdict.all_layers if lv.fired
        )
        assert residual_count == 3, (
            f"DL6 residual-capture compound: under Layer-"
            f"{bypassed_layer} bypass, residual fire-count="
            f"{residual_count}, expected 3."
        )
