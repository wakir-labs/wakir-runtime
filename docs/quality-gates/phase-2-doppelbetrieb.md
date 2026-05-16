# Quality-Gate — Phase 2 (Doppelbetrieb)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-N cross-check by Henrik (Internal Audit) |
| Status | Draft for Phase-1b → Phase-2 promotion |
| Phase | 2 — Doppelbetrieb (wakir-Tomás-Container runs in parallel with Pre-Framework-Tomás; both produce engineering-output; Doppelbetrieb-Score-CLI is authoritative comparison) |
| Source | ADR-0058 (Pilot-Persona-Migrations-Plan) §"Phase 4 Cutover-Entscheidung", Migration-Playbook §5 |
| Date approved | 2026-05-16 (draft pending Zone-N review and Engineering-Persona Zone-M concurrence) |

## 0. Phase contract

Phase 2 begins when Phase-1b has been stable for at least 7
consecutive days with all five Phase-1b acceptance-gates green and
Henrik's Audit-Sample for Phase-1b has cleared (no
ADR-0058-compliance findings outstanding).

In Phase 2 the wakir-Tomás-Container is **load-bearing in shadow**:
it consumes the same auftraege as Pre-Framework-Tomás (via the
bridge-forward fan-out), produces independent engineering-output,
and the Doppelbetrieb-Score-CLI runs every 6 hours over both
sinks to produce the four-axis verdict. The cutover (Phase-2 →
Phase-3) is gated on the four-axis verdict being `pass` for 6
consecutive weeks per ADR-0058.

## 1. Acceptance-Gates

### 2.1 All Phase-1b gates remain green

* **Gate:** Every gate from `phase-1b-pilot.md` §1 still passes for
  the duration of Phase 2.
* **Evidence:** Continuous CI-Live-VM-Acceptance-Gate runs (at least
  weekly).
* **Owned-by:** Kai + Selin (substrate stability), Amara (gate
  enforcement).

### 2.2 Bridge-Forward fan-out is symmetric

* **Gate:** For every auftrag published on
  `wakir.<env>.agent.agent.task.assigned.tomas`, exactly one output
  lands on the Pre-Framework-Tomás sink **and** one output lands on
  the wakir-Tomás-Container sink. Drop-rate ≤ 0.1% over rolling 24h.
* **Evidence:** Bridge-Forward fan-out metrics; bridge-audit
  reconciliation report (Sprint-10 Tag-6 spec §7).
* **Owned-by:** Reza (schema) + Selin (subscribe-loop) + Noa
  (metric/alerting).
* **Test-Vector:** new vector to be added in Phase-2 sprint; not in
  scope for Sprint-QA-Tag-15.

### 2.3 Doppelbetrieb-Score four-axis verdict ≥ pass for 6 consecutive weeks

* **Gate:** Every 6h Doppelbetrieb-Score-CLI run produces
  `verdict == "pass"` with:
  * `functional_equivalence >= 0.95`
  * `byte_delta` ≤ documented per-output-class threshold
  * `structural_equivalence >= 0.90`
  * `spurious_divergence <= 5` per 100 outputs (per Doppelbetrieb-
    Score-CLI defaults)
* **Evidence:** 6h Score-JSON outputs aggregated into a weekly
  rollup (`wirelang doppelbetrieb-aggregate` per Sprint-10 Tag-6).
* **Owned-by:** Selin (CLI) + Reza (schema).
* **Test-Vector:** existing `test_cli_doppelbetrieb_score.py` +
  `test_cli_doppelbetrieb_aggregate.py`. The 6-week threshold is
  a **runtime gate**, not a test-time gate — it lives in the
  weekly rollup-report Henrik samples.

### 2.4 No V-907 pin-drift events for 28 days

* **Gate:** Zero `PersonaHashDriftError` events emitted by
  `wakir-persona-tomas.service` over a rolling 28 days.
* **Evidence:** Bridge-audit `axis-a-pin` records all match the
  build-time pin; no `EXIT_V907_HASH_DRIFT` restarts.
* **Owned-by:** Selin (engine) + Henrik (audit-sample).

### 2.5 Persona-state KV-bucket integrity

* **Gate:** The NATS-KV bucket `wakir-persona-state-acme-tomas`
  carries one and only one `active_log` entry per Container-spawn,
  and the entries are monotonic by `transition.utc`.
* **Evidence:** `wirelang persona-inspect --kv-roundtrip` returns
  clean over the rolling 28-day window.
* **Owned-by:** Selin (engine state-backing).
* **Test-Vector:** existing
  `test_engine_natskv_active_log.py` covers the per-spawn invariant;
  rolling-window monotonicity is a **runtime gate** monitored by
  Noa-Alert.

## 2. Test-Coverage thresholds

Inherits all Phase-1b thresholds. Additional Phase-2-specific
thresholds:

| Component | Coverage threshold (line) | Coverage threshold (branch) | Source |
|---|---|---|---|
| `wirelang.cli.doppelbetrieb_aggregate` | 90% | 85% | Selin |
| `wirelang.persona_engine.bridge_audit_writer` | 90% | 85% | Selin |
| Bridge-forward fan-out logic (Reza spec module) | 85% | 80% | Reza |

## 3. SLI/SLO requirements (coordination with Noa SRE)

Phase 2 adds production-traffic SLOs (since the wakir-Tomás-Container
is now load-bearing in shadow):

| SLI | Window | SLO | Owner |
|---|---|---|---|
| Output-reply timeliness (publish → reply on output subject) p99 | rolling 1h | ≤45s | Noa |
| Bridge-Forward fan-out drop-rate | rolling 24h | ≤0.1% | Noa |
| Doppelbetrieb-Score verdict drop-from-pass count | rolling 7d | 0 | Noa+Amara |
| V-907 pin-drift event count | rolling 28d | 0 | Noa+Selin |

Coordination note (vorläufig per P2): the SLO numbers above need
Noa-design-review. The p99 ≤ 45s number is derived from the
Phase-1b p95 ≤ 30s gate plus a defensive margin; Noa may tighten or
loosen based on Phase-1b telemetry.

## 4. Henrik-Audit-Punkte (Zone N)

Henrik's Audit-Sample for Phase 2 consumes everything from Phase-1b
plus:

* **E.** The weekly Doppelbetrieb-Score-Aggregate-Report (the
  4-axis verdict-rollup) — sampled weekly.
* **F.** The bridge-forward fan-out reconciliation report — sampled
  weekly.
* **G.** The Phase-2 → Phase-3 cutover-decision artefact (when it
  exists) — full audit, not sample, since this is an ADR-0058
  load-bearing decision.

Henrik does **not** consume:

* Live SLI dashboards (Noa-domain).
* Per-output Doppelbetrieb diffs (QA-domain, sample only).

## 5. Phase-2 → Phase-3 promotion criteria

Gate criteria (cumulative — all must hold):

1. All §1 Acceptance-Gates green for 6 consecutive weeks.
2. All §2 Coverage-Thresholds green at every CI-run.
3. All §3 SLOs honoured for 6 consecutive weeks.
4. Henrik-Audit for Phase 2 cleared (no ADR-0058 findings
   outstanding).
5. ADR-0058 §"Phase 4 Cutover-Entscheidung" decision-artefact
   approved by Aufsichtsrat (governance-decision, not QA-decision).

QA blocks the promotion if any of (1)–(3) fail. Governance blocks
the promotion if (4) or (5) fail.

— Amara
