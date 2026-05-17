<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Phase-3c Welle-Status Dashboard — Runbook

**Status:** Tag-30 Mini-Welle deliverable
**Owner:** Noa Bergstroem (SRE)
**Source-of-truth:** [`dashboards/persona-engine-phase-3c-welle-status.json`](../../dashboards/persona-engine-phase-3c-welle-status.json),
[`scripts/phase-3c-welle-status-emitter.py`](../../scripts/phase-3c-welle-status-emitter.py)
**Related ADRs:** ADR-0065 (Phase-3c cutover plan), ADR-0066 (4-week acceleration)
**Related runbooks:** [`phase-3c-cutover-runbook.md`](phase-3c-cutover-runbook.md), [`phase-3c-trigger-gates.md`](phase-3c-trigger-gates.md), [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md)

---

## 1. Why this dashboard exists

ADR-0066 collapsed the seven Phase-3c cutover welles into a four-week
schedule with two welles in parallel for KW 24, 26, and 27. During those
parallel weeks, the operator running the cutover-acceptance meeting needs
to answer four questions at a glance, on one panel:

1. **Where is each welle right now?** — `pre_cutover`, `in_cutover`,
   `post_cutover`, `rollback_active`, `welle_complete`.
2. **How many welles are active concurrently?** — capped at 2 by
   ADR-0066. A third concurrent welle is an automatic red.
3. **Is the python-vs-rust backend split healthy per welle?** — a
   sustained python skew on a welle in `in_cutover` or `post_cutover`
   is the operator's red flag.
4. **Has cross-modul-drift fired on a doppel-welle pair?** — the
   Phase-2-Acceptance-Gate cross-modul-pin-status feeds the indicator;
   `fail` is an automatic rollback trigger per ADR-0066 Mitigation-1.

The trigger-gate aggregator (Tag-24, `phase-3c-trigger-gate-aggregator.py`)
answers "can we start the next welle?" The baseline tracker (Tag-25,
`phase-3c-observability-baseline-tracker.py`) answers "do we have enough
BackendDecision history?" Neither answers "where is each welle right now?"
This dashboard does.

## 2. Architecture

```
+---------------------------+      +---------------------------+
| BackendDecision JSONL     |      | Phase-2-Acceptance-Gate   |
| (persona-engine emits     |      | output JSON               |
|  log_backend_decision)    |      | (cross_modul_pin_status)  |
+-------------+-------------+      +-------------+-------------+
              |                                  |
              v                                  v
       +------+----------------------------------+------+
       |   phase-3c-welle-status-emitter.py (Tag-30)    |
       |                                                |
       |   reads lifecycle-override JSON (operator-hand)|
       |   computes per-welle status + counters         |
       |   emits Prometheus textfile + JSON snapshot    |
       +-------------------------+----------------------+
                                 |
                                 v
                  +--------------+--------------+
                  | Prometheus (textfile coll.) |
                  +--------------+--------------+
                                 |
                                 v
       +-------------------------+---------------------------+
       | dashboards/persona-engine-phase-3c-welle-status.json|
       +-----------------------------------------------------+
```

The emitter is **stdlib-only**: no podman, no NATS, no live cosign
invocation. It reads on-disk inputs and writes on-disk outputs. This
keeps the dashboard substrate inside the sandbox-host-trennung
discipline ([`feedback_sandbox_host_trennung.md`](../../../.claude/memory/feedback_sandbox_host_trennung.md)
in the agents repo).

## 3. Input contract

### 3.1 BackendDecision JSONL (required)

Path resolution priority:

1. `--decisions-jsonl PATH` CLI flag (operator override).
2. `WAKIR_PHASE_3C_OBS_BASELINE_PATH` ENV (shared with the Tag-24
   Gate-4 aggregator).
3. `WAKIR_BACKEND_DECISION_JSONL` ENV (shared with the Tag-22
   observability aggregator).

When no path resolves, the emitter exits **2** with a clear stderr
message. This is intentional — without BackendDecision evidence the
dashboard has nothing substantive to show, and a green-by-default
posture would be misleading.

Each record matches the schema
`wirelang/persona_engine/rust_backend_switch.py::log_backend_decision`:

```json
{
  "level": "INFO",
  "msg": "backend-decision",
  "domain": "v907_verify",
  "requested_backend": "rust",
  "chosen_backend": "rust",
  "resolution_latency_us": 142,
  "fallback_reason": null,
  "bin_path": "/usr/local/bin/wakir-v907-verify",
  "ts": "2026-05-17T20:00:00Z"
}
```

### 3.2 Lifecycle-override JSON (optional)

Path resolution priority:

1. `--lifecycle-json PATH`.
2. `WAKIR_PHASE_3C_WELLE_LIFECYCLE` ENV.

When the file is absent, every welle defaults to `pre_cutover`. The
operator writes this file by hand at four points per welle:

| Operator-hand event             | Write to lifecycle JSON                    |
| ------------------------------- | ------------------------------------------ |
| Cutover-day 06:00 CEST start    | `{"<welle>": "in_cutover"}`                |
| Cutover-day 18:00 CEST close    | `{"<welle>": "post_cutover"}`              |
| Rollback gate tripped           | `{"<welle>": "rollback_active"}`           |
| Soak (7d) passed                | `{"<welle>": "welle_complete"}`            |

Multiple welles share one file: `{"1": "in_cutover", "2": "in_cutover"}`.

The emitter **does not auto-advance** the lifecycle. This is deliberate:
state transitions are operator decisions, not derived measurements.

### 3.3 Phase-2-Acceptance-Gate JSON (optional)

Path resolution priority:

1. `--phase2-acceptance-json PATH`.
2. `WAKIR_PHASE_2_ACCEPTANCE_OUTPUT` ENV.

When the file is absent, the `cross_modul_drift` indicator is yellow
with reason `phase-2-acceptance-output-not-configured`. Yellow is
conservative; a missing file is "no signal", not green.

The emitter reads only one field:

```json
{ "cross_modul_pin_status": "pass" | "fail" | "skipped" | ... }
```

`pass` -> GREEN, `fail` -> RED, everything else -> YELLOW.

## 4. Operator workflow

### 4.1 During a cutover week (e.g., KW 24, Welle-1+2 parallel)

```bash
# 1. Cutover-day 06:00 CEST: mark Welle-1 and Welle-2 as in_cutover.
cat > /var/lib/wakir/phase-3c-welle-lifecycle.json <<'EOF'
{
  "1": "in_cutover",
  "2": "in_cutover"
}
EOF

# 2. Emitter cron is already running every 60s on the monitoring host.
#    Confirm the snapshot file is fresh:
ls -la /var/lib/node_exporter/textfile_collector/phase-3c-welle-status.prom

# 3. Open the Grafana dashboard: Wakir Persona-Engine - Phase-3c Welle Status.
#    Both Welle-1 and Welle-2 panels should be YELLOW (in_cutover).
#    Welle-Aktiv-Count = 2, Doppel-Welle-Cap = 2, cap_exceeded = false.

# 4. Cutover-day 18:00 CEST: cutover-day done, soak window opens.
cat > /var/lib/wakir/phase-3c-welle-lifecycle.json <<'EOF'
{
  "1": "post_cutover",
  "2": "post_cutover"
}
EOF

# 5. Seven days later, soak passed:
cat > /var/lib/wakir/phase-3c-welle-lifecycle.json <<'EOF'
{
  "1": "welle_complete",
  "2": "welle_complete"
}
EOF
```

### 4.2 When a rollback fires

```bash
# Rollback triggered on Welle-1 (v907_verify p99 latency exceeded 3x baseline).
cat > /var/lib/wakir/phase-3c-welle-lifecycle.json <<'EOF'
{
  "1": "rollback_active",
  "2": "in_cutover"
}
EOF

# Dashboard:
#  - Welle-1 panel turns RED.
#  - Welle-Aktiv-Count remains 2 (rollback counts as active).
#  - Emitter exit-code = 1 (alerting picks this up).
#
# Once rollback completes and Welle-1 is back to python-default,
# move it to welle_complete (failed-and-reverted is still terminal
# for the marathon counter — operator decision).
```

### 4.3 Reading the dashboard during a parallel-welle audit

The cross-modul-drift panel is the doppel-welle-week's primary signal:

| Panel state | Meaning                                                  | Action                                                  |
| ----------- | -------------------------------------------------------- | ------------------------------------------------------- |
| GREEN       | Phase-2-Acceptance-Gate cross_modul_pin = pass           | Continue both welles per schedule.                      |
| YELLOW      | Phase-2-Acceptance-Gate output missing OR skipped        | Investigate operator-hand setup; do NOT start a doppel. |
| RED         | Phase-2-Acceptance-Gate cross_modul_pin = fail           | Immediate rollback of BOTH active welles per ADR-0066.  |

## 5. Deployment

### 5.1 Where the emitter runs

The emitter ships as `scripts/phase-3c-welle-status-emitter.py` in the
`wakir-runtime` repo. Two deployment patterns:

* **Workstation / dry-run pattern:** operator runs the emitter ad-hoc
  with `--out var/phase-3c-welle-status.json` and inspects the JSON
  by hand. No Prometheus, no Grafana.
* **Live deployment pattern:** Kai's container substrate runs the
  emitter as a `systemd.timer` every 60s, writing the textfile
  rendering to `/var/lib/node_exporter/textfile_collector/phase-3c-welle-status.prom`.
  The node-exporter on the monitoring host scrapes the textfile.
  Grafana queries Prometheus via the `prom` datasource UID.

### 5.2 Container/Quadlet wiring (operator-hand, Zone H)

This dashboard is a Noa-substrate deliverable. The container/Quadlet
wiring lives in Kai's container-infra workspace and is **out of scope
for this PR** per the Zone-H cross-review discipline. The follow-up
spawn for Kai is a separate substrate task.

What Kai needs from this PR (already satisfied):

* `scripts/phase-3c-welle-status-emitter.py` — stdlib-only Python entry
  point. Kai wraps it in a `systemd.timer` unit.
* Metric-family names are stable (see section 6).
* JSON snapshot schema (`$.schema = "wakir.phase-3c.welle-status-emitter/1"`)
  is versioned. Schema bump = new dashboard. No silent breakage.

## 6. Stable metric-family contract

The Grafana dashboard queries these Prometheus metric families. Renaming
them is a **schema-breaking change** that requires a coordinated
dashboard update.

| Metric family                                              | Labels                                       | Meaning                                              |
| ---------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------- |
| `persona_engine_phase_3c_welle_state`                      | `welle`, `domain`, `state`                   | Long-form one-hot per welle per state.               |
| `persona_engine_phase_3c_welle_decisions_total`            | `welle`, `domain`, `backend`                 | BackendDecision counts by backend family.            |
| `persona_engine_phase_3c_welle_fallback_total`             | `welle`, `domain`                            | Fallback-record count.                               |
| `persona_engine_phase_3c_welle_latency_us`                 | `welle`, `domain`, `backend`, `quantile`     | resolution_latency_us percentiles.                   |
| `persona_engine_phase_3c_marathon_progress_pct`            | (none)                                       | count(welle_complete) / 7 * 100.                     |
| `persona_engine_phase_3c_welle_aktiv_count`                | (none)                                       | in_cutover + rollback_active welles.                 |
| `persona_engine_phase_3c_doppel_welle_cap`                 | (none)                                       | Static 2.                                            |
| `persona_engine_phase_3c_cap_exceeded`                     | (none)                                       | 1.0 if welle_aktiv_count > 2.                        |
| `persona_engine_phase_3c_cross_modul_drift`                | `status`                                     | One-hot over green/yellow/red.                       |

Adding a new metric is non-breaking. Removing or renaming a metric
requires a coordinated dashboard PR and a bump of `SCHEMA_ID` in the
emitter.

## 7. Exit-code contract

| Exit | Meaning                                                                 |
| ---- | ----------------------------------------------------------------------- |
| 0    | Snapshot clean; no rollback active, cap not exceeded.                   |
| 1    | At least one welle in `rollback_active`, OR cap exceeded (`>2` active). |
| 2    | Input resolution failed (JSONL path unset), OR lifecycle JSON invalid.  |

Exit-code 1 is the AlertManager hook the live deployment uses to page.

## 8. Phase-3c Welle Inventory

Source: ADR-0066 §Welle-Sequenz (override of ADR-0065 §Empfehlung).

| Welle | Domain                    | KW    | Pair      |
| ----- | ------------------------- | ----- | --------- |
| 1     | `v907_verify`             | KW 24 | welle-2   |
| 2     | `svid_workload_identity`  | KW 24 | welle-1   |
| 3     | `bridge_audit_writer`     | KW 25 | solo      |
| 4     | `state_backing`           | KW 26 | welle-5   |
| 5     | `lifecycle_state_machine` | KW 26 | welle-4   |
| 6     | `subscribe_loop`          | KW 27 | welle-7   |
| 7     | `recovery_workflow`       | KW 27 | welle-6   |

Adding an eighth welle requires editing both `WELLE_DOMAIN_MAP` in
the emitter AND adding a stat panel in the dashboard JSON AND bumping
the dashboard `version` field. ADR-0065 / ADR-0066 amendment first.

## 9. Test coverage

Hermetic test suite: [`tests/scripts/test_phase_3c_welle_status_emitter.py`](../../tests/scripts/test_phase_3c_welle_status_emitter.py).
15 tests covering:

* Module public-API surface.
* Path-resolution priority for all three input ENVs.
* Default-pre-cutover when lifecycle absent.
* Per-welle python/rust/fallback split.
* Lifecycle override advances states.
* Marathon-progress gauge math.
* Welle-aktiv counter + cap-exceeded logic.
* Rollback-active exit-code 1.
* Cross-modul-drift tri-state mapping.
* Latency percentile computation per backend.
* Prometheus textfile metric-name stability.
* CLI `--out` + `--prom-textfile` integration.
* Invalid lifecycle state -> exit-code 2.
* JSONL malformed-line tolerance.

## 10. Open follow-ups (post-Tag-30)

* **Kai container-infra spawn** — wrap the emitter in a `systemd.timer`
  + Quadlet unit so the live deployment runs it every 60s. Zone H
  cross-review. Out of scope for this PR.
* **AlertManager rule** — `phase_3c_cap_exceeded == 1` for >5 minutes
  pages the on-call. To be authored once the live deployment lands.
* **Welle-1 cutover-week (KW 24)** — the dashboard's first live test.
  Document the actual operator-hand cadence in
  [`phase-3c-welle-1-runbook.md`](phase-3c-welle-1-runbook.md) as a
  post-Tag-30 backfill.
