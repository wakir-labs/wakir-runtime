# Quality-Gate — Failure-Mode A2 FSM-Phantom-Transition Coverage Matrix Update (Tag-46)

| Field | Value |
|---|---|
| Owner | Reza Tehrani (Dev-Engineering-2 / Wirelang), with Tomás cross-review (Zone-1 Identity-Substrate) |
| Status | COVERED — re-classification of Amara-Tag-45 PARTIAL classification |
| Phase | 3 (closing): Pre-Mortem failure-mode test-coverage follow-up |
| Source | Tag-46 Reza Auftrag (Continuous-Mode, 2026-05-18); Amara-Tag-45 §A2 follow-up scope (`docs/quality-gates/pre-mortem-failure-mode-coverage.md`); Henrik Tag-44 Pre-Mortem-Skizze §A2 (`reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md`) |
| Date | 2026-05-18 (creation, Tag-46 A2-coverage spawn) |
| Test-File | `wirelang/tests/persona_engine/test_fsm_phantom_transition_coverage_a2.py` |
| Companion (parent matrix) | `docs/quality-gates/pre-mortem-failure-mode-coverage.md` (Amara Tag-45) |

## 0. Contract scope

This document updates the **A2 row** of the Tag-45 Pre-Mortem
Failure-Mode Coverage-Matrix from **PARTIAL** to **COVERED**, citing
the new hermetic test surface in
`wirelang/tests/persona_engine/test_fsm_phantom_transition_coverage_a2.py`.

The Tag-45 audit named this Tag-46 follow-up explicitly (Tag-45
§4 row 1, table-id "A2 FSM-Phantom-Transitions"). The Tag-46
spawn closes the named gap.

This document is **scoped narrowly to A2**. It does not modify the
A1/A3..A8/B/C/D classifications in the parent matrix. Items A6 and
A8 remain PARTIAL and are tracked for separate Tag-46+ follow-ups
(`test_cosign_chain_marathon_image_hash_stability.py` and
`test_welle_4_state_backing_persistence_loss.py`).

## 1. A2 row — before and after

### Before (Tag-45 classification)

| Field | Value |
|---|---|
| Failure-mode | A2 — FSM-Phantom-Transitions (illegal state-transitions post-cutover) |
| Coverage state | **PARTIAL** |
| Pinning tests | AP-4 (Tag-44) — partial coverage of FSM-state-leak via namespace-prefix discipline, but does NOT exercise transition-legality oracle directly. Tag-37 Rust FSM-Replay-Engine — out-of-scope for the Python suite. |
| Follow-up named | Tag-46+ — add Python-side FSM-transition-legality oracle. |

### After (Tag-46 update)

| Field | Value |
|---|---|
| Failure-mode | A2 — FSM-Phantom-Transitions (illegal state-transitions post-cutover) |
| Coverage state | **COVERED** |
| Pinning tests | (Existing) AP-4 (Tag-44) — namespace-prefix discipline arm. (New, Tag-46) 15 hermetic tests in `test_fsm_phantom_transition_coverage_a2.py` covering four sub-pathways: state-machine-edge-cases (5 tests), race-conditions in transition-emit (3 tests), snapshot-corruption-recovery (4 tests), cross-modul-leak to state_backing (3 tests). |
| Follow-up | None — A2 closed for Phase-3-Marathon. |

## 2. Tag-46 sub-pathway coverage map

The Tag-45 follow-up scope named four sub-pathways for A2. Each is
covered by a dedicated test block in the Tag-46 file.

### Sub-pathway 1 — state-machine-edge-cases

Five tests pin the transition-legality oracle as the
cartesian-product of (from_state, to_state) over STATES x STATES.

| Test | Invariant |
|---|---|
| `test_a2_legality_oracle_every_invalid_edge_is_rejected` | All 27 invalid edges raise `InvalidTransitionError` + record audit-rejection. |
| `test_a2_legality_oracle_every_valid_edge_advances` | All 9 valid edges advance state + record audit-acceptance. |
| `test_a2_self_loop_is_never_valid` | No self-loop in `VALID_TRANSITIONS`; all 6 self-loops rejected. |
| `test_a2_unknown_target_state_is_rejected_with_typed_error` | Phantom target raises `UnknownStateError` with typed audit-reason. |
| `test_a2_terminal_state_rejects_all_outgoing_phantoms` | No state has 0 outgoing edges (no phantom-attractor). |

### Sub-pathway 2 — race-conditions in transition-emit

Three tests pin history-determinism under the single-writer
serialisation contract.

| Test | Invariant |
|---|---|
| `test_a2_rapid_fire_legal_sequence_history_determinism` | All 9 valid edges, exercised in sequence from a single thread, produce a deterministic 8-record history. |
| `test_a2_mid_sequence_phantom_does_not_corrupt_history_cursor` | A mid-sequence phantom rejection does not corrupt the next legal transition. |
| `test_a2_serialised_writer_lock_emit_under_threading_lock` | Under multi-thread access serialised by `threading.Lock`, history is byte-identical to the single-thread case. |

### Sub-pathway 3 — snapshot-corruption-recovery

Four tests pin `LifecycleStateMachine.replay` against corrupted
history-records (the recovery-workflow §3.7.4 R2 path).

| Test | Invariant |
|---|---|
| `test_a2_replay_rejects_accepted_edge_not_in_valid_transitions` | An accepted-record whose `(from, to)` is phantom raises on replay. |
| `test_a2_replay_rejects_accepted_edge_with_mismatched_from_state` | An accepted-record whose `from_state` does not match the cursor raises on replay. |
| `test_a2_replay_preserves_rejected_records_without_state_advance` | A rejected-record in the history replays as an audit annotation and does not advance the cursor. |
| `test_a2_replay_empty_history_yields_initial_state` | Boundary: empty history yields fresh `uninstantiated` FSM. |

### Sub-pathway 4 — cross-modul-leak to state_backing

Three tests pin the Zone-1 Identity-Substrate-Konsens at the FSM
to state_backing seam.

| Test | Invariant |
|---|---|
| `test_a2_no_leak_fsm_transition_to_other_persona_state_backing` | Persona-A FSM transition does not create snapshots in persona-B's state_backing keyspace. |
| `test_a2_no_leak_state_backing_snapshot_does_not_advance_other_fsm` | Persona-B state_backing snapshot does not advance persona-A's FSM. |
| `test_a2_phantom_transition_attempt_does_not_corrupt_state_backing` | A rejected FSM phantom-transition does not silently mutate state_backing snapshot bytes. |

## 3. Coverage-matrix delta against Tag-45 §3

The Tag-45 §3 coverage-summary table is updated as follows. Only
Class-A changes; B/C/D rows unchanged.

| Class | Total | COVERED | PARTIAL | GAP-ACCEPTED | GAP-OPEN |
|---|---|---|---|---|---|
| A (Technisch) | 8 | 6 (A1, A2, A3, A4, A5, A7) | 2 (A6, A8) | 0 | 0 |
| B (Operativ) | 6 | 2 (B2, B4) | 2 (B1, B3) | 2 (B5, B6) | 0 |
| C (Prozedural) | 5 | 2 (C1, C2) | 0 | 3 (C3, C4, C5) | 0 |
| D (Externe) | 5 | 0 | 0 | 5 (D1-D5) | 0 |
| **Total** | **24** | **10** | **4** | **10** | **0** |

**Coverage interpretation delta.**

- COVERED: 9 of 24 (37.5%) -> **10 of 24 (41.7%)** after Tag-46.
- PARTIAL: 5 of 24 (20.8%) -> **4 of 24 (16.7%)** after Tag-46.
- GAP-ACCEPTED: 10 of 24 (41.7%) — unchanged.
- GAP-OPEN: 0 of 24 (0%) — unchanged.

## 4. Cross-review observations (Vermutungs-Kennzeichnung P2)

**Zone-1 Identity-Substrate-Konsens (Reza/Tomás).** Sub-pathway 4
(cross-modul-leak) pins the FSM <-> state_backing seam by persona_id.
This aligns with the Zone-1 cross-review-zone scope (persona-identity
namespace bidirectional isolation). No new Tomás-cross-review item is
spawned by this document; the existing Zone-1 cadence is sufficient.

**A2 versus AP-4 relationship.** AP-4 (Tag-44, control-plane anti-
pattern) pins the structural arm "namespace-prefix discipline rejects
cross-Welle state-leak". The Tag-46 file additionally pins the
"transition-legality oracle" arm. Together the two layers are
defence-in-depth: AP-4 catches the namespace-pollution failure-mode,
A2-Tag-46 catches the in-namespace-but-illegal-edge failure-mode.

**Rust FSM-Replay-Engine relationship (Tag-37).** The Tag-37 Rust
crate tests in `bridge-audit/` are the authoritative oracle for the
replay-engine binary-protocol layer. The Tag-46 Python tests are the
oracle for the Python-side LifecycleStateMachine surface. The two
layers are independent; no Rust-Python parity test is mandated by
this document. (A Rust-Python parity test for the FSM exists at
`wirelang/tests/persona_engine/test_lifecycle_state_machine_cross_lang_parity.py`
and provides incidental cross-layer assurance.)

## 5. Run instructions

The test file is hermetic and runs under the default lane:

```
python -m pytest wirelang/tests/persona_engine/test_fsm_phantom_transition_coverage_a2.py -v
```

Expected: 15 passed in <1s. No opt-in marker required.

— Reza Tehrani (Dev-Engineering-2 / Wirelang), Tag-46 A2 FSM-Phantom-Transition Coverage, 2026-05-18
