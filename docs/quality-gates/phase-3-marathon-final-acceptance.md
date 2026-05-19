# Quality-Gate — Phase-3-Marathon Final-Acceptance (Consolidated Doc)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Active — consolidated final-acceptance doc for the Phase-3-Marathon (Tag-40..Tag-53 substrate roll-up). Pending Phase-3c-Welle-Marathon execution (ADR-0066 four-Wochen-Cadence KW-24 -> KW-27). |
| Phase | 3 (closing): single-doc Definition-of-Done across the entire Marathon control-surface. |
| Source | Tag-54 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode); roll-up of Tag-40 (#L1) -> Tag-41 (#L2) -> Tag-43 (#L3) -> Tag-44 (#L4 + 10 anti-patterns) -> Tag-45 (#L5 + 23-failure-mode coverage) -> Tag-46 (sweep) -> Tag-47 (Pyramide-Validation) -> Tag-50 (consolidated sweep) -> Tag-52 (#L6 Defence-in-Depth) -> Tag-53 (Pyramide-doc-refresh + pre-cutover-final-sanity-gate); ADR-0066 four-Wochen-Cadence; ADR-0065 Verifikations-Plan; ADR-0058 §Nachtrag (live-VM-acceptance-lane); Henrik Tag-44 Pre-Mortem-Skizze. |
| Date | 2026-05-19 (Tag-54 consolidation) |
| Test-File (this doc's hermetic anchor) | `tests/quality_gates/test_phase_3_marathon_final_acceptance_doc.py` |
| Companion (6-Layer Pyramide structural map) | `docs/quality-gates/marathon-acceptance-pyramide.md` (Tag-53) |
| Companion (Anti-Pattern surface) | `docs/quality-gates/phase-3-marathon-anti-patterns.md` (Tag-44) |
| Companion (Pre-Mortem 23-failure-mode coverage) | `docs/quality-gates/pre-mortem-failure-mode-coverage.md` (Tag-45/46/50) |
| Companion (Marathon-Schluss-DoD) | `docs/quality-gates/phase-3-marathon-schluss-acceptance.md` (Tag-43) |
| Companion (Pre-Cutover-Final-Sanity-Gate runbook) | `docs/ci/pre-cutover-final-sanity-gate-runbook.md` (Tomas Tag-53) |
| Companion (SLO catalogue) | `docs/observability/sli-slo-phase-3-marathon.md` (Noa Tag-52) |
| Companion (marker workflow) | `.github/workflows/phase-3-complete-marker.yml` (Tomas Tag-40, AC-1..AC-5) |
| Companion (sanity-gate workflow) | `.github/workflows/pre-cutover-final-sanity-gate.yml` (Tomas Tag-53, S1..S7) |
| Audit-Boundary | Zone N: this doc is QA-domain artefact. Henrik consumes the consolidated surface as Audit-Evidence-Index. No overlap with Henrik's Audit-Trail (WAT/OTS) or governance-layer compliance. |

## 0. Contract scope

This document is the **consolidated Marathon-Final-Acceptance Definition-of-Done**
for the Phase-3c-Welle-Marathon. It is the single artefact that an
acceptance-gate consumer (Tomas, Henrik, Mira, Aufsichtsrat) reads
to answer "what does the Phase-3-Marathon control-surface have to
satisfy to fire the Phase-3-COMPLETE-marker?", without having to
cross-reference the six companion docs.

This doc does **not** replace any companion. Each companion remains
the source-of-truth for its sub-surface:

| Sub-surface | Source-of-truth (NOT this doc) |
|---|---|
| 6-Layer Pyramide structural map | `marathon-acceptance-pyramide.md` (Tag-53) |
| 10 Anti-Pattern axes (AP-1..AP-10) | `phase-3-marathon-anti-patterns.md` (Tag-44) |
| 23 Pre-Mortem failure-mode coverage classification | `pre-mortem-failure-mode-coverage.md` (Tag-45/46/50) |
| AC-1..AC-5 marker-emit-gate predicate | `.github/workflows/phase-3-complete-marker.yml` (Tomas Tag-40) |
| 7 SLO catalogue (SLI/SLO-MARATHON-1..7) | `sli-slo-phase-3-marathon.md` (Noa Tag-52) |
| S1..S7 Pre-Cutover-Final-Sanity-Gate substrates | `pre-cutover-final-sanity-gate.yml` + runbook (Tomas Tag-53) |
| Marathon-Schluss positive-sequence DoD | `phase-3-marathon-schluss-acceptance.md` (Tag-43) |

This doc is **descriptive of an active substrate**, not prescriptive
of work to do. All five conjunctive surfaces below exist on `main`
as of Tag-53 (PR #345 landed). Tag-54 consolidates them into a
single Final-Acceptance contract for human + audit reference.

The Final-Acceptance contract is **complementary, not substitutive**:
none of the five surfaces below replaces the live-VM-acceptance-lane
(operator-hand-territory, ADR-0058 §Nachtrag) or the Audit-Trail
(WAT/OTS, Henriks Zone-N domain).

## 1. The Marathon-Final-Acceptance five-surface conjunction

The Phase-3-COMPLETE-marker (`.github/workflows/phase-3-complete-marker.yml`,
Tomas Tag-40) fires **iff** all five surfaces below are simultaneously
green at the Welle-7 sign-off-Freitag (KW-27, 2026-07-03 17:00 CEST per
ADR-0066 cadence):

| Surface | Anchor | Cardinality | Source-of-truth |
|---|---|---|---|
| **Surface-1 — AC-1..AC-5 conjunction** | Marker-emit-predicate | 5 conjuncts | `.github/workflows/phase-3-complete-marker.yml` (Tomas Tag-40) |
| **Surface-2 — 6-Layer Acceptance-Pyramide** | Test-substrate cascade | 6 layers | `docs/quality-gates/marathon-acceptance-pyramide.md` (Tag-53) |
| **Surface-3 — 10 Anti-Pattern rejection (AP-1..AP-10)** | Control-plane rejection | 10 axes | `docs/quality-gates/phase-3-marathon-anti-patterns.md` (Tag-44) |
| **Surface-4 — 23 Pre-Mortem failure-mode coverage** | Failure-space attestation | 23 (per Henrik), 24 table-rows | `docs/quality-gates/pre-mortem-failure-mode-coverage.md` (Tag-45/46/50) |
| **Surface-5 — 7 SLO catalogue (SLI/SLO-MARATHON-1..7)** | Operational health | 7 SLIs / 7 SLOs (4 cutover-blocking, 3 informational) | `docs/observability/sli-slo-phase-3-marathon.md` (Noa Tag-52) |

Plus the **Pre-Cutover-Final-Sanity-Gate (S1..S7)** as the
Monday-morning final-readiness probe before any KW-N Cutover-Mittwoch:

| Pre-Gate | Anchor | Cardinality | Source-of-truth |
|---|---|---|---|
| **Surface-Pre — S1..S7 Pre-Cutover-Final-Sanity-Gate** | Pre-KW-N readiness | 7 substrates (READY / CAUTION / BLOCK) | `.github/workflows/pre-cutover-final-sanity-gate.yml` + `docs/ci/pre-cutover-final-sanity-gate-runbook.md` (Tomas Tag-53) |

The Surface-Pre is **not** a marker-emit-gate; it is a Monday
05:00 UTC pre-flight that gates the Wednesday auto-scheduler. A
`BLOCK` verdict blocks the cutover-day from being scheduled at
all; the marker-emit-gate (Surface-1..5) does not run if the
Cutover-Mittwoch was never reached.

## 2. Surface-1 — AC-1..AC-5 conjunction (marker-emit-gate)

Per `.github/workflows/phase-3-complete-marker.yml` §Emit-step
predicate. The marker writes `state/phase-3-complete-marker.json`
iff the Boolean conjunction AC-1 AND AC-2 AND AC-3 AND AC-4 AND
AC-5 evaluates true.

| AC | Anchor | Source artefact | Gate |
|----|--------|-----------------|------|
| **AC-1** | Seven welle-sign-offs | `state/welle-{1..7}-sign-off.json` | All seven present, status in `{green, yellow_henrik_hand_approval}` |
| **AC-2** | Aggregate validation green | `phase-3c-welle-{1..7}-validation.yml` workflows on main HEAD | All seven workflows `conclusion=success` |
| **AC-3** | Predecessor closure | `state/phase-3{a,b,c}-closure.json` | Phase-3a=15/15, Phase-3b=9/9, Phase-3c=7/7 attested |
| **AC-4** | Henrik R-A1..R-A6 ratification | `state/henrik-phase-3-complete-ratification.json` | `aggregate_verdict="ratified"` |
| **AC-5** | AR-Hand stamp (IIA-1130) | `state/ar-hand-phase-3-complete-stamp.json` | `ar_hand_ratification=True` + non-empty `ar_hand_quote` |

**IIA-1130 anchor (AC-5).** Per Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle:
the marker setting is mechanical-executive (workflow emits the file);
Internal Audit RATIFIES (AC-4), AR-Hand RATIFIES FINAL (AC-5). At no
point is Internal Audit the marker-actor.

**False-positive contract.** The marker MUST NOT fire under any of:

| Condition | Failing gate |
|---|---|
| Welle-3 rolls back | Cascade-block (state-machine) + AC-1 (downstream wellen pending) |
| Welle-7-Pre-Auditor-Decision missing | KW-27 bundle `is_green=False` + AC-5 quote empty |
| Cross-modul drift Welle-4-vs-5 > 0 (blocker) | State-machine drift-aggregation `"blocker"` |
| 6/7 sign-offs (any one missing) | AC-1 fails (count != 7) |
| KW-26 partial Doppel-Welle sign-off | KW-26 bundle `is_green=False` + AC-1 (count=6) |
| AC-4 Henrik aggregate_verdict="blocked" | AC-4 fails (Bilanz-Trigger surfaces "AC-4") |
| AC-5 AR-Hand-quote empty/whitespace | AC-5 fails (IIA-1130 anchor broken) |

## 3. Surface-2 — 6-Layer Acceptance-Pyramide

The six-layer hermetic test cascade. Each Layer-N is structurally
dependent on Layer-1..N-1 (Tag-47 file-presence cascade). A hole
in any layer hollows out every layer above it.

| Layer | Name | Tag-Anchor | File | Test-Count (Tag-53) | Contract |
|---|---|---|---|---|---|
| 1 | State-Machine | Tag-40 | `tests/phase_3c/test_phase_3_final_regression.py` | 28 | Given seven sign-off-records, does the Phase-3-COMPLETE-marker fire? |
| 2 | Per-Day | Tag-41 | `tests/phase_3c/test_cutover_day_e2e_drill.py` | 45 | Does one Cutover-Mittwoch produce a correctly-shaped sign-off-record? |
| 3 | Marathon | Tag-43 | `tests/phase_3c/test_marathon_schluss_acceptance_drill.py` | 27 | Does the four-Wochen-Sequence thread the per-day records into the AC-1..AC-5 conjunction, fire the marker, fire the Bilanz-Trigger? |
| 4 | Anti-Pattern | Tag-44 | `tests/phase_3c/test_marathon_anti_patterns.py` | 20 | Does the control-surface REJECT ten dedicated control-plane anti-patterns by construction? |
| 5 | Pre-Mortem Coverage | Tag-45 | `tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py` | 25 | Does the union of Layer-1..4 cover Henriks 23 Pre-Mortem failure-modes, or is each gap explicitly classified? |
| 6 | Defence-in-Depth Run-Suite | Tag-52 | `tests/phase_3c/test_defence_in_depth_layer_6.py` | 22 | Do all four A1 defence-layers fire together on a unified A1 attack-scenario; does at least one residual layer still fire under single-layer bypass? |

**Sum (Tag-53 snapshot):** 167 hermetic tests across the six layers.
The test-counts are *present substrate size*, not coverage-quotas.
The contract is the per-layer invariant, not the test-count.

**Layer-boundaries.** Each layer has a sharp boundary; crossing it
is the layer-bleed anti-pattern (per `marathon-acceptance-pyramide.md`
section 3). The Tag-47 Pyramide-Validation-Audit
(`tests/phase_3c/test_acceptance_pyramide_tag_46_validation.py`)
enforces file-presence cascade as an executable contract.

## 4. Surface-3 — 10 Anti-Pattern axes (AP-1..AP-10)

Per `docs/quality-gates/phase-3-marathon-anti-patterns.md` (Tag-44).
The control-surface MUST REJECT each AP by construction; the Layer-4
suite (Tag-44, 20 tests) pins each AP-rejection as an executable
invariant.

| AP | Name | Production-anchor |
|---|---|---|
| **AP-1** | Phase-3-COMPLETE-Marker race | `concurrency.group=phase-3-complete-marker` + `cancel-in-progress: false` |
| **AP-2** | Welle-Sign-Off replay | `state/welle-{N}-sign-off.json` PR-merge idempotency-ledger |
| **AP-3** | Audit-Trail corruption (Self-Reference-Trap Welle-3) | `docs/runbooks/welle-3-bridge-audit-writer-cutover.md` drain-before-activate |
| **AP-4** | Cross-Welle FSM-state-leak | Namespace-prefix discipline (state-backing per-welle prefix) |
| **AP-5** | Sign-Off timestamp drift | ADR-0066 cadence-ISO sign-off-Freitag pinning |
| **AP-6** | AR-Hand ratification bypass | AC-5 non-empty `ar_hand_quote` predicate |
| **AP-7** | IIA-1130 Welle-7 self-audit trap | AR-Hand-Pre-Auditor-Decision substitute control |
| **AP-8** | Cutover-day timing drift | Per-day timing-contract within ADR-0066 quiet-window |
| **AP-9** | Rollback cascade | Cascade-block on first Welle-rollback |
| **AP-10** | COMPLETE-marker false-positive via empty state-files | AC-1..AC-5 non-empty-content predicate |

Layer-4 is the *narrowest* of the six pyramid layers: each AP-axis
pins one invariant of the control surface itself, not one Welle-state
outcome.

## 5. Surface-4 — 23 Pre-Mortem failure-mode coverage

Per `docs/quality-gates/pre-mortem-failure-mode-coverage.md` (Tag-45,
Tag-46 sweep, Tag-50 consolidated). Henrik's Tag-44 Pre-Mortem-Skizze
enumerates 23 hypothetical failure-modes in four classes:

| Class | Modes | Description |
|---|---|---|
| **Class-A — Technisch** | A1..A8 (8 modes) | Cross-Modul-Drift, FSM-Phantom-Transitions, State-Migration-Failure, NATS-Mode-Mismatch, Self-Reference-Trap-Fire, Cosign-Verification-Drift, Persona-Engine-Sprach-Drift, NATS-JetStream-Loss-Recovery |
| **Class-B — Operativ** | B1..B6 (6 modes) | AR-Hand-Stop-Marker-Missing-Trigger, Sign-Off-Sequenz-Bruch, Pre-Auditor-Konflikt Welle-3, Pre-Auditor-Konflikt Welle-7, Spawn-Collision >30/Tag, Persona-Sleep-Watch-Bruch |
| **Class-C — Prozedural** | C1..C5 (5 modes) | COMPLETE-Marker-False-Positive, AR-Ratifikation-Race, Public-Communication-Premature, ADR-Substanz-False-Premise, YAML-Frontmatter-Disziplin-Bruch |
| **Class-D — Externe** | D1..D5 (5 modes) | GitHub-API-Outage, NATS-Service-Failure auf Pilot-VM, Cosign-Verification-Drift (sigstore/Fulcio external), Cloud-Provider-Throttling, OpenTimestamps-Calendar-Outage |

**Naming note (Tag-50 section 3).** Henrik's section 6 names *"23 hypothetische
Failure-Modes"* but the table-row count is A8 + B6 + C5 + D5 = 24.
Henrik notes "einzelne ID-Luecken durch Klassifikations-Defaultpfad"
in section 6. The coverage matrix uses the 24 table-row count as canonical
denominator; the task framing uses Henrik's "23" headline number.
Both refer to the same coverage surface.

**Coverage classification (Tag-50 consolidated):**

| State | Count | % | Meaning |
|---|---|---|---|
| **COVERED** | 12 | 50.0% | At least one Layer-1..5 test directly asserts the invariant the failure-mode would violate. |
| **PARTIAL** | 2 | 8.3% | Indirect coverage with a Tag-46+ follow-up named (A2 FSM-Phantom-Transitions, B3 Pre-Auditor-Konflikt Welle-3). |
| **GAP-ACCEPTED** | 10 | 41.7% | Structurally out-of-scope: 5 external D-class (D1..D5), 3 governance-layer (B5/B6/C4), 2 site-repo / operator-hand (C3/C5). |
| **GAP-OPEN** | 0 | 0.0% | No failure-mode has no path forward. |

**Layer-5 is a meta-audit.** It does not re-execute Layer-1..4
invariants; it introspects (via `importlib`) the test-modules of
Layer-1..4 and asserts each Pre-Mortem failure-mode is pinned by at
least one Layer-1..4 test, or classified.

## 6. Surface-5 — 7 SLO catalogue (SLI/SLO-MARATHON-1..7)

Per `docs/observability/sli-slo-phase-3-marathon.md` (Noa Tag-52).
Seven SLIs, four cutover-blocking, three informational:

| SLI ID | Name | SLO target | Window | Cutover-blocking? |
|---|---|---|---|---|
| **SLI-MARATHON-1** | Welle-Cutover-Success-Rate | >= 99% per-Welle | 6h trailing | **YES** |
| **SLI-MARATHON-2** | Cross-Modul-Drift-Rate | == 0 (hard zero) | 24h trailing | **YES** |
| **SLI-MARATHON-3** | Alert-Volume-Trend | informational | n/a | no |
| **SLI-MARATHON-4** | AR-Hand-Stop-Trigger-Rate | informational | n/a | no |
| **SLI-MARATHON-5** | Build-Reproducibility | per-binary green | per-build | **YES** |
| **SLI-MARATHON-6** | SBOM-Verdict | aggregate + per-binary green | per-build | **YES** |
| **SLI-MARATHON-7** | Cosign-OIDC-Drift | zero drift | per-build | **YES** |

**Cutover-Acceptance Gate (SLO conjunction).** A Welle does not
progress to signed-off if any cutover-blocking SLO is RED at the
Welle's cutover-Mittwoch. The Phase-3-COMPLETE-marker is not
emittable if any cutover-blocking SLO is RED on the Welle-7
sign-off-Freitag.

**Out-of-scope for this surface:** per-Welle BackendDecision-latency
SLO (Phase-1b carry-over), Doppel-Welle Divergence-PP SLO
(operator-procedural), SBOM-Generator-Run-Recency SLO (CI freshness),
Persona-Spawn-Health Dashboard SLOs (Aisha HR-operative), Federation
cross-org-trust SLOs (Reza Zone-B).

## 7. Surface-Pre — Pre-Cutover-Final-Sanity-Gate (S1..S7)

Per `.github/workflows/pre-cutover-final-sanity-gate.yml` +
`docs/ci/pre-cutover-final-sanity-gate-runbook.md` (Tomas Tag-53).
Monday 05:00 UTC pre-flight, gates the Wednesday auto-scheduler.

| ID | Substrate | Owning persona / PR |
|---|---|---|
| **S1** | engine_manifest (0.5.2-final + pin-pack parity) | Selin PR #336 (Tag-52) |
| **S2** | spec_freeze (v0.4.3-freeze marker) | Reza PR #338 (Tag-53) |
| **S3** | 15-binary SBOM substrate | Kai PR #311 (Tag-48) |
| **S4** | build-reproducibility-daily | Noa (Tag-46) |
| **S5** | cosign-OIDC drift + verify-images | Kai PR #307 (Tag-47) |
| **S6** | welle-probes (7 pre-cutover + 5 hot-spot) | Reza / Selin (Tag-40..Tag-45) |
| **S7** | marathon-tracker + tracker-gate | Selin PR #261 (Tag-40) |

**Decision rule:**

* `READY`   - all seven substrates green.
* `CAUTION` - 1..2 substrates yellow, zero red.
* `BLOCK`   - any substrate red, OR three or more yellow.

The threshold `yellows>=3 -> BLOCK` is **tighter** than the four-
substrate Tag-41 gate (`yellows>=2 -> BLOCK` there). Seven substrates
carry more redundancy. A `BLOCK` blocks the auto-scheduler at the
07:00 UTC trigger; the Cutover-Mittwoch does not start.

## 8. Marathon-Bilanz-Trigger (post-marker)

Once the Phase-3-COMPLETE-marker is set green, the **Phase-3-Marathon-
Bilanz-Trigger** fires. The trigger is the input-event for the Noa
Tag-43 Phase-3-Bilanz-Generator
(`.github/workflows/phase-3-marathon-final-bilanz.yml`).

Trigger payload schema (`BilanzTrigger` dataclass, pure-fn derivation
from marathon + AC-1..AC-5):

```python
@dataclass(frozen=True)
class BilanzTrigger:
    fires: bool
    marker_iso: str = ""
    kw_24_signoff_iso: str = ""
    kw_25_signoff_iso: str = ""
    kw_26_signoff_iso: str = ""
    kw_27_signoff_iso: str = ""
    welle_signoff_count: int = 0
    blocking_reasons: Tuple[str, ...] = ()
```

Firing rules:

* `fires=True` iff AC-1..AC-5 all green (i.e. marker emitted).
* If `fires=False`, `blocking_reasons` carries the failing AC IDs
  (e.g. `("AC-1", "AC-5")`).
* `marker_iso` is the workflow-emit-time; chronologically after
  `kw_27_signoff_iso`.
* `welle_signoff_count` mirrors AC-1 count (7 on green).

## 9. The four-KW Marathon-Cadence (ADR-0066)

| KW | Pattern | Wellen | Modul(e) | Cutover-Mittwoch | Sign-Off-Freitag |
|----|---------|--------|----------|------------------|------------------|
| KW-24 | Doppel-Welle-1+2 (parallel) | 1, 2 | `v907_verify`, `svid_workload_identity` | 2026-06-10 09:00 CEST | 2026-06-12 17:00 CEST |
| KW-25 | Solo-Welle-3 | 3 | `bridge_audit_writer` | 2026-06-17 09:00 CEST | 2026-06-19 17:00 CEST |
| KW-26 | Doppel-Welle-4+5 (parallel) | 4, 5 | `state_backing`, `lifecycle_state_machine` | 2026-06-24 09:00 CEST | 2026-06-26 17:00 CEST |
| KW-27 | Doppel-Welle-6+7 (parallel) | 6, 7 | `subscribe_loop`, `recovery_workflow` | 2026-07-01 09:00 CEST | 2026-07-03 17:00 CEST |

KW-27 is the Phase-3-Schluss-slot; IIA-1130 Welle-7-Pre-Auditor-
Decision required on the Welle-7 cutover-Mittwoch (2026-07-01).

## 10. Zone-N coordination with Internal Audit

Per ADR-0044 section Zone-N (Amara-Henrik boundary):

* QA-evidence in this doc is **complementary** to Henrik's audit-
  sample. The test-substrate behind Surface-1..5 is *not* a substitute
  for Henrik's Welle-6+7-Pre-Audit-Bundle, the Cutover-Day-Audit-
  Sample, or the Aggregate-Phase-3-Schluss-Audit-Spec.
* The marker-emit-event is **AR-Hand-ratified** (AC-5), not Henrik-
  ratified (IIA-1130 anchor). Henrik retains independent sampling
  rights on the rollback-cascade audit-trail.
* Henrik's Welle-7-Pre-Auditor-Decision sample at Welle-7 cutover-day
  consumes the `Welle7PreAuditorDecision` shape Surface-1 carries as
  the contract-anchor.
* This consolidated Tag-54 doc is QA-Audit-Evidence-Index, not Audit-
  Trail. The Audit-Trail (WAT/OTS) is Henriks Zone-N domain.

## 11. What this doc is NOT

* **NOT a release-gate.** The Phase-3-COMPLETE-marker is the release-
  gate (Surface-1 AC-1..AC-5 conjunction). This doc consolidates the
  acceptance-conditions that give the marker its evidentiary weight.
* **NOT a coverage-target.** The cardinality numbers (5 AC, 6 layers,
  10 AP, 23 failure-modes, 7 SLO, 7 S-substrates) are *present
  substrate size*, not coverage-quotas. Adding tests / SLOs / S-
  substrates to inflate any count is layer-bleed.
* **NOT Henriks Audit-Trail.** The Audit-Trail (WAT/OTS) is Henriks
  Zone-N domain. This doc is QA-Audit-Evidence-Index, complementary
  to - not substitutive of - the Audit-Trail.
* **NOT a substitute for the live-VM-acceptance-lane** (operator-hand-
  territory, ADR-0058 section Nachtrag). Hermetic-tests do not replace live-
  bring-up evidence.
* **NOT a substitute for any companion doc.** Each companion remains
  the source-of-truth for its sub-surface (see section 0 table). This doc
  is the consolidated roll-up index, not a re-derivation.

## 12. Maintenance contract

This doc updates when, and only when, the five-surface conjunction
shape changes:

* A new surface is added (currently five Marathon-acceptance surfaces +
  one pre-cutover-sanity surface; any 6th Marathon-acceptance surface
  requires an ADR-class change to the marker-emit predicate).
* An existing surface's source-of-truth file path changes (companion
  rename / refactor - keep the section 0 table coherent).
* An existing surface's cardinality changes materially (e.g. 6 -> 7
  Pyramide-layers requires a synchronised refresh here AND in
  `marathon-acceptance-pyramide.md`).

Routine per-surface drift (test-count drift in Pyramide layers, AP-
text refinement, Pre-Mortem follow-up state transitions, SLO threshold
tuning, S-substrate ownership rotation) does NOT require a doc-refresh
here. The doc captures **the consolidated five-surface shape**; the
companion docs capture **per-surface substance**.

Tag-54 (this consolidation) is the first roll-up since the Tag-53
Pyramide-doc-refresh + Pre-Cutover-Final-Sanity-Gate landing. Prior
to Tag-54, the five-surface shape was distributed across the six
companion docs and the marker-workflow predicate. Tag-54 promotes
the consolidated shape to a single descriptive doc for human +
audit-evidence reference.

## 13. Tag-N anchor map

| Tag | Date | Surface contribution | Anchor PR / File |
|---|---|---|---|
| Tag-40 | 2026-05-15 | Surface-1 marker-workflow + Surface-2 Layer-1 substrate | PR #266 + `phase-3-complete-marker.yml` + `test_phase_3_final_regression.py` |
| Tag-41 | 2026-05-15 | Surface-2 Layer-2 substrate + Pre-cutover-sanity-gate (4-substrate baseline) | `test_cutover_day_e2e_drill.py` + `phase-3c-pre-cutover-sanity.yml` |
| Tag-43 | 2026-05-17 | Surface-2 Layer-3 substrate + Marathon-Schluss-DoD + Bilanz-Trigger contract | `test_marathon_schluss_acceptance_drill.py` + `phase-3-marathon-schluss-acceptance.md` |
| Tag-44 | 2026-05-18 | Surface-3 (10 AP axes) + Surface-2 Layer-4 substrate + Henrik 23-Pre-Mortem-Skizze | `test_marathon_anti_patterns.py` + `phase-3-marathon-anti-patterns.md` |
| Tag-45 | 2026-05-18 | Surface-4 (23-Pre-Mortem coverage) + Surface-2 Layer-5 substrate | `test_pre_mortem_failure_mode_coverage_audit.py` + `pre-mortem-failure-mode-coverage.md` |
| Tag-46 | 2026-05-18 | Surface-4 sweep (A2/A6/A8/B1/B3) | scoped sub-spawns + doc section 4 follow-ups |
| Tag-47 | 2026-05-18 | Surface-2 Pyramide-Validation-Audit (structural cascade) | PR #303 + `test_acceptance_pyramide_tag_46_validation.py` |
| Tag-50 | 2026-05-18 | Surface-4 consolidated sweep Tag-44..49 | PR #323 + `test_pre_mortem_coverage_sweep_tag_50_consolidated.py` |
| Tag-52 | 2026-05-19 | Surface-2 Layer-6 substrate + Surface-5 (7 SLO catalogue) | PR #333 + `test_defence_in_depth_layer_6.py` + `sli-slo-phase-3-marathon.md` |
| Tag-53 | 2026-05-19 | Surface-Pre (S1..S7 Sanity-Gate) + Pyramide-doc-refresh | PR #339 + PR #341 + `pre-cutover-final-sanity-gate.yml` + `marathon-acceptance-pyramide.md` |
| Tag-54 | 2026-05-19 | **This consolidated Final-Acceptance doc** | this PR + `tests/quality_gates/test_phase_3_marathon_final_acceptance_doc.py` |

— Amara
