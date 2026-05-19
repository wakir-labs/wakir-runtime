# Quality-Gate — Phase-3-Marathon-Acceptance-Pyramide (6-Layer)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Active — six-layer pyramid landed (Tag-40..Tag-52); doc-refresh Tag-53 |
| Phase | 3c (closing) — Phase-3-Marathon control-surface Definition-of-Done |
| Source | Tag-40 (#L1) -> Tag-41 (#L2) -> Tag-43 (#L3) -> Tag-44 (#L4-anti-pattern) -> Tag-45 (#L5-pre-mortem) -> Tag-52 (#L6 defence-in-depth); ADR-0066 four-Wochen-Cadence (KW-24 -> KW-27) |
| Date | 2026-05-19 (Tag-53 consolidated doc-refresh) |
| Companion (Pyramide-Validation-Audit) | `tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py` (Tag-47, structural cascade) |
| Companion (Doc-Refresh-Audit) | `tests/quality_gates/test_marathon_acceptance_pyramide_doc.py` (Tag-53, this doc's hermetic anchor) |
| Companion (Pre-Mortem-Coverage-Doc) | `docs/quality-gates/pre-mortem-failure-mode-coverage.md` (Layer-5 Tag-45/46 anchor) |
| Companion (Anti-Pattern-Doc) | `docs/quality-gates/phase-3-marathon-anti-patterns.md` (Layer-4 Tag-44 anchor) |
| Audit-Boundary | Zone N: this doc is QA-domain artefact (system-behaviour invariants). Henrik consumes the layer-table as Audit-Evidence-Index. |

## 0. Contract scope

This document is the **canonical structural map** of the Phase-3-
Marathon-Acceptance-Pyramide. It captures, in a single artefact, the
six-layer cascade of acceptance contracts that the Phase-3-Marathon
control-surface must satisfy in order to fire the Phase-3-COMPLETE
marker (`.github/workflows/phase-3-complete-marker.yml`, Tomás
Tag-40) and trigger the Phase-3-Marathon-Bilanz cascade.

The pyramid is a **cascade**, not a partition: Layer-N is structurally
dependent on Layer-1..N-1 (each layer makes claims about its
predecessors, e.g. Layer-5 introspects Layer-1..4 coverage; Layer-6
composes Layer-1..4 defence-modules). A hole anywhere in the cascade
hollows out every layer above it. The Tag-47 Pyramide-Validation-
Audit (`test_acceptance_pyramide_tag_46_validation.py`) enforces this
file-presence cascade as an executable contract.

The six layers are **complementary, not substitutive**. No layer
replaces the live-VM-acceptance-lane (operator-hand-territory,
ADR-0058 §Nachtrag) or the Audit-Trail (Henriks Zone-N domain).

This doc is **descriptive of an active substrate**, not prescriptive
of work to do. All six layers exist on `main` as of Tag-52 (PR #333
landed). Tag-53 refreshes the consolidated map after the Tag-52 Layer-
6 addition; future layers (if any) require an ADR-class change.

## 1. The six-layer canonical map

| Layer | Name | Tag-Anchor | File | Test-Count | Contract |
|---|---|---|---|---|---|
| 1 | State-Machine | Tag-40 | `tests/phase_3c/test_phase_3_final_regression.py` | 28 | Given seven sign-off-records, does the Phase-3-COMPLETE-marker fire? |
| 2 | Per-Day | Tag-41 | `tests/phase_3c/test_cutover_day_e2e_drill.py` | 45 | Does one Cutover-Mittwoch produce a correctly-shaped sign-off-record? |
| 3 | Marathon | Tag-43 | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` | 27 | Does the four-Wochen-Sequence thread the per-day records into the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-Trigger? |
| 4 | Anti-Pattern | Tag-44 | `tests/phase_3c/test_marathon_anti_patterns.py` | 20 | Does the control-surface REJECT ten dedicated control-plane anti-patterns by construction? |
| 5 | Pre-Mortem Coverage | Tag-45 | `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py` | 25 | Does the union of Layer-1..4 cover Henriks 23 Pre-Mortem failure-modes, or is each gap explicitly classified? |
| 6 | Defence-in-Depth Run-Suite | Tag-52 | `tests/phase_3c/test_defence_in_depth_layer_6.py` | 22 | Do all four A1 defence-layers fire together on a unified A1 attack-scenario, and does at least one residual layer still fire under single-layer bypass? |

Sum: 167 hermetic tests across the six layers (Tag-53 snapshot).
The numbers are not coverage-targets — they are the present substrate
size; the contract is the per-layer invariant, not the test-count.

## 2. Per-layer definitions

### 2.1 Layer-1 — State-Machine (Tag-40)

**File:** `tests/phase_3c/test_phase_3_final_regression.py`
**Test-Count (Tag-53):** 28
**Contract:** Given seven Welle sign-off-records (Welle-1..7, each a
record with `welle_id`, `kw`, `acceptance_status`, `sign_off_ts`,
`sign_off_owner`), the Phase-3-COMPLETE-marker MUST fire iff all seven
records carry `acceptance_status == "GREEN"` and are emitted in the
ADR-0066 cadence-order. The marker emit-gate is the AC-1..AC-5
conjunction defined in `.github/workflows/phase-3-complete-marker.yml`.

**Test taxonomy:**

- Aggregate-marker-fire (positive): seven-record happy-path -> marker.
- Aggregate-marker-block (negative): any-one-RED -> no marker.
- Aggregate-marker-block (structural): missing-Welle, out-of-cadence-
  order, duplicate-welle_id, late-sign-off-ts.
- Cross-Welle-disjointness: ENV-vars disjoint, focus-MODULs disjoint
  (the static substrate-level half of the A1 defence-in-depth).

**Layer-1 is the structural floor.** Every subsequent layer assumes
the marker-emit-gate exists and is well-defined.

### 2.2 Layer-2 — Per-Day (Tag-41)

**File:** `tests/phase_3c/test_cutover_day_e2e_drill.py`
**Test-Count (Tag-53):** 45
**Contract:** One Cutover-Mittwoch (the per-day live-VM-mock drill
within a single Welle's KW) MUST produce a correctly-shaped sign-off-
record consumable by Layer-1. The record-shape is the contract Layer-1
asserts at the aggregate-level; Layer-2 asserts that the per-day E2E-
flow actually produces it.

**Test taxonomy:**

- Cutover-Mittwoch happy-path: pre-flight -> deploy -> health-probe ->
  rollback-drill -> sign-off-record.
- Per-day failure-injection: any step fails -> RED sign-off-record (not
  no-record; explicit failure-signal).
- Per-day timing-contract: drill completes within the ADR-0066 quiet-
  window envelope.
- Per-day idempotency: re-runs produce identical records (deterministic
  fixture seed).

**Layer-2 is the unit-cell.** Layer-3 (Marathon) is the sequence of
Layer-2 cells over four Wochen.

### 2.3 Layer-3 — Marathon (Tag-43)

**File:** `tests/phase_3c/test_marathon_schluss_acceptance_drill.py`
**Test-Count (Tag-53):** 27
**Contract:** The four-Wochen-Sequence (KW-24..KW-27, ADR-0066
Doppel-Welle-Cadence) MUST thread the per-day records (Layer-2) into
the AC-1..AC-5 conjunction (Layer-1) across the seven Welle-slots and
the inter-KW quiet-windows. The Marathon fires the COMPLETE-marker
once the conjunction is satisfied; the Bilanz-Trigger fires once the
marker is set.

**Test taxonomy:**

- End-to-end-happy-path: four-Wochen-sequence -> marker -> Bilanz.
- Inter-KW quiet-window contract: no Welle-N-2 work bleeds into the
  KW between Welle-N and Welle-N+2.
- Aggregate-Blocker-Rejection (A1 axis-2): cross-welle drift signal
  between adjacent Wellen -> aggregate refuses to emit marker.
- Welle-cadence-order enforcement: Welle-N+1 cannot sign off before
  Welle-N.

**Layer-3 is the marathon-sequence pin.** It is the positive twin of
Layer-4 (which pins the same surface from the rejection side).

### 2.4 Layer-4 — Anti-Pattern (Tag-44)

**File:** `tests/phase_3c/test_marathon_anti_patterns.py`
**Test-Count (Tag-53):** 20
**Contract:** The control-surface MUST REJECT ten dedicated control-
plane anti-patterns by construction. Where Layer-3 pins the marathon-
sequence positively, Layer-4 pins it negatively — by enumerating ten
named anti-patterns (AP-1..AP-10) and asserting each is rejected.

**Anti-pattern axes (canonical AP-1..AP-10):** Welle-skip,
Welle-reorder, Welle-duplication, Namespace-prefix-leak (A1 axis-3),
out-of-window-sign-off, post-marker-mutation, missing-quiet-window,
double-marker-emit, stale-fixture-bypass, sign-off-impersonation.

**Layer-4 is the narrowest of the six.** Each AP pins one invariant of
the control-surface; together they form the rejection-side of the
Layer-3 marathon-sequence.

### 2.5 Layer-5 — Pre-Mortem Coverage (Tag-45)

**File:** `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py`
**Test-Count (Tag-53):** 25
**Contract:** The union of Layer-1..4 MUST cover Henriks 23 Pre-Mortem
failure-modes (the Tag-44 Pre-Mortem-Skizze A1..A12, B1..B7, C1..C4),
or each uncovered failure-mode MUST be explicitly classified as
DEFERRED / OUT-OF-SCOPE / OPERATOR-HAND with a documented rationale.

Layer-5 is a **meta-audit**: it does not re-execute Layer-1..4
invariants; it introspects (via `importlib`) the test-modules of
Layer-1..4 and asserts each Pre-Mortem failure-mode is pinned by at
least one Layer-1..4 test, or classified.

**Coverage map source-of-truth:**
`docs/quality-gates/pre-mortem-failure-mode-coverage.md`. The doc and
the executable audit are kept in sync; the audit will refuse to start
if the doc-side §0 pyramid-table contradicts the canonical
`PYRAMIDE` constant.

**Layer-5 is the coverage-pin.** It is the answer to "does the
positive+negative stack (Layer-1..4) actually cover the failure-space
Henrik enumerated?"

### 2.6 Layer-6 — Defence-in-Depth Run-Suite (Tag-52)

**File:** `tests/phase_3c/test_defence_in_depth_layer_6.py`
**Test-Count (Tag-53):** 22
**Contract:** All four A1 defence-layers (DL1 static substrate, DL2
aggregate blocker, DL3 namespace prefix, DL4 dynamic marathon-trace)
MUST fire together on a unified A1 attack-scenario; AND, under single-
layer bypass (DL1 cleared, DL2 cleared, DL3 cleared, DL4 cleared), at
least one of the remaining three layers MUST still fire on the
canonical A1 attack (defence-in-depth residual capture).

Layer-6 is qualitatively different from Layer-1..5. Layer-1..4 each
pin one contract surface; Layer-5 pins the coverage-map; Layer-6 pins
the **multi-layer atomic contract** — that the A1 defences compose,
not just exist. A1 (Cross-Modul-Drift Welle-N -> Welle-N+1) is the
sole failure-mode that traverses all four layer-axes, and Layer-6 is
the proof that no single layer is the sole gate.

**Test taxonomy (DL6-* IDs):**

- DL6-COMPOSITE-* (5): atomic composite-fire on canonical attack +
  canonical green + replay-determinism + axis-orthogonality.
- DL6-RESIDUAL-* (4): residual capture under each single-layer bypass.
- DL6-AXIS-* (4): per-layer-axis isolation.
- DL6-INTEGRATION-* (5): Tag-N substrate cross-anchor (Layer-1..4
  file-presence; Pyramide-Map Layer-6-row presence).
- DL6-INVARIANT-* (4): Layer-6-as-a-layer invariants (test-count
  bounds, file-path canonical, no cross-layer state leak).

## 3. Layer-Boundaries

Each layer has a sharp boundary; crossing a boundary is a code-smell.

| Layer | What it OWNS | What it does NOT own |
|---|---|---|
| 1 | Aggregate marker-emit-gate; record-shape contract. | Per-day flow internals; cross-welle propagation dynamics. |
| 2 | Per-day E2E-flow; record-production correctness. | Aggregate-level marker logic; cross-day sequencing. |
| 3 | Cross-Welle marathon-sequence; inter-KW quiet-window contract. | Per-day internals; control-plane anti-patterns; pre-mortem coverage. |
| 4 | Control-plane anti-pattern rejection (AP-1..AP-10). | Positive marathon-sequence (Layer-3 owns it); coverage-meta. |
| 5 | Coverage-meta — does Layer-1..4 cover Pre-Mortem? | Re-executing Layer-1..4 contracts; defence-in-depth composition. |
| 6 | Composite firing + residual capture across A1 defence-layers. | Single-layer A1 contracts (each owned by Layer-1..4); non-A1 failure-modes (Layer-5 covers those). |

**Anti-pattern: layer-bleed.** A Layer-4 anti-pattern test that
re-asserts the Layer-1 marker-emit-gate is layer-bleed; the marker-
gate is Layer-1's contract. Layer-4 tests assume Layer-1 holds, and
attack the *control-surface around it*. The Tag-47 Pyramide-Validation-
Audit enforces this implicitly via the file-presence cascade.

## 4. Cross-Layer-Invarianten

Five cross-cutting invariants tie the six layers together:

### 4.1 File-presence cascade (Tag-47 audit)

Layer-N's file MUST exist iff Layer-1..N-1's files all exist. A hole
anywhere in the cascade hollows out every layer above. Pinned by
`test_acceptance_pyramide_tag_46_validation.py` §1.

### 4.2 Layer-5 dependency-edge

Layer-5's coverage-audit MUST introspect Layer-1..4 modules (via
`importlib`) and reference each Layer-1..4 file-basename in its module-
docstring. Layer-5 cannot make coverage-claims about modules it does
not load. Pinned by `test_acceptance_pyramide_tag_46_validation.py` §3.

### 4.3 Layer-6 composition-edge

Layer-6's defence-suite MUST import the four A1 defence-modules (the
A1-relevant subsets of Layer-1..4) and exercise them on a unified
attack-scenario. Layer-6's `DL6-INTEGRATION-*` group pins each
defence-module's presence as a file-on-tree assertion.

### 4.4 Doc-table consistency

The §1 layer-map in this doc MUST be structurally identical to the
canonical `PYRAMIDE` constant in `test_acceptance_pyramide_tag_46_
validation.py` (extended for Layer-6). Specifically: the six layer-
labels, the six Tag-N origins, the six file-basenames, and Amara as
sole layer-owner MUST reconcile. Pinned by the Tag-53
`test_marathon_acceptance_pyramide_doc.py` audit.

### 4.5 Non-substitution invariant

No layer is substitutive of any other. In particular: Layer-5
(coverage-meta) does not replace Layer-1..4 (the actual contracts);
Layer-6 (defence-in-depth) does not replace any single A1 defence-
layer in Layer-1..4. The pyramid is a cascade of complementary
invariants, not a chain of refinements.

## 5. Tag-N anchor map

| Tag | Date | Layer / Action | Anchor PR / File |
|---|---|---|---|
| Tag-40 | 2026-05-15 | Layer-1 substrate | PR #266 + `test_phase_3_final_regression.py` |
| Tag-41 | 2026-05-15 | Layer-2 substrate | `test_cutover_day_e2e_drill.py` |
| Tag-43 | 2026-05-17 | Layer-3 substrate | `test_marathon_schluss_acceptance_drill.py` |
| Tag-44 | 2026-05-18 | Layer-4 substrate + Pre-Mortem-Skizze | `test_marathon_anti_patterns.py` + Henrik 23-failure-mode list |
| Tag-45 | 2026-05-18 | Layer-5 substrate | `test_pre_mortem_failure_mode_coverage_audit.py` + `docs/quality-gates/pre-mortem-failure-mode-coverage.md` |
| Tag-46 | 2026-05-18 | Layer-5 follow-ups (A2/A6/A8/B1/B3) | scoped sub-spawns; doc §4 follow-up table |
| Tag-47 | 2026-05-18 | Pyramide-Validation-Audit (structural cascade) | PR #303 + `test_acceptance_pyramide_tag_46_validation.py` |
| Tag-50 | 2026-05-18 | Pre-Mortem Coverage-Sweep consolidated Tag-44..49 | PR #323 |
| Tag-51 | 2026-05-19 | A1 Defence-Layer-4 formalisation | PR #325 + `test_a1_marathon_cascade_defence_layer_4.py` |
| Tag-52 | 2026-05-19 | Layer-6 Defence-in-Depth Run-Suite | PR #333 + `test_defence_in_depth_layer_6.py` |
| Tag-53 | 2026-05-19 | Pyramide-Doc-Refresh (this doc) | this PR + `tests/quality_gates/test_marathon_acceptance_pyramide_doc.py` |

## 6. What this doc is NOT

- NOT a release-gate. The Phase-3-COMPLETE-marker is the release-gate
  (Layer-1 contract). This doc maps the test-substrate that gives
  the marker its evidentiary weight.
- NOT a coverage-target. The test-counts in §1 are present substrate
  size, not coverage-quotas. Adding tests to inflate a layer's count
  is layer-bleed (§3 anti-pattern).
- NOT Henriks Audit-Trail. The Audit-Trail (WAT/OTS) is Henriks Zone-N
  domain. This doc is QA-Audit-Evidence-Index, complementary to —
  not substitutive of — the Audit-Trail.
- NOT a substitute for the live-VM-acceptance-lane (operator-hand-
  territory, ADR-0058 §Nachtrag). Hermetic-tests do not replace
  live-bring-up evidence.

## 7. Maintenance contract

This doc updates when, and only when, the layer-map changes:

- A new layer is added (currently six; any 7th requires an ADR-class
  change to ADR-0066's acceptance-cadence).
- An existing layer's file-path changes (file-rename / refactor).
- An existing layer's contract changes materially (semantic shift,
  not test-count drift).

Routine test-count drift, fixture-tuning, and per-layer follow-ups do
NOT require a doc-refresh. The doc captures **structure**; the test-
files capture **substance**.

Tag-53 (this refresh) is the first consolidation since the Layer-6
addition (Tag-52, PR #333). Prior to Tag-53, the layer-map was
distributed across multiple per-layer doc-files (anti-patterns, pre-
mortem-coverage, schluss-acceptance) and the executable
`PYRAMIDE` constant. Tag-53 promotes the constant to a single
descriptive doc for human reference.

— Amara
