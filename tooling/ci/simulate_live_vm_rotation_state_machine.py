#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Sandbox-Stub Simulator for the Live-VM Rotation Plan
(0.5.1 -> 0.5.2 -> 0.5.3-rc1).

OPEN-J2 (Tag-56 reverse map): the live-VM rotation 0.5.1 -> 0.5.2 /
0.5.3-rc1 itself cannot run inside the hermetic CI substrate because
the rotation drives an actual VM lifecycle (snapshot, image swap,
quadlet reload, post-rotation acceptance probe). It stays Operator-
Hand by construction.

What we **can** validate hermetically is the **state-machine** that
governs the rotation plan: the set of entry states, the legal
transitions between them, the recovery paths from every failure
state, and the decision-points the operator companion uses to pick
the next transition. That state-machine is a deterministic graph and
can be exercised exhaustively in pure Python with no VM runtime.

This simulator models exactly that. It is intentionally:

* **Stub-only**. No subprocess, no podman, no qemu, no network. The
  word ``simulate`` in the filename is load-bearing - there is no
  real rotation behind this code path.
* **State-machine-deterministic**. The transition table is a pure
  function ``(state, event) -> next_state``. The set of legal events
  per state is fixed up front.
* **Recovery-path-complete**. Every failure state in the table has
  at least one transition back into a healthy state (``DRAINED`` or
  ``ROTATION_COMMITTED_v0_5_3_rc1``); the test suite asserts this
  graph-property holds.

The Sandbox-Boundary is **hard**. The simulator never claims that a
successful state-machine run implies a successful Live-VM rotation -
it only proves the *plan* the operator companion will execute is
internally consistent and recoverable. The actual rotation remains
Operator-Hand (see ADR-0042 Live-VM Acceptance, ADR-0058 Operator-
Hand SOP).

Schema (v1)
-----------

Each simulator run emits a JSON envelope::

    {
      "schema_version": "live-vm-rotation-state-machine.v1",
      "from_version": "0.5.1",
      "via_version": "0.5.2",
      "to_version":  "0.5.3-rc1",
      "entry_state": "PRE_FLIGHT_CHECKS",
      "trace": [
        {"state": "PRE_FLIGHT_CHECKS", "event": "checks_pass",
         "next": "SNAPSHOT_CREATED"},
        ...
      ],
      "final_state": "ROTATION_COMMITTED_v0_5_3_rc1",
      "verdict": "ROTATION-STATE-MACHINE-INTACT",
      "states_visited": 10,
      "recovery_paths_terminate": true
    }

Verdict rule
------------

* ``ROTATION-STATE-MACHINE-INTACT`` - the simulator reached
  ``ROTATION_COMMITTED_v0_5_3_rc1`` or ``DRAINED`` (the two terminal
  healthy states) from every requested entry state, **and** every
  recovery path from every failure state terminates in at most
  ``MAX_TRANSITIONS`` steps without cycling.

* ``DRIFT`` - any requested entry state failed to terminate, **or**
  any recovery path cycled, **or** a transition was attempted for an
  ``(state, event)`` pair not in the transition table.

CLI
---

::

    python3 tooling/ci/simulate_live_vm_rotation_state_machine.py \\
        --entry-state PRE_FLIGHT_CHECKS \\
        --strategy happy_path \\
        --out artifacts/sm-trace.json

    python3 tooling/ci/simulate_live_vm_rotation_state_machine.py \\
        --all-entry-states \\
        --strategy recovery \\
        --out artifacts/sm-recovery-trace.json

The exit code is ``0`` on ``ROTATION-STATE-MACHINE-INTACT`` and ``2``
on ``DRIFT``. ``--help`` is supported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# State-machine definition
# ---------------------------------------------------------------------------

# Two terminal healthy states. Reaching either of these is a successful
# rotation-plan outcome:
#
#   * ROTATION_COMMITTED_v0_5_3_rc1: full rotation 0.5.1 -> 0.5.3-rc1
#     completed and acceptance gate passed.
#   * DRAINED: rotation aborted cleanly. The VM is back on 0.5.1, no
#     in-flight requests dropped, and the operator chose not to
#     retry.
TERMINAL_HEALTHY = frozenset(
    {"ROTATION_COMMITTED_v0_5_3_rc1", "DRAINED"}
)

# All 12 states the rotation plan can be in. Ten are non-terminal,
# two are terminal-healthy. (The requirement is "10+ states" - we
# carry 12 including the two terminals.)
STATES = (
    "PRE_FLIGHT_CHECKS",
    "SNAPSHOT_CREATED",
    "IMAGE_SWAP_0_5_2",
    "QUADLET_RELOAD_0_5_2",
    "ACCEPTANCE_PROBE_0_5_2",
    "STABILIZED_AT_0_5_2",
    "IMAGE_SWAP_0_5_3_rc1",
    "QUADLET_RELOAD_0_5_3_rc1",
    "ACCEPTANCE_PROBE_0_5_3_rc1",
    "ROTATION_COMMITTED_v0_5_3_rc1",
    "ROLLBACK_IN_PROGRESS",
    "DRAINED",
)

# Failure states are the non-terminal states from which the operator
# may choose to fall back via ROLLBACK_IN_PROGRESS. Every failure
# state must have a transition leading (eventually) into a terminal
# healthy state; the test suite asserts this.
FAILURE_STATES = frozenset(
    {
        "PRE_FLIGHT_CHECKS",
        "SNAPSHOT_CREATED",
        "IMAGE_SWAP_0_5_2",
        "QUADLET_RELOAD_0_5_2",
        "ACCEPTANCE_PROBE_0_5_2",
        "STABILIZED_AT_0_5_2",
        "IMAGE_SWAP_0_5_3_rc1",
        "QUADLET_RELOAD_0_5_3_rc1",
        "ACCEPTANCE_PROBE_0_5_3_rc1",
        "ROLLBACK_IN_PROGRESS",
    }
)

# Transition table. Each entry maps (state, event) -> next_state.
# Every failure state has at least one event that routes into
# ROLLBACK_IN_PROGRESS, and ROLLBACK_IN_PROGRESS itself routes to
# DRAINED. This guarantees the recovery-path-completeness property.
TRANSITIONS: dict[tuple[str, str], str] = {
    # Pre-flight branch.
    ("PRE_FLIGHT_CHECKS", "checks_pass"): "SNAPSHOT_CREATED",
    ("PRE_FLIGHT_CHECKS", "checks_fail"): "ROLLBACK_IN_PROGRESS",
    # Snapshot branch.
    ("SNAPSHOT_CREATED", "snapshot_ok"): "IMAGE_SWAP_0_5_2",
    ("SNAPSHOT_CREATED", "snapshot_fail"): "ROLLBACK_IN_PROGRESS",
    # 0.5.2 swap branch.
    ("IMAGE_SWAP_0_5_2", "swap_ok"): "QUADLET_RELOAD_0_5_2",
    ("IMAGE_SWAP_0_5_2", "swap_fail"): "ROLLBACK_IN_PROGRESS",
    # 0.5.2 quadlet reload.
    ("QUADLET_RELOAD_0_5_2", "reload_ok"): "ACCEPTANCE_PROBE_0_5_2",
    ("QUADLET_RELOAD_0_5_2", "reload_fail"): "ROLLBACK_IN_PROGRESS",
    # 0.5.2 acceptance probe.
    ("ACCEPTANCE_PROBE_0_5_2", "probe_ok"): "STABILIZED_AT_0_5_2",
    ("ACCEPTANCE_PROBE_0_5_2", "probe_fail"): "ROLLBACK_IN_PROGRESS",
    # Stabilization decision-point.
    ("STABILIZED_AT_0_5_2", "advance"): "IMAGE_SWAP_0_5_3_rc1",
    ("STABILIZED_AT_0_5_2", "hold"): "ROLLBACK_IN_PROGRESS",
    # 0.5.3-rc1 swap.
    ("IMAGE_SWAP_0_5_3_rc1", "swap_ok"): "QUADLET_RELOAD_0_5_3_rc1",
    ("IMAGE_SWAP_0_5_3_rc1", "swap_fail"): "ROLLBACK_IN_PROGRESS",
    # 0.5.3-rc1 reload.
    ("QUADLET_RELOAD_0_5_3_rc1", "reload_ok"): "ACCEPTANCE_PROBE_0_5_3_rc1",
    ("QUADLET_RELOAD_0_5_3_rc1", "reload_fail"): "ROLLBACK_IN_PROGRESS",
    # 0.5.3-rc1 acceptance probe.
    (
        "ACCEPTANCE_PROBE_0_5_3_rc1",
        "probe_ok",
    ): "ROTATION_COMMITTED_v0_5_3_rc1",
    (
        "ACCEPTANCE_PROBE_0_5_3_rc1",
        "probe_fail",
    ): "ROLLBACK_IN_PROGRESS",
    # Rollback always terminates in DRAINED.
    ("ROLLBACK_IN_PROGRESS", "drain_ok"): "DRAINED",
}

ENTRY_STATES = (
    "PRE_FLIGHT_CHECKS",
    "SNAPSHOT_CREATED",
    "IMAGE_SWAP_0_5_2",
    "QUADLET_RELOAD_0_5_2",
    "ACCEPTANCE_PROBE_0_5_2",
    "STABILIZED_AT_0_5_2",
    "IMAGE_SWAP_0_5_3_rc1",
    "QUADLET_RELOAD_0_5_3_rc1",
    "ACCEPTANCE_PROBE_0_5_3_rc1",
    "ROLLBACK_IN_PROGRESS",
)

# Strategy = which event is picked when several are legal. The
# operator companion always picks one - this just makes the simulator
# deterministic for testing.
STRATEGIES = ("happy_path", "recovery")

HAPPY_EVENTS = {
    "checks_pass",
    "snapshot_ok",
    "swap_ok",
    "reload_ok",
    "probe_ok",
    "advance",
    "drain_ok",
}

RECOVERY_EVENTS = {
    "checks_fail",
    "snapshot_fail",
    "swap_fail",
    "reload_fail",
    "probe_fail",
    "hold",
    "drain_ok",
}

# Safety bound for cycle detection. The longest legal trace through
# the graph is < 15 transitions; anything beyond is treated as a
# DRIFT signal.
MAX_TRANSITIONS = 32

SCHEMA_VERSION = "live-vm-rotation-state-machine.v1"


# ---------------------------------------------------------------------------
# Simulator core
# ---------------------------------------------------------------------------


def legal_events(state: str) -> tuple[str, ...]:
    """Return the tuple of events legal in ``state`` in alphabetical
    order. Used by the operator-companion doc and by the test suite.
    """
    out = sorted(ev for (s, ev) in TRANSITIONS if s == state)
    return tuple(out)


def pick_event(state: str, strategy: str) -> str | None:
    """Pick the event to fire next given ``strategy``.

    Returns ``None`` if ``state`` is terminal (no legal events).
    Raises ``ValueError`` for an unknown strategy.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}")
    events = legal_events(state)
    if not events:
        return None
    pool = HAPPY_EVENTS if strategy == "happy_path" else RECOVERY_EVENTS
    for ev in events:
        if ev in pool:
            return ev
    # Strategy-mismatch fallback: if no event matches the strategy
    # pool (e.g. ROLLBACK_IN_PROGRESS has only ``drain_ok``), pick
    # the first legal event. drain_ok is in both pools so this
    # branch is exercised only on terminal recovery hops.
    return events[0]


def simulate(
    entry_state: str,
    strategy: str = "happy_path",
    max_transitions: int = MAX_TRANSITIONS,
) -> dict:
    """Run a single state-machine simulation from ``entry_state``.

    Returns the trace envelope dict (schema v1).
    Never raises on a known failure state; instead encodes ``DRIFT``
    in the verdict so a single drifted entry-state cannot crash the
    whole batch run.
    """
    if entry_state not in STATES:
        return _drift(entry_state, reason=f"unknown entry-state: {entry_state}")
    if strategy not in STRATEGIES:
        return _drift(
            entry_state, reason=f"unknown strategy: {strategy}"
        )

    trace: list[dict] = []
    visited: set[str] = set()
    state = entry_state
    visited.add(state)

    for _ in range(max_transitions):
        if state in TERMINAL_HEALTHY:
            break
        event = pick_event(state, strategy)
        if event is None:
            return _drift(
                entry_state,
                reason=f"no legal event in non-terminal state {state}",
                trace=trace,
            )
        key = (state, event)
        if key not in TRANSITIONS:
            return _drift(
                entry_state,
                reason=f"transition {key} not in table",
                trace=trace,
            )
        next_state = TRANSITIONS[key]
        trace.append(
            {"state": state, "event": event, "next": next_state}
        )
        state = next_state
        # Cycle = re-entry into an already-visited state. With the
        # current table no cycle is possible; the check is a guard
        # against future drift in the table itself.
        if state in visited and state not in TERMINAL_HEALTHY:
            return _drift(
                entry_state,
                reason=f"cycle detected at state {state}",
                trace=trace,
            )
        visited.add(state)

    if state not in TERMINAL_HEALTHY:
        return _drift(
            entry_state,
            reason=(
                f"max_transitions={max_transitions} exhausted at "
                f"state {state}"
            ),
            trace=trace,
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "from_version": "0.5.1",
        "via_version": "0.5.2",
        "to_version": "0.5.3-rc1",
        "entry_state": entry_state,
        "strategy": strategy,
        "trace": trace,
        "final_state": state,
        "verdict": "ROTATION-STATE-MACHINE-INTACT",
        "states_visited": len(visited),
        "recovery_paths_terminate": True,
    }


def _drift(
    entry_state: str,
    reason: str,
    trace: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "from_version": "0.5.1",
        "via_version": "0.5.2",
        "to_version": "0.5.3-rc1",
        "entry_state": entry_state,
        "strategy": None,
        "trace": trace or [],
        "final_state": None,
        "verdict": "DRIFT",
        "drift_reason": reason,
        "states_visited": len({entry_state}) if entry_state in STATES else 0,
        "recovery_paths_terminate": False,
    }


def simulate_all_entry_states(strategy: str = "happy_path") -> dict:
    """Run ``simulate`` from every entry-state and aggregate verdicts.

    The aggregate verdict is ``ROTATION-STATE-MACHINE-INTACT`` only if
    every per-entry-state run carries that verdict.
    """
    per_entry: list[dict] = []
    overall = "ROTATION-STATE-MACHINE-INTACT"
    for entry in ENTRY_STATES:
        env = simulate(entry, strategy=strategy)
        per_entry.append(env)
        if env["verdict"] != "ROTATION-STATE-MACHINE-INTACT":
            overall = "DRIFT"
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": strategy,
        "entry_state_count": len(ENTRY_STATES),
        "per_entry": per_entry,
        "verdict": overall,
    }


def verify_recovery_paths_terminate() -> dict:
    """Graph-property check: from every failure state, the recovery
    strategy reaches a terminal healthy state in <= MAX_TRANSITIONS.

    This is what the workflow's Stage 2 calls. Returns an envelope
    with a verdict.
    """
    failures: list[dict] = []
    for entry in sorted(FAILURE_STATES):
        env = simulate(entry, strategy="recovery")
        if env["verdict"] != "ROTATION-STATE-MACHINE-INTACT":
            failures.append(env)
            continue
        if env["final_state"] not in TERMINAL_HEALTHY:
            failures.append(env)
    verdict = (
        "ROTATION-STATE-MACHINE-INTACT" if not failures else "DRIFT"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "check": "recovery_paths_terminate",
        "failure_state_count": len(FAILURE_STATES),
        "failures": failures,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="simulate_live_vm_rotation_state_machine",
        description=(
            "Hermetic Sandbox-Stub simulator for the Live-VM rotation "
            "0.5.1 -> 0.5.2 -> 0.5.3-rc1 state-machine."
        ),
    )
    p.add_argument(
        "--entry-state",
        choices=ENTRY_STATES,
        help="Single entry-state to simulate from.",
    )
    p.add_argument(
        "--all-entry-states",
        action="store_true",
        help="Run the simulator from every entry-state in the table.",
    )
    p.add_argument(
        "--verify-recovery-paths",
        action="store_true",
        help=(
            "Run the recovery-path-completeness graph-property "
            "check (Stage 2 of the workflow)."
        ),
    )
    p.add_argument(
        "--strategy",
        choices=STRATEGIES,
        default="happy_path",
        help="Event-pick strategy (default: happy_path).",
    )
    p.add_argument(
        "--out",
        type=Path,
        help="Write the envelope to this path as pretty JSON.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    if args.verify_recovery_paths:
        env = verify_recovery_paths_terminate()
    elif args.all_entry_states:
        env = simulate_all_entry_states(strategy=args.strategy)
    elif args.entry_state:
        env = simulate(args.entry_state, strategy=args.strategy)
    else:
        # Default: happy-path run from PRE_FLIGHT_CHECKS.
        env = simulate("PRE_FLIGHT_CHECKS", strategy="happy_path")

    payload = json.dumps(env, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if env["verdict"] == "ROTATION-STATE-MACHINE-INTACT" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
