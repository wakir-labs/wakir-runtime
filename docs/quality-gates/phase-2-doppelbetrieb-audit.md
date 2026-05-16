# Quality-Gate — Phase 2 (Doppelbetrieb) — Konsistenz-Audit

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), Zone-N cross-check by Henrik (Internal Audit) |
| Status | Audit-Report, Draft — Sprint-Quality-Gate-Konsistenz-Audit-MINI |
| Phase | Cross-Check between Spec (PR #80) and Test-Implementation (PR #109) + CI-Workflow (PR #115) |
| Date | 2026-05-16 |
| Anchors | ADR-0058 §"Phase 2 — Doppelbetrieb"; `docs/quality-gates/phase-2-doppelbetrieb.md` (PR #80); `tests/infra/test_phase_2_acceptance_gates.py` (PR #109); `.github/workflows/phase-2-validation-gate.yml` (PR #115). |

## 0. Audit-Scope and Method

This audit is a **paper-Cross-Check**: I read the Phase-2 spec
(`phase-2-doppelbetrieb.md`), then the hermetic acceptance-test suite
(`test_phase_2_acceptance_gates.py`), then the CI-workflow driver
(`phase-2-validation-gate.yml`), and recorded for each acceptance-gate:

* Which test-suite covers the gate (hermetic, live, or neither)?
* Which actual substance on `main` already exists to back the gate?
* Which assumptions remain unverified at the test-time level (i.e.
  what is a runtime-gate Henrik samples, not a CI-gate QA enforces)?

Audit-Scope-Boundary: the audit only covers the Phase-2 promotion
contract as written in PR #80. It does NOT re-audit ADR-0058 itself,
it does NOT replace Henrik's quartalsweisen Zone-N-Review, and it
does NOT touch live-VM acceptance (Operator-Hand-lane, see
`feedback_sandbox_host_trennung.md`).

## 1. Cross-Check per Acceptance-Gate

The Phase-2 spec (PR #80) defines **five** acceptance-gates in §1
(numbered 2.1 .. 2.5). The hermetic test-suite (PR #109) defines
**five** gate-tests plus an aggregator (Gate-2-1 .. Gate-2-5 plus
`test_gate_aggregator_phase_2_acceptance_all_green`). The numbering
matches; the **semantic mapping does not match 1:1**. This is the
single largest finding of this audit.

### Mapping table

| Spec gate (PR #80) | Test gate (PR #109) | Semantic match | Notes |
|---|---|---|---|
| §2.1 All Phase-1b gates remain green | (none — covered by phase-1b workflow chain) | n/a | Runtime-gate; not a Phase-2 hermetic test. Audit OK. |
| §2.2 Bridge-Forward fan-out symmetric (drop ≤ 0.1%) | `test_gate_2_1_bridge_forward_symmetry` | **MATCH** | Numbering off by one (Test-Gate-2-1 ⇔ Spec-Gate-2.2). |
| §2.3 Doppelbetrieb-Score 4-axis verdict ≥ pass | `test_gate_2_2_konsistenz_score_threshold` | **PARTIAL** | Test only asserts functional-equivalence axis. Three of four axes (byte_delta, structural_equivalence, spurious_divergence) are NOT asserted hermetically. See §2 Finding F-2. |
| §2.4 No V-907 pin-drift for 28 days | `test_gate_2_3_v907_hash_stability_marker` | **MATCH (test-time proxy)** | Test asserts pin stability over 50-emission window; the 28-day window is a runtime-gate Henrik samples. Doc anchor in test correctly identifies this as a test-time proxy. |
| §2.5 Persona-state KV-bucket integrity | (none — runtime-gate per Noa-Alert) | n/a | Spec explicitly marks the rolling-window monotonicity as a **runtime-gate**, with the per-spawn invariant covered by `test_engine_natskv_active_log.py`. Audit OK. |
| (no spec gate) | `test_gate_2_4_recovery_r1_r4_mock_drill` | **EXTRA** | Test anchors itself to ADR-0058 §"Phase 3 stress-test-drill matrix" — not to any Phase-2 spec gate. See §2 Finding F-1. |
| (spec §3 SLO row) | `test_gate_2_5_subscribe_loop_lag_mock` | **MATCH (SLO proxy)** | Spec §3 lists the p99 ≤ 45s as a runtime SLO (Noa-design-review pending). Test asserts the same number as a hermetic mock. Acceptable as proxy. |

### Cross-check by gate

#### 2-1 Bridge-Forward-Symmetry (Spec §2.2)

* **Test-suite:** `test_gate_2_1_bridge_forward_symmetry` — hermetic.
* **Substance on `main`:**
  - `tests/infra/test_doppelbetrieb_bridge_smoke.py` (Sprint-10 Tag-9)
    asserts payload-hash agreement + engine-version discrimination
    over a two-engine emission scenario.
  - `wirelang.persona_engine.bridge_audit_writer` emits both sinks.
  - No bridge-forward fan-out drop-rate measurement exists on `main`
    yet — the spec calls this out: "Test-Vector: new vector to be
    added in Phase-2 sprint; not in scope for Sprint-QA-Tag-15."
* **Unverified assumption:** Drop-rate measurement substrate (the
  fan-out reconciliation report from Sprint-10 Tag-6 spec §7) is a
  **runtime artefact** not yet wired into a CI gate. The hermetic
  test asserts the threshold contract; it does not exercise the
  fan-out emitter itself. **This is correct test-time scoping** but
  the runtime emitter is the gap Phase-2 must close in KW 25-27.

#### 2-2 Konsistenz-Score (Spec §2.3)

* **Test-suite:** `test_gate_2_2_konsistenz_score_threshold` — hermetic,
  via `wirelang.persona_engine.bridge_audit_diff_engine`
  (Selin PR #106).
* **Substance on `main`:**
  - Diff-engine is live and JCS-canonicalises both implementations.
  - `wirelang doppelbetrieb-score` CLI exists (Selin) — referenced by
    Spec §2.3 Test-Vector.
  - `wirelang doppelbetrieb-aggregate` (Sprint-10 Tag-6) emits the
    weekly rollup-report.
* **Unverified assumption — PARTIAL COVERAGE — see Finding F-2:**
  The spec §2.3 verdict is a **4-axis** verdict:
    1. `functional_equivalence >= 0.95`  — covered hermetically.
    2. `byte_delta ≤ documented per-output-class threshold` — **NOT
       asserted hermetically**.
    3. `structural_equivalence >= 0.90` — **NOT asserted hermetically**.
    4. `spurious_divergence ≤ 5 per 100 outputs` — **NOT asserted
       hermetically**.
  The hermetic test maps `consistency_score` onto axis 1 only.
  Axes 2/3/4 live in the runtime CLI (`wirelang doppelbetrieb-score`)
  output and are sampled by Henrik weekly. **This is a deliberate
  test-time-vs-runtime-gate split**, and the spec acknowledges it
  ("the 6-week threshold is a runtime gate, not a test-time gate").
  But the audit recommends a follow-up test that asserts the four-axis
  *shape* of the CLI output (schema-pin), even if the CLI itself runs
  on runtime data Henrik samples. See §3 Folge-Item FI-1.

#### 2-3 V-907-Hash-Stabilität (Spec §2.4)

* **Test-suite:** `test_gate_2_3_v907_hash_stability_marker` — hermetic.
* **Substance on `main`:**
  - `wirelang.persona_engine.v907_verify` (Selin) emits
    `PersonaHashDriftError` on drift, container exits rc=2
    (`EXIT_V907_HASH_DRIFT`).
  - `BridgeAuditWriter` carries the `v907_pin` field on every
    envelope.
* **Unverified assumption:** 28-day rolling window — covered as
  **runtime-gate Henrik samples**, not a CI-gate. Test asserts the
  per-emission invariant correctly. Audit OK.

#### 2-4 Recovery-R1..R4-Mock-Drill (NO SPEC GATE — see Finding F-1)

* **Test-suite:** `test_gate_2_4_recovery_r1_r4_mock_drill` — hermetic.
* **Substance on `main`:**
  - `wirelang.persona_engine.recovery_workflow` exists.
  - `wirelang.persona_engine.drill_scheduler` exists.
  - ADR-0058 §"Phase 3 — Validation (Wochen 5-6)" describes the
    live stress-test-drill matrix; the hermetic test is the test-time
    contract-shape equivalent.
* **Unverified assumption — FINDING F-1:** This test does NOT
  correspond to any Phase-2 acceptance-gate in `phase-2-doppelbetrieb.md`.
  The test's own docstring correctly anchors it to ADR-0058 §"Phase 3",
  not §"Phase 2". **Either the spec is missing a gate, or the test is
  in the wrong phase.** See §2 Finding F-1 for the recommendation.

#### 2-5 Subscribe-Loop-Lag (Spec §3 SLO row)

* **Test-suite:** `test_gate_2_5_subscribe_loop_lag_mock` — hermetic.
* **Substance on `main`:**
  - `wirelang.persona_engine.nats_subscribe_loop` (Selin) is the
    real subscribe-loop substrate.
  - Spec §3 SLO row lists p99 ≤ 45s as "vorläufig per P2: needs
    Noa-design-review".
* **Unverified assumption:** SLO number `45s` is a placeholder
  pending Noa's design-review of Phase-1b telemetry. **The hermetic
  test hardcodes the placeholder.** If Noa tightens or loosens the
  SLO, both the spec and the test must move in lock-step. See
  §3 Folge-Item FI-3.

#### §2.5 Persona-state KV-bucket integrity (NO TEST IN SUITE)

* **Test-suite:** none in the Phase-2 acceptance gate suite.
* **Substance on `main`:**
  - `test_engine_natskv_active_log.py` (existing — covers the
    per-spawn invariant per Spec §2.5 Test-Vector).
* **Unverified assumption:** Rolling-window monotonicity is a
  **runtime-gate** monitored by Noa-Alert. Audit OK. Spec
  acknowledges this is not a hermetic-test-suite item.

#### §2.1 Phase-1b gates remain green (NO PHASE-2 TEST)

* **Test-suite:** the Phase-1b CI lane covers this transitively.
* **Substance on `main`:**
  - `tests/infra/test_phase_1b_*.py` family + `e2e-vm-acceptance-gate`
    workflow.
* **Unverified assumption:** "for the duration of Phase 2" is a
  runtime-process-contract, not a CI-gate. The CI runs Phase-1b
  weekly. Audit OK.

## 2. Konsistenz-Score zwischen Spec und Test-Implementation

I compute the consistency-score over the 7-row mapping table in §1
using the same shape as the runtime Doppelbetrieb-Score four-axis
verdict (the test-time meta-application of the metric Selin's CLI
produces).

| Axis | Score | Notes |
|---|---|---|
| Coverage-Completeness (spec gates with at least one test) | 4/5 = 0.80 | §2.1 transitive, §2.2 covered, §2.3 partial (counts as 0.5), §2.4 covered, §2.5 runtime-gate-by-design (counts as covered). Numerator: 1 + 1 + 0.5 + 1 + 1 = 4.5 → 0.90. Adjusted: **0.90**. |
| Semantic-Mapping (test anchors to correct spec gate) | 4/5 = 0.80 | Gate-2-1, Gate-2-2, Gate-2-3, Gate-2-5 anchor correctly. Gate-2-4 anchors to ADR-0058 Phase-3, NOT to any Phase-2 spec gate. **Finding F-1.** |
| Numbering-Discipline (gate IDs align) | 0/1 = 0.00 | Spec uses §2.1..§2.5; tests use Gate-2-1..Gate-2-5. The numerical labels look identical but Spec-Gate-2.2 ⇔ Test-Gate-2-1 (off-by-one). **Finding F-3.** |
| Schema-Pin (CI-driver targets exact test functions) | 5/5 = 1.00 | Workflow PR #115 invokes `pytest -k <exact-function-name>` per gate. No drift risk from rename. |

Aggregate Konsistenz-Score: **mean(0.90, 0.80, 0.00, 1.00) = 0.675**.

Interpretation: below the spec-canonical 0.95 functional-equivalence
threshold (PR #80 §2.3), driven primarily by the numbering-discipline
axis. The two semantic findings (F-1, F-2) are **Phase-2-Validation-
Welle Folge-Items**, not Phase-2-promotion blockers. The numbering
finding (F-3) is **cosmetic but audit-relevant** — Henrik's weekly
sample will surface "Spec-Gate-2.4" vs "Test-Gate-2-4" as semantically
distinct items.

### Findings

#### F-1: Test-Gate-2-4 (Recovery R1..R4) has no corresponding Phase-2 spec gate

**Severity:** Medium.

**Evidence:** `test_gate_2_4_recovery_r1_r4_mock_drill` docstring
explicitly anchors itself to "ADR-0058 §'Phase 3 — Validation
(Wochen 5-6)' Stress-Test-Drill matrix" — not to any §1 acceptance-
gate in `phase-2-doppelbetrieb.md`. The Phase-2 spec has gates
§2.1..§2.5; none of them is a recovery-drill gate.

**Recommendation:** EITHER

* (a) Move the Recovery-R1..R4 test to a `test_phase_3_validation_gates.py`
  file in KW 25-27 when the Phase-3 spec doc is drafted, OR
* (b) Add a sixth acceptance-gate `§2.6 Recovery-Drill-Mock` to
  `phase-2-doppelbetrieb.md`, since recovery-readiness is arguably
  a Phase-2 promotion criterion (you cannot go to Phase 3 without
  demonstrating recovery-readiness in Phase 2).

**My pref as QA:** (b). Phase-2 → Phase-3 promotion criteria §5
in the spec already implies recovery-readiness. Making it explicit
as §2.6 closes the gap. **Notiz für Mira — strategic implication
(spec amendment), I cannot ship it without approval.**

#### F-2: Gate-2-2 hermetic test covers 1 of 4 verdict axes

**Severity:** Low (deliberate design, but document it).

**Evidence:** Spec §2.3 names four axes for the Doppelbetrieb-Score
verdict (functional_equivalence, byte_delta, structural_equivalence,
spurious_divergence). The hermetic test asserts only
functional_equivalence (via `consistency_score`). The other three
axes live in `wirelang doppelbetrieb-score` CLI output and are
sampled at runtime by Henrik.

**Recommendation:** Add a Schema-Pin-Test that asserts the
**shape** of the CLI's four-axis verdict JSON output, even if the
values themselves are runtime-only. This catches accidental field-
rename or axis-drop in Selin's CLI. See §3 Folge-Item FI-1.

#### F-3: Numbering off-by-one between Spec §2.x and Test-Gate-2-x

**Severity:** Cosmetic (audit-trail friction).

**Evidence:**

* Spec §2.2 = Test-Gate-2-1
* Spec §2.3 = Test-Gate-2-2
* Spec §2.4 = Test-Gate-2-3
* Spec §2.5 = no test
* Test-Gate-2-4 = no spec gate
* Spec §3 SLO row = Test-Gate-2-5

**Recommendation:** Document the off-by-one in the spec — add a
mapping table to `phase-2-doppelbetrieb.md` §1 prologue (this audit
doc has one in §1, can be inlined upstream). DO NOT renumber the
test functions: the CI-workflow PR #115 already pins them by name.
A rename would cascade.

## 3. Folge-Items for Phase-2-Validation-Welle (KW 25-27)

The audit surfaces three Folge-Items for the Phase-2-Validation
sprint window (KW 25-27 per ADR-0058 Phase-3-Validation cadence).
All three are recommendations, not blockers for Phase-1b-to-Phase-2
promotion.

### FI-1: Add Schema-Pin-Test for 4-axis Doppelbetrieb-Score CLI output

**Owner:** Amara + Selin coordination (Zone-M via Tomás).

**Substance:** A new hermetic test that constructs a mock
Doppelbetrieb-Score JSON output and asserts:

* All four axis-fields present: `functional_equivalence`,
  `byte_delta`, `structural_equivalence`, `spurious_divergence`.
* `verdict` field present and in `{pass, warn, fail}`.
* `schema` field present and pinned to spec-canonical id.

This catches CLI-schema-drift even when the CLI itself runs on
runtime data Henrik samples. See `test_phase_2_gate_consistency_audit.py`
in this PR (FI-1 partial-implementation as audit-evidence).

**Justification:** Closes Finding F-2.

### FI-2: Spec amendment — add §2.6 Recovery-Drill-Mock gate

**Owner:** Amara (drafter), Mira (approver, since spec amendment is
QA-strategic).

**Substance:** Add a sixth acceptance-gate to
`phase-2-doppelbetrieb.md`:

> §2.6 Recovery-Drill-Mock — R1..R4 contract-surface green
>
> **Gate:** Hermetic mock-drill transcript across R1..R4 records
> `recovered=True` for every axis. Test-time proxy for the live
> stress-test-drill matrix (ADR-0058 Phase-3 §Validation).
>
> **Evidence:** `test_gate_2_4_recovery_r1_r4_mock_drill` green.
> Live-drill remains Operator-Hand-lane responsibility.
>
> **Owned-by:** Amara (test enforcement), Selin (engine recovery
> workflow).

**Justification:** Closes Finding F-1 (anchor Gate-2-4 to a spec
gate it can claim).

### FI-3: Lock-step coordination with Noa for §3 SLO numbers

**Owner:** Amara + Noa (Zone-M via Tomás, escalation to Mira if
SLO design-review changes Phase-2 promotion criteria).

**Substance:** Spec §3 SLO row p99 ≤ 45s is "vorläufig per P2".
Hermetic test hardcodes the same number. When Noa's Phase-1b
telemetry design-review produces the final SLO, both files must
move in lock-step:

* `phase-2-doppelbetrieb.md` §3 SLO row.
* `test_phase_2_acceptance_gates.py` `P99_REPLY_TIMELINESS_S` /
  `SUBSCRIBE_LAG_P99_S` constants.

A drift between the two would silently make the hermetic test
non-authoritative for the runtime SLO. Add a comment to the test
constants linking to the spec §3 row, so a future grep finds both.

## 4. Audit-Verdict

* **Phase-1b → Phase-2 promotion is not blocked by this audit.**
  All five Phase-1b acceptance-gates remain the load-bearing
  promotion criteria. The Phase-2 hermetic test-suite (PR #109)
  + CI-workflow (PR #115) provide sufficient test-time coverage
  for the Phase-2 → Phase-3 promotion contract once Phase-2 begins.
* **Three Folge-Items (FI-1, FI-2, FI-3) target the Phase-2-Validation-
  Welle (KW 25-27).** None are blockers for Phase-2 entry.
* **Audit consistency-score: 0.675** (below spec-canonical 0.95,
  driven by numbering-discipline; semantic-mapping at 0.80; coverage-
  completeness at 0.90). Recommend re-audit after FI-1/FI-2/FI-3 close.
* **Zone-N cross-check pending:** Henrik to confirm the Audit-Boundary
  on F-2 (whether Schema-Pin-Test counts as QA-substrate or as
  Audit-Sample-evidence). See `inbox/2026-05-16-amara-zone-n-sprint-qa-tag-15-quality-gates-cross-review.md`
  for the open Zone-N briefing.

— Amara
