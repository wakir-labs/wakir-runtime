# Phase-3c Pre-Cutover-Probe-Phase Live-Demo

**Script:** `scripts/phase-3c/pre-cutover-probe-phase-live-demo.py`
**Owner:** Reza Tehrani (Dev-Engineering-2)
**Tag:** Sprint-Tag-43, 2026-05-18
**Anchors:** ADR-0058 sec-Nachtrag, ADR-0065, ADR-0066, PR #267, PR #270, PR #272, PR #273, PR #275

## Purpose

A one-shot, stdlib-only local orchestrator that runs every Phase-3c
Welle pre-cutover probe (`scripts/phase-3c/welle-N-pre-cutover-probe.sh`,
N=1..7) in Sandbox-Stub-Mode, aggregates the seven verdicts into a
single Marathon-Readiness signal, optionally triggers the Tomas Tag-42
CI marathon-dashboard workflow, and emits both a JSON envelope and a
human-readable ASCII table for Mira-Inbox / Operator consumption.

This script is **complementary** to the CI dashboard:

* **CI Marathon-Dashboard** (PR #270) runs on schedule + on push and
  publishes a long-form GitHub Step-Summary artifact. It's the system
  of record for the Cutover-Day-Morning verdict.
* **Live-Demo (this script)** is the *human-loop rehearsal driver*:
  fires from any operator shell at any time, prints a stdout verdict
  immediately, and surfaces the *delta* between the empirically-known
  clean-main baseline and the current observation. Useful when a
  recent main-tip change might have regressed a probe.

## Sandbox-Stub-Mode

The script never opens a real SSH socket. For every Welle probe the
orchestrator:

* synthesises a per-run `HOME` directory containing a touched
  `.ssh/wakir-pilot-vm-diagnose` keyfile (so the probe's pre-condition
  check passes),
* sets `WAKIR_SSH_BIN=/usr/bin/true` (binary that consumes args and
  exits 0; prevents any accidental SSH attempt),
* invokes the probe with `--dry-run --quiet` so the probe exercises
  arg-parse, axis-dispatch, verdict-aggregation, and exit-code mapping
  *without* contacting the wakir-pilot VM,
* maps the probe's exit code (0/1/2/3/4) to a verdict
  (`GREEN`/`CAUTION`/`BLOCK`/`BLOCK`/`NOT-EXEC`) per the
  welle-N-pre-cutover-probe.sh contract.

This mirrors the CI dashboard's sandbox-stub setup verbatim
(`.github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml`),
ensuring the local demo verdict matches what CI emits for the same
probe set on the same snapshot.

## Empirical Demo Baseline (clean main, sandbox-stub)

On baseline `04fb3c3` (Tag-42 main-tip), the seven probes in dry-run
mode produce this verdict mix:

| W | KW | Component                | Verdict | Reason                                |
|---|----|--------------------------|---------|---------------------------------------|
| 1 | 24 | v907_verify              | CAUTION | AXIS-4 yellow without `--expected-hash` |
| 2 | 24 | svid_workload_identity   | CAUTION | AXIS-4 yellow without `--expected-hash` |
| 3 | 25 | bridge_audit_writer      | CAUTION | AXIS-4 yellow without `--expected-hash` |
| 4 | 26 | state_backing            | CAUTION | AXIS-4 yellow without `--pair-hash`     |
| 5 | 26 | lifecycle_state_machine  | CAUTION | AXIS-4 yellow without `--pair-hash`     |
| 6 | 27 | subscribe_loop           | GREEN   | all axes dry-run-clean                  |
| 7 | 27 | recovery_workflow        | BLOCK   | IIA-1130 pre-auditor-decision absent on main |

Aggregate marathon-readiness: **`BLOCK`** (Welle-7 BLOCK dominates).

This is the *expected* baseline encoded in `WELLE_CATALOGUE` and
`EXPECTED_AGGREGATE_BASELINE`; the Comparison-View renders every
observed-vs-expected delta so the operator can spot regressions.

### Path from baseline to Cutover-Day READY

Five steps separate the demo baseline from the Cutover-Day-Morning
READY verdict:

1. Operator supplies `--expected-hash <hex>` per Welle (1..5) so
   AXIS-4 strict equality passes; pin-pack hash is in
   `tooling/anchors/pre_cutover_pin_pack.json`.
2. Operator supplies `--pair-hash <hex>` for Welle-4/-5 doppel-welle
   AXIS-4 cross-modul parity.
3. State-engineer commits `state/welle-7-pre-auditor-decision.json`
   per IIA-1130 § Phase-3-Ende audit-gate (Henrik signs).
4. Live VM is reachable via `${HOME}/.ssh/wakir-pilot-vm-diagnose`
   (Mira-Hand-SSH per ADR-0058 sec-Nachtrag).
5. Probes run *without* `--dry-run` — i.e. against the real
   wakir-pilot VM, not sandbox-stub.

The Live-Demo addresses steps 1-2 by surfacing the per-Welle delta;
steps 3-5 are operator-hand on Cutover-Day-Morning.

## CLI

```text
python3 scripts/phase-3c/pre-cutover-probe-phase-live-demo.py \
    [--repo-root PATH] \
    [--output-json PATH] \
    [--output-md PATH] \
    [--mode {dry-run,sandbox-stub}] \
    [--gh-trigger | --no-gh-trigger] \
    [--gh-workflow phase-3c-pre-cutover-marathon-dashboard.yml] \
    [--gh-ref main] \
    [--gh-poll-seconds N] \
    [--probe-timeout-seconds 60.0] \
    [--component-overrides JSON] \
    [--quiet]
```

### Defaults

* `--repo-root`: current working directory.
* `--mode`: `sandbox-stub` (alias of `dry-run` for this demo).
* `--gh-trigger`: off (use `--gh-trigger` to fire CI).
* `--gh-workflow`: `phase-3c-pre-cutover-marathon-dashboard.yml`.
* `--gh-ref`: `main`.
* `--gh-poll-seconds`: 0 (do not poll after dispatch).
* `--probe-timeout-seconds`: 60.

### Exit codes

| Exit | Verdict     | Meaning                                          |
|------|-------------|--------------------------------------------------|
| 0    | READY       | All seven probes GREEN (operator-hand pin-packs supplied). |
| 1    | CAUTION     | 1..2 CAUTION/NOT-EXEC, zero BLOCK.               |
| 2    | BLOCK       | Any BLOCK, or 3+ degraded.                       |
| 3    | precond-fail| Repo / scripts / `bash` / `true` missing.        |
| 4    | NOT-READY   | All seven NOT-EXEC.                              |

The demo exit code reflects the **observed** aggregate, not the
expected baseline. Use the JSON envelope's `aggregate_match` field
to assert "observed == expected" in scripts that wrap this demo.

## JSON envelope schema (v1.0)

```json
{
  "schema_version": "1.0",
  "run_id": "pre-cutover-demo-20260518T190003Z",
  "started_at_utc": "2026-05-18T19:00:03Z",
  "finished_at_utc": "2026-05-18T19:00:03Z",
  "repo_root": "/var/home/fred/AI-Corp/.worktree-reza-tag43-probe-live-demo-runtime",
  "mode": "sandbox-stub",
  "expected_aggregate": "BLOCK",
  "observed_aggregate": "BLOCK",
  "aggregate_match": true,
  "summary_counts": {"GREEN": 1, "CAUTION": 5, "BLOCK": 1, "NOT-EXEC": 0},
  "probes": [
    {
      "welle": 1,
      "component": "v907_verify",
      "kw": 24,
      "pair_partner": 2,
      "pair_mode": "parallel",
      "probe_script": "scripts/phase-3c/welle-1-pre-cutover-probe.sh",
      "probe_present": true,
      "exit_code": 1,
      "verdict": "CAUTION",
      "verdict_source": "probe-exit-code",
      "expected_verdict": "CAUTION",
      "delta": "match",
      "duration_seconds": 0.038,
      "details": "exit=1 verdict-line=CAUTION expected_reason=AXIS-4 yellow without --expected-hash"
    }
    /* ... six more ... */
  ],
  "gh_trigger": {
    "attempted": false,
    "workflow": "phase-3c-pre-cutover-marathon-dashboard.yml",
    "ref": "main",
    "ok": false,
    "stdout": "",
    "stderr": "",
    "run_url": null,
    "run_status": null,
    "run_conclusion": null,
    "poll_seconds": 0
  }
}
```

## ASCII summary (Operator-Hand format)

The script prints (and optionally writes to `--output-md`) an
ASCII table covering:

* Run metadata (run_id, timestamps, repo_root, mode).
* Expected vs. observed aggregate + `aggregate_match`.
* Per-Welle observed/expected/delta row.
* Summary counts.
* Doppel-Welle coupling (ADR-0066) with `ALIGNED` / `DRIFT` flag.
* `gh-trigger` block (not-attempted, or run_url / run_status when
  triggered).

Example tail (clean baseline):

```text
Per-Welle Verdicts
------------------------------------------------------------------------
W  KW  Component                  Observed   Expected   Delta
------------------------------------------------------------------------
1  24  v907_verify                CAUTION    CAUTION    match
2  24  svid_workload_identity     CAUTION    CAUTION    match
3  25  bridge_audit_writer        CAUTION    CAUTION    match
4  26  state_backing              CAUTION    CAUTION    match
5  26  lifecycle_state_machine    CAUTION    CAUTION    match
6  27  subscribe_loop             GREEN      GREEN      match
7  27  recovery_workflow          BLOCK      BLOCK      match
------------------------------------------------------------------------

MARATHON-READINESS=BLOCK expected=BLOCK match=True
```

## Comparison-View semantics

* **`match`** -- observed verdict equals expected baseline.
* **`drift:<observed>-vs-<expected>`** -- observed differs from
  expected; surfaces probe-script regressions or environment-stub
  failures.
* **`absent`** -- probe script not present at the expected path; usually
  indicates the demo was run against a snapshot that pre-dates the
  Welle's probe-script land.

A `match` row on every Welle plus `aggregate_match=true` means the
probe phase is empirically intact on the current snapshot. Any
`drift:` row needs operator-hand triage before the Marathon-Dashboard
verdict is trustworthy.

## gh-trigger integration

When `--gh-trigger` is set, the script calls:

```bash
gh workflow run phase-3c-pre-cutover-marathon-dashboard.yml --ref main
```

If `--gh-poll-seconds N>0` is also set, the script polls
`gh run list --workflow ... --limit 1 --json url,status,conclusion`
in a loop for up to N seconds, surfacing the most-recent run's URL /
status / conclusion in the JSON envelope so the operator can paste it
into the inbox report.

Poll loop tolerates `gh` errors silently and returns whatever it
managed to collect within the budget. The trigger envelope is always
present in the output JSON (with `attempted=false` when
`--no-gh-trigger`) so downstream consumers can rely on a stable shape.

## Hermetic tests

`tests/scripts/test_pre_cutover_probe_phase_live_demo.py` (15 tests):

1. catalogue shape (7 unique welles, symmetric pair_partner).
2. EXIT_TO_VERDICT mirrors probe contract.
3. aggregate marathon-readiness rules (5 cases).
4. run_single_probe with absent script -> NOT-EXEC.
5. run_single_probe with fake exit-0 probe -> GREEN, match.
6. run_single_probe with fake exit-2 probe -> BLOCK, drift.
7. end-to-end execute_demo with synthetic 7-probe repo seeded to
   match the empirical baseline -> aggregate BLOCK + every delta
   match.
8. render_ascii_table content sanity (all components, sections,
   ALIGNED markers).
9. component-overrides parser rejects invalid JSON / array / out-of-
   range welle / empty component.
10. trigger_marathon_dashboard with non-existent gh binary -> ok=False,
    stderr populated.
11. trigger_marathon_dashboard with fake gh exit-0 -> ok=True.

All tests are hermetic: no real SSH, no real `gh`, no network.

## Operator-Hand runbook (Cutover-Day-Morning rehearsal)

```bash
# Step 1: from any operator shell on any host
cd <repo-root>
python3 scripts/phase-3c/pre-cutover-probe-phase-live-demo.py \
    --output-json /tmp/demo-verdict.json \
    --output-md   /tmp/demo-verdict.md

# Step 2: inspect the ASCII table on stdout -- aggregate should match
# the empirical baseline (BLOCK on clean main, READY post-pin-pack).

# Step 3: when satisfied, fire the CI dashboard too:
python3 scripts/phase-3c/pre-cutover-probe-phase-live-demo.py \
    --gh-trigger --gh-poll-seconds 120 \
    --output-json /tmp/demo-verdict-with-ci.json

# Step 4: paste the ASCII table into the Mira-Inbox liefer-bericht
# and link /tmp/demo-verdict.json as a forensic artifact.
```

## Cross-references

* `scripts/phase-3c/welle-1-pre-cutover-probe.sh` (and 2..7)
* `tooling/ci/aggregate_pre_cutover_marathon_dashboard.py`
* `tooling/ci/emit_marathon_probe_envelope.py`
* `.github/workflows/phase-3c-pre-cutover-marathon-dashboard.yml`
* `docs/phase-3c/marathon-aggregat-tracker.md`
* `docs/adr/ADR-0058-mira-hand-ssh-authority.md` (sec-Nachtrag)
* `docs/adr/ADR-0065-phase-3c-cutover-plan.md`
* `docs/adr/ADR-0066-doppel-welle-ordering.md`

-- Reza Tehrani
