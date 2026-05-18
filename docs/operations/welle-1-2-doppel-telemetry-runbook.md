<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Welle-1+2 (KW-24 Doppel-Cutover) Day-0 Telemetry Runbook

| Field | Value |
|---|---|
| Owner | Noa Bergstroem (SRE) |
| Status | Tag-32 Mini-Welle deliverable |
| Substrate | [`scripts/welle-1-2-doppel-telemetry-emitter.py`](../../scripts/welle-1-2-doppel-telemetry-emitter.py), [`dashboards/persona-engine-phase-3c-welle-status.json`](../../dashboards/persona-engine-phase-3c-welle-status.json) (panels 51-63) |
| Related ADRs | ADR-0065 (Phase-3c cutover plan), ADR-0066 (Acceleration + doppel-week schedule) |
| Sibling runbooks | [`welle-3-telemetry-runbook.md`](welle-3-telemetry-runbook.md), [`phase-3c-welle-status-dashboard-runbook.md`](phase-3c-welle-status-dashboard-runbook.md), [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md), [`phase-3c-welle-2-runbook.md`](phase-3c-welle-2-runbook.md) |
| Welles | 1 (`v907_verify`) + 2 (`svid_workload_identity`) |
| Cutover-Week | KW 24 (Mo Dry-Run, Mi Cutover) |

---

## 1. Why this telemetry exists

ADR-0066 (2026-05-17) collapsed the seven Phase-3c cutover welles
into a four-week schedule. KW 24 is the **first doppel-week**:

* **Welle-1** — `v907_verify` (ENV `WAKIR_V907_VERIFY_BACKEND`)
* **Welle-2** — `svid_workload_identity`
   (ENV `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND`)

Both welles run in parallel through one Monday Dry-Run and one
Wednesday Cutover. The Tag-31 Welle-3 telemetry addressed the **solo
welle's** circular-oracle risk. KW 24 has a different risk profile
that needs its own Day-0 observability:

> **Doppel-Welle Correlation Risk.** When two welles cut over in the
> same week, a regression that affects both modules (a shared
> dependency, a host-OS quirk, a SPIFFE config drift) can hide
> inside the aggregate counters Tag-30's general welle-status emitter
> exposes. Aggregate "all green" can mask "Welle-1 -3pp, Welle-2 +3pp".

The Tag-32 mitigation has three parts that mirror the Welle-3 design
but at **per-welle** granularity:

1. **Per-welle high-frequency self-score panels.** Two 10s-tick self-
   score timeseries, one for each welle. Sliding window over the
   `BackendDecision` JSONL, filtered by domain. Substrate behind
   panels 51 (Welle-1) and 57 (Welle-2).

2. **Per-welle independent oracle panels.** Phase-2 cross-modul
   stress test runs **outside** each welle's code path. The Phase-2
   output JSON carries per-welle entries (preferred schema) so the
   dashboard renders Welle-1 self-score next to Welle-1 oracle, and
   the same pair for Welle-2.

3. **Per-welle divergence red-flag tiles + a single combined health-
   score.** Each welle gets its own red-flag (`>0.5pp` divergence OR
   `oracle status == fail`). The combined health-score panel takes
   `min(welle-1 self-score, welle-2 self-score)` so an operator who
   only watches one tile still sees the weaker welle. The combined
   red-flag fires when **any** per-welle red-flag is set; the reason
   label cites which welle(s).

## 2. Architecture

```
+---------------------------+      +---------------------------+
| BackendDecision JSONL     |      | Phase-2 cross-modul       |
| (persona-engine emits     |      | stress-test output JSON   |
|  log_backend_decision)    |      | (per-welle entries)       |
+-------------+-------------+      +-------------+-------------+
              |                                  |
              v                                  v
       +------+----------------------------------+------+
       |   welle-1-2-doppel-telemetry-emitter.py (Tag-32)|
       |                                                |
       |   For each welle in {1, 2}:                    |
       |     * sliding-window over that welle's domain  |
       |     * self-consistency score                   |
       |     * independent oracle from per_welle entry  |
       |     * red-flag iff |self - oracle| > 0.5pp     |
       |       OR oracle status == fail                 |
       |                                                |
       |   Combined:                                    |
       |     * health-score = min(self-scores)          |
       |     * red-flag = any(per-welle red-flag)       |
       |     * pair-aktiv-count                         |
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
                  | 51 (Welle-1 self-score)     |
                  | 52 (Welle-1 oracle)         |
                  | 53 (Welle-1 divergence pp)  |
                  | 54 (Welle-1 red-flag)       |
                  | 55 (Welle-1 aktiv)          |
                  | 56 (Welle-1 window split)   |
                  | 57 (Welle-2 self-score)     |
                  | 58 (Welle-2 oracle)         |
                  | 59 (Welle-2 divergence pp)  |
                  | 60 (Welle-2 red-flag)       |
                  | 61 (Welle-2 aktiv)          |
                  | 62 (Welle-2 window split)   |
                  | 63 (Combined health-score)  |
                  +-----------------------------+
```

The emitter is one-shot: a single invocation produces one snapshot
covering both welles. The 10s cadence is enforced by the caller's
systemd timer or cron loop. The emitter does **not** sleep,
daemonize, or schedule itself.

## 3. Inputs

### 3.1 BackendDecision JSONL (decisions log)

Same file Tag-30's general emitter and Tag-31's Welle-3 emitter read.
The doppel emitter scans the file **twice** — once filtered by
`domain == "v907_verify"` (Welle-1), once by
`domain == "svid_workload_identity"` (Welle-2). Records for other
welles (`bridge_audit_writer`, `state_backing`, ...) are silently
skipped.

Path resolution (CLI > ENV > none):

1. `--decisions-jsonl PATH`
2. `WAKIR_PHASE_3C_OBS_BASELINE_PATH` ENV
3. `WAKIR_BACKEND_DECISION_JSONL` ENV

### 3.2 Phase-2 cross-modul stress-test output JSON

The Phase-2-Acceptance-Gate's optional cross-modul stress-test runs
outside each welle's code path and emits a single JSON file with
**per-welle entries**:

```json
{
  "per_welle": {
    "1": {
      "cross_modul_stress_status": "pass",
      "cross_modul_stress_score_pct": 99.7
    },
    "2": {
      "cross_modul_stress_status": "pass",
      "cross_modul_stress_score_pct": 99.4
    }
  }
}
```

Backward-compatibility fallback (single root-level status, applied
to both welles) is preserved for old Phase-2 outputs:

```json
{
  "cross_modul_stress_status": "pass",
  "cross_modul_stress_score_pct": 99.0
}
```

Path resolution:

1. `--phase2-stress-json PATH`
2. `WAKIR_PHASE_2_STRESS_OUTPUT` ENV

Behaviour when the file is missing, malformed, or the per-welle entry
is absent: the affected welle's oracle status degrades to YELLOW with
a diagnostic reason. The dashboard's per-welle oracle panel renders
the YELLOW status; the divergence and red-flag panels surface the
`stress-oracle-score-missing` reason rather than firing.

### 3.3 Lifecycle override JSON (optional)

Operator-hand state-machine override for the per-welle lifecycle
state (PRE_CUTOVER / IN_CUTOVER / POST_CUTOVER / ROLLBACK_ACTIVE /
WELLE_COMPLETE). Same format as Tag-30 / Tag-31:

```json
{
  "1": "in_cutover",
  "2": "in_cutover"
}
```

Path resolution:

1. `--lifecycle-json PATH`
2. `WAKIR_PHASE_3C_WELLE_LIFECYCLE` ENV

Missing or malformed override -> both welles default to PRE_CUTOVER
(safe degrade — a malformed lifecycle should not falsely advance a
welle).

## 4. Outputs

### 4.1 JSON snapshot

Written to `--out PATH` (or stdout if omitted). Top-level schema:

```json
{
  "schema_id": "wakir.persona-engine.welle-1-2-doppel-telemetry.v1",
  "generated_at": "2026-05-18T09:00:00Z",
  "pair_label": "1+2",
  "window_seconds": 300,
  "tick_interval_seconds": 10,
  "divergence_threshold_pct": 0.5,
  "welles": [
    {"welle": 1, "domain": "v907_verify", "env_var": "WAKIR_V907_VERIFY_BACKEND",
     "welle_state": "...", "welle_aktiv": true, "window_counts": {...},
     "consistency_score_pct": ..., "stress_oracle": {...},
     "divergence_pct": ..., "divergence_red_flag": ...,
     "red_flag_reason": "..."},
    {"welle": 2, "domain": "svid_workload_identity",
     "env_var": "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND", ...}
  ],
  "combined_health_score_pct": ...,
  "combined_red_flag": false,
  "combined_red_flag_reason": "ok",
  "pair_aktiv_count": 2,
  "doppel_welle_cap": 2
}
```

### 4.2 Prometheus textfile

Written to `--prom-textfile PATH`. All gauges. Per-welle metrics
carry `welle="1"|"2"`, `domain="v907_verify"|"svid_workload_identity"`,
`pair="1+2"` labels. Combined metrics carry `pair="1+2"`.

Per-welle metric names (emitted once per welle):

* `persona_engine_doppel_welle_consistency_score`
* `persona_engine_doppel_welle_stress_oracle_score`
* `persona_engine_doppel_welle_divergence_pct`
* `persona_engine_doppel_welle_divergence_red_flag`
* `persona_engine_doppel_welle_window_python_count`
* `persona_engine_doppel_welle_window_rust_count`
* `persona_engine_doppel_welle_window_fallback_count`
* `persona_engine_doppel_welle_window_seconds`
* `persona_engine_doppel_welle_tick_interval_seconds`
* `persona_engine_doppel_welle_divergence_threshold_pct`
* `persona_engine_doppel_welle_aktiv`

Combined metric names (emitted once):

* `persona_engine_doppel_welle_combined_health_score`
* `persona_engine_doppel_welle_combined_red_flag`
* `persona_engine_doppel_welle_pair_aktiv_count`

`None` numeric values render as `NaN` per the Prometheus textfile
spec. Booleans render as `0` or `1`.

### 4.3 Exit code

* `0` — snapshot built, no red-flag.
* `1` — snapshot built, **any** red-flag (per-welle or combined).
  Operator investigation required; the doppel-week rollback decision
  attaches to the **specific** welle that fired the flag.
* `2` — input error (malformed JSON / unreadable file / bad CLI).

## 5. Operator playbook

### 5.1 Pre-Cutover (Sunday evening of KW 24)

1. Confirm the dashboard renders the Welle-1+2 row (panels 51-63).
2. Confirm Welle-1 aktiv = 0 and Welle-2 aktiv = 0 (both
   `PRE_CUTOVER`). Pair-aktiv-count = 0.
3. Confirm combined health-score panel reads NaN (no traffic in
   window yet). Confirm combined red-flag = 0.

### 5.2 Monday — Dry-Run

1. Operator-hand flips lifecycle override:
   `{"1": "in_cutover", "2": "in_cutover"}`. Both aktiv tiles turn
   yellow, pair-aktiv-count = 2.
2. Dry-run traffic begins on a small slice. Watch panels 51 / 57
   (self-scores). Both should climb toward 99-100% as rust takes
   over the dry-run percentage.
3. Watch panel 63 (combined health-score). It tracks the weaker of
   the two self-scores. A 99/100 split renders combined = 99.
4. Phase-2 stress test runs in parallel. Watch panels 52 / 58
   (oracles). Both should sit at GREEN with a score within 0.5pp of
   each welle's self-score.
5. At end of dry-run window: flip lifecycle override to
   `{"1": "post_cutover", "2": "post_cutover"}`. Aktiv tiles return
   to blue; pair-aktiv-count = 0. Soak overnight.

### 5.3 Wednesday — Cutover

1. Operator-hand flips back to `{"1": "in_cutover", "2": "in_cutover"}`.
2. Cutover traffic ramps. **Watch panels 53, 54 (Welle-1 divergence
   + red-flag) and 59, 60 (Welle-2 divergence + red-flag).**
3. **If panel 54 turns red (Welle-1 red-flag):**
   * The emitter has exited 1 on the latest tick.
   * The reason label tells you which trigger fired
     (`divergence-N.NNNNpct-exceeds-threshold-0.5000pct` or
     `stress-oracle-status-fail`).
   * Open the Welle-1 cutover runbook
     [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md)
     §Rollback. **Do not** treat Welle-2 as red unless its own
     red-flag (panel 60) is set.
4. **If panel 60 turns red (Welle-2 red-flag):** same procedure with
   Welle-2's runbook.
5. **If panel 63's combined red-flag tile is red but neither panel
   54 nor panel 60 is red:** that's a contradiction — the emitter
   should never set combined-red-flag without a per-welle red-flag.
   File an SRE ticket against the doppel emitter.

### 5.4 Post-Cutover (Friday)

1. Lifecycle override `{"1": "post_cutover", "2": "post_cutover"}`.
2. Watch self-scores and oracle scores stay flat at 99-100% over
   the 48h soak. Any sustained drift in either welle is the
   rollback trigger.
3. After 48h clean soak: lifecycle override to
   `{"1": "welle_complete", "2": "welle_complete"}`. Aktiv tiles
   stay blue, pair-aktiv-count = 0. The general welle-status
   dashboard's Marathon Progress increments by 2/7.

## 6. Failure modes (and what the operator sees)

| Failure | Self-score panel | Oracle panel | Divergence panel | Red-flag panel | Combined panel |
|---|---|---|---|---|---|
| No traffic in window yet | NaN | varies | NaN | green (reason `consistency-score-no-traffic-in-window`) | NaN |
| Stress oracle file missing | normal | NaN, status YELLOW | NaN | green (reason `stress-oracle-score-missing`) | tracks min self-score |
| Stress oracle reports `fail` | normal | shows score, status RED | shows numeric delta | RED (reason `stress-oracle-status-fail`) | RED |
| Per-welle divergence > 0.5pp | normal | normal | shows delta (red threshold) | RED (reason `divergence-N.NNNNpct-...`) | RED (cites that welle) |
| Welle-1 red, Welle-2 green | normal | normal | normal | per-welle accurate | RED, reason `welle-1-red-flag` |
| Both welles red | normal | normal | normal | both RED | RED, reason `welle-1+2-red-flag` |
| Phase-2 output uses legacy schema | normal | both welles same score | normal | both react identically | tracks min |

## 7. Drift guards / tests

`tests/scripts/test_welle_1_2_doppel_telemetry.py` (13 tests) covers:

1. Public-API surface (constants + functions present, default values
   stable).
2. Welle fix-set: `(1, v907_verify, ENV) + (2, svid_workload_identity, ENV)`
   — a copy-paste edit that drifts the env-var or domain will fail
   this test.
3. Path resolution priority (CLI > ENV > None) for all three input
   paths.
4. Window ingest filters by domain + time independently per welle;
   other welles' records do not leak into Welle-1 / Welle-2 windows.
5. Consistency-score math: empty -> None, pure rust -> 100, mixed ->
   ratio.
6. Per-welle stress-oracle schema + legacy-fallback + malformed-file
   degrade-safely behaviour.
7. Lifecycle override accepts string + int keys; missing welle ->
   PRE_CUTOVER; malformed file -> both PRE_CUTOVER.
8. Combined health-score = `min(per-welle scores)`; pair-aktiv-count
   = count of welles in_cutover/rollback_active.
9. Per-welle independent red-flags: a red Welle-2 does not falsely
   flag a green Welle-1; combined-reason cites the specific welle(s).
10. Inputs missing -> no red-flag, distinct reasons per welle.
11. Prometheus textfile emits all per-welle metric names twice (once
    per welle) and all combined metric names once with `pair="1+2"`.
12. CLI green path: exit 0, both JSON snapshot + Prometheus textfile
    written, payload schema stable.
13. CLI red-flag path: exit 1, combined-red-flag set, reason cites
    the specific welle; bad CLI flags -> exit 2.

## 8. Deployment

The emitter ships in the wakir-runtime repository alongside the
existing Tag-30 / Tag-31 emitters. Kai's container-infra-substrate
owns the systemd timer that runs the emitter on the deployment's
textfile-collector cadence (10s tick during the doppel-week, ramped
back to 1m for the post_cutover soak).

Sample systemd unit:

```ini
[Unit]
Description=Welle-1+2 doppel telemetry emitter (KW-24)
After=network.target

[Service]
Type=oneshot
Environment=WAKIR_PHASE_3C_OBS_BASELINE_PATH=/var/lib/wakir/persona-engine/decisions.jsonl
Environment=WAKIR_PHASE_2_STRESS_OUTPUT=/var/lib/wakir/phase-2/stress.json
Environment=WAKIR_PHASE_3C_WELLE_LIFECYCLE=/var/lib/wakir/operator/lifecycle.json
ExecStart=/usr/bin/python3 /opt/wakir/scripts/welle-1-2-doppel-telemetry-emitter.py \
  --out /var/lib/wakir/telemetry/welle-1-2-doppel.json \
  --prom-textfile /var/lib/node-exporter/textfile/welle-1-2-doppel.prom
```

Sample timer:

```ini
[Unit]
Description=Welle-1+2 doppel telemetry tick (KW-24, 10s)

[Timer]
OnBootSec=10s
OnUnitActiveSec=10s
Unit=welle-1-2-doppel-telemetry.service

[Install]
WantedBy=timers.target
```

## 9. Out of scope

* The emitter does **not** enforce the doppel-welle cap (that is
  Tag-30's job). It surfaces `pair_aktiv_count` so the dashboard can
  show inadvertent solo drift or cap violation.
* The emitter does **not** rotate, daemonize, or schedule itself.
* The emitter does **not** depend on NATS, podman, cosign, or any
  network resource. Stdlib + filesystem only.
* This runbook covers **only** the Welle-1+2 doppel cutover (KW 24).
  Welle-3 (KW 25 solo) is covered by [`welle-3-telemetry-runbook.md`](welle-3-telemetry-runbook.md).
  Welle-4+5 (KW 26) and Welle-6+7 (KW 27) will get analogous
  doppel-telemetry deliverables in their own mini-welles.

---

*Sign-off: Noa Bergstroem (SRE), Tag-32 Mini-Welle, 2026-05-17.*
