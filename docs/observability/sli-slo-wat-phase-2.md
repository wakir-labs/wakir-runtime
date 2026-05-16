# SLI / SLO Catalogue — WAT Anchor Pipeline (Phase 2)

**Owner:** Noa Bergstroem (SRE) · **Sprint:** Sprint-WAT-Anchor-Pipeline-Live-Observability-MINI · **Status:** proposed (pending Zone I Tomas consensus, then Priya CTO approval)

This document is the canonical SLI/SLO catalogue for the WAT (Wakir Audit Trail) OTS-anchor pipeline. It is the sister-doc to `docs/observability/sli-slo-phase-1b.md` (Phase 1b pilot — persona-engine + Mira-Hourly stack) and was tagged "TBD" there pending Tomas' PR #124 `wakir-anchor anchor-receipt` CLI landing on `wakir-runtime/main`.

PR #124 is now on main (ADR-0064 §Folgeartefakte Phase-2-Observability, ~01:00 CEST 2026-05-17 deployment). The gauge-emitter that feeds this catalogue ships in the same PR: `scripts/wat-anchor-pipeline-observability.py`.

The instrumentation seam is Tomas' `wakir-anchor` CLI; the gauge surface is the Prometheus textfile-collector under Kai's node-exporter Quadlet (Zone H deployment substrate). This catalogue defines **what** is measured and **what threshold counts as a breach**; Kai's Zone H Quadlet bundle defines **how** the collector picks it up; the alert-rules referencing these SLOs land in a follow-on doc (`docs/observability/alert-rules-wat-phase-2.md`, TBD next sprint).

---

## 1. Scope and non-goals

### In scope (Phase 2)

- **OTS calendar attestation flow:** Merkle root submission to OpenTimestamps calendars, calendar-attestation count, upgrade-to-finalized transition.
- **Bitcoin-block-height finalization:** the upgrade-to-finalized path that lands a calendar attestation as a Bitcoin-block-confirmed timestamp.
- **Anchor-pending age:** how long a pending receipt stays pending before finalization.
- **Bitcoin-block-height drift detection:** CI-probe drift vs. an external block-height source (mempool.space public endpoint) as a sanity check on the Bitcoin-node Tomas' WAT-core consumes.
- **Schema-drift detection:** the observability CLI contract (PR #124 stdout shape) is a stable surface; drift in either direction (older CLI emitting fewer fields, newer CLI emitting an unknown schema_version) surfaces as an explicit gauge so the SLO dashboard does not silently degrade.

### Out of scope (deferred to Phase 3)

- **Merkle-tree-build time SLO:** Tomas' merkle-aggregator already has timing instrumentation but the persona-engine spawn rate has not yet produced enough leaves per aggregate window to make the latency observable. Deferred until steady-state Phase-2 traffic shows a stable build-time distribution.
- **Cross-org WAT federation SLOs:** federation-evaluator response time, cross-trust-domain anchor relay. Owned by Reza; requires Zone B cross-review.
- **Receipt-DB write-latency SLOs:** the receipt-spool is a flat-file spool today; promotion to a transactional store is a separate ADR.
- **OTS-calendar-per-attestation latency SLIs:** per-calendar response-time histograms are useful for diagnosing a single bad upstream but introduce metric-sprawl (3+ calendars × per-request latency bucket per second). Deferred until a real OTS-calendar incident motivates per-upstream observability.

### Out-of-band: cost
Anchor-flow USD cost (Bitcoin mempool fee for the calendar's aggregate transaction) is not borne by Wakir Labs — the OTS-calendar operator pays. Cost SLOs deferred to Daniel (CFO) per the Phase-1b sister-doc.

---

## 2. WAT-anchor-pipeline SLIs

Five SLIs, each backed by exactly one Prometheus gauge from the observability script. No metric sprawl: each gauge is justified by exactly one operator question.

### 2.1 Anchor finalization rate (`SLI-WAT-1`)

| Attribute | Value |
|---|---|
| Metric | `wat_anchor_finalized_count` / (`wat_anchor_finalized_count` + `wat_anchor_pending_count` + `wat_anchor_failed_count`) |
| Definition | Fraction of WAT anchor receipts in `verifier_state=finalized` over the spool lifetime. |
| Window | 96-hour trailing |
| Rationale | The WAT-anchor pipeline's entire value proposition is: anchors that were stamped against OTS calendars must eventually transition to Bitcoin-block-confirmed (finalized). A non-finalizing receipt is either stuck waiting on the calendar to publish or is genuinely broken. 96 h is the upper bound on the OTS calendar -> Bitcoin publication cadence under the OpenTimestamps aggregator-of-aggregators contract (calendars batch and submit roughly daily; 4 days of slack covers a long weekend and one missed batch). |
| Aggregation | `wat_anchor_finalized_count / clamp_min(wat_anchor_finalized_count + wat_anchor_pending_count + wat_anchor_failed_count, 1)` (recording rule; Zone H Kai deliverable to land it in Prometheus rules) |
| Labels | none (spool-wide aggregate) |

**SLO-1:** 96-hour-trailing finalization-rate > **99%**.

**Error budget:** 1% of receipts in the window may stay non-finalized. Burn-rate alert at 2 × budget over 24 h triggers a Tomas ticket; at 5 × over 4 h pages.

**Justification of 99% target:** Tomas' WAT-Core has been observed to finalize within 24 hours under healthy conditions (Phase-1b dogfooding logs, Tag-9 through Tag-15). A 1% miss rate budgets for one stuck receipt per 100 anchors; that is one receipt per ~3 hourly Mira-anchors per day in current traffic — a tolerable Tier-2 ticket cadence, not a paging event.

### 2.2 Anchor-pending latency (`SLI-WAT-2`)

| Attribute | Value |
|---|---|
| Metric | `wat_last_anchor_age_seconds` (instantaneous; sampled every 15 min via the observability script's `--latest` CLI invocation) |
| Definition | Seconds elapsed since the latest WAT anchor receipt was created, **conditioned on the receipt still being in `verifier_state=pending`**. We do not include finalized receipts in this SLI — once a receipt finalizes, its age becomes a historical fact, not a pipeline-health signal. |
| Window | 15-minute trailing samples; SLO evaluated at the **p99 across all pending receipts observed in the trailing 7-day window**. Note: the observability script only reports the **latest** receipt's age, so the SLO is approximated via the recording-rule `max_over_time(wat_last_anchor_age_seconds[7d] and on() wat_anchor_pending_count > 0)`. A full per-receipt-age histogram is a Phase-3 stretch goal. |
| Rationale | A receipt that sits pending for more than 2 hours is unusual: calendar attestations land within minutes, the calendar-internal aggregation runs every ~1 hour. A pending-age above 2 hours points at a calendar outage (transient) or a calendar dropping our submission (durable, alert-worthy). |
| Aggregation | `histogram_quantile(0.99, ...)` against the per-receipt-age series when a Phase-3 per-receipt-age gauge is added; until then the approximation above. |
| Labels | none |

**SLO-2:** p99 of pending-anchor age < **2 hours** (7200 seconds).

**Error budget:** 1% of the time the pending-age may exceed 2 h. Burn-rate alert at 2 × over 6 h triggers a Tomas ticket; at 5 × over 1 h pages the on-call.

**Justification of 2-hour target:** OpenTimestamps calendars aggregate every ~1 hour per the public-aggregator contract. A 2-hour budget covers one missed aggregation slot plus the next slot's batch landing. Anything longer indicates the calendar dropped our submission or the WAT-core's pending-spool is not being polled.

### 2.3 Bitcoin-block-height drift (`SLI-WAT-3`)

| Attribute | Value |
|---|---|
| Metric | `wat_bitcoin_block_height_latest` (from the observability script) vs. an external reference block-height from a CI-probe of `https://mempool.space/api/blocks/tip/height` |
| Definition | Absolute difference between the Bitcoin block height at which our most-recent finalized WAT receipt was anchored and the current Bitcoin tip height as reported by mempool.space. A growing drift means we are not finalizing into the current block-stream; either the calendar is behind or our consumer of the calendar is behind. |
| Window | Instantaneous (CI-probe runs every 15 minutes, parallel to the observability script's timer slot) |
| Rationale | Bitcoin mines ~144 blocks per day (one per ~10 min). A finalized receipt should be within roughly 6 blocks (1 hour) of the current tip under healthy conditions; 6 blocks corresponds to the standard Bitcoin "confirmed" threshold and gives the calendar room to aggregate before publishing. Drift beyond 6 blocks indicates either (a) we have not finalized a receipt recently (no recent anchor activity — combine with SLO-1 to disambiguate) or (b) the WAT-core's Bitcoin-block-height reader is stale. |
| Aggregation | direct gauge comparison; recording rule `wat_bitcoin_block_height_drift = mempool_space_block_height_latest - wat_bitcoin_block_height_latest` (when the mempool-space probe lands in a follow-up sprint; until then this SLO is **observational only**) |
| Labels | none |

**SLO-3:** `wat_bitcoin_block_height_drift` stays within **6 blocks** of the mempool.space tip.

**Error budget:** the drift may exceed 6 blocks for up to **2% of the trailing 24-hour window**. Burn-rate alert at 2 × over 12 h triggers a ticket; at 5 × over 1 h pages.

**Justification of 6-block target:** the standard Bitcoin confirmation threshold is 6 blocks (~1 hour). Drift below that is "we have a fresh anchor"; drift above that is "our latest anchor is not following the chain". This is the most operator-actionable Bitcoin-side signal.

**Phase-2 limitation, explicitly documented:** the mempool.space external probe is not in this MINI scope. SLO-3 lands today as a **defined target with no live gauge feed** — the observability script emits `wat_bitcoin_block_height_latest`, the external-probe gauge is the follow-up substrate. This is captured in `outbox/2026-05-17-noa-sprint-wat-anchor-observability-mini-done.md` as a deferred item, not a missed deliverable.

### 2.4 Schema-drift detection (`SLI-WAT-4`, auxiliary)

| Attribute | Value |
|---|---|
| Metric | `wat_anchor_pipeline_schema_drift` (gauge, 0.0 / 1.0) |
| Definition | 1.0 when the CLI emits an unknown `schema_version` or `verifier_state`, 0.0 otherwise. |
| Window | Instantaneous |
| Rationale | The CLI contract between Tomas' PR #124 and Noa's observability script is the entire surface this SLI catalogue depends on. If Tomas bumps the schema and Noa's script lags, the gauges silently misalign with reality. The schema-drift gauge is the canary. |
| Aggregation | direct gauge |
| Labels | none |

**Threshold:** any sustained `wat_anchor_pipeline_schema_drift == 1.0` for > 30 minutes pages. Justified: the CLI contract is a Zone-I cross-review artefact — a drift signal means the cross-review failed to catch a schema-bump.

### 2.5 CLI-availability and CLI-failure (`SLI-WAT-5`, auxiliary)

| Attribute | Value |
|---|---|
| Metric | `wat_anchor_cli_unavailable` + `wat_anchor_pipeline_cli_failure` (gauges, 0/1) |
| Definition | `wat_anchor_cli_unavailable=1.0` when the `wakir-anchor` binary is not on PATH (the observability script's host container has lost the WAT package). `wat_anchor_pipeline_cli_failure=1.0` when the CLI ran but returned non-zero or produced unparseable JSON. |
| Window | Instantaneous |
| Rationale | These two gauges separate "infra broken" (CLI missing — Kai's container-orchestration domain) from "WAT-core broken" (CLI ran and failed — Tomas' WAT-core domain). The separation matters for paging routing. |
| Labels | none |

**Threshold:** `wat_anchor_cli_unavailable == 1.0` for > 10 minutes pages the SRE on-call **and** the Kai container-infra on-call. `wat_anchor_pipeline_cli_failure == 1.0` for > 30 minutes pages the SRE on-call **and** the Tomas matrix-lead. The 30 vs. 10 minute split reflects the recovery shape: a missing binary is a quick Kai-side fix; a failing CLI may need Tomas to investigate the WAT-core logs.

---

## 3. Error-budget tracking mechanic

### 3.1 Budget calculation

For each SLI with a percentage error budget (SLI-WAT-1, WAT-2, WAT-3), the error budget is computed as:

    budget_remaining = (window_duration × (1 - SLO_target)) - (time_in_violation)

where `time_in_violation` is the cumulative wall-clock during which the SLI exceeded its threshold inside the window.

### 3.2 Burn-rate alerting (Google SRE Book §4.4, normalised to the 15-min cadence)

Three burn-rate alert tiers (parity with Phase-1b sister-doc §4.2):

| Tier | Window | Burn-rate multiplier | Action |
|---|---|---|---|
| **Slow** | 24 h | 2 × budget | Ticket (Henrik audit-trail) |
| **Fast** | 4 h | 5 × budget | Page (operator on-call) |
| **Page-now** | 15 min | 14.4 × budget | Page + ntfy AR-channel |

The slow tier window is widened from 6 h (persona-engine SLOs) to 24 h here because the WAT-anchor pipeline operates on a fundamentally slower clock (calendars publish hourly, Bitcoin finalises in ~hours). A 6-hour slow-tier window would trip on normal OTS aggregation cadence variance.

### 3.3 Budget exhaustion -> Zone I trigger

When the 28-day error budget for any of SLI-WAT-1, WAT-2, or WAT-3 is fully consumed:

1. **Strategy-Hand-Mira halts new persona-engine releases that depend on WAT-anchor finalization** (Phase-2 release-gating predicate). Existing pilots stay running.
2. **Cross-Review Zone I (Noa + Tomas) convenes within 12 h** to root-cause. Aisha protocols consensus per `agents-workspaces/hr/cross-review-protocols/`.
3. **Tomas WAT-core deep-dive:** receipt-spool inspection, OTS-calendar HTTP probe, Bitcoin-RPC sanity check.
4. **AR (Fred)** receives an A-class `needs-attention.md` item.

The 12-hour Zone-I convening window is tighter than the Zone-H 24-hour analog from Phase-1b sister-doc §4.3 because WAT-anchor breaches affect the audit-trail substrate that downstream Phase-2 sales artefacts depend on. A WAT-pipeline outage that lasts longer than half a day starts breaking commit-OTS pipelines further out.

### 3.4 Operator-facing summary panel

A single Grafana single-stat panel renders the daily error-budget consumption rate against the 28-day target. Operators can read "are we burning budget faster than we earn it" off one row. This panel lands in `dashboards/wat-anchor-pipeline-health.json` (deferred to the follow-on dashboard sprint).

---

## 4. Recording rules (Zone H deliverable)

The following Prometheus recording rules are required for SLO dashboards to be performant. **Kai owns the deployment**; Noa specifies them here as Monitoring-Requirements:

```yaml
groups:
  - name: wakir-wat-anchor-slo
    interval: 60s
    rules:
      - record: wat_anchor_pipeline:finalization_rate:96h
        expr: |
          wat_anchor_finalized_count
          /
          clamp_min(
            wat_anchor_finalized_count
            + wat_anchor_pending_count
            + wat_anchor_failed_count,
            1
          )
      - record: wat_anchor_pipeline:pending_age_seconds:max_7d
        expr: |
          max_over_time(
            (wat_last_anchor_age_seconds and on() wat_anchor_pending_count > 0)[7d:15m]
          )
      - record: wat_anchor_pipeline:schema_drift_active
        expr: wat_anchor_pipeline_schema_drift == 1
      - record: wat_anchor_pipeline:cli_health_active
        expr: |
          (wat_anchor_cli_unavailable == 1)
          or
          (wat_anchor_pipeline_cli_failure == 1)
```

The Bitcoin-block-height-drift recording rule lands once the mempool.space external probe is deployed (Phase-2 follow-up):

```yaml
      # Pending external-probe deployment (Phase-2 follow-up sprint).
      # - record: wat_anchor_pipeline:bitcoin_block_height_drift
      #   expr: mempool_space_block_height_latest - wat_bitcoin_block_height_latest
```

Alert rules that reference these recording-rule names land in `docs/observability/alert-rules-wat-phase-2.md` (TBD next sprint).

---

## 5. Review cadence

- **Weekly:** Noa reviews the WAT-anchor pipeline dashboard every Monday morning. Burn-rate trends feed the weekly CTO report.
- **Monthly:** SLO targets re-validated. The 99% finalization-rate target is the load-bearing number; if monthly review shows we are hitting 99.9%, Mira can tighten the target via a follow-up ADR. If we are hitting 95%, Tomas root-causes before any target change.
- **Per WAT-core change:** Tomas pings Noa on every WAT-anchor-path PR. Noa reviews whether the change affects the gauge schema; if yes, the observability script and this catalogue are revised together.

---

## 6. Cross-review zones

This catalogue lives in the Zone-I cross-review (Noa × Tomas) per ADR-0042 §SRE Persona Definition. Tomas reviews the SLO definitions before deployment; the gauge-emitter script side (`scripts/wat-anchor-pipeline-observability.py`) is reviewed in the same Zone-I PR.

Zone-H (Noa × Kai) covers the textfile-collector substrate (the observability script writes into the same `/var/lib/node_exporter/textfile_collector/` path that Kai's node-exporter Quadlet already scrapes). No new Zone-H surface is opened by this sprint; the pattern matches `mira-hourly-watchdog.py`, `per-model-cost-aggregator.py`, and `cache-hit-rate-aggregator.py`.

---

## 7. Appendix A — CLI contract reference

### A.1 `wakir-anchor anchor-receipt --latest --json` output schema

```json
{
  "schema_version": 1,
  "receipt_path": "meta/timestamps/wat/.../root.bin.ots",
  "anchor_root_hex": "<64-hex-char SHA-256 root>",
  "verifier_state": "finalized" | "pending" | "failed",
  "bitcoin_block_height": <integer | null>,
  "bitcoin_block_hash": "<64-hex | null>",
  "calendar_attestations": <integer>,
  "anchor_timestamp_utc": "<ISO-8601 | null>",
  "finalized_timestamp_utc": "<ISO-8601 | null>",
  "age_seconds_since_anchor": <integer | null>,
  "age_seconds_since_finalized": <integer | null>,
  "spool_totals": {
    "finalized": <integer>,
    "pending": <integer>,
    "failed": <integer>
  }
}
```

The `schema_version` field is the cross-review-contract anchor: bumping it requires a synchronous Zone-I review with Noa. The observability script's `EXPECTED_SCHEMA_VERSION` constant (currently 1) tracks the latest reviewed schema; a CLI returning a higher version is treated as drift (SLI-WAT-4).

Fields whose value may be `null` (`bitcoin_block_height`, `bitcoin_block_hash`, `anchor_timestamp_utc`, `finalized_timestamp_utc`, `age_seconds_since_anchor`, `age_seconds_since_finalized`) are `null` exactly when the receipt is still in `verifier_state=pending` (Bitcoin block not yet known, finalize-time not yet known) or `verifier_state=failed`. The observability script renders `null` ages as `-1` and `null` block heights as `0` in the Prometheus textfile (so the gauge surface stays additive).

### A.2 Exit codes

The CLI is contracted to:

- exit **0** when it successfully read the spool and emitted JSON, even when the spool is empty (it emits a "no receipts yet" sentinel JSON object in that case),
- exit **non-zero** when the receipt-DB is unreadable or the OTS-calendar HTTP probe failed durably.

The observability script collapses both error paths into the `wat_anchor_pipeline_cli_failure=1.0` gauge.

---

## 8. Appendix B — Gauge schema reference

Every Prometheus gauge emitted by `scripts/wat-anchor-pipeline-observability.py`, with the SLI it backs:

| Gauge | SLI | Notes |
|---|---|---|
| `wat_anchor_finalized_count` | SLI-WAT-1 (numerator) | Spool-wide counter exposed as a gauge per textfile-collector restart-resilience. |
| `wat_anchor_pending_count` | SLI-WAT-1 (denominator part) | — |
| `wat_anchor_failed_count` | SLI-WAT-1 (denominator part) | — |
| `wat_anchor_calendar_attestations` | (operator-diagnostic, not SLI) | Latest receipt's calendar count. |
| `wat_last_anchor_age_seconds` | SLI-WAT-2 | `-1` if no data. |
| `wat_last_finalized_age_seconds` | (operator-diagnostic) | `-1` if no data. |
| `wat_bitcoin_block_height_latest` | SLI-WAT-3 (left side of the drift equation) | `0` if pending. |
| `wat_anchor_pipeline_schema_drift` | SLI-WAT-4 | 0/1. |
| `wat_anchor_cli_unavailable` | SLI-WAT-5 (Kai-side) | 0/1. |
| `wat_anchor_pipeline_cli_failure` | SLI-WAT-5 (Tomas-side) | 0/1. |
| `wat_anchor_pipeline_scrape_timestamp_seconds` | (correlator) | POSIX-epoch of last write. |

---

## 9. Anchors

- **Observability emitter:** `scripts/wat-anchor-pipeline-observability.py`
- **Hermetic tests:** `tests/infra/test_wat_anchor_pipeline_observability.py`
- **WAT-core CLI source:** `wat/cmd/anchor_cli.py` (Tomas PR #124 adds the `anchor-receipt` subcommand and the `--latest --json` flag pair)
- **Sister-doc (Phase 1b):** `docs/observability/sli-slo-phase-1b.md` — persona-engine + Mira-Hourly stack SLOs.
- **ADR anchors:** ADR-0064 §Folgeartefakte Phase-2-Observability (this sprint's mandate); ADR-0042 §SRE Persona Definition (Zone H + Zone I cross-review contract); ADR-0007 (WAT-Pipeline overview).
- **Cross-review zones:** Zone H (Noa × Kai container-operations — textfile-collector substrate); Zone I (Noa × Tomas WAT-core — CLI contract + SLO definitions).
- **OTS calendar contract reference:** `https://github.com/opentimestamps/python-opentimestamps` (the WAT-core's vendored dependency).
- **Bitcoin-block-height reference (Phase-2 follow-up):** `https://mempool.space/api/blocks/tip/height` — public endpoint, no API key, parsed as plain text integer.

---

*Noa Bergstroem — SRE, Wakir Labs · Sprint-WAT-Anchor-Pipeline-Live-Observability-MINI · 2026-05-16*
