# SLI / SLO Catalogue — Phase 1b Pilot

**Owner:** Noa Bergstroem (SRE) · **Sprint:** SRE Tag-15 · **Status:** proposed (pending Zone H Kai consensus, then Priya CTO approval)

This document is the canonical SLI/SLO catalogue for the Phase 1b Pilot. It covers two systems:

1. **wakir-persona-engine** — the real-implementation persona-engine container (image tag `0.4.2-pilot`, Sprint-Pengine-12). Instrumentation seam: `wirelang/persona_engine/observability.py`.
2. **mira-hourly stack** — the hourly CEO-check synthesis loop driven by `aicorp-mira-hourly.timer` + `scripts/mira-hourly.sh` + the watchdog (`scripts/mira-hourly-watchdog.py`).

Both systems share one OTLP collector + Prometheus pipeline. The collector deployment is Kai's domain (Zone H); this document is the Monitoring-Requirements input.

---

## 1. Scope and non-goals

### In scope (Phase 1b Pilot)

- Spawn-time path: boot → V-907 verify → SVID fetch → FSM `spawning → running` → first engineering-output emit.
- Steady-state path: NATS-subscribe-loop dispatch latency, FSM transition health.
- Recovery path: R1..R4 trigger counts, outcome split.
- SVID fence health: full-fetch failure rate (Bug-40 fence-to-probe-only path).
- Mira-Hourly tick presence and quota-cap-abort detection.

### Out of scope (deferred to Phase 2)

- WAT-pipeline SLOs (OTS anchor latency, Merkle-tree-build time, anchor failure rate). Owned by Tomás (WAT-core); requires Zone I cross-review first. Skeleton lives in `docs/observability/sli-slo-wat-phase-2.md` (TBD).
- Cross-org federation SLOs (federation-evaluator response time, cross-trust-domain bridge latency). Owned by Reza; requires Zone B cross-review.
- Frontend SLIs (Quartz render p95, AR-dashboard load time). Owned by Lena.
- Cost SLOs (USD-per-spawn, hourly-tick token-budget). Owned by Daniel (CFO); Phase 2 once steady-state token usage stabilises.

---

## 2. Persona-Engine SLIs

Five SLIs, each mapped to exactly one OTel meter (no metric sprawl). Sources defined in `wirelang/persona_engine/observability.py`.

### 2.1 Spawn latency (`SLI-PE-1`)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.spawn.latency_seconds` (Histogram) |
| Definition | Wall-clock from `PersonaEngine.boot()` entry to the first `engineering-output-emission-first` event inside `PersonaEngine.spawn()`. |
| Window | 15-minute trailing |
| Rationale | This is the user-visible spawn experience. Phase 1b Pilot deployments must boot a fresh persona container in under a minute or the Operator-Hand workflow stalls. |
| Aggregation | `histogram_quantile(0.95, sum by (le) (rate(...[15m])))` |
| Labels | `persona_id`, `org_id`, `session_id`, `outcome` |

**SLO:** p95 < 60 s.

**Error budget:** 5% of the 15-minute window may exceed 60 s. Burn-rate alert at 2 × budget over 2 h triggers a ticket; at 5 × over 30 min, pages the on-call.

### 2.2 Subscribe-loop dispatch lag (`SLI-PE-2`)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.subscribe.lag_seconds` (Histogram) |
| Definition | Wall-clock between the inbound auftrag envelope's `ts_utc` and the subscribe-loop's per-msg dispatch in `_handle_message_inner`. |
| Window | 15-minute trailing |
| Rationale | The Doppelbetrieb-Vergleichs-Score depends on the persona-engine processing Mira-side bridge-forward auftraege within the same second the Pre-Framework Tomás would. A growing lag indicates JetStream backpressure or a stuck hook. |
| Aggregation | `histogram_quantile(0.99, sum by (le) (rate(...[15m])))` |
| Labels | `persona_id`, `org_id`, `subject` |

**SLO:** p99 < 2 s.

**Error budget:** 1% of the 15-minute window may exceed 2 s. p99 staying above target for 30 minutes pages.

### 2.3 V-907 verify duration (`SLI-PE-3`)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.v907.verify_duration_seconds` (Histogram) |
| Definition | Wall-clock of `verify_v907_pin()` inside `_boot_internal`. |
| Window | 15-minute trailing |
| Rationale | The V-907 hash is computed on every spawn (no caching). A drift here is the canary for `persona_canonical_form` import overhead or axis-A bind-mount slowness. Should normally complete in tens of milliseconds; a sudden p95 over 500 ms points at I/O contention or a wheel regression. |
| Aggregation | `histogram_quantile(0.95, sum by (le) (rate(...[15m])))` |
| Labels | `persona_id`, `org_id`, `mode` (`real` / `stub` / `drift` / `compute_error`), `matched` |

**SLO:** p95 < 500 ms.

**Error budget:** 5% of the window may exceed 500 ms. Burn-rate alert at 2 × over 1 h triggers a ticket.

### 2.4 FSM stuck-state detection (`SLI-PE-4`)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.fsm.transitions_total` (Counter) |
| Definition | Time elapsed in a non-terminal state (`spawning`, `despawning`, `recovered`) without a transition. Derived from the absence of new transitions for a given `(persona_id, session_id)` pair. |
| Window | 5-minute rolling |
| Rationale | The lifecycle FSM has six states (spec §3.3). Three are transient (`spawning`, `despawning`, `recovered`). An engine stuck in `spawning` for longer than 5 minutes is a definitive crash signal. |
| Aggregation | `time() - max by (persona_id, session_id) (max_over_time(persona_engine_fsm_transitions_total{accepted="true"}[5m]))` — Recording rule to be defined in Prometheus rules (Zone H deliverable from Kai). |
| Labels | `persona_id`, `org_id`, `session_id`, `from_state`, `to_state` |

**SLO:** No persona-engine instance in a transient state for > 5 minutes.

**Error budget:** Zero — any breach pages immediately. Justified: a stuck transient state is a critical reliability failure, not a degradation.

### 2.5 Recovery R-phase trigger rate (`SLI-PE-5`)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.recovery.trigger_total` (Counter) |
| Definition | Rate of recovery_workflow R1/R2/R3/R4 phase invocations. |
| Window | 1-hour trailing |
| Rationale | Steady-state recovery should be rare. A sustained rate above 1/h per persona indicates the engine is crashing more than it should — either a real bug or a SPIRE-Agent backing issue. |
| Aggregation | `sum by (persona_id, trigger, outcome) (rate(...[1h]) * 3600)` |
| Labels | `persona_id`, `org_id`, `trigger` (`R1`/`R2`/`R3`/`R4`), `outcome` (`success`/`failure`) |

**SLO:** R-trigger rate < 1/h per persona.

**Error budget:** Two triggers per persona per hour. A third triggers a ticket; sustained 5+ pages.

### 2.6 SVID fence rate (auxiliary, not user-facing)

| Attribute | Value |
|---|---|
| Metric | `persona_engine.svid.fetch_failures_total` (Counter) |
| Definition | Rate of fence-to-probe-only entries (Sprint-Pengine-11 Bug-40 graceful-fallback). |
| Window | 1-hour trailing |
| Rationale | Bug-40 protects against SPIRE-Agent flakiness, but a sustained fence rate above 1/h indicates the SPIRE-Agent is itself unreliable. This is an internal-reliability metric, not a user-facing SLO — but it must be alertable. |
| Labels | `persona_id`, `org_id`, `fence_mode` (`wheel-missing` / `fetch-failure`) |

**Threshold:** Sustained > 5/h for 10 minutes pages.

---

## 3. Mira-Hourly stack SLIs

Two SLIs, sourced from `scripts/mira-hourly-watchdog.py` (Prometheus textfile-collector output).

### 3.1 Hourly-tick presence (`SLI-MH-1`)

| Attribute | Value |
|---|---|
| Metric | `mira_hourly_last_tick_age_seconds` (Gauge, textfile-collector) |
| Definition | Seconds since the most recent record in `infra/mira-hourly-telemetry.jsonl`. |
| Window | Instantaneous |
| Rationale | The hourly CEO-check is the heartbeat of the Aufsichtsrats-Synthesis loop. If it stops, the corp is running blind. |
| Aggregation | Direct gauge |
| Labels | none |

**SLO:** `mira_hourly_last_tick_age_seconds < 4800` (80 minutes).

**Error budget:** Zero. The hourly timer is `OnCalendar=hourly`, healthy gap < 65 min. 80 min covers 15 min slack for the slowest observed run + 5 min watchdog off-grid offset. Breach pages immediately.

### 3.2 Hourly-tick abort detection (`SLI-MH-2`)

| Attribute | Value |
|---|---|
| Metric | `mira_hourly_consecutive_abort_count` (Gauge, textfile-collector) |
| Definition | Number of consecutive abort-shaped records at the tail of the telemetry JSONL. Abort signature: `is_error == true` AND `num_turns <= 1` AND `total_cost_usd == 0` AND `duration_ms < 5000` (quota-cap or rate-limit response shape). |
| Window | Instantaneous (most recent N records) |
| Rationale | The 2026-05-15 18:00 + 19:00 CEST incident showed the wrapper firing on schedule but the underlying `claude` CLI aborting sub-second on quota cap. The telemetry record exists, but it's not a real synthesis run — Aufsichtsrats-visibility into the corp is silently degraded. |
| Aggregation | Direct gauge |
| Labels | none |

**SLO:** `mira_hourly_consecutive_abort_count < 2`.

**Error budget:** One abort. Two consecutive aborts page. Justified: a single quota cap can be a transient API hiccup; two in a row indicates either a sustained quota issue or a structural problem (account suspension, network outage, claude-dev container drift).

---

## 4. Error-budget tracking mechanic

### 4.1 Budget calculation

For each SLI with a percentage error budget (SLI-PE-1, PE-2, PE-3, PE-5), the error budget is computed as:

    budget_remaining = (window_duration × (1 - SLO_target)) - (time_in_violation)

where `time_in_violation` is the cumulative wall-clock during which the SLI exceeded its threshold inside the window.

### 4.2 Burn-rate alerting (Google SRE Book §4.4)

Three burn-rate alert tiers:

| Tier | Window | Burn-rate multiplier | Action |
|---|---|---|---|
| **Slow** | 6 h | 2 × budget | Ticket (Henrik audit-trail) |
| **Fast** | 1 h | 5 × budget | Page (operator on-call) |
| **Page-now** | 5 min | 14.4 × budget | Page + ntfy AR-channel |

Burn-rate multipliers chosen per the Google SRE Workbook table-2 worked example, normalised to the 15-minute SLI evaluation window.

### 4.3 Budget exhaustion → release gating

When the 28-day error budget for any persona-engine SLI is fully consumed:

1. **Strategy-Hand-Mira halts new persona-engine releases.** Phase-1b-Pilot stays on the last green tag.
2. **Cross-Review Zone H (Noa + Kai) convenes within 24 h** to root-cause.
3. **Tomás Matrix-Lead consulted** if the budget breach implicates WAT-pipeline (Zone I trigger).
4. **AR (Fred)** receives an A-class needs-attention.md item.

Mira-Hourly SLIs (SLI-MH-1, MH-2) use a different rule: any breach is page-immediate, no burn-rate windowing. Justified: the Aufsichtsrats-Synthesis loop is the corp's nervous system; quiet degradation is not acceptable.

---

## 5. Recording rules (Zone H deliverable)

The following Prometheus recording rules are required for the SLO dashboards to be performant. **Kai owns the deployment**; Noa specifies them here as Monitoring-Requirements.

```yaml
groups:
  - name: wakir-persona-engine-slo
    interval: 30s
    rules:
      - record: persona_engine:spawn_latency_seconds:p95_15m
        expr: histogram_quantile(0.95, sum by (le, persona_id, org_id) (rate(persona_engine_spawn_latency_seconds_bucket[15m])))
      - record: persona_engine:subscribe_lag_seconds:p99_15m
        expr: histogram_quantile(0.99, sum by (le, persona_id, org_id) (rate(persona_engine_subscribe_lag_seconds_bucket[15m])))
      - record: persona_engine:v907_verify_duration_seconds:p95_15m
        expr: histogram_quantile(0.95, sum by (le, persona_id, org_id) (rate(persona_engine_v907_verify_duration_seconds_bucket[15m])))
      - record: persona_engine:recovery_trigger_rate_per_hour
        expr: sum by (persona_id, trigger, outcome) (rate(persona_engine_recovery_trigger_total[1h]) * 3600)
      - record: persona_engine:svid_fetch_failure_rate_per_hour
        expr: sum by (persona_id, fence_mode) (rate(persona_engine_svid_fetch_failures_total[1h]) * 3600)
```

Alert rules referencing these recording-rule names are in `docs/observability/alert-rules-phase-1b.md` (TBD, follow-up Sprint).

---

## 6. Review cadence

- **Weekly:** Noa reviews the SLO dashboard (`dashboards/persona-engine-health.json`) every Monday morning. Burn-rate trends fed into the weekly report.
- **Monthly:** SLO targets re-validated. Targets that are easy by 10× should tighten; targets that are missed by 2× need root-cause work.
- **Per-release:** A persona-engine release that introduces a new instrumentation seam must add or revise the corresponding SLI in this document.

---

## 7. Anchors

- **Persona-engine instrumentation module:** `wirelang/persona_engine/observability.py`
- **Persona-engine hermetic tests:** `wirelang/tests/persona_engine/test_observability.py`
- **Mira-Hourly watchdog:** `scripts/mira-hourly-watchdog.py`
- **Mira-Hourly watchdog tests:** `tests/test_mira_hourly_watchdog.py`
- **Grafana dashboard:** `dashboards/persona-engine-health.json`
- **OTel-Extra:** `pyproject.toml [project.optional-dependencies] persona-engine-observability`
- **Cross-review zone:** ADR-0042 (SRE persona definition) §Zone H (Noa × Kai container-operations)
- **Spec anchor:** `wirelang/specs/persona-engine-format-spec.md` §3.3 (FSM), §3.7.4 (recovery), §5 (V-907)
- **Sister-doc (deferred Phase 2):** `docs/observability/sli-slo-wat-phase-2.md` — WAT-pipeline SLOs (Zone I, Tomás review required first).

---

*Noa Bergstroem — SRE, Wakir Labs · Sprint-SRE Tag-15 · 2026-05-16*
