<!-- SPDX-License-Identifier: Apache-2.0 -->

# Aggregator Monitoring — Operator Documentation

**Audience:** SRE / Mira-Hand operators triaging the ADR-0068
`ci-aggregator` migration window (Tag-37 PR #244 land → ~1-week
observation → Mira-Hand-cutover).

**Authors:** Noa Bergstroem (SRE), Tag-38.
**Anchors:** ADR-0068 §Migration-Strategy + §Beschluss; PR #244
`e29439dc` (Tomas, Tag-37); `scripts/ci/ci_aggregator.py` substrate.

---

## What this document covers

1. The three Tag-38 observability substrates and how they fit together.
2. How to run the failure-rate-tracker (operator workstation + CI).
3. The drift-detection schema — what fires, what gates the Mira-Hand-
   cutover.
4. The Prometheus / Grafana access path for the cross-welle dashboard.
5. Notify-paths and the Mira-Hand follow-up checklist for non-zero drift.

---

## 1. Substrates

Three artefacts ship with the Tag-38 spawn (this PR):

| Artefact | Path | Role |
|---|---|---|
| Failure-rate tracker | `scripts/observability/aggregator-failure-rate-tracker.py` | Polls ci-aggregator runs, rolls per-check failure-rate + latency, detects drift vs legacy-union. |
| Cross-welle dashboard | `dashboards/phase-3c-cross-welle-coordination.json` | Grafana JSON — five operator-views unified (Welle-status, cross-modul-drift, BackendDecision-snapshot, aggregator-verdict-stream, Henrik-signoff). |
| Hermetic tests | `tests/observability/test_aggregator_failure_rate_tracker.py` | 23 tests covering pure-function decision core. |

The tracker is the **producer** of the `wakir_aggregator_*` Prometheus
gauges. The dashboard is the **consumer**.

---

## 2. Running the failure-rate tracker

### Operator workstation (`gh` CLI mode, default)

```bash
cd /path/to/wakir-runtime
python3 scripts/observability/aggregator-failure-rate-tracker.py \
  --owner=wakir-labs \
  --repo=wakir-runtime \
  --max-runs=100 \
  --json-output=/tmp/aggregator-rollup.json
```

Default `--mode=gh-cli` shells out to `gh api`. Requires `gh auth login`
beforehand. Exit code 0 = no drift, 1 = drift detected (cutover blocker).

For a quick visual scan:

```bash
python3 scripts/observability/aggregator-failure-rate-tracker.py \
  --owner=wakir-labs --repo=wakir-runtime --max-runs=50 \
  | jq '.rollups[] | {check_name, win_50: .windows["50"] | {failure_rate, samples: .sample_count, p95: .latency_p95_seconds}}'
```

### CI-host mode (`live`, urllib + `GITHUB_TOKEN`)

For invocation from a Kai-Container-Infra-deployed cron / systemd-timer
host (no `gh` CLI installed):

```bash
GITHUB_TOKEN=ghp_... python3 scripts/observability/aggregator-failure-rate-tracker.py \
  --mode=live \
  --owner=wakir-labs --repo=wakir-runtime \
  --max-runs=500 \
  --json-output=/var/lib/wakir/aggregator-rollup.json \
  --prometheus-output=/var/lib/prometheus/node-exporter/wakir_aggregator_failure_rate.prom
```

The Prometheus textfile path is the conventional node-exporter scrape
directory. Kai owns the node-exporter deployment; coordination via
Zone-H (Noa-Spec, Kai-Substrate). See `agents-workspaces/sre/` for the
spec-side ownership.

### Hermetic / dry-run mode

For test fixtures or offline operator demonstration:

```bash
python3 scripts/observability/aggregator-failure-rate-tracker.py \
  --mode=fixture \
  --fixture-runs=/path/to/fixture.json \
  --json-output=/tmp/rollup.json
```

The fixture schema is documented in the tracker's `load_fixture_runs`
docstring.

---

## 3. Drift-detection schema

### What is a drift event?

Per `compute_legacy_vs_aggregator_drift`, a drift event is a
`ci-aggregator` run on a `head_sha` where the aggregator's own job
conclusion **disagrees** with the union of the six legacy Required-
Status-Check verdicts.

The six legacy names are pinned in `LEGACY_REQUIRED_NAMES` and the
hermetic test
`test_legacy_required_names_match_aggregator_inventory` enforces
that they match the `SUB_WORKFLOWS` inventory in
`scripts/ci/ci_aggregator.py`.

### Union semantics

| Per-check verdicts | Union verdict |
|---|---|
| All six = `success` | `success` |
| Any = `failure` / `cancelled` / `timed_out` | `failure` |
| All six = `skipped` (no path-filter triggered) | `success` (skip-ok equivalent) |
| Any required check missing from the run's jobs list | `missing` |
| Mixed `success` + `skipped` | `success` |

### Threshold: zero

ADR-0068 §Migration-Step-2 expects **zero** drift events over the ~1-
week observation window. A single divergence is enough to:

1. Make the tracker exit non-zero (operator-visible signal).
2. Increment `wakir_aggregator_drift_events` to `>=1`.
3. Light up panel 31 of the cross-welle dashboard red.
4. Block the Mira-Hand-cutover script from running until investigated.

### Investigation flow

When a drift event fires:

1. **Capture context** — the tracker's JSON output includes
   `legacy_per_check` for every drift event. Pin this in a Mira-inbox
   note (path under `agents-workspaces/mira/inbox/`).
2. **Classify** — was the drift a `false-positive` (aggregator said
   `failure`, legacy-union said `success`) or `false-negative`
   (aggregator said `success`, legacy-union said `failure`)?
   - False-positive is annoying but not unsafe — it would block
     merges that the legacy stack would have allowed.
   - **False-negative is unsafe** — it would have admitted a PR that
     the legacy stack would have blocked. This is the cutover-blocker
     class.
3. **Reproduce** — the `head_sha` in the drift event is the reproducer.
   Re-run the aggregator on that SHA via `workflow_dispatch` to confirm.
4. **Patch the inventory** — most drift events trace to a path-glob
   in `SUB_WORKFLOWS` that does not match the live workflow's
   `paths:` filter. Patch the inventory in `scripts/ci/ci_aggregator.py`,
   land via PR, and reset the observation window.
5. **Reset window** — the `~1-week` cutover-eligibility-window resets
   from zero whenever a drift event fires. ADR-0068 §Migration-Step-3
   is gated on a clean window.

---

## 4. Prometheus / Grafana access

### Prometheus textfile path

Conventional location:

```
/var/lib/prometheus/node-exporter/wakir_aggregator_failure_rate.prom
```

The node-exporter `--collector.textfile.directory=` flag must point at
the parent directory. Kai's container-infra substrate owns the
node-exporter deployment.

### Gauges produced

| Gauge | Labels | Semantic |
|---|---|---|
| `wakir_aggregator_failure_rate` | `check`, `window` | Failures / (failures + successes). Skipped excluded. |
| `wakir_aggregator_latency_seconds` | `check`, `window`, `pct` (p50/p95/p99) | Wait-loop latency percentiles. |
| `wakir_aggregator_sample_count` | `check`, `window` | Sample count per window (for denominator-sanity). |
| `wakir_aggregator_drift_events` | (no labels) | Drift event count. Cutover-blocker if `>= 1`. |

### Dashboard import

```bash
curl -X POST http://grafana.internal/api/dashboards/db \
  -H "Authorization: Bearer $GRAFANA_TOKEN" \
  -H "Content-Type: application/json" \
  -d @dashboards/phase-3c-cross-welle-coordination.json
```

Dashboard UID: `wakir-phase-3c-cross-welle-coordination`. Direct-link
after import: `https://grafana.internal/d/wakir-phase-3c-cross-welle-coordination/`.

---

## 5. Notify paths and Mira-Hand follow-up

### Tracker invocation cadence

Recommendation: every 15 minutes during the cutover observation window
(ADR-0068 §Migration-Step-2). Frequency rationale: the aggregator runs
on every PR, typical PR-merge cadence is ~3-5 per hour during Phase-3c,
so 15-min cadence captures all completed runs without API rate-limit
strain (500 runs / 15 min = ~33 req/min, well below GitHub's
5000 req/hour authenticated ceiling).

### Notify-event semantics

A non-zero tracker exit code maps to a Mira-Notify event. The
suggested wiring (Kai-substrate-owned):

```bash
# In a Kai-deployed systemd-timer wrapper script:
if ! python3 scripts/observability/aggregator-failure-rate-tracker.py ...; then
  # Tracker exited non-zero => drift detected.
  /usr/local/bin/mira-notify-emitter \
    --severity=warn \
    --source=aggregator-failure-rate-tracker \
    --message="ADR-0068 cutover-window: drift detected, cutover blocked. See /var/lib/wakir/aggregator-rollup.json#drift_events"
fi
```

The `mira-notify-emitter` script does not yet exist as Tag-38; see the
**Mira-Hand follow-up items** below.

### Cutover gate

ADR-0068 §Migration-Step-3 (Mira-Hand-cutover, "remove the six legacy
Required-Status names from Branch-Protection, add `ci-aggregator` as
the sole Required name") is gated on:

1. `wakir_aggregator_drift_events == 0` for the last 7 calendar days.
2. `wakir_aggregator_failure_rate{check="ci-aggregator",window="100"} < 0.05`
   (aggregator itself is reliable).
3. At least 50 aggregator runs in the observation window
   (`wakir_aggregator_sample_count{window="50"} >= 50` for the
   `ci-aggregator` check).

The Mira-Hand-cutover script (not in this PR — Mira-Hand-Folge item)
should read these gauges and refuse to run if any of the three gates
fail.

---

## Mira-Hand follow-up items

These are out of Noa's substrate scope and require Mira-Hand or a
Kai-container-infra spawn:

1. **Kai-substrate:** Deploy node-exporter on the Mira-Hourly-Stack
   host with `--collector.textfile.directory=` pointing at
   `/var/lib/prometheus/node-exporter/`. Coordinate via Zone-H.
2. **Kai-substrate:** Systemd-timer wrapper that invokes the tracker
   every 15 minutes during the cutover-observation window.
3. **Mira-Hand:** Wire `mira-notify-emitter` (or equivalent ntfy
   channel) for non-zero tracker exit codes. Notify-payload should
   include the drift event's `head_sha` so the operator can
   re-run-workflow.
4. **Mira-Hand:** When the gate conditions in §5 hold, run the
   `gh api -X PUT /repos/wakir-labs/wakir-runtime/branches/main/protection`
   patch to remove the six legacy required-status-check names and
   add `ci-aggregator` as the sole name. This is the ADR-0068
   §Migration-Step-3 action.
5. **Henrik-coordination:** Henrik's `henrik-signoff-emitter` (panel
   41-45 source) is referenced by the dashboard but not yet
   implemented. Until it lands, those tiles read uniformly `pending`.
   Henrik-spawn or Mira-Hand can write the gauge directly via the
   persona-engine pushgateway as an interim.

---

## Cross-references

- ADR-0068 (Status-Aggregator-Workflow als alleiniger Required-Status-Check, approved 2026-05-18)
- ADR-0066 (Phase-3c Beschleunigung Option A+, KW-24..27 Wellen-Plan)
- `scripts/ci/ci_aggregator.py` (Tomas Tag-37 PR #244 substrate)
- `docs/ci/aggregator-workflow.md` (Tomas Tag-37 PR #244 docs)
- `scripts/backend-decision-observability.py` PR #179 (BackendDecision-Aggregator)
- `dashboards/persona-engine-phase-3c-welle-status.json` (per-welle high-frequency view)
- `dashboards/persona-engine-backend-decisions.json` (per-engine BackendDecision drill-down)

— Noa Bergstroem (SRE), Tag-38
