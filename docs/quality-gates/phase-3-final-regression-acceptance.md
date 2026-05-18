# Quality-Gate — Phase-3-Final-Regression-Suite Definition-of-Done

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft skeleton — pending Phase-3c-Welle-Marathon completion (ADR-0066 §Beschluss four-Wochen-Cadence KW 24 -> KW 27) |
| Phase | 3 (closing): atomic Acceptance-Suite for Phase-3-COMPLETE marker |
| Source | Tag-40 Amara Auftrag (Continuous-Mode, 2026-05-18); ADR-0066 §Beschluss; ADR-0065 §Verifikations-Plan + §Welle-Ende-Acceptance; ADR-0058 §Phase-3 |
| Date | 2026-05-18 (creation, Tag-40 Phase-3c-Substanz 7/7) |
| Test-File | `tests/phase_3c/test_phase_3_final_regression.py` |

## 0. Phase-3-COMPLETE contract

This document is the **atomic** Definition-of-Done for the
Phase-3-COMPLETE marker: a single hermetic test-suite that verifies,
in **one** test-run, the cross-Welle aggregate invariants required for
the Tomás Tag-40 Marker-Workflow to write the Phase-3-COMPLETE marker
into the WAT-anchored audit-trail.

The Phase-3-COMPLETE marker fires **only when every one of the
following six gates is green**:

1. All seven welle cutovers (KW-24 ... KW-27 per ADR-0066) carry
   sign-off-marker `status="signed-off"`.
2. Every welle's AC-1..AC-5 (ADR-0065 §Acceptance-Kriterien) are
   green.
3. Every welle's AC-4 cross-review-consensus equals the full
   six-persona engineering matrix (`tomas, reza, kai, lena, noa, selin`).
4. The four Welle-Ende-Acceptance gates (WE-1..WE-4, ADR-0065
   §Welle-Ende-Acceptance) are green: container-image-tag
   `0.7.0-rust` active, Quadlet ENV-flags all seven on `rust`,
   Henrik-Audit-Compliance-Check green, Python-legacy archived.
5. No upstream welle has `status="rolled-back"` (cascade-block
   contract).
6. The cross-Welle drift-aggregation verdict is not `"blocker"`
   (single-or-many `"caution"` aggregated to `"caution"` is
   acceptable; any `"blocker"` cancels the marker).

When any of the six gates fails, the marker MUST NOT fire and the
verdict's `blocking_reasons` tuple surfaces every failed gate by name
for Operator-Hand triage + Henrik Zone-N audit-sample input.

## 1. Test-suite scope (28 tests)

The test-suite covers seven regression-axes. Each axis carries the
minimum-test-count needed for substantive coverage; collectively they
satisfy the Auftrag-Tag-40 minimum of 15 tests (with margin to 28).

### 1.1 CW — Cross-Welle-Integration (4 tests)

1. `test_cw_all_seven_wellen_run_in_adr_0066_reihenfolge_kw_24_to_27`
2. `test_cw_welle_m_state_does_not_corrupt_welle_n_for_all_m_lt_n`
3. `test_cw_welle_isolation_holds_under_intermediate_sequential_states`
4. `test_cw_kw_25_solo_welle_3_is_only_solo_welle_in_cadence`

CW pins the ADR-0066-Reihenfolge constant: the seven welle slots occupy
exactly the four-Wochen-Cadence shape (KW-24 has 2 wellen, KW-25 has 1
solo, KW-26 has 2, KW-27 has 2), no ENV-var collisions, no MODUL
collisions, and Welle-3 is the only Solo-Welle (Henrik-Caution carve-out).

### 1.2 P3M — Phase-3-COMPLETE-Marker state-machine (5 tests)

5. `test_p3m_marker_sets_only_when_all_seven_wellen_sign_off`
6. `test_p3m_marker_blocked_when_six_of_seven_wellen_sign_off`
7. `test_p3m_marker_blocked_when_ac_4_cross_review_consensus_missing`
8. `test_p3m_marker_blocked_when_we_1_to_we_4_welle_ende_incomplete`
9. `test_p3m_marker_includes_cross_welle_drift_aggregation_verdict`

P3M is the heart of the suite: the `Phase3CompleteMarkerStateMachine`
in-test oracle that aggregates per-Welle sign-off-markers + WE-1..WE-4
gates into the `Phase3CompleteMarkerVerdict` payload. The five tests
cover the happy-path (all gates green) + each of the four gate-failure
modes (signoff-count, AC-4 consensus, WE-1..WE-4, drift-aggregation).

### 1.3 CASCADE — Rollback-cascade contract (3 tests)

10. `test_cascade_welle_3_rollback_blocks_welle_4_through_7_start`
11. `test_cascade_welle_5_rollback_blocks_welle_6_through_7_but_not_4`
12. `test_cascade_asymmetric_doppel_welle_rollback_preserves_partner`

CASCADE enforces the rollback-cascade contract: when an upstream welle
rolls back, downstream wellen cannot be signed off on top of it. The
DW-AC-3 asymmetric-rollback contract (ADR-0066 §Beschluss) carves out
the case where one Doppel-Welle partner rolls back while the other
remains on `rust`-default — that is allowed, the partner's sign-off
status survives.

### 1.4 REPLAY — 4-Wochen-Marathon long-trace replay (2 tests)

13. `test_replay_kw_24_through_27_chronological_trace_with_signoff_markers`
14. `test_replay_marathon_trace_preserves_per_welle_ac_1_to_ac_5_invariants`

REPLAY drives the full 12-event marathon-trace (4 KWs × cutover/review/
signoff = 12 events) chronologically and asserts (a) ISO timestamps
strictly increase, (b) each KW emits exactly cutover -> review ->
signoff in that order, (c) no welle can sign off before its review
event, and (d) the end-of-trace state aggregates to a green
Phase-3-COMPLETE verdict.

### 1.5 FALSE-POS — Marker false-positive defence (3 tests)

15. `test_false_pos_marker_not_set_on_six_of_seven_signoff`
16. `test_false_pos_marker_not_set_when_ac_4_henrik_audit_consensus_missing`
17. `test_false_pos_marker_not_set_on_premature_kw_26_partial_signoff`

FALSE-POS sweeps the seven possible "one-missing" arrangements (each of
welle-1 ... welle-7 pending while the other six are signed off) and
confirms the marker fails in every case. Also pins the AC-4-consensus
gate and the premature-firing defence (5/7 signoff at end of KW-26).

### 1.6 SUBSTRATE — Per-Welle smoke-substrate cross-Welle consistency (4 tests)

18. `test_substrate_all_seven_smokes_expose_focus_component_and_env_var`
19. `test_substrate_engine_boot_components_strictly_grow_or_stay_across_wellen`
20. `test_substrate_all_smokes_expose_tri_state_exit_codes`
21. `test_substrate_all_smokes_share_phase_pre_post_rollback_constants`

SUBSTRATE static-checks the seven welle smoke modules
(`scripts/phase-3c/welle-*-cutover-smoke.py`) for cross-Welle uniformity:
each exposes `FOCUS_COMPONENT`, `FOCUS_ENV_VAR`, the tri-state exit-code
triple (0/1/2), and the PHASE_PRE/POST/ROLLBACK label-set. Drift in
this substrate would mean a per-Welle smoke envelope cannot be merged
into the marathon-trace aggregator — a Phase-3-final-regression-blocker.

Note: Welle-5's `FOCUS_ENV_VAR` is `WAKIR_FSM_BACKEND` (short-form
`fsm`, not the ADR-0066 long-form `lifecycle_state_machine`). Welle-7's
`FOCUS_COMPONENT` is `recovery` (short-form, not `recovery_workflow`).
The suite accepts the short/long-form synonyms documented in the per-
Welle smoke headers.

### 1.7 EXTENDED — additional cascade + verdict edge-cases (3 tests)

22. `test_extended_marker_verdict_serialises_to_audit_trail_compatible_payload`
23. `test_extended_drift_aggregation_single_caution_does_not_block_marker`
24. `test_extended_full_cascade_all_seven_rolled_back_yields_signoff_zero`

EXTENDED covers the audit-trail wire-up contract (`asdict(verdict) +
json.dumps` must round-trip without TypeError), the caution-aggregation
rule (caution does not block, only blocker does), and the worst-case
full-abort scenario (all 7 wellen rolled-back yields signoff_count=0
and surfaces every blocking-reason).

### 1.8 TIMING — Marathon-trace timing + signoff-order invariants (4 tests)

25. `test_timing_each_welle_signoff_iso_is_after_its_cutover_iso`
26. `test_timing_doppel_welle_partners_share_kw_cutover_and_signoff_iso`
27. `test_timing_solo_welle_3_kw_25_strictly_between_dw_1_2_and_dw_4_5`
28. `test_timing_marathon_trace_total_span_matches_adr_0066_four_weeks`

TIMING pins the four-Wochen-Cadence calendar invariants: signoff_iso
strictly > cutover_iso for every welle, Doppel-Welle partners share KW
+ timestamps, Solo-Welle-3 KW-25 strictly between DW-1+2 KW-24 and
DW-4+5 KW-26, and the marathon's total span is exactly 23 days
(KW-24 Mittwoch -> KW-27 Freitag).

## 2. Hermeticity boundary

stdlib-only. No podman, no live NATS, no live Bridge-Audit-Writer I/O,
no OTS-calendar contact, no engine boot. The seven welle smoke-modules
are loaded via `importlib` from their hyphenated `scripts/phase-3c/`
paths; each smoke's `ENGINE_BOOT_COMPONENTS` inventory is consumed
statically (no resolver invocation). The `Phase3CompleteMarkerState
Machine` is an in-test pure-Python oracle.

The live-VM-acceptance-lane (ADR-0060) remains Operator-Hand
responsibility for the actual Phase-3-cutover execution; this suite is
the QA-side oracle the live drill compares against.

## 3. Sign-Off-Marker shape contract

The `SignOffMarker` dataclass (in `test_phase_3_final_regression.py`,
§ "Sign-Off-Marker shape") carries the following fields:

| Field | Type | Purpose |
|---|---|---|
| `welle_number` | `int` (1..7) | Welle-ordinal in ADR-0066-Reihenfolge. |
| `status` | `str` | `"signed-off"`, `"rolled-back"`, or `"pending"`. |
| `ac_1_5_green` | `bool` | AC-1..AC-5 all green per ADR-0065 §AC-1..AC-5. |
| `ac_4_consensus_personas` | `frozenset[str]` | Personas that consented in the Cross-Review-Session (must equal the six-persona engineering matrix for sign-off). |
| `cross_welle_drift_assert` | `str` | `"green"`, `"caution"`, or `"blocker"` from the welle's A7 cross-modul-drift assertion. |
| `cutover_iso` | `str` | Cutover-Mittwoch ISO timestamp. |
| `signoff_iso` | `str` | Signoff-Freitag ISO timestamp. |

This shape mirrors the canonical `CrossWelleSignOffMarker` from Reza
Tag-40 Cross-Welle-Generalprobe (parallel spawn). Pre-Reza-Tag-40-merge,
the shape lives in `test_phase_3_final_regression.py` as the contract-
anchor; post-merge, the file consumes the canonical shape directly.

## 4. Phase-3-COMPLETE-Marker payload contract

The `Phase3CompleteMarkerVerdict` dataclass carries the audit-trail
payload that the Tomás Tag-40 Marker-Workflow writes:

| Field | Type | Purpose |
|---|---|---|
| `phase_3_complete` | `bool` | True iff all six gates of §0 are green. |
| `signoff_count` | `int` (0..7) | Number of wellen with `status="signed-off"`. |
| `cross_review_consensus` | `bool` | True iff all 7 wellen carry the full six-persona AC-4-consent. |
| `welle_ende_complete` | `bool` | True iff WE-1..WE-4 are all green. |
| `drift_aggregation_verdict` | `str` | `"green"`, `"caution"`, or `"blocker"` aggregated across all 7 wellen. |
| `cascade_blocked` | `bool` | True iff any welle has `status="rolled-back"`. |
| `blocking_reasons` | `tuple[str, ...]` | Human-readable enumeration of every failed gate (empty tuple iff marker fires). |

The contract is enforced by
`test_extended_marker_verdict_serialises_to_audit_trail_compatible_
payload`: `asdict(verdict)` + `json.dumps(..., sort_keys=True)` must
round-trip without TypeError, and the keyset must equal the seven
fields above. The Marker-Workflow writes this payload to the WAT-
anchored audit-trail as a single-line JSON record.

## 5. Cross-spawn coordination (Tag-40)

The Phase-3-final-regression suite is one of four parallel Tag-40
spawns that collectively close Phase-3c. Each spawn references the
others by name + scope; this section enumerates the touchpoints.

| Spawn | Owner | Substrate | Touchpoint to this suite |
|---|---|---|---|
| Cross-Welle-Generalprobe | Reza (Tag-40) | Wirelang-level fixture exporting `CrossWelleSignOffMarker` shape + ADR-0066-Reihenfolge constant | This file's `SignOffMarker` mirrors the canonical shape pre-merge; post-merge, this file imports directly from Reza's fixture. |
| Marathon-Aggregat-Tracker | Selin (Tag-40) | Persona-engine substrate that emits per-Welle sign-off-records during the live marathon | This file's `Phase3CompleteMarkerStateMachine` is the test-time oracle the tracker compares against at each KW Freitag-signoff event. |
| Phase-3-COMPLETE-Marker-Workflow | Tomás (Tag-40) | CI-aggregator workflow that consumes sign-off-records + writes the Phase-3-COMPLETE marker to the WAT-anchored audit-trail | This file's `Phase3CompleteMarkerVerdict` payload-shape is the contract the workflow's writer-side respects. |
| Cutover-Day-Audit-Spec | Henrik (Tag-40) | Zone-N audit-sample-spec on the rollback-cascade audit-records + AC-4 cross-review evidence | This file's CASCADE-axis tests are the Amara-side QA-evidence Henrik's audit-sample consumes as a complementary input. |

## 6. Skip-by-default — opt-in pattern

Unlike the per-Welle and Doppel-Welle E2E-suites (which use
`phase_3c_acceptance` + `phase_3c_doppel_welle_acceptance` markers and
opt-in via env-var/CLI), the Phase-3-final-regression-suite runs by
**default** in CI. Rationale:

* The suite is hermetic + stdlib-only + uses the same smoke modules
  that are already exercised by the per-Welle test-files. It costs
  ~0.2s to run.
* The state-machine assertions are **static contract tests** on the
  ADR-0066-Reihenfolge + the Phase-3-COMPLETE marker shape. Running
  these by default catches drift early.
* No live-substrate dependencies — the suite cannot false-positive on
  Phase-3c-readiness because it makes no claims about live cutover
  state, only about the *contract shape* the cutover must conform to.

The 6+ Required-Status-Checks gating (Auftrag-Tag-40 disziplin) is
satisfied by the suite running inside the default `pytest tests/`
collection on every CI-run.

## 7. Zone-N coordination (Henrik / Internal Audit)

Per the Amara/Henrik Zone-N-Boundary-Discipline (ADR-0044 §Zone-N):
QA-evidence from this suite is **complementary** to Henrik's audit-
sample, **not substitutive**. The specific touchpoints:

* **CASCADE-axis evidence** (tests 10, 11, 12): Henrik consumes the
  test results as input to his Cutover-Day-Audit-Spec sample of the
  rollback-cascade audit-trail. The test-evidence here pins the
  state-machine contract; Henrik's audit-sample independently verifies
  that the production cutover-day audit-trail conforms to that
  contract.
* **P3M `cross_review_consensus` evidence** (tests 7, 16): Henrik
  consumes the AC-4 consensus-tracking evidence as input to his
  ADR-0035 §C-Drift-Closure compliance-check. The test-evidence here
  pins the six-persona consensus requirement; Henrik's audit-sample
  verifies the Aisha-protokollierte cross-review-records carry the
  full six-persona consent.
* **EXTENDED-axis `audit_trail_compatible_payload` evidence** (test
  22): Henrik consumes the payload-shape contract as input to his
  WAT-anchor audit-trail sample. The test-evidence here pins the
  payload-shape; Henrik's audit-sample verifies the production WAT-
  anchored marker-record matches the shape.

The Phase-3-COMPLETE marker itself is set by the Tomás Tag-40 Marker-
Workflow on green QA-evidence; Henrik retains independent sampling
rights on the cutover-day audit-trail and may flag a regression even
if QA-evidence is green (Zone-N-boundary preserved).

## 8. Vermutungs-Kennzeichnung (P2)

Per ADR-0025 §Antwort-Disziplin, the following assumptions in this
suite are marked as **vorläufig** pending Phase-3c-Marathon completion:

* The four-Wochen-Marathon-Trace timestamps (KW-24 Mittwoch 09:00 CEST
  -> KW-27 Freitag 17:00 CEST) are anchored to the ADR-0066 §Beschluss
  calendar; the actual Phase-3c-Marathon may shift by up to ±1 week
  depending on the upstream Phase-3b-Komplettierung schedule.
* The `SignOffMarker` shape mirrors the canonical
  `CrossWelleSignOffMarker` shape from Reza Tag-40 Cross-Welle-
  Generalprobe (parallel spawn). Pre-spawn, this file uses the
  documented shape from §3 of this doc. Post-spawn-merge, the file
  imports directly from Reza's fixture; the shape contract is then
  enforced from a single substrate.
* The `Phase3CompleteMarkerVerdict` payload-fields are placeholder
  shape-anchors pending Tomás Tag-40 Marker-Workflow wire-up; the
  marker-state-machine asserts here pin the contract surface so the
  workflow's writer-side cannot drift the schema silently.
* The CASCADE-axis tests (10, 11, 12) assume the DW-AC-3 asymmetric-
  rollback contract holds (ADR-0066 §Beschluss). If the Doppel-Welle-
  4+5 or Doppel-Welle-6+7 cutover surfaces a contract-violation that
  invalidates DW-AC-3, the CASCADE-axis tests will need a re-design;
  Henrik's audit-sample at the Doppel-Welle-trigger-sprint is the
  early-warning signal.

## 9. Related artefacts

* `tests/phase_3c/test_phase_3_final_regression.py` (Amara, this PR-
  suite) — the test-file this document gates.
* `tests/acceptance/phase_3c/_ac_assertions.py` (Amara, Tag-30/32/34/
  38/39) — the per-Welle AC-1..AC-5 assertion-helpers this suite's
  marker-state-machine consumes conceptually.
* `tests/acceptance/phase_3c/conftest.py` (Amara) — the per-Welle
  fixture-substrate the marker-state-machine layered atop.
* `tests/phase_3c/test_welle_*_cutover_smoke.py` (Amara,
  Tag-34..Tag-39) — the seven per-Welle smoke-test files this suite
  aggregates across.
* `tests/phase_3c/test_doppel_welle_*_acceptance.py` (Amara,
  Tag-38..Tag-39) — the Doppel-Welle E2E-acceptance files that gate
  the parallel-cutover contract this suite enforces at the marathon
  level.
* `docs/quality-gates/phase-3c-acceptance-criteria.md` (Amara) — the
  per-Welle + Doppel-Welle acceptance-criteria matrix this suite
  builds atop.
* `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md`
  (AR-approved 2026-05-16) — the parent Phase-3c-Cutover-Plan this
  suite gates the closure of.
* `decisions/0066-phase-3c-beschleunigung-option-a-plus.md` (AR-
  approved 2026-05-17) — the four-Wochen-Doppel-Welle-Cadence this
  suite encodes as ADR-0066-Reihenfolge.
* `scripts/phase-3c/welle-*-cutover-smoke.py` (seven smoke modules) —
  the substrate this suite imports for cross-Welle inventory
  consistency checks.

— Amara
