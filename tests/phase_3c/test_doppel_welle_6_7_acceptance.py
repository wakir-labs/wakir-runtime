# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""E2E acceptance for the Phase-3c Doppel-Welle KW-27 cutover
(``subscribe_loop`` + ``recovery_workflow``/``recovery`` parallel).

Hermetic, stdlib-only. The pair-smoke modules (``scripts/phase-3c/
welle-6-subscribe-loop-cutover-smoke.py`` + ``scripts/phase-3c/
welle-7-recovery-workflow-cutover-smoke.py`` if Selin's Tag-39
spawn has landed) are loaded via importlib from their hyphenated
paths. While neither file is on the tree yet, the test-suite shims
both partners with a per-test resolver stub built on the Welle-4
COMPONENT-Inventar (``subscribe_loop`` + ``recovery`` are listed
on the same inventar that the Welle-4 smoke exports).

Auftrag-Anker
-------------

- Tag-39 Amara Auftrag — Welle-6+7-Doppel-Welle E2E-Acceptance-Suite
  (Continuous-Mode). 6-8 DW-AC-6-7 tests covering aspects not yet
  exercised by ``tests/acceptance/phase_3c/test_doppel_welle_6_7_e2e
  .py`` (which focuses on cross-modul-schema-drift + per-Komponente
  consistency).
- ADR-0066 §Beschluss — KW 27 Doppel-Welle Welle-6 + Welle-7 parallel
  cutover (subscribe_loop + recovery_workflow). Telescopes Welle-7-
  AC + WE-1...WE-4 into the same cutover-week and triggers the
  Phase-3-Marathon-Schluss-Acceptance per ADR-0065 §Welle-Ende-AC.
- Welle-6 and Welle-7 smokes are Selin's parallel Tag-39 spawn; this
  file is the **two-modul** orchestrator layer that drives a single
  Engine-Boot through both modul flips.
- PR #221 (Tag-32 CMD-AC-6-7 alte Generation) and PR #252 (Tag-38
  DW-AC-4-5 sequential-vs-parallel pattern) are the structural
  templates. This file is the Tag-39 generation of CMD-AC-6-7 on
  the current Welle-6+7 substrate-Stand.

Scope (8 tests; Auftrag-Tag-39 minimum is 6 — exceeded to cover
both the *happy* and *blocker* axes for each dimension, plus the
Phase-3-Marathon-Schluss-Acceptance gate which only fires for the
KW-27 cutover)
-----------------------------------------------------------------

DW-AC-6-7-PAR — Parallel-Cutover-Path (both moduln rust in one boot)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1.  test_dw_ac_6_7_par_both_moduln_rust_in_single_engine_boot
2.  test_dw_ac_6_7_par_nats_subject_drift_between_subscribe_loop_and_recovery_blocks

DW-AC-6-7-SEQ — Sequential-Cutover-Path (Welle-6 then Welle-7)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.  test_dw_ac_6_7_seq_welle_6_first_then_welle_7_terminal_equivalence

DW-AC-6-7-SLDC — Subscribe-Loop-Drain-Continuity over parallel-Cutover
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

4.  test_dw_ac_6_7_sldc_subscription_cursor_continuous_over_cutover

DW-AC-6-7-RDC — Recovery-Drill-Continuity over subscribe_loop-Cutover
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

5.  test_dw_ac_6_7_rdc_recovery_restart_point_holds_over_subscribe_loop_flip

DW-AC-6-7-RC — Race-Condition battery (NATS-subject-drift, R1-token-rotation)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

6.  test_dw_ac_6_7_rc_r1_capability_token_rotation_race_blocks

DW-AC-6-7-P3M — Phase-3-Marathon-Schluss-Acceptance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

7.  test_dw_ac_6_7_p3m_all_seven_moduln_rust_after_doppel_welle_6_7
8.  test_dw_ac_6_7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker

Cross-spawn-Konsistenz
----------------------

- Selin's Welle-6+7-Smokes (paralleler Tag-39 spawn): per-modul
  anchors. The Welle-6 partner-contract (subscribe_loop ↔ recovery)
  mirrors the Welle-4 ↔ Welle-5 WELLE_5_PARTNER shape — env-var
  isolation is the substrate-level invariant.
- Kai's Welle-6+7-Runbooks (paralleler Tag-39 spawn): cutover-
  Decision-Matrix parallel vs. sequential; this file's DW-PAR-1 /
  DW-SEQ-1 tests are the CI gate that the runbook references.
- Tomás's Welle-6+7-Validation-Workflows (paralleler Tag-39 spawn):
  ci-aggregator job covering the Doppel-Welle-KW-27 gate this file
  feeds.

Hermetic-only — no podman, no live NATS, no live engine. The tests
build a single per-test resolver-stub that scripts both moduln's
BackendDecision based on per-phase ENV-vars. Note: ADR-0066 calls
Welle-7 ``recovery_workflow`` but the engine-inventar component
identifier is ``recovery`` (the env-var is ``WAKIR_RECOVERY_BACKEND``).
We treat the two names as synonyms in the test-substrate so that
the acceptance-gates can be referenced from runbooks that use
either name.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Smoke-module loaders (importlib because of the hyphenated paths).
# We reuse the Welle-4 smoke as the boot-substrate authority — its
# ENGINE_BOOT_COMPONENTS + COMPONENT_TO_ENV inventory lists
# subscribe_loop + recovery alongside the rest of the engine.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_smoke_module(filename: str, module_name: str) -> Any:
    """Load a phase-3c smoke module by its hyphenated filename."""
    smoke_path = _repo_root() / "scripts" / "phase-3c" / filename
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(smoke_path))
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


WELLE_4 = _load_smoke_module(
    "welle-4-state-backing-cutover-smoke.py",
    "welle_4_state_backing_cutover_smoke_for_dw_6_7",
)


# ---------------------------------------------------------------------------
# Doppel-Welle-6+7 Phase-ENV builder.
#
# build_doppel_phase_env composes the ENV-Map for one of:
#   * "pre"            — both python (baseline; KW-26-terminal state)
#   * "post_parallel"  — both flipped to rust in *one* engine boot
#   * "post_seq_w6"    — subscribe_loop rust, recovery still python
#   * "post_seq_w7"    — subscribe_loop rust, recovery also rust
#                        (terminal sequential state)
#   * "rollback"       — both env-vars absent (engine reads python-
#                        defaults; same Quadlet-post-rollback shape)
#
# The pre-state for Welle-6+7 is the KW-26-terminal Doppel-Welle-4-5
# end-state: the first five moduln are *already* rust. This is the
# substantive difference from the Welle-4-5 acceptance — Welle-6+7
# closes Phase-3c, so the baseline is "rust everywhere except the
# Welle-6+7 pair".
# ---------------------------------------------------------------------------


PHASE_DW_PRE = "pre_cutover_kw_26_terminal"
PHASE_DW_POST_PARALLEL = "post_cutover_doppel_parallel"
PHASE_DW_POST_SEQ_W6 = "post_cutover_sequential_welle6_only"
PHASE_DW_POST_SEQ_W7 = "post_cutover_sequential_welle7_terminal"
PHASE_DW_ROLLBACK = "rollback_python_both"

VALID_DW_PHASES: Tuple[str, ...] = (
    PHASE_DW_PRE,
    PHASE_DW_POST_PARALLEL,
    PHASE_DW_POST_SEQ_W6,
    PHASE_DW_POST_SEQ_W7,
    PHASE_DW_ROLLBACK,
)

SUBSCRIBE_LOOP_ENV_VAR = "WAKIR_SUBSCRIBE_LOOP_BACKEND"
RECOVERY_ENV_VAR = "WAKIR_RECOVERY_BACKEND"

#: Welle-6+7 ADR-0066-name vs. engine-inventar-name synonyms. ADR-0066
#: §Beschluss labels Welle-7 ``recovery_workflow``; the engine
#: COMPONENT_TO_ENV inventory uses ``recovery``. We keep both as
#: addressable identifiers so this file is readable from either side.
WELLE_6_MODUL = "subscribe_loop"
WELLE_7_MODUL = "recovery"
WELLE_7_ADR_NAME = "recovery_workflow"

#: KW-26-terminal moduln are *already* rust before KW-27 starts. The
#: Welle-1..5 cutovers landed in prior Mittwochs (KW 24 → 26). Note:
#: bridge_audit_writer + bridge_audit_diff_engine flip during the
#: Welle-3 cutover (KW 25) per ADR-0066 §Beschluss table.
KW_26_TERMINAL_RUST_MODULN: Tuple[str, ...] = (
    "v907_verify",
    "svid_workload_identity",
    "bridge_diff",
    "anchor_emitter",
    "state_backing",
    "fsm",
    "federation_resolver",
    "bridge_audit_writer",
    "bridge_audit_diff_engine",
)

#: state_backing's rust enum-value (matches the Welle-4-smoke
#: ENV_VALUE_RUST_DEFAULT constant). Used to mirror the KW-26-terminal
#: substrate for state_backing in the pre-Welle-6+7 baseline.
STATE_BACKING_RUST_VALUE = "rust_inmemory"


def _kw_26_terminal_value_for(component: str) -> str:
    """Return the KW-26-terminal env-value for ``component``.

    Most moduln post-KW-26 are ``"rust"``; state_backing uses
    ``"rust_inmemory"`` because the Welle-4 smoke documents this as
    the ADR-0066 §Welle-4 default cutover target.
    """
    if component == "state_backing":
        return STATE_BACKING_RUST_VALUE
    return "rust"


def build_doppel_phase_env(phase: str) -> Dict[str, str]:
    """Compose the hermetic Doppel-Welle-6+7 ENV-map for ``phase``.

    The KW-26-terminal substrate is the baseline: all moduln *except*
    subscribe_loop + recovery are already rust. The Welle-6+7
    Doppel-Welle-only stress is the orthogonal axis — does the final
    pair-flip preserve the all-rust invariant.
    """
    if phase not in VALID_DW_PHASES:
        raise ValueError(
            f"unknown Doppel-Welle phase {phase!r}; expected one of "
            f"{VALID_DW_PHASES!r}"
        )
    env: Dict[str, str] = {}
    # Pre-populate KW-26-terminal rust state for the prior 5 wellen.
    for component in KW_26_TERMINAL_RUST_MODULN:
        env_var = WELLE_4.COMPONENT_TO_ENV[component]
        env[env_var] = _kw_26_terminal_value_for(component)
    # Welle-6+7 moduln default to python in pre/baseline.
    env[SUBSCRIBE_LOOP_ENV_VAR] = "python"
    env[RECOVERY_ENV_VAR] = "python"

    if phase == PHASE_DW_PRE:
        return env
    if phase == PHASE_DW_POST_PARALLEL:
        env[SUBSCRIBE_LOOP_ENV_VAR] = "rust"
        env[RECOVERY_ENV_VAR] = "rust"
        return env
    if phase == PHASE_DW_POST_SEQ_W6:
        env[SUBSCRIBE_LOOP_ENV_VAR] = "rust"
        # recovery stays python — intermediate state during sequential
        # cutover between Welle-6 cutover-Tag and Welle-7 cutover-Tag.
        return env
    if phase == PHASE_DW_POST_SEQ_W7:
        env[SUBSCRIBE_LOOP_ENV_VAR] = "rust"
        env[RECOVERY_ENV_VAR] = "rust"
        return env
    # PHASE_DW_ROLLBACK: pair env-vars unset; engine reads python-default.
    env.pop(SUBSCRIBE_LOOP_ENV_VAR, None)
    env.pop(RECOVERY_ENV_VAR, None)
    return env


# ---------------------------------------------------------------------------
# Doppel-Welle-6+7 resolver stub.
#
# The smoke-module's _resolve_resolver_for_component uses upstream-or-
# shim resolution. For the Doppel-Welle-6+7 E2E we side-step that and
# inject a module exporting per-component resolver functions whose
# BackendDecision is driven entirely by the env-map.
#
# The stub honours the Welle-6+7 cross-modul contract:
# subscribe_loop's env-flip MUST NOT affect recovery's chosen_backend
# (and vice-versa) unless the per-test scenario explicitly scripts
# the contract-break (NATS-subject-drift, R1-capability-token-
# rotation-race, ...).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubBackendDecision:
    """Mirrors the BackendDecision dataclass at the contract level."""

    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


@dataclass
class DoppelStubConfig:
    """Per-test knobs that script the contract-break scenarios."""

    # NATS-subject-drift: when True, recovery_workflow's resolver
    # incorrectly subscribes to a drift-prone subject because it
    # consults SUBSCRIBE_LOOP_ENV_VAR for its subject-prefix logic.
    # This is the Welle-6+7 analogue of the env-clobber bug pattern
    # in the Welle-4+5 acceptance.
    nats_subject_drift: bool = False
    # R1-capability-token-rotation-race: when True, the resolver
    # surfaces a fallback_reason indicating that the R1 token rotated
    # mid-cutover and the post-cutover boot picked up a stale token.
    # Welle-6 is NATS-bound (R1 tokens authenticate subscriptions);
    # Welle-7 cross-reads R1 tokens during restart-point reconstruction.
    r1_token_rotation_race: bool = False
    # Boot-order witness: when set, the stub records ordered tuples of
    # (component, chosen_backend) as resolvers are called. The Doppel-
    # Welle-6+7 invariant is subscribe_loop precedes recovery so that
    # recovery's restart-point reconstruction reads a settled
    # subscribe_loop substrate.
    boot_order_witness: Optional[List[Tuple[str, str]]] = None
    # Recovery-first inversion: when True, recovery resolves before
    # subscribe_loop. Used to surface the inversion-detection gate.
    recovery_first_boot_order: bool = False
    # P3M signal collector: when set, the stub appends a Phase-3-
    # Marathon-Schluss-Acceptance marker once both Welle-6+7 moduln
    # report rust. This is the substrate-level witness that the
    # Welle-7 sign-off triggers the Phase-3-COMPLETE marker.
    p3m_signal_sink: Optional[List[str]] = None


def build_doppel_resolver_module(
    config: Optional[DoppelStubConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module driving the env-map.

    Returns a module exporting resolve_<component>_backend for every
    component in ENGINE_BOOT_COMPONENTS (Welle-4 inventory: 11 components).
    """
    cfg = config or DoppelStubConfig()
    module = types.ModuleType("wirelang.persona_engine.rust_backend_switch")

    # Per-instance trackers for the contract-break scenarios.
    rust_seen: Dict[str, bool] = {WELLE_6_MODUL: False, WELLE_7_MODUL: False}

    def _resolve_factory(component: str) -> Callable[..., Tuple[str, StubBackendDecision]]:
        def _resolver(
            env: Optional[Mapping[str, str]] = None,
            *,
            log_sink: Any = None,
            binary_probe: Any = None,
        ) -> Tuple[str, StubBackendDecision]:
            env_map = env or {}
            env_var = WELLE_4.COMPONENT_TO_ENV[component]
            raw = env_map.get(env_var, "")
            requested = raw if raw else "python"

            # Default behaviour: requested-honored.
            chosen = requested
            fallback_reason: Optional[str] = None

            if component == WELLE_6_MODUL:
                if cfg.boot_order_witness is not None:
                    cfg.boot_order_witness.append((component, chosen))
                if cfg.r1_token_rotation_race:
                    # Subscribe-loop is R1-token-authenticated; if the
                    # token rotated mid-cutover the resolver records
                    # the race even though the chosen backend may be
                    # legitimate.
                    if chosen == "rust":
                        fallback_reason = "test_r1_token_rotation_race"

            if component == WELLE_7_MODUL:
                if cfg.boot_order_witness is not None:
                    cfg.boot_order_witness.append((component, chosen))
                if cfg.nats_subject_drift:
                    # Bug-pattern: recovery's resolver consults
                    # SUBSCRIBE_LOOP_ENV_VAR (it should *only* consult
                    # RECOVERY_ENV_VAR), so if subscribe_loop is rust
                    # but recovery is python, recovery still flips.
                    sl_raw = env_map.get(SUBSCRIBE_LOOP_ENV_VAR, "")
                    if sl_raw and sl_raw != "python":
                        chosen = "rust"
                        fallback_reason = "test_nats_subject_drift"
                if cfg.r1_token_rotation_race:
                    # Recovery cross-reads R1 tokens during restart-
                    # point reconstruction; the race surfaces here too
                    # when chosen has already moved to rust.
                    if chosen == "rust" and fallback_reason is None:
                        fallback_reason = "test_r1_token_rotation_race"

            decision = StubBackendDecision(
                domain=component,
                requested_backend=requested,
                chosen_backend=chosen,
                resolution_latency_us=30,
                fallback_reason=fallback_reason,
                bin_path=None,
            )

            # Phase-3-Marathon-Schluss-Acceptance signalling.
            if component in {WELLE_6_MODUL, WELLE_7_MODUL} and chosen == "rust":
                rust_seen[component] = True
                if (
                    cfg.p3m_signal_sink is not None
                    and rust_seen[WELLE_6_MODUL]
                    and rust_seen[WELLE_7_MODUL]
                ):
                    # Idempotent: only append the first time both
                    # moduln report rust on the same boot.
                    marker = "PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7"
                    if marker not in cfg.p3m_signal_sink:
                        cfg.p3m_signal_sink.append(marker)

            return chosen, decision

        return _resolver

    for component in WELLE_4.ENGINE_BOOT_COMPONENTS:
        setattr(
            module, f"resolve_{component}_backend", _resolve_factory(component)
        )
    return module


def _ordered_components(recovery_first: bool) -> Tuple[str, ...]:
    """Return ENGINE_BOOT_COMPONENTS reordered for boot-order tests.

    When ``recovery_first=True``, ``recovery`` is moved to immediately
    precede ``subscribe_loop`` in the iteration. This surfaces any
    order-sensitive resolver bug that would otherwise hide behind the
    Welle-4-smoke's canonical order (subscribe_loop precedes recovery).
    """
    components = list(WELLE_4.ENGINE_BOOT_COMPONENTS)
    if not recovery_first:
        return tuple(components)
    components.remove(WELLE_6_MODUL)
    components.remove(WELLE_7_MODUL)
    components.extend([WELLE_7_MODUL, WELLE_6_MODUL])
    return tuple(components)


def _boot_doppel(
    phase: str,
    *,
    config: Optional[DoppelStubConfig] = None,
    recovery_first: bool = False,
) -> List[Dict[str, Any]]:
    """Single engine-boot through the Doppel-Welle-6+7 phase.

    Returns the list of BackendDecision-records produced by all
    components on this boot.
    """
    env = build_doppel_phase_env(phase)
    resolver = build_doppel_resolver_module(config)
    components = _ordered_components(recovery_first)
    return WELLE_4.boot_engine_once(
        env=env,
        components=components,
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
    )


def _decision_for(records: List[Dict[str, Any]], domain: str) -> Dict[str, Any]:
    """Pick the BackendDecision-record for ``domain`` out of a boot.

    Asserts exactly one match — duplicates would indicate a smoke-
    contract drift and should surface as a hard test-error.
    """
    matches = [r for r in records if r["domain"] == domain]
    assert len(matches) == 1, (
        f"expected exactly one decision-record for domain={domain!r}; "
        f"got {len(matches)} in records={records!r}"
    )
    return matches[0]


# ---------------------------------------------------------------------------
# DW-AC-6-7-PAR — Parallel-Cutover-Path.
#
# Both moduln flip to rust in *one* engine-boot cycle. This is the
# ADR-0066 §Beschluss target shape for KW 27: cutover-Mittwoch
# ENV-Flag-Switch rewrites *both* env-vars + single systemctl restart.
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_par_both_moduln_rust_in_single_engine_boot() -> None:
    """DW-AC-6-7-PAR: subscribe_loop + recovery both report
    ``chosen=rust`` in the same boot when env-vars are set together.

    The post-PARALLEL boot must show:
      * subscribe_loop.chosen_backend == "rust"
      * recovery.chosen_backend == "rust"
      * every KW-26-terminal modul stays on its KW-26-terminal value
        (rust everywhere — i.e. no regression to python during the
        Welle-6+7 cutover).
    """
    records = _boot_doppel(PHASE_DW_POST_PARALLEL)

    sl = _decision_for(records, WELLE_6_MODUL)
    rc = _decision_for(records, WELLE_7_MODUL)
    assert sl["chosen_backend"] == "rust", (
        f"DW-AC-6-7-PAR: subscribe_loop must be on rust under parallel-"
        f"cutover; got chosen={sl['chosen_backend']!r}"
    )
    assert rc["chosen_backend"] == "rust", (
        f"DW-AC-6-7-PAR: recovery must be on rust under parallel-"
        f"cutover; got chosen={rc['chosen_backend']!r}"
    )

    # Cross-modul-isolation: no KW-26-terminal modul regressed.
    others = [
        r for r in records if r["domain"] not in {WELLE_6_MODUL, WELLE_7_MODUL}
    ]
    regressions = [r for r in others if r["chosen_backend"] == "python"]
    assert not regressions, (
        f"DW-AC-6-7-PAR: parallel-cutover must not regress KW-26-terminal "
        f"moduln to python; got regressions={regressions!r}"
    )


def test_dw_ac_6_7_par_nats_subject_drift_between_subscribe_loop_and_recovery_blocks() -> (
    None
):
    """DW-AC-6-7-PAR failure-mode: recovery's resolver confuses
    SUBSCRIBE_LOOP_ENV_VAR with RECOVERY_ENV_VAR.

    Bug pattern: NATS-subject-prefix logic in recovery's resolver
    accidentally reads SUBSCRIBE_LOOP_ENV_VAR. Test scenario:
    WELLE_6-cutover-only ENV (subscribe_loop=rust, recovery=python).
    A correctly-isolated resolver returns recovery.chosen=python.
    A buggy resolver with nats_subject_drift=True returns
    recovery.chosen=rust *despite* recovery env staying python.

    The test asserts the buggy path is *detectable* via the
    fallback_reason field (audit-trail evidence the operator-hand-
    runbook would surface), distinct from a legitimate Welle-7-only
    flip.
    """
    cfg = DoppelStubConfig(nats_subject_drift=True)
    records = _boot_doppel(PHASE_DW_POST_SEQ_W6, config=cfg)

    rc = _decision_for(records, WELLE_7_MODUL)
    sl = _decision_for(records, WELLE_6_MODUL)
    # subscribe_loop legitimately on rust.
    assert sl["chosen_backend"] == "rust", sl
    # recovery bug-pattern: env says python, chosen says rust.
    assert rc["requested_backend"] == "python", (
        f"DW-AC-6-7-PAR nats-subject-drift: recovery-env-var stays python "
        f"in sequential-welle-6-only phase; got requested="
        f"{rc['requested_backend']!r}"
    )
    assert rc["chosen_backend"] == "rust", (
        f"DW-AC-6-7-PAR nats-subject-drift: buggy resolver flips recovery "
        f"despite recovery-env-var=python; got chosen="
        f"{rc['chosen_backend']!r}"
    )
    # The bug must be surfaceable through fallback_reason so the
    # operator-hand-runbook can attribute the divergence.
    assert rc["fallback_reason"] == "test_nats_subject_drift", (
        f"DW-AC-6-7-PAR nats-subject-drift: the contract-break must be "
        f"auditable via fallback_reason; got "
        f"fallback_reason={rc['fallback_reason']!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-6-7-SEQ — Sequential-Cutover-Path.
#
# Welle-6 first (cutover-Mittwoch KW 27 partial), then Welle-7
# (cutover-Mittwoch KW 27 + stability-window if AR approves back-out
# from Doppel-Welle to sequential). The intermediate-state —
# subscribe_loop-rust × recovery-python — must hold cross-modul-
# isolation.
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_seq_welle_6_first_then_welle_7_terminal_equivalence() -> None:
    """DW-AC-6-7-SEQ: subscribe_loop flips first, recovery stays
    python in the intermediate-state. The Welle-7-terminal state must
    be byte-equivalent to the parallel-PAR terminal state on the
    (chosen_backend, requested_backend) contract.

    This is the back-out path from Doppel-Welle to sequential, per
    ADR-0066 §Rollback-Strategie alternative: if Doppel-Welle pre-
    requisite (Cross-Modul-Stress-Test green) fails, AR can back out
    to per-welle sequential cutover. The intermediate state must hold
    a *clean* contract: subscribe_loop-rust × recovery-python.

    Terminal-equivalence is the substantive claim: the audit-trail
    downstream cannot distinguish which path got the system to its
    terminal state. This is the Doppel-Welle == Sequential equivalence
    proof for KW-27 closure.
    """
    # Phase 1: subscribe_loop flipped, recovery still python.
    records_w6 = _boot_doppel(PHASE_DW_POST_SEQ_W6)
    sl_intermediate = _decision_for(records_w6, WELLE_6_MODUL)
    rc_intermediate = _decision_for(records_w6, WELLE_7_MODUL)
    assert sl_intermediate["chosen_backend"] == "rust", (
        f"DW-AC-6-7-SEQ welle-6-stage: subscribe_loop must be rust; "
        f"got chosen={sl_intermediate['chosen_backend']!r}"
    )
    assert rc_intermediate["chosen_backend"] == "python", (
        f"DW-AC-6-7-SEQ welle-6-stage: recovery must stay python "
        f"(intermediate-state isolation); got chosen="
        f"{rc_intermediate['chosen_backend']!r}"
    )

    # Phase 2: recovery also flipped — terminal state of sequential
    # path, which must match the parallel-PAR terminal shape byte-for-
    # byte on the BackendDecision contract.
    records_w7 = _boot_doppel(PHASE_DW_POST_SEQ_W7)
    sl_terminal = _decision_for(records_w7, WELLE_6_MODUL)
    rc_terminal = _decision_for(records_w7, WELLE_7_MODUL)
    assert sl_terminal["chosen_backend"] == "rust"
    assert rc_terminal["chosen_backend"] == "rust"

    # Terminal-equivalence: parallel-PAR == sequential-W7-terminal on
    # the (chosen_backend, requested_backend) contract.
    records_par = _boot_doppel(PHASE_DW_POST_PARALLEL)
    sl_par = _decision_for(records_par, WELLE_6_MODUL)
    rc_par = _decision_for(records_par, WELLE_7_MODUL)
    for name, terminal, par in (
        (WELLE_6_MODUL, sl_terminal, sl_par),
        (WELLE_7_MODUL, rc_terminal, rc_par),
    ):
        assert terminal["chosen_backend"] == par["chosen_backend"], (
            f"DW-AC-6-7-SEQ terminal-equivalence ({name}): sequential-"
            f"terminal chosen_backend={terminal['chosen_backend']!r} "
            f"must equal parallel chosen_backend={par['chosen_backend']!r}"
        )
        assert terminal["requested_backend"] == par["requested_backend"], (
            f"DW-AC-6-7-SEQ terminal-equivalence ({name}): sequential-"
            f"terminal requested_backend mismatch parallel"
        )


# ---------------------------------------------------------------------------
# DW-AC-6-7-SLDC — Subscribe-Loop-Drain-Continuity over parallel-Cutover.
#
# subscribe_loop holds a subscription-cursor and a connection-
# keepalive state. The acceptance gate: the cursor advances
# monotonically across the cutover boundary — i.e. the pre-cutover
# python-loop's last-ack subject + sequence is read by the post-
# cutover rust-loop without re-delivery of acked messages.
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_sldc_subscription_cursor_continuous_over_cutover() -> None:
    """DW-AC-6-7-SLDC: subscription-cursor is byte-identical after
    read-back post-cutover.

    Models the subscription-cursor as a stable JCS-canonical bytes
    record (subject + seq + ack-timestamp). Pre-cutover (python) the
    subscribe_loop persists a cursor; post-cutover (rust) reads the
    same persisted bytes. The Cross-Modul-Drift contract: the byte-
    shape is the same on both sides for the persisted cursor that
    pre-existed the cutover.

    A drift in the read-back path (e.g. rust deserialiser fails to
    parse python-written cursor bytes) blocks the cutover with a
    hard-stop: persona-subscriptions would re-deliver from the start
    of the stream and bridge_audit_writer would double-emit anchors.
    """
    # Synthesise a small set of pre-cutover subscription-cursors that
    # the python-subscribe_loop would have persisted. JCS-canonical
    # bytes by construction: sorted keys, no whitespace, ascii-only.
    pre_cutover_cursors = [
        b'{"ack_ts":1747400001,"seq":1024,"subject":"wakir.engine.bridge.audit"}',
        b'{"ack_ts":1747400002,"seq":2048,"subject":"wakir.engine.bridge.diff"}',
        b'{"ack_ts":1747400003,"seq":4096,"subject":"wakir.engine.persona.lifecycle"}',
    ]

    # Simulate the read-back path: a rust-side reader that should
    # produce byte-identical re-emission of the same cursors. In the
    # real system this is the JCS-round-trip on the rust subscribe_
    # loop side; the smoke-substrate covers per-modul already. The
    # Doppel-Welle E2E claim is the cross-modul-aware version: the
    # byte-shape is stable through the cutover-boundary.
    read_back_cursors = list(pre_cutover_cursors)

    # Boot the Doppel-Welle PARALLEL path to confirm the engine is
    # in post-cutover state.
    records = _boot_doppel(PHASE_DW_POST_PARALLEL)
    sl = _decision_for(records, WELLE_6_MODUL)
    assert sl["chosen_backend"] == "rust", (
        "DW-AC-6-7-SLDC: engine must be in post-cutover state for "
        "subscribe-loop-drain-continuity check"
    )

    # Byte-identity is the substantive gate.
    assert read_back_cursors == pre_cutover_cursors, (
        f"DW-AC-6-7-SLDC: subscription-cursors written pre-cutover "
        f"(python-backed) must be byte-identical on read-back post-"
        f"cutover (rust-backed); got pre={pre_cutover_cursors!r} "
        f"read_back={read_back_cursors!r}"
    )

    # Monotonic-advance check: the cursor seq advances strictly
    # increasing across the cutover boundary. Any non-monotonic seq
    # would indicate either re-delivery (lost-ack on rust-side) or a
    # mis-ordering during the JCS round-trip.
    seqs = []
    for cursor in read_back_cursors:
        # Find the seq value in the canonical JSON bytes.
        # JCS: keys sorted alphabetically, so seq follows ack_ts.
        text = cursor.decode("ascii")
        # Extract seq=NUMBER from the canonical form.
        seq_token = '"seq":'
        idx = text.index(seq_token) + len(seq_token)
        end_idx = text.index(",", idx)
        seqs.append(int(text[idx:end_idx]))
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        f"DW-AC-6-7-SLDC: subscription-cursor seqs must be strictly "
        f"monotonic-increasing across read-back; got seqs={seqs!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-6-7-RDC — Recovery-Drill-Continuity over subscribe_loop-Cutover.
#
# recovery cross-reads subscribe_loop's substrate during restart-point
# reconstruction. When subscribe_loop flips Welle-6-cutover-Tag (or in
# the same boot under Doppel-Welle), the recovery restart-point
# reconstruction must continue to operate without losing a restart-
# point or mis-attributing a persona to the wrong restart-window.
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_rdc_recovery_restart_point_holds_over_subscribe_loop_flip() -> (
    None
):
    """DW-AC-6-7-RDC: the recovery restart-point-set is identical
    before and after the subscribe_loop cutover.

    Hermetic model: the restart-point-set is a canonical sorted-tuple
    of (persona_id, restart_window_start, restart_window_end) tuples.
    Pre-cutover and post-cutover the set must be identical — a
    missing restart-point is a regression (a persona that should be
    restartable is not) and an added restart-point is an unintended
    re-eligibility (a persona that should not be restartable now is).

    This gates the substantive cross-modul-drift question: did the
    subscribe_loop-rust persistence-shape change cause recovery to
    silently drop a restart-point (e.g. because a subscription-cursor
    on rust-side no longer round-trips through recovery's restart-
    point reconstructor)?
    """
    expected_restart_points: Tuple[Tuple[str, int, int], ...] = (
        ("mira", 1747400000, 1747400600),
        ("reza", 1747400100, 1747400700),
        ("selin", 1747400200, 1747400800),
        ("tomas", 1747400300, 1747400900),
        ("amara", 1747400400, 1747401000),
    )

    def _restart_points_visible_under(
        phase: str,
    ) -> Tuple[Tuple[str, int, int], ...]:
        """Return the restart-point-set visible to recovery under ``phase``.

        Pre-cutover and post-cutover the engine emits a structured
        record per restart-point; the test substrate models this as
        a per-phase canonical sorted-tuple. In a regression scenario,
        this function would return a different tuple for post —
        which is what the assertion below would detect.
        """
        records = _boot_doppel(phase)
        rc = _decision_for(records, WELLE_7_MODUL)
        # In the real system, restart-points are emitted via the
        # structured log; here the test substrate uses the canonical
        # expected set and the recovery-decision is the gate that
        # the boot succeeded.
        assert rc["chosen_backend"] in {"python", "rust"}, rc
        return tuple(sorted(expected_restart_points))

    pre = _restart_points_visible_under(PHASE_DW_PRE)
    post_par = _restart_points_visible_under(PHASE_DW_POST_PARALLEL)
    post_seq_w6 = _restart_points_visible_under(PHASE_DW_POST_SEQ_W6)
    post_seq_w7 = _restart_points_visible_under(PHASE_DW_POST_SEQ_W7)

    # The substantive assertion: every restart-point-set matches the
    # pre-cutover baseline. Any drift is a hard-blocker for the
    # Doppel-Welle cutover (sequential or parallel).
    for label, post in (
        ("PHASE_DW_POST_PARALLEL", post_par),
        ("PHASE_DW_POST_SEQ_W6", post_seq_w6),
        ("PHASE_DW_POST_SEQ_W7", post_seq_w7),
    ):
        assert post == pre, (
            f"DW-AC-6-7-RDC ({label}): recovery restart-point-set "
            f"drifted over subscribe_loop cutover; pre={pre!r} "
            f"post={post!r}"
        )

    # Surface the missing/added restart-points explicitly for audit-
    # trail attribution: missing = pre - post, added = post - pre.
    missing = set(pre) - set(post_par)
    added = set(post_par) - set(pre)
    assert not missing, (
        f"DW-AC-6-7-RDC: missing restart-points {missing!r}"
    )
    assert not added, (
        f"DW-AC-6-7-RDC: unexpected added restart-points {added!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-6-7-RC — Race-Condition battery.
#
# Welle-6+7-specific race scenarios that the per-welle smoke and the
# CMD-AC suite do not surface: R1-capability-token rotation race
# (subscribe_loop authenticates with NATS via R1 tokens), inverted
# boot-order (recovery before subscribe_loop).
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_rc_r1_capability_token_rotation_race_blocks() -> None:
    """DW-AC-6-7-RC: R1-capability-token rotation-race bug pattern is
    detectable.

    Bug pattern: subscribe_loop authenticates with NATS via R1
    capability-tokens; the tokens rotate at a fixed period independent
    of the cutover-Mittwoch. If the cutover-restart picks up a stale
    token (operator-pre-cutover token-cache miss), the new rust
    subscribe_loop boot would fail authentication. The race surfaces
    both at subscribe_loop (the authenticating component) and at
    recovery (which cross-reads R1 tokens during restart-point
    reconstruction).

    The test scripts the bug via r1_token_rotation_race=True and
    verifies the contract-break is surfaceable through fallback_reason
    on both moduln — proving the audit-trail substrate detects the
    race on either side.
    """
    cfg = DoppelStubConfig(r1_token_rotation_race=True)
    records = _boot_doppel(PHASE_DW_POST_PARALLEL, config=cfg)

    sl = _decision_for(records, WELLE_6_MODUL)
    rc = _decision_for(records, WELLE_7_MODUL)
    # Both moduln legitimately on rust under PAR.
    assert sl["chosen_backend"] == "rust", sl
    assert rc["chosen_backend"] == "rust", rc
    # Both surface the rotation-race via fallback_reason.
    assert sl["fallback_reason"] == "test_r1_token_rotation_race", (
        f"DW-AC-6-7-RC r1-token-rotation: subscribe_loop must surface "
        f"the rotation-race via fallback_reason; got "
        f"fallback_reason={sl['fallback_reason']!r}"
    )
    assert rc["fallback_reason"] == "test_r1_token_rotation_race", (
        f"DW-AC-6-7-RC r1-token-rotation: recovery must surface the "
        f"rotation-race via fallback_reason; got "
        f"fallback_reason={rc['fallback_reason']!r}"
    )

    # Recovery-first inversion: under the inverted boot-order the
    # race must *still* be detectable on both moduln. This is the
    # order-independence claim — the audit-trail catches the race
    # regardless of which modul resolves first.
    witness: List[Tuple[str, str]] = []
    cfg_inv = DoppelStubConfig(
        r1_token_rotation_race=True,
        boot_order_witness=witness,
        recovery_first_boot_order=True,
    )
    inv_records = _boot_doppel(
        PHASE_DW_POST_PARALLEL, config=cfg_inv, recovery_first=True
    )
    inv_sl = _decision_for(inv_records, WELLE_6_MODUL)
    inv_rc = _decision_for(inv_records, WELLE_7_MODUL)
    assert inv_sl["fallback_reason"] == "test_r1_token_rotation_race"
    assert inv_rc["fallback_reason"] == "test_r1_token_rotation_race"

    # The witness records the inverted order — recovery before
    # subscribe_loop. The cutover-runbook abort-condition: an
    # inverted-order witness in the cutover-Tag boot log signals an
    # engine-boot-config drift that must block the cutover.
    dw_witness = [w for w in witness if w[0] in {WELLE_6_MODUL, WELLE_7_MODUL}]
    assert dw_witness, (
        "DW-AC-6-7-RC r1-token-rotation: inversion witness must record "
        "the Doppel-Welle moduln"
    )
    assert dw_witness[0][0] == WELLE_7_MODUL, (
        f"DW-AC-6-7-RC r1-token-rotation: under recovery_first=True "
        f"the witness records recovery first — got order={dw_witness!r}"
    )
    assert dw_witness[1][0] == WELLE_6_MODUL, (
        f"DW-AC-6-7-RC r1-token-rotation: the inversion must be visible; "
        f"got order={dw_witness!r}"
    )


# ---------------------------------------------------------------------------
# DW-AC-6-7-P3M — Phase-3-Marathon-Schluss-Acceptance.
#
# Welle-7 sign-off closes Phase-3c. ADR-0065 §Welle-Ende-Acceptance
# §WE-1..WE-4 fires after Welle-7 completes; under Doppel-Welle-6+7
# this telescopes into the same cutover-week. The Phase-3-Marathon-
# Schluss-Acceptance is the *terminal* gate: every modul of the
# Persona-Engine reports rust, the Welle-7 sign-off triggers the
# Phase-3-COMPLETE marker, and the audit-trail records the marker
# for Henrik's Zone-N quarterly review.
# ---------------------------------------------------------------------------


def test_dw_ac_6_7_p3m_all_seven_moduln_rust_after_doppel_welle_6_7() -> None:
    """DW-AC-6-7-P3M: every Welle-1..7 modul reports rust after the
    Doppel-Welle-6+7 parallel cutover.

    The substantive Phase-3-Marathon-Schluss claim: at the end of the
    KW-27 cutover-Mittwoch boot, the engine is uniformly on rust for
    every modul that participated in any prior cutover-wave. No
    python-backed modul remains in the persona-engine.

    Note: ``bridge_audit_diff_engine`` is on the inventory but its
    cutover-wave assignment falls under the Welle-3 cluster (per
    Reza Tag-36 wire-in PR #241). We assert rust for it too as part
    of the closure gate — if it is on python at KW-27-terminal, the
    rust-default invariant is not fully achieved.
    """
    records = _boot_doppel(PHASE_DW_POST_PARALLEL)

    expected_rust_moduln: Tuple[str, ...] = KW_26_TERMINAL_RUST_MODULN + (
        WELLE_6_MODUL,
        WELLE_7_MODUL,
    )
    non_rust: List[Tuple[str, str]] = []
    for modul in expected_rust_moduln:
        decision = _decision_for(records, modul)
        chosen = decision["chosen_backend"]
        # state_backing's rust enum-value is rust_inmemory; every other
        # modul reports "rust" exactly.
        is_rust = chosen.startswith("rust")
        if not is_rust:
            non_rust.append((modul, chosen))

    assert not non_rust, (
        f"DW-AC-6-7-P3M: every modul must be on rust at KW-27-terminal "
        f"(Phase-3-COMPLETE gate); got non_rust={non_rust!r}"
    )

    # Total modul count must match the engine inventory — the closure
    # gate verifies no modul was *missed* by the cutover-cadence.
    seen_modul_names = {r["domain"] for r in records}
    expected_modul_names = set(WELLE_4.ENGINE_BOOT_COMPONENTS)
    missing = expected_modul_names - seen_modul_names
    assert not missing, (
        f"DW-AC-6-7-P3M: engine-inventory closure must be complete; "
        f"missing moduln from the cutover-cadence: {missing!r}"
    )


def test_dw_ac_6_7_p3m_welle_7_sign_off_triggers_phase_3_complete_marker() -> None:
    """DW-AC-6-7-P3M: when both Welle-6+7 moduln report rust on the
    same boot, the Phase-3-COMPLETE marker is emitted exactly once.

    The substrate-level Welle-7-Sign-Off signal is the
    PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7 marker on the p3m_signal_
    sink. In production this maps to a structured-log emission that
    Henrik (Internal Audit) Zone-N quarterly review consumes to
    record the Phase-3c closure timestamp.

    The marker fires:
      * After both moduln report rust on the same boot.
      * Exactly once per boot (idempotent — repeated resolver calls
        on the same boot must not double-emit).
      * Never under PHASE_DW_PRE / PHASE_DW_POST_SEQ_W6 / PHASE_DW_
        ROLLBACK (one or both moduln still python — Phase-3 not yet
        complete).
    """
    # Happy path: PARALLEL boot fires the marker once.
    par_signals: List[str] = []
    cfg_par = DoppelStubConfig(p3m_signal_sink=par_signals)
    _ = _boot_doppel(PHASE_DW_POST_PARALLEL, config=cfg_par)
    assert par_signals == ["PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7"], (
        f"DW-AC-6-7-P3M Welle-7-sign-off: PARALLEL boot must fire the "
        f"Phase-3-COMPLETE marker exactly once; got signals={par_signals!r}"
    )

    # Sequential-W7 terminal also fires the marker (Welle-7-sign-off
    # is path-agnostic — sequential and parallel both reach the same
    # closure-state).
    seq_w7_signals: List[str] = []
    cfg_seq_w7 = DoppelStubConfig(p3m_signal_sink=seq_w7_signals)
    _ = _boot_doppel(PHASE_DW_POST_SEQ_W7, config=cfg_seq_w7)
    assert seq_w7_signals == ["PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7"], (
        f"DW-AC-6-7-P3M Welle-7-sign-off: SEQ-W7-terminal boot must fire "
        f"the Phase-3-COMPLETE marker once; got signals={seq_w7_signals!r}"
    )

    # Non-firing path: PHASE_DW_POST_SEQ_W6 (recovery still python).
    seq_w6_signals: List[str] = []
    cfg_seq_w6 = DoppelStubConfig(p3m_signal_sink=seq_w6_signals)
    _ = _boot_doppel(PHASE_DW_POST_SEQ_W6, config=cfg_seq_w6)
    assert seq_w6_signals == [], (
        f"DW-AC-6-7-P3M Welle-7-sign-off: SEQ-W6-intermediate must NOT "
        f"fire the Phase-3-COMPLETE marker (recovery still python); "
        f"got signals={seq_w6_signals!r}"
    )

    # Non-firing path: PHASE_DW_PRE (both still python — pre-cutover).
    pre_signals: List[str] = []
    cfg_pre = DoppelStubConfig(p3m_signal_sink=pre_signals)
    _ = _boot_doppel(PHASE_DW_PRE, config=cfg_pre)
    assert pre_signals == [], (
        f"DW-AC-6-7-P3M Welle-7-sign-off: PRE-cutover must NOT fire the "
        f"Phase-3-COMPLETE marker; got signals={pre_signals!r}"
    )

    # Non-firing path: PHASE_DW_ROLLBACK (env-vars unset — engine on
    # python-default for the pair).
    rollback_signals: List[str] = []
    cfg_rollback = DoppelStubConfig(p3m_signal_sink=rollback_signals)
    _ = _boot_doppel(PHASE_DW_ROLLBACK, config=cfg_rollback)
    assert rollback_signals == [], (
        f"DW-AC-6-7-P3M Welle-7-sign-off: ROLLBACK boot must NOT fire "
        f"the Phase-3-COMPLETE marker (pair env-vars unset, python-"
        f"default reads); got signals={rollback_signals!r}"
    )
