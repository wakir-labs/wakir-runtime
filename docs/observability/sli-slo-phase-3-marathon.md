# SLI / SLO Catalogue — Phase-3 Marathon Final Pre-Cutover

**Owner:** Noa Bergstroem (SRE) · **Sprint:** Tag-52 Phase-3-Marathon Final-Pre-Cutover-SLO-Dashboard · **Status:** proposed (pending Priya CTO sign-off, Zone-I Tomas async review for SLO-2 Cross-Modul-Drift definition cross-check)

This document is the canonical SLI/SLO catalogue for the Phase-3 Marathon final pre-cutover surface. It is the rollup catalogue across the Tag-40 Marathon-Live-Coordination dashboard (operational deep-view, 71 panels), the Tag-41 Cutover-Day-Live-Stream (7 realtime panels), the Tag-30/31/32 Welle-Status emitter family, and the Tag-47/48/49 supply-chain probes. The companion dashboard renders these SLOs in `dashboards/phase-3-marathon-slo-final.json` (Tag-52, 28 panels).

Sister catalogues:

- `docs/observability/sli-slo-phase-1b.md` — Phase-1b persona-engine + Mira-Hourly stack SLOs (Tag-15 baseline).
- `docs/observability/sli-slo-wat-phase-2.md` — WAT-anchor pipeline SLOs (Tag-15).

The Phase-3 Marathon SLOs in this doc do **not** restate Phase-1b or WAT-Phase-2 SLOs; they are the **Marathon-specific** rollup. The cutover-acceptance gate is the conjunction of (this doc's "Cutover-blocking" SLOs) AND (sister-doc SLOs not in regression at the same wall-clock window).

---

## 1. Scope and non-goals

### In scope (Tag-52, Marathon final pre-cutover)

- **Welle-Cutover-Success-Rate per Welle** over a rolling 6h window. Captures the rate at which a Welle's BackendDecision-stream is shifting from fallback to the signed-off-target.
- **Cross-Modul-Drift count** as a hard-zero SLO. ADR-0066 §A1 makes any non-zero drift an immediate-rollback-trigger; this catalogue formalises the SLO surface.
- **Alert-Volume-Trend** broken out by severity (page / ticket / log). Informational SLO; alert-fatigue gate, not a release-blocker.
- **AR-Hand-Stop-Trigger-Rate** — the human-final-line marker count over the Marathon. Informational SLO; cardinality-bounded planning metric.
- **Build-Reproducibility verdict** across the 15-binary release-manifest. Tag-47 substrate.
- **SBOM-Verdict** aggregate + per-binary. Tag-49 substrate.
- **Cosign-OIDC-Drift** aggregate + per-binary + trust-root. Tag-48 substrate.

### Out of scope (deferred to Phase-3-Post-Cutover or later)

- **Per-Welle BackendDecision-latency SLO breakouts:** the Tag-30 emitter exports the latency histograms (`persona_engine_phase_3c_welle_latency_us`) but the per-Welle latency p99 < 25ms target is already covered as a Phase-1b SLO carried over to Marathon; not re-stated here.
- **Doppel-Welle Divergence-PP SLO:** the Tag-32 emitter publishes `persona_engine_doppel_welle_divergence_pct` and the Tag-50 welle-N-alerts already page on > 5pp. The SLO target itself is operator-procedural (Mira-pause-trigger), not error-budget-shaped, and is deferred to a dedicated Doppel-Welle-Coordination doc post-cutover.
- **SBOM-Generator-Run-Recency SLO:** `wakir_sbom_generator_run_timestamp_seconds` exists but its SLO is about CI-freshness rather than supply-chain-integrity; covered by the Tag-50 Welle-N CI freshness alerts.
- **Persona-Spawn-Health Dashboard SLOs:** Tag-32 persona-spawn-counter aggregates organisational health (Aisha-Schwellen). These are HR-operative SLOs and stay in `dashboards/persona-spawn-health.json` per the Tag-32 spawn-health-dashboard runbook; not Marathon-cutover-gating.
- **Federation cross-org-trust SLOs:** owned by Reza per the Zone-B cross-review allocation.

### Out-of-band: cost

Marathon-specific spawn-cost rollup is the Persona-Engine Cost-Cache dashboard (`dashboards/persona-engine-cost-cache.json`), Tag-15. Daniel (CFO) owns the budget threshold; Noa does not re-state cost SLOs here.

---

## 2. Phase-3 Marathon SLIs

Seven SLIs, each backed by a small bounded set of Prometheus gauges or counters. No metric sprawl: every SLI is justified by exactly one operator question.

### 2.1 Welle-Cutover-Success-Rate (`SLI-MARATHON-1`)

| Attribute | Value |
|---|---|
| Metric | `1 - (rate(persona_engine_phase_3c_welle_fallback_total[6h]) / clamp_min(rate(persona_engine_phase_3c_welle_decisions_total[6h]), 1e-12))` |
| Definition | Per-Welle ratio of (BackendDecisions routed to the signed-off target backend) divided by (total BackendDecisions in the window). Computed per Welle via the welle label of the Tag-30 emitter's counter family. |
| Window | 6-hour trailing |
| Rationale | Each Welle's cutover-success is the ratio of decisions landing on the signed-off backend vs. falling back. A 6h window matches the Welle-handover cadence on a Doppel-Welle day (one Welle promoted to signed-off in the morning, the second by afternoon); it is also wide enough that one stalled persona doesn't dominate the ratio. |
| Aggregation | `rate(...)` ratio per `welle` label; rollup via `sum`-without (the Tag-52 dashboard panel 12 burn-rate gauge). |
| Labels | `welle` (welle-1..welle-7) |

**SLO-1:** per-Welle success-rate >= **99%** over the 6h trailing window.

**Error budget:** 1% fallback per Welle per 6h. Burn-rate-alert thresholds (Tag-52 dashboard panel 12 + Tag-40 alert rules): 2x budget over 1h triggers a Tomas-ticket; 5x over 15 min pages the on-call.

**Justification of 99% target:** the BackendDecision-stream in Phase-1b dogfooding (Tag-9..Tag-15) showed steady-state fallback rates of 0.1-0.3% under healthy conditions. 99% gives a 3-10x headroom above baseline; sustained < 99% means the Welle's chosen backend is genuinely struggling, not a noise artefact.

**Cutover-blocking:** YES. A Welle below 99% over the trailing 6h does not progress to signed-off.

### 2.2 Cross-Modul-Drift-Rate (`SLI-MARATHON-2`)

| Attribute | Value |
|---|---|
| Metric | `wakir_cross_modul_drift_count` (aggregate) and `wakir_cross_modul_drift_count_per_welle{welle=...}` |
| Definition | Count of Phase-2-Acceptance-Gate cross-modul-stress-score excursions where the score crossed the 0.005 (0.5pp) baseline-deviation threshold during a Welle's pre/cutover/post phase. |
| Window | 24h trailing (SLO eval); instantaneous (alert) |
| Rationale | ADR-0066 §A1-Cross-Modul-Drift-Mitigation defines any drift event as an immediate-rollback-trigger. The cross-modul-stress-score is the Phase-2 Acceptance-Gate's continuous self-check that no Welle in flight is destabilising a sibling module. A non-zero count is by-design intolerable. |
| Aggregation | direct counter; `increase(...[24h])` for the trailing-window rollup. |
| Labels | `welle` (per-Welle), none (aggregate) |

**SLO-2:** drift_count == **0** over rolling 24h.

**Error budget:** **hard zero**. Cross-Modul-Drift is not budget-shaped; any RED non-zero state is a Mira+Tomas+Henrik triage event per ADR-0066.

**Justification of hard-zero target:** the cross-modul-stress-score is constructed precisely to detect the 0.5pp-above-baseline shift that ADR-0066 §A1 says we must rollback on. There is no "acceptable amount" of drift; a burst means a Welle's substrate change leaked into a sibling. The companion alert `WakirPhase3CrossModulDriftDetected` already fires page-severity at `increase(... [5m]) > 0` for 60s.

**Cutover-blocking:** YES. Any drift event triggers the ADR-0066 immediate-rollback-trigger.

### 2.3 Alert-Volume-Trend (`SLI-MARATHON-3`, informational)

| Attribute | Value |
|---|---|
| Metric | `sum by (severity) (ALERTS{alertstate="firing",phase="phase-3-marathon"})` |
| Definition | Count of currently-firing alerts broken out by severity (page / ticket / log) and filtered to the `phase="phase-3-marathon"` label that all Tag-40 / Tag-45 / Tag-50 Marathon alert-rules carry. |
| Window | 24h trailing (SLO eval); instantaneous (panel display) |
| Rationale | Alert-fatigue is itself a reliability risk per the Noa-persona blind-spot register. Sustained high page-volume during steady-state pre-cutover suggests an over-tuned alert; sustained high page-volume during cutover-day is expected operator load. This SLI is the alert-budget on the alert-budget. |
| Aggregation | direct count from the Prometheus ALERTS metric. |
| Labels | `severity` (page / ticket / log), `phase` (phase-3-marathon filter) |

**SLO-3a (steady-state, KW <24 and KW >27):** page-alerts <= **2 / 24h**.

**SLO-3b (cutover-day, KW 24-27):** page-alerts <= **20 / 24h**.

**Error budget:** 100 page-alerts per Marathon (KW-24..27, 28 days). Burn-rate breach triggers a Noa-Alert-Rule-Review (own-dogfooding, not on-call paging).

**Justification of dual-threshold target:** during steady-state pre-cutover, page-volume above 2/24h means an alert is genuinely over-tuned. During cutover-day, page-volume up to 20/24h reflects expected Welle-handover load (3-5 pages per Welle x 7 Wellen distributed across 4 weeks). Anything above 20/day is the alert-fatigue territory and triggers Noa to revise the rule, not to wake on-call faster.

**Cutover-blocking:** NO (informational). High alert volume itself is not a release-blocker; the underlying alerts are.

### 2.4 AR-Hand-Stop-Trigger-Rate (`SLI-MARATHON-4`, informational)

| Attribute | Value |
|---|---|
| Metric | `wakir_ar_hand_stop_marker_total` (monotonic counter) |
| Definition | Cumulative count of times the AR-Hand-Stop marker has been triggered during the Marathon. The marker is set by the Aufsichtsrat at planned Welle-handover checkpoints to acknowledge a Welle is ready to promote. |
| Window | Marathon-to-date (KW-24..27, 28 days) |
| Rationale | The AR-Hand-Stop is the human-final-line marker before a Welle goes signed-off. The Tag-45 B1 alert `WakirPhase3ARHandStopMissing` fires when the marker is silent at a planned checkpoint; the opposite end (too many triggers) is what this SLI measures. A higher-than-planned trigger count means either more handover-checkpoints occurred than the Marathon plan calls for, or a planning-vs-execution drift Mira and Aisha should retro on. |
| Aggregation | `max_over_time(... [28d])` for the Marathon-to-date rollup. |
| Labels | none |

**SLO-4:** AR-Hand-Stop trigger count <= **3 fires per Marathon**.

**Error budget:** 3 fires is the planned shape (Welle-1+2 handover, Welle-4+5 handover, Welle-6+7 handover). 4-5 fires is an Aisha-retro signal; 6+ fires is a planning-vs-execution drift Mira reviews.

**Justification of 3-fire target:** Phase-3-Marathon has three Doppel-Welle handover points per the ADR-0066 plan (the solo-Welle KW-25 needs one trigger embedded in the surrounding handovers). The 3-fire upper bound is a planning-fidelity check, not a reliability target.

**Cutover-blocking:** NO (informational). The trigger count itself is not a release-blocker; the Welle-state-machine is.

### 2.5 Build-Reproducibility (`SLI-MARATHON-5`)

| Attribute | Value |
|---|---|
| Metric | `wakir_build_reproducibility_drift_count` (aggregate) and `wakir_build_reproducibility_deterministic{binary=...}` (per-binary 0/1) |
| Definition | Number of binaries (out of the 15-binary release manifest) whose fingerprints are not byte-equal across the two derivation passes the Tag-47 `verify-15-binary-build-reproducibility.py` script runs. |
| Window | per CI run (the script runs in the pre-cutover daily probe workflow and on every PR touching the release manifest) |
| Rationale | A non-reproducible binary in the release-manifest means we cannot bit-for-bit verify what we shipped. The Cutover-Day-Acceptance-Gate requires all 15 binaries to be deterministic. This is one of the supply-chain pillars; the other two are SBOM-Verdict (SLO-6) and Cosign-OIDC-Drift (SLO-7). |
| Aggregation | direct counter; per-binary table at panel 52. |
| Labels | `binary` (per-binary verdict only) |

**SLO-5:** drift_count == **0** (15/15 binaries deterministic) at every cutover-acceptance gate.

**Error budget:** **hard zero**. A non-deterministic binary is release-cut-blocking per ADR-0066 §Cutover-Day-Acceptance-Gate.

**Justification of hard-zero target:** the 15-binary release manifest is the supply-chain unit-of-attestation. Allowing even one drift would invalidate the cosign-OIDC binding at the same time (re-signed because re-built differently), cascading SLO-7 fail. The hard-zero is the simplest sufficient gate.

**Cutover-blocking:** YES.

### 2.6 SBOM-Verdict (`SLI-MARATHON-6`)

| Attribute | Value |
|---|---|
| Metric | `wakir_sbom_verification_aggregate_verdict` (0/1) and `wakir_sbom_verification_per_binary_drift_count{binary=...}` |
| Definition | Aggregate verdict (1 = all 15 binaries' SBOMs match their pinned baseline within the allowed transitive-package set, 0 = at least one drifts) plus the per-binary drift-count breakdown. Source: Tag-49 `verify-15-binary-sbom-against-baseline.py`. |
| Window | per CI run (same cadence as SLO-5) |
| Rationale | An SBOM-drift means a transitive dependency shifted from the baseline. This is the supply-chain change-detection layer. A bumped transitive in a wirelang binary is Reza's review; in a wat binary Tomas'; in an orchestrator binary Kai's. The gate is on the aggregate; the deep-view is the per-binary drift-count panel. |
| Aggregation | direct gauge; per-binary table at panel 62 + timeseries at panel 63. |
| Labels | `binary` (per-binary), `verdict` (binaries-by-verdict-count) |

**SLO-6:** aggregate_verdict == **1** at every cutover-acceptance gate.

**Error budget:** **hard zero** on aggregate verdict. Per-binary drift_count > 0 is a Tier-2 ticket (review-trigger), not a release-block; aggregate == 0 (which means at least one binary's drift exceeded the allowed-transitives set) is a release-block.

**Justification of hard-zero aggregate target:** the per-binary drift_count permits small bounded drift (Cargo's transitives, supply-chain inevitability) per the Tag-49 baseline-tolerance machinery. The aggregate verdict is computed by the Tag-49 verifier against that tolerance; if it goes 0, even the tolerance-bounded baseline rejected the run.

**Cutover-blocking:** YES (on aggregate). Per-binary drift_count > 0 alone is informational.

### 2.7 Cosign-OIDC-Drift (`SLI-MARATHON-7`)

| Attribute | Value |
|---|---|
| Metric | `wakir_cosign_drift_probe_aggregate` (0/1), `wakir_cosign_drift_probe_trust_root` (0/1), `wakir_cosign_drift_probe_per_binary{binary=...}` (0/1) |
| Definition | Aggregate cosign-keyless-OIDC-binding drift signal (1 = at least one binary's cosign-verify response now binds to a different OIDC issuer/subject than the pinned baseline, 0 = all signatures bind to the expected trust-root), plus the trust-root pin verification (1 = Fulcio + Rekor trust-roots cosign-keyless validates against still match the pinned values, 0 = the trust-root rotated), plus the per-binary breakdown. Source: Tag-48 `cosign-keyless-oidc-drift-probe.py`. |
| Window | per CI run (same cadence as SLO-5, SLO-6) |
| Rationale | A drifted OIDC-binding means a binary was re-signed against a different OIDC subject (CI service-account rotation, branch-trigger change, or worst-case supply-chain attack). The trust-root pin verifies the keyless-cosign chain-of-trust itself didn't rotate underneath us. Together these two gauges are the supply-chain-integrity attestation. |
| Aggregation | direct gauges; per-binary table at panel 73. |
| Labels | `binary` (per-binary) |

**SLO-7:** aggregate == **0** AND trust_root == **1** at every cutover-acceptance gate.

**Error budget:** **hard zero** on aggregate; trust_root must be 1.

**Justification of hard-zero target:** any OIDC-binding drift on an unscheduled CI rotation is supply-chain-suspicious. Even a benign cause (CI service-account rotation we forgot to re-baseline) is a release-blocker until the baseline is updated and re-reviewed by Henrik (Internal Audit). The trust-root pin is the deeper chain-of-trust check; if it rotates, the whole keyless-cosign attestation regime needs to be re-evaluated, which is by definition out-of-cutover.

**Cutover-blocking:** YES (on aggregate AND trust_root).

---

## 3. Cutover-Acceptance Gate

The Marathon-COMPLETE 5-way conjunction (Tag-40 dashboard panel 156) is the formal Phase-3-complete marker. Tag-52 adds the SLO-rollup gate **as an additional precondition** that must hold at the moment the 5-way conjunction is evaluated:

| Gate | Source | Threshold |
|---|---|---|
| All 7 Wellen signed-off | `persona_engine_phase_3c_welle_state == 3` | 7/7 |
| Henrik Phase-3-Schluss-Audit | `wakir_henrik_audit_signoff == 1` | 1 |
| No Welle rolled-back | `persona_engine_phase_3c_welle_state == 4` count | 0 |
| Cross-Modul-Drift | `wakir_cross_modul_drift_count == 0` | 0 |
| AR-Hand-Final-Sign-Off | `wakir_ar_hand_final_signoff_phase_3 == 1` | 1 |
| **+ Tag-52 SLO-Rollup** | (this catalogue's cutover-blocking SLOs all GREEN) | all GREEN |

Where "all GREEN" = SLO-1, SLO-2, SLO-5, SLO-6, SLO-7 simultaneously within target. SLO-3 and SLO-4 are informational and do not gate.

---

## 4. Dashboard rendering

The Tag-52 dashboard renders the seven SLOs as seven row-groups (panel IDs 10..19, 20..29, 30..39, 40..49, 50..59, 60..69, 70..79) with a Marathon-Composite-Health header (panel IDs 1..4) and a doc-anchor text panel (panel 99). 28 panels total. Schema version Grafana 10.x (schemaVersion 38). UID `wakir-phase-3-marathon-slo-final`.

The dashboard intentionally does **not** restate the operational deep-views of the Tag-40 71-panel dashboard or the Tag-41 7-panel realtime view. It is the **error-budget rollup** for the AR-Pre-Cutover-Sichtung and the Cutover-Day-Morgen operator who wants ONE focused view at 06:30 CEST. The deeper investigation views remain at their existing UIDs.

---

## 5. Review cadence

- **Weekly** (Tuesday): Noa reviews SLO-1 and SLO-3 error-budget burn against the prior 7 days. If a Welle's SLO-1 burn-rate is >2x the budget, flag in the weekly Mira sync.
- **Per-Welle cutover**: Noa verifies all cutover-blocking SLOs are GREEN before the AR-Hand-Stop trigger. If any RED, signal Mira to delay the handover.
- **Per ADR change** affecting the underlying metrics: Zone-I (with Tomas for SLO-2 / WAT-relevant metrics) and Zone-H (with Kai for the Prometheus textfile-collector deployment) review the SLO doc and dashboard for label/metric-name compatibility.

---

## 6. Open follow-ups (deferred, captured here so they do not get lost)

- **Per-Welle Latency-Burn-Rate SLO** rolled up into this dashboard: currently the Tag-40 dashboard has the latency p99 per Welle but the burn-rate gauge is only computed for the aggregate. Tag-53+ deferral.
- **SLO-3 alert-fatigue heatmap** broken out per-alert-name (not just per-severity): current panel rolls all firing alerts per severity. A per-rule histogram would help identify single noisiest rules; deferred to Tag-53+.
- **SLO-2 RCA-link annotation**: when `wakir_cross_modul_drift_count` increments, the dashboard could auto-link to the Phase-2-Acceptance-Gate verdict output. Requires Grafana annotation hookup; deferred.

---

*Tag-52 SLO Catalogue, Noa Bergstroem (SRE), 2026-05-19.*
