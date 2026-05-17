<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Welle-3 (Bridge-Audit-Writer) Telemetry Runbook

| Field | Value |
|---|---|
| Owner | Noa Bergstroem (SRE) |
| Status | Tag-31 Mini-Welle deliverable |
| Substrate | [`scripts/welle-3-telemetry-emitter.py`](../../scripts/welle-3-telemetry-emitter.py), [`dashboards/persona-engine-phase-3c-welle-status.json`](../../dashboards/persona-engine-phase-3c-welle-status.json) (panels 41-46) |
| Related ADRs | ADR-0065 (Phase-3c cutover plan), ADR-0066 (Acceleration + Welle-3 Mitigation-2) |
| Sibling runbooks | [`phase-3c-welle-status-dashboard-runbook.md`](phase-3c-welle-status-dashboard-runbook.md), [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md), [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md), [`phase-3c-welle-2-runbook.md`](phase-3c-welle-2-runbook.md) |
| Welle | 3 (`bridge_audit_writer`) |
| Cutover-Week | KW 25 (solo, no parallel partner) |

---

## 1. Why this telemetry exists

ADR-0066 condensed the seven Phase-3c cutover welles into a four-week
schedule by allowing two welles in parallel for KW 24, 26, and 27.
KW 25 is the lone exception: Welle-3 (`bridge_audit_writer`) runs
**solo**.

The reason is a structural risk Henrik (Internal Audit) flagged
during the ADR-0066 review:

> **Consistency-Oracle-Selbst-Cutover-Risiko.** Once the persona
> engine's Rust backend takes over `bridge_audit_writer`, the very
> module that emits the BackendDecision audit envelopes is itself
> being swapped. The python-vs-rust split read back from
> `bridge_audit_writer` is the module describing its own switch —
> a circular oracle. Soloing the week reduces variance, but the
> circular-oracle problem remains.

The Tag-31 mitigation has three parts:

1. **High-frequency self-score panel.** A 10-second tick (vs. the
   Tag-30 emitter's 1-minute tick) gives the operator a near-real-
   time view of `bridge_audit_writer`'s self-reported rust-rate
   during the KW-25 cutover window.

2. **Independent oracle panel.** A Phase-2 cross-modul stress test
   runs **outside** the `bridge_audit_writer` code path and emits
   its cross-modul-rust-rate to a separate output JSON. The
   dashboard renders the oracle's score as a trendline next to the
   self-score, so the operator can see the two curves diverge if
   the circular oracle is masking a defect.

3. **Divergence red-flag.** When the absolute delta between the
   self-score and the oracle exceeds 0.5 percentage points (or the
   oracle itself reports `fail`), the dashboard's red-flag tile
   turns red and the emitter exits with code 1. That exit code is
   the ADR-0066 Welle-3 immediate-rollback trigger.

## 2. Architecture

```
+---------------------------+      +---------------------------+
| BackendDecision JSONL     |      | Phase-2 cross-modul       |
| (persona-engine emits     |      | stress-test output JSON   |
|  log_backend_decision)    |      | (independent of           |
|                           |      |  bridge_audit_writer)     |
+-------------+-------------+      +-------------+-------------+
              |                                  |
              v                                  v
       +------+----------------------------------+------+
       |   welle-3-telemetry-emitter.py (Tag-31)        |
       |                                                |
       |   sliding-window over Welle-3 records only     |
       |   computes self-consistency score              |
       |   loads independent oracle score               |
       |   raises red-flag iff |self - oracle| > 0.5pp  |
       |   OR oracle status == fail                     |
       +-------------------------+----------------------+
                                 |
                                 v
                  +--------------+--------------+
                  | Prometheus textfile         |
                  | + JSON snapshot             |
                  +--------------+--------------+
                                 |
                                 v
                  +--------------+--------------+
                  | Grafana dashboard panels    |
                  | 41 (self-score)             |
                  | 42 (oracle)                 |
                  | 43 (divergence pp)          |
                  | 44 (red-flag)               |
                  | 45 (welle-3 aktiv)          |
                  | 46 (window backend split)   |
                  +-----------------------------+
```

The emitter is one-shot: a single invocation produces one snapshot.
The 10-second cadence is enforced by the caller's systemd timer or
cron loop. The emitter does **not** sleep, daemonize, or schedule
itself.

## 3. Invocation surface

### 3.1 Inputs (path resolution: CLI > ENV)

| Input | CLI flag | ENV (priority order) |
|---|---|---|
| BackendDecision JSONL | `--decisions-jsonl PATH` | `WAKIR_PHASE_3C_OBS_BASELINE_PATH`, then `WAKIR_BACKEND_DECISION_JSONL` |
| Phase-2 stress-test JSON | `--phase2-stress-json PATH` | `WAKIR_PHASE_2_STRESS_OUTPUT` |
| Lifecycle override JSON | `--lifecycle-json PATH` | `WAKIR_PHASE_3C_WELLE_LIFECYCLE` |

All inputs are optional. The emitter never invents numbers: a
missing or empty BackendDecision file produces a `null`
`consistency_score_pct`; a missing or unparseable stress-test file
produces a `YELLOW` oracle with `score_pct: null`; a missing
lifecycle override defaults the Welle-3 state to `pre_cutover`.

### 3.2 Configuration knobs

| Flag | Default | Meaning |
|---|---|---|
| `--tick-interval-seconds N` | 10 | Tick cadence (informational; the caller enforces it). Must be > 0. |
| `--window-seconds N` | 300 | Sliding-window length over the BackendDecision JSONL. Must be > 0. |
| `--divergence-threshold-pct F` | 0.5 | Red-flag threshold in percentage points. Must be >= 0. |

### 3.3 Outputs

| Flag | Default | Meaning |
|---|---|---|
| `--out PATH` | stdout | JSON snapshot. Same schema regardless of red-flag state. |
| `--prom-textfile PATH` | (none) | Prometheus node-exporter textfile-collector format. |

### 3.4 Exit codes

| Code | Meaning | Operator action |
|---|---|---|
| 0 | Snapshot built, no red-flag | Continue cutover; next tick. |
| 1 | Red-flag set | ADR-0066 Welle-3 immediate-rollback trigger. Run the rollback runbook (`phase-3c-cutover-runbook.md` §Rollback). |
| 2 | Input error (bad CLI / unreadable file / negative threshold) | Fix the caller's invocation; do not interpret as a Welle-3 signal. |

### 3.5 Example invocation

```bash
WAKIR_PHASE_3C_OBS_BASELINE_PATH=/var/lib/wakir/backend-decisions.jsonl \
WAKIR_PHASE_2_STRESS_OUTPUT=/var/lib/wakir/phase-2-stress.json \
WAKIR_PHASE_3C_WELLE_LIFECYCLE=/var/lib/wakir/welle-lifecycle.json \
  python3 scripts/welle-3-telemetry-emitter.py \
    --tick-interval-seconds 10 \
    --window-seconds 300 \
    --divergence-threshold-pct 0.5 \
    --out /run/wakir/welle-3-telemetry.json \
    --prom-textfile /var/lib/node_exporter/textfile_collector/welle-3-telemetry.prom
```

The systemd timer behind this invocation runs every 10 seconds. The
textfile collector picks up the `.prom` file on its own poll
interval; the `OnCalendar=*:*:0/10` schedule keeps the textfile
recent enough for the dashboard's `refresh: 1m` setting to never see
stale data.

## 4. Prometheus metric inventory

All gauges. All carry `welle="3"` and `domain="bridge_audit_writer"`
labels. The `welle_aktiv` gauge additionally carries the lifecycle
state as a `state` label; the `divergence_red_flag` gauge carries
the diagnostic reason as a `reason` label; the `stress_oracle_score`
gauge carries the oracle's tri-state status as a `status` label.

| Metric | Meaning | Dashboard panel |
|---|---|---|
| `persona_engine_welle_3_consistency_score` | Self-score: rust_count / total * 100 | 41 |
| `persona_engine_welle_3_stress_oracle_score` | Phase-2 stress-test cross-modul rust-rate | 42 |
| `persona_engine_welle_3_divergence_pct` | abs(self - oracle), percentage points | 43 |
| `persona_engine_welle_3_divergence_red_flag` | 1 iff rollback trigger fired | 44 |
| `persona_engine_welle_3_aktiv` | 1 iff state in {in_cutover, rollback_active} | 45 |
| `persona_engine_welle_3_window_python_count` | Python decisions in window | 46 |
| `persona_engine_welle_3_window_rust_count` | Rust decisions in window | 46 |
| `persona_engine_welle_3_window_fallback_count` | Fallback decisions in window | 46 |
| `persona_engine_welle_3_window_seconds` | Sliding window length | (label-only) |
| `persona_engine_welle_3_tick_interval_seconds` | Tick cadence in seconds | (label-only) |
| `persona_engine_welle_3_divergence_threshold_pct` | Configured threshold | (label-only) |

A `None` value (no signal yet) is rendered as `NaN` per the
Prometheus textfile spec; the dashboard tile shows "No data" and
neither green nor red.

## 5. Decision policy on the cutover hour

### 5.1 Pre-cutover (Monday morning, KW 25)

1. Confirm Tag-30 welle-status emitter is running on the 1-minute
   cadence (Tag-30 runbook §3).
2. Start the Welle-3 telemetry emitter on the 10-second cadence:
   ```bash
   systemctl start wakir-welle-3-telemetry.timer
   ```
3. Open the dashboard. Panels 41-46 should populate within one
   minute. Self-score and oracle should both be at the pre-cutover
   baseline (typically 0% rust because Welle-3 is still on
   `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=python`).
4. Flip the lifecycle override to `in_cutover`:
   ```bash
   jq '.["3"] = "in_cutover"' /var/lib/wakir/welle-lifecycle.json \
     > /var/lib/wakir/welle-lifecycle.json.tmp && \
   mv /var/lib/wakir/welle-lifecycle.json.tmp \
      /var/lib/wakir/welle-lifecycle.json
   ```
   Panel 45 turns yellow with state `in_cutover`.

### 5.2 During cutover (KW 25, Mon-Thu)

* Panel 41 (self-score) should climb from ~0% to near-100% as the
  Welle-3 env-var flip propagates.
* Panel 42 (oracle) should track within 0.5pp of panel 41.
* Panel 43 (divergence) should stay green (< 0.3pp), yellow at
  0.3-0.5pp, red at > 0.5pp.
* Panel 44 (red-flag tile) is the authoritative rollback signal.
* Panel 46 should show the rust series climbing and the python
  series flatlining; the fallback series should stay near zero.

### 5.3 Red-flag fires

The emitter exits 1 on any of:

* **Divergence > threshold.** Reason format:
  `divergence-<value>pct-exceeds-threshold-<configured>pct`.
* **Oracle status == fail.** Reason:
  `stress-oracle-status-fail`.

Operator action on red-flag:

1. Flip the lifecycle override to `rollback_active`:
   ```bash
   jq '.["3"] = "rollback_active"' /var/lib/wakir/welle-lifecycle.json \
     > /var/lib/wakir/welle-lifecycle.json.tmp && \
   mv /var/lib/wakir/welle-lifecycle.json.tmp \
      /var/lib/wakir/welle-lifecycle.json
   ```
2. Roll back the Welle-3 env-var:
   ```bash
   unset WAKIR_BRIDGE_AUDIT_WRITER_BACKEND
   systemctl restart wakir-persona-engine
   ```
3. Run the cutover-runbook §Rollback procedure for evidence capture.
4. File a Phase-3c incident ticket; tag with `welle-3`,
   `circular-oracle`, and the precise reason from panel 44.

### 5.4 Post-cutover (KW 25, Thu-Sun)

1. Flip the lifecycle override to `post_cutover` once the cutover
   PR has been live for the agreed soak window (ADR-0065 §Soak).
2. After 72 hours green: flip to `welle_complete`. Panel 45 turns
   blue, panel 41 stays near-100%.
3. Stop the 10-second telemetry timer (Tag-30 emitter continues to
   carry Welle-3 in the general welle-status panel):
   ```bash
   systemctl stop wakir-welle-3-telemetry.timer
   ```

## 6. Hermetic test surface

Tests live in
[`tests/scripts/test_welle_3_telemetry_emitter.py`](../../tests/scripts/test_welle_3_telemetry_emitter.py)
and run under the regular `tests` workflow. All twelve tests are
hermetic (stdlib + pytest, no network, no podman). The test list:

1. `test_module_loads_and_exports_public_surface`
2. `test_resolve_paths_priority_order_cli_env_none`
3. `test_ingest_window_filters_by_domain_and_time`
4. `test_compute_consistency_score_none_when_window_empty`
5. `test_load_stress_oracle_tri_state_and_score_pct`
6. `test_load_welle_3_lifecycle_string_and_int_keys`
7. `test_build_snapshot_red_flag_on_divergence_exceeds_threshold`
8. `test_build_snapshot_red_flag_on_stress_oracle_fail`
9. `test_build_snapshot_no_red_flag_when_inputs_missing`
10. `test_render_prometheus_textfile_emits_stable_metric_names`
11. `test_main_cli_writes_out_and_prom_textfile_returns_zero_when_green`
12. `test_main_cli_returns_one_on_divergence_red_flag`

## 7. Open follow-ups

* **Phase-2 stress-test wiring.** Tag-31 ships the emitter side
  only. The Phase-2-Acceptance-Gate workflow needs to emit the
  `cross_modul_stress_score_pct` field alongside the existing
  `cross_modul_stress_status`. Until that wiring lands, the oracle
  reports `score_pct: null` and the divergence math degrades to
  `None` (panel 43 shows "No data", panel 44 stays green). This is
  acceptable as long as the operator on the cutover call confirms
  the stress-test output *manually* during the rehearsal — but the
  follow-up Mini-Welle should automate it.

* **Alertmanager rule.** The dashboard's red-flag tile is the
  operator-facing signal during the cutover call. A back-channel
  alertmanager rule that pages on
  `persona_engine_welle_3_divergence_red_flag == 1` is a candidate
  for a follow-up Mini-Welle. Left out of Tag-31 to keep the PR
  scope tight per ADR-0066's single-PR-per-mitigation discipline.

* **Tag-30 emitter convergence.** The Tag-30 emitter's
  per-welle latency panels (30-32) do not currently
  cross-correlate with the Tag-31 self-score. Once KW 25 closes,
  fold the Welle-3 high-frequency panel back into the general
  welle-status dashboard so the post-mortem reviewer can compare
  Welle-3 trajectory against Welle-1/2 baseline.

— Noa
