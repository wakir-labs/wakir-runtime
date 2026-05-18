# Phase-3c Cross-Welle Cutover-Generalprobe Runbook

| Field | Value |
|---|---|
| Owner | Reza Tehrani (Dev-Engineering-2) |
| ADR | [0066](../../decisions/0066-phase-3c-beschleunigung-option-a-plus.md) |
| Script (Python) | [`scripts/phase-3c/cross-welle-cutover-generalprobe.py`](../../scripts/phase-3c/cross-welle-cutover-generalprobe.py) |
| Tests | [`tests/phase_3c/test_cross_welle_generalprobe.py`](../../tests/phase_3c/test_cross_welle_generalprobe.py) |
| Siblings | Welles 1..7 per-welle smokes under `scripts/phase-3c/welle-N-*-cutover-smoke.py` |
| Status | Tag-40 dress-rehearsal — required GREEN before KW-24 cutover-execution starts |

## Purpose

The **Cross-Welle Cutover-Generalprobe** is the marathon
dress-rehearsal that pins all seven ADR-0066 cutover-waves into
one operator-facing verdict before KW-24 execution starts.

Each per-welle smoke
(`scripts/phase-3c/welle-N-*-cutover-smoke.py`) hermetically verifies
its own wave (pre / post / rollback phases, A1..A5/A6/A7 + R1
asserts). Those seven smokes do **not** verify that the four-week
calendar holds together end-to-end. The generalprobe does: it
sequences all seven welle-smokes in ADR-0066 calendar-order,
aggregates their exit codes and assert-records into a single
**Marathon-Verdict**, and exits `0/1/2 = GREEN / CAUTION /
ROLLBACK_RECOMMENDED`. Cutover-Execution KW-24 does not start
without a GREEN generalprobe in CI.

The generalprobe is **not** the Pilot-VM live-bring-up.
The live-bring-up remains Operator-Hand and runs against the
Pilot-VM Quadlet defaults per the per-welle Operator-Cutover-Runbooks
under `docs/phase-3c/welle-N-*-runbook.md`.

## ADR-0066 calendar plan

The generalprobe schedules the seven welles into four
sub-sequences mirroring the ADR-0066 KW-24..KW-27 calendar:

| KW | Welles | Mode | Rationale |
|---|---|---|---|
| KW-24 | Welle-1 `v907_verify` + Welle-2 `svid_workload_identity` | parallel | Both are low-risk read-side flips; same calendar week, independent envelopes, no cross-modul drift between the pair. |
| KW-25 | Welle-3 `bridge_audit_writer` | solo | Write-side, single highest-risk wave; gets a full week to settle in production observability before the next pair flips. |
| KW-26 | Welle-4 `state_backing` + Welle-5 `lifecycle_state_machine` | parallel | Cross-modul drift verified by A7 asserts in welle-4 (against welle-5 FSM) and welle-5 (against welle-4 state-backing). |
| KW-27 | Welle-6 `subscribe_loop` + Welle-7 `recovery_workflow` | parallel | Closing pair; cross-modul drift verified by A7 asserts in welle-6 (against welle-7 recovery) and welle-7 (against welle-6 subscribe-loop). |

The plan is pinned in `PLAN: Tuple[SubSequence, ...]` in the
orchestrator module and asserted by the test suite. Any deviation
from this calendar breaks
`test_plan_constants_match_adr_0066_kw24_kw27`.

## Operator usage

```bash
# Full marathon — default boot count, all seven welles, exit 0=GREEN.
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \
    --out-dir out/generalprobe/ \
    --output out/generalprobe-marathon.json
echo "exit=$?"

# Plan-only — print the ADR-0066 sequence, no smoke invoked, exit 0.
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --dry-run

# Partial run: only KW-24 + KW-25 (welles 1..3).
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --up-to-welle 3

# Resume mid-marathon: welles 4..7 (KW-26 + KW-27).
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --from-welle 4

# Fast smoke for CI-only checks (2 boots per phase instead of default 8).
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \
    --smoke-arg=--boots-per-phase=2

# Force sequential execution (debugging stderr interleave).
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py --sequential
```

The orchestrator spawns each welle-smoke as a subprocess with
`PYTHONPATH` set to the repo-root so the smoke can import
`wirelang.persona_engine.rust_backend_switch`. It never touches
NATS, the Rust binary, or the Anthropic SDK — the smokes are
hermetic by construction and the orchestrator preserves that
hermeticity.

## Marathon-Verdict semantics

The generalprobe emits a single Marathon-Envelope (`schema:
wakir.phase-3c.cross-welle-generalprobe/1`) with three operator-
facing verdicts:

### 1. Marathon-Exit-Code (worst-band-wins)

```
marathon_exit_code = max(welle.exit_code for welle in dispatched)
marathon_band      = BAND_FOR_EXIT[marathon_exit_code]
```

- **0 / GREEN** — all dispatched welles exited 0. Cutover-Execution
  KW-24 may start.
- **1 / CAUTION** — at least one welle exited 1 (caution-severity
  assert failed: A3 latency tolerance or A4 decision-count drift).
  Operator investigates the failed welle's envelope; cutover-Execution
  may proceed if the investigation clears the drift, otherwise rolls
  back.
- **2 / ROLLBACK_RECOMMENDED** — at least one welle exited 2
  (blocker-severity assert failed: A1 backend-flip, A2 cross-lang
  parity-hash, A5 fallback-clean, R1 rollback-to-python, or any A6/A7
  blocker). Cutover-Execution does **not** start; the operator
  investigates the failing welle and re-runs the generalprobe after
  the fix.

Short-circuit: if a sub-sequence emits ROLLBACK, later sub-sequences
are **not** dispatched. The Marathon-Envelope records this in
`welle_results` (only the dispatched welles appear).

### 2. Cross-Welle-Drift-Aggregator

For each A1..A7 family present in at least one dispatched welle's
envelope, the aggregator records:

```json
{
  "passed_in":  [welle_ids],
  "failed_in":  [{"welle": id, "severity": "blocker|caution", "detail": "..."}],
  "skipped_in": [welle_ids where family is N/A],
  "family_verdict": "GREEN | AMBER | RED"
}
```

Per-family verdict:

- **GREEN** — all dispatched welles passed (or family is N/A for them).
- **AMBER** — at least one caution-severity fail, no blocker fails.
- **RED** — at least one blocker-severity fail.

The overall `cross_welle_drift.overall_drift_verdict` is the
worst family-verdict (RED > AMBER > GREEN). It is **orthogonal**
to the per-welle marathon exit-code: a welle can be CAUTION
(exit 1) but contribute to a family that is RED (blocker fail in
a different welle), which is the signal the marathon-verdict
catches that single-welle smokes cannot.

### 3. Pinned assert-family inventory

The aggregator knows which families are expected per welle. From
the Tag-40 walk-through of the live envelopes:

| Family | Severity | Welles |
|---|---|---|
| `A1_backend_flip` | blocker | 1..7 |
| `A2_cross_lang_parity_hash` | blocker | 1..7 |
| `A3_latency_within_tolerance` | caution | 1..7 |
| `A4_decision_count_in_place` | caution | 1..7 |
| `A5_fallback_clean` | blocker | 1..7 |
| `R1_rollback_to_python` | blocker | 1..7 |
| `A6_svid_fixture_parity` | caution | 2 |
| `A6_bridge_audit_stream_parity` | caution | 3 |
| `A6_cross_backend_read_compatibility` | caution | 4 |
| `A6_fsm_transition_integrity` | caution | 5 |
| `A6_subscribe_loop_lag_stability` | caution | 6 |
| `A6_recovery_r1_r4_drill` | caution | 7 |
| `A7_self_reference_trap_control` | caution | 3 |
| `A7_cross_modul_drift_welle_5_fsm` | caution | 4 |
| `A7_cross_modul_drift_welle_4_state_backing` | caution | 5 |
| `A7_cross_modul_drift_welle_7_recovery` | caution | 6 |
| `A7_cross_modul_drift_welle_6_subscribe_loop` | caution | 7 |

The A7 keys are deliberately welle-pair-specific so the operator can
read drift symmetry directly: a `A7_cross_modul_drift_welle_5_fsm`
fail (in welle-4) and a `A7_cross_modul_drift_welle_4_state_backing`
pass (in welle-5) tell two different stories about which side of the
parallel KW-26 pair leaked state.

## Output

By default the orchestrator writes:

- Per-welle envelopes — `<out-dir>/welle-N-envelope.json` (default
  `out/cross-welle-generalprobe/<unix-ts>/welle-N-envelope.json`).
- Marathon-Envelope — `--output PATH` (default: stdout).

The Marathon-Envelope shape (pinned by
`test_run_generalprobe_green_path_dispatches_all_welles`):

```json
{
  "schema": "wakir.phase-3c.cross-welle-generalprobe/1",
  "timestamp_utc": 1747584000,
  "dry_run": false,
  "plan": [
    {"kw_label": "KW-24", "welles": [1, 2], "mode": "parallel"},
    {"kw_label": "KW-25", "welles": [3], "mode": "solo"},
    {"kw_label": "KW-26", "welles": [4, 5], "mode": "parallel"},
    {"kw_label": "KW-27", "welles": [6, 7], "mode": "parallel"}
  ],
  "welle_results": [
    {
      "welle": 1,
      "focus_component": "v907_verify",
      "exit_code": 0,
      "band": "GREEN",
      "envelope_path": "out/cross-welle-generalprobe/1747584000/welle-1-envelope.json",
      "asserts_summary": {"total": 6, "passed": ["..."], "failed": []},
      "error": null
    }
    // ... welle-2 .. welle-7
  ],
  "marathon_exit_code": 0,
  "marathon_band": "GREEN",
  "cross_welle_drift": {
    "families": {
      "A1_backend_flip": {
        "passed_in": [1, 2, 3, 4, 5, 6, 7],
        "failed_in": [],
        "skipped_in": [],
        "family_verdict": "GREEN"
      }
      // ... all other A1..A7 families
    },
    "welles_dispatched": [1, 2, 3, 4, 5, 6, 7],
    "overall_drift_verdict": "GREEN"
  }
}
```

## CI integration

The generalprobe is wired into the `phase-3c-cross-welle-generalprobe`
required status check on the `wakir-runtime` repo. The check runs
in three modes:

1. **Smoke-PR-Check** — on every PR touching `scripts/phase-3c/**`,
   `wirelang/persona_engine/rust_backend_switch.py`, or
   `tests/phase_3c/**`: full marathon with `--smoke-arg=--boots-per-phase=2`
   (fast, ~30 s). Required GREEN.
2. **Main-Branch-Check** — on every push to `main`: full marathon
   with default `--boots-per-phase=8`. Required GREEN before the
   commit is considered cutover-ready.
3. **KW-24-Go-No-Go** — manual workflow_dispatch, full marathon
   with `--boots-per-phase=16` (high-confidence run). GREEN gate
   for the KW-24 cutover-execution PR.

The required-status-check name on the branch-protection rule is
exactly `phase-3c-cross-welle-generalprobe` (display-name of the
job, not the workflow). Per the high-tempo branch-protection
hygiene note from 2026-05-16, the check-names match must be
literal.

## Exit-code contract for shell gates

```bash
python3 scripts/phase-3c/cross-welle-cutover-generalprobe.py \
    --output out/marathon.json
case $? in
  0) echo "GREEN — cutover-execution may start" ;;
  1) echo "CAUTION — investigate failing welle envelope before proceeding" ;;
  2) echo "ROLLBACK_RECOMMENDED — do not start cutover; fix and re-run" ;;
  *) echo "UNKNOWN exit code — treat as ROLLBACK" ; exit 2 ;;
esac
```

## Hermeticity notes

- The orchestrator never mutates `os.environ`. Each subprocess is
  spawned with a freshly-built env-map derived from `os.environ`
  with `PYTHONPATH` prepended to the repo-root.
- The smokes themselves are hermetic: no NATS, no Rust binary, no
  Anthropic SDK. The orchestrator does not relax that contract.
- The test suite injects a deterministic `smoke_runner` seam so
  every test in `tests/phase_3c/test_cross_welle_generalprobe.py`
  runs without spawning a real subprocess. The default subprocess
  runner is exercised end-to-end only in the Smoke-PR-Check and
  Main-Branch-Check CI lanes.

## References

- ADR-0065 — Phase-3c cutover Python-default → Rust-default
- ADR-0066 — Phase-3c Beschleunigung Option-A-Plus (vier-Wochen-Marathon KW-24 → KW-27)
- Per-welle smoke runbooks: `docs/phase-3c/welle-N-cutover-smoke.md`
- Per-welle operator-cutover-runbooks:
  `docs/phase-3c/welle-N-*-runbook.md`
- Sibling probe (feasibility-only, no asserts):
  `scripts/phase-3c-cutover-dry-run.py`
