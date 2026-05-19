<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Welle-Handler-Family Overview (Persona-Engine, Phase-3c)

**Status:** doc-form-only Master-Reference, Tag-77 (Selin, persona-engine).
**Audience:** persona-engine maintainers, audit-stream consumers, ops/SRE.
**Scope:** the seven disjoint trigger-families exposed by the persona-
engine producer-substrate (`wirelang.persona_engine.welle_state_producer`)
and the top-level dispatch modules (`engine.py` sync + `engine_async.py`
async), plus the cross-Welle Phase-3-COMPLETE verifier added Tag-76.

This document is the master cross-reference for the eight handler-
methods that together drive the Phase-3c-Welle-Marathon (KW-22..KW-27)
through the persona-engine producer-substrate. It is **not** a spec --
the canonical spec lives in the docstrings of
`wirelang/persona_engine/welle_state_producer.py` and the per-Tag plan
docs under `docs/quality-gates/`. This document is a polish-layer
overview to let a reader find the right handler + the right
precondition + the right audit-record trigger in a single page, without
having to grep through twelve test files.

This is doc-form-only -- no test changes, no producer-substrate changes,
no engine.py changes, no schema changes. It complements the Tag-77
cross-Welle handler-integration-tests
(`wirelang/tests/persona_engine/test_cross_welle_handler_integration_tag77.py`).

---

## 1. Producer-substrate scope and discipline

`wirelang.persona_engine.welle_state_producer.WelleStateProducer` is a
stateless-per-call writer over the `state/welle-{1..7}.json` rollup
files (the operator-curated per-Welle state envelopes; schema pin
`tag-67-v1` per `docs/persona-engine/state-file-producer-wiring-plan.md`).

The producer is **engine-side only**:

* No NATS coupling. No SPIRE coupling. No subprocess. Pure in-process
  atomic file I/O.
* No workflow-coupling. The producer does not emit downstream markers
  (e.g. `PHASE_3_COMPLETE_VIA_DOPPEL_WELLE_6_7`). Marker emission lives
  at the audit-trail consumer (Henrik Internal Audit Zone-N).
* No marker-file mutation. The seven per-Welle marker files
  (`state/welle-{1..7}-sign-off.json`, the four substrate-specific
  marker files, etc.) are operator-curated; the producer reads marker-
  status as a **caller-supplied parameter** and refuses-to-write
  on precondition violation.
* No persona-definition coupling (Aisha-Domaene, ADR-0043).
* No WAT-core coupling (Tomas-Domaene, Zone-K).
* No identity-substrate coupling (Reza-Domaene, Zone-L).
* No container-infra coupling (Kai-Domaene, Zone-J).

Every handler call constructs a fresh `WelleStateProducer` (the
top-level dispatch in `engine.py` mirrors this pattern). The producer
class itself is stateless across handler invocations; the only state
is the on-disk `state/welle-{1..7}.json` envelopes.

---

## 2. Refusal-to-write discipline (deterministic precondition order)

Every per-Welle handler enforces preconditions in a **deterministic
refusal-order** so that the audit-trail captures the first violation
unambiguously. The refusal-order is:

1. `signoff_iso` (or `cutover_iso` / `rollback_iso` / `verify_iso`)
   shape validation -- raises `TimeInvariantViolationError`.
2. Companion-marker check (`sign_off_marker_status == "signed-off"`)
   -- raises `SignOffPreconditionError`.
3. Pre-auditor guard (Welle-3 + Welle-7 only) -- raises
   `PreAuditorGuardError`.
4. Substrate-specific marker check (sealing / snapshot-restore /
   capability-token-rotation / cross-substrate-parity / final-sealing)
   -- raises the substrate-specific error subclass.
5. State-file shape + transition validation -- raises
   `StateFileShapeError` / `InvalidStatusTransitionError`.

Idempotency: every handler returns an audit-record with
`prior_status == new_status` (no on-disk mutation) on a double-fire.
**Welle-7 is the strict-idempotency exception**: even after a
successful sign-off, a retry with degraded preconditions (e.g. a
missing pre-auditor decision) is rejected. Rationale: Welle-7 is the
terminal Phase-3-COMPLETE-marker trigger, so the audit-trail forensic
record MUST reflect the marker substrate that authorised every
successful and idempotent sign-off call.

---

## 3. The seven disjoint trigger-families

Every audit-record carries a `trigger` literal that uniquely
identifies the handler-family that produced it. The trigger-literals
are **disjoint** -- a downstream bridge-audit-writer consumer can
route any record to the correct sub-stream without ambiguity.

| # | Trigger literal                | Handler                              | Welle(s) | Marker precondition                                                                  | Added in |
|---|--------------------------------|--------------------------------------|----------|--------------------------------------------------------------------------------------|----------|
| 1 | `cutover`                      | `handle_cutover_event`               | 1..7     | none (pending -> in-progress)                                                        | Tag-69   |
| 2 | `sign-off`                     | `handle_sign_off_event`              | 1, 3     | `sign_off_marker_status == "signed-off"`; Welle-3: + pre-auditor "designated"        | Tag-69/71|
| 3 | `sealing`                      | `handle_welle_2_sealing_event`       | 2        | + `doppelbetrieb_sealed_marker_status == "sealed"`                                   | Tag-70   |
| 4 | `snapshot-restore`             | `handle_welle_4_signoff_event`       | 4        | + `snapshot_restore_marker_status == "restored"`                                     | Tag-72   |
| 5 | `capability-token-rotation`    | `handle_welle_5_signoff_event`       | 5        | + `capability_token_rotation_marker_status == "rotated"`                             | Tag-73   |
| 6 | `cross-substrate-parity`       | `handle_welle_6_signoff_event`       | 6        | + `cross_substrate_parity_marker_status == "verified"`                               | Tag-74   |
| 7 | `final-sealing`                | `handle_welle_7_signoff_event`       | 7        | + pre-auditor "designated" + `final_sealing_marker_status == "confirmed"`            | Tag-75   |
|---|--------------------------------|--------------------------------------|----------|--------------------------------------------------------------------------------------|----------|
| -- | `rollback`                    | `handle_rollback_event`              | 1..7     | `rollback_marker_status == "rollback-authorized"`                                    | Tag-70   |
| -- | `phase-3-complete-verify`     | `handle_phase_3_complete_event`      | cross    | read-only cross-Welle aggregate verifier (all 7 signed-off + monotone cutover_iso)   | Tag-76   |

The first seven rows are the seven per-Welle trigger-families
(disjoint per-record). The last two rows are the cross-cutting
families: `rollback` is parametric over `welle_number` and may fire
at any point in the marathon (terminal); `phase-3-complete-verify` is
the cross-Welle aggregate (read-only) and fires once at Phase-3c-
Schluss.

---

## 4. Handler-family detail

### 4.1 `cutover` (Tag-69, Welle-1..7)

`WelleStateProducer.handle_cutover_event(welle_number, cutover_iso)`

* Transition: `pending -> in-progress`.
* Sets `cutover_iso` on the state-file.
* No marker preconditions; cutover is the start-event of every Welle.
* Idempotent on `not-pending` (double-fire returns no-op record).
* Record carries `trigger="cutover"`.

### 4.2 `sign-off` (Tag-69, Welle-1; Tag-71, Welle-3)

`WelleStateProducer.handle_sign_off_event(welle_number, signoff_iso, *, sign_off_marker_status, pre_auditor_decision=None)`

* Transition: `in-progress -> signed-off`.
* Vanilla sign-off; used by Welle-1 (no pre-auditor) and Welle-3
  (with pre-auditor "designated").
* Welle-3 dispatch: `engine.handle_welle_3_signoff_event` shorthand
  hard-codes `welle_number=3` (Tag-71).
* Idempotent on `signed-off`.
* Record carries `trigger="sign-off"`.

### 4.3 `sealing` (Tag-70, Welle-2)

`WelleStateProducer.handle_welle_2_sealing_event(signoff_iso, *, sign_off_marker_status, doppelbetrieb_sealed_marker_status)`

* Welle-2 closes the legacy <-> new dual-write window (KW-24 Mi).
* Hard-codes `welle_number=2`.
* Two marker preconditions: standard sign-off-marker + the
  `doppelbetrieb_sealed_marker_status == "sealed"` operator-marker.
* No pre-auditor guard (Welle-2 not in `PRE_AUDITOR_GUARDED_WELLEN`).
* Idempotent on `signed-off`.
* Record carries `trigger="sealing"`.
* Top-level dispatch: `engine.handle_welle_sealing_event` (Tag-70).

### 4.4 `snapshot-restore` (Tag-72, Welle-4)

`WelleStateProducer.handle_welle_4_signoff_event(signoff_iso, *, sign_off_marker_status, snapshot_restore_marker_status)`

* Welle-4 is the State-Backing Welle (KW-25 Mo). The 10th pre-boot
  BackendDecision (`state_backing` rust<->python switch, Tag-57-emit-
  order-pin) flips during this Welle.
* Hard-codes `welle_number=4`.
* Two marker preconditions: standard sign-off-marker + the
  `snapshot_restore_marker_status == "restored"` operator-marker
  (sourced from Tomas-Tag-56-Rollback-Workflow §J4).
* No pre-auditor guard.
* Idempotent on `signed-off`.
* Record carries `trigger="snapshot-restore"`.
* Top-level dispatch: `engine.handle_welle_4_signoff_event` (Tag-72).

### 4.5 `capability-token-rotation` (Tag-73, Welle-5)

`WelleStateProducer.handle_welle_5_signoff_event(signoff_iso, *, sign_off_marker_status, capability_token_rotation_marker_status)`

* Welle-5 is the Capability-Token Welle (KW-25 Fr 2026-06-19,
  Reza-Zone-L). The capability-token enforce-mode flip from
  audit-only-mode to enforce-mode happens during this Welle (per
  kw-24-welle-1-7-acceptance-criteria §5 probes W5-S1..S4).
* Hard-codes `welle_number=5`.
* Two marker preconditions: standard sign-off-marker + the
  `capability_token_rotation_marker_status == "rotated"` operator-
  marker (sourced from `state/capability-token-rotation-drill.json`).
* No pre-auditor guard.
* Idempotent on `signed-off`.
* Record carries `trigger="capability-token-rotation"`.
* Top-level dispatch: `engine.handle_welle_5_signoff_event` (Tag-73).

KW-anchor note: the Welle-5 KW-anchor was reconciled from KW-25 to
KW-26 in Tag-74 (per `docs/persona-engine/welle-5-kw-anchor-
reconciliation-tag74.md`). The KW-25 wording above reflects the
historical handler-docstring and the original kw-24-welle-1-7-
acceptance-criteria text; the canonical KW-anchor for
Phase-3-COMPLETE-verifier purposes is `KW-26`
(per `PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR`).

### 4.6 `cross-substrate-parity` (Tag-74, Welle-6)

`WelleStateProducer.handle_welle_6_signoff_event(signoff_iso, *, sign_off_marker_status, cross_substrate_parity_marker_status)`

* Welle-6 is the Cross-Substrate-Parity Welle.
* Hard-codes `welle_number=6`.
* Two marker preconditions: standard sign-off-marker + the
  `cross_substrate_parity_marker_status == "verified"` operator-
  marker (sourced from Tomas' `cross-substrate-parity-gate` workflow:
  cosign <-> quadlet <-> backend-switch parity across the three
  artefact-substrates).
* No pre-auditor guard.
* Idempotent on `signed-off`.
* Record carries `trigger="cross-substrate-parity"`.
* Top-level dispatch: `engine.handle_welle_6_signoff_event` (Tag-74).

### 4.7 `final-sealing` (Tag-75, Welle-7)

`WelleStateProducer.handle_welle_7_signoff_event(signoff_iso, *, sign_off_marker_status, pre_auditor_decision=None, final_sealing_marker_status)`

* Welle-7 is the **terminal** Welle of the Phase-3c-Welle-Marathon
  (KW-27 per pre-cutover-acceptance-run-order.md §3 + phase-3c-doppel-
  welle-6-7.md §4).
* Hard-codes `welle_number=7`.
* **Three** preconditions (the most-guarded sign-off path in the
  substrate):
  1. standard `sign_off_marker_status == "signed-off"`,
  2. pre-auditor guard `pre_auditor_decision == "designated"` (Welle-7
     is in `PRE_AUDITOR_GUARDED_WELLEN`, Henrik-cannot-self-sign-off
     invariant; mirrors Welle-3),
  3. `final_sealing_marker_status == "confirmed"` (Tag-75 §2.8;
     operator-curated `state/welle-7-final-sealing.json`).
* **Strict idempotency**: even after a successful sign-off, a retry
  with degraded preconditions is rejected. Rationale: terminal marker
  trigger; audit-trail must capture marker authority on every call.
* Record carries `trigger="final-sealing"` (intentionally distinct
  from Welle-2's `"sealing"`: Welle-2 closes one substrate boundary,
  Welle-7 closes the entire Phase-3c-Welle-Marathon).
* Top-level dispatch: `engine.handle_welle_7_signoff_event` (Tag-75).

### 4.8 `phase-3-complete-verify` (Tag-76, cross-Welle)

`WelleStateProducer.handle_phase_3_complete_event(verify_iso, *, required_wellen=PHASE_3_COMPLETE_REQUIRED_WELLEN, phase_3_emitter=None)`

* **Read-only** cross-Welle aggregate verifier. Does NOT mutate any
  state-file.
* Invariants checked (refusal-order):
  1. `verify_iso` shape (RFC 3339, second-precision UTC).
  2. For each required `welle_number`:
     a. `state/welle-N.json` exists and is shape-valid.
     b. `status == "signed-off"`.
     c. `cutover_iso` and `signoff_iso` are non-empty.
  3. Cross-Welle cutover-monotonicity: for `i < j`, `cutover_iso[i] <=
     cutover_iso[j]`. Equal cutover_iso between Welles 4/5/6 is
     tolerated (KW-26 shared anchor per Tag-74 reconciliation).
* On green: returns a `Phase3CompleteAuditRecord` with `verdict =
  "phase-3-complete-verified"` and `trigger = "phase-3-complete-
  verify"`. Emits via optional `phase_3_emitter` hook.
* On red: raises `Phase3CompleteVerifierError` (or one of the per-
  Welle refusal-errors during file-loading).
* The cross-Welle audit-record (`Phase3CompleteAuditRecord`) is a
  **disjoint type** from the per-Welle `WelleAuditRecord`. The
  audit-stream consumer can demultiplex on record-type.
* Top-level dispatch: `engine.handle_phase_3_complete_event` (Tag-76).

---

## 5. Cross-Welle pairwise-pinning matrix

The seven trigger-families are **pairwise disjoint** by trigger
literal. A bridge-audit-writer consumer can compute the trigger-set
of any successful Marathon-run by counting unique trigger-literals on
the audit-stream. For the canonical seven-Welle Marathon, the
trigger-set is:

```
{"cutover", "sign-off", "sealing", "snapshot-restore",
 "capability-token-rotation", "cross-substrate-parity",
 "final-sealing"}
```

(`"sign-off"` covers Welle-1 and Welle-3; the other five
`final-sealing`-family triggers are per-Welle.) Adding the read-only
cross-Welle verifier-trigger:

```
{ ..., "phase-3-complete-verify"}
```

The `"rollback"` literal is disjoint from all of the above; it is
**not** part of a green Marathon-run (rollback is a terminal failure-
path).

This document's master matrix is mirrored by the Tag-77 cross-Welle
integration tests
(`wirelang/tests/persona_engine/test_cross_welle_handler_integration_tag77.py`),
which pin every disjoint pairing.

---

## 6. Canonical KW-anchor schedule

Per `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3 + the
Tag-74 KW-anchor reconciliation, the canonical KW-anchor schedule
(also exposed as `PHASE_3_COMPLETE_CANONICAL_KW_ANCHOR` for the
verifier-fixture) is:

| Welle | KW-anchor | Day-of-week (operator-curated)  | Family-trigger              |
|-------|-----------|---------------------------------|-----------------------------|
| 1     | KW-22     | Wo (cutover-anchor)             | `sign-off`                  |
| 2     | KW-23     | Mi (Doppelbetrieb-Sealing)      | `sealing`                   |
| 3     | KW-25     | Fr (Bridge-Audit + pre-auditor) | `sign-off` (pre-auditor)    |
| 4     | KW-26     | Mo (State-Backing)              | `snapshot-restore`          |
| 5     | KW-26     | Fr (Capability-Token-Rotation)  | `capability-token-rotation` |
| 6     | KW-26     | (shared KW with Welle-4/5)      | `cross-substrate-parity`    |
| 7     | KW-27     | Schluss-Acceptance + pre-auditor| `final-sealing`             |

Welles 4/5/6 share KW-26 by design. The verifier tolerates equal
cutover_iso between any pair in {4, 5, 6} (the cross-Welle
monotonicity invariant uses `<=`, not `<`, for that reason).

---

## 7. Sync vs async dispatch surface

Every handler exists in both flavours:

* `wirelang.persona_engine.engine.handle_*` -- sync free functions,
  one per family. They construct a stateless `WelleStateProducer` per
  call and delegate to the producer-method.
* `wirelang.persona_engine.engine_async.handle_*` -- async wrappers
  via the default-loop thread-pool executor. They are
  `inspect.iscoroutinefunction(...)` -- True; the sync counterparts
  are False.

The async surface is symmetric to the sync one (no signature drift,
no semantic drift). Both delegate to the same
`WelleStateProducer` producer-substrate. The async layer is a thin
loop-executor wrapper; the substrate itself is sync (file I/O).

---

## 8. Scope discipline and zones

Tag-77 is doc-form-only + cross-Welle integration-tests. No producer-
substrate changes. No engine.py changes. No schema changes. No
persona-definition changes (Aisha-Domaene). No WAT-core changes
(Tomas-Domaene, Zone-K). No identity-substrate changes (Reza-Domaene,
Zone-L). No container-infra changes (Kai-Domaene, Zone-J). No
Phase-3-COMPLETE-marker emission (Henrik Internal Audit Zone-N).

This doc is the polish-layer master reference for the seven disjoint
trigger-families + the cross-Welle Phase-3-COMPLETE verifier. It does
not change behaviour. If a reader needs more depth than this overview
provides:

* per-Welle producer-method docstring -> canonical contract
  (`wirelang/persona_engine/welle_state_producer.py`);
* per-Tag plan-doc -> rollout context
  (`docs/quality-gates/pre-cutover-acceptance-run-order.md`,
  `docs/quality-gates/phase-3c-doppel-welle-6-7.md`);
* per-Tag test file -> happy-path + refusal-path pins
  (`wirelang/tests/persona_engine/test_welle_{N}_producer_tag{69..75}.py`,
  `wirelang/tests/persona_engine/test_production_bringup_verifier_tag76.py`);
* the cross-Welle pairwise-pinning matrix -> Tag-77 integration tests
  (`wirelang/tests/persona_engine/test_cross_welle_handler_integration_tag77.py`).

-- Selin (persona-engine), Tag-77.
