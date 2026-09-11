<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Design note: per-component backend rollback (Rust → Python)

**Status:** design note, extracted from the retired
`phase-3-marathon-rollback.yml` workflow (recoverable via tag
`archive/pre-phase-4`). No active workflow implements this today; the
note records the pattern so a future rollback path does not have to be
redesigned from scratch.

## Problem

The persona engine ships each of its seven components (`v907_verify`,
`svid_workload_identity`, `bridge_audit_writer`, `state_backing`,
`lifecycle_state_machine`, `subscribe_loop`, `recovery_workflow`) with
two backends: the Rust CLI binary (default since 2026-05-20) and the
Python reference implementation. Backend selection is an environment
flag per component (`WAKIR_PE_<COMPONENT>_BACKEND=rust|python`) read by
the engine's backend-decision layer and set in the component's Quadlet
unit file on the host.

A rollback flips that flag back to `python` for one or more components
and restarts the affected units. The interesting part is not the flip
itself but doing it deterministically under pressure.

## Pattern

1. **Reverse activation order.** Components were promoted to the Rust
   default in a fixed order (1 → 7). Rollback walks the order backwards
   (7 → 1) so that a component never runs on the Python backend while a
   component that depends on it still runs on Rust. Partial rollback
   starts at any position in that sequence and continues to the end.

2. **Audit marker before any mutation.** The first step writes a
   rollback-attempt marker (actor, reason, cycle id, mode) to the audit
   trail. If the run dies half-way, the attempt is still recorded and
   attempted-vs-completed rollbacks can be counted without scraping
   logs.

3. **Fail-closed sequencing.** Each component step depends on the
   previous one; a failure halts the chain unless the operator
   explicitly opts into partial rollback. The default is to stop.

4. **State-backing needs a snapshot restore.** `state_backing` is the
   only component with persistent state whose on-disk format differs
   between backends. Its rollback step must restore the pre-cutover
   snapshot in addition to flipping the flag; a rollback of that
   component without snapshot restore is reported as degraded, not as
   success.

5. **Stub mode vs. live mode.** The orchestration runs in CI in a stub
   mode that plans every action and emits per-component envelopes
   (`{component, target_backend, planned, status}`) without touching a
   host. Live mode is refused on hosted runners; the actual
   flag-flip-and-restart runs on the target host under operator hand.
   The CI run validates the plan; the host run executes it.

6. **Aggregate verdict.** After the chain, a manifest aggregates the
   per-component envelopes into `READY | PARTIAL | FAILED` and the
   operator receives a notification payload prepared by CI but sent by
   hand (CI holds no notification credentials).

## Non-goals

- Automatic rollback on alert. Rollback is an operator decision.
- Rollback across schema versions of the WAT manifest; that is a
  migration, not a backend switch.

## Related

- `docs/operations/cross-substrate-parity-runbook.md` — the parity gate
  that keeps cosign policy, Quadlet units and backend-switch table
  aligned.
- `wirelang/persona_engine/` backend-decision layer (reads the flags).
