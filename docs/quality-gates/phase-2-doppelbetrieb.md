# Quality-Gate — Phase 2 (Doppelbetrieb)

| Field | Value |
|---|---|
| Owner | QA engineering (QA), with Zone-N cross-check by internal audit |
| Status | Draft for Phase-1b → Phase-2 promotion |
| Phase | 2 — Doppelbetrieb (wakir-Container runs in parallel with the pre-framework agent; both produce engineering-output; Doppelbetrieb-Score-CLI is authoritative comparison) |
| Source | ADR-0058 (Pilot-Persona-Migrations-Plan) §"Phase 4 cutover-Entscheidung", Migration-Playbook §5 |
| Date approved | 2026-05-16 (draft pending Zone-N review and Engineering-Persona Zone-M concurrence) |

## 0. Phase contract

Phase 2 begins when Phase-1b has been stable for at least 7
consecutive days with all five Phase-1b acceptance-gates green and
internal audit's Audit-Sample for Phase-1b has cleared (no
ADR-0058-compliance findings outstanding).

In Phase 2 the wakir-Container is **load-bearing in shadow**:
it consumes the same auftraege as the pre-framework agent (via the
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
* **Owned-by:** infrastructure engineering + persona-engine engineering (substrate stability), QA engineering (gate
  enforcement).

### 2.2 Bridge-Forward fan-out is symmetric

* **Gate:** For every auftrag published on
  `wakir.<env>.agent.agent.task.assigned.tomas`, exactly one output
  lands on the pre-framework agent sink **and** one output lands on
  the wakir-Container sink. Drop-rate ≤ 0.1% over rolling 24h.
* **Evidence:** Bridge-Forward fan-out metrics; bridge-audit
  reconciliation report (spec §7).
* **Owned-by:** protocol engineering (schema) + persona-engine engineering (subscribe-loop) + SRE engineering
  (metric/alerting).
* **Test-Vector:** new vector to be added in Phase-2 sprint; not in
  scope for the QA increment.

### 2.3 Doppelbetrieb-Score four-axis verdict ≥ pass for 6 consecutive weeks

* **Gate:** Every 6h Doppelbetrieb-Score-CLI run produces
  `verdict == "pass"` with:
  * `functional_equivalence >= 0.95`
  * `byte_delta` ≤ documented per-output-class threshold
  * `structural_equivalence >= 0.90`
  * `spurious_divergence <= 5` per 100 outputs (per Doppelbetrieb-
    Score-CLI defaults)
* **Evidence:** 6h Score-JSON outputs aggregated into a weekly
  rollup (`wirelang doppelbetrieb-aggregate`).
* **Owned-by:** persona-engine engineering (CLI) + protocol engineering (schema).
* **Test-Vector:** existing `test_cli_doppelbetrieb_score.py` +
  `test_cli_doppelbetrieb_aggregate.py`. The 6-week threshold is
  a **runtime gate**, not a test-time gate — it lives in the
  weekly rollup-report internal audit samples.

### 2.4 No V-907 pin-drift events for 28 days

* **Gate:** Zero `PersonaHashDriftError` events emitted by
  `wakir-persona-tomas.service` over a rolling 28 days.
* **Evidence:** Bridge-audit `axis-a-pin` records all match the
  build-time pin; no `EXIT_V907_HASH_DRIFT` restarts.
* **Owned-by:** persona-engine engineering (engine) + internal audit (audit-sample).

### 2.5 Persona-state KV-bucket integrity

* **Gate:** The NATS-KV bucket `wakir-persona-state-acme-tomas`
  carries one and only one `active_log` entry per Container-spawn,
  and the entries are monotonic by `transition.utc`.
* **Evidence:** `wirelang persona-inspect --kv-roundtrip` returns
  clean over the rolling 28-day window.
* **Owned-by:** persona-engine engineering (engine state-backing).
* **Test-Vector:** existing
  `test_engine_natskv_active_log.py` covers the per-spawn invariant;
  rolling-window monotonicity is a **runtime gate** monitored by
  Alert.

## 2. Test-Coverage thresholds

Inherits all Phase-1b thresholds. Additional Phase-2-specific
thresholds:

| Component | Coverage threshold (line) | Coverage threshold (branch) | Source |
|---|---|---|---|
| `wirelang.cli.doppelbetrieb_aggregate` | 90% | 85% | persona-engine engineering |
| `wirelang.persona_engine.bridge_audit_writer` | 90% | 85% | persona-engine engineering |
| Bridge-forward fan-out logic (protocol engineering spec module) | 85% | 80% | protocol engineering |

## 3. SLI/SLO requirements (coordination with SRE engineering)

Phase 2 adds production-traffic SLOs (since the wakir-Container
is now load-bearing in shadow):

| SLI | Window | SLO | Owner |
|---|---|---|---|
| Output-reply timeliness (publish → reply on output subject) p99 | rolling 1h | ≤45s | SRE engineering |
| Bridge-Forward fan-out drop-rate | rolling 24h | ≤0.1% | SRE engineering |
| Doppelbetrieb-Score verdict drop-from-pass count | rolling 7d | 0 | SRE engineering + QA engineering |
| V-907 pin-drift event count | rolling 28d | 0 | SRE engineering + persona-engine engineering |

Coordination note (vorläufig per P2): the SLO numbers above need
an SRE design review. The p99 ≤ 45s number is derived from the
Phase-1b p95 ≤ 30s gate plus a defensive margin; SRE engineering may tighten or
loosen based on Phase-1b telemetry.

## 4. Audit-Punkte (Zone N)

internal audit's Audit-Sample for Phase 2 consumes everything from Phase-1b
plus:

* **E.** The weekly Doppelbetrieb-Score-Aggregate-Report (the
  4-axis verdict-rollup) — sampled weekly.
* **F.** The bridge-forward fan-out reconciliation report — sampled
  weekly.
* **G.** The Phase-2 → Phase-3 cutover-decision artefact (when it
  exists) — full audit, not sample, since this is an ADR-0058
  load-bearing decision.

internal audit does **not** consume:

* Live SLI dashboards (SRE domain).
* Per-output Doppelbetrieb diffs (QA-domain, sample only).

## 5. Phase-2 → Phase-3 promotion criteria

Gate criteria (cumulative — all must hold):

1. All §1 Acceptance-Gates green for 6 consecutive weeks.
2. All §2 Coverage-Thresholds green at every CI-run.
3. All §3 SLOs honoured for 6 consecutive weeks.
4. Audit for Phase 2 cleared (no ADR-0058 findings
   outstanding).
5. ADR-0058 §"Phase 4 cutover-Entscheidung" decision-artefact
   approved by external audit (governance-decision, not QA-decision).

QA blocks the promotion if any of (1)–(3) fail. Governance blocks
the promotion if (4) or (5) fail.
