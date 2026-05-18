<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Pre-Mortem Failure-Mode Notify-Catalog

**Owner:** Noa Bergstroem (SRE) - Tag-45
**Anchor:** Henrik Tag-44 Pre-Mortem-Skizze
(`reports/audit/phase-3-marathon-pre-mortem-2026-05-18.md`)
**Companion artifact:** `dashboards/phase-3-marathon-alerts.yaml`
**Companion dashboard panels:** 180-184 (Tag-45 Cross-Welle-Hot-Spot
row in `dashboards/phase-3c-cross-welle-coordination.json`)
**Status:** proposed (pending Henrik cross-review + Kai Zone-H
deployment substrate review)

---

## 1. Scope

This catalogue maps each Henrik Tag-44 Pre-Mortem failure-mode that
has a Tag-45 alert rule to:

1. The Prometheus alert rule (`alert:` name in
   `phase-3-marathon-alerts.yaml`).
2. The detection thresholds and `for:` window with rationale.
3. The notify path (severity + receivers + side effects).
4. The runbook anchor.
5. The Pre-Mortem failure-mode-ID and mitigation anchor.

Out of scope: Class-A3, A6, A7, A8, B2, B4, B5, B6, C2, C3, C4, C5,
D1..D5. These either lack a direct counter (A3/A8 state-migration
ride on existing welle-rollback alert), already have coverage in
the Tag-40 baseline (A6 cosign-verify drift via cross-substrate-
parity-gate), or are tracked in non-Prometheus instruments
(spawn-collision via Aggregator-Workflow, comms premature via
site-repo-PR-review). They are listed in Section 4 with their
existing detection anchor.

---

## 2. Alert-Rule Threshold + Notify-Path Catalogue

### 2.1 Class-A1 - Cross-Modul-Drift per-welle early-warning

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeA1CrossModulDriftPerWelle` |
| Source metric | `wakir_cross_modul_drift_count_per_welle{source_welle, target_welle}` |
| Threshold | `> 0` |
| For-window | `2m` (tolerates two 60s scrape cycles) |
| Severity | `page` |
| Notify path | PagerDuty (sre-oncall) + ntfy (ar-hand) + activity-log append |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-a1-cross-modul-drift` |
| Pre-Mortem-ID | A1 |
| Mitigation anchor | Tag-39 Cross-Welle-Cutover-Spec; PRE-Audit-Evidence pro Welle |
| Rationale | The Tag-40 baseline alert (`WakirPhase3CrossModulDriftDetected`) fires on the **aggregate** counter. The per-welle counter triggers earlier when only one Welle-pair has drift, so Welle-3 -> Welle-4 hot-spot lights up before global aggregate ticks. `for: 2m` rather than `5m` to surface the propagation faster; this is acceptable because the per-welle counter is less noisy than the aggregate. |

### 2.2 Class-A2 - FSM-Phantom-Transitions

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeA2FsmPhantomTransition` |
| Source metric | `wakir_lifecycle_fsm_illegal_transition_total{welle, from_state, to_state}` |
| Threshold | `> 0` |
| For-window | `60s` |
| Severity | `page` |
| Notify path | PagerDuty (sre-oncall) + ntfy (ar-hand) + activity-log append |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-a2-fsm-phantom` |
| Pre-Mortem-ID | A2 |
| Mitigation anchor | Reza Tag-37 Replay-Engine; state-backing-Validierung Welle-4 |
| Rationale | Illegal FSM transitions are never tolerated post-cutover; threshold of `> 0` after one scrape cycle (60s) is appropriate. The metric is exposed by the lifecycle-state-machine bin (Reza Tag-37); if absent in a scrape Prometheus will not fire on stale data. |

### 2.3 Class-A4 - NATS-Mode-Mismatch (Tag-41 Bug-42-Klasse)

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeA4NatsModeMismatch` |
| Source metric | `wakir_nats_mode_mismatch_total{subject, publisher_mode, subscriber_mode}` |
| Threshold | `> 0` |
| For-window | `60s` |
| Severity | `page` |
| Notify path | PagerDuty (sre-oncall) + activity-log append |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-a4-nats-mode-mismatch` |
| Pre-Mortem-ID | A4 |
| Mitigation anchor | Tag-41 Bug-42-Fix-PR; NATS-Mode-Assertion on Live-VM |
| Rationale | Tag-41 Bug-42 introduced the counter; CI-Acceptance-Gate (live-fcos-VM) is supposed to catch the regression in pre-deployment. The Prometheus rule is the deployment-time safety net. Single-scrape threshold is sufficient because the metric only increments on actual assertion failures. |

### 2.4 Class-A5 - Self-Reference-Trap Welle-3 (KW-25 CRITICAL)

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeA5SelfReferenceTrapWelle3Critical` |
| Source metric | `persona_engine_backend_decision_total{welle="welle-3", subject="audit-bridge"}` rate-ratio vs. 24h-offset baseline |
| Threshold | `>= 3` (rate / baseline ratio) |
| For-window | `2m` |
| Severity | `page` |
| Notify path | PagerDuty (sre-oncall) + ntfy (ar-hand-critical) + activity-log append + Henrik IIA-1130-trigger |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-a5-self-reference-trap` |
| Pre-Mortem-ID | A5 |
| Mitigation anchor | Welle-3 IIA-1130-Pre-Decision-Spec; AR-designated extern Pre-Auditor for Welle-3 audit |
| Rationale | Henrik Pre-Mortem Worst-Case 2.1 cites a +340% spike at T+12min as the first sign of the recursion loop. The 3x threshold catches the spike with margin while staying robust against normal small fluctuations. `for: 2m` to require persistence (not a single scrape blip). The IIA-1130-trigger side-effect documents the policy: AR-Hand must designate an external pre-auditor; Henrik must NOT self-audit. The 15s scrape interval (vs. 30s elsewhere) reflects the elevated criticality of Welle-3 SOLO. |

### 2.5 Class-B1 - AR-Hand-Stop-Marker-Missing-Trigger

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeB1ArHandStopMissingTrigger` |
| Source metrics | `wakir_cross_modul_drift_count > 0` AND `increase(wakir_ar_hand_stop_marker_total[5m]) == 0` |
| Threshold | conjunction holds |
| For-window | `5m` |
| Severity | `page` |
| Notify path | ntfy (ar-hand-critical) + activity-log append + Henrik audit-trail |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-b1-ar-hand-stop-missing` |
| Pre-Mortem-ID | B1 |
| Mitigation anchor | Cutover-Day-Audit-Spec §1 Marker-Trigger-Pflicht; ADR-0019 §6 |
| Rationale | This is the meta-alert: drift is present BUT the AR-Hand-Stop-Marker did not fire. Per Cutover-Day-Audit-Spec the marker trigger is Pflicht; this alert surfaces the gap between observed risk and operative response. The notify path bypasses PagerDuty (which goes to sre-oncall) and goes direct to AR-Hand because the absence is a governance signal, not a service signal. |

### 2.6 Class-B3 - Welle-3 IIA-1130-Default-Path (warning)

| Field | Value |
|---|---|
| Alert | `WakirPhase3FailureModeB3Iia1130DefaultPath` |
| Source metric | `wakir_welle_schluss_audit_signoff{welle="welle-3", auditor}` |
| Threshold | conjunction: `auditor="henrik" == 1` AND `auditor="external-pre-auditor" == 0` |
| For-window | `1m` |
| Severity | `warning` |
| Notify path | ntfy (ar-hand-info) + activity-log append |
| Runbook | `https://wakir-labs.example/runbooks/failure-mode-b3-iia-1130-default` |
| Pre-Mortem-ID | B3 |
| Mitigation anchor | Welle-3-IIA-1130-Pre-Decision-Spec; AR-Hand-Entscheidung steht aus |
| Rationale | Per Henrik Pre-Mortem B3 has **low probability** (spec gesetzt) but **high impact** if ignored. Warning rather than page because the IIA-1130 decision is an AR-Hand-Governance-Entscheidung, not an on-call response. The ntfy `ar-hand-info` channel is non-urgent. |

### 2.7 Class-C1 - Marker-False-Positive granular sentinels

Two granular alerts cover the two most-likely drift conditions:

| Alert | Condition | Notify path |
|---|---|---|
| `WakirPhase3FailureModeC1MarkerFalsePositiveCond1` | AC-1 (all 7 wellen state==4) reads true while some welle reports state != 4 | PagerDuty (sre-oncall) + activity-log + Henrik marker-audit |
| `WakirPhase3FailureModeC1MarkerFalsePositiveCond4` | AC-4 (drift==0 over 28d window) reads true while live drift counter > 0 | PagerDuty (sre-oncall) + activity-log + Henrik marker-audit |

| Field | Shared value |
|---|---|
| For-window | `1m` |
| Severity | `page` |
| Pre-Mortem-ID | C1 |
| Mitigation anchor | Phase-3-Complete-Marker-Audit-Trail-Spec |
| Rationale | The Tag-40 baseline `WakirPhase3CompleteMarkerFalsePositive` guards the composite AND-of-5 marker; the granular sentinels show **which condition** is drifting, which is the diagnostic information needed for runbook execution. They do not replace the composite alert -- both stay live. |

### 2.8 Cross-Welle Hot-Spot Alerts

Two coupling-detector alerts surface Henrik Pre-Mortem Section 3
structural hot-spots:

| Alert | Hot-Spot | Conditions | For-window | Severity |
|---|---|---|---|---|
| `WakirPhase3HotSpotWelle3Welle4Coupling` | Welle-3 audit-bridge -> Welle-4 state-backing | audit-bridge rate-ratio > 1.5 AND state-backing-hash changes > 0 | `2m` | `page` |
| `WakirPhase3HotSpotWelle4Welle5Welle7Coupling` | Welle-4 state-backing -> Welle-5 audit-verifier / Welle-7 recovery | state-backing-hash changes > 0 AND (Welle-5 signoff OR Welle-7 pre-audit read) | `5m` | `page` |

Notify path for both: PagerDuty (sre-oncall) + ntfy (ar-hand-critical)
+ activity-log append.

Rationale: These are coupling-detectors, not single-metric alerts.
They require **both** sides of the structural coupling to be active.
Hot-Spot #1 has a tighter threshold (1.5x baseline) than the A5
alert (3x) because the coupling itself is the signal, not the raw
rate magnitude. Hot-Spot #2 uses a 5m window because state-backing
changes are slower-moving than event-stream rates.

---

## 3. Notify-Path Receiver Inventory

| Receiver | Channel | Use case |
|---|---|---|
| `pagerduty:sre-oncall` | PagerDuty service | 24/7 on-call response, paging |
| `ntfy:ar-hand-critical` | ntfy.sh topic (encrypted) | AR-Hand critical attention, immediate |
| `ntfy:ar-hand` | ntfy.sh topic (encrypted) | AR-Hand attention, non-immediate |
| `ntfy:ar-hand-info` | ntfy.sh topic (encrypted) | AR-Hand information surface, governance |
| `ticket:sre-ops` | JIRA-style ops ticket queue | Non-paging operational follow-up (Tag-50 ticket-severity Welle alarms) |
| `activity-log:append` | Local file `activity-log.md` append-only | Audit trail for Henrik |
| `henrik-iia-1130-trigger` | Internal-audit-workflow (webhook to Henrik inbox) | IIA-1130 policy enforcement marker |
| `henrik-audit-trail` | Internal-audit-workflow | Standard audit-trail item |
| `henrik-marker-audit` | Internal-audit-workflow | Phase-3-COMPLETE marker-audit-trail item |

Operational note: the AlertManager receiver configuration that
wires these labels to actual transports is owned by Kai (Zone H,
deployment substrate). This catalogue documents the **policy**;
Kai owns the wiring.

---

## 4. Pre-Mortem Failure-Modes WITHOUT Tag-45 alert rules

These failure-modes from Henrik Tag-44 Pre-Mortem are intentionally
not covered by a new Tag-45 Prometheus alert. Their detection
anchor is documented below for completeness.

| ID | Failure-Mode | Detection anchor (existing) |
|---|---|---|
| A3 | State-Migration-Failure | Welle-rollback alert (covers state-backing rollback); Reza Replay-Engine diff |
| A6 | Cosign-Verification-Drift | `cosign-verify-images.yml` CI workflow; cross-substrate-parity-gate |
| A7 | Persona-Engine-Sprach-Drift | `persona-engine-backend-decisions.json` latency P95/P99 panels |
| A8 | NATS-JetStream-Persistence-Loss | Welle-rollback alert; state-backing-Pre-Cutover-Snapshot diff |
| B2 | Sign-Off-Sequenz-Bruch | activity-log sequence check (non-Prometheus) |
| B4 | Welle-7 IIA-1130-Konflikt | Same pattern as B3; spec gesetzt, AR-Hand-Entscheidung |
| B5 | Spawn-Collision | Aggregator-Workflow PR-topology-check (non-Prometheus) |
| B6 | Persona-Sleep-Watch-Bruch | `persona-engine-health.json` sleep-watch panel |
| C2 | AR-Ratifikation-Race | activity-log marker-reihenfolge (non-Prometheus) |
| C3 | Public-Comms-Premature | Site-repo-PR-review (non-Prometheus) |
| C4 | ADR-Substanz-False-Premise | Mira-Hand pre-Vorlage (non-Prometheus) |
| C5 | YAML-Frontmatter-Disziplin | Pre-commit lint + Quartz-Render-Test (non-Prometheus) |
| D1 | GitHub-API-Outage | github.status.com Watch + Aggregator-Workflow-Timeout |
| D2 | NATS-Service-Failure on Pilot-VM | ADR-0060 Live-FCOS-VM-CI-Gate + NATS-Cluster-Replikation |
| D3 | Cosign-Verification-Drift (extern) | Pinned-Cosign-Version + AR-Hand-Audit |
| D4 | Cloud-Provider-Throttling | Registry-Mirror + Pre-Cutover-Image-Cache-Warmup |
| D5 | OpenTimestamps-Calendar-Outage | Multiple-Calendar-Server + deferred-Verification-Pfad |

If new metrics emerge for any of these, a Tag-N follow-up will
add the corresponding rule.

---

## 5. Tag-50 Welle-N-Specific Alert-Rules

Tag-50 extends this catalogue with seven **per-welle alert groups**
(`welle-1-alerts` .. `welle-7-alerts`) in
`dashboards/phase-3-marathon-alerts.yaml`. Where Sections 2.x map
failure-mode classes (A1..C1) to alarms, Section 5 maps welle-N
to its dedicated welle-scoped alarms. The two views are
complementary: an aggregate A2 (`WakirPhase3FailureModeA2FsmPhantomTransition`)
fires on any welle's illegal FSM transition; the Tag-50 alarm
`WakirWelle5FsmPhantomTransition` fires exclusively on Welle-5
with a `welle="welle-5"` label, so the operator sees the welle-
scoped page without disambiguating from the aggregate's label.

### 5.1 Welle inventory + KW-topology

| Welle | Component | KW-week | Topology | Group |
|---|---|---|---|---|
| `welle-1` | `v907_verify` | `kw-24` | doppel partner Welle-2 | `welle-1-alerts` |
| `welle-2` | `svid_workload_identity` | `kw-24` | doppel partner Welle-1 | `welle-2-alerts` |
| `welle-3` | `bridge_audit_writer` | `kw-25` | **solo** (critical) | `welle-3-alerts` |
| `welle-4` | `state_backing` | `kw-26` | doppel partner Welle-5 | `welle-4-alerts` |
| `welle-5` | `lifecycle_state_machine` (FSM) | `kw-26` | doppel partner Welle-4 | `welle-5-alerts` |
| `welle-6` | `subscribe_loop` | `kw-27` | doppel partner Welle-7 | `welle-6-alerts` |
| `welle-7` | `recovery_workflow` | `kw-27` | doppel partner Welle-6 | `welle-7-alerts` |

### 5.2 Welle-1 (v907_verify)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle1V907VerifyRustRateCollapse` | self-score < 95 | 2m | page | PagerDuty + ntfy ar-hand + activity-log |
| `WakirWelle1Welle2DoppelDivergence` | \|welle-1 - welle-2 self-score\| > 5pp | 3m | ticket | ticket sre-ops + activity-log |

Rationale: the KW-24 doppel-cutover rust-rate gate is 95% per
ADR-0066. The two doppel-partners should track within 5pp; larger
divergence is a structural signal.

### 5.3 Welle-2 (svid_workload_identity)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle2SvidRotationFailure` | rotation-failure counter increase > 0 | 60s | page | PagerDuty + ntfy ar-hand + activity-log |
| `WakirWelle2SelfScoreCollapse` | self-score < 95 | 2m | page | PagerDuty + ntfy ar-hand + activity-log |

Rationale: SVID-rotation failure breaks workload-identity
assertions on Welle-2 cutover; the SPIFFE pipeline must be live.

### 5.4 Welle-3 (bridge_audit_writer, KW-25 SOLO critical)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle3SelfReferenceTrapFire` | audit-bridge rate >= 2x 24h-offset baseline | 90s | page | PagerDuty + ntfy ar-hand-critical + activity-log + Henrik IIA-1130-trigger |
| `WakirWelle3SoloTopologyViolation` | Welle-3 in pre/in cutover AND >1 welle in pre/in cutover | 60s | page | PagerDuty + ntfy ar-hand-critical + activity-log |
| `WakirWelle3StressOracleDivergence` | \|self-score - phase-2-stress-oracle\| > 0.5pp | 60s | page | PagerDuty + ntfy ar-hand-critical + activity-log |

Group scrape interval: **15s** (vs. 30s elsewhere). The Tag-45 A5
failure-mode-class alert uses a 3x threshold over 2m for the
class-level page; the Welle-3-scoped `SelfReferenceTrapFire` uses
2x over 90s for an earlier welle-scoped page. Both stay live;
the welle-scoped one is the front-line page on KW-25 SOLO.

The 0.5pp stress-oracle divergence threshold reflects the
ADR-0066 Welle-3 immediate-rollback trigger (Henrik / Internal
Audit caution, welle-status dashboard panel 43).

### 5.5 Welle-4 (state_backing)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle4StateReadFail` | state-backing-read-fail counter increase > 0 | 60s | page | PagerDuty + ntfy ar-hand-critical + activity-log |
| `WakirWelle4StateBackingMigrationRollback` | migration-rollback counter increase > 0 | 60s | page | PagerDuty + ntfy ar-hand + activity-log |
| `WakirWelle4WriteLatencyP99Excess` | write-latency P99 > 250ms | 5m | ticket | ticket sre-ops + activity-log |

State-read-fail is the coupling source for the Tag-45 Hot-Spot
#2 (Welle-4 -> Welle-5/7); this welle-scoped alarm fires first.
Migration-rollback is distinct from the global welle-rollback
baseline alert: it scopes to the migration-script-level rollback
counter.

### 5.6 Welle-5 (lifecycle_state_machine / FSM)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle5FsmPhantomTransition` | illegal-transition counter (welle=welle-5) > 0 | 60s | page | PagerDuty + ntfy ar-hand + activity-log |
| `WakirWelle5LifecycleOrphanState` | orphan-state counter > 0 | 90s | page | PagerDuty + activity-log |
| `WakirWelle5SignedOffBeforeWelle4Stable` | welle-5 signoff AND welle-4 hash changed in 10m | 60s | page | PagerDuty + ntfy ar-hand + activity-log + Henrik audit-trail |

Welle-5 KW-26 doppel-ordering rule: Welle-4 state-backing must
stabilize BEFORE Welle-5 audit-verifier signs off. The third
alarm catches the ordering violation directly; it is the welle-
scoped page that surfaces a moving-target attestation.

### 5.7 Welle-6 (subscribe_loop)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle6SubscribeLoopStall` | rate(delivered) == 0 over 2m | 2m | page | PagerDuty + ntfy ar-hand + activity-log |
| `WakirWelle6SubscribeLoopReplayStorm` | rate(redelivery) > 10 msg/s | 2m | page | PagerDuty + ntfy ar-hand + activity-log |

Stall and replay-storm are complementary failure-modes on the
same JetStream consumer surface: stall = zero traffic, replay-
storm = excessive retry traffic. Both indicate broken consumer-
ack flow but the response differs (broker-side vs. consumer-side
investigation).

### 5.8 Welle-7 (recovery_workflow)

| Alert | Threshold | For | Severity | Notify |
|---|---|---|---|---|
| `WakirWelle7RecoveryRehearsalFail` | rehearsal-failure counter increase > 0 | 60s | page | PagerDuty + ntfy ar-hand-critical + activity-log |
| `WakirWelle7RecoveryWithoutPreAuditWarning` | henrik signoff AND no external-pre-auditor signoff | 1m | warning | ntfy ar-hand-info + activity-log |
| `WakirWelle7RecoveryReplayDivergence` | replay-divergence counter increase > 0 | 60s | page | PagerDuty + ntfy ar-hand + activity-log |

The `WithoutPreAuditWarning` parallels Tag-45 B3 (Welle-3 IIA-1130
default-path) and covers Henrik Pre-Mortem B4 (Welle-7 IIA-1130-
Konflikt). Warning severity per low-probability / high-impact
classification.

### 5.9 Welle-N alert-name convention

All Tag-50 alert names follow `WakirWelle<N><Description>`. This
prefix is disjoint from Tag-40 / Tag-45 names (which start with
`WakirPhase3`). The disjointness is enforced by
`tests/ci/test_welle_n_specific_alerts.py`.

---

## 6. Cross-Review Status

| Reviewer | Domain | Status |
|---|---|---|
| Henrik (Internal Audit) | Pre-Mortem-Failure-Mode mapping correctness | requested |
| Kai (Container-Infra) | Zone H -- AlertManager receiver wiring | requested |
| Tomas (Matrix-Lead) | Zone I -- WAT pipeline overlap (none expected; Marathon is not WAT) | informed |
| Priya (CTO) | hierarchical approval per ADR-0045 | requested |

The cross-review checklist is enforced via the PR review process
and not blocked at this Tag-45 / Tag-50 commit boundary, per
Continuous-Mode default (AR-direktive).

---

## 7. Disclaimer

This catalogue is **proposed** and reflects Tag-45 + Tag-50
substance. It follows the §10 GOVERNANCE.md boundary: Internal
Audit (Henrik) classifies and audits; SRE (Noa) measures and
surfaces. The catalogue does not classify findings or produce
verdicts.

-- Noa
